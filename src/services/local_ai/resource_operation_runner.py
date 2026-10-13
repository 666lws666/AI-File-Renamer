"""One bounded public-resource worker; real tails outlive logical completion.

The inference service and authority are borrowed, never replaced or shut down.
The composition owner separately drains that service's retained invocation owner.
"""
from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass, field
import math
from pathlib import Path
import re
from threading import Condition, Event, Thread, current_thread
import time
from uuid import uuid4

from src.core.processing_authority import ProcessingMode
from .inference_journal import InferenceRecoveryState, LocalInferenceJournal
from .inference_service import LocalServiceSnapshot
from .production_resources import (PRODUCT_CATALOG_ID, ProductionLocalResources,
                                   prepare_production_parents)
from .resource_catalog import RESOURCE_IDS, catalog_from_manifest
from .resource_manager import ResourceSnapshot, ResourceState
from .resource_store import StoreOwnershipUncertain
from .resource_transport import ResourceError


_KINDS = frozenset(('inspect', 'download', 'import', 'prepare', 'repair', 'cleanup'))
_CODES = frozenset(('CANCELLED', 'PAUSED', 'STALE_CONTEXT', 'CALLBACK_FAILED',
    'RECOVERY_REQUIRED', 'CLEANUP_PENDING', 'NATIVE_OWNERSHIP_UNCERTAIN', 'BUSY',
    'STORE_UNAVAILABLE', 'SOURCE_MISSING', 'INSUFFICIENT_SPACE', 'VERIFICATION_FAILED',
    'PREPARATION_FAILED', 'TRANSFER_FAILED', 'TIMEOUT', 'INVALID_RESPONSE',
    'RESOURCE_MISSING', 'RESOURCE_VERIFICATION_FAILED', 'LOCAL_INFERENCE_FAILED',
    'HOST_UNSUPPORTED', 'HOST_INPUT_INVALID', 'HOST_MEASUREMENT_FAILED',
    'LOCAL_MEMORY_LOW', 'LOCAL_DISK_LOW', 'NOT_READY', 'CLOSED'))


def safe_error(value, default='PREPARATION_FAILED'):
    return value if type(value) is str and value in _CODES else default


def _service_projection(snapshot):
    if snapshot is None: return None
    phases = ('NOT_READY', 'PREPARING', 'RUNNING', 'READY', 'RECOVERY_REQUIRED',
              'CLEANUP_PENDING', 'CLOSED')
    phase = snapshot.phase if type(snapshot.phase) is str and snapshot.phase in phases else 'NOT_READY'
    identity = snapshot.identity
    if type(identity) is not str or re.fullmatch('[0-9a-f]{64}', identity) is None:
        identity = None
    error = None if snapshot.error is None else safe_error(snapshot.error, 'LOCAL_INFERENCE_FAILED')
    waiting = snapshot.waiting_count
    if type(waiting) is not int or not 0 <= waiting <= 8: waiting = 0
    return LocalServiceSnapshot(phase, identity, error, waiting)


def valid_deadline(deadline):
    try:
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError()
    except (OverflowError, TypeError, ValueError):
        raise ValueError('RESOURCE_DRAIN_DEADLINE_ERROR') from None


def validate_composition(config, manager, service, trusted_anchor):
    """Pure catalog/path/object checks, no filesystem preparation or observation."""
    try:
        if type(config) is not ProductionLocalResources:
            raise ValueError()
        catalog = config.catalog
        manifest = {name: getattr(catalog, name) for name in ('model_id',
            'source_revision', 'quantization_repository', 'quantization_revision',
            'runtime_release', 'model_license', 'runtime_license', 'purpose')}
        manifest.update(schema_version=1, resources=[x.as_transport_dict() for x in catalog.resources])
        anchor = Path(trusted_anchor)
        base = config.state_root.parent
        if (catalog_from_manifest(manifest) != catalog or catalog.identity != PRODUCT_CATALOG_ID
                or catalog.purpose != 'managed-local-resources-v1'
                or catalog.runtime_release != 'b10885'
                or manager.catalog is not catalog or Path(manager.root) != config.resource_root
                or service._config.catalog is not catalog
                or service._config.resource_root != config.resource_root
                or service._config.runtime_root != config.runtime_root
                or service._config.state_root != config.state_root
                or not anchor.is_absolute() or anchor.parent == anchor
                or not base.is_relative_to(anchor)
                or config.resource_root != base / 'resources' / PRODUCT_CATALOG_ID
                or config.runtime_root != base / 'runtime' / PRODUCT_CATALOG_ID
                or config.state_root != base / 'state' or not config.bundled_runtime.is_absolute()):
            raise ValueError()
    except (AttributeError, TypeError, ValueError, ResourceError):
        raise ValueError('INVALID_RESOURCE_COMPOSITION') from None


@dataclass(frozen=True, slots=True)
class ResourceOperationRequest:
    operation_id: str
    session_id: str
    generation: int
    catalog_id: str
    kind: str
    choice_revision: int = 0
    consent: bool = False
    source_directory: str | None = field(default=None, repr=False)
    resource_id: str | None = None
    cancel_event: Event = field(default_factory=Event, repr=False, compare=False)
    pause_event: Event = field(default_factory=Event, repr=False, compare=False)
    cancelled: object = field(default=None, repr=False, compare=False)

    @classmethod
    def create(cls, **kwargs):
        return cls(operation_id=uuid4().hex, **kwargs)


@dataclass(frozen=True, slots=True)
class ResourceOperationProgress:
    request: ResourceOperationRequest
    state: ResourceState
    current_id: str
    transferred_bytes: int
    total_bytes: int
    verified_bytes: int = 0
    acquired_bytes: int = 0


@dataclass(frozen=True, slots=True)
class ResourceOperationResult:
    request: ResourceOperationRequest
    resources: ResourceSnapshot | None
    service: LocalServiceSnapshot | None
    recovery_state: InferenceRecoveryState | None
    error_code: str | None


class _Stopped(Exception):
    def __init__(self, code): self.code = code


class ResourceOperationRunner:
    def __init__(self, config, manager, service, *, authority, trusted_anchor,
                 journal=None, prepare_parents=prepare_production_parents,
                 completion_callback, progress_callback):
        validate_composition(config, manager, service, trusted_anchor)
        self.config, self.manager, self.service, self.authority = config, manager, service, authority
        self.trusted_anchor = Path(trusted_anchor)
        self.journal = journal if journal is not None else LocalInferenceJournal(config.state_root)
        self.prepare_parents = prepare_parents
        self.completion_callback, self.progress_callback = completion_callback, progress_callback
        self._condition = Condition()
        self._open = True
        self._worker = None
        self._active = None
        self._future = None
        self._pending = None
        self._acks = {}
        self._progress = None
        self._native = []
        self._callback_failed = False

    @property
    def worker(self): return self._worker

    @property
    def pending(self):
        with self._condition: return self._pending

    @property
    def active_future(self):
        with self._condition: return self._future

    @property
    def pending_ack_count(self):
        with self._condition: return len(self._acks)

    @property
    def retained_native_owners(self):
        with self._condition: return tuple(self._native)

    def is_current(self, request):
        snapshot = self.authority.snapshot()
        with self._condition:
            owned = request is self._active or request is self._pending
            opened = self._open
        return (opened and owned and request.catalog_id == self.config.catalog.identity
            and request.session_id == snapshot.session_id and request.generation == snapshot.generation
            and request.choice_revision == snapshot.revision
            and (request.kind == 'inspect' or snapshot.mode is ProcessingMode.LOCAL))

    def _valid(self, request):
        if (type(request) is not ResourceOperationRequest or type(request.kind) is not str
                or request.kind not in _KINDS
                or type(request.operation_id) is not str
                or re.fullmatch('[0-9a-f]{32}', request.operation_id) is None
                or type(request.generation) is not int or request.generation < 0
                or type(request.choice_revision) is not int or request.choice_revision < 0
                or type(request.cancel_event) is not Event or type(request.pause_event) is not Event
                or request.cancelled is not None and not callable(request.cancelled)):
            return False
        snapshot = self.authority.snapshot()
        if (request.catalog_id != self.config.catalog.identity or request.session_id != snapshot.session_id
                or request.generation != snapshot.generation
                or request.choice_revision != snapshot.revision
                or request.kind != 'inspect' and snapshot.mode is not ProcessingMode.LOCAL):
            return False
        if request.kind == 'download' and (type(request.consent) is not bool or request.consent is not True):
            return False
        if request.kind == 'repair' and (type(request.resource_id) is not str
                or request.resource_id not in RESOURCE_IDS):
            return False
        if request.kind == 'import' and (type(request.source_directory) is not str
                or not request.source_directory or len(request.source_directory) > 32760
                or '\0' in request.source_directory or not Path(request.source_directory).is_absolute()):
            return False
        return True

    def submit(self, request):
        if not self._valid(request): return False
        with self._condition:
            if not self._open or self._native or self._callback_failed: return False
            if self._active is not None: self._active.cancel_event.set()
            if self._pending is not None: self._pending.cancel_event.set()
            # Unstarted pending has neither Future nor queued delivery. Its
            # cancellation and owner removal are synchronous, not a phantom ack.
            self._pending = request
            if self._worker is None:
                self._worker = Thread(target=self._run, name='local-resource-worker', daemon=False)
                self._worker.start()
            self._condition.notify_all()
        return True

    def cancel(self, *, paused=False):
        with self._condition:
            # Delivery is still controllable after computation/worker retirement
            # and before the exact Qt acknowledgement, not just while active.
            requests = {id(r): r for r in (self._active, self._pending,
                *(pair[0] for pair in self._acks.values())) if r is not None}.values()
            for request in requests:
                (request.pause_event if paused else request.cancel_event).set()
            return bool(requests)

    def _check(self, request):
        if request.cancel_event.is_set(): raise _Stopped('CANCELLED')
        if request.pause_event.is_set(): raise _Stopped('PAUSED')
        try:
            if request.cancelled is not None and request.cancelled(): raise _Stopped('CANCELLED')
        except _Stopped: raise
        except BaseException: raise _Stopped('CALLBACK_FAILED') from None
        if not self.is_current(request): raise _Stopped('STALE_CONTEXT')

    def _notify_progress(self, request, identifier, count, total):
        if (type(identifier) is not str or identifier not in RESOURCE_IDS
                or type(count) is not int or type(total) is not int
                or count < 0 or total < 0 or count > total):
            raise _Stopped('CALLBACK_FAILED')
        spec = next(item for item in self.config.catalog.resources if item.id == identifier)
        if total != spec.bytes:
            raise _Stopped('CALLBACK_FAILED')
        state = ResourceState.DOWNLOADING if request.kind == 'download' else ResourceState.IMPORTING
        value = ResourceOperationProgress(request, state, identifier, count, total)
        with self._condition:
            notify = self._progress is None
            self._progress = value
        if notify: self.progress_callback()

    def take_progress(self):
        with self._condition:
            value, self._progress = self._progress, None
            self._condition.notify_all()
            return value

    def owns_result(self, request, result):
        with self._condition:
            pair = self._acks.get(id(request))
            return pair is not None and pair[0] is request and pair[1] is result

    def acknowledge(self, request, result):
        with self._condition:
            pair = self._acks.get(id(request))
            if pair is None or pair[0] is not request or pair[1] is not result: return False
            del self._acks[id(request)]
            self._condition.notify_all()
            return True

    def _execute(self, request):
        resources, service, recovery = None, None, None
        try:
            self._check(request)
            def cancelled():
                try: self._check(request); return False
                except _Stopped as exc:
                    if exc.code == 'CALLBACK_FAILED': raise exc
                    return True
            progress = lambda identifier, count, total: self._notify_progress(request, identifier, count, total)
            if request.kind == 'inspect':
                resources = self.manager.inspect(cancelled=cancelled)
                recovery = self.journal.inspect_recovery_state()
            elif request.kind == 'cleanup':
                service = self.service.retry_cleanup(deadline=time.monotonic()+30)
            elif request.kind == 'repair':
                resources = self.manager.repair_resource(request.resource_id)
            else:
                with self.prepare_parents(self.config, trusted_anchor=self.trusted_anchor,
                        for_readiness=True, cancelled=cancelled):
                    self._check(request)
                    if request.kind == 'download':
                        resources = self.manager.import_bundled_runtime(self.config.bundled_runtime,
                            cancelled=cancelled, progress=progress)
                        self._check(request)
                        if resources.state is ResourceState.ERROR: raise _Stopped(safe_error(resources.error_code))
                        resources = self.manager.download(consent=True, cancelled=cancelled,
                            paused=request.pause_event.is_set, progress=progress)
                    elif request.kind == 'import':
                        resources = self.manager.import_offline(Path(request.source_directory),
                            cancelled=cancelled, paused=request.pause_event.is_set, progress=progress)
                    if resources is not None and resources.state in (ResourceState.ERROR,
                            ResourceState.PAUSED, ResourceState.CANCELLED):
                        raise _Stopped(safe_error(resources.error_code))
                    self._check(request)
                    resources = self.manager.inspect(cancelled=cancelled)
                    self._check(request)
                    if resources.state is not ResourceState.AVAILABLE:
                        raise _Stopped(safe_error(resources.error_code, 'RESOURCE_MISSING'))
                    recovery = self.journal.inspect_recovery_state()
                    if recovery is InferenceRecoveryState.RECOVERY_REQUIRED:
                        raise _Stopped('RECOVERY_REQUIRED')
                    self._check(request)
                    # Fresh monotonic readiness budget includes the service's
                    # ten-second cleanup reserve; transfer time cannot expire it.
                    service = self.service.check_ready(cancelled=cancelled,
                        deadline=time.monotonic()+900, is_current=lambda:self.is_current(request))
            self._check(request)
            service = _service_projection(service)
            code = service.error if service is not None else None
            if code is None and resources is not None and resources.error_code:
                code = safe_error(resources.error_code)
            return ResourceOperationResult(request, resources, service, recovery, code)
        except StoreOwnershipUncertain as exc:
            with self._condition:
                if not any(owner is exc.retained_owner for owner in self._native):
                    self._native.append(exc.retained_owner)
            code = 'NATIVE_OWNERSHIP_UNCERTAIN'
        except _Stopped as exc: code = exc.code
        except BaseException as exc:
            code = safe_error(getattr(exc, 'code', None))
        # The accepted manager snapshot is a bounded in-memory observation,
        # never another scan or a transfer callback's high-water projection.
        if resources is None:
            resources = self.manager.snapshot()
        return ResourceOperationResult(request, resources, _service_projection(service), recovery, code)

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda:not self._open or self._pending is not None and not self._acks)
                if not self._open and self._pending is None: return
                request, self._pending = self._pending, None
                self._active = request
                self._future = Future()
                future = self._future
                future.set_running_or_notify_cancel()
            result = self._execute(request)
            with self._condition: self._acks[id(request)] = (request, result)
            # Future.done is deliberately not the lifetime boundary: its own
            # synchronous callbacks and the public callback still own this lane.
            try:
                future.set_result(result)
                self.completion_callback(request, result)
            except BaseException:
                with self._condition: self._callback_failed = True
            finally:
                with self._condition:
                    self._active, self._future = None, None
                    self._condition.notify_all()

    def begin_close(self):
        with self._condition:
            self._open = False
            if self._active is not None: self._active.cancel_event.set()
            if self._pending is not None:
                self._pending.cancel_event.set()
                self._pending = None
            self._condition.notify_all()

    def drain_owned_operations(self, *, deadline):
        """Permanently seal and prove only our actual retained owners drained.

        The borrowed service is deliberately neither shut down nor certified:
        its owner must perform that later, after this lane is genuinely idle.
        """
        valid_deadline(deadline)
        self.begin_close()
        worker = self._worker
        if worker is current_thread(): return False
        if worker is not None: worker.join(max(0.0, deadline-time.monotonic()))
        with self._condition:
            owners = tuple(self._native)
            tails = bool(self._active or self._acks or self._progress or self._callback_failed)
        # Never call cleanup/free on ambiguous owners. Only readonly proof that
        # the exact retained capability has genuinely become idle permits drain.
        try: native_idle = all(owner.idle is True for owner in owners)
        except BaseException: native_idle = False
        return not tails and native_idle and (worker is None or not worker.is_alive())

    def close(self, *, deadline):
        owned_idle = self.drain_owned_operations(deadline=deadline)
        try:
            service = self.service.snapshot()
            service_idle = (service.phase in ('NOT_READY', 'READY', 'CLOSED')
                            and service.waiting_count == 0)
        except BaseException: service_idle = False
        return owned_idle and service_idle

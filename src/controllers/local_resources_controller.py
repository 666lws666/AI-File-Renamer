"""Qt-owned explicit resource actions, sharing the existing processing choice."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from PySide6.QtCore import QCoreApplication, QObject, Property, QThread, Qt, Signal, Slot

from src.core.processing_authority import LocalReadiness, ProcessingMode
from src.services.local_ai.resource_catalog import RESOURCE_IDS
from src.services.local_ai.resource_manager import ResourceState
from src.services.local_ai.resource_operation_runner import (
    ResourceOperationRequest, ResourceOperationRunner, safe_error, valid_deadline,
)
from src.services.local_ai.production_resources import prepare_production_parents


@dataclass(frozen=True, slots=True)
class _PreparationProjection:
    session_id: str
    generation: int
    revision: int
    catalog_id: str


class LocalResourcesController(QObject):
    stateChanged = Signal()
    _completed = Signal(object, object)
    _progressReady = Signal()

    def __init__(self, coordinator, config, manager, service, *, trusted_anchor,
                 journal=None, prepare_parents=prepare_production_parents,
                 runner_factory=ResourceOperationRunner, parent=None):
        super().__init__(parent)
        self._require_owner()
        if coordinator.thread() != self.thread():
            raise ValueError('INVALID_RESOURCE_COMPOSITION')
        self.coordinator, self.config = coordinator, config
        self._open, self._closing = True, False
        self._current = None
        self._preparation_projection = self._current_projection = None
        self._admitting, self._emitting = 0, 0
        self._admission_serial = 0
        self._phase, self._resource_state, self._error = 'NOT_READY', 'missing', ''
        self._operation_id, self._current_id, self._recovery = '', '', 'missing'
        self._verified, self._acquired, self._remaining = 0, 0, config.catalog.total_bytes
        self._completed.connect(self._consume_completion, Qt.ConnectionType.QueuedConnection)
        self._progressReady.connect(self._consume_progress, Qt.ConnectionType.QueuedConnection)
        self.runner = runner_factory(config, manager, service, authority=coordinator.authority,
            trusted_anchor=trusted_anchor, journal=journal, prepare_parents=prepare_parents,
            completion_callback=self._post_completion, progress_callback=self._post_progress)
        coordinator.stateChanged.connect(self._authority_changed)

    def _require_owner(self):
        if QThread.currentThread() != self.thread():
            raise RuntimeError('RESOURCE_OWNER_THREAD_REQUIRED')

    def _emit_state(self):
        self._emitting += 1
        try: self.stateChanged.emit()
        finally: self._emitting -= 1

    def _local_action_allowed(self):
        return self._open and self.coordinator.is_open and self.coordinator.snapshot.mode is ProcessingMode.LOCAL

    @Property(str, notify=stateChanged)
    def phase(self): return self._phase

    @Property(str, notify=stateChanged)
    def resourceState(self): return self._resource_state

    @Property(str, notify=stateChanged)
    def errorCode(self): return self._error

    @Property(str, notify=stateChanged)
    def operationId(self): return self._operation_id

    @Property(bool, notify=stateChanged)
    def busy(self): return self._current is not None

    @Property(bool, notify=stateChanged)
    def canPause(self):
        return self._open and self._current is not None and self._current.kind in ('download', 'import')

    @Property('qlonglong', notify=stateChanged)
    def verifiedBytes(self): return self._verified

    @Property('qlonglong', notify=stateChanged)
    def acquiredBytes(self): return self._acquired

    @Property('qlonglong', notify=stateChanged)
    def remainingTransferBytes(self): return self._remaining

    @Property('qlonglong', notify=stateChanged)
    def totalBytes(self): return self.config.catalog.total_bytes

    @Property(str, notify=stateChanged)
    def currentResourceId(self): return self._current_id

    @Property(str, notify=stateChanged)
    def resourceRoot(self): return str(self.config.resource_root)

    @Property(str, notify=stateChanged)
    def modelName(self): return self.config.catalog.model_id

    @Property(str, notify=stateChanged)
    def runtimeVersion(self): return self.config.catalog.runtime_release

    @Property(str, notify=stateChanged)
    def recoveryState(self): return self._recovery

    @Property(bool, notify=stateChanged)
    def canPrepare(self): return self._local_action_allowed()

    @Property(bool, notify=stateChanged)
    def canDownload(self): return self._local_action_allowed()

    @Property(bool, notify=stateChanged)
    def canImport(self): return self._local_action_allowed()

    @Property(bool, notify=stateChanged)
    def canRetryCleanup(self):
        return self._local_action_allowed() and self._phase == 'CLEANUP_PENDING'

    def _admit(self, kind, **inputs):
        self._require_owner()
        if not self._open or not self.coordinator.is_open: return False
        before = self.coordinator.snapshot
        if kind != 'inspect' and before.mode is not ProcessingMode.LOCAL: return False
        self._admission_serial += 1
        serial = self._admission_serial
        self._admitting += 1
        try:
            projection = None
            if kind in ('download', 'import', 'prepare', 'repair'):
                expected = before.generation + int(before.engine_fingerprint is not None
                    or before.local_readiness is LocalReadiness.READY)
                projection = _PreparationProjection(before.session_id, expected,
                    before.revision, self.config.catalog.identity)
                # Install before synchronous public callbacks: a nested inspect
                # can inherit this projection even before outer admission.
                self._preparation_projection = projection
                if not self.coordinator.publish_local_state(before.generation, LocalReadiness.PREPARING):
                    self._retire_preparation(projection)
                    return False
                after = self.coordinator.snapshot
                if (not self._open or not self.coordinator.is_open
                        or serial != self._admission_serial
                        or after.session_id != before.session_id or after.generation != expected
                        or after.revision != before.revision
                        or after.mode is not ProcessingMode.LOCAL
                        or after.local_readiness is not LocalReadiness.PREPARING):
                    # Nested admission owns its inherited/replacement token.
                    if serial == self._admission_serial:
                        self._retire_preparation(projection)
                    return False
            else:
                after = before
                if kind == 'inspect': projection = self._preparation_projection
            request = ResourceOperationRequest.create(session_id=after.session_id,
                generation=after.generation, choice_revision=after.revision,
                catalog_id=self.config.catalog.identity, kind=kind, **inputs)
            if not self.runner.submit(request):
                if kind != 'inspect': self._retire_preparation(projection)
                return False
            self._current = request
            self._current_projection = projection
            self._operation_id, self._error, self._current_id = request.operation_id, '', ''
            self._phase = 'PREPARING' if kind in ('download', 'import', 'prepare', 'repair') else 'VERIFYING'
            self._emit_state()
            return True
        finally: self._admitting -= 1

    @Slot(result=bool)
    def inspect(self): return self._admit('inspect')

    # QVariant preserves the original QML type: a bool slot would coerce 1 or
    # "true" to True before the explicit-consent check could see the input.
    @Slot('QVariant', result=bool)
    def downloadAndEnable(self, consent):
        self._require_owner()
        if type(consent) is not bool or consent is not True: return False
        return self._admit('download', consent=True)

    @Slot(str, result=bool)
    def importAndEnable(self, source_directory):
        self._require_owner()
        from pathlib import Path
        if (type(source_directory) is not str or not source_directory
                or len(source_directory) > 32760 or '\0' in source_directory
                or not Path(source_directory).is_absolute()): return False
        return self._admit('import', source_directory=source_directory)

    @Slot(result=bool)
    def prepareExisting(self): return self._admit('prepare')

    @Slot(result=bool)
    def pause(self):
        self._require_owner()
        if not self.canPause: return False
        return self.runner.cancel(paused=True)

    @Slot(result=bool)
    def cancel(self):
        self._require_owner()
        if not self._open or self._current is None: return False
        return self.runner.cancel()

    @Slot(str, result=bool)
    def repairResource(self, resource_id):
        self._require_owner()
        if type(resource_id) is not str or resource_id not in RESOURCE_IDS: return False
        return self._admit('repair', resource_id=resource_id)

    @Slot(result=bool)
    def retryCleanup(self):
        self._require_owner()
        if not self.canRetryCleanup: return False
        return self._admit('cleanup')

    def _authority_changed(self):
        self._require_owner()
        request = self._current
        if request is not None:
            snapshot = self.coordinator.snapshot
            if (not self.coordinator.is_open or snapshot.session_id != request.session_id
                    or snapshot.generation != request.generation
                    or snapshot.revision != request.choice_revision
                    or request.kind != 'inspect' and snapshot.mode is not ProcessingMode.LOCAL):
                self.runner.cancel()
        self._emit_state()

    def _post_completion(self, request, result): self._completed.emit(request, result)
    def _post_progress(self): self._progressReady.emit()

    @Slot()
    def _consume_progress(self):
        self._require_owner()
        progress = self.runner.take_progress()
        if progress is None or progress.request is not self._current or not self._open: return
        self._resource_state = progress.state.value
        self._current_id = progress.current_id
        self._phase = 'TRANSFERRING'
        # Transferred high-water marks are advisory, not durable acquired bytes.
        self._emit_state()

    def _current_result(self, request, result):
        snapshot = self.coordinator.snapshot
        return (self._open and self.coordinator.is_open and self._current is request
            and result.request is request and request.catalog_id == self.config.catalog.identity
            and request.session_id == snapshot.session_id and request.generation == snapshot.generation
            and request.choice_revision == snapshot.revision
            and (request.kind == 'inspect' or snapshot.mode is ProcessingMode.LOCAL))

    def _retire_preparation(self, projection, state=LocalReadiness.CANCELLED):
        if projection is None or self._preparation_projection is not projection: return
        self._preparation_projection = None
        snapshot = self.coordinator.snapshot
        # Same-choice invalidation (e.g. catalog publication) can advance the
        # generation without retiring PREPARING. Never touch a newer choice or
        # a replacement operation's token, nor standalone genuine READY.
        if (self._open and self.coordinator.is_open
                and snapshot.session_id == projection.session_id
                and snapshot.revision == projection.revision
                and snapshot.generation >= projection.generation
                and self.config.catalog.identity == projection.catalog_id
                and snapshot.mode is ProcessingMode.LOCAL
                and snapshot.local_readiness is LocalReadiness.PREPARING):
            self.coordinator.publish_local_state(snapshot.generation, state)

    @Slot(object, object)
    def _consume_completion(self, request, result):
        self._require_owner()
        if not self.runner.owns_result(request, result): return
        try:
            current = self._current_result(request, result)
            if self._current is not request: return
            # Retire only this logical operation before any public callback.
            # The runner's exact result/Future/callback/ack owners remain alive.
            self._current = None
            projection, self._current_projection = self._current_projection, None
            if not current:
                self._phase, self._error = 'CANCELLED', 'STALE_CONTEXT'
                self._retire_preparation(projection)
                self._emit_state()
                return
            resources = result.resources
            if resources is not None and resources.catalog_id == self.config.catalog.identity:
                self._resource_state = resources.state.value
                self._verified, self._acquired, self._remaining = (
                    resources.verified_bytes, resources.acquired_bytes, resources.remaining_bytes)
                self._current_id = resources.current_id if resources.current_id in RESOURCE_IDS else ''
            if result.recovery_state is not None: self._recovery = result.recovery_state.value
            self._error = safe_error(result.error_code) if result.error_code else ''
            # Controls accepted while a real Future/public/Qt tail was held
            # fence publication, while keeping the computed resource truth.
            if self._error not in ('CLEANUP_PENDING', 'RECOVERY_REQUIRED', 'NATIVE_OWNERSHIP_UNCERTAIN'):
                if request.cancel_event.is_set(): self._error = 'CANCELLED'
                elif request.pause_event.is_set(): self._error = 'PAUSED'
            service = result.service
            ready = (request.kind in ('download', 'import', 'prepare') and not self._error
                and service is not None and service.phase == 'READY' and service.error is None
                and type(service.identity) is str and re.fullmatch('[0-9a-f]{64}', service.identity) is not None)
            if ready:
                self._phase = 'READY'
                if self._preparation_projection is projection: self._preparation_projection = None
                self.coordinator.publish_local_state(request.generation, LocalReadiness.READY,
                    engine_fingerprint=service.identity)
            elif request.kind in ('download', 'import', 'prepare'):
                if not self._error: self._error = 'NOT_READY'
                self._phase = (self._error if self._error in ('RECOVERY_REQUIRED', 'CLEANUP_PENDING',
                    'CANCELLED', 'PAUSED') else 'FAILED')
                state = LocalReadiness.CANCELLED if self._error in ('CANCELLED', 'PAUSED', 'STALE_CONTEXT') else LocalReadiness.FAILED
                if self._preparation_projection is projection: self._preparation_projection = None
                self.coordinator.publish_local_state(request.generation, state)
            else:
                cleanup_phase = service.phase if request.kind == 'cleanup' and service is not None else None
                if cleanup_phase in ('CLEANUP_PENDING', 'RECOVERY_REQUIRED'):
                    self._phase = self._error = cleanup_phase
                else:
                    self._phase = (self._error if self._error in ('CANCELLED','PAUSED') else 'FAILED') if self._error else (
                    'AVAILABLE' if self._resource_state == ResourceState.AVAILABLE.value else 'NOT_READY')
                if request.kind == 'repair':
                    state = LocalReadiness.FAILED if self._error else LocalReadiness.NOT_READY
                    self._retire_preparation(projection, state)
                elif request.kind == 'cleanup':
                    self.coordinator.publish_local_state(request.generation,
                        LocalReadiness.FAILED if self._error else LocalReadiness.NOT_READY)
                elif request.kind == 'inspect': self._retire_preparation(projection)
            self._emit_state()
        finally: self.runner.acknowledge(request, result)

    def begin_close(self):
        self._require_owner()
        if not self._open: return
        self._open = False
        self.runner.begin_close()
        # Closing retires admission/logical ownership, never actual worker,
        # Future, native or already-posted Qt acknowledgement ownership.
        self._current = None
        self._current_projection = self._preparation_projection = None
        self._emit_state()

    def _drain(self, *, deadline, full_close):
        self._require_owner()
        valid_deadline(deadline)
        if self._closing: return False
        self._closing = True
        try:
            self.begin_close()
            if self._emitting or self._admitting: return False
            while True:
                if time.monotonic() < deadline:
                    # No lock held across arbitrary Qt/user callbacks.
                    QCoreApplication.processEvents()
                drain = self.runner.close if full_close else self.runner.drain_owned_operations
                done = drain(deadline=min(deadline, time.monotonic()+.01))
                if done and self._current is None: return True
                if time.monotonic() >= deadline: return False
        finally: self._closing = False

    def drain_owned_operations(self, *, deadline):
        return self._drain(deadline=deadline, full_close=False)

    def close(self, *, deadline):
        return self._drain(deadline=deadline, full_close=True)

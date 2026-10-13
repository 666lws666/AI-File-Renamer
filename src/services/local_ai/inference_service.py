"""One-slot, fail-closed orchestration for prepared local naming inference.

Construction and import are inert.  Native work is reachable only through the
fixed attestation, private-stage and zero-capability AppContainer sequence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import math
import ntpath
from pathlib import Path
import secrets
import threading
import time
from types import SimpleNamespace

from .host_capacity import HostCapacityError, measure_host_capacity, require_host_capacity
from .inference_launch import RECIPE_VERSION, build_launch, discover_windows_paths
from .inference_owner import InvocationOwner
from .inference_request import (LocalInferenceResult, LocalNamingRequest,
                                LocalRequestError, decode_prepared_response,
                                prepare_request)
from .native.exemptions import OwnedLoopbackExemptionQuery
from .native.model_stage import StageBytesMember, StageError, stage_model_bundle
from .native.profile import OwnedAppContainerProfile
from .native.security import AppContainerSecurity, TokenEvidence
from .resource_catalog import ResourceCatalog


_MAX_SECONDS = 900.0
_CLEANUP_RESERVE = 10.0
_MAX_WAITERS = 8
_MAX_STAGE_MEMBERS = 80
_MAX_STAGE_BYTES = 5 * 1024**3
_SELF_CHECK_TEXT = "Campus network maintenance"


class _Failure(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _cleanup_phase(error) -> str:
    return "RECOVERY_REQUIRED" if error == "RECOVERY_REQUIRED" else "CLEANUP_PENDING"


@dataclass(frozen=True, slots=True)
class LocalInferenceConfig:
    resource_root: Path = field(repr=False)
    runtime_root: Path = field(repr=False)
    state_root: Path = field(repr=False)
    catalog: ResourceCatalog


@dataclass(frozen=True, slots=True)
class LocalServiceSnapshot:
    phase: str
    identity: str | None
    error: str | None
    waiting_count: int


def _production_dependencies():
    def journal_factory(root):
        from .inference_journal import LocalInferenceJournal
        return LocalInferenceJournal(root)

    def attest_resources(*args, **kwargs):
        from .inference_resources import attest_resources as attest
        return attest(*args, **kwargs)

    def run_bounded(*args, **kwargs):
        from .native.process import run_bounded as run
        return run(*args, **kwargs)

    return SimpleNamespace(
        clock=time.monotonic,
        journal_factory=journal_factory,
        discover_windows_paths=discover_windows_paths,
        attest_resources=attest_resources,
        profile_factory=OwnedAppContainerProfile,
        measure_host_capacity=measure_host_capacity,
        require_host_capacity=require_host_capacity,
        stage_model_bundle=stage_model_bundle,
        exemption_factory=OwnedLoopbackExemptionQuery,
        security_factory=AppContainerSecurity,
        build_launch=build_launch,
        run_bounded=run_bounded,
    )


def _canonical_identity(payload: dict) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def _resource_identity(attested, naming_mode: str, protocol_version: str) -> str:
    return _canonical_identity({
        "catalog": attested.catalog_id,
        "public_resources": attested.identity,
        "protocol": protocol_version,
        "recipe": RECIPE_VERSION,
        "context": 8192,
        "output": 1024,
        "cpu_threads": 4,
        "naming_mode": naming_mode,
    })


def _readiness_anchor(attested, catalog: ResourceCatalog) -> str:
    model_names = {item.filename for item in catalog.resources
                   if item.id in ("model-q4", "vision-f16")}
    runtime = [{"name": item.name, "size": item.size, "sha256": item.sha256}
               for item in attested.members if item.name not in model_names]
    return _canonical_identity({"catalog": catalog.identity, "recipe": RECIPE_VERSION,
                                "runtime": runtime})


def _validate_stage(evidence, public, private):
    expected = {item.name: (item.size, item.sha256) for item in public}
    expected.update({item.name: (len(item.data), sha256(item.data).hexdigest())
                     for item in private})
    try:
        members = evidence.members
        if (type(members) is not tuple or len(members) != len(expected)
                or not evidence.directory_path or type(evidence.directory_id) is not tuple
                or len(evidence.directory_id) != 2
                or not ntpath.basename(evidence.directory_path).startswith("stage_")):
            raise ValueError()
        seen = set()
        for member in members:
            if (member.name in seen or member.name not in expected
                    or (member.size, member.sha256) != expected[member.name]):
                raise ValueError()
            seen.add(member.name)
        if seen != set(expected):
            raise ValueError()
    except (AttributeError, TypeError, ValueError):
        raise _Failure("STAGE_VERIFICATION_FAILED") from None


class _Cancellation:
    def __init__(self, service, cancelled, is_current, work_deadline):
        self.service = service
        self.cancelled = cancelled
        self.is_current = is_current
        self.work_deadline = work_deadline
        self.failure = None

    def check(self):
        # Once a native boundary has observed cancellation, preserve that reason
        # even if the caller's flags recover before control returns here.
        if self.failure is not None:
            raise _Failure(self.failure)
        if self.service._shutdown.is_set():
            self.failure = "CANCELLED"
            raise _Failure(self.failure)
        try:
            if self.cancelled():
                self.failure = "CANCELLED"
                raise _Failure(self.failure)
            if not self.is_current():
                self.failure = "STALE_CONTEXT"
                raise _Failure(self.failure)
        except _Failure:
            raise
        except BaseException:
            self.failure = "CALLBACK_FAILED"
            raise _Failure(self.failure) from None
        if self.service._deps.clock() >= self.work_deadline:
            self.failure = "TIMEOUT"
            raise _Failure(self.failure)

    def is_set(self):
        try:
            self.check()
            return False
        except _Failure as error:
            self.failure = error.code
            return True


class LocalInferenceService:
    def __init__(self, config: LocalInferenceConfig, *, _dependencies=None):
        if type(config) is not LocalInferenceConfig:
            raise TypeError("INVALID_CONFIG")
        self._config = config
        self._deps = _production_dependencies() if _dependencies is None else _dependencies
        self._operation = threading.Lock()
        self._state = threading.Lock()
        self._shutdown = threading.Event()
        self._phase = "NOT_READY"
        self._identity = None
        self._error = None
        self._waiting = 0
        self._journal_context = None
        self._journal = None
        self._owner = None

    def snapshot(self) -> LocalServiceSnapshot:
        with self._state:
            return LocalServiceSnapshot(self._phase, self._identity, self._error,
                                        self._waiting)

    def _publish(self, phase, error=None, identity=None):
        with self._state:
            self._phase = phase
            self._error = error
            self._identity = identity
        return self.snapshot()

    def _deadline(self, value):
        try:
            valid = type(value) in (int, float) and math.isfinite(value)
            now = self._deps.clock()
            if valid:
                valid = value > now
        except (OverflowError, ValueError, TypeError):
            valid = False
            now = self._deps.clock()
        if not valid:
            raise _Failure("INVALID_DEADLINE")
        return min(float(value), now + _MAX_SECONDS)

    def _acquire(self, deadline, cancelled, is_current):
        with self._state:
            if self._waiting >= _MAX_WAITERS:
                raise _Failure("BUSY")
            self._waiting += 1
        try:
            while True:
                if self._shutdown.is_set():
                    raise _Failure("CLOSED")
                try:
                    if cancelled():
                        raise _Failure("CANCELLED")
                    if not is_current():
                        raise _Failure("STALE_CONTEXT")
                except _Failure:
                    raise
                except BaseException:
                    raise _Failure("CALLBACK_FAILED") from None
                remaining = deadline - self._deps.clock()
                if remaining <= 0:
                    raise _Failure("TIMEOUT")
                if self._operation.acquire(timeout=min(.05, remaining)):
                    return
        finally:
            with self._state:
                self._waiting -= 1

    def _ensure_journal(self):
        if self._journal is not None:
            return
        journal = self._deps.journal_factory(self._config.state_root)
        context = journal.lease()
        try:
            leased = context.__enter__()
        except BaseException:
            self._publish("RECOVERY_REQUIRED", "RECOVERY_REQUIRED")
            raise
        self._journal_context = context
        self._journal = leased

    def _invoke(self, prepared, *, cancelled, deadline, is_current, self_check=False):
        # These modules bind native APIs at import and belong to operations,
        # never cloud-only service import or construction.
        from .inference_journal import InferenceJournalError, InferenceRecoveryRequired
        from .native.process import ProcessOwnershipInterrupted, ProcessResult
        from .resource_store import StoreBusy
        from .resource_transport import ResourceCancelled, ResourceError
        started = self._deps.clock()
        work_deadline = deadline - _CLEANUP_RESERVE
        if work_deadline <= started:
            return LocalInferenceResult(False, None, "TIMEOUT", None, 0.0)
        cancellation = _Cancellation(self, cancelled, is_current, work_deadline)
        owner = None
        fields = None
        engine_identity = None
        error = None
        interrupted = None
        try:
            cancellation.check()
            self._ensure_journal()
            cancellation.check()
            if self._config.catalog.runtime_release != "b10885":
                raise _Failure("UNSUPPORTED_RUNTIME")
            windows_paths = self._deps.discover_windows_paths()
            cancellation.check()
            include_vision = self_check or bool(prepared.visual_names)
            owner = InvocationOwner(_clock=self._deps.clock)
            self._owner = owner
            context = self._deps.attest_resources(
                self._config.resource_root, self._config.runtime_root,
                self._config.catalog, include_vision=include_vision,
                cancelled=cancellation.is_set, deadline=work_deadline)
            owner.resource_context = context
            try:
                attested = context.__enter__()
            except BaseException as exc:
                # A generator that failed during __enter__ cannot be re-entered
                # to prove that a failed partial unwind released every pin.
                if isinstance(exc, (ResourceCancelled, StoreBusy)) or (
                        isinstance(exc, ResourceError) and exc.code in (
                            "RESOURCE_MISSING", "RESOURCE_TIMEOUT",
                            "RESOURCE_VERIFICATION_FAILED", "INVALID_INFERENCE_RESOURCES",
                            "INVALID_RUNTIME_INVENTORY")):
                    owner.resource_context = None
                    raise
                owner.recovery_required = True
                if not isinstance(exc, Exception):
                    raise
                raise _Failure("RECOVERY_REQUIRED") from None
            if (attested.catalog_id != self._config.catalog.identity
                    or attested.runtime_release != "b10885"):
                raise _Failure("RESOURCE_VERIFICATION_FAILED")
            anchor = _readiness_anchor(attested, self._config.catalog)
            if not self_check and anchor != self._identity:
                raise _Failure("RESOURCE_VERIFICATION_FAILED")
            engine_identity = _resource_identity(attested, prepared.naming_mode,
                                                 prepared.protocol_version)
            projector_name = attested.projector_name if prepared.visual_names else None
            public = tuple(item for item in attested.members
                           if item.name != attested.projector_name or projector_name)
            private = prepared.members
            stage_bytes = sum(item.size for item in public) + sum(len(item.data) for item in private)
            if len(public) + len(private) > _MAX_STAGE_MEMBERS or stage_bytes > _MAX_STAGE_BYTES:
                raise _Failure("STAGE_BOUNDS")
            cancellation.check()
            name = "xuxia_local_" + secrets.token_hex(16)
            profile = self._deps.profile_factory(name)
            owner.profile = profile
            prepared_profile = profile.prepare()
            if prepared_profile.name != name:
                raise _Failure("PROFILE_FAILED")
            sid = prepared_profile.sid
            cancellation.check()
            record = self._journal.begin(catalog_id=self._config.catalog.identity,
                                         profile_name=name, package_sid=sid)
            owner.journal = self._journal
            owner.run_id = record.run_id
            cancellation.check()
            capacity = self._deps.measure_host_capacity(self._config.state_root)
            self._deps.require_host_capacity(capacity, staging_bytes=stage_bytes)
            cancellation.check()
            entrypoint = "llama-mtmd-cli.exe" if prepared.visual_names else "llama-completion.exe"
            try:
                owner.stage = self._deps.stage_model_bundle(
                    str(self._config.state_root), sid, public + private, entrypoint,
                    cancelled=cancellation.is_set)
            except StageError as exc:
                if exc.owner is not None:
                    owner.stage = exc.owner
                raise
            evidence = owner.stage.recheck()
            _validate_stage(evidence, public, private)
            cancellation.check()
            self._journal.attach_stage(owner.run_id,
                name=ntpath.basename(evidence.directory_path), identity=evidence.directory_id)
            cancellation.check()
            exemption = self._deps.exemption_factory(sid)
            owner.exemption = exemption
            query = exemption.query()
            if (query.package_sid != sid or query.exempt is not False
                    or query.cleanup_complete is not True):
                raise _Failure("EXEMPTION_FAILED")
            cancellation.check()
            exemption.require_not_exempt()
            cancellation.check()
            if profile.__enter__() is not profile or getattr(profile, "sid", sid) != sid:
                raise _Failure("PROFILE_FAILED")
            cancellation.check()
            security = self._deps.security_factory(sid)
            owner.security = security
            if security.__enter__() is not security:
                raise _Failure("CONTAINMENT_FAILED")
            if type(security) is AppContainerSecurity and security.capabilities.CapabilityCount != 0:
                raise _Failure("CONTAINMENT_FAILED")
            cancellation.check()
            evidence = owner.stage.recheck()
            _validate_stage(evidence, public, private)
            cancellation.check()
            launch = self._deps.build_launch(evidence, model_name=attested.model_name,
                projector_name=projector_name, visual_names=prepared.visual_names,
                windows_paths=windows_paths)
            cancellation.check()
            capacity = self._deps.measure_host_capacity(self._config.state_root)
            self._deps.require_host_capacity(capacity, staging_bytes=0)
            cancellation.check()
            self._publish("RUNNING", None, self._identity)
            owner.child_cleanup_confirmed = False
            remaining_work = work_deadline - self._deps.clock()
            if remaining_work <= 0:
                owner.child_cleanup_confirmed = True
                raise _Failure("TIMEOUT")
            result = self._deps.run_bounded(
                launch.executable, launch.arguments, cwd=launch.cwd,
                environment=launch.environment, timeout_seconds=remaining_work,
                cancellation_event=cancellation, stdout_limit=262144,
                stderr_limit=1048576,
                cleanup_timeout_seconds=min(3.0, max(0.001, deadline - self._deps.clock())),
                security_context=security)
            if type(result) is not ProcessResult:
                raise _Failure("ENGINE_FAILED")
            owner.process = result.pending_owner
            owner.child_cleanup_confirmed = result.cleanup_complete is True and owner.process is None
            if not owner.child_cleanup_confirmed:
                if owner.process is None:
                    owner.recovery_required = True
                raise _Failure("CLEANUP_PENDING")
            # Cancellation/deadline may have fired inside the runner.  Its
            # prelaunch cancelled result has no child token to verify, and a
            # transient caller flag may already have recovered by this point.
            cancellation.check()
            if result.status == "cancelled":
                raise _Failure(cancellation.failure or "CANCELLED")
            if result.status == "timeout":
                raise _Failure(cancellation.failure or "TIMEOUT")
            token = result.token_evidence
            if (type(token) is not TokenEvidence or token.package_sid != sid
                    or token.is_appcontainer is not True
                    or type(token.capability_count) is not int or token.capability_count != 0):
                raise _Failure("TOKEN_VERIFICATION_FAILED")
            if result.status != "completed" or result.exit_code != 0:
                raise _Failure("ENGINE_FAILED")
            if type(result.stdout) is not bytes or len(result.stdout) > 262144:
                raise _Failure("INVALID_RESPONSE")
            cancellation.check()
            fields = decode_prepared_response(prepared, result.stdout)
            if self_check:
                engine_identity = anchor
        except ProcessOwnershipInterrupted as exc:
            if owner is not None:
                owner.process = exc.pending_owner
                owner.child_cleanup_confirmed = False
            interrupted = exc
        except BaseException as exc:
            if not isinstance(exc, Exception):
                interrupted = exc
            elif isinstance(exc, (_Failure, LocalRequestError, HostCapacityError)):
                error = exc.code
            elif isinstance(exc, ResourceCancelled):
                error = cancellation.failure or "CANCELLED"
            elif isinstance(exc, StoreBusy):
                error = "BUSY"
            elif isinstance(exc, ResourceError):
                if cancellation.failure is not None:
                    error = cancellation.failure
                elif (exc.code == "RESOURCE_TIMEOUT"
                      or (exc.code == "INVALID_INFERENCE_RESOURCES"
                          and self._deps.clock() >= work_deadline)):
                    error = "TIMEOUT"
                else:
                    error = exc.code if exc.code in (
                        "RESOURCE_MISSING", "RESOURCE_VERIFICATION_FAILED",
                        "INVALID_INFERENCE_RESOURCES", "INVALID_RUNTIME_INVENTORY"
                    ) else "RESOURCE_FAILED"
            elif isinstance(exc, (InferenceRecoveryRequired, InferenceJournalError)):
                error = "RECOVERY_REQUIRED"
            elif isinstance(exc, StageError):
                error = (cancellation.failure or "CANCELLED") if exc.stage == "cancelled" else "STAGE_FAILED"
            else:
                error = "LOCAL_INFERENCE_FAILED"
            if owner is not None and not owner.child_cleanup_confirmed and owner.process is None:
                owner.recovery_required = True
        if owner is not None:
            try:
                cleanup = owner.cleanup(deadline=deadline)
            except BaseException as exc:
                self._owner = owner
                self._publish("RECOVERY_REQUIRED", "RECOVERY_REQUIRED")
                if interrupted is not None:
                    raise interrupted
                raise
            if not cleanup.complete:
                self._owner = owner
                phase = _cleanup_phase(cleanup.error)
                self._publish(phase, cleanup.error)
                if interrupted is not None:
                    raise interrupted
                return LocalInferenceResult(False, None, cleanup.error, engine_identity,
                                            self._deps.clock() - started)
            self._owner = None
        if interrupted is not None:
            raise interrupted
        if error == "RECOVERY_REQUIRED":
            self._publish("RECOVERY_REQUIRED", error)
        try:
            if self._shutdown.is_set():
                raise _Failure("CANCELLED")
            if cancelled():
                raise _Failure("CANCELLED")
            if not is_current():
                raise _Failure("STALE_CONTEXT")
            if self._deps.clock() >= deadline:
                raise _Failure("TIMEOUT")
        except _Failure as exc:
            error = exc.code
        except BaseException:
            error = "CALLBACK_FAILED"
        return LocalInferenceResult(error is None, fields if error is None else None,
                                    error, engine_identity, self._deps.clock() - started)

    def check_ready(self, *, cancelled=lambda: False, deadline: float,
                    is_current=lambda: True) -> LocalServiceSnapshot:
        try:
            limit = self._deadline(deadline)
            self._acquire(limit, cancelled, is_current)
        except _Failure as exc:
            snap = self.snapshot()
            return LocalServiceSnapshot(snap.phase, snap.identity, exc.code, snap.waiting_count)
        try:
            snap = self.snapshot()
            if snap.phase in ("CLOSED", "RECOVERY_REQUIRED", "CLEANUP_PENDING"):
                return snap
            self._publish("PREPARING")
            request = LocalNamingRequest(_SELF_CHECK_TEXT, (), "en-US", "smart")
            result = self._invoke(prepare_request(request), cancelled=cancelled,
                                  deadline=limit, is_current=is_current, self_check=True)
            if self.snapshot().phase in ("CLEANUP_PENDING", "RECOVERY_REQUIRED"):
                return self.snapshot()
            if result.success:
                return self._publish("READY", None, result.engine_identity)
            return self._publish("NOT_READY", result.error)
        finally:
            self._operation.release()

    def infer(self, request: LocalNamingRequest, *, cancelled=lambda: False,
              deadline: float, is_current=lambda: True) -> LocalInferenceResult:
        started = self._deps.clock()
        try:
            limit = self._deadline(deadline)
            prepared = prepare_request(request)
            snap = self.snapshot()
            if snap.phase not in ("READY", "RUNNING"):
                code = snap.phase if snap.phase in ("CLOSED", "CLEANUP_PENDING", "RECOVERY_REQUIRED") else "NOT_READY"
                raise _Failure(code)
            self._acquire(limit, cancelled, is_current)
        except (_Failure, LocalRequestError) as exc:
            return LocalInferenceResult(False, None, exc.code, None,
                                        self._deps.clock() - started)
        try:
            snap = self.snapshot()
            if snap.phase != "READY" or self._owner is not None:
                code = snap.phase if snap.phase in ("CLOSED", "CLEANUP_PENDING", "RECOVERY_REQUIRED") else "NOT_READY"
                return LocalInferenceResult(False, None, code, None,
                                            self._deps.clock() - started)
            result = self._invoke(prepared, cancelled=cancelled, deadline=limit,
                                  is_current=is_current)
            snap = self.snapshot()
            if snap.phase not in ("CLEANUP_PENDING", "RECOVERY_REQUIRED"):
                retain_ready = result.success or result.error in (
                    "INVALID_REQUEST", "INSUFFICIENT_CONTENT", "CANCELLED",
                    "STALE_CONTEXT", "TIMEOUT", "CALLBACK_FAILED")
                self._publish("READY" if retain_ready else "NOT_READY",
                              None if result.success else result.error,
                              snap.identity if retain_ready else None)
            return result
        finally:
            self._operation.release()

    def retry_cleanup(self, *, deadline: float) -> LocalServiceSnapshot:
        try:
            limit = self._deadline(deadline)
        except _Failure as exc:
            snap = self.snapshot()
            return LocalServiceSnapshot(snap.phase, snap.identity, exc.code, snap.waiting_count)
        if not self._operation.acquire(timeout=max(0.0, limit - self._deps.clock())):
            snap = self.snapshot()
            return LocalServiceSnapshot(snap.phase, snap.identity, "BUSY", snap.waiting_count)
        try:
            if self._owner is None:
                return self.snapshot()
            result = self._owner.cleanup(deadline=limit)
            if result.complete:
                self._owner = None
                return self._publish("NOT_READY")
            phase = _cleanup_phase(result.error)
            return self._publish(phase, result.error)
        finally:
            self._operation.release()

    def shutdown(self, *, deadline: float) -> LocalServiceSnapshot:
        try:
            limit = self._deadline(deadline)
        except _Failure as exc:
            snap = self.snapshot()
            return LocalServiceSnapshot(snap.phase, snap.identity, exc.code, snap.waiting_count)
        self._shutdown.set()
        if not self._operation.acquire(timeout=max(0.0, limit - self._deps.clock())):
            snap = self.snapshot()
            return LocalServiceSnapshot(snap.phase, snap.identity, "CLEANUP_PENDING", snap.waiting_count)
        try:
            if self.snapshot().phase == "RECOVERY_REQUIRED" and self._owner is None:
                return self.snapshot()
            if self._owner is not None:
                result = self._owner.cleanup(deadline=limit)
                if not result.complete:
                    phase = _cleanup_phase(result.error)
                    return self._publish(phase, result.error)
                self._owner = None
            if self._journal_context is not None:
                try:
                    self._journal_context.__exit__(None, None, None)
                except BaseException:
                    return self._publish("RECOVERY_REQUIRED", "RECOVERY_REQUIRED")
                self._journal_context = None
                self._journal = None
            return self._publish("CLOSED")
        finally:
            self._operation.release()

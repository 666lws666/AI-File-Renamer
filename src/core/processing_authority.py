"""Process-local processing authority; no persistence or transport execution.

A commitment authorizes exactly one already-running transport attempt, not a
packet cutoff. Selecting LOCAL invalidates work without waiting for that attempt.
Only a managed runtime coordinator may report verified LOCAL readiness.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from threading import Event, Lock
from uuid import uuid4
from weakref import ref


class ProcessingMode(str, Enum):
    CLOUD = "cloud"
    LOCAL = "local"


class LocalReadiness(str, Enum):
    NOT_READY = "not_ready"
    PREPARING = "preparing"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PersistenceStatus(str, Enum):
    PENDING = "pending"
    SAVED = "saved"
    ERROR = "error"


class ProcessingStateError(ValueError):
    code = "PROCESSING_STATE_ERROR"

    def __init__(self):
        super().__init__(self.code)


class ProcessingSuperseded(ProcessingStateError):
    code = "PROCESSING_SUPERSEDED"


class CloudDispatchBlocked(ProcessingStateError):
    code = "CLOUD_DISPATCH_BLOCKED"


class LocalProcessingUnavailable(ProcessingStateError):
    code = "LOCAL_PROCESSING_UNAVAILABLE"


@dataclass(frozen=True)
class ProcessingSnapshot:
    session_id: str
    generation: int
    mode: ProcessingMode
    revision: int
    local_readiness: LocalReadiness
    persistence_status: PersistenceStatus
    engine_fingerprint: str | None
    committed_attempts: int
    error_code: str | None


@dataclass(frozen=True)
class WorkContext:
    snapshot: ProcessingSnapshot
    task_attempt_id: str = field(repr=False)
    generation_cancel_event: Event = field(repr=False)
    task_cancel_event: Event | None = field(default=None, repr=False)
    _state: _WorkState | None = field(default=None, init=False, repr=False, compare=False)

    @property
    def session_id(self) -> str:
        return self.snapshot.session_id

    @property
    def generation(self) -> int:
        return self.snapshot.generation

    @property
    def mode(self) -> ProcessingMode:
        return self.snapshot.mode

    @property
    def engine_fingerprint(self) -> str | None:
        return self.snapshot.engine_fingerprint


@dataclass(frozen=True)
class CloudProbeContext:
    """Fixed connection probe provenance, never business-content authority."""

    session_id: str
    generation: int
    candidate_fingerprint: str = field(repr=False)
    candidate_model: str = field(repr=False)
    request_id: str = field(repr=False)
    generation_cancel_event: Event = field(repr=False)
    task_cancel_event: Event | None = field(default=None, repr=False)
    _state: _WorkState | None = field(default=None, init=False, repr=False, compare=False)


@dataclass(frozen=True)
class ChoiceIntent:
    session_id: str
    revision: int
    mode: ProcessingMode


@dataclass(frozen=True)
class TransitionReceipt:
    snapshot: ProcessingSnapshot
    intent: ChoiceIntent

    @property
    def committed_attempts(self) -> int:
        return self.snapshot.committed_attempts


@dataclass(frozen=True)
class _AttemptReceipt:
    _owner: object = field(repr=False)


class _WorkState:
    """Context-owned ledger and identity seal; never retains its context."""

    def __init__(self, owner: object, context: WorkContext | CloudProbeContext):
        self.owner = owner
        self.context = ref(context)
        self.attempted_ids: set[str] = set()


_MAX_REVISION = 2**63 - 1
_FINGERPRINT = re.compile(r"[0-9a-f]{64}")


def _validate_fingerprint(value: str) -> None:
    if type(value) is not str or _FINGERPRINT.fullmatch(value) is None:
        raise ProcessingStateError()


def _validate_identifier(value: str) -> None:
    if type(value) is not str or not value or len(value) > 128:
        raise ProcessingStateError()


class ProcessingAuthority:
    """Single-lock authority with only bounded in-memory critical sections.

    Public values are immutable provenance, not bearer permits. Exact issued
    object identity is checked for contexts, choice completion and receipts.
    This is an application concurrency boundary, not a Python sandbox against
    code deliberately modifying private attributes.
    """

    def __init__(self, *, initial_mode: ProcessingMode,
                 initial_revision: int = 0, startup_error: bool = False):
        if (type(initial_mode) is not ProcessingMode
                or type(initial_revision) is not int
                or not 0 <= initial_revision <= _MAX_REVISION
                or type(startup_error) is not bool):
            raise ProcessingStateError()
        self._lock = Lock()
        self._owner = object()
        self._session_id = uuid4().hex
        self._generation = 0
        self._revision = initial_revision
        self._mode = ProcessingMode.LOCAL if startup_error else initial_mode
        self._local_readiness = LocalReadiness.NOT_READY
        self._cloud_fingerprint: str | None = None
        self._local_fingerprint: str | None = None
        self._generation_cancel_event = Event()
        self._startup_error = startup_error
        self._persistence_status = PersistenceStatus.ERROR if startup_error else PersistenceStatus.SAVED
        self._latest_intent: ChoiceIntent | None = None
        self._outstanding: dict[int, _AttemptReceipt] = {}
        self._admission_closed = False

    def _engine_locked(self) -> str | None:
        return (self._cloud_fingerprint if self._mode is ProcessingMode.CLOUD
                else self._local_fingerprint)

    def _snapshot_locked(self) -> ProcessingSnapshot:
        error = ("PROCESSING_STARTUP_ERROR" if self._startup_error else
                 "PROCESSING_PERSISTENCE_ERROR" if self._persistence_status is PersistenceStatus.ERROR
                 else None)
        return ProcessingSnapshot(self._session_id, self._generation, self._mode,
            self._revision, self._local_readiness, self._persistence_status,
            self._engine_locked(), len(self._outstanding), error)

    def _advance_generation_locked(self) -> None:
        Event.set(self._generation_cancel_event)
        self._generation_cancel_event = Event()
        self._generation += 1

    def _new_intent_locked(self, mode: ProcessingMode) -> ChoiceIntent:
        if self._revision >= _MAX_REVISION:
            raise ProcessingStateError()
        self._revision += 1
        intent = ChoiceIntent(self._session_id, self._revision, mode)
        self._latest_intent = intent
        self._persistence_status = PersistenceStatus.PENDING
        return intent

    def snapshot(self) -> ProcessingSnapshot:
        with self._lock:
            return self._snapshot_locked()

    def invalidate_work(self) -> ProcessingSnapshot:
        """Cancel current admissions without changing selection or readiness."""
        with self._lock:
            self._advance_generation_locked()
            return self._snapshot_locked()

    def close_admission(self) -> ProcessingSnapshot:
        """One-way lifetime fence; committed receipts remain owned and finishable."""
        with self._lock:
            if not self._admission_closed:
                self._admission_closed = True
                self._latest_intent = None
                self._advance_generation_locked()
                Event.set(self._generation_cancel_event)
            return self._snapshot_locked()

    def unbind_cloud_engine(self) -> ProcessingSnapshot:
        """Remove unavailable cloud inputs without selecting a different mode."""
        with self._lock:
            if self._cloud_fingerprint is not None:
                self._cloud_fingerprint = None
                self._advance_generation_locked()
            return self._snapshot_locked()

    def select_local(self) -> TransitionReceipt:
        with self._lock:
            if self._admission_closed:
                raise ProcessingSuperseded()
            if self._mode is not ProcessingMode.LOCAL:
                self._local_readiness = LocalReadiness.NOT_READY
                self._local_fingerprint = None
            self._mode = ProcessingMode.LOCAL
            self._advance_generation_locked()
            self._latest_intent = None
            # Even an exhausted durable revision cannot prevent immediate
            # closure. Never recycle its number or leave a CLOUD retry valid.
            if self._revision >= _MAX_REVISION:
                self._persistence_status = PersistenceStatus.ERROR
                raise ProcessingStateError()
            intent = self._new_intent_locked(ProcessingMode.LOCAL)
            return TransitionReceipt(self._snapshot_locked(), intent)

    def request_cloud_choice(self) -> ChoiceIntent:
        with self._lock:
            if self._admission_closed:
                raise ProcessingSuperseded()
            intent = self._new_intent_locked(ProcessingMode.CLOUD)
            if self._mode is ProcessingMode.CLOUD:
                # A repeat explicit choice must be acknowledged before any new
                # dispatch. Revoke old work now; success must never revive it.
                self._advance_generation_locked()
            return intent

    def _cloud_admission_locked(self) -> bool:
        return (not self._admission_closed and self._mode is ProcessingMode.CLOUD and not self._startup_error
                and self._persistence_status is PersistenceStatus.SAVED)

    def is_current_choice(self, intent: ChoiceIntent) -> bool:
        """Authenticate a pending/failed choice without consuming its retry."""
        if type(intent) is not ChoiceIntent:
            return False
        with self._lock:
            return intent is self._latest_intent

    def complete_choice(self, intent: ChoiceIntent, *, persisted: bool) -> bool:
        if type(persisted) is not bool:
            raise ProcessingStateError()
        if type(intent) is not ChoiceIntent:
            return False
        with self._lock:
            if self._admission_closed or intent is not self._latest_intent:
                return False
            # Persistence-only retries may complete the same latest failed
            # intent. Success consumes it so late failures cannot regress it.
            if persisted:
                self._latest_intent = None
            self._persistence_status = PersistenceStatus.SAVED if persisted else PersistenceStatus.ERROR
            if persisted and intent.mode is ProcessingMode.CLOUD:
                self._startup_error = False
                if self._mode is not ProcessingMode.CLOUD:
                    self._mode = ProcessingMode.CLOUD
                    self._advance_generation_locked()
            return True

    def bind_cloud_engine(self, fingerprint: str) -> ProcessingSnapshot:
        _validate_fingerprint(fingerprint)
        with self._lock:
            if fingerprint != self._cloud_fingerprint:
                self._cloud_fingerprint = fingerprint
                if self._mode is ProcessingMode.CLOUD:
                    self._advance_generation_locked()
            return self._snapshot_locked()

    def set_local_state(self, expected_generation: int, state: LocalReadiness,
                        *, engine_fingerprint: str | None = None) -> bool:
        if (type(expected_generation) is not int or expected_generation < 0
                or type(state) is not LocalReadiness):
            raise ProcessingStateError()
        if state is LocalReadiness.READY or engine_fingerprint is not None:
            _validate_fingerprint(engine_fingerprint)
        fingerprint = engine_fingerprint if state is LocalReadiness.READY else None
        with self._lock:
            if self._admission_closed or expected_generation != self._generation:
                return False
            if self._mode is ProcessingMode.LOCAL and (
                    fingerprint != self._local_fingerprint
                    or (self._local_readiness is LocalReadiness.READY and state is not LocalReadiness.READY)):
                self._advance_generation_locked()
            self._local_readiness = state
            self._local_fingerprint = fingerprint
            return True

    def capture_work(self, *, engine_fingerprint: str, task_attempt_id: str,
                     task_cancel_event: Event | None = None) -> WorkContext:
        _validate_fingerprint(engine_fingerprint)
        _validate_identifier(task_attempt_id)
        if task_cancel_event is not None and type(task_cancel_event) is not Event:
            raise ProcessingStateError()
        with self._lock:
            if (self._admission_closed or Event.is_set(self._generation_cancel_event)
                    or (task_cancel_event is not None and Event.is_set(task_cancel_event))):
                raise ProcessingSuperseded()
            if self._mode is ProcessingMode.LOCAL:
                if (self._local_readiness is not LocalReadiness.READY
                        or engine_fingerprint != self._local_fingerprint):
                    raise LocalProcessingUnavailable()
            elif not self._cloud_admission_locked() or engine_fingerprint != self._cloud_fingerprint:
                raise CloudDispatchBlocked()
            context = WorkContext(self._snapshot_locked(), task_attempt_id,
                                  self._generation_cancel_event, task_cancel_event)
            object.__setattr__(context, "_state", _WorkState(self._owner, context))
            return context

    def _current_locked(self, context: WorkContext) -> bool:
        if type(context) is not WorkContext:
            return False
        state = context._state
        if (type(state) is not _WorkState or state.owner is not self._owner
                or state.context() is not context):
            return False
        return (not self._admission_closed and context.session_id == self._session_id
                and context.generation == self._generation
                and context.mode is self._mode
                and context.engine_fingerprint == self._engine_locked()
                and context.generation_cancel_event is self._generation_cancel_event
                and not Event.is_set(context.generation_cancel_event)
                and (context.task_cancel_event is None or not Event.is_set(context.task_cancel_event))
                and (self._mode is not ProcessingMode.LOCAL
                     or self._local_readiness is LocalReadiness.READY)
                and (self._mode is not ProcessingMode.CLOUD
                     or self._cloud_admission_locked()))

    def capture_cloud_probe(self, *, candidate_fingerprint: str, candidate_model: str,
                            request_id: str, task_cancel_event: Event | None = None
                            ) -> CloudProbeContext:
        _validate_fingerprint(candidate_fingerprint)
        _validate_identifier(candidate_model)
        _validate_identifier(request_id)
        if task_cancel_event is not None and type(task_cancel_event) is not Event:
            raise ProcessingStateError()
        with self._lock:
            if (self._admission_closed or Event.is_set(self._generation_cancel_event)
                    or (task_cancel_event is not None and Event.is_set(task_cancel_event))):
                raise ProcessingSuperseded()
            if not self._cloud_admission_locked():
                raise CloudDispatchBlocked()
            context = CloudProbeContext(self._session_id, self._generation,
                candidate_fingerprint, candidate_model, request_id,
                self._generation_cancel_event, task_cancel_event)
            object.__setattr__(context, "_state", _WorkState(self._owner, context))
            return context

    def _current_cloud_probe_locked(self, context: CloudProbeContext) -> bool:
        if type(context) is not CloudProbeContext:
            return False
        state = context._state
        if (type(state) is not _WorkState or state.owner is not self._owner
                or state.context() is not context):
            return False
        return (self._cloud_admission_locked()
                and context.session_id == self._session_id
                and context.generation == self._generation
                and context.generation_cancel_event is self._generation_cancel_event
                and not Event.is_set(context.generation_cancel_event)
                and (context.task_cancel_event is None or not Event.is_set(context.task_cancel_event)))

    def is_current_cloud_probe(self, context: CloudProbeContext) -> bool:
        with self._lock:
            return self._current_cloud_probe_locked(context)

    def is_current(self, context: WorkContext) -> bool:
        with self._lock:
            return self._current_locked(context)

    def assert_current(self, context: WorkContext) -> None:
        if not self.is_current(context):
            raise ProcessingSuperseded()

    def commit_cloud_attempt(self, context: WorkContext, attempt_id: str) -> _AttemptReceipt:
        _validate_identifier(attempt_id)
        with self._lock:
            if not self._cloud_admission_locked() or not self._current_locked(context):
                raise CloudDispatchBlocked()
            return self._register_attempt_locked(context._state, attempt_id)

    def _register_attempt_locked(self, state: _WorkState, attempt_id: str) -> _AttemptReceipt:
        """Register one attempt only after purpose-specific checks, with lock held."""
        attempted = state.attempted_ids
        if attempt_id in attempted or len(attempted) >= 32:
            raise CloudDispatchBlocked()
        receipt = _AttemptReceipt(self._owner)
        attempted.add(attempt_id)
        self._outstanding[id(receipt)] = receipt
        return receipt

    def finish_attempt(self, receipt: _AttemptReceipt) -> None:
        if type(receipt) is not _AttemptReceipt:
            raise ProcessingStateError()
        with self._lock:
            if (receipt._owner is not self._owner
                    or self._outstanding.get(id(receipt)) is not receipt):
                raise ProcessingStateError()
            del self._outstanding[id(receipt)]

    def commit_cloud_probe_attempt(self, context: CloudProbeContext, attempt_id: str
                                   ) -> _AttemptReceipt:
        _validate_identifier(attempt_id)
        with self._lock:
            if not self._current_cloud_probe_locked(context):
                raise CloudDispatchBlocked()
            return self._register_attempt_locked(context._state, attempt_id)

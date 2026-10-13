"""Bounded fixed-purpose connection probes with owned queued Qt delivery."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Event, Lock
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal, Slot

from src.core.connection_test import ConnectionOutcome, ConnectionResult
from src.core.provider_profile import ProviderProfile
from src.providers.openai_compatible import ProcessingDispatch


@dataclass(frozen=True)
class ProbeRequest:
    request_id: str
    session_epoch: int
    candidate_epoch: int
    purpose: str
    profile: ProviderProfile = field(repr=False)
    key: str = field(repr=False)
    credential_source: str
    fingerprint: str = field(repr=False)
    processing_dispatch: ProcessingDispatch = field(repr=False)

    @property
    def cancel_event(self) -> Event:
        return self.processing_dispatch.context.task_cancel_event


@dataclass(frozen=True)
class ProbeCompletion:
    request: ProbeRequest = field(repr=False)
    result: ConnectionResult = field(repr=False)


class ManagedConnectionRunner(QObject):
    """One executing probe plus one replaceable latest pending request.

    Ownership includes emission exit AND delivery exit; a Future becoming done
    is deliberately not used as evidence that Qt callback targets may be freed.
    The caller retains this QObject until ``workers_idle`` after begin_close.
    """
    completed = Signal(object)
    _ready = Signal(object)

    def __init__(self, service: Callable, parent: QObject | None = None):
        super().__init__(parent)
        self._service = service
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fixed-probe")
        self._lock = Lock()
        self._active: ProbeRequest | None = None
        self._pending: ProbeRequest | None = None
        self._running = False
        self._closing = False
        self._deliveries: set[int] = set()
        self._ready.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

    def submit(self, request: ProbeRequest) -> bool:
        with self._lock:
            if self._closing:
                request.cancel_event.set()
                return False
            if self._active is not None:
                self._active.cancel_event.set()
            if self._pending is not None:
                self._pending.cancel_event.set()
            self._pending = request
            if not self._running:
                self._running = True
                try:
                    self._executor.submit(self._work)
                except Exception:
                    # submit/thread creation can fail before any worker owns
                    # this loop. Seal this executor and remove unexecuted work;
                    # never leave phantom running ownership or disclose errors.
                    self._running = False
                    self._pending = None
                    self._closing = True
                    request.cancel_event.set()
                    self._executor.shutdown(wait=False, cancel_futures=True)
                    return False
            return True

    def cancel(self, request: ProbeRequest) -> None:
        request.cancel_event.set()
        with self._lock:
            if self._pending is request:
                self._pending = None

    def _work(self) -> None:
        while True:
            with self._lock:
                request = self._pending
                self._pending = None
                if request is None:
                    self._running = False
                    return
                self._active = request
            try:
                if not request.processing_dispatch.is_current():
                    result = ConnectionResult(ConnectionOutcome.UNKNOWN_ERROR)
                else:
                    result = self._service(request.profile, request.key,
                        processing_dispatch=request.processing_dispatch)
                    if not isinstance(result, ConnectionResult):
                        result = ConnectionResult(ConnectionOutcome.UNKNOWN_ERROR)
            except Exception:
                result = ConnectionResult(ConnectionOutcome.UNKNOWN_ERROR)
            completion = ProbeCompletion(request, result)
            with self._lock:
                self._deliveries.add(id(completion))
            try:
                self._ready.emit(completion)
            finally:
                # Only after emit returned can this request stop owning its target.
                with self._lock:
                    self._active = None

    @Slot(object)
    def _deliver(self, completion: ProbeCompletion) -> None:
        try:
            self.completed.emit(completion)
        finally:
            with self._lock:
                self._deliveries.discard(id(completion))

    def begin_close(self) -> None:
        with self._lock:
            self._closing = True
            if self._active is not None:
                self._active.cancel_event.set()
            if self._pending is not None:
                self._pending.cancel_event.set()
                self._pending = None
        self._executor.shutdown(wait=False, cancel_futures=False)

    @property
    def workers_idle(self) -> bool:
        with self._lock:
            return not self._running and self._active is None and self._pending is None and not self._deliveries

    @property
    def active_count(self) -> int:
        with self._lock:
            return int(self._active is not None)

    @property
    def pending_count(self) -> int:
        with self._lock:
            return int(self._pending is not None)

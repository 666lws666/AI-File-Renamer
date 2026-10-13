"""One bounded, serial off-Qt owner for already approved file operations.

Capacity spans admission through the *exit* of terminal notification. The caller
must keep this QObject and its Qt targets alive and pump Qt until ``closed``.
Closing is nonblocking and never cancels committed file work.
"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import threading

from PySide6.QtCore import QObject, Qt, Signal, Slot

from src.services.file_operation_backend import (
    FileOperationBackend, FileOperationOutcome, FileOperationRequest, validate_request,
)


@dataclass(frozen=True, eq=False)
class FileOperationReservation:
    request: FileOperationRequest


@dataclass(frozen=True)
class FileOperationProgress:
    reservation: FileOperationReservation
    index: int
    result: FileOperationOutcome


@dataclass(frozen=True)
class FileOperationCompletion:
    reservation: FileOperationReservation
    results: tuple[FileOperationOutcome, ...]


@dataclass(eq=False)
class _Job:
    reservation: FileOperationReservation
    committed: bool = False
    deliveries: int = 0
    emitting: int = 0
    terminal_delivered: bool = False
    released: bool = False
    receipt: object = None


@dataclass(eq=False)
class _Delivery:
    payload: object
    job: _Job
    entered: bool = False
    publishing: bool = False


class ManagedFileOperationLane(QObject):
    itemCompleted = Signal(object)
    completed = Signal(object)
    _progressReady = Signal(object)
    _completionReady = Signal(object)

    def __init__(self, backend: FileOperationBackend, parent=None, *, capacity: int = 1000):
        if type(capacity) is not int or not 1 <= capacity <= 1000:
            raise ValueError("fileops.error.invalidCapacity")
        super().__init__(parent)
        self._backend = backend
        self._capacity = capacity
        self._lock = threading.Lock()
        self._jobs = {}
        self._operations = {}
        self._queue = deque()
        self._deliveries = {}
        self._owned = 0
        self._loop_scheduled = False
        self._emitting = 0
        self._futures = []
        self._closing = False
        self._receipts = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="file-operation-lane")
        self._progressReady.connect(self._deliver_progress, Qt.ConnectionType.QueuedConnection)
        self._completionReady.connect(self._deliver_completion, Qt.ConnectionType.QueuedConnection)

    def _require_owner(self):
        # Query native QObject affinity; saved Python QThread wrappers can change
        # identity after GC and are not an ownership boundary.
        if not self.thread().isCurrentThread():
            raise RuntimeError("fileops.error.wrongThread")

    def reserve(self, request: FileOperationRequest) -> FileOperationReservation | None:
        self._require_owner()
        validate_request(request)
        with self._lock:
            if (self._closing or request.operation_id in self._operations
                    or self._owned + request.item_count > self._capacity):
                return None
            reservation = FileOperationReservation(request)
            job = _Job(reservation)
            self._jobs[id(reservation)] = job
            self._operations[request.operation_id] = job
            self._owned += request.item_count
        if self._receipts is not None:
            try:
                receipt = self._receipts.reserve(request)
            except Exception:
                self.cancel(reservation)
                return None
            with self._lock:
                accepted = not self._closing and self._issued(reservation) is job and receipt is not None
                if accepted: job.receipt = receipt
            if not accepted:
                if receipt is not None: self._receipts.cancel(receipt)
                self.cancel(reservation)
                return None
        return reservation

    def attach_receipts(self, receipts):
        self._require_owner()
        from src.core.watch_self_events import WatchSelfEvents
        if type(receipts) is not WatchSelfEvents:
            raise ValueError("invalid_watch_receipts")
        with self._lock:
            if self._receipts is not None or self._jobs or self._closing:
                raise ValueError("invalid_watch_receipts")
            self._receipts = receipts

    def _issued(self, reservation):
        job = self._jobs.get(id(reservation))
        return job if job is not None and job.reservation is reservation else None

    def _retire(self, job):
        reservation = job.reservation
        self._jobs.pop(id(reservation), None)
        operation_id = reservation.request.operation_id
        if self._operations.get(operation_id) is job:
            del self._operations[operation_id]

    def cancel(self, reservation: FileOperationReservation) -> bool:
        self._require_owner()
        with self._lock:
            job = self._issued(reservation)
            if job is None or job.committed:
                return False
            self._retire(job)
            self._owned -= reservation.request.item_count
        if job.receipt is not None: self._receipts.cancel(job.receipt)
        return True

    def commit(self, reservation: FileOperationReservation) -> bool:
        self._require_owner()
        cancelled = []
        with self._lock:
            job = self._issued(reservation)
            if self._closing or job is None or job.committed:
                return False
            job.committed = True
            self._queue.append(job)
            if self._loop_scheduled:
                return True
            self._loop_scheduled = True
            self._prune_futures()
            try:
                self._futures.append(self._executor.submit(self._run))
            except Exception:
                # No loop was submitted: every queued job is still unexecuted.
                self._loop_scheduled = False
                self._closing = True
                self._queue.clear()
                for unexecuted in tuple(self._jobs.values()):
                    if not unexecuted.committed or unexecuted is job:
                        self._retire(unexecuted)
                        self._owned -= unexecuted.reservation.request.item_count
                        if unexecuted.receipt is not None: cancelled.append(unexecuted.receipt)
                self._executor.shutdown(wait=False)
            else:
                return True
        for receipt in cancelled: self._receipts.cancel(receipt)
        return False

    def _post(self, payload, job, signal):
        with self._lock:
            self._deliveries[id(payload)] = _Delivery(payload, job)
            job.deliveries += 1
            job.emitting += 1
            self._emitting += 1
        try:
            signal.emit(payload)
        finally:
            with self._lock:
                self._emitting -= 1
                job.emitting -= 1
                released = self._release_delivered(job)
            if released and job.receipt is not None:
                self._receipts.acknowledge(job.receipt)

    def _release_delivered(self, job):
        # Recursive Qt event pumping can deliver a terminal while an earlier
        # public progress callback is still on the stack.
        if (job.terminal_delivered and not job.deliveries and not job.emitting
                and not job.released):
            job.released = True
            self._owned -= job.reservation.request.item_count
            return True
        return False

    def _finish_delivery(self, delivery, *, terminal=False):
        with self._lock:
            self._deliveries.pop(id(delivery.payload), None)
            delivery.job.deliveries -= 1
            if terminal:
                delivery.job.terminal_delivered = True
            released = self._release_delivered(delivery.job)
        if released and delivery.job.receipt is not None:
            self._receipts.acknowledge(delivery.job.receipt)

    def _run(self):
        while True:
            with self._lock:
                if not self._queue:
                    self._loop_scheduled = False
                    return
                job = self._queue.popleft()
            request = job.reservation.request
            results = []
            for index in range(request.item_count):
                task_id = (request.plans[index].task_id if request.kind == "apply"
                           else request.task_ids[index])
                try:
                    if job.receipt is not None and hasattr(self._backend, "set_move_observer"):
                        def observe(phase, source, target, result=None):
                            if phase == "before":
                                self._receipts.before_move(job.receipt, task_id, source, target)
                            else:
                                self._receipts.after_move(job.receipt, task_id, source, target, result)
                        self._backend.set_move_observer(observe)
                    result = self._backend.execute_item(request, index)
                except Exception:
                    result = FileOperationOutcome(task_id, request.batch_id, False,
                                                  "fileops.error.unknownOutcome", "", True)
                finally:
                    if job.receipt is not None and hasattr(self._backend, "set_move_observer"):
                        self._backend.set_move_observer(None)
                if job.receipt is not None:
                    self._receipts.settle(job.receipt, task_id, result)
                results.append(result)
                self._post(FileOperationProgress(job.reservation, index, result), job,
                           self._progressReady)
            self._post(FileOperationCompletion(job.reservation, tuple(results)), job,
                       self._completionReady)

    def _claim(self, payload, expected):
        with self._lock:
            delivery = self._deliveries.get(id(payload))
            if (type(payload) is not expected or delivery is None
                    or delivery.payload is not payload or delivery.entered
                    or self._issued(payload.reservation) is not delivery.job):
                return None
            delivery.entered = True
            if expected is FileOperationCompletion:
                # Retire private identity before public notification, but do not
                # release capacity or queued delivery lifetime until its exit.
                self._retire(delivery.job)
            return delivery

    @Slot(object)
    def _deliver_progress(self, payload):
        delivery = self._claim(payload, FileOperationProgress)
        if delivery is None:
            return
        with self._lock:
            delivery.publishing = True
        try:
            self.itemCompleted.emit(payload)
        finally:
            with self._lock:
                delivery.publishing = False
            self._finish_delivery(delivery)

    @Slot(object)
    def _deliver_completion(self, payload):
        delivery = self._claim(payload, FileOperationCompletion)
        if delivery is None:
            return
        with self._lock:
            delivery.publishing = True
        try:
            self.completed.emit(payload)
        finally:
            with self._lock:
                delivery.publishing = False
            self._finish_delivery(delivery, terminal=True)

    def is_publishing(self, payload) -> bool:
        """Exact current public notification, not a copied/replayed envelope."""
        self._require_owner()
        with self._lock:
            delivery = self._deliveries.get(id(payload))
            return (delivery is not None and delivery.payload is payload
                    and delivery.entered and delivery.publishing)

    def begin_close(self) -> None:
        self._require_owner()
        with self._lock:
            if self._closing:
                return
            self._closing = True
            cancelled = []
            for job in tuple(self._jobs.values()):
                if not job.committed:
                    self._retire(job)
                    self._owned -= job.reservation.request.item_count
                    if job.receipt is not None: cancelled.append(job.receipt)
        for receipt in cancelled: self._receipts.cancel(receipt)
        self._executor.shutdown(wait=False)

    def _prune_futures(self):
        self._futures[:] = [future for future in self._futures if not future.done()]

    def _idle(self):
        self._prune_futures()
        return (not self._loop_scheduled and not self._queue and not self._futures
                and not self._emitting and not self._deliveries)

    @property
    def owned_item_count(self) -> int:
        with self._lock:
            return self._owned

    @property
    def pending_job_count(self) -> int:
        with self._lock:
            return sum(job.committed for job in self._jobs.values())

    @property
    def workers_idle(self) -> bool:
        with self._lock:
            return self._idle()

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closing and self._owned == 0 and self._idle()

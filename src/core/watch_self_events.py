"""Bounded non-authorizing shared-lane event receipts.

No disk, callbacks, signals or event pumping under the ledger lock. Unknown
evidence holds rather than suppresses. Closing retains real observation tails.
"""
from dataclasses import dataclass, field
import hashlib
import math
import ntpath
import os
import threading
import time

from src.core.rename_plan import (NativeFileIdentity, SourceFingerprint,
    validate_native_identity, validate_source_fingerprint)
from src.services.file_operation_backend import validate_request, validate_outcome_evidence


@dataclass(frozen=True)
class FileObservation:
    identity: NativeFileIdentity
    fingerprint: SourceFingerprint
    digest: str


def _valid_observation(value):
    if type(value) is not FileObservation:
        return False
    try:
        validate_native_identity(value.identity)
        validate_source_fingerprint(value.fingerprint)
    except ValueError:
        return False
    return (type(value.digest) is str and len(value.digest) == 64
            and all(char in "0123456789abcdef" for char in value.digest))


_READ_RECOVERY = []  # Native ambiguity survives Python wrapper collection.


class _ReadOperation:
    """Independent READ-only ownership; never touches the native move owner."""
    def __init__(self, reader, native):
        self.reader, self.native = reader, native
        self.handles, self.requests, self.buffers = [], [], []
        self.uncertain = False

    def quarantine(self, reason):
        if self.uncertain: return
        self.uncertain, self.reason = True, reason
        with self.reader._lock:
            self.reader._quarantined.append(self)
        _READ_RECOVERY.append(self)

    def root(self, path):
        import ctypes
        handle = self.native._kernel.CreateFileW(self.native._native_path(path),
            0x100081, 1, None, 3, 0x02200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise self.native._NativeError(ctypes.get_last_error())
        self.handles.append(self.native._OwnedHandle(handle))
        return handle

    def child(self, parent, name, directory):
        import ctypes
        native = self.native
        request = native._CreateRequest(parent, name)
        self.requests.append(request)
        try:
            request.state = "submitted"
            # FILE_OPEN only, no CREATE/WRITE/DELETE. Every descendant is
            # relative to the still-held non-reparse parent. SHARE_READ only.
            status = native._nt_create(request, 0x100081, 1, 1,
                0x200020 | (1 if directory else 0x40))
            handle = request.capture(self)
            if status == 0x103:
                request.wait_result = native._wait(handle or parent, 250)
                request.completion = request.block.status
                reason = "read-create-pending"
            elif type(status) is not int:
                reason = "read-create-status"
            elif status < 0:
                reason = "read-create-output" if handle else ""
            elif (status != 0 or request.block.status != 0 or request.block.information != 1
                    or not handle or handle == ctypes.c_void_p(-1).value):
                reason = "read-create-completion"
            else:
                reason = ""
            if reason:
                request.state = "uncertain"
                self.quarantine(reason)
                raise native._Uncertain()
            request.state, request.completion = "terminal", status
            request.release(self)
            if status < 0:
                raise native._NativeError(native._nt.RtlNtStatusToDosError(status))
            return handle
        except BaseException:
            if request.state == "freed": raise
            if request.state != "free-uncertain": request.capture(self)
            self.quarantine("read-create-submission")
            raise native._Uncertain() from None

    def close_all(self):
        if self.uncertain: return
        for record in reversed(self.handles):
            record.state = "closing"
            try:
                self.native._close(record.value)
            except BaseException:
                record.state = "close-uncertain"
                self.quarantine("read-handle-close")
                return
            record.state = "closed"


class NativeWatchObservation:
    """Two bounded worker observations, independent ambiguity and close tails."""
    def __init__(self):
        self._lock = threading.Lock()
        self._active = 0
        self._quarantined = []
        self._closing = False
        self._cancel = threading.Event()

    def read_file(self, path, *, max_bytes=512 * 1024 * 1024, deadline=None, cancel_event=None):
        if threading.current_thread() is threading.main_thread():
            raise RuntimeError("watch_observation_worker_required")
        if type(max_bytes) is not int or not 1 <= max_bytes <= 512 * 1024 * 1024:
            raise ValueError("invalid_watch_observation_budget")
        limit = time.monotonic() + 2 if deadline is None else deadline
        if type(limit) not in (float, int) or not math.isfinite(limit):
            raise ValueError("invalid_watch_observation_budget")
        # A caller cannot stretch the per-observation soft budget beyond 2s.
        limit = min(limit, time.monotonic() + 2)
        def expired():
            return (time.monotonic() >= limit or self._cancel.is_set()
                    or (cancel_event is not None and cancel_event.is_set()))
        if expired(): return None
        from src.core import safe_file_move as native
        if not native._NATIVE_AVAILABLE: return None
        with self._lock:
            if self._closing or self._quarantined or self._active >= 2: return None
            self._active += 1
        operation = _ReadOperation(self, native)
        observation = None
        try:
            validated = native._path(path)
            drive, tail = ntpath.splitdrive(validated)
            components = tail.strip("\\").split("\\")
            if not components or len(components) > 1024: return None
            parent = operation.root(drive + "\\")
            for index, name in enumerate(components):
                directory = index < len(components) - 1
                if expired(): return None
                held = native._info(parent)
                if held.attributes & native._REPARSE or not held.attributes & native._DIRECTORY:
                    return None
                if not directory and native._filesystem(parent) != "NTFS": return None
                parent = operation.child(parent, name, directory)
            before = native._info(parent)
            if (before.attributes & (native._DIRECTORY | native._REPARSE)
                    or before.links != 1 or before.fingerprint.size_bytes > max_bytes):
                return None
            import ctypes
            from ctypes import wintypes
            read = native._kernel.ReadFile
            read.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                             ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
            read.restype = wintypes.BOOL
            buffer, count = ctypes.create_string_buffer(65536), wintypes.DWORD()
            operation.buffers.extend((buffer, count))
            digest, amount = hashlib.sha256(), 0
            while not expired():
                try:
                    accepted = read(parent, buffer, len(buffer), ctypes.byref(count), None)
                except BaseException:
                    operation.quarantine("read-submission")
                    raise native._Uncertain() from None
                if not accepted:
                    if ctypes.get_last_error() == 997:
                        operation.quarantine("read-pending")
                    return None
                if not count.value: break
                amount += count.value
                if amount > max_bytes: return None
                digest.update(buffer.raw[:count.value])
            else:
                return None
            after = native._info(parent)
            immutable = lambda value: (value.volume, value.index, value.creation,
                value.attributes, value.links, value.fingerprint)
            if immutable(before) != immutable(after) or amount != before.fingerprint.size_bytes or expired():
                return None
            observation = FileObservation(NativeFileIdentity(after.volume, after.index, after.creation),
                after.fingerprint, digest.hexdigest())
        except (OSError, ValueError, native._Unsupported):
            observation = None
        finally:
            operation.close_all()
            with self._lock: self._active -= 1
        return observation if not operation.uncertain else None

    def begin_close(self):
        self._cancel.set()
        with self._lock: self._closing = True

    @property
    def workers_idle(self):
        with self._lock: return not self._active and not self._quarantined

    @property
    def quarantined_count(self):
        with self._lock: return len(self._quarantined)


_DEFAULT_OBSERVER = NativeWatchObservation()


def observe_file(path, **options):
    return _DEFAULT_OBSERVER.read_file(path, **options)


def _path(value):
    return os.path.normcase(os.path.abspath(value))


def _family(path, target, extension):
    if _path(path) == _path(target):
        return True
    if _path(os.path.dirname(path)) != _path(os.path.dirname(target)):
        return False
    name, actual = os.path.normcase(os.path.basename(target)), os.path.normcase(os.path.basename(path))
    extension = os.path.normcase(extension)
    if extension:
        if not actual.endswith(extension): return False
        stem, suffix = name[:-len(extension)], name[-len(extension):]
        actual_stem, actual_suffix = actual[:-len(extension)], actual[-len(extension):]
    else:
        stem, suffix = os.path.splitext(name)
        actual_stem, actual_suffix = os.path.splitext(actual)
    counter = actual_stem[len(stem) + 1:] if actual_stem.startswith(stem + "_") else ""
    return (actual_suffix == suffix and bool(counter) and len(counter) <= 3
            and counter.isascii() and counter.isdecimal() and counter[0] != "0"
            and int(counter) < 1000)


@dataclass(eq=False)
class _RowReceipt:
    task_id: str
    source: str = ""
    target: str = ""
    extension: str = ""
    paths: set = field(default_factory=set)
    digests: dict = field(default_factory=dict)
    successes: dict = field(default_factory=dict)
    settled: bool = False
    recovery: bool = False

    def matches(self, path):
        return (_path(path) in self.paths or (bool(self.source) and _path(path) == _path(self.source))
                or (bool(self.target) and _family(path, self.target, self.extension)))


@dataclass(eq=False)
class _Receipt:
    request: object
    rows: dict
    finished_at: float | None = None


class WatchSelfEvents:
    def __init__(self, *, capacity=1000, late_seconds=30, clock=time.monotonic, observe=None):
        if (type(capacity) is not int or not 1 <= capacity <= 1000
                or type(late_seconds) not in (float, int) or not math.isfinite(late_seconds)
                or not 0 < late_seconds <= 30 or not callable(clock)
                or (observe is not None and not callable(observe))):
            raise ValueError("invalid_watch_receipts")
        self._capacity, self._late = capacity, late_seconds
        self._clock, self._observe = clock, observe
        self._reader = NativeWatchObservation()
        self._lock = threading.Lock()
        self._receipts = {}
        self._callbacks = 0
        self._closing = False
        self._cancel = threading.Event()

    def _read(self, path):
        return (self._observe(path) if self._observe is not None else
                self._reader.read_file(path, cancel_event=self._cancel))

    def _prune(self, now):
        self._receipts = {key: receipt for key, receipt in self._receipts.items()
            if receipt.finished_at is None or any(row.recovery for row in receipt.rows.values())
            or now - receipt.finished_at < self._late}

    def reserve(self, request):
        validate_request(request)
        now = self._clock()
        with self._lock:
            self._prune(now)
            if (self._closing or request.operation_id in self._receipts
                    or sum(len(value.rows) for value in self._receipts.values()) + request.item_count > self._capacity):
                return None
            rows = ({plan.task_id: _RowReceipt(plan.task_id, plan.source_path,
                plan.target_path, plan.extension) for plan in request.plans} if request.kind == "apply"
                else {task: _RowReceipt(task) for task in request.task_ids})
            receipt = _Receipt(request, rows)
            self._receipts[request.operation_id] = receipt
            return receipt

    def cancel(self, receipt):
        with self._lock:
            if self._receipts.get(receipt.request.operation_id) is not receipt:
                return False
            del self._receipts[receipt.request.operation_id]
            return True

    def before_move(self, receipt, task_id, source, target):
        with self._lock:
            if self._receipts.get(receipt.request.operation_id) is not receipt:
                return
            row = receipt.rows.get(task_id)
            if row is None: return
            # Worker-trusted Undo/compensation candidates only; never blanket
            # directory filters or expanded collision name allocations.
            for path in (source, target):
                if not row.matches(path):
                    if len(row.paths) >= 8:
                        row.recovery = True
                        return
                    row.paths.add(_path(path))
            cached = row.digests.get(_path(source))
            self._callbacks += 1
        try:
            observed = cached if cached is not None else self._read(source)
            with self._lock:
                if _valid_observation(observed):
                    row.digests[_path(source)] = observed
        finally:
            with self._lock: self._callbacks -= 1

    def after_move(self, receipt, task_id, source, target, result):
        with self._lock:
            row = receipt.rows.get(task_id)
            if row is None or self._receipts.get(receipt.request.operation_id) is not receipt:
                return
            observed = row.digests.get(_path(source))
            try:
                validate_native_identity(result.source_identity)
                validate_source_fingerprint(result.source_fingerprint)
                valid = result.success is True and result.recovery_required is False
            except (ValueError, AttributeError):
                valid = False
            if (valid and _valid_observation(observed)
                    and (observed.identity.volume_serial, observed.identity.file_index)
                        == (result.source_identity.volume_serial, result.source_identity.file_index)):
                # NTFS tunneling can change creation time during this held-file
                # rename. Physical PRE/POST attribution uses volume/file ID;
                # every future observation compares the full actual POST ID.
                row.successes[_path(target)] = FileObservation(result.source_identity,
                    result.source_fingerprint, observed.digest)
                row.digests[_path(target)] = row.successes[_path(target)]

    def settle(self, receipt, task_id, result):
        now = self._clock()
        with self._lock:
            if self._receipts.get(receipt.request.operation_id) is not receipt: return
            row = receipt.rows.get(task_id)
            if row is None or row.settled: return
            try:
                validate_outcome_evidence(result)
                if result.task_id != task_id: raise ValueError()
                row.recovery = row.recovery or result.recovery_required
                row.paths.update(_path(path) for path in result.owned_residue_paths)
                if result.success and _path(result.new_path) not in row.successes:
                    row.recovery = True  # No trusted pre-mutation content capture.
            except (ValueError, AttributeError):
                row.recovery = True
            row.settled = True

    def acknowledge(self, receipt):
        """Actual shared-lane emission/publication tail, before late expiry."""
        now = self._clock()
        with self._lock:
            if self._receipts.get(receipt.request.operation_id) is not receipt: return
            if all(value.settled for value in receipt.rows.values()):
                receipt.finished_at = now
                if self._closing: del self._receipts[receipt.request.operation_id]

    def decision(self, path):
        now = self._clock()
        with self._lock:
            self._prune(now)
            rows = tuple(row for receipt in self._receipts.values()
                for row in receipt.rows.values() if row.matches(path))
            if not rows: return "allow"
            if any(not row.settled or row.recovery for row in rows): return "hold"
            evidence = tuple(row.successes.get(_path(path)) for row in rows)
            evidence = tuple(value for value in evidence if value is not None)
            if not evidence: return "allow"
            self._callbacks += 1
        try:
            observed = self._read(path)
            if observed is None: return "hold"
            return "suppress" if observed in evidence else "allow"
        finally:
            with self._lock: self._callbacks -= 1

    def begin_close(self):
        self._cancel.set()
        self._reader.begin_close()
        with self._lock:
            self._closing = True
            self._receipts = {key: receipt for key, receipt in self._receipts.items()
                if receipt.finished_at is None}

    @property
    def workers_idle(self):
        with self._lock:
            idle = not self._callbacks and (not self._closing or not self._receipts)
        return idle and self._reader.workers_idle

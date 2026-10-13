"""The sole persisted processing choice, independent of general configuration.

The writer serializes choice revisions. A timed-out close returns False and its
daemon worker continues draining; the caller must not claim durability or exit
expecting pending writes to survive. No authority callback runs under our locks.
"""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import stat
import tempfile
from threading import Condition, Lock, Thread, current_thread
from uuid import uuid4

from .processing_authority import ChoiceIntent, ProcessingAuthority, ProcessingMode


_MAX_BYTES = 4096
_MAX_REVISION = 2**63 - 1


if os.name == "nt":
    import ctypes
    from ctypes import wintypes
    import msvcrt

    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _kernel.CreateFileW.restype = wintypes.HANDLE
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL
    _kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                  ctypes.c_void_p, wintypes.DWORD]
    _kernel.SetFileInformationByHandle.restype = wintypes.BOOL


class _WindowsPin:
    """A transaction-local no-reparse handle, denying rename by other handles."""

    def __init__(self, path: Path, *, directory=False, create=False):
        self.writable = create
        access = 0x80 if directory else (0xC0010000 if create else 0x80000000)
        self.handle = _kernel.CreateFileW(str(path), access, 3 if directory else 1,
                                         None, 1 if create else 3,
                                         0x00200000 | (0x02000000 if directory else 0), None)
        if self.handle == ctypes.c_void_p(-1).value:
            self.handle = None
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            _safe_stat(path, directory=directory)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.handle is not None:
            _kernel.CloseHandle(self.handle)
            self.handle = None

    def descriptor(self):
        # Ownership passes to the stream. Keep its handle value for rename and
        # exact-handle cleanup while that stream is open.
        descriptor = msvcrt.open_osfhandle(
            self.handle, os.O_BINARY | (os.O_RDWR if self.writable else os.O_RDONLY))
        self.handle = None
        return descriptor


@contextmanager
def _parent_guard(path: Path, *, create=False):
    if os.name != "nt":
        parents = _parents(path, allow_missing=create)
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
        _check_parents(parents)
        yield
        return
    # Pin each existing ancestor before creating/opening its child. Never
    # resolve junctions and never relax ACLs or recursively clean directories.
    with ExitStack() as stack:
        for parent in reversed(path.parents):
            try:
                pin = _WindowsPin(parent, directory=True)
            except FileNotFoundError:
                if not create:
                    raise
                parent.mkdir(exist_ok=True)
                pin = _WindowsPin(parent, directory=True)
            stack.callback(pin.close)
        if create:
            path.parent.mkdir(exist_ok=True)
        yield


class ProcessingIntentError(ValueError):
    """Fixed, safe-to-display persistence failure; no underlying input details."""

    def __init__(self):
        super().__init__("PROCESSING_PERSISTENCE_ERROR")


class _MissingIntent(FileNotFoundError):
    """Absence observed before opening, not a record lost during a read."""


@dataclass(frozen=True)
class ProcessingStartupRecord:
    mode: ProcessingMode
    revision: int
    startup_error: bool = False


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProcessingIntentError()
        result[key] = value
    return result


def _reject_constant(value):
    raise ProcessingIntentError()


def _decode(payload: bytes) -> ProcessingStartupRecord:
    if len(payload) > _MAX_BYTES:
        raise ProcessingIntentError()
    value = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object,
                       parse_constant=_reject_constant)
    if (type(value) is not dict
            or set(value) != {"schema_version", "revision", "mode"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or type(value["revision"]) is not int
            or not 1 <= value["revision"] <= _MAX_REVISION
            or type(value["mode"]) is not str
            or value["mode"] not in ("cloud", "local")):
        raise ProcessingIntentError()
    return ProcessingStartupRecord(ProcessingMode(value["mode"]), value["revision"])


def _candidate(intent: ChoiceIntent) -> bytes:
    if (type(intent) is not ChoiceIntent or type(intent.mode) is not ProcessingMode
            or type(intent.revision) is not int
            or not 1 <= intent.revision <= _MAX_REVISION):
        raise ProcessingIntentError()
    payload = json.dumps({"schema_version": 1, "revision": intent.revision,
                          "mode": intent.mode.value}, separators=(",", ":")).encode("utf-8")
    _decode(payload)
    return payload


def _safe_stat(path: Path, *, directory=False):
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        raise ProcessingIntentError()
    return info


def _identity(info):
    return info.st_dev, info.st_ino


def _parents(path: Path, *, allow_missing=False):
    identities = []
    for parent in reversed(path.parents):
        try:
            info = _safe_stat(parent, directory=True)
        except FileNotFoundError:
            if allow_missing:
                break
            raise
        identities.append((parent, _identity(info)))
    return identities


def _check_parents(identities):
    for parent, identity in identities:
        if _identity(_safe_stat(parent, directory=True)) != identity:
            raise ProcessingIntentError()


def _open_read(path: Path):
    if os.name == "nt":
        pin = _WindowsPin(path)
        try:
            return pin.descriptor()
        finally:
            pin.close()
    return os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))


def _read_record(path: Path) -> bytes:
    try:
        parents = _parents(path)
        previous = _safe_stat(path)
    except FileNotFoundError:
        raise _MissingIntent() from None
    descriptor = _open_read(path)
    try:
        stream = os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise
    with stream as file:
        if _identity(os.fstat(file.fileno())) != _identity(previous):
            raise ProcessingIntentError()
        result = file.read(_MAX_BYTES + 1)
    _check_parents(parents)
    if _identity(_safe_stat(path)) != _identity(previous):
        raise ProcessingIntentError()
    return result


def _atomic_replace(candidate, temporary: Path, destination: Path):
    if os.name != "nt":
        os.replace(temporary, destination)
        return
    name = str(destination)
    length = len(name.encode("utf-16-le"))

    class RenameInfo(ctypes.Structure):
        _fields_ = [("replace", wintypes.BOOLEAN), ("root", wintypes.HANDLE),
                    ("length", wintypes.DWORD), ("name", wintypes.WCHAR * (length // 2 + 1))]

    info = RenameInfo()
    info.replace = True
    info.length = length
    info.name = name
    handle = msvcrt.get_osfhandle(candidate)
    if not _kernel.SetFileInformationByHandle(handle, 3, ctypes.byref(info), ctypes.sizeof(info)):
        raise ctypes.WinError(ctypes.get_last_error())


def _delete_owned_candidate(descriptor):
    # FileDispositionInfo deletes this exact open object on close, not whatever
    # another operation might subsequently put at the old temporary pathname.
    flag = wintypes.BOOLEAN(True)
    _kernel.SetFileInformationByHandle(msvcrt.get_osfhandle(descriptor), 4,
                                      ctypes.byref(flag), ctypes.sizeof(flag))


class ProcessingIntentStore:
    def __init__(self, path: Path):
        self.path = Path(os.path.abspath(path))
        self._lock = Lock()

    def load(self) -> ProcessingStartupRecord:
        with self._lock:
            try:
                try:
                    with _parent_guard(self.path):
                        return _decode(_read_record(self.path))
                except FileNotFoundError as error:
                    # Missing ancestors mean there was never a readable record;
                    # disappearance after initial validation is not legacy state.
                    if isinstance(error, _MissingIntent):
                        raise
                    try:
                        _parents(self.path)
                    except FileNotFoundError:
                        raise _MissingIntent() from None
                    raise
            except _MissingIntent:
                return ProcessingStartupRecord(ProcessingMode.CLOUD, 0)
            except (OSError, ValueError, UnicodeError, RecursionError):
                return ProcessingStartupRecord(ProcessingMode.LOCAL, 0, True)

    def save(self, intent: ChoiceIntent) -> None:
        payload = _candidate(intent)
        with self._lock:
            try:
                with _parent_guard(self.path, create=True):
                    self._save_candidate(payload)
            except (OSError, ValueError):
                raise ProcessingIntentError() from None

    def _save_candidate(self, payload):
        temporary = None
        identity = None
        try:
            parents = _parents(self.path)
            try:
                _safe_stat(self.path)
            except FileNotFoundError:
                pass
            if os.name == "nt":
                temporary = self.path.parent / (".processing-intent-" + uuid4().hex + ".tmp")
                pin = _WindowsPin(temporary, create=True)
                try:
                    descriptor = pin.descriptor()
                finally:
                    pin.close()
            else:
                descriptor, name = tempfile.mkstemp(prefix=".processing-intent-", suffix=".tmp",
                                                     dir=self.path.parent)
                temporary = Path(name)
            try:
                identity = _identity(os.fstat(descriptor))
                stream = os.fdopen(descriptor, "wb")
            except BaseException:
                if os.name == "nt":
                    _delete_owned_candidate(descriptor)
                os.close(descriptor)
                raise
            with stream as file:
                published = False
                try:
                    if file.write(payload) != len(payload):
                        raise ProcessingIntentError()
                    file.flush()
                    os.fsync(file.fileno())
                    _check_parents(parents)
                    if _identity(_safe_stat(temporary)) != identity:
                        raise ProcessingIntentError()
                    try:
                        _safe_stat(self.path)
                    except FileNotFoundError:
                        pass
                    _atomic_replace(file.fileno(), temporary, self.path)
                    published = True
                finally:
                    if os.name == "nt" and not published:
                        _delete_owned_candidate(file.fileno())
        finally:
            if os.name != "nt" and temporary is not None and identity is not None:
                try:
                    _check_parents(parents)
                    if _identity(_safe_stat(temporary)) == identity:
                        temporary.unlink()
                except (OSError, ValueError):
                    pass


class ProcessingIntentWriter:
    """One worker, monotonic revisions, and retry of only the latest failed object.

    submit returns whether a save was queued; even rejected submissions receive
    one failed authority completion. close stops admission, waits at most 0.25 s,
    and reports whether all writes and notifications have drained. Repeated
    close calls may finish waiting after a prior timeout.
    """

    def __init__(self, store: ProcessingIntentStore, authority: ProcessingAuthority,
                 *, completion_callback=None):
        self._store = store
        self._authority = authority
        self._completion_callback = completion_callback
        self._condition = Condition(Lock())
        self._queue = deque()
        self._closed = False
        self._latest: ChoiceIntent | None = None
        self._failed: ChoiceIntent | None = None
        self._thread = Thread(target=self._run, name="processing-intent-writer", daemon=True)
        self._thread.start()

    def submit(self, intent: ChoiceIntent) -> bool:
        try:
            _candidate(intent)
            valid = self._authority.is_current_choice(intent)
        except (ValueError, AttributeError):
            valid = False
        with self._condition:
            accepted = valid and not self._closed and (
                self._latest is None or intent.revision > self._latest.revision
                or intent is self._failed)
            if accepted:
                self._latest = intent
                self._failed = None
                self._queue.append(intent)
                self._condition.notify()
        if not accepted:
            self._complete(intent, False)
        return accepted

    def _complete(self, intent, persisted):
        if self._completion_callback is None:
            self._authority.complete_choice(intent, persisted=persisted)
        else:
            self._completion_callback(intent, persisted)

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._queue or self._closed)
                if not self._queue:
                    return
                intent = self._queue.popleft()
            try:
                persisted = self._authority.is_current_choice(intent)
                if persisted:
                    self._store.save(intent)
            except Exception:
                persisted = False
            with self._condition:
                if not persisted and intent is self._latest:
                    self._failed = intent
            self._complete(intent, persisted)

    def close(self, *, timeout=0.25) -> bool:
        if (type(timeout) not in (int, float) or not 0 <= timeout <= 0.25
                or not math.isfinite(timeout)):
            raise ValueError("PROCESSING_WRITER_TIMEOUT_ERROR")
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        if current_thread() is self._thread:
            return False
        self._thread.join(timeout=timeout)
        return not self._thread.is_alive()

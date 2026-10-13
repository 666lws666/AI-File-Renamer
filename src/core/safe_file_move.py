"""Verified worker-only Windows boundary for engine Apply, Undo and compensation.

Only same-volume held-object rename is supported. Cross-volume requests are
explicitly refused with the original retained: holding the default stream does
NOT freeze all NTFS streams. No source deletion, copy or path-based fallback
exists. Only newly owned empty guard files use DELETE_ON_CLOSE cleanup.
Uncertain native resources are quarantined until actual OS process termination;
GC, module reload and embedded-interpreter restart are not supported recovery.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import ntpath
import os
import re
import secrets
import threading

from .rename_plan import (NativeFileIdentity, SourceFingerprint, validate_native_identity,
                          validate_source_fingerprint)


@dataclass(frozen=True)
class SafeFileMoveResult:
    success: bool
    new_path: str = ""
    error_code: str = ""
    recovery_required: bool = False
    source_fingerprint: SourceFingerprint | None = None
    owned_residue_paths: tuple[str, ...] = ()
    source_identity: NativeFileIdentity | None = None


_WINDOWS = os.name == "nt"
_NATIVE_AVAILABLE = False
_EPOCH_TICKS = 116444736000000000
_DIRECTORY = 0x10
_REPARSE = 0x400
_RESERVED = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", re.I)


class _Unsupported(Exception):
    pass


class _InvalidRoot(Exception):
    pass


class _Changed(Exception):
    pass


class _CrossVolumeBlocked(Exception):
    pass


class _NativeError(OSError):
    def __init__(self, code):
        super().__init__(code, "Native file operation failed")
        self.winerror = code


class _Uncertain(OSError):
    pass


class _FileInformation(ctypes.Structure):
    _fields_ = [("attributes", wintypes.DWORD), ("creation", wintypes.FILETIME),
                ("access", wintypes.FILETIME), ("write", wintypes.FILETIME),
                ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]


class _RenameHeader(ctypes.Structure):
    # The union's DWORD alignment and pointer-width root determine Name's offset.
    _fields_ = [("flags", wintypes.DWORD), ("root", wintypes.HANDLE),
                ("length", wintypes.DWORD), ("name", wintypes.WCHAR * 1)]


class _StatusValue(ctypes.Union):
    _fields_ = [("status", ctypes.c_int32), ("pointer", ctypes.c_void_p)]


class _StatusBlock(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("value", _StatusValue), ("information", ctypes.c_size_t)]


class _UnicodeString(ctypes.Structure):
    _fields_ = [("length", wintypes.USHORT), ("maximum", wintypes.USHORT),
                ("buffer", ctypes.c_void_p)]


class _ObjectAttributes(ctypes.Structure):
    _fields_ = [("length", wintypes.ULONG), ("root", wintypes.HANDLE),
                ("name", ctypes.c_void_p), ("attributes", wintypes.ULONG),
                ("security", ctypes.c_void_p), ("quality", ctypes.c_void_p)]


if _WINDOWS:
    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _kernel.CreateFileW.restype = wintypes.HANDLE
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL
    _kernel.GetFileType.argtypes = [wintypes.HANDLE]
    _kernel.GetFileType.restype = wintypes.DWORD
    _kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileInformation)]
    _kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    _kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel.WaitForSingleObject.restype = wintypes.DWORD
    _kernel.GetProcessHeap.argtypes = []
    _kernel.GetProcessHeap.restype = wintypes.HANDLE
    _kernel.HeapAlloc.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_size_t]
    _kernel.HeapAlloc.restype = ctypes.c_void_p
    _kernel.HeapFree.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p]
    _kernel.HeapFree.restype = wintypes.BOOL
    try:
        _nt = ctypes.WinDLL("ntdll")
        _nt.NtSetInformationFile.argtypes = [wintypes.HANDLE, ctypes.POINTER(_StatusBlock),
                                            ctypes.c_void_p, wintypes.ULONG, ctypes.c_int]
        _nt.NtSetInformationFile.restype = ctypes.c_int32
        _nt.NtCreateFile.argtypes = [ctypes.c_void_p, wintypes.ULONG, ctypes.c_void_p,
                                    ctypes.c_void_p, ctypes.c_void_p, wintypes.ULONG,
                                    wintypes.ULONG, wintypes.ULONG, wintypes.ULONG,
                                    ctypes.c_void_p, wintypes.ULONG]
        _nt.NtCreateFile.restype = ctypes.c_int32
        _kernel.GetVolumeInformationByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR,
            wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            wintypes.LPWSTR, wintypes.DWORD]
        _kernel.GetVolumeInformationByHandleW.restype = wintypes.BOOL
        _nt.RtlNtStatusToDosError.argtypes = [ctypes.c_int32]
        _nt.RtlNtStatusToDosError.restype = wintypes.ULONG
        _NATIVE_AVAILABLE = True
    except (AttributeError, OSError):
        pass  # The public API rejects before opening any filesystem objects.


@dataclass(frozen=True)
class _Info:
    attributes: int
    volume: int
    index: int
    links: int
    creation: int
    access: int
    write: int
    fingerprint: SourceFingerprint


def _ticks(value):
    return (value.dwHighDateTime << 32) | value.dwLowDateTime


def _native_path(path):
    # Extended syntax is generated only after strict local-drive input validation.
    return "\\\\?\\" + path


def _open(path, *, directory=False):
    # Attribute-only directory handles do not engage sharing enforcement; the
    # actual 0x80/0x81 comparison proved LIST_DIRECTORY is needed to deny rename.
    access = 0x100081 if directory else 0x80110000
    handle = _kernel.CreateFileW(_native_path(path), access, 3 if directory else 0,
                                 None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise _NativeError(ctypes.get_last_error())
    return handle


def _filesystem(handle):
    name = ctypes.create_unicode_buffer(32)
    if not _kernel.GetVolumeInformationByHandleW(handle, None, 0, None, None, None, name, len(name)):
        raise _NativeError(ctypes.get_last_error())
    return name.value


def _close(handle):
    if not _kernel.CloseHandle(handle):
        raise _NativeError(ctypes.get_last_error())


def _info(handle):
    if _kernel.GetFileType(handle) != 1:  # FILE_TYPE_DISK only.
        raise _Unsupported()
    result = _FileInformation()
    if not _kernel.GetFileInformationByHandle(handle, ctypes.byref(result)):
        raise _NativeError(ctypes.get_last_error())
    write = _ticks(result.write)
    return _Info(result.attributes, result.volume,
                 (result.index_high << 32) | result.index_low, result.links,
                 _ticks(result.creation), _ticks(result.access), write,
                 SourceFingerprint((result.size_high << 32) | result.size_low,
                                   (write - _EPOCH_TICKS) * 100))


def _nt_set(handle, block, buffer):
    return _nt.NtSetInformationFile(handle, ctypes.byref(block), buffer, len(buffer), 10)


def _heap_alloc(amount):
    heap = _kernel.GetProcessHeap()
    if not heap:
        raise _NativeError(ctypes.get_last_error())
    pointer = _kernel.HeapAlloc(heap, 8, amount)  # Serialized process heap, zeroed.
    if not pointer:
        raise OSError("Native request allocation failed")  # HeapAlloc sets no last error.
    return pointer


def _heap_free(pointer):
    if not _kernel.HeapFree(_kernel.GetProcessHeap(), 0, pointer):
        raise _NativeError(ctypes.get_last_error())


def _wait(handle, milliseconds):
    return _kernel.WaitForSingleObject(handle, milliseconds)


class _RenameRequest:
    """Non-owning Python views over one explicitly owned native allocation.

    No destructor/atexit free: even destruction of every Python reference cannot
    free an unresolved process-heap request that the kernel may still access.
    """
    def __init__(self, parent, encoded):
        self.kind = "rename"
        if not 0 < len(encoded) <= 510:
            raise ValueError("Invalid bounded native name")
        alignment = ctypes.alignment(_RenameHeader)
        offset = (ctypes.sizeof(_StatusBlock) + alignment - 1) // alignment * alignment
        amount = ctypes.sizeof(_RenameHeader) + len(encoded)
        self.pointer = _heap_alloc(offset + amount)
        self.state = "allocated"
        self.wait_result = None
        self.completion = None
        self.block = _StatusBlock.from_address(self.pointer)
        self.buffer = (ctypes.c_char * amount).from_address(self.pointer + offset)
        header = _RenameHeader.from_address(self.pointer + offset)
        header.flags = 0
        header.root = parent
        header.length = len(encoded)
        ctypes.memmove(self.pointer + offset + _RenameHeader.name.offset, encoded, len(encoded))
        self.block.status = ctypes.c_int32(0xC0000000).value

    def release(self, transaction):
        self.state = "freeing"  # Mark BEFORE the possibly ambiguous native call.
        try:
            _heap_free(self.pointer)
        except BaseException:
            self.state = "free-uncertain"
            transaction.quarantine("heap-free")
            raise _Uncertain() from None
        self.state = "freed"
        # Do not retain dangling views; the original numeric ownership record is
        # kept only for audit and never reused/probed after an ambiguous free.
        self.block = self.buffer = None


class _CreateRequest(_RenameRequest):
    """All pointer-bearing create input/output resides in one <=640-byte heap."""
    def __init__(self, parent, name):
        encoded = name.encode("utf-16-le")
        if (not 0 < len(encoded) <= 510 or name in (".", "..")
                or any(char in name for char in "\\/:\0")):
            raise ValueError("Invalid single native component")
        self.kind, self.name = "create", name
        self.amount = 128 + len(encoded) + 2
        self.pointer = _heap_alloc(self.amount)
        self.state = "allocated"
        self.wait_result = self.completion = None
        self.returned_handle = None
        self.output = ctypes.c_void_p.from_address(self.pointer)
        self.block = _StatusBlock.from_address(self.pointer + 16)
        self.attributes = _ObjectAttributes.from_address(self.pointer + 32)
        self.unicode = _UnicodeString.from_address(self.pointer + 96)
        self.buffer = (ctypes.c_char * (len(encoded) + 2)).from_address(self.pointer + 128)
        ctypes.memmove(self.pointer + 128, encoded, len(encoded))
        self.unicode.length = len(encoded)
        self.unicode.maximum = len(encoded) + 2
        self.unicode.buffer = self.pointer + 128
        self.attributes.length = ctypes.sizeof(_ObjectAttributes)
        self.attributes.root = parent
        self.attributes.name = self.pointer + 96
        self.attributes.attributes = 0x1040  # OBJ_CASE_INSENSITIVE | OBJ_DONT_REPARSE
        self.block.status = ctypes.c_int32(0xC0000000).value

    def capture(self, transaction):
        handle = self.output.value
        if handle and handle != ctypes.c_void_p(-1).value and self.returned_handle is None:
            transaction.handles.append(_OwnedHandle(handle))
            self.returned_handle = handle
        return handle

    def release(self, transaction):
        super().release(transaction)
        self.output = self.attributes = self.unicode = None


def _nt_create(request, access, share, disposition, options):
    return _nt.NtCreateFile(request.pointer, access, request.pointer + 32,
                            request.pointer + 16, None, 0x80, share, disposition,
                            options, None, 0)


def _rename(handle, parent, name):
    encoded = name.encode("utf-16-le")
    transaction = _OWNER.active
    if transaction is None:
        raise OSError("No admitted native transaction")
    request = _RenameRequest(parent, encoded)
    transaction.requests.append(request)  # Ownership registered BEFORE submission.
    # SetFileInformationByHandle's Win32 path conversion rejects this relative
    # contract with 87 on the verified host. The documented user-mode Nt entry
    # preserves BOTH held objects, and is not a path-based rename fallback.
    try:
        request.state = "submitted"
        status = _nt_set(handle, request.block, request.buffer)
        if status == 0x103:
            request.wait_result = _wait(handle, 250)
            request.completion = request.block.status
            # A signal alone does not prove this request completed. Even known
            # terminal completion never turns an initially pending call into PASS.
            known_terminal = request.completion in (0, ctypes.c_int32(0xC0000035).value,
                                                     ctypes.c_int32(0xC0000022).value)
            reason = "pending-terminal" if request.wait_result == 0 and known_terminal else "pending-unresolved"
        elif type(status) is not int or status >= 0 and (status != 0 or request.block.status != 0):
            reason = "native-completion"
        else:
            reason = ""
        if reason:
            transaction.quarantine(reason)
            request.state = "uncertain"
            raise _Uncertain()
        request.state = "terminal"
        request.completion = status
        request.release(transaction)
        if status < 0:
            raise _NativeError(_nt.RtlNtStatusToDosError(status))
    except BaseException:
        if request.state == "freed":
            raise  # Completion is proven; no native request storage remains live.
        if not transaction.uncertain:
            transaction.quarantine("native-submission")
            request.state = "uncertain"
        raise _Uncertain() from None


def _path(value, *, root=False):
    if type(value) is not str or not 1 <= len(value) <= 4096:
        raise ValueError()
    value = value.replace("/", "\\")
    if (not re.match(r"^[a-zA-Z]:\\", value) or value.startswith("\\\\")
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)
            or any(char in value[2:] for char in ':<>"|?*')):
        raise ValueError()
    if not root and value.endswith("\\"):
        raise ValueError()
    parts = value[3:].split("\\") if len(value) > 3 else []
    # A single trailing root separator is harmless; empty interior components are not.
    if parts and parts[-1] == "":
        parts.pop()
    for part in parts:
        if (not part or part in (".", "..") or part.endswith((".", " "))
                or _RESERVED.match(part.split(".")[0].rstrip(" "))
                or len(part.encode("utf-16-le")) > 510):
            raise ValueError()
    return value[:2].upper() + "\\" + "\\".join(parts)


def _inside(path, root):
    path, root = ntpath.normcase(path), ntpath.normcase(root)
    return path == root or path.startswith(root.rstrip("\\") + "\\")


def _validate(source, destination, expected, roots, create, expected_identity=None):
    if expected_identity is not None:
        validate_native_identity(expected_identity)
    if expected is None and expected_identity is None:
        raise ValueError()
    if expected is not None:
        validate_source_fingerprint(expected)
    if type(create) is not bool or type(roots) is not tuple or not 1 <= len(roots) <= 2000:
        raise ValueError()
    source, destination = _path(source), _path(destination)
    normalized = tuple(_path(root, root=True) for root in roots)
    if len(set(map(ntpath.normcase, normalized))) != len(normalized):
        raise ValueError()
    if ntpath.normcase(source) == ntpath.normcase(destination) or not ntpath.basename(destination):
        raise ValueError()
    selections = []
    for path in (source, destination):
        matching = [root for root in normalized if _inside(path, root)]
        if not matching:
            raise ValueError()
        selections.append(max(matching, key=len))
    # A file cannot also be its own selected directory authorizer.
    if any(ntpath.normcase(path) == ntpath.normcase(root)
           for path, root in zip((source, destination), selections)):
        raise ValueError()
    return source, destination, selections[0], selections[1]


@dataclass
class _OwnedHandle:
    value: int
    state: str = "open"


@dataclass
class _Guard:
    parent: int
    path: str
    retain: bool
    record: _OwnedHandle | None = None


class _ProcessOwner:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = None
        self.quarantine = None


_OWNER = _ProcessOwner()  # Never reset: only a fresh OS worker process recovers.


class _Transaction:
    def __init__(self):
        self.handles = []
        self.parents = {}
        self.close_failed = False
        self.requests = []
        self.uncertain = False
        self.reason = ""
        self.source = self.destination = ""
        self.source_fingerprint = None
        self.source_identity = None
        self.owned_residue_paths = ()
        self.publication_attempted = self.published = False
        self.guards = {}

    def quarantine(self, reason):
        self.uncertain = True
        self.reason = reason
        _OWNER.quarantine = self
        _OWNER.active = None

    def open(self, path, **kwargs):
        handle = _open(path, **kwargs)
        self.handles.append(_OwnedHandle(handle))
        return handle

    def open_child(self, parent, name, *, directory=False, create=False, guard=False):
        request = _CreateRequest(parent, name)
        self.requests.append(request)
        access = 0x100081 if directory else (0x110081 if guard else 0x80110000)
        options = 0x200020 | (1 if directory else 0) | (0x1040 if guard else 0)
        try:
            request.state = "submitted"
            # WRITE sharing is needed for native relative rename; it is NOT a
            # reparse barrier. Retained nonempty guards provide that protection.
            status = _nt_create(request, access, 3 if directory else 0, 2 if create else 1, options)
            handle = request.capture(self)
            if status == 0x103:
                request.wait_result = _wait(handle or parent, 250)
                request.completion = request.block.status
                reason = "create-pending"
            elif type(status) is not int:
                reason = "create-completion"
            elif status < 0:
                reason = "create-output" if handle else ""
            elif (status != 0 or request.block.status != 0
                  or request.block.information != (2 if create else 1)
                  or not handle or handle == ctypes.c_void_p(-1).value):
                reason = "create-completion"
            else:
                reason = ""
            if reason:
                self.quarantine(reason)
                request.state = "uncertain"
                raise _Uncertain()
            request.state = "terminal"
            request.completion = status
            request.release(self)
            if status < 0:
                if status in (ctypes.c_int32(0xC0000280).value, ctypes.c_int32(0xC000050B).value):
                    raise _Unsupported()
                raise _NativeError(_nt.RtlNtStatusToDosError(status))
            return handle
        except BaseException:
            if request.state == "freed":
                raise
            # A submitted call may have filled the output slot before raising.
            # Never touch freed/possibly freed request storage again.
            if request.state != "free-uncertain":
                request.capture(self)
            if not self.uncertain:
                self.quarantine("create-submission")
                request.state = "uncertain"
            raise _Uncertain() from None

    def guard(self, parent, path, *, retain=False):
        if len(path) == 3 and path[1:] == ":\\":
            raise _Unsupported()  # A selected drive root grants no guard-at-anchor mutation.
        key = ntpath.normcase(path)
        if key in self.guards:
            self.guards[key].retain |= retain
            return
        # Callers supply only admitted selected-root descendants. Existing
        # pinned children protect all ancestors outside those selected roots.
        name = ".xuxia-move-" + secrets.token_hex(16) + ".tmp"
        guard_path = ntpath.join(path, name)
        if len(guard_path) > 4096:
            raise ValueError("Generated guard path exceeds the approved bound")
        owned = _Guard(parent, guard_path, retain)
        self.guards[key] = owned  # Possible owned path registered before submission.
        try:
            handle = self.open_child(parent, name, create=True, guard=True)
            owned.record = self.handles[-1]
            info = _info(handle)
            if info.attributes & (_DIRECTORY | _REPARSE) or info.fingerprint.size_bytes != 0:
                raise _Unsupported()
            self.check_directory(parent)
        except BaseException:
            if owned.record is None and not self.uncertain:
                del self.guards[key]  # A definitive rejected CREATE owns no object.
            raise

    @staticmethod
    def check_directory(handle):
        info = _info(handle)
        if info.attributes & _REPARSE or not info.attributes & _DIRECTORY:
            raise _Unsupported()
        return info

    def close_record(self, record):
        record.state = "closing"
        try:
            _close(record.value)
        except BaseException:
            self.close_failed = True
            record.state = "close-uncertain"
            self.quarantine("handle-close")
            raise _Uncertain() from None
        record.state = "closed"

    def release_guard(self, path, *, final=False):
        key = ntpath.normcase(path)
        owned = self.guards.get(key)
        if owned is None or owned.retain and not final:
            return
        self.close_record(owned.record)
        # Successful CloseHandle alone does not prove DELETE_ON_CLOSE removed
        # the entry: another ordinary attribute handle can keep it delete-pending.
        # Probe the name through the still-held parent, NEVER the closed handle.
        try:
            self.open_child(owned.parent, ntpath.basename(owned.path))
        except _NativeError as error:
            if error.winerror == 2:
                del self.guards[key]
                return
        except (_Unsupported, OSError, ValueError):
            pass
        self.quarantine("guard-removal")
        raise _Uncertain()

    def chain(self, parent, root, *, create=False):
        drive, tail = ntpath.splitdrive(parent)
        components = [drive + "\\"]
        for part in tail.strip("\\").split("\\") if tail.strip("\\") else []:
            components.append(ntpath.join(components[-1], part))
        previous = None
        for path in components:
            key = ntpath.normcase(path)
            if key in self.parents:
                previous = self.parents[key]
                continue
            try:
                handle = (self.open(path, directory=True) if previous is None else
                          self.open_child(previous, ntpath.basename(path), directory=True))
            except _NativeError as error:
                if error.winerror not in (2, 3):
                    raise
                if _inside(root, path):  # Drive/ancestors/selected root must already exist.
                    raise _InvalidRoot() from None
                if not create or not _inside(path, root):
                    raise
                parent_path = ntpath.dirname(path)
                self.guard(previous, parent_path)
                handle = self.open_child(previous, ntpath.basename(path), directory=True, create=True)
            self.check_directory(handle)
            self.parents[key] = handle
            if previous is not None:
                self.release_guard(ntpath.dirname(path))
            previous = handle
        return self.parents[ntpath.normcase(parent)]

    def close_all(self):
        if self.uncertain:
            return
        try:
            for path in tuple(self.guards):
                self.release_guard(path, final=True)
            for record in reversed(self.handles):
                if record.state == "open":
                    self.close_record(record)
        except _Uncertain:
            return  # First ambiguity stops ALL remaining cleanup, with ownership retained.


def _ordinary_key(error, phase):
    if isinstance(error, _CrossVolumeBlocked):
        return "SAFE_MOVE_CROSS_VOLUME_BLOCKED"
    if isinstance(error, _InvalidRoot):
        return "SAFE_MOVE_INVALID_ROOT"
    if isinstance(error, _Unsupported):
        return "SAFE_MOVE_UNSUPPORTED_METADATA"
    if isinstance(error, _Changed):
        return "SAFE_MOVE_SOURCE_CHANGED"
    code = getattr(error, "winerror", None)
    if phase == "source" and code in (32, 33):
        return "SAFE_MOVE_SOURCE_BUSY"
    if phase == "publication" and code in (80, 183):
        return "SAFE_MOVE_TARGET_OCCUPIED"
    return "SAFE_MOVE_MOVE_FAILED"


def safe_move(source: str, destination: str, *, expected_fingerprint: SourceFingerprint | None = None,
              expected_identity: NativeFileIdentity | None = None,
              allowed_roots: tuple[str, ...], create_parents: bool = True) -> SafeFileMoveResult:
    """Move only the admitted opened object; all uncertainty is explicit recovery.

    Empty validated descendant directories may remain on failure. Fingerprints
    are size/mtime, not a cryptographic pre-admission integrity guarantee.
    Identity-only admission supports historical Undo of the same edited file;
    Apply must always supply its existing approved fingerprint. Supplied proofs
    are independently enforced, and at least one valid proof is required.
    """
    requested_destination = destination
    try:
        source, destination, source_root, target_root = _validate(
            source, destination, expected_fingerprint, allowed_roots, create_parents, expected_identity)
    except (ValueError, UnicodeError):
        return SafeFileMoveResult(False, error_code="SAFE_MOVE_INVALID_INPUT")
    if not _WINDOWS or not _NATIVE_AVAILABLE:
        return SafeFileMoveResult(False, error_code="SAFE_MOVE_UNSUPPORTED_PLATFORM")

    if not _OWNER.lock.acquire(blocking=False):
        return SafeFileMoveResult(False, error_code="SAFE_MOVE_MOVE_FAILED")
    try:
        if _OWNER.quarantine is not None:
            return SafeFileMoveResult(False, error_code="SAFE_MOVE_RECOVERY_REQUIRED", recovery_required=True)
        transaction = _Transaction()
        _OWNER.active = transaction
        return _move_validated(source, destination, source_root, target_root,
                               expected_fingerprint, create_parents, requested_destination, transaction,
                               expected_identity)
    finally:
        _OWNER.active = None
        _OWNER.lock.release()


def _move_validated(source, destination, source_root, target_root, expected_fingerprint,
                    create_parents, requested_destination, transaction, expected_identity):
    transaction.source, transaction.destination = source, destination
    captured = None
    captured_identity = None
    recovery_needed = False
    residues = ()
    completed = False
    error_key = "SAFE_MOVE_MOVE_FAILED"
    phase = "ancestors"
    try:
        source_parent = transaction.chain(ntpath.dirname(source), source_root)
        phase = "source"
        source_handle = transaction.open_child(source_parent, ntpath.basename(source))
        original = _info(source_handle)
        if original.attributes & (_DIRECTORY | _REPARSE):
            raise _Unsupported()
        captured = original.fingerprint
        captured_identity = NativeFileIdentity(original.volume, original.index, original.creation)
        transaction.source_fingerprint = captured
        transaction.source_identity = captured_identity
        if ((expected_fingerprint is not None and captured != expected_fingerprint)
                or (expected_identity is not None and captured_identity != expected_identity)):
            raise _Changed()
        phase = "ancestors"
        # Refuse at the held EXISTING authorizer, before any descendant creation.
        target_authorizer = transaction.chain(target_root, target_root)
        if _info(target_authorizer).volume != original.volume:
            raise _CrossVolumeBlocked()
        if _filesystem(source_parent) != "NTFS" or _filesystem(target_authorizer) != "NTFS":
            raise _Unsupported()
        transaction.guard(source_parent, ntpath.dirname(source), retain=True)
        target_parent = transaction.chain(ntpath.dirname(destination), target_root, create=create_parents)
        if _info(target_parent).volume != original.volume:
            raise _CrossVolumeBlocked()
        transaction.guard(target_parent, ntpath.dirname(destination), retain=True)
        phase = "publication"
        transaction.publication_attempted = True
        _rename(source_handle, target_parent, ntpath.basename(destination))
        transaction.published = True
        check = _info(source_handle)
        if ((check.volume, check.index) != (original.volume, original.index)
                or check.fingerprint != captured):
            raise _Changed()
        # NTFS name tunneling may update creation metadata across this held
        # rename. Save its actual POST value for the next strict admission.
        captured_identity = NativeFileIdentity(check.volume, check.index, check.creation)
        transaction.source_identity = captured_identity
        completed = True
    except (_Unsupported, _InvalidRoot, _Changed, _CrossVolumeBlocked, OSError, ValueError) as error:
        error_key = _ordinary_key(error, phase)
        collision = phase == "publication" and getattr(error, "winerror", None) in (80, 183)
        # A native non-replacing collision is a definite no-mutation failure.
        # Other publication exceptions may have happened AFTER the real rename.
        recovery_needed = transaction.publication_attempted and not collision
        if recovery_needed:
            residues = (source, destination)
    finally:
        transaction.close_all()
        if transaction.uncertain:
            recovery_needed = True
            residues = tuple(dict.fromkeys((source, destination,
                *(guard.path for guard in transaction.guards.values()))))

    if recovery_needed:
        transaction.owned_residue_paths = residues
        return SafeFileMoveResult(False, error_code="SAFE_MOVE_RECOVERY_REQUIRED", recovery_required=True,
                                  source_fingerprint=captured, owned_residue_paths=residues,
                                  source_identity=captured_identity)
    if completed:
        return SafeFileMoveResult(True, new_path=requested_destination, source_fingerprint=captured,
                                  source_identity=captured_identity)
    return SafeFileMoveResult(False, error_code=error_key, source_fingerprint=captured,
                              source_identity=captured_identity)

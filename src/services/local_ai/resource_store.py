"""Windows-owned resource directory, pinned handles and nonblocking OS lease.

No ACL changes, PID files, recursive cleanup or pathname-based replacement.
An unsupported platform fails closed instead of emulating Windows pinning.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from .resource_transport import ResourceCancelled, ResourceError, SAFE_NAME
from src.core import safe_file_move as _native


MARKER = ".xuxia-local-resources.json"


class StoreOwnershipError(ResourceError):
    """The directory or an exact resource path cannot be trusted."""


class StoreBusy(ResourceError):
    """Another operation owns the nonblocking lease."""


class StoreOwnershipUncertain(StoreOwnershipError):
    """Opaque worker owner must remain retained; never project it into UI data."""
    def __init__(self, owner):
        super().__init__("NATIVE_OWNERSHIP_UNCERTAIN", code="NATIVE_OWNERSHIP_UNCERTAIN")
        self._retained_owner = owner

    @property
    def retained_owner(self):
        return self._retained_owner


def _local_path(value):
    try:
        if not isinstance(value, (str, Path)):
            raise ValueError()
        return Path(_native._path(str(value), root=True))
    except (TypeError, ValueError):
        raise StoreOwnershipError("UNSUPPORTED_STORE_PATH") from None


# Only ambiguous requests/handles are retained here. No frozen mutation owner is
# consulted or changed. A fresh OS process, not GC, recovers uncertain ownership.
_UNCERTAIN_DIRECTORY_OWNERS = []


class PreparedParentDirectories:
    """Independent relative-create request owner, scoped to one worker operation."""
    def __init__(self):
        if os.name != "nt" or not _native._NATIVE_AVAILABLE:
            raise StoreOwnershipError("UNSUPPORTED_STORE_PLATFORM")
        self.handles, self.requests = [], []
        self.directories, self.guards = {}, {}
        self.uncertain = False
        self.active = True

    @property
    def retained(self):
        return self.active or self.uncertain

    @property
    def idle(self):
        return not self.retained

    def quarantine(self, reason):
        self.reason = reason
        if not self.uncertain:
            self.uncertain = True
            _UNCERTAIN_DIRECTORY_OWNERS.append(self)

    def child(self, parent, name, *, directory=False, create=False, guard=False,
              writable=False, lease=False):
        request = _native._CreateRequest(parent, name)
        self.requests.append(request)
        access = 0x100081 if directory else 0x80100000
        if writable:
            access |= 0x40000000 | (0 if lease else 0x10000)
        if guard:
            access = 0x110081
        options = 0x200020 | (1 if directory else 0x40) | (0x1000 if guard else 0)
        try:
            request.state = "submitted"
            status = _native._nt_create(request, access, 3 if directory else 0 if guard else 1,
                                        2 if create else 1, options)
            handle = request.capture(self)
            if (type(status) is not int or status == 0x103
                    or status >= 0 and (status != 0 or request.block.status != 0
                        or request.block.information != (2 if create else 1) or not handle)
                    or status < 0 and handle):
                self.quarantine("directory-create-completion")
                request.state = "uncertain"
                raise StoreOwnershipUncertain(self)
            request.state = "terminal"
            request.completion = status
            request.release(self)
            if status < 0:
                code = _native._nt.RtlNtStatusToDosError(status)
                if code in (2, 3):
                    raise FileNotFoundError()
                if code in (80, 183):
                    raise FileExistsError()
                if lease and code in (32, 33):
                    raise StoreBusy("BUSY")
                raise StoreOwnershipError("UNSAFE_STORE_PATH")
            return handle
        except BaseException:
            if request.state == "freed":
                raise
            if request.state != "free-uncertain":
                request.capture(self)
            self.quarantine("directory-create-submission")
            raise StoreOwnershipUncertain(self) from None

    def pin_chain(self, path):
        for current in (*reversed(path.parents), path):
            if current in self.directories:
                continue
            if current.parent == current:
                handle = _native._open(str(current), directory=True)
                self.handles.append(_native._OwnedHandle(handle))
            else:
                handle = self.child(self.directories[current.parent], current.name, directory=True)
            self.directories[current] = handle
            self.check_directory(handle)
        return self.directories[path]

    @staticmethod
    def check_directory(handle):
        info = _native._info(handle)
        if info.attributes & 0x400 or not info.attributes & 0x10:
            raise StoreOwnershipError("UNSAFE_STORE_PATH")

    def guard(self, path):
        if path in self.guards:
            return self.guards[path][0]
        if path.parent == path:
            raise StoreOwnershipError("UNSUPPORTED_STORE_PATH")
        name = ".xuxia-resource-init-" + uuid.uuid4().hex + ".tmp"
        handle = self.child(self.directories[path], name, create=True, guard=True)
        self.guards[path] = (name, self.handles[-1])
        self.check_directory(self.directories[path])
        info = _native._info(handle)
        if info.attributes & 0x410 or info.fingerprint.size_bytes != 0:
            raise StoreOwnershipError("UNSAFE_STORE_PATH")
        return name

    def close_record(self, record):
        record.state = "closing"
        try:
            _native._close(record.value)
        except BaseException:
            record.state = "close-uncertain"
            self.quarantine("directory-handle-close")
            raise StoreOwnershipUncertain(self) from None
        record.state = "closed"

    def release_guard(self, path):
        name, record = self.guards[path]
        self.close_record(record)
        try:
            self.child(self.directories[path], name)
        except FileNotFoundError:
            del self.guards[path]
            return
        except BaseException:
            self.quarantine("directory-guard-unwind")
            raise StoreOwnershipUncertain(self) from None
        self.quarantine("directory-guard-remains")
        raise StoreOwnershipUncertain(self)

    def assert_safe(self):
        if self.uncertain:
            raise StoreOwnershipUncertain(self)
        if not self.active:
            raise StoreOwnershipError("PARENT_CAPABILITY_RELEASED")
        for handle in self.directories.values():
            self.check_directory(handle)

    def close(self):
        if self.uncertain:
            return False
        if not self.active:
            return True
        for path in tuple(reversed(self.guards)):
            self.release_guard(path)
        for record in reversed(self.handles):
            if record.state == "open":
                self.close_record(record)
        self.active = False
        return True

    def file(self, path, *, writable=False, create=False, lease=False):
        handle = self.child(self.directories[path.parent], path.name, writable=writable,
                            create=create, lease=lease)
        # Proven completed request transfers this one handle to its normal pin.
        record = self.handles.pop()
        assert record.value == handle
        pin = _PinnedFile.__new__(_PinnedFile)
        pin.handle, pin.writable = handle, writable
        try:
            pin.check()
        except BaseException:
            pin.close()
            raise
        return pin


@contextmanager
def _prepare_directory_parents(*, trusted_anchor, parents, cancelled=lambda: False,
                               max_missing=8):
    anchor = _local_path(trusted_anchor)
    targets = tuple(dict.fromkeys(_local_path(path) for path in parents))
    if (not targets or type(max_missing) is not int or not 0 <= max_missing <= 8
            or anchor.parent == anchor or any(not path.is_relative_to(anchor) for path in targets)):
        raise StoreOwnershipError("INVALID_PARENT_AUTHORITY")
    owner = PreparedParentDirectories()
    def check():
        if cancelled():
            raise ResourceCancelled("CANCELLED")
    try:
        check()
        owner.pin_chain(anchor)
        required = set()
        for target in targets:
            required.update(path for path in (*target.parents, target)
                            if path != anchor and path.is_relative_to(anchor))
        missing = []
        for path in sorted(required, key=lambda p: (len(p.parts), str(p).casefold())):
            check()
            if path.parent not in owner.directories:
                missing.append(path)
                continue
            try:
                handle = owner.child(owner.directories[path.parent], path.name, directory=True)
            except FileNotFoundError:
                missing.append(path)
            else:
                owner.directories[path] = handle
                owner.check_directory(handle)
        if len(missing) > max_missing:
            raise StoreOwnershipError("PARENT_CREATION_LIMIT")
        # No namespace mutation occurs until the entire missing union is bounded.
        for path in missing:
            check()
            owner.guard(path.parent)
            handle = owner.child(owner.directories[path.parent], path.name, directory=True, create=True)
            owner.directories[path] = handle
            owner.guard(path)
        for target in targets:
            check()
            owner.guard(target)
        owner.assert_safe()
        yield owner
        owner.assert_safe()
    except (FileNotFoundError, FileExistsError, _native._NativeError, _native._Unsupported):
        raise StoreOwnershipError("UNSAFE_PARENT_PATH") from None
    finally:
        owner.close()


if os.name == "nt":
    import msvcrt
    from ctypes import wintypes

    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _kernel.CreateFileW.restype = wintypes.HANDLE
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL
    _kernel.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                                      ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel.DuplicateHandle.restype = wintypes.BOOL

    class _Info(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("creation", wintypes.FILETIME),
                    ("access", wintypes.FILETIME), ("write", wintypes.FILETIME),
                    ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                    ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                    ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]

    _kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Info)]
    _kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    _kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _kernel.SetFileInformationByHandle.restype = wintypes.BOOL


class _PinnedFile:
    def __init__(self, path, *, directory=False, writable=False, create=False, lease=False):
        if os.name != "nt":
            raise StoreOwnershipError("UNSUPPORTED_STORE_PLATFORM")
        self.handle = None
        self.writable = writable
        access = 0x81 if directory else 0x80000000  # LIST_DIRECTORY + attributes
        if writable:
            access |= 0x40000000 | (0 if lease else 0x10000)  # GENERIC_WRITE, DELETE
        self.handle = _kernel.CreateFileW(str(path), access, 3 if directory else 1, None,
                                          1 if create else 3, 0x00200000 | (0x02000000 if directory else 0), None)
        if self.handle == ctypes.c_void_p(-1).value:
            self.handle = None
            code = ctypes.get_last_error()
            if lease and code in (32, 33):
                raise StoreBusy("BUSY")
            if code in (2, 3):
                raise FileNotFoundError()
            if create and code in (80, 183):
                raise FileExistsError()
            raise StoreOwnershipError("UNSAFE_STORE_PATH")
        try:
            self.check(directory=directory)
        except BaseException:
            self.close()
            raise

    def info(self):
        info = _Info()
        if not _kernel.GetFileInformationByHandle(self.handle, ctypes.byref(info)):
            raise StoreOwnershipError("UNSAFE_STORE_PATH")
        return info

    def check(self, *, directory=False):
        info = self.info()
        if info.attributes & 0x400 or bool(info.attributes & 0x10) != directory:
            raise StoreOwnershipError("UNSAFE_STORE_PATH")
        if not directory and info.links != 1:
            raise StoreOwnershipError("UNSAFE_STORE_FILE")
        return info

    def stream(self, mode="rb"):
        self.check()
        duplicate = wintypes.HANDLE()
        process = _kernel.GetCurrentProcess()
        if not _kernel.DuplicateHandle(process, self.handle, process, ctypes.byref(duplicate), 0, False, 2):
            raise StoreOwnershipError("UNSAFE_STORE_FILE")
        try:
            fd = msvcrt.open_osfhandle(duplicate.value, os.O_BINARY | (os.O_RDWR if self.writable else os.O_RDONLY))
        except BaseException:
            _kernel.CloseHandle(duplicate)
            raise
        stream = os.fdopen(fd, "r+b" if self.writable else "rb")
        stream.seek(0, os.SEEK_END if mode == "ab" else os.SEEK_SET)
        if mode == "wb":
            stream.truncate(0)
        return stream

    def rename(self, destination):
        self.check()
        name = str(destination)
        encoded_length = len(name.encode("utf-16-le"))

        class RenameInfo(ctypes.Structure):
            _fields_ = [("replace", wintypes.BOOLEAN), ("root", wintypes.HANDLE),
                        ("length", wintypes.DWORD), ("name", wintypes.WCHAR * (encoded_length // 2 + 1))]

        info = RenameInfo()
        info.replace = False
        info.root = None
        info.length = encoded_length
        info.name = name
        if not _kernel.SetFileInformationByHandle(self.handle, 3, ctypes.byref(info), ctypes.sizeof(info)):
            raise StoreOwnershipError("PUBLISH_CONFLICT")

    def close(self):
        if self.handle is not None:
            _kernel.CloseHandle(self.handle)
            self.handle = None


@contextmanager
def _owned_directory(path: Path, *, create=False):
    path = _local_path(path)
    owner = PreparedParentDirectories()
    try:
        owner.pin_chain(path.parent)
        try:
            owner.pin_chain(path)
        except FileNotFoundError:
            if not create:
                raise
            owner.guard(path.parent)
            handle = owner.child(owner.directories[path.parent], path.name, directory=True, create=True)
            owner.directories[path] = handle
            owner.guard(path)
        owner.assert_safe()
        yield path, owner
    finally:
        owner.close()


@contextmanager
def pinned_directory(path: Path, *, create=False):
    """Pin ancestors with LIST+ATTRS; only an explicit call may create one leaf."""
    with _owned_directory(path, create=create) as (root, owner):
        yield root
        owner.assert_safe()


@contextmanager
def source_files(path: Path, names):
    """Read-only pins for precisely the pinned catalog basenames, never a manifest."""
    held = {}
    try:
        with _owned_directory(path) as (root, owner):
            for name in names:
                if not isinstance(name, str) or not SAFE_NAME.fullmatch(name) or name.endswith("."):
                    raise StoreOwnershipError("UNSAFE_STORE_FILE")
                held[name] = owner.file(root / name)
            yield held
            owner.assert_safe()
    except FileNotFoundError:
        raise ResourceError("SOURCE_MISSING", code="SOURCE_MISSING") from None
    finally:
        for pin in held.values():
            pin.close()


class ResourceStore:
    def __init__(self, root: Path, catalog_id: str):
        self.root = Path(root)
        self.catalog_id = catalog_id
        self._lock = threading.Lock()
        self._files = {}
        self._missing = set()
        self._active = False
        self._readonly = False
        self._directory_owner = None

    @contextmanager
    def lease(self, *, create=False):
        with self._lease(create=create, readonly=False) as store:
            yield store

    @contextmanager
    def observe(self):
        """Read-only marker pin; excludes writers without initializing anything."""
        with self._lease(create=False, readonly=True) as store:
            yield store

    @contextmanager
    def _lease(self, *, create, readonly):
        if not self._lock.acquire(blocking=False):
            raise StoreBusy("BUSY")
        marker = None
        try:
            try:
                with _owned_directory(self.root, create=create) as (root, owner):
                    self.root = root
                    self._directory_owner = owner
                    self._readonly = readonly
                    marker_path = root / MARKER
                    try:
                        marker = owner.file(marker_path, writable=not readonly, lease=True)
                    except FileNotFoundError:
                        guard_name = owner.guards.get(root, (None,))[0]
                        if not create or any(child.name != guard_name for child in root.iterdir()):
                            raise StoreOwnershipError("UNOWNED_STORE") from None
                        guard_name = owner.guard(root)
                        if any(child.name != guard_name for child in root.iterdir()):
                            raise StoreOwnershipError("UNOWNED_STORE")
                        try:
                            marker = owner.file(marker_path, writable=True, create=True, lease=True)
                        except FileExistsError:
                            raise StoreBusy("BUSY") from None
                        payload = {"schema": 1, "catalog_id": self.catalog_id, "store_id": uuid.uuid4().hex}
                        with marker.stream("wb") as stream:
                            stream.write(json.dumps(payload, sort_keys=True).encode("utf-8"))
                            stream.flush()
                            os.fsync(stream.fileno())
                    with marker.stream() as stream:
                        raw = stream.read(4097)
                    try:
                        data = json.loads(raw)
                        valid = (len(raw) <= 4096 and isinstance(data, dict)
                                 and set(data) == {"schema", "catalog_id", "store_id"}
                                 and type(data["schema"]) is int and data["schema"] == 1
                                 and data["catalog_id"] == self.catalog_id
                                 and isinstance(data["store_id"], str)
                                 and re.fullmatch(r"[a-f0-9]{32}", data["store_id"]))
                    except (ValueError, UnicodeError, RecursionError):
                        valid = False
                    if not valid:
                        raise StoreOwnershipError("INVALID_STORE_MARKER")
                    # The exact pinned marker now keeps the leaf nonempty.
                    if root in owner.guards:
                        owner.release_guard(root)
                    owner.assert_safe()
                    self._active = True
                    yield self
            except FileNotFoundError:
                if self._active:
                    raise StoreOwnershipError("STORE_IO_FAILED") from None
                if create:
                    raise StoreOwnershipError("MISSING_STORE_PARENT") from None
                yield None
            except OSError:
                raise StoreOwnershipError("STORE_IO_FAILED") from None
        finally:
            self._active = False
            self._readonly = False
            self._directory_owner = None
            for pin in self._files.values():
                pin.close()
            self._files.clear()
            self._missing.clear()
            if marker is not None:
                marker.close()
            self._lock.release()

    def _name(self, name):
        if not self._active or not isinstance(name, str) or not SAFE_NAME.fullmatch(name) or name.endswith("."):
            raise StoreOwnershipError("UNSAFE_STORE_FILE")
        return name

    def pin(self, name, *, writable=False, create=False):
        name = self._name(name)
        if self._readonly and (writable or create):
            raise StoreOwnershipError("READONLY_STORE")
        if name not in self._files:
            try:
                pin = _PinnedFile(self.root / name, writable=writable, create=create)
            except FileExistsError:
                raise StoreOwnershipError("UNSAFE_STORE_SUBSTITUTION") from None
            if name in self._missing and not create:
                pin.close()
                raise StoreOwnershipError("UNSAFE_STORE_SUBSTITUTION")
            self._files[name] = pin
            self._missing.discard(name)
        pin = self._files[name]
        pin.check()
        if writable and not pin.writable:
            raise StoreOwnershipError("UNSAFE_STORE_FILE")
        return pin

    def exists(self, name):
        try:
            self.pin(name, writable=name.endswith(".part"))
            return True
        except FileNotFoundError:
            self._missing.add(name)
            return False

    def size(self, name):
        info = self.pin(name, writable=name.endswith(".part")).check()
        return (info.size_high << 32) | info.size_low

    def open_file(self, name, mode="rb"):
        writable = mode != "rb" or name.endswith(".part")
        if name in self._missing and mode != "rb":
            return self.pin(name, writable=True, create=True).stream(mode)
        try:
            pin = self.pin(name, writable=writable)
        except FileNotFoundError:
            if mode == "rb":
                raise
            pin = self.pin(name, writable=True, create=True)
        return pin.stream(mode)

    def publish(self, part, final):
        self.assert_safe()
        self._name(final)
        pin = self.pin(part, writable=True)
        pin.rename(self.root / final)
        self._files[final] = self._files.pop(part)
        return self.root / final

    def assert_safe(self):
        if self._directory_owner is not None:
            self._directory_owner.assert_safe()
        for pin in self._files.values():
            pin.check()

    def restart(self, name):
        if self.exists(name):
            self.publish(name, name + ".rejected-" + uuid.uuid4().hex)

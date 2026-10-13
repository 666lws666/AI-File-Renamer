"""Narrow, trusted fixed-hello staging. No CLI, launch, profile or ACL repair.

Threat boundary: a capability-less child, NOT malicious same-user/admin code.
CreateDirectory has no returned handle: exclusive success followed immediately
by nofollow pinned open and exact security/type readback establishes the initial
directory identity only under that boundary. Failed acquisition is uncertain.
Keep the live owner (including StageError.owner) until explicit cleanup/close.
There is deliberately no context manager, destructor or restart adoption.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import ntpath
import re
import secrets


# Windows SDK access/share/disposition constants; no handwritten native ABI.
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
DELETE = 0x10000
FILE_SHARE_READ = 1
FILE_SHARE_WRITE = 2
FILE_SHARE_DELETE = 4
CREATE_NEW = 1
OPEN_EXISTING = 3
OPEN_REPARSE_POINT = 0x00200000
BACKUP_SEMANTICS = 0x02000000
FILE_ALL_ACCESS = 0x1F01FF
FILE_READ_EXECUTE = 0x1200A9
FILE_GENERIC_READ = 0x120089
ALLOWED_CONTENT = b"xuxia-allowed-fixture-v1\r\n"
DENIED_CONTENT = b"xuxia-denied-fixture-v1\r\n"
MAX_BYTES = 4 * 1024 * 1024
_SID = re.compile(r"S-1-15-2(?:-(?:0|[1-9][0-9]{0,9})){7}", re.ASCII)
_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", re.I)


@dataclass(frozen=True)
class SecurityFacts:
    owner_sid: str
    protected: bool
    dacl_present: bool
    aces: tuple[tuple[int, int, int, str], ...]


@dataclass(frozen=True)
class ObjectInfo:
    volume_serial: int
    file_id: int
    size: int
    links: int
    directory: bool
    reparse: bool
    disk: bool

    @property
    def identity(self):
        return self.volume_serial, self.file_id


@dataclass(frozen=True)
class FixtureEvidence:
    filename: str
    path: str
    identity: tuple[int, int]
    sha256: str
    size: int
    file_links: int
    security: SecurityFacts


@dataclass(frozen=True)
class StageEvidence:
    directory_path: str
    executable_path: str
    directory_id: tuple[int, int]
    executable_id: tuple[int, int]
    sha256: str
    size: int
    file_links: int
    security: SecurityFacts
    fixtures: tuple[FixtureEvidence, ...] = ()


@dataclass(frozen=True)
class CleanupReport:
    complete: bool
    pending: bool
    handles_closed: bool
    remaining_paths: tuple[str, ...]
    uncertain_paths: tuple[str, ...]
    failures: tuple[str, ...]


class StageError(Exception):
    """Fixed stage code only; partial acquisitions retain their live owner."""
    def __init__(self, stage, owner=None):
        self.stage = stage
        self.owner = owner
        super().__init__(stage)


@dataclass
class _Object:
    path: str
    directory: bool
    handle: object = None
    identity: tuple[int, int] | None = None
    owned: bool = False
    uncertain: bool = False
    delete_handle: bool = False
    disposition: bool = False
    removed: bool = False
    security: SecurityFacts | None = None
    digest: str | None = None
    size: int | None = None


def _expected_security(user, package):
    return SecurityFacts(user, True, True, (
        (0, 0, FILE_ALL_ACCESS, user),
        (0, 0, FILE_ALL_ACCESS, "S-1-5-18"),
        (0, 0, FILE_READ_EXECUTE, package)))


def _fixture_security(user, package, *, allowed):
    return SecurityFacts(user, True, True, (
        (0, 0, FILE_ALL_ACCESS, user),
        (0, 0, FILE_ALL_ACCESS, "S-1-5-18"),
    ) + (((0, 0, FILE_GENERIC_READ, package),) if allowed else ()))


def _validate(parent, sid, data, digest):
    if (type(parent) is not str or not re.fullmatch(r"[A-Za-z]:\\.+", parent)
            or len(parent) > 180 or "/" in parent):
        raise StageError("path_input")
    parts = parent[3:].split("\\")
    if any(not p or p in (".", "..") or p[-1:] in (" ", ".")
           or any(ord(c) < 32 or c in '<>:"|?*' for c in p)
           or _RESERVED.fullmatch(p) for p in parts):
        raise StageError("path_input")
    if (type(sid) is not str or not _SID.fullmatch(sid)
            or any(int(p) > 0xFFFFFFFF for p in sid.split("-")[4:])):
        raise StageError("sid_input")
    if type(data) is not bytes or not 0 < len(data) <= MAX_BYTES:
        raise StageError("bytes_input")
    if (type(digest) is not str or not re.fullmatch("[0-9a-f]{64}", digest)
            or sha256(data).hexdigest() != digest):
        raise StageError("digest_input")


class OwnedProbe:
    """Thread-confined live ownership; retain this object through child teardown.

    recheck() is required immediately before future launch. cleanup(True) must
    only follow confirmed child cleanup. close_only() intentionally releases all
    pins without deletion and permanently forfeits automatic cleanup authority.
    """
    def __init__(self, native, parent, digest, size):
        self._native = native
        self._parent = parent
        self._digest = digest
        self._size = size
        self._ancestors = []
        self._directory = None
        self._file = None
        self._fixtures = []
        self._security = None
        self._volume = None
        self._evidence = None
        self._state = "creating"

    def _call(self, stage, function, *args):
        try:
            return function(*args)
        except BaseException:
            # Preserve handles even for interruption; never embed exception text.
            raise StageError(stage, self) from None

    def _check(self, obj, *, security=False, content=False):
        info = self._call("object_info", self._native.info, obj.handle)
        if (not info.disk or info.reparse or info.directory != obj.directory
                or info.volume_serial != self._volume or info.links != 1
                or not 0 < info.file_id < 1 << 64
                or obj.identity is not None and obj.identity != info.identity):
            raise StageError("object_identity", self)
        path = self._call("object_path", self._native.final_path, obj.handle)
        if ntpath.normcase(path) != ntpath.normcase(obj.path):
            raise StageError("object_path", self)
        if security and self._call("object_security", self._native.security,
                                   obj.handle) != (obj.security or self._security):
            raise StageError("object_security", self)
        if content:
            size = obj.size if obj.size is not None else self._size
            digest = obj.digest if obj.digest is not None else self._digest
            if info.size != size:
                raise StageError("object_size", self)
            data = self._call("object_read", self._native.read, obj.handle, size + 1)
            if type(data) is not bytes or len(data) != size or sha256(data).hexdigest() != digest:
                raise StageError("object_hash", self)
        return info

    def _ancestors_valid(self):
        for obj in self._ancestors:
            self._check(obj)

    def _open(self, obj, access, *, create=False):
        obj.handle = self._call("object_open", self._native.open, obj.path, access,
            FILE_SHARE_READ | (FILE_SHARE_WRITE if obj.directory else 0),
            CREATE_NEW if create else OPEN_EXISTING,
            OPEN_REPARSE_POINT | (BACKUP_SEMANTICS if obj.directory else 0),
            (obj.security or self._security) if create else None)

    def _close(self, obj):
        if obj.handle is not None:
            self._call("handle_close", self._native.close, obj.handle)
            obj.handle = None

    def _confirm_removed(self, obj):
        # Disposition is deferred until *all* opens close, not merely our own.
        # A path replacement or access-denied/delete-pending result is not proof
        # of removal; this read-only check never grants authority over a path.
        if self._call("removal_query", self._native.absent, obj.path) is not True:
            raise StageError("removal_unconfirmed", self)
        obj.removed = True

    @property
    def evidence(self):
        if self._evidence is None:
            raise StageError("evidence_unavailable", self)
        return self._evidence

    def recheck(self):
        if self._state != "ready":
            raise StageError("stage_not_ready", self)
        self._ancestors_valid()
        self._check(self._directory, security=True)
        self._check(self._file, security=True, content=True)
        for obj in self._fixtures:
            if obj.handle is None:
                self._open(obj, GENERIC_READ)
            try:
                self._check(obj, security=True, content=True)
            finally:
                self._close(obj)
        return self.evidence

    def _all_objects(self):
        return [o for o in [*self._fixtures, self._file, self._directory,
                            *reversed(self._ancestors)] if o is not None]

    def _report(self, failures=()):
        own = [o for o in (*self._fixtures, self._file, self._directory) if o is not None]
        remaining = tuple(o.path for o in own if not o.removed)
        uncertain = tuple(o.path for o in own if o.uncertain)
        closed = all(o.handle is None for o in self._all_objects())
        complete = not remaining and closed and not failures
        return CleanupReport(complete, not complete, closed, remaining, uncertain, tuple(failures))

    def _remove(self, obj):
        if obj.removed:
            return
        if not obj.owned or obj.uncertain or obj.identity is None:
            raise StageError("ownership_uncertain", self)
        # A successful disposition followed by failed close is retried as close,
        # not reopen: Windows may reject new opens once delete-pending is set.
        if obj.disposition:
            self._close(obj)
            self._confirm_removed(obj)
            return
        self._ancestors_valid()
        if not obj.delete_handle:
            if obj.handle is not None:
                self._check(obj)
                self._close(obj)
            # No delete-sharing pin may coexist with DELETE access. Parent pins
            # stay held; exact identity is revalidated before any disposition.
            # Failed acquisition returned no handle: preserve the expected ID
            # and permit a later retry, which must still verify the full object.
            self._open(obj, GENERIC_READ | DELETE)
            try:
                self._check(obj, security=True)
            except StageError:
                # An acquired but unverifiable/different object is never adopted.
                obj.uncertain = True
                raise
            obj.delete_handle = True
        self._check(obj, security=True)
        self._call("object_disposition", self._native.dispose, obj.handle)
        obj.disposition = True
        self._close(obj)
        self._confirm_removed(obj)

    def cleanup(self, *, child_cleanup_confirmed):
        if child_cleanup_confirmed is not True:
            return self._report(("child_cleanup_pending",))
        if self._state == "closed_only":
            return self._report(("close_only_no_authority",))
        if self._state == "removed":
            return self._report()
        self._state = "cleanup_pending"
        failures = []
        for obj in (*self._fixtures, self._file, self._directory):
            if obj is None:
                continue
            try:
                self._remove(obj)
            except StageError as exc:
                failures.append(exc.stage)
                # Never remove a parent after a file failure/uncertain child.
                break
        if not failures:
            for obj in reversed(self._ancestors):
                try:
                    self._close(obj)
                except StageError as exc:
                    failures.append(exc.stage)
        result = self._report(failures)
        if result.complete:
            self._state = "removed"
        return result

    def close_only(self):
        """Release pins explicitly; report leftovers, never assert removal."""
        if self._state != "removed":
            self._state = "closed_only"
        failures = []
        for obj in self._all_objects():
            try:
                self._close(obj)
                if obj.disposition:
                    self._confirm_removed(obj)
            except StageError as exc:
                failures.append(exc.stage)
        return self._report(failures)


def stage_probe(parent: str, package_sid: str, compiled_bytes: bytes,
                expected_sha256: str, *, include_fixtures: bool = False,
                _native=None) -> OwnedProbe:
    """Stage caller-trusted fixed hello bytes; caller retains return/error owner.

    parent is an existing local QA directory, not a general arbitrary copy root.
    SID comes from the separately prepared profile. No executable is ever run.
    """
    _validate(parent, package_sid, compiled_bytes, expected_sha256)
    if type(include_fixtures) is not bool:
        raise StageError("fixtures_input")
    # Entropy can fail: obtain it before any native resource exists so there is
    # no owner/handle to lose if the OS random source is unavailable.
    try:
        stage_name = "stage_" + secrets.token_hex(16)
    except BaseException:
        raise StageError("stage_entropy") from None
    if _native is None:
        try:
            _native = _Native()
        except Exception:
            raise StageError("native_bindings") from None
    owner = OwnedProbe(_native, parent, expected_sha256, len(compiled_bytes))
    fs, volume, drive = owner._call("volume_query", _native.volume, parent)
    if fs != "NTFS" or drive != 3 or type(volume) is not int or not 0 <= volume <= 0xFFFFFFFF:
        raise StageError("volume_unsupported", owner)
    owner._volume = volume
    user = owner._call("current_user", _native.current_user)
    owner._security = _expected_security(user, package_sid)
    path = parent[:3]
    paths = [path]
    for part in parent[3:].split("\\"):
        path = ntpath.join(path, part)
        paths.append(path)
    for path in paths:
        obj = _Object(path, True)
        owner._ancestors.append(obj)
        owner._open(obj, GENERIC_READ)
        obj.identity = owner._check(obj).identity
    owner._ancestors_valid()
    directory = _Object(ntpath.join(parent, stage_name), True, uncertain=True)
    owner._directory = directory
    owner._call("directory_create", _native.mkdir, directory.path, owner._security)
    # This immediate acquisition is the explicitly scoped initial proof, not
    # an atomic API guarantee against arbitrary same-user replacement.
    owner._open(directory, GENERIC_READ)
    info = owner._check(directory, security=True)
    owner._ancestors_valid()
    directory.identity, directory.owned, directory.uncertain = info.identity, True, False
    file = _Object(ntpath.join(directory.path, "hello.exe"), False, uncertain=True)
    owner._file = file
    owner._open(file, GENERIC_READ | GENERIC_WRITE, create=True)
    # CREATE_NEW returns the created object itself, unlike CreateDirectory.
    file.owned = True
    file.identity = owner._check(file, security=True).identity
    file.uncertain = False
    written = owner._call("file_write", _native.write, file.handle, compiled_bytes)
    if type(written) is not int or written != len(compiled_bytes):
        raise StageError("file_short_write", owner)
    owner._call("file_flush", _native.flush, file.handle)
    owner._check(file, security=True, content=True)
    # A writer handle blocks future image loading. Retain parent, close writer,
    # reacquire read-only/no-write/no-delete-sharing, then revalidate exactly.
    owner._close(file)
    try:
        owner._open(file, GENERIC_READ)
        owner._check(file, security=True, content=True)
    except StageError:
        file.uncertain = True
        raise
    owner._ancestors_valid()
    owner._check(directory, security=True)
    fixture_evidence = []
    if include_fixtures:
        for name, payload, allowed in (("allowed.txt", ALLOWED_CONTENT, True),
                                       ("denied.txt", DENIED_CONTENT, False)):
            fixture = _Object(ntpath.join(directory.path, name), False,
                              uncertain=True,
                              security=_fixture_security(user, package_sid, allowed=allowed),
                              digest=sha256(payload).hexdigest(), size=len(payload))
            owner._fixtures.append(fixture)
            owner._open(fixture, GENERIC_READ | GENERIC_WRITE, create=True)
            fixture.owned = True
            fixture.identity = owner._check(fixture, security=True).identity
            fixture.uncertain = False
            written = owner._call("file_write", _native.write, fixture.handle, payload)
            if type(written) is not int or written != len(payload):
                raise StageError("file_short_write", owner)
            owner._call("file_flush", _native.flush, fixture.handle)
            owner._check(fixture, security=True, content=True)
            owner._close(fixture)
            try:
                owner._open(fixture, GENERIC_READ)
                owner._check(fixture, security=True, content=True)
            except StageError:
                fixture.uncertain = True
                raise
            owner._close(fixture)
            fixture_evidence.append(FixtureEvidence(name, fixture.path, fixture.identity,
                fixture.digest, fixture.size, 1, fixture.security))
        owner._ancestors_valid()
        owner._check(directory, security=True)
    owner._evidence = StageEvidence(directory.path, file.path, directory.identity,
        file.identity, expected_sha256, len(compiled_bytes), 1, owner._security,
        tuple(fixture_evidence))
    owner._state = "ready"
    return owner


class _Native:
    """Lazy pywin32 adapter. Construction imports only; no OS object changes."""
    def __init__(self):
        import win32api
        import win32file
        import win32security
        import pywintypes
        self.api, self.file, self.security_api, self.types = win32api, win32file, win32security, pywintypes

    def current_user(self):
        s = self.security_api
        token = s.OpenProcessToken(self.api.GetCurrentProcess(), 8)
        try:
            return s.ConvertSidToStringSid(s.GetTokenInformation(token, s.TokenUser)[0])
        finally:
            token.Close()

    def volume(self, path):
        root = ntpath.splitdrive(path)[0] + "\\"
        info = self.api.GetVolumeInformation(root)
        # GetVolumeInformation uses signed C long; file information uses DWORD.
        return info[4], info[1] & 0xFFFFFFFF, self.file.GetDriveType(root)

    def _attributes(self, facts):
        s = self.security_api
        descriptor = s.SECURITY_DESCRIPTOR()
        descriptor.SetSecurityDescriptorOwner(s.ConvertStringSidToSid(facts.owner_sid), False)
        acl = s.ACL()
        for ace_type, flags, mask, sid in facts.aces:
            if ace_type != 0:
                raise ValueError("unsupported_ace")
            acl.AddAccessAllowedAceEx(s.ACL_REVISION, flags, mask, s.ConvertStringSidToSid(sid))
        descriptor.SetSecurityDescriptorDacl(True, acl, False)
        descriptor.SetSecurityDescriptorControl(0x1000, 0x1000)
        attrs = self.types.SECURITY_ATTRIBUTES()
        attrs.bInheritHandle = False
        attrs.SECURITY_DESCRIPTOR = descriptor
        return attrs

    def _security_facts(self, descriptor):
        s = self.security_api
        control = descriptor.GetSecurityDescriptorControl()[0]
        acl = descriptor.GetSecurityDescriptorDacl()
        aces = []
        if acl is not None:
            # Exact readback permits only the three basic ACCESS_ALLOWED ACEs.
            if acl.GetAceCount() > 3:
                raise ValueError("extra_aces")
            for i in range(acl.GetAceCount()):
                ace = acl.GetAce(i)
                if len(ace) != 3 or ace[0][0] != 0:
                    raise ValueError("unsupported_ace")
                aces.append((ace[0][0], ace[0][1], ace[1], s.ConvertSidToStringSid(ace[2])))
        return SecurityFacts(s.ConvertSidToStringSid(descriptor.GetSecurityDescriptorOwner()),
            bool(control & 0x1000), bool(control & 4) and acl is not None, tuple(aces))

    def mkdir(self, path, security):
        self.file.CreateDirectory(path, self._attributes(security))

    def open(self, path, access, share, creation, flags, security=None):
        # PyHANDLE has an automatic destructor and clears its stored value even
        # on Close failure. Detach immediately: explicit owner state controls
        # both lifetime and retry; abandoning this owner leaks pins intentionally.
        return self.file.CreateFile(path, access, share,
            self._attributes(security) if security else None, creation, flags, None).Detach()

    def info(self, handle):
        i = self.file.GetFileInformationByHandle(handle)
        return ObjectInfo(i[4], i[8] << 32 | i[9], i[5] << 32 | i[6], i[7],
                          bool(i[0] & 0x10), bool(i[0] & 0x400), self.file.GetFileType(handle) == 1)

    def security(self, handle):
        s = self.security_api
        return self._security_facts(s.GetSecurityInfo(handle, s.SE_FILE_OBJECT,
            s.OWNER_SECURITY_INFORMATION | s.DACL_SECURITY_INFORMATION))

    def final_path(self, handle):
        path = self.file.GetFinalPathNameByHandle(handle, 0)
        return path[4:] if path.startswith("\\\\?\\") else path

    def write(self, handle, data):
        error, count = self.file.WriteFile(handle, data)
        if error != 0:
            raise OSError("synchronous_write_failed")
        return count

    def flush(self, handle):
        self.file.FlushFileBuffers(handle)

    def read(self, handle, size):
        self.file.SetFilePointer(handle, 0, 0)
        error, data = self.file.ReadFile(handle, size)
        if error != 0:
            raise OSError("synchronous_read_failed")
        return data

    def read_at(self, handle, offset, size):
        """Bounded positional read for large staged files; never materialize a model."""
        if not 0 <= offset <= 5 * 1024**3 or not 0 < size <= 1024 * 1024:
            raise ValueError("read_bounds")
        self.file.SetFilePointer(handle, offset, 0)
        error, data = self.file.ReadFile(handle, size)
        if error != 0:
            raise OSError("synchronous_read_failed")
        return data

    def dispose(self, handle):
        # Upstream win32file.i: FileDispositionInfo takes a Boolean, not a dict.
        self.file.SetFileInformationByHandle(handle, self.file.FileDispositionInfo, True)

    def close(self, handle):
        self.file.CloseHandle(handle)

    def absent(self, path):
        try:
            # b312 win32api explicitly checks INVALID_FILE_ATTRIBUTES and raises;
            # win32file's unchecked DWORD wrapper can return -1 without raising.
            # Do not infer absence from a sentinel or stale thread last-error.
            attributes = self.api.GetFileAttributes(path)
        except self.types.error as exc:
            if exc.winerror in (2, 3):  # FILE_NOT_FOUND / PATH_NOT_FOUND only
                return True
            raise
        if type(attributes) is not int or not 0 <= attributes < 0xFFFFFFFF:
            raise ValueError("invalid_attribute_result")
        return False

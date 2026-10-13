"""Owned, read-only model bundle staging; never launches a process."""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import ntpath
from pathlib import Path
import re
import secrets
from typing import Callable

from src.services.local_ai.native.stage import (
    CREATE_NEW, FILE_GENERIC_READ, FILE_READ_EXECUTE, GENERIC_READ,
    GENERIC_WRITE, OPEN_EXISTING, OPEN_REPARSE_POINT, BACKUP_SEMANTICS,
    FILE_SHARE_READ, FILE_ALL_ACCESS, StageError,
    SecurityFacts, OwnedProbe, _Object, _Native, _validate, _RESERVED,
)

CHUNK = 1024 * 1024
MAX_MEMBER = 4 * 1024**3
MAX_TOTAL = 5 * 1024**3
MAX_PRIVATE_TEXT = 128 * 1024
MAX_PRIVATE_VISUALS = 16 * 1024 * 1024
_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", re.ASCII)
_VISUAL = re.compile(r"visual_(0[0-7])\.(jpg|png|webp)", re.ASCII)


@dataclass(frozen=True)
class StageMember:
    name: str
    source: Path
    size: int
    sha256: str
    executable: bool = False


@dataclass(frozen=True)
class StageBytesMember:
    name: str
    data: bytes = field(repr=False)


@dataclass(frozen=True)
class _PrivateExpected:
    size: int
    sha256: str = field(repr=False)


@dataclass(frozen=True)
class MemberEvidence:
    name: str
    source_path: str | None
    source_identity: tuple[int, int] | None
    path: str
    identity: tuple[int, int]
    size: int
    sha256: str = field(repr=False)
    security: SecurityFacts


@dataclass(frozen=True)
class BundleEvidence:
    directory_path: str
    directory_id: tuple[int, int]
    directory_security: SecurityFacts
    executable_path: str
    members: tuple[MemberEvidence, ...]


def _validate_input(parent, sid, members, entrypoint):
    _validate(parent, sid, b"x", sha256(b"x").hexdigest())
    if type(members) is not tuple or not 1 <= len(members) <= 80:
        raise StageError("members_input")
    names = set()
    total = 0
    visual_total = 0
    visual_indices = set()
    for member in members:
        if type(member) not in (StageMember, StageBytesMember):
            raise StageError("member_input")
        name = member.name
        if (type(name) is not str or not _NAME.fullmatch(name)
                or name.endswith(".") or _RESERVED.fullmatch(name)
                or name.casefold() in names):
            raise StageError("member_name")
        names.add(name.casefold())
        if type(member) is StageBytesMember:
            visual = _VISUAL.fullmatch(name)
            if name not in ("prompt.txt", "schema.json") and visual is None:
                raise StageError("member_name")
            if type(member.data) is not bytes or not member.data:
                raise StageError("member_bounds")
            limit = MAX_PRIVATE_VISUALS if visual else MAX_PRIVATE_TEXT
            if len(member.data) > limit:
                raise StageError("member_bounds")
            if visual:
                if visual.group(1) in visual_indices:
                    raise StageError("member_name")
                visual_indices.add(visual.group(1))
                visual_total += len(member.data)
                if visual_total > MAX_PRIVATE_VISUALS:
                    raise StageError("member_bounds")
            total += len(member.data)
            continue
        if not isinstance(member.source, Path) or not member.source.is_absolute():
            raise StageError("source_input")
        source = str(member.source)
        if (not re.fullmatch(r"[A-Za-z]:\\.+", source)
                or any(p in ("", ".", "..") or p.endswith((" ", "."))
                       or any(ord(c) < 32 or c in '<>:"|?*' for c in p)
                       for p in source[3:].split("\\"))):
            raise StageError("source_input")
        if (type(member.size) is not int or not 0 < member.size <= MAX_MEMBER
                or type(member.sha256) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", member.sha256)
                or type(member.executable) is not bool):
            raise StageError("member_bounds")
        if member.executable and not name.lower().endswith((".exe", ".dll")):
            raise StageError("member_rights")
        total += member.size
    if total > MAX_TOTAL:
        raise StageError("bundle_bounds")
    if (type(entrypoint) is not str or entrypoint.casefold() not in names
            or not any(type(m) is StageMember and m.name == entrypoint and m.executable
                       and m.name.lower().endswith(".exe") for m in members)):
        raise StageError("entrypoint_input")


def _file_security(user, package, executable):
    return SecurityFacts(user, True, True, (
        (0, 0, FILE_ALL_ACCESS, user),
        (0, 0, FILE_ALL_ACCESS, "S-1-5-18"),
        (0, 0, FILE_READ_EXECUTE if executable else FILE_GENERIC_READ, package),
    ))


class OwnedModelBundle(OwnedProbe):
    def __init__(self, native, parent):
        super().__init__(native, parent, "", 0)
        self._members = []
        self._source_pins = []
        self._member_sources = {}

    @property
    def directory_path(self):
        return self._directory.path if self._directory else None

    @property
    def executable_path(self):
        return self._file.path if self._file else None

    def _all_objects(self):
        return self._source_pins + super()._all_objects()

    def _source_check(self, obj, *, expected=None):
        info = self._call("source_info", self._native.info, obj.handle)
        path = self._call("source_path", self._native.final_path, obj.handle)
        if (not info.disk or info.reparse or info.directory != obj.directory
                or info.links != 1 or not 0 < info.file_id < 1 << 64
                or ntpath.normcase(path) != ntpath.normcase(obj.path)
                or obj.identity is not None and obj.identity != info.identity
                or expected is not None and info.size != expected):
            raise StageError("source_identity", self)
        return info

    def _pin_source(self, member):
        source = str(member.source)
        drive, tail = ntpath.splitdrive(source)
        path = drive + "\\"
        for part in [None, *tail.lstrip("\\").split("\\")[:-1]]:
            if part is not None:
                path = ntpath.join(path, part)
            obj = _Object(path, True)
            self._source_pins.append(obj)
            obj.handle = self._call("source_open", self._native.open, path,
                GENERIC_READ, FILE_SHARE_READ,
                OPEN_EXISTING, OPEN_REPARSE_POINT | BACKUP_SEMANTICS, None)
            obj.identity = self._source_check(obj).identity
        obj = _Object(source, False)
        self._source_pins.append(obj)
        obj.handle = self._call("source_open", self._native.open, source,
            GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING, OPEN_REPARSE_POINT, None)
        obj.identity = self._source_check(obj, expected=member.size).identity
        return obj

    def _source_chain_valid(self):
        for obj in self._source_pins:
            self._source_check(obj)

    def _hash_handle(self, handle, size, stage):
        digest = sha256()
        offset = 0
        while offset < size:
            self._cancel_check()
            block = self._call(stage, self._native.read_at, handle, offset,
                               min(CHUNK, size - offset))
            if type(block) is not bytes or not block or len(block) > min(CHUNK, size - offset):
                raise StageError("file_short_read", self)
            digest.update(block)
            offset += len(block)
        if self._call(stage, self._native.read_at, handle, size, 1) != b"":
            raise StageError("file_extra_bytes", self)
        return digest.hexdigest()

    def _cancel_check(self):
        try:
            cancelled = self._cancelled()
        except BaseException:
            raise StageError("cancelled", self) from None
        if cancelled:
            raise StageError("cancelled", self)

    def _verify_member(self, obj, member, *, hash_content):
        info = self._check(obj, security=True)
        if info.size != member.size:
            raise StageError("object_size", self)
        if hash_content and self._hash_handle(obj.handle, member.size, "object_read") != member.sha256:
            raise StageError("object_hash", self)

    def recheck(self):
        if self._state != "ready":
            raise StageError("stage_not_ready", self)
        try:
            self._ancestors_valid()
            self._check(self._directory, security=True)
            for obj, member in self._members:
                released = obj.handle is None
                if released:
                    self._open(obj, GENERIC_READ)
                self._verify_member(obj, member, hash_content=released)
        except StageError:
            # A failed revalidation can leave a newly acquired but unverified
            # read pin attached. It never becomes evidence of immutability.
            self._state = "invalid"
            raise
        return self.evidence

    def cleanup(self, *, child_cleanup_confirmed):
        if child_cleanup_confirmed is not True:
            return self._report(("child_cleanup_pending",))
        failures = []
        for obj in reversed(self._source_pins):
            try:
                self._close(obj)
            except StageError as exc:
                failures.append(exc.stage)
        result = super().cleanup(child_cleanup_confirmed=True)
        return self._report((*failures, *result.failures))


def stage_model_bundle(parent: str, package_sid: str,
                       members: tuple[StageMember | StageBytesMember, ...], entrypoint: str, *,
                       cancelled: Callable[[], bool] = lambda: False,
                       _native=None) -> OwnedModelBundle:
    _validate_input(parent, package_sid, members, entrypoint)
    if not callable(cancelled):
        raise StageError("cancel_input")
    try:
        stage_name = "stage_" + secrets.token_hex(16)
    except BaseException:
        raise StageError("stage_entropy") from None
    if _native is None:
        try:
            _native = _Native()
        except Exception:
            raise StageError("native_bindings") from None
    owner = OwnedModelBundle(_native, parent)
    owner._cancelled = cancelled
    owner._cancel_check()
    fs, volume, drive = owner._call("volume_query", _native.volume, parent)
    if fs != "NTFS" or drive != 3 or type(volume) is not int or not 0 <= volume <= 0xFFFFFFFF:
        raise StageError("volume_unsupported", owner)
    owner._volume = volume
    user = owner._call("current_user", _native.current_user)
    owner._security = SecurityFacts(user, True, True, (
        (0, 0, FILE_ALL_ACCESS, user), (0, 0, FILE_ALL_ACCESS, "S-1-5-18"),
        (0, 0, FILE_READ_EXECUTE, package_sid)))
    path = parent[:3]
    for part in [None, *parent[3:].split("\\")]:
        if part is not None:
            path = ntpath.join(path, part)
        obj = _Object(path, True)
        owner._ancestors.append(obj)
        owner._open(obj, GENERIC_READ)
        obj.identity = owner._check(obj).identity
    owner._ancestors_valid()
    directory = _Object(ntpath.join(parent, stage_name), True, uncertain=True)
    owner._directory = directory
    owner._call("directory_create", _native.mkdir, directory.path, owner._security)
    owner._open(directory, GENERIC_READ)
    info = owner._check(directory, security=True)
    owner._ancestors_valid()
    directory.identity, directory.owned, directory.uncertain = info.identity, True, False
    evidence = []
    for member in members:
        owner._cancel_check()
        in_memory = type(member) is StageBytesMember
        source = None if in_memory else owner._pin_source(member)
        if source is not None:
            owner._source_chain_valid()
        size = len(member.data) if in_memory else member.size
        digest_expected = sha256(member.data).hexdigest() if in_memory else member.sha256
        obj = _Object(ntpath.join(directory.path, member.name), False, uncertain=True,
                      security=_file_security(user, package_sid,
                                              not in_memory and (member.executable or member.name.lower().endswith(".dll"))),
                      digest=None if in_memory else digest_expected,
                      size=None if in_memory else size)
        expected = _PrivateExpected(size, digest_expected) if in_memory else member
        owner._members.append((obj, expected))
        if member.name == entrypoint:
            owner._file = obj
        else:
            owner._fixtures.append(obj)
        owner._open(obj, GENERIC_READ | GENERIC_WRITE, create=True)
        obj.owned = True
        obj.identity = owner._check(obj, security=True).identity
        obj.uncertain = False
        digest = sha256()
        offset = 0
        while offset < size:
            owner._cancel_check()
            if in_memory:
                block = member.data[offset:offset + CHUNK]
            else:
                block = owner._call("source_read", _native.read_at, source.handle,
                                    offset, min(CHUNK, size - offset))
                if type(block) is not bytes or not block or len(block) > min(CHUNK, size - offset):
                    raise StageError("source_short_read", owner)
            digest.update(block)
            written = owner._call("file_write", _native.write, obj.handle, block)
            if type(written) is not int or written != len(block):
                raise StageError("file_short_write", owner)
            offset += len(block)
        if source is not None:
            owner._source_chain_valid()
            if owner._call("source_read", _native.read_at, source.handle, size, 1) != b"":
                raise StageError("source_extra_bytes", owner)
        if digest.hexdigest() != digest_expected:
            raise StageError("source_hash", owner)
        owner._call("file_flush", _native.flush, obj.handle)
        owner._verify_member(obj, expected, hash_content=True)
        owner._close(obj)
        try:
            owner._open(obj, GENERIC_READ)
            owner._verify_member(obj, expected, hash_content=True)
        except StageError:
            obj.uncertain = True
            raise
        evidence.append(MemberEvidence(member.name,
                                       str(member.source) if source is not None else None,
                                       source.identity if source is not None else None,
                                       obj.path, obj.identity, size,
                                       digest_expected, obj.security))
    for obj in reversed(owner._source_pins):
        owner._close(obj)
    owner._ancestors_valid()
    owner._check(directory, security=True)
    owner._evidence = BundleEvidence(directory.path, directory.identity,
                                      owner._security, owner._file.path, tuple(evidence))
    owner._state = "ready"
    return owner

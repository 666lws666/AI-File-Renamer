"""Bounded, pinned inventory of the application's verified Windows runtime ZIP.

This module extracts data only. It neither selects nor starts an executable.
"""

from __future__ import annotations

import hashlib
import math
import os
import shutil
import stat
import time
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

from .resource_catalog import ResourceCatalog
from .resource_store import MARKER, ResourceStore, StoreBusy, StoreOwnershipError
from .resource_transport import (CHUNK_BYTES, DISK_RESERVE_BYTES, RESERVED_NAMES,
                                 SAFE_NAME, ResourceCancelled, ResourceError)


MAX_MEMBERS = 68
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_ZIP_METADATA_READ = 16 * 1024 * 1024
_REQUIRED = frozenset({"llama-completion.exe", "llama-mtmd-cli.exe"})


@dataclass(frozen=True, slots=True)
class RuntimeMember:
    name: str
    path: Path
    size: int
    sha256: str
    executable: bool


@dataclass(frozen=True, slots=True)
class RuntimeInventory:
    catalog_id: str
    runtime_release: str
    root: Path
    members: tuple[RuntimeMember, ...]


def _error(code):
    raise ResourceError(code, code=code)


def _check(cancelled, deadline):
    if cancelled():
        raise ResourceCancelled("CANCELLED", code="CANCELLED")
    if time.monotonic() >= deadline:
        _error("RUNTIME_TIMEOUT")


def _hash_stream(stream, check):
    digest = hashlib.sha256()
    count = 0
    while True:
        check()
        chunk = stream.read(CHUNK_BYTES)
        check()
        if not chunk:
            return count, digest.hexdigest()
        if not isinstance(chunk, bytes) or len(chunk) > CHUNK_BYTES:
            _error("RUNTIME_READ_FAILED")
        count += len(chunk)
        digest.update(chunk)


class _BoundedArchiveStream:
    """Allow zipfile's directory parse without an unbounded underlying read."""

    def __init__(self, source, check):
        self.source = source
        self.check = check

    def read(self, size=-1):
        if size < 0 or size > MAX_ZIP_METADATA_READ:
            _error("INVALID_RUNTIME_ARCHIVE")
        pieces = []
        remaining = size
        while remaining:
            self.check()
            piece = self.source.read(min(remaining, CHUNK_BYTES))
            self.check()
            if not piece:
                break
            pieces.append(piece)
            remaining -= len(piece)
        return b"".join(pieces)

    def seek(self, *args):
        return self.source.seek(*args)

    def tell(self):
        return self.source.tell()

    def seekable(self):
        return True


def _validate_members(archive, check):
    infos = archive.infolist()
    if not 1 <= len(infos) <= MAX_MEMBERS:
        _error("INVALID_RUNTIME_ARCHIVE")
    seen = set()
    total = 0
    for info in infos:
        check()
        name = info.filename
        mode = info.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if (not isinstance(name, str) or len(name) > 255 or not SAFE_NAME.fullmatch(name)
                or name.endswith(".") or name.split(".")[0].upper() in RESERVED_NAMES
                or name.casefold() == MARKER.casefold() or name.casefold() in seen
                or info.is_dir() or kind not in (0, stat.S_IFREG)
                or info.flag_bits & 1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                or info.file_size < 0 or info.file_size > MAX_EXPANDED_BYTES):
            _error("INVALID_RUNTIME_ARCHIVE")
        seen.add(name.casefold())
        total += info.file_size
        if total > MAX_EXPANDED_BYTES:
            _error("INVALID_RUNTIME_ARCHIVE")
    if not _REQUIRED <= seen or any((name + ".part").casefold() in seen for name in seen):
        _error("INVALID_RUNTIME_ARCHIVE")
    return sorted(infos, key=lambda info: (info.filename.casefold(), info.filename))


def _space(root, remaining, free_bytes):
    usage = free_bytes(root)
    available = usage.free if hasattr(usage, "free") else usage
    if type(available) is not int or available < remaining + DISK_RESERVE_BYTES:
        _error("INSUFFICIENT_SPACE")


def _verified_final(store, info, expected, check):
    if store.size(info.filename) != info.file_size:
        _error("RUNTIME_VERIFICATION_FAILED")
    with store.open_file(info.filename) as stream:
        count, digest = _hash_stream(stream, check)
    if count != info.file_size or digest != expected:
        _error("RUNTIME_VERIFICATION_FAILED")


def _remaining(store, infos):
    amount = 0
    for info in infos:
        if not store.exists(info.filename):
            part = info.filename + ".part"
            size = store.size(part) if store.exists(part) else 0
            if size > info.file_size:
                _error("RUNTIME_VERIFICATION_FAILED")
            amount += info.file_size - size
    return amount


def _extract_member(archive, store, info, expected, infos, check, free_bytes):
    final = info.filename
    part = final + ".part"
    if store.exists(final):
        _verified_final(store, info, expected, check)
        return
    offset = store.size(part) if store.exists(part) else 0
    if offset > info.file_size:
        _error("RUNTIME_VERIFICATION_FAILED")
    _space(store.root, _remaining(store, infos), free_bytes)
    with archive.open(info) as incoming:
        if offset:
            with store.open_file(part) as prefix:
                left = offset
                while left:
                    check()
                    chunk = prefix.read(min(CHUNK_BYTES, left))
                    other = incoming.read(len(chunk))
                    check()
                    if not chunk or chunk != other:
                        _error("RUNTIME_VERIFICATION_FAILED")
                    left -= len(chunk)
        check()
        with store.open_file(part, "ab" if offset else "wb") as output:
            count = offset
            while count < info.file_size:
                check()
                chunk = incoming.read(min(CHUNK_BYTES, info.file_size - count))
                check()
                if not chunk or len(chunk) > info.file_size - count:
                    _error("RUNTIME_VERIFICATION_FAILED")
                _space(store.root, _remaining(store, infos), free_bytes)
                store.assert_safe()
                output.write(chunk)
                count += len(chunk)
            # ZipExtFile verifies CRC when read through EOF, including zero-byte files.
            if incoming.read(1):
                _error("RUNTIME_VERIFICATION_FAILED")
            output.flush()
            os.fsync(output.fileno())
    if store.size(part) != info.file_size:
        _error("RUNTIME_VERIFICATION_FAILED")
    with store.open_file(part) as staged:
        count, digest = _hash_stream(staged, check)
    if count != info.file_size or digest != expected:
        _error("RUNTIME_VERIFICATION_FAILED")
    check()
    store.publish(part, final)


def prepare_runtime_inventory(resource_root: Path, runtime_root: Path,
                              catalog: ResourceCatalog, *, cancelled=lambda: False,
                              timeout_seconds=120.0, free_bytes=shutil.disk_usage) -> RuntimeInventory:
    """Verify a pinned archive and extract it into a separate owned runtime store."""
    if type(timeout_seconds) not in (int, float) or not isinstance(catalog, ResourceCatalog):
        _error("INVALID_RUNTIME_INPUT")
    try:
        timeout = float(timeout_seconds)
    except OverflowError:
        _error("INVALID_RUNTIME_INPUT")
    if not math.isfinite(timeout) or timeout <= 0:
        _error("INVALID_RUNTIME_INPUT")
    try:
        source_root = Path(os.path.abspath(resource_root))
        target_root = Path(os.path.abspath(runtime_root))
        source_case = os.path.normcase(source_root)
        target_case = os.path.normcase(target_root)
        try:
            overlapping = os.path.commonpath((source_case, target_case)) in (source_case, target_case)
        except ValueError:  # Different Windows volumes cannot overlap.
            overlapping = False
        if overlapping or not target_root.parent.is_dir():
            _error("INVALID_RUNTIME_ROOT")
        runtime = next((item for item in catalog.resources if item.id == "runtime-cpu"), None)
        if (runtime is None or len(catalog.identity) != 64 or not runtime.filename.endswith(".zip")
                or runtime.bytes <= 0 or len(runtime.sha256) != 64):
            _error("INVALID_RUNTIME_INPUT")
        deadline = time.monotonic() + timeout
        check = lambda: _check(cancelled, deadline)
        check()
        with ResourceStore(source_root, catalog.identity).lease() as source:
            if source is None or not source.exists(runtime.filename):
                _error("SOURCE_MISSING")
            if source.size(runtime.filename) != runtime.bytes:
                _error("RUNTIME_VERIFICATION_FAILED")
            with source.open_file(runtime.filename) as pinned_archive:
                count, digest = _hash_stream(pinned_archive, check)
                if count != runtime.bytes or digest != runtime.sha256:
                    _error("RUNTIME_VERIFICATION_FAILED")
                pinned_archive.seek(0)
                with zipfile.ZipFile(_BoundedArchiveStream(pinned_archive, check)) as archive:
                    infos = _validate_members(archive, check)
                    expected = {}
                    for info in infos:
                        check()
                        with archive.open(info) as member:
                            size, digest = _hash_stream(member, check)
                        if size != info.file_size:
                            _error("INVALID_RUNTIME_ARCHIVE")
                        expected[info.filename] = digest
                    check()
                    owned_id = catalog.identity + ":runtime:" + catalog.runtime_release
                    with ResourceStore(target_root, owned_id).lease(create=True) as target:
                        for info in infos:
                            check()
                            target.exists(info.filename)
                            target.exists(info.filename + ".part")
                        _space(target.root, _remaining(target, infos), free_bytes)
                        for info in infos:
                            check()
                            _extract_member(archive, target, info, expected[info.filename], infos, check, free_bytes)
                        members = []
                        for info in infos:
                            check()
                            _verified_final(target, info, expected[info.filename], check)
                            members.append(RuntimeMember(info.filename, target.root / info.filename,
                                                         info.file_size, expected[info.filename],
                                                         info.filename.lower().endswith((".exe", ".dll"))))
                        target.assert_safe()
                        return RuntimeInventory(catalog.identity, catalog.runtime_release,
                                                target.root, tuple(members))
    except (ResourceError, StoreBusy, StoreOwnershipError):
        raise
    except (OSError, ValueError, TypeError, OverflowError, EOFError, zlib.error, zipfile.BadZipFile,
            zipfile.LargeZipFile, RuntimeError):
        _error("RUNTIME_PREPARATION_FAILED")

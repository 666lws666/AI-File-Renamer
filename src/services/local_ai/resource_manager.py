"""Synchronous resource preparation only: no model launch or mode activation."""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .resource_catalog import RESOURCE_IDS, ResourceCatalog
from .resource_store import ResourceStore, StoreBusy, StoreOwnershipError, source_files
from .resource_transport import (CHUNK_BYTES, ResourceCancelled, ResourceError,
                                 _space, fetch_resource, urlopen, validate_resource)


class ResourceState(str, Enum):
    MISSING = "missing"
    PARTIAL = "partial"
    VERIFYING = "verifying"
    DOWNLOADING = "downloading"
    IMPORTING = "importing"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    AVAILABLE = "available"
    ERROR = "error"


@dataclass(frozen=True)
class ResourceSnapshot:
    state: ResourceState
    catalog_id: str
    verified_ids: tuple[str, ...]
    current_id: str | None
    received_bytes: int
    total_bytes: int
    error_code: str | None
    verified_bytes: int = 0
    acquired_bytes: int = 0
    remaining_bytes: int = 0  # Advisory: observed parts need not be reusable.


class _Paused(ResourceCancelled):
    pass


class ResourceManager:
    def __init__(self, root: Path, catalog: ResourceCatalog, *, opener=urlopen,
                 free_bytes=shutil.disk_usage):
        if (not isinstance(catalog, ResourceCatalog) or len(catalog.resources) != 3
                or {item.id for item in catalog.resources} != RESOURCE_IDS
                or len({item.filename.casefold() for item in catalog.resources}) != 3):
            raise ResourceError("INVALID_RESOURCE_CATALOG")
        for item in catalog.resources:
            validate_resource(item.as_transport_dict())
        self.root, self.catalog = Path(root), catalog
        self._opener, self._free_bytes = opener, free_bytes
        self._store = ResourceStore(self.root, catalog.identity)
        self._operation = threading.Lock()
        self._observation = threading.Lock()
        self._snapshot = ResourceSnapshot(ResourceState.MISSING, catalog.identity, (), None, 0,
                                          catalog.total_bytes, None, 0, 0, catalog.total_bytes)

    def snapshot(self) -> ResourceSnapshot:
        with self._observation:
            return self._snapshot

    def _set(self, state, *, verified=None, current=None, received=None, error=None, acquired=None):
        with self._observation:
            previous = self._snapshot
            identifiers = previous.verified_ids if verified is None else tuple(verified)
            actual = previous.acquired_bytes if acquired is None else acquired
            self._snapshot = ResourceSnapshot(state, self.catalog.identity,
                identifiers, current,
                previous.received_bytes if received is None else received,
                self.catalog.total_bytes, error,
                sum(item.bytes for item in self.catalog.resources if item.id in identifiers),
                actual, self.catalog.total_bytes - actual)
            return self._snapshot

    @staticmethod
    def _check(cancelled, paused):
        if paused():
            raise _Paused("PAUSED")
        if cancelled():
            raise ResourceCancelled("CANCELLED")

    def _hash(self, store, item, check):
        if store.size(item.filename) != item.bytes:
            raise ResourceError("VERIFICATION_FAILED", code="VERIFICATION_FAILED")
        digest = hashlib.sha256()
        count = 0
        with store.open_file(item.filename) as stream:
            while True:
                check()
                chunk = stream.read(CHUNK_BYTES)
                check()
                if not chunk:
                    break
                count += len(chunk)
                digest.update(chunk)
        if count != item.bytes or digest.hexdigest() != item.sha256:
            raise ResourceError("VERIFICATION_FAILED", code="VERIFICATION_FAILED")

    def _scan(self, store, check):
        verified, received, partial = [], 0, False
        acquired = 0
        # Pin every recognized file before transferring anything.
        for item in self.catalog.resources:
            check()
            store.exists(item.filename)
            if store.exists(item.filename + ".part"):
                size = store.size(item.filename + ".part")
                if size > item.bytes or store.exists(item.filename):
                    raise ResourceError("VERIFICATION_FAILED", code="VERIFICATION_FAILED")
                acquired += size
                partial = True
        self._set(ResourceState.VERIFYING, acquired=acquired)
        for item in self.catalog.resources:
            check()
            if store.exists(item.filename):
                self._set(ResourceState.VERIFYING, verified=verified, current=item.id, received=received)
                self._hash(store, item, check)
                verified.append(item.id)
                received += item.bytes
                acquired += item.bytes
                self._set(ResourceState.VERIFYING, verified=verified, received=received, acquired=acquired)
        return verified, received, partial

    def _run(self, action, *, create, cancelled, paused):
        if not self._operation.acquire(blocking=False):
            raise StoreBusy("BUSY")
        try:
            self._set(ResourceState.VERIFYING, verified=(), received=0, acquired=0)
            check = lambda: self._check(cancelled, paused)
            check()
            with self._store.lease(create=create) as store:
                if store is None:
                    return self._set(ResourceState.MISSING)
                try:
                    return action(store, check)
                except (OSError, ValueError):
                    # Normalize ordinary copy/hash I/O before the store's own
                    # ownership boundary handles lease-acquisition failures.
                    raise ResourceError("PREPARATION_FAILED", code="PREPARATION_FAILED") from None
        except (StoreBusy, StoreOwnershipError):
            self._set(ResourceState.ERROR, error="STORE_UNAVAILABLE")
            raise
        except _Paused:
            return self._set(ResourceState.PAUSED, current=self.snapshot().current_id, error="PAUSED")
        except ResourceCancelled:
            return self._set(ResourceState.CANCELLED, current=self.snapshot().current_id, error="CANCELLED")
        except ResourceError as error:
            code = error.code if error.code in {"INSUFFICIENT_SPACE", "VERIFICATION_FAILED", "SOURCE_MISSING", "PREPARATION_FAILED"} else "TRANSFER_FAILED"
            return self._set(ResourceState.ERROR, current=self.snapshot().current_id, error=code)
        except (OSError, ValueError):
            return self._set(ResourceState.ERROR, current=self.snapshot().current_id, error="PREPARATION_FAILED")
        finally:
            self._operation.release()

    def inspect(self, *, cancelled=lambda: False) -> ResourceSnapshot:
        def inspect_store(store, check):
            verified, received, partial = self._scan(store, check)
            state = (ResourceState.AVAILABLE if len(verified) == len(self.catalog.resources)
                     else ResourceState.PARTIAL if verified or partial else ResourceState.MISSING)
            return self._set(state, verified=verified, received=received)
        return self._run(inspect_store, create=False, cancelled=cancelled, paused=lambda: False)

    def _prepare(self, store, check, transfer, state, progress, selection=None):
        selection = self.catalog.resources if selection is None else selection
        verified, received, _ = self._scan(store, check)
        for item in selection:
            check()
            if item.id in verified:
                continue
            self._set(state, verified=verified, current=item.id, received=received)
            highwater = 0
            part = item.filename + ".part"
            prior_part = store.size(part) if store.exists(part) else 0
            other_acquired = self.snapshot().acquired_bytes - prior_part

            def update(identifier, count, total):
                nonlocal highwater
                highwater = max(highwater, count)
                self._set(state, verified=verified, current=identifier, received=received + highwater,
                          acquired=other_acquired + highwater)
                if progress is not None:
                    progress(identifier, highwater, total)

            remaining = sum(spec.bytes for spec in selection if spec.id not in verified)
            existing = sum(store.size(spec.filename + ".part")
                           for spec in selection if spec.id not in verified and store.exists(spec.filename + ".part"))
            _space(store.root, remaining - existing, self._free_bytes)
            transfer(store, item, check, update)
            check()
            self._set(ResourceState.VERIFYING, current=item.id)
            self._hash(store, item, check)
            verified.append(item.id)
            received += item.bytes
            self._set(state, verified=verified, received=received, acquired=other_acquired + item.bytes)
        # Every final was independently hashed under the same directory/file pins.
        check()
        store.assert_safe()
        return self._set(ResourceState.AVAILABLE if len(verified) == 3 else ResourceState.PARTIAL,
                         verified=verified, received=received)

    def _budget(self, store, current_id, selection=None):
        """Reserve unwritten bytes of the other resources on every capacity check."""
        def available(path):
            usage = self._free_bytes(path)
            free = usage.free if hasattr(usage, "free") else usage
            other = 0
            for item in self.catalog.resources if selection is None else selection:
                if item.id != current_id and not store.exists(item.filename):
                    part = item.filename + ".part"
                    size = store.size(part) if store.exists(part) else 0
                    if size > item.bytes:
                        raise ResourceError("VERIFICATION_FAILED", code="VERIFICATION_FAILED")
                    other += item.bytes - size
            return free - other
        return available

    def download(self, *, consent: bool = False, cancelled=lambda: False,
                 paused=lambda: False, progress=None) -> ResourceSnapshot:
        if consent is not True:
            raise ResourceError("EXPLICIT_CONSENT_REQUIRED")

        def transfer(store, item, check, update):
            def stopped():
                check()
                return False
            fetch_resource(item.as_transport_dict(), store.root, opener=self._opener,
                           cancelled=stopped, free_bytes=self._budget(store, item.id),
                           progress=update, owned_store=store)

        return self._run(lambda store, check: self._prepare(store, check, transfer, ResourceState.DOWNLOADING, progress),
                         create=True, cancelled=cancelled, paused=paused)

    def _import_item(self, store, item, source, check, update, selection):
        """One exact pinned offline transfer body, also used for runtime-only seed."""
        part = item.filename + ".part"
        offset = store.size(part) if store.exists(part) else 0
        if offset > item.bytes:
            raise ResourceError("VERIFICATION_FAILED", code="VERIFICATION_FAILED")
        digest = hashlib.sha256()
        with source.stream() as incoming:
            if offset:
                with store.open_file(part) as prefix:
                    left = offset
                    while left:
                        check()
                        chunk = prefix.read(min(CHUNK_BYTES, left))
                        other = incoming.read(len(chunk))
                        check()
                        if not chunk or chunk != other:
                            raise ResourceError("VERIFICATION_FAILED", code="VERIFICATION_FAILED")
                        digest.update(chunk)
                        left -= len(chunk)
                update(item.id, offset, item.bytes)
            with store.open_file(part, "ab" if offset else "wb") as output:
                while True:
                    check()
                    chunk = incoming.read(min(CHUNK_BYTES, item.bytes - offset + 1))
                    check()
                    if not chunk:
                        break
                    if len(chunk) > item.bytes - offset:
                        raise ResourceError("VERIFICATION_FAILED", code="VERIFICATION_FAILED")
                    _space(store.root, item.bytes - offset, self._budget(store, item.id, selection))
                    store.assert_safe()
                    if output.write(chunk) != len(chunk):
                        raise OSError()
                    digest.update(chunk)
                    offset += len(chunk)
                    update(item.id, offset, item.bytes)
                output.flush()
                os.fsync(output.fileno())
        if offset != item.bytes or digest.hexdigest() != item.sha256:
            raise ResourceError("VERIFICATION_FAILED", code="VERIFICATION_FAILED")
        check()
        store.publish(part, item.filename)

    def _import_selection(self, source, selection, *, cancelled, paused, progress):
        def import_store(store, check):
            with source_files(Path(source), [item.filename for item in selection]) as sources:
                def transfer(store, item, check, update):
                    self._import_item(store, item, sources[item.filename], check, update, selection)
                return self._prepare(store, check, transfer, ResourceState.IMPORTING, progress, selection)
        return self._run(import_store, create=True, cancelled=cancelled, paused=paused)

    def import_offline(self, source: Path, *, cancelled=lambda: False,
                       paused=lambda: False, progress=None) -> ResourceSnapshot:
        return self._import_selection(source, self.catalog.resources, cancelled=cancelled,
                                      paused=paused, progress=progress)

    def import_bundled_runtime(self, source: Path, *, cancelled=lambda: False,
                               progress=None) -> ResourceSnapshot:
        item = next(spec for spec in self.catalog.resources if spec.id == "runtime-cpu")
        source = Path(source)
        if source.name != item.filename:
            if not self._operation.acquire(blocking=False):
                raise StoreBusy("BUSY")
            try:
                return self._set(ResourceState.ERROR, error="SOURCE_MISSING")
            finally:
                self._operation.release()
        return self._import_selection(source.parent, (item,), cancelled=cancelled,
                                      paused=lambda: False, progress=progress)

    def repair_resource(self, resource_id: str) -> ResourceSnapshot:
        item = next((spec for spec in self.catalog.resources if spec.id == resource_id), None)
        if item is None:
            raise ResourceError("UNKNOWN_RESOURCE_ID")
        def repair(store, check):
            # Acquire writable pins before inspecting: readonly scan pins cannot
            # be upgraded, and the fresh lease never replaces an existing final.
            for name in (item.filename, item.filename + ".part"):
                try:
                    store.pin(name, writable=True)
                except FileNotFoundError:
                    continue
                store.publish(name, name + ".rejected-" + uuid.uuid4().hex)
            verified, received, partial = self._scan(store, check)
            return self._set(ResourceState.PARTIAL if verified or partial else ResourceState.MISSING,
                             verified=verified, received=received)
        return self._run(repair, create=False, cancelled=lambda: False, paused=lambda: False)

    def restart_partial(self, resource_id: str) -> None:
        item = next((spec for spec in self.catalog.resources if spec.id == resource_id), None)
        if item is None:
            raise ResourceError("UNKNOWN_RESOURCE_ID")
        def restart(store, check):
            store.restart(item.filename + ".part")
            # Rebuild from surviving files while this same exclusive lease is
            # held: quarantine bytes no longer count, unrelated files still do.
            verified, received, partial = self._scan(store, check)
            state = (ResourceState.AVAILABLE if len(verified) == len(self.catalog.resources)
                     else ResourceState.PARTIAL if verified or partial else ResourceState.MISSING)
            return self._set(state, verified=verified, received=received)
        self._run(restart, create=False, cancelled=lambda: False, paused=lambda: False)

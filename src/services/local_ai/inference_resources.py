"""Attest public local inference files while retaining their owned-store pins."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from .native.model_stage import StageMember
from .resource_catalog import ResourceCatalog, ResourceSpec, catalog_from_manifest
from .resource_store import MARKER, ResourceStore, StoreBusy, StoreOwnershipError
from .resource_transport import RESERVED_NAMES, ResourceCancelled, ResourceError, SAFE_NAME
from .runtime_inventory import RuntimeInventory, RuntimeMember, prepare_runtime_inventory


_HASH = re.compile(r"[0-9a-f]{64}\Z")
_CHUNK = 1024 * 1024
_MAX_TOTAL = 5 * 1024 ** 3


@dataclass(frozen=True, slots=True)
class AttestedResources:
    catalog_id: str
    runtime_release: str
    identity: str
    model_name: str
    projector_name: str | None
    members: tuple[StageMember, ...] = field(repr=False)


def _error(code: str):
    raise ResourceError(code, code=code) from None


def _check(cancelled, deadline):
    try:
        if cancelled():
            raise ResourceCancelled("CANCELLED", code="CANCELLED")
    except ResourceError:
        raise
    except BaseException:
        raise ResourceCancelled("CANCELLED", code="CANCELLED") from None
    if time.monotonic() >= deadline:
        _error("RESOURCE_TIMEOUT")


def _validate_catalog(catalog):
    if (type(catalog) is not ResourceCatalog or type(catalog.resources) is not tuple
            or any(type(item) is not ResourceSpec for item in catalog.resources)):
        _error("INVALID_INFERENCE_RESOURCES")
    try:
        manifest = {"schema_version": 1, "model_id": catalog.model_id,
                    "source_revision": catalog.source_revision,
                    "quantization_repository": catalog.quantization_repository,
                    "quantization_revision": catalog.quantization_revision,
                    "runtime_release": catalog.runtime_release,
                    "model_license": catalog.model_license,
                    "runtime_license": catalog.runtime_license,
                    "purpose": catalog.purpose,
                    "resources": [item.as_transport_dict() for item in catalog.resources]}
        rebuilt = catalog_from_manifest(manifest)
        if rebuilt != catalog:
            _error("INVALID_INFERENCE_RESOURCES")
    except (AttributeError, TypeError, ValueError, ResourceError):
        _error("INVALID_INFERENCE_RESOURCES")


def _select(inventory, runtime_root, catalog, include_vision):
    expected_root = Path(os.path.abspath(runtime_root))
    if (type(inventory) is not RuntimeInventory or inventory.catalog_id != catalog.identity
            or inventory.runtime_release != catalog.runtime_release or inventory.root != expected_root
            or type(inventory.members) is not tuple or not 1 <= len(inventory.members) <= 68):
        _error("INVALID_RUNTIME_INVENTORY")
    selected = []
    names = set()
    total = 0
    for member in inventory.members:
        if (type(member) is not RuntimeMember or type(member.name) is not str
                or not SAFE_NAME.fullmatch(member.name) or member.name.endswith(".")
                or member.name.split(".")[0].upper() in RESERVED_NAMES
                or member.name.casefold() == MARKER.casefold()
                or type(member.size) is not int or member.size <= 0
                or type(member.sha256) is not str or not _HASH.fullmatch(member.sha256)
                or type(member.executable) is not bool
                or member.executable != member.name.lower().endswith((".exe", ".dll"))
                or not isinstance(member.path, Path)
                or member.path != expected_root / member.name
                or member.name.casefold() in names):
            _error("INVALID_RUNTIME_INVENTORY")
        names.add(member.name.casefold())
        total += member.size
        selected.append(StageMember(member.name, member.path, member.size,
                                    member.sha256, member.executable))
    if tuple(selected) != tuple(sorted(selected, key=lambda item: (item.name.casefold(), item.name))):
        _error("INVALID_RUNTIME_INVENTORY")
    for identifier in ("model-q4", "vision-f16") if include_vision else ("model-q4",):
        spec = next(item for item in catalog.resources if item.id == identifier)
        if spec.filename.casefold() in names:
            _error("INVALID_INFERENCE_RESOURCES")
        names.add(spec.filename.casefold())
        total += spec.bytes
        selected.append((spec.filename, spec.bytes, spec.sha256))
    if len(selected) > 70 or total > _MAX_TOTAL:
        _error("INVALID_INFERENCE_RESOURCES")
    return selected, len(inventory.members)


def _verify(store, member, cancelled, deadline):
    _check(cancelled, deadline)
    if store.size(member.name) != member.size:
        _error("RESOURCE_VERIFICATION_FAILED")
    digest = hashlib.sha256()
    count = 0
    with store.open_file(member.name) as stream:
        while count < member.size:
            _check(cancelled, deadline)
            chunk = stream.read(min(_CHUNK, member.size - count))
            _check(cancelled, deadline)
            if type(chunk) is not bytes or not chunk or len(chunk) > member.size - count:
                _error("RESOURCE_VERIFICATION_FAILED")
            digest.update(chunk)
            count += len(chunk)
        _check(cancelled, deadline)
        extra = stream.read(1)
        _check(cancelled, deadline)
        if extra != b"" or digest.hexdigest() != member.sha256:
            _error("RESOURCE_VERIFICATION_FAILED")


@contextmanager
def attest_resources(resource_root: Path, runtime_root: Path,
                     catalog: ResourceCatalog, *, include_vision: bool,
                     cancelled=lambda: False, deadline: float):
    """Yield content-free evidence while both stores and selected files stay pinned."""
    if type(include_vision) is not bool or type(deadline) not in (int, float):
        _error("INVALID_INFERENCE_RESOURCES")
    try:
        limit = float(deadline)
    except (OverflowError, ValueError):
        _error("INVALID_INFERENCE_RESOURCES")
    if not math.isfinite(limit) or limit <= time.monotonic() or not callable(cancelled):
        _error("INVALID_INFERENCE_RESOURCES")
    _validate_catalog(catalog)
    def safe_cancelled():
        if time.monotonic() >= limit:
            _error("RESOURCE_TIMEOUT")
        try:
            was_cancelled = bool(cancelled())
        except BaseException:
            raise ResourceCancelled("CANCELLED", code="CANCELLED") from None
        if time.monotonic() >= limit:
            _error("RESOURCE_TIMEOUT")
        return was_cancelled

    preparing = True
    try:
        _check(safe_cancelled, limit)
        inventory = prepare_runtime_inventory(resource_root, runtime_root, catalog,
                                              cancelled=safe_cancelled,
                                              timeout_seconds=limit - time.monotonic())
        _check(safe_cancelled, limit)
        selected, runtime_count = _select(inventory, runtime_root, catalog, include_vision)
        with ExitStack() as stack:
            source = stack.enter_context(ResourceStore(resource_root, catalog.identity).lease())
            if source is None:
                _error("RESOURCE_MISSING")
            _check(safe_cancelled, limit)
            target = stack.enter_context(ResourceStore(runtime_root, catalog.identity +
                                      ":runtime:" + catalog.runtime_release).lease())
            if target is None:
                _error("RESOURCE_MISSING")
            members = []
            for index, selected_member in enumerate(selected):
                _check(safe_cancelled, limit)
                if index < runtime_count:
                    member = selected_member
                    store = target
                else:
                    name, size, sha256 = selected_member
                    member = StageMember(name, source.root / name, size, sha256, False)
                    store = source
                try:
                    store.pin(member.name)
                except FileNotFoundError:
                    _error("RESOURCE_MISSING")
                members.append(member)
            for index, member in enumerate(members):
                _verify(target if index < runtime_count else source, member, safe_cancelled, limit)
            source.assert_safe()
            target.assert_safe()
            payload = {"schema": 1, "catalog_id": catalog.identity,
                       "runtime_release": catalog.runtime_release, "vision": include_vision,
                       "members": [{"name": item.name, "size": item.size,
                                    "sha256": item.sha256, "executable": item.executable}
                                   for item in members]}
            identity = hashlib.sha256(json.dumps(payload, sort_keys=True,
                                                 separators=(",", ":"), ensure_ascii=False)
                                      .encode("utf-8")).hexdigest()
            result = AttestedResources(catalog.identity, catalog.runtime_release, identity,
                                       next(item.filename for item in catalog.resources if item.id == "model-q4"),
                                       next(item.filename for item in catalog.resources if item.id == "vision-f16")
                                       if include_vision else None, tuple(members))
            source.assert_safe()
            target.assert_safe()
            _check(safe_cancelled, limit)
            preparing = False
            yield result
    except (StoreBusy, ResourceCancelled):
        raise
    except (ResourceError, StoreOwnershipError) as error:
        if not preparing:
            raise
        if getattr(error, "code", None) in {"INVALID_INFERENCE_RESOURCES", "INVALID_RUNTIME_INVENTORY",
                                               "RESOURCE_TIMEOUT", "RESOURCE_MISSING",
                                               "RESOURCE_VERIFICATION_FAILED"}:
            raise
        if getattr(error, "code", None) == "RUNTIME_TIMEOUT":
            _error("RESOURCE_TIMEOUT")
        if getattr(error, "code", None) == "SOURCE_MISSING":
            _error("RESOURCE_MISSING")
        if getattr(error, "code", None) == "RUNTIME_VERIFICATION_FAILED":
            _error("RESOURCE_VERIFICATION_FAILED")
        _error("RESOURCE_PREPARATION_FAILED")
    except (OSError, ValueError, TypeError, OverflowError, RuntimeError, EOFError):
        if not preparing:
            raise
        _error("RESOURCE_PREPARATION_FAILED")

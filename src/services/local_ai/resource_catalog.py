"""Immutable, bounded metadata for the three pinned feasibility resources."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from .resource_transport import ResourceError, validate_resource


MAX_MANIFEST_BYTES = 64 * 1024
MAX_RESOURCE_BYTES = 4 * 1024 ** 3
MAX_TOTAL_BYTES = 5 * 1024 ** 3
RESOURCE_IDS = frozenset({"runtime-cpu", "model-q4", "vision-f16"})
RESOURCE_KEYS = frozenset({"id", "filename", "url", "bytes", "sha256"})
HEX_REVISION = re.compile(r"[a-f0-9]{40}\Z")
RUNTIME_RELEASE = re.compile(r"b[0-9]+\Z")


@dataclass(frozen=True, slots=True)
class ResourceSpec:
    id: str
    filename: str
    url: str
    bytes: int
    sha256: str

    def as_transport_dict(self) -> dict:
        return {"id": self.id, "filename": self.filename, "url": self.url,
                "bytes": self.bytes, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class ResourceCatalog:
    model_id: str
    source_revision: str
    quantization_repository: str
    quantization_revision: str
    runtime_release: str
    model_license: str
    runtime_license: str
    purpose: str
    resources: tuple[ResourceSpec, ...]
    identity: str

    @property
    def total_bytes(self) -> int:
        return sum(item.bytes for item in self.resources)


def _required_text(manifest: dict, key: str, expected: str) -> str:
    value = manifest.get(key)
    if value != expected or type(value) is not str:
        raise ResourceError("invalid resource catalog metadata")
    return value


def _revision(manifest: dict, key: str) -> str:
    value = manifest.get(key)
    if not isinstance(value, str) or not HEX_REVISION.fullmatch(value):
        raise ResourceError("invalid resource catalog revision")
    return value


def catalog_from_manifest(manifest: dict) -> ResourceCatalog:
    """Validate pinned application metadata without I/O or mutable aliases."""
    if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise ResourceError("invalid resource catalog schema")
    model_id = _required_text(manifest, "model_id", "Qwen/Qwen3.5-4B")
    source_revision = _revision(manifest, "source_revision")
    quantization_repository = _required_text(manifest, "quantization_repository", "unsloth/Qwen3.5-4B-GGUF")
    quantization_revision = _revision(manifest, "quantization_revision")
    runtime_release = manifest.get("runtime_release")
    if not isinstance(runtime_release, str) or not RUNTIME_RELEASE.fullmatch(runtime_release):
        raise ResourceError("invalid resource catalog release")
    model_license = _required_text(manifest, "model_license", "Apache-2.0")
    runtime_license = _required_text(manifest, "runtime_license", "MIT")
    purpose = manifest.get("purpose")
    if (not isinstance(purpose, str) or not purpose.strip() or len(purpose) > 120
            or any(not char.isprintable() for char in purpose)):
        raise ResourceError("invalid resource catalog purpose")

    raw_resources = manifest.get("resources")
    if not isinstance(raw_resources, list) or len(raw_resources) != 3:
        raise ResourceError("invalid resource catalog resources")
    resources = []
    ids = set()
    filenames = set()
    for raw in raw_resources:
        if not isinstance(raw, dict) or raw.keys() != RESOURCE_KEYS:
            raise ResourceError("invalid resource catalog resource fields")
        validate_resource(raw)
        identifier = raw["id"]
        filename = raw["filename"]
        if identifier.casefold() in ids or filename.casefold() in filenames:
            raise ResourceError("duplicate resource catalog entry")
        ids.add(identifier.casefold())
        filenames.add(filename.casefold())
        if identifier not in RESOURCE_IDS or raw["bytes"] > MAX_RESOURCE_BYTES:
            raise ResourceError("invalid resource catalog resource")
        if identifier == "runtime-cpu":
            expected_url = f"https://github.com/ggml-org/llama.cpp/releases/download/{runtime_release}/{filename}"
            valid_type = filename.endswith(".zip")
        else:
            expected_url = (f"https://huggingface.co/{quantization_repository}/resolve/"
                            f"{quantization_revision}/{filename}")
            valid_type = filename.endswith(".gguf")
        if not valid_type or raw["url"] != expected_url:
            raise ResourceError("invalid resource catalog resource URL or type")
        resources.append(ResourceSpec(identifier, filename, raw["url"], raw["bytes"], raw["sha256"]))
    if ids != RESOURCE_IDS or sum(item.bytes for item in resources) > MAX_TOTAL_BYTES:
        raise ResourceError("invalid resource catalog resource set or size")

    resources_tuple = tuple(resources)
    identity_payload = {
        "model_id": model_id,
        "source_revision": source_revision,
        "quantization_repository": quantization_repository,
        "quantization_revision": quantization_revision,
        "runtime_release": runtime_release,
        "model_license": model_license,
        "runtime_license": runtime_license,
        "purpose": purpose,
        "resources": [item.as_transport_dict() for item in sorted(resources_tuple, key=lambda item: item.id)],
    }
    serialized = json.dumps(identity_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    identity = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return ResourceCatalog(model_id, source_revision, quantization_repository,
                           quantization_revision, runtime_release, model_license,
                           runtime_license, purpose, resources_tuple, identity)


def load_resource_catalog(path: Path) -> ResourceCatalog:
    """Load only a regular UTF-8 JSON file of at most 64 KiB."""
    try:
        path = Path(path)
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_MANIFEST_BYTES:
            raise ResourceError("invalid resource catalog")
        with path.open("rb") as stream:
            data = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(data) > MAX_MANIFEST_BYTES:
            raise ResourceError("invalid resource catalog")
        return catalog_from_manifest(json.loads(data.decode("utf-8")))
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError, ResourceError):
        raise ResourceError("invalid resource catalog") from None

"""Safe provider boundary for locally extracted, explicitly prepared content.

The factory boundary is an application invariant, not a cryptographic sandbox: Python
callers can introspect private names.  Normal application code cannot construct a
``PreparedVisualPayload`` directly and must use the validated preprocessing factory.
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional


_ALLOWED_VISUAL_KINDS = frozenset(
    {"resized_image", "rendered_scan_page", "video_keyframe"}
)
_ALLOWED_IMAGE_MIME_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/webp"}
)
_PREPROCESSING_CONSTRUCTION_TOKEN = object()
_BANNED_KEYS = frozenset(
    {
        "path",
        "filepath",
        "sourcepath",
        "apikey",
        "authorization",
        "authtoken",
        "accesstoken",
        "token",
        "secret",
        "password",
        "requestbody",
    }
)
_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _looks_like_absolute_path(value: str) -> bool:
    return (
        value.startswith(("/", "\\\\", "file://"))
        or _WINDOWS_ABSOLUTE_PATH.match(value) is not None
    )


def _freeze_safe_value(value: Any, *, reject_paths: bool) -> Any:
    """Validate and recursively freeze values crossing the provider boundary."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if reject_paths and _looks_like_absolute_path(value):
            raise ValueError("Raw filesystem paths are not valid provider metadata")
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError("Raw binary data is only allowed in PreparedVisualPayload")
    if isinstance(value, (Path, io.IOBase)) or hasattr(value, "read"):
        raise TypeError("Paths and file handles cannot cross the provider boundary")
    if isinstance(value, Mapping):
        frozen = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise TypeError("Provider metadata keys must be strings")
            if _normalized_key(key) in _BANNED_KEYS:
                raise ValueError(f"Forbidden provider field: {key}")
            frozen[key] = _freeze_safe_value(child, reject_paths=reject_paths)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_safe_value(child, reject_paths=reject_paths) for child in value
        )
    raise TypeError(f"Unsupported provider value type: {type(value).__name__}")


def _thaw_safe_value(value: Any) -> Any:
    """Return a JSON-serializable copy without reintroducing mutable internals."""
    if isinstance(value, Mapping):
        return {key: _thaw_safe_value(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw_safe_value(child) for child in value]
    return value


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    text: bool = False
    vision: bool = False
    multi_image: bool = False
    json_mode: bool = False
    json_schema: bool = False
    streaming: bool = False
    tool_calling: bool = False


@dataclass(frozen=True, slots=True, init=False)
class PreparedVisualPayload:
    """Validated local preprocessing output; never a raw image, PDF, or video."""

    kind: str
    mime_type: str
    data: bytes
    content_digest: str
    width: int
    height: int
    byte_size: int
    source_index: int
    preprocessing_version: str
    provenance: str

    def __init__(
        self,
        kind: str,
        mime_type: str,
        data: bytes,
        content_digest: str,
        width: int,
        height: int,
        byte_size: int,
        source_index: int = -1,
        preprocessing_version: str = "",
        provenance: str = "",
        *,
        _construction_token: object | None = None,
    ) -> None:
        if _construction_token is not _PREPROCESSING_CONSTRUCTION_TOKEN:
            raise TypeError(
                "PreparedVisualPayload must be created by prepare_visual_payload()"
            )
        if kind not in _ALLOWED_VISUAL_KINDS:
            raise ValueError(f"Invalid prepared visual kind: {kind}")
        if mime_type not in _ALLOWED_IMAGE_MIME_TYPES:
            raise ValueError(f"Invalid prepared visual MIME type: {mime_type}")
        if not isinstance(data, bytes) or not data:
            raise ValueError("Prepared visual data must be non-empty bytes")
        if width <= 0 or height <= 0:
            raise ValueError("Prepared visual dimensions must be positive")
        if source_index < 0:
            raise ValueError("Prepared visual source_index must be non-negative")
        if byte_size != len(data):
            raise ValueError("Prepared visual byte_size does not match data")
        expected_digest = hashlib.sha256(data).hexdigest()
        if content_digest != expected_digest:
            raise ValueError("Prepared visual content digest does not match data")
        if not preprocessing_version.strip() or not provenance.strip():
            raise ValueError("Preprocessing version and provenance are required")

        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "mime_type", mime_type)
        object.__setattr__(self, "data", data)
        object.__setattr__(self, "content_digest", content_digest)
        object.__setattr__(self, "width", width)
        object.__setattr__(self, "height", height)
        object.__setattr__(self, "byte_size", byte_size)
        object.__setattr__(self, "source_index", source_index)
        object.__setattr__(self, "preprocessing_version", preprocessing_version)
        object.__setattr__(self, "provenance", provenance)


def prepare_visual_payload(
    *,
    kind: str,
    mime_type: str,
    data: bytes,
    width: int,
    height: int,
    source_index: int,
    preprocessing_version: str,
    provenance: str,
) -> PreparedVisualPayload:
    """Create the only binary payload type accepted by ``ProviderRequest``."""
    if not isinstance(data, bytes):
        raise TypeError("Prepared visual data must be bytes")
    return PreparedVisualPayload(
        kind=kind,
        mime_type=mime_type,
        data=data,
        content_digest=hashlib.sha256(data).hexdigest(),
        width=width,
        height=height,
        byte_size=len(data),
        source_index=source_index,
        preprocessing_version=preprocessing_version,
        provenance=provenance,
        _construction_token=_PREPROCESSING_CONSTRUCTION_TOKEN,
    )


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    request_id: str
    task_id: str
    extracted_text: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    visual_payloads: tuple[PreparedVisualPayload, ...] = field(default_factory=tuple)
    requested_schema: Optional[Mapping[str, Any]] = None
    quality_mode: str = "balanced"
    locale: str = "en-US"
    model: str = ""
    timeout: int = 30
    correlation_id: str = ""

    def __post_init__(self) -> None:
        if not self.request_id or not self.task_id:
            raise ValueError("request_id and task_id are required")
        if self.timeout <= 0:
            raise ValueError("Provider timeout must be positive")
        payloads = tuple(self.visual_payloads)
        for payload in payloads:
            if not isinstance(payload, PreparedVisualPayload):
                raise TypeError(
                    "Visual payloads must be validated PreparedVisualPayload instances"
                )
        object.__setattr__(self, "visual_payloads", payloads)
        object.__setattr__(
            self,
            "metadata",
            _freeze_safe_value(self.metadata, reject_paths=True),
        )
        if self.requested_schema is not None:
            object.__setattr__(
                self,
                "requested_schema",
                _freeze_safe_value(self.requested_schema, reject_paths=False),
            )


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    fields: Mapping[str, Any] = field(default_factory=dict)
    usage: Mapping[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    model_used: str = ""
    provider_profile_id: str = ""
    correlation_id: str = ""

    def __post_init__(self) -> None:
        if self.latency_ms < 0:
            raise ValueError("Provider latency cannot be negative")
        object.__setattr__(
            self, "fields", _freeze_safe_value(self.fields, reject_paths=False)
        )
        object.__setattr__(
            self, "usage", _freeze_safe_value(self.usage, reject_paths=False)
        )

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "fields": _thaw_safe_value(self.fields),
            "usage": _thaw_safe_value(self.usage),
            "latency_ms": self.latency_ms,
            "model_used": self.model_used,
            "provider_profile_id": self.provider_profile_id,
            "correlation_id": self.correlation_id,
        }

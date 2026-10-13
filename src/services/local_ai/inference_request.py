"""Pure bounded local naming input and strict result adaptation; no I/O."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from hashlib import sha256
import json
from types import MappingProxyType

from src.core.naming_fields import NamingFields
from src.core.provider_protocol import PreparedVisualPayload
from src.core.smart_naming import SmartNamingError, SmartNamingPolicy
from src.core.template_model import (DateFormat, OrgMode, OutputLanguage,
                                     Separator, Template, TemplateField)
from . import naming_protocol as protocol
from .native.model_stage import StageBytesMember


TEMPLATE_PROTOCOL_VERSION = "local-template-v1"
_SUFFIXES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
_KINDS = ("resized_image", "rendered_scan_page", "video_keyframe")


class LocalRequestError(ValueError):
    def __init__(self, code="INVALID_REQUEST"):
        self.code = code if code in ("INVALID_REQUEST", "INVALID_RESPONSE", "INSUFFICIENT_CONTENT") else "INVALID_REQUEST"
        super().__init__(self.code)


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if type(value) in (str, bool, int, float, type(None), NamingFields):
        return value
    raise LocalRequestError("INVALID_RESPONSE")


def _valid_visual(payload):
    if type(payload) is not PreparedVisualPayload:
        return False
    if (type(payload.data) is not bytes or not payload.data
            or type(payload.byte_size) is not int or payload.byte_size != len(payload.data)
            or type(payload.content_digest) is not str or payload.content_digest != sha256(payload.data).hexdigest()
            or any(type(value) is not int or value <= 0 for value in (payload.width, payload.height))
            or type(payload.source_index) is not int or payload.source_index < 0
            or type(payload.kind) is not str or payload.kind not in _KINDS
            or type(payload.mime_type) is not str or payload.mime_type not in _SUFFIXES
            or any(type(value) is not str or not value.strip()
                   for value in (payload.preprocessing_version, payload.provenance))):
        return False
    data = payload.data
    return {"image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/jpeg": data.startswith(b"\xff\xd8\xff"),
            "image/webp": len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"}[payload.mime_type]


def _valid_template(template):
    if type(template) is not Template or type(template.fields) is not tuple:
        return False
    if (type(template.name) is not str or not template.name.strip()
            or type(template.pattern) is not str
            or type(template.date_format) is not DateFormat
            or type(template.separator) is not Separator
            or type(template.org_mode) is not OrgMode
            or type(template.output_language) is not OutputLanguage
            or type(template.version) is not int or template.version < 1
            or type(template.id) is not str or not template.id.strip()):
        return False
    for item in template.fields:
        if (type(item) is not TemplateField
                or type(item.dc_name) is not str or not item.dc_name.strip()
                or type(item.display_name) is not str or not item.display_name.strip()
                or type(item.order) is not int or item.order < 1
                or type(item.enabled) is not bool
                or type(item.id) is not str or not item.id.strip()):
            return False
    return True


def _snapshot_template(template):
    if not _valid_template(template):
        raise LocalRequestError()
    try:
        return replace(template, fields=tuple(replace(item) for item in template.fields))
    except (TypeError, ValueError, AttributeError):
        raise LocalRequestError() from None


@dataclass(frozen=True, slots=True)
class LocalNamingRequest:
    text: str = field(repr=False)
    visuals: tuple[PreparedVisualPayload, ...] = field(repr=False)
    locale: str
    naming_mode: str
    template: Template | None = field(default=None, repr=False)
    quality: str = "balanced"
    text_layout: str = "lines"

    def __post_init__(self):
        try:
            valid = (
                type(self.text) is str and len(self.text.encode("utf-8")) <= 32768
                and type(self.visuals) is tuple and len(self.visuals) <= 8
                and all(_valid_visual(item) for item in self.visuals)
                and sum(item.byte_size for item in self.visuals) <= 16777216
                and bool(self.text.strip() or self.visuals)
                and type(self.locale) is str and self.locale in protocol.SUPPORTED_NAMING_LOCALES
                and type(self.naming_mode) is str and self.naming_mode in ("smart", "template")
                and ((self.template is None) if self.naming_mode == "smart" else _valid_template(self.template))
                and type(self.quality) is str and self.quality in ("economy", "balanced", "quality", "high")
                and type(self.text_layout) is str and self.text_layout in ("lines", "contiguous")
                and (self.text_layout == "lines" or (bool(self.text.strip()) and not self.visuals)))
        except (AttributeError, TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            raise LocalRequestError()
        if self.naming_mode == "template":
            object.__setattr__(self, "template", _snapshot_template(self.template))
        if self.quality == "high":
            object.__setattr__(self, "quality", "quality")


@dataclass(frozen=True, slots=True)
class LocalInferenceResult:
    success: bool
    fields: object | None = field(repr=False)
    error: str | None
    engine_identity: str | None
    elapsed_seconds: float

    def __post_init__(self):
        object.__setattr__(self, "fields", _freeze(self.fields))


@dataclass(frozen=True, slots=True)
class PreparedNamingInput:
    members: tuple[StageBytesMember, ...] = field(repr=False)
    text: str = field(repr=False)
    text_evidence: Mapping | None = field(repr=False)
    template: Template | None = field(repr=False)
    locale: str
    naming_mode: str
    visual_names: tuple[str, ...]
    protocol_version: str


def prepare_request(request: LocalNamingRequest) -> PreparedNamingInput:
    if type(request) is not LocalNamingRequest:
        raise LocalRequestError()
    request.__post_init__()
    try:
        template = _snapshot_template(request.template) if request.naming_mode == "template" else None
        has_text, has_visuals = bool(request.text.strip()), bool(request.visuals)
        bank = protocol.text_evidence_spans(request.text, text_layout=request.text_layout) if has_text else None
        context = dict(has_text=has_text, has_visuals=has_visuals, text_evidence=bank)
        if request.naming_mode == "smart":
            prompt = protocol.build_smart_prompt(request.locale, request.text,
                text_layout=request.text_layout, **context)
            schema = protocol.local_schema(request.locale, **context)
            version = protocol.SMART_PROTOCOL_VERSION
        else:
            prompt = protocol.build_template_prompt(template, request.locale, request.text,
                text_layout=request.text_layout, **context)
            schema = protocol.template_schema(template, request.locale, **context)
            version = TEMPLATE_PROTOCOL_VERSION
        prompt_bytes = prompt.encode("utf-8")
        schema_bytes = json.dumps(schema, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if not 0 < len(prompt_bytes) <= 131072 or not 0 < len(schema_bytes) <= 131072:
            raise LocalRequestError()
        names = tuple(f"visual_{index:02d}.{_SUFFIXES[item.mime_type]}" for index, item in enumerate(request.visuals))
        members = (StageBytesMember("prompt.txt", prompt_bytes), StageBytesMember("schema.json", schema_bytes))
        members += tuple(StageBytesMember(name, item.data) for name, item in zip(names, request.visuals))
        return PreparedNamingInput(members, request.text, _freeze(bank), template,
                                   request.locale, request.naming_mode, names, version)
    except (AttributeError, TypeError, ValueError, OverflowError, RecursionError):
        raise LocalRequestError() from None


def decode_prepared_response(prepared: PreparedNamingInput, raw: bytes):
    if type(prepared) is not PreparedNamingInput or type(raw) is not bytes or len(raw) > 262144:
        raise LocalRequestError("INVALID_RESPONSE")
    context = dict(has_text=bool(prepared.text.strip()), has_visuals=bool(prepared.visual_names),
                   text_evidence=prepared.text_evidence)
    try:
        if prepared.naming_mode == "smart":
            result = protocol.decode_response(raw, prepared.locale, **context)
            if result["understood"] is False:
                raise LocalRequestError("INSUFFICIENT_CONTENT")
            SmartNamingPolicy(prepared.locale).render(result, extracted_text=prepared.text,
                has_visuals=bool(prepared.visual_names), extension=".txt")
            return _freeze(result)
        return protocol.decode_template_response(raw, prepared.template, prepared.locale, **context)
    except LocalRequestError:
        raise
    except (SmartNamingError, ValueError) as exc:
        code = "INSUFFICIENT_CONTENT" if str(exc) == "template.error.insufficientContent" else "INVALID_RESPONSE"
        raise LocalRequestError(code) from None
    except (TypeError, AttributeError, OverflowError, RecursionError):
        raise LocalRequestError("INVALID_RESPONSE") from None

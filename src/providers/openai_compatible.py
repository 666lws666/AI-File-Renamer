"""Safe OpenAI-compatible chat-completions adapter.

The protocol name describes a wire format only.  It does not create OpenAI or
Anthropic product presets.  The adapter is permanently bound to one immutable
``ProviderProfile`` and never switches provider while retrying.
"""
from __future__ import annotations

import base64
import json
import math
import time
import warnings
from io import BytesIO
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from src.core.processing_authority import (
    CloudDispatchBlocked,
    CloudProbeContext,
    ProcessingAuthority,
    ProcessingSuperseded,
    WorkContext,
)
from src.core.processing_identity import cloud_engine_fingerprint
from src.core.provider_profile import ProviderProfile
from src.core.provider_protocol import ProviderRequest, ProviderResponse
from src.services.retry_policy import (
    ClassifiedProviderError,
    ErrorCategory,
    RetryExecutionResult,
    RetryExecutor,
    RetryPolicy,
    classify_http_status,
)


@dataclass(frozen=True)
class ProcessingDispatch:
    """Explicit business/probe dispatch; neither is a reusable network permit."""

    authority: ProcessingAuthority = field(repr=False)
    context: WorkContext | CloudProbeContext = field(repr=False)

    def __post_init__(self) -> None:
        if (type(self.authority) is not ProcessingAuthority
                or type(self.context) not in (WorkContext, CloudProbeContext)):
            raise TypeError("Invalid processing dispatch")

    def is_current(self) -> bool:
        if type(self.context) is CloudProbeContext:
            return self.authority.is_current_cloud_probe(self.context)
        return self.authority.is_current(self.context)


def _fixed_probe_body(body: Mapping[str, Any], context: CloudProbeContext) -> dict[str, Any]:
    """Validate exact JSON types and detach the fixed body from caller mutation."""
    if (type(body) is not dict
            or set(body) != {"model", "messages", "stream", "max_tokens"}
            or type(body["model"]) is not str or body["model"] != context.candidate_model
            or body["stream"] is not False
            or type(body["max_tokens"]) is not int or body["max_tokens"] != 1):
        raise CloudDispatchBlocked()
    messages = body["messages"]
    if type(messages) is not list or len(messages) != 1:
        raise CloudDispatchBlocked()
    message = messages[0]
    if (type(message) is not dict or set(message) != {"role", "content"}
            or type(message["role"]) is not str or message["role"] != "user"
            or type(message["content"]) is not str or message["content"] != "ping"):
        raise CloudDispatchBlocked()
    return {"model": context.candidate_model,
            "messages": [{"role": "user", "content": "ping"}],
            "stream": False, "max_tokens": 1}


@dataclass(frozen=True)
class _ProbeOutcome:
    """Minimal connection-probe response semantics.

    The probe sends ``"ping"`` WITHOUT ``response_format=json_object``, so a
    real provider may legally answer with plain text.  ``content`` is kept
    as an internal probe_text only — it is NEVER treated as a naming field.
    """

    content: str
    model: str
    latency_ms: float
    usage: Mapping[str, Any]
    body: Mapping[str, Any]


class ProviderAdapterError(RuntimeError):
    """Base class for safe, credential-free adapter failures."""


class ProviderAdapterConfigurationError(ProviderAdapterError):
    """The immutable profile/request combination cannot be invoked safely."""


class ProviderHTTPError(ProviderAdapterError):
    """Remote HTTP failure with structured retry information."""

    def __init__(
        self,
        status_code: int,
        *,
        retry_after: str | float | int | None = None,
        usage: Mapping[str, int | float] | None = None,
    ) -> None:
        super().__init__(f"Provider request failed with HTTP {status_code}")
        self.status_code = status_code
        self.retry_after = retry_after
        self.usage = MappingProxyType(dict(usage or {}))


class ProviderResponseError(ProviderAdapterError):
    """The server returned a success status with an unusable response."""

    def __init__(
        self,
        message: str,
        *,
        usage: Mapping[str, int | float] | None = None,
    ) -> None:
        super().__init__(message)
        self.usage = MappingProxyType(dict(usage or {}))


class ProviderTransportTimeout(ProviderAdapterError):
    """Credential-free timeout wrapper for arbitrary transport errors."""


class ProviderNetworkError(ProviderAdapterError):
    """Credential-free network wrapper for arbitrary transport errors."""


@dataclass(frozen=True, slots=True)
class TransportResponse:
    """JSON response returned by the injected transport."""

    status_code: int
    headers: Mapping[str, str] = field(default_factory=dict)
    json_body: Mapping[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0

    def __post_init__(self) -> None:
        if self.status_code < 100 or self.status_code > 599:
            raise ValueError("HTTP status_code is outside the valid range")
        if self.latency_ms < 0:
            raise ValueError("Transport latency cannot be negative")
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))
        object.__setattr__(
            self, "json_body", MappingProxyType(dict(self.json_body))
        )


class JsonTransport(Protocol):
    """Minimal injectable transport; contract tests use an in-memory double."""

    def send(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        json_body: Mapping[str, Any],
        timeout: int,
        dispatch_context: ProcessingDispatch | None = None,
    ) -> TransportResponse: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    """Treat every redirect as a response; never forward credential headers."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UrllibJsonTransport:
    """Bounded standard-library HTTPS JSON transport with redirects disabled."""

    DEFAULT_MAX_RESPONSE_BYTES = 4 * 1024 * 1024

    def __init__(
        self,
        *,
        opener: Callable[..., Any] | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        self._open = opener or build_opener(_NoRedirectHandler()).open
        self._max_response_bytes = max_response_bytes

    def _read_bounded(self, response: Any, status_code: int) -> bytes:
        raw = response.read(self._max_response_bytes + 1)
        if len(raw) <= self._max_response_bytes:
            return raw
        if status_code < 200 or status_code >= 300:
            return b"{}"
        raise ProviderResponseError("Provider response exceeds the size limit")

    def send(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        json_body: Mapping[str, Any],
        timeout: int,
        dispatch_context: ProcessingDispatch | None = None,
    ) -> TransportResponse:
        probe_dispatch = False
        if dispatch_context is not None:
            if type(dispatch_context) is not ProcessingDispatch:
                raise CloudDispatchBlocked()
            probe_dispatch = type(dispatch_context.context) is CloudProbeContext
            if probe_dispatch:
                if not dispatch_context.is_current():
                    raise CloudDispatchBlocked()
                json_body = _fixed_probe_body(json_body, dispatch_context.context)
        encoded = json.dumps(
            json_body, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        request = Request(
            url,
            data=encoded,
            headers=dict(headers),
            method="POST",
        )
        started = time.monotonic()
        receipt = None
        try:
            try:
                # Preparation is complete. No wait, callback or serialization
                # may be inserted between this one-use commitment and _open.
                if dispatch_context is not None:
                    if probe_dispatch:
                        receipt = dispatch_context.authority.commit_cloud_probe_attempt(
                            dispatch_context.context, uuid4().hex
                        )
                    else:
                        receipt = dispatch_context.authority.commit_cloud_attempt(
                            dispatch_context.context, uuid4().hex
                        )
                with self._open(request, timeout=timeout) as response:
                    status_code = int(response.status)
                    raw = self._read_bounded(response, status_code)
                    response_headers = dict(response.headers.items())
            except HTTPError as error:
                status_code = int(error.code)
                raw = self._read_bounded(error, status_code)
                response_headers = (
                    dict(error.headers.items()) if error.headers is not None else {}
                )
            elapsed_ms = (time.monotonic() - started) * 1000.0
            try:
                decoded = json.loads(
                    raw.decode("utf-8"),
                    parse_constant=_reject_nonstandard_json_constant,
                )
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                if status_code < 200 or status_code >= 300:
                    decoded = {}
                else:
                    raise ProviderResponseError(
                        "Provider returned a non-JSON response"
                    ) from error
            if not isinstance(decoded, Mapping):
                if status_code < 200 or status_code >= 300:
                    decoded = {}
                else:
                    raise ProviderResponseError("Provider JSON root must be an object")
            return TransportResponse(
                status_code=status_code,
                headers=response_headers,
                json_body=decoded,
                latency_ms=elapsed_ms,
            )
        finally:
            if receipt is not None:
                dispatch_context.authority.finish_attempt(receipt)


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_plain_json(child) for child in value]
    return value


def _header(
    headers: Mapping[str, str], name: str
) -> str | None:
    folded = name.casefold()
    for key, value in headers.items():
        if key.casefold() == folded:
            return value
    return None


def _numeric_usage(value: Any) -> dict[str, int | float]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if isinstance(item, (int, float)) and not isinstance(item, bool)
    }


class _SchemaContractError(ValueError):
    pass


def _reject_nonstandard_json_constant(value: str) -> None:
    raise ValueError(f"Non-standard JSON numeric constant: {value}")


def _contains_nonfinite_number(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, Mapping):
        return any(_contains_nonfinite_number(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_nonfinite_number(child) for child in value)
    return False


def _json_values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
    ):
        return (
            not _contains_nonfinite_number(left)
            and not _contains_nonfinite_number(right)
            and left == right
        )
    if isinstance(left, Mapping) or isinstance(right, Mapping):
        return (
            isinstance(left, Mapping)
            and isinstance(right, Mapping)
            and set(left) == set(right)
            and all(_json_values_equal(left[key], right[key]) for key in left)
        )
    if isinstance(left, (list, tuple)) or isinstance(right, (list, tuple)):
        return (
            isinstance(left, (list, tuple))
            and isinstance(right, (list, tuple))
            and len(left) == len(right)
            and all(_json_values_equal(a, b) for a, b in zip(left, right))
        )
    return type(left) is type(right) and left == right


_SCHEMA_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "title",
        "description",
        "default",
        "examples",
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "minItems",
        "maxItems",
    }
)
_SCHEMA_TYPES = frozenset(
    {"object", "array", "string", "integer", "number", "boolean", "null"}
)


def _validate_schema_definition(schema: Any, *, location: str = "$") -> None:
    if not isinstance(schema, Mapping):
        raise _SchemaContractError(f"{location} schema must be an object")
    if _contains_nonfinite_number(schema):
        raise _SchemaContractError(
            f"{location} schema contains a non-finite number"
        )
    unknown = set(schema) - _SCHEMA_KEYWORDS
    if unknown:
        raise _SchemaContractError(
            f"{location} uses unsupported schema keywords: {sorted(unknown)}"
        )
    schema_type = schema.get("type")
    if schema_type is not None and schema_type not in _SCHEMA_TYPES:
        raise _SchemaContractError(f"{location} has unsupported schema type")
    enum_values = schema.get("enum")
    if enum_values is not None and (
        not isinstance(enum_values, (list, tuple)) or not enum_values
    ):
        raise _SchemaContractError(f"{location}.enum must be a non-empty array")

    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, Mapping):
            raise _SchemaContractError(f"{location}.properties must be an object")
        for name, child_schema in properties.items():
            if not isinstance(name, str):
                raise _SchemaContractError(
                    f"{location}.properties keys must be strings"
                )
            _validate_schema_definition(
                child_schema, location=f"{location}.{name}"
            )
    required = schema.get("required")
    if required is not None:
        if (
            not isinstance(required, (list, tuple))
            or any(not isinstance(name, str) for name in required)
            or len(set(required)) != len(required)
        ):
            raise _SchemaContractError(
                f"{location}.required must contain unique string names"
            )
        if properties is not None and not set(required).issubset(properties):
            raise _SchemaContractError(
                f"{location}.required references an unknown property"
            )
    additional = schema.get("additionalProperties", True)
    if not isinstance(additional, (bool, Mapping)):
        raise _SchemaContractError(
            f"{location}.additionalProperties must be boolean or schema"
        )
    if isinstance(additional, Mapping):
        _validate_schema_definition(
            additional, location=f"{location}.*"
        )
    items = schema.get("items")
    if items is not None:
        _validate_schema_definition(items, location=f"{location}[]")

    for keyword in ("minLength", "maxLength", "minItems", "maxItems"):
        value = schema.get(keyword)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise _SchemaContractError(
                f"{location}.{keyword} must be a non-negative integer"
            )
    for keyword in ("minimum", "maximum"):
        value = schema.get(keyword)
        if value is not None and (
            not isinstance(value, (int, float)) or isinstance(value, bool)
        ):
            raise _SchemaContractError(
                f"{location}.{keyword} must be numeric"
            )


def _matches_schema_type(value: Any, schema_type: str) -> bool:
    if schema_type == "object":
        return isinstance(value, Mapping)
    if schema_type == "array":
        return isinstance(value, (list, tuple))
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "null":
        return value is None
    return False


def _validate_schema_value(
    value: Any, schema: Mapping[str, Any], *, location: str = "$"
) -> None:
    if _contains_nonfinite_number(value):
        raise _SchemaContractError(f"{location} contains a non-finite number")
    if "enum" in schema and not any(
        _json_values_equal(value, candidate) for candidate in schema["enum"]
    ):
        raise _SchemaContractError(f"{location} is not an allowed enum value")
    schema_type = schema.get("type")
    if schema_type is not None and not _matches_schema_type(value, schema_type):
        raise _SchemaContractError(f"{location} does not match type {schema_type}")

    if isinstance(value, Mapping):
        properties = schema.get("properties", {})
        required = schema.get("required", ())
        missing = [name for name in required if name not in value]
        if missing:
            raise _SchemaContractError(
                f"{location} is missing required fields: {missing}"
            )
        additional = schema.get("additionalProperties", True)
        for name, child in value.items():
            if name in properties:
                _validate_schema_value(
                    child, properties[name], location=f"{location}.{name}"
                )
            elif additional is False:
                raise _SchemaContractError(
                    f"{location} contains an unexpected field: {name}"
                )
            elif isinstance(additional, Mapping):
                _validate_schema_value(
                    child, additional, location=f"{location}.{name}"
                )
    if isinstance(value, (list, tuple)):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise _SchemaContractError(f"{location} has too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise _SchemaContractError(f"{location} has too many items")
        if "items" in schema:
            for index, child in enumerate(value):
                _validate_schema_value(
                    child, schema["items"], location=f"{location}[{index}]"
                )
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise _SchemaContractError(f"{location} is too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise _SchemaContractError(f"{location} is too long")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise _SchemaContractError(f"{location} is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise _SchemaContractError(f"{location} is above maximum")


_MAX_VISUAL_PAYLOAD_BYTES = 10 * 1024 * 1024
_MAX_TOTAL_VISUAL_BYTES = 32 * 1024 * 1024
_MAX_VISUAL_PIXELS = 16_000_000
_EXPECTED_IMAGE_FORMAT = {
    "image/png": "PNG",
    "image/jpeg": "JPEG",
    "image/webp": "WEBP",
}


def _has_exact_image_container(mime_type: str, data: bytes) -> bool:
    if mime_type == "image/jpeg":
        return data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9")
    if mime_type == "image/webp":
        return (
            len(data) >= 12
            and data.startswith(b"RIFF")
            and data[8:12] == b"WEBP"
            and int.from_bytes(data[4:8], "little") + 8 == len(data)
        )
    if mime_type != "image/png" or not data.startswith(
        b"\x89PNG\r\n\x1a\n"
    ):
        return False
    offset = 8
    while offset + 12 <= len(data):
        chunk_length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        chunk_end = offset + 12 + chunk_length
        if chunk_end > len(data):
            return False
        if chunk_type == b"IEND":
            return chunk_length == 0 and chunk_end == len(data)
        offset = chunk_end
    return False


def _canonicalize_visual_payload_for_upload(payload: Any) -> bytes:
    if payload.byte_size > _MAX_VISUAL_PAYLOAD_BYTES:
        raise ProviderAdapterConfigurationError(
            "Prepared visual payload exceeds the upload size limit"
        )
    if payload.width * payload.height > _MAX_VISUAL_PIXELS:
        raise ProviderAdapterConfigurationError(
            "Prepared visual payload exceeds the pixel limit"
        )
    if not _has_exact_image_container(payload.mime_type, payload.data):
        raise ProviderAdapterConfigurationError(
            "Prepared visual payload contains trailing or invalid container data"
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(payload.data)) as image:
                detected_format = image.format
                detected_size = image.size
                image.load()
                has_alpha = "A" in image.getbands() or "transparency" in image.info
                canonical_image = image.convert("RGBA" if has_alpha else "RGB")
        if detected_format != _EXPECTED_IMAGE_FORMAT.get(payload.mime_type):
            raise ProviderAdapterConfigurationError(
                "Prepared visual MIME type does not match its image bytes"
            )
        if detected_size != (payload.width, payload.height):
            raise ProviderAdapterConfigurationError(
                "Prepared visual dimensions do not match its image bytes"
            )

        canonical_image.info.clear()
        output = BytesIO()
        save_options: dict[str, Any] = {}
        if detected_format == "JPEG":
            canonical_image = canonical_image.convert("RGB")
            save_options = {"quality": 90, "optimize": True}
        elif detected_format == "PNG":
            save_options = {"optimize": True}
        elif detected_format == "WEBP":
            save_options = {"quality": 85, "method": 4}
        canonical_image.save(output, format=detected_format, **save_options)
        canonical_image.close()
        canonical = output.getvalue()
    except ProviderAdapterConfigurationError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, Warning) as error:
        raise ProviderAdapterConfigurationError(
            "Prepared visual payload is not a valid bounded image"
        ) from error
    if not canonical or len(canonical) > _MAX_VISUAL_PAYLOAD_BYTES:
        raise ProviderAdapterConfigurationError(
            "Canonical visual payload exceeds the upload size limit"
        )
    if not _has_exact_image_container(payload.mime_type, canonical):
        raise ProviderAdapterConfigurationError(
            "Canonical visual payload container is invalid"
        )
    return canonical


def _chat_completions_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    path = parsed.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path = f"{path}/chat/completions"
    return urlunsplit(
        (parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment)
    )


class OpenAICompatibleAdapter:
    """Invoke one fixed Provider profile through a strict JSON contract."""

    def __init__(
        self,
        *,
        profile: ProviderProfile,
        credential: str,
        transport: JsonTransport | None = None,
        retry_executor: RetryExecutor | None = None,
        processing_dispatch: ProcessingDispatch | None = None,
    ) -> None:
        if not isinstance(profile, ProviderProfile):
            raise TypeError("profile must be ProviderProfile")
        if profile.protocol_kind != "openai_compatible":
            raise ProviderAdapterConfigurationError(
                "Profile does not use the OpenAI-compatible wire protocol"
            )
        if not profile.id or not profile.provider_id:
            raise ProviderAdapterConfigurationError(
                "Provider profile identity is required"
            )
        if not profile.base_url:
            raise ProviderAdapterConfigurationError(
                "Provider profile base URL is required"
            )
        if not isinstance(credential, str) or not credential.strip():
            raise ProviderAdapterConfigurationError(
                "Provider credential is required"
            )
        self._profile = profile
        self._credential = credential.strip()
        self._transport = transport or UrllibJsonTransport()
        self._retry_executor = retry_executor or RetryExecutor(RetryPolicy())
        self._processing_dispatch = processing_dispatch
        self._chat_completions_url = _chat_completions_url(profile.base_url)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(profile_id={self._profile.id!r}, "
            f"provider_id={self._profile.provider_id!r})"
        )

    @property
    def profile(self) -> ProviderProfile:
        return self._profile

    @property
    def chat_completions_url(self) -> str:
        return self._chat_completions_url

    def invoke(
        self,
        request: ProviderRequest,
        *,
        cancellation_token: Callable[[], bool] | None = None,
    ) -> RetryExecutionResult:
        """Invoke the fixed profile and retain every retry attempt outcome.

        The connection-verification gate is NEVER bypassed here — unverified
        profiles must use ``invoke_probe`` (the declared probe bypass).
        """
        if (self._processing_dispatch is not None
                and type(self._processing_dispatch.context) is CloudProbeContext):
            raise CloudDispatchBlocked()
        canonical_visual_payloads = self._validate_invocation(request)
        body = self._build_request_body(request, canonical_visual_payloads)
        headers = self._build_headers()

        def operation() -> ProviderResponse:
            return self._run_transport_operation(
                url=self._chat_completions_url,
                headers=headers,
                json_body=body,
                timeout=min(request.timeout, self._profile.timeout_seconds),
                request=request,
            )

        return self._execute_with_retry(operation, cancellation_token)

    def invoke_probe(
        self,
        *,
        cancellation_token: Callable[[], bool] | None = None,
    ) -> RetryExecutionResult:
        """Run the fixed minimal connection probe ("ping", max_tokens=1,
        stream=False — no user content, paths, images, or videos).

        This is the ONLY path allowed to execute for a profile whose
        ``needs_connection_verification`` is still True: it bypasses exactly
        that gate and nothing else.  The enabled / protocol / credential /
        model / text-capability checks all still run, and the request goes
        through the SAME shared transport send, retry policy, and HTTP error
        classification as a normal invoke.

        The RESPONSE contract is probe-specific (``_parse_probe_transport_
        response``): plain text such as "pong" is accepted — the business
        JSON contract is NOT applied to probes.
        """
        dispatch = self._processing_dispatch
        if dispatch is not None and type(dispatch.context) is CloudProbeContext:
            context = dispatch.context
            if (not dispatch.is_current()
                    or context.candidate_model != self._profile.model
                    or context.candidate_fingerprint != cloud_engine_fingerprint(self._profile)):
                raise CloudDispatchBlocked()
        self._validate_invocation_for_probe()
        body = {
            "model": self._profile.model,
            "messages": [{"role": "user", "content": "ping"}],
            "stream": False,
            "max_tokens": 1,
        }
        headers = self._build_headers()

        def operation() -> _ProbeOutcome:
            transport_response = self._send_transport(
                url=self._chat_completions_url,
                headers=headers,
                json_body=body,
                timeout=min(15, self._profile.timeout_seconds),
            )
            return self._parse_probe_transport_response(transport_response)

        return self._execute_with_retry(operation, cancellation_token)

    def _execute_with_retry(
        self,
        operation: Callable[[], Any],
        cancellation_token: Callable[[], bool] | None,
    ) -> RetryExecutionResult:
        dispatch = self._processing_dispatch
        if dispatch is None:
            return self._retry_executor.execute(
                operation, self._classify_error,
                cancellation_token=cancellation_token,
                usage_extractor=lambda outcome: outcome.usage,
            )

        def is_cancelled() -> bool:
            # Caller code is outside the authority lock; it may itself change
            # the selected mode, so currentness is checked after the callback.
            if cancellation_token is not None and cancellation_token():
                return True
            return not dispatch.is_current()

        return self._retry_executor.execute(
            operation, self._classify_error,
            cancellation_token=is_cancelled,
            cancellation_event=dispatch.context.generation_cancel_event,
            usage_extractor=lambda outcome: outcome.usage,
        )

    def _send_transport(
        self,
        *,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, Any],
        timeout: int,
    ) -> TransportResponse:
        """Send one request with canonical error normalisation — NO response
        content parsing.

        Raw transport exceptions are never surfaced — each is mapped to a
        sanitised Provider error with a fixed message, so credentials and
        response bodies cannot leak into callers or logs.  This is the SHARED
        network path used by both business invokes and the connection probe.
        """
        try:
            if self._processing_dispatch is not None:
                # A guarded transport must implement the dispatch contract.
                # Never fall back to the legacy signature after TypeError.
                return self._transport.send(
                    url=url, headers=headers, json_body=json_body, timeout=timeout,
                    dispatch_context=self._processing_dispatch,
                )
            return self._transport.send(
                url=url,
                headers=headers,
                json_body=json_body,
                timeout=timeout,
            )
        except (ProcessingSuperseded, CloudDispatchBlocked):
            raise
        except ProviderHTTPError as error:
            raise ProviderHTTPError(
                error.status_code,
                retry_after=error.retry_after,
                usage=error.usage,
            ) from None
        except ProviderTransportTimeout:
            raise ProviderTransportTimeout(
                "Provider request timed out"
            ) from None
        except ProviderNetworkError:
            raise ProviderNetworkError(
                "Provider network request failed"
            ) from None
        except ProviderResponseError as error:
            raise ProviderResponseError(
                "Provider transport returned a malformed response",
                usage=error.usage,
            ) from None
        except ProviderAdapterError:
            raise ProviderAdapterError(
                "Provider transport failed"
            ) from None
        except TimeoutError:
            raise ProviderTransportTimeout(
                "Provider request timed out"
            ) from None
        except (ConnectionError, OSError):
            raise ProviderNetworkError(
                "Provider network request failed"
            ) from None
        except Exception:
            raise ProviderAdapterError(
                "Provider transport failed unexpectedly"
            ) from None

    def _run_transport_operation(
        self,
        *,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, Any],
        timeout: int,
        request: ProviderRequest,
    ) -> ProviderResponse:
        """BUSINESS invoke path: shared send + the strict Chat Completions
        JSON contract parser."""
        transport_response = self._send_transport(
            url=url,
            headers=headers,
            json_body=json_body,
            timeout=timeout,
        )
        return self._parse_transport_response(transport_response, request)

    def _parse_probe_transport_response(
        self, response: TransportResponse
    ) -> _ProbeOutcome:
        """PROBE path response semantics — minimal and independent of the
        business JSON contract.

        Requirements:
        - HTTP must be 2xx;
        - ``choices`` must be a non-empty list;
        - ``choice/message`` must be legal objects;
        - ``content`` must be a non-empty string — plain text is ACCEPTED
          (the probe sends no ``response_format``, so providers may answer
          with anything, e.g. "pong");
        - ``finish_reason="length"`` is accepted: max_tokens=1 truncation
          still proves endpoint, auth, and model reachability;
        - no NamingFields schema validation;
        - model / latency / usage are still recorded; content is stored as
          internal probe_text only, never as a naming field.
        """
        if not isinstance(response, TransportResponse):
            raise ProviderResponseError(
                "Provider transport returned an invalid response object"
            )
        body = response.json_body
        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderHTTPError(
                response.status_code,
                retry_after=_header(response.headers, "Retry-After"),
                usage=_numeric_usage(body.get("usage")),
            )

        usage = _numeric_usage(body.get("usage"))
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderResponseError(
                "Provider response does not contain a completion choice",
                usage=usage,
            )
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise ProviderResponseError(
                "Provider completion choice is invalid", usage=usage
            )
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise ProviderResponseError(
                "Provider response message is invalid", usage=usage
            )
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderResponseError(
                "Provider response content is empty", usage=usage
            )

        return _ProbeOutcome(
            content=content,
            model=str(body.get("model") or self._profile.model),
            latency_ms=response.latency_ms,
            usage=usage,
            body=body,
        )

    def _validate_invocation(self, request: ProviderRequest) -> tuple[bytes, ...]:
        """Gate checks for normal business invokes — the connection
        verification gate is enforced here and NEVER bypassed."""
        if self._profile.needs_connection_verification:
            raise ProviderAdapterConfigurationError(
                "Provider profile requires connection verification"
            )
        return self._validate_invocation_common(request)

    def _validate_invocation_for_probe(self) -> None:
        """Probe-path validation: everything except the verification gate."""
        self._validate_invocation_common(
            ProviderRequest(
                request_id="connection-probe",
                task_id="connection-probe",
                extracted_text="ping",
            )
        )

    def _validate_invocation_common(
        self, request: ProviderRequest
    ) -> tuple[bytes, ...]:
        if not isinstance(request, ProviderRequest):
            raise TypeError("request must be ProviderRequest")
        if not self._profile.enabled:
            raise ProviderAdapterConfigurationError(
                "Provider profile is disabled"
            )
        if not self._profile.capabilities.text and request.extracted_text:
            raise ProviderAdapterConfigurationError(
                "Provider profile does not support text input"
            )
        if request.visual_payloads and not self._profile.capabilities.vision:
            raise ProviderAdapterConfigurationError(
                "Provider profile does not support prepared visual input"
            )
        if request.visual_payloads and self._profile.provider_id == "deepseek":
            from src.core.provider_presets import capabilities_for_model, get_provider_preset
            if not capabilities_for_model(
                get_provider_preset("deepseek"), request.model or self._profile.model
            ).vision:
                raise ProviderAdapterConfigurationError(
                    "Selected DeepSeek model does not support prepared visual input"
                )
            if any(max(p.width, p.height) > 8192 for p in request.visual_payloads):
                raise ProviderAdapterConfigurationError(
                    "Prepared visual dimensions exceed the DeepSeek image limit"
                )
        if (
            len(request.visual_payloads) > 1
            and not self._profile.capabilities.multi_image
        ):
            raise ProviderAdapterConfigurationError(
                "Provider profile does not support multiple prepared images"
            )
        if len(request.visual_payloads) > 8:
            raise ProviderAdapterConfigurationError(
                "Prepared visual payload count exceeds the configured limit"
            )
        if (
            sum(payload.byte_size for payload in request.visual_payloads)
            > _MAX_TOTAL_VISUAL_BYTES
        ):
            raise ProviderAdapterConfigurationError(
                "Prepared visual payloads exceed the total upload size limit"
            )
        canonical_visual_payloads = tuple(
            _canonicalize_visual_payload_for_upload(payload)
            for payload in request.visual_payloads
        )
        if sum(map(len, canonical_visual_payloads)) > _MAX_TOTAL_VISUAL_BYTES:
            raise ProviderAdapterConfigurationError(
                "Canonical visual payloads exceed the total upload size limit"
            )
        if request.requested_schema is not None:
            try:
                _validate_schema_definition(request.requested_schema)
            except _SchemaContractError as error:
                raise ProviderAdapterConfigurationError(
                    "Requested response schema is unsupported or invalid"
                ) from error
        if not (request.model or self._profile.model):
            raise ProviderAdapterConfigurationError(
                "Provider model is required"
            )
        return canonical_visual_payloads

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._profile.auth_scheme == "bearer":
            headers["Authorization"] = f"Bearer {self._credential}"
        elif self._profile.auth_scheme == "api_key_header":
            headers["api-key"] = self._credential
        else:
            raise ProviderAdapterConfigurationError(
                "Unsupported Provider authentication scheme"
            )
        return headers

    def _build_request_body(
        self,
        request: ProviderRequest,
        canonical_visual_payloads: tuple[bytes, ...],
    ) -> dict[str, Any]:
        schema = (
            _plain_json(request.requested_schema)
            if request.requested_schema is not None
            else None
        )
        system_parts = [
            "Return only one valid JSON object. Do not use Markdown fences.",
            f"Use locale {request.locale} for human-language field values.",
        ]
        if schema is not None:
            system_parts.append(
                "The required JSON Schema is: "
                + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
            )
        user_payload = {
            "extracted_text": request.extracted_text or "",
            "metadata": _plain_json(request.metadata),
            "quality_mode": request.quality_mode,
        }
        user_text = json.dumps(
            user_payload, ensure_ascii=False, separators=(",", ":")
        )
        if request.visual_payloads:
            user_content: str | list[dict[str, Any]] = [
                {"type": "text", "text": user_text}
            ]
            for payload, canonical_data in zip(
                request.visual_payloads, canonical_visual_payloads
            ):
                encoded = base64.b64encode(canonical_data).decode("ascii")
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{payload.mime_type};base64,{encoded}"
                        },
                    }
                )
        else:
            user_content = user_text

        body: dict[str, Any] = {
            "model": request.model or self._profile.model,
            "messages": [
                {"role": "system", "content": "\n".join(system_parts)},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
        }
        capabilities = self._profile.capabilities
        if schema is not None and capabilities.json_schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "xuxia_naming_fields",
                    "strict": True,
                    "schema": schema,
                },
            }
        elif capabilities.json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    def _parse_transport_response(
        self,
        response: TransportResponse,
        request: ProviderRequest,
    ) -> ProviderResponse:
        if not isinstance(response, TransportResponse):
            raise ProviderResponseError(
                "Provider transport returned an invalid response object"
            )
        body = response.json_body
        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderHTTPError(
                response.status_code,
                retry_after=_header(response.headers, "Retry-After"),
                usage=_numeric_usage(body.get("usage")),
            )

        usage = _numeric_usage(body.get("usage"))
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderResponseError(
                "Provider response does not contain a completion choice",
                usage=usage,
            )
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise ProviderResponseError(
                "Provider completion choice is invalid", usage=usage
            )
        if choice.get("finish_reason") in {"length", "content_filter"}:
            raise ProviderResponseError(
                "Provider completion did not finish normally", usage=usage
            )
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise ProviderResponseError(
                "Provider response message is invalid", usage=usage
            )
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderResponseError(
                "Provider response content is empty", usage=usage
            )
        try:
            fields = json.loads(
                content,
                parse_constant=_reject_nonstandard_json_constant,
            )
        except (json.JSONDecodeError, ValueError) as error:
            raise ProviderResponseError(
                "Provider response content is not valid JSON", usage=usage
            ) from error
        if not isinstance(fields, Mapping):
            raise ProviderResponseError(
                "Provider response JSON must be an object", usage=usage
            )
        if request.requested_schema is not None:
            try:
                _validate_schema_value(fields, request.requested_schema)
            except _SchemaContractError as error:
                raise ProviderResponseError(
                    "Provider response violates the requested schema",
                    usage=usage,
                ) from error

        return ProviderResponse(
            fields=fields,
            usage=usage,
            latency_ms=response.latency_ms,
            model_used=str(body.get("model") or request.model or self._profile.model),
            provider_profile_id=self._profile.id,
            correlation_id=request.correlation_id,
        )

    @staticmethod
    def _classify_error(error: Exception) -> ClassifiedProviderError:
        if isinstance(error, (ProcessingSuperseded, CloudDispatchBlocked)):
            return ClassifiedProviderError(ErrorCategory.CANCELLED, message=error.code)
        if isinstance(error, ProviderHTTPError):
            return ClassifiedProviderError(
                category=classify_http_status(error.status_code),
                retry_after=error.retry_after,
                status_code=error.status_code,
                message=str(error),
                usage=error.usage,
            )
        if isinstance(error, ProviderTransportTimeout):
            return ClassifiedProviderError(
                ErrorCategory.TIMEOUT, message="Provider request timed out"
            )
        if isinstance(error, ProviderNetworkError):
            return ClassifiedProviderError(
                ErrorCategory.NETWORK, message="Provider network request failed"
            )
        if isinstance(error, ProviderResponseError):
            return ClassifiedProviderError(
                ErrorCategory.MALFORMED_RESPONSE,
                message=str(error),
                usage=error.usage,
            )
        return ClassifiedProviderError(
            ErrorCategory.INVALID_REQUEST,
            message="Provider request failed before a valid response",
        )

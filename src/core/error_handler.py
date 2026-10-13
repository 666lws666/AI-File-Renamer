"""Unified error classification, redaction, and four-layer routing."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from src.core.app_error import AppError, ErrorScope, ErrorSeverity


class PresentationLayer(str, Enum):
    FILE_CARD = "file_card"
    BATCH = "batch"
    TOAST = "toast"
    BLOCKING = "blocking"


@dataclass(frozen=True)
class ErrorPresentation:
    layer: PresentationLayer
    error: AppError


_POLICIES = {
    "http_401": (False, "error.provider.unauthorized", "open_settings"),
    "http_403": (False, "error.provider.forbidden", "open_settings"),
    "http_404": (False, "error.provider.notFound", "open_settings"),
    "http_429": (True, "error.provider.rateLimited", "retry"),
    "timeout": (True, "error.provider.timeout", "retry"),
    "network": (True, "error.provider.network", "retry"),
    "server_5xx": (True, "error.provider.server", "retry"),
    "json_invalid": (False, "error.provider.invalidResponse", "retry_high_quality"),
    "no_vision": (False, "error.capability.noVision", "open_settings"),
    "resource_limit": (False, "error.resource.limit", "reduce_input"),
    "file_missing": (False, "error.file.missing", "remove_item"),
    "file_locked": (True, "error.file.locked", "retry"),
    "permission": (False, "error.file.permission", "choose_location"),
    "conflict": (False, "error.file.conflict", "edit_name"),
    "disk_full": (False, "error.file.diskFull", "free_space"),
    "invalid_name": (False, "error.file.invalidName", "edit_name"),
    "file_io": (False, "error.file.io", "review_details"),
}


def sanitize_detail(detail: object) -> str:
    text = str(detail or "")
    text = re.sub(r"(?is)traceback.*", "<redacted-stack>", text)
    text = re.sub(r"(?i)request[_ -]?body\s*[=:]\s*\{?[^\s]*\}?", "<redacted-body>", text)
    text = re.sub(r"(?i)raw[_ -]?ai[_ -]?request\s*[=:].*", "<redacted-request>", text)
    text = re.sub(r"(?i)authorization\s*:\s*bearer\s+\S+", "Authorization: <redacted>", text)
    text = re.sub(r"(?i)bearer\s+\S+", "Bearer <redacted>", text)
    text = re.sub(r"(?i)api[_-]?key\s*[=:]\s*\S+", "credential=<redacted>", text)
    text = re.sub(r"(?i)\bsk-[A-Za-z0-9_-]+", "<redacted>", text)
    text = re.sub(r"(?i)[A-Z]:[/\\]Users[/\\][^\s]+", "<redacted-path>", text)
    return text[:500]


class ErrorHandler:
    @staticmethod
    def from_execution_error(detail: object, *, scope: ErrorScope) -> ErrorPresentation:
        """Classify the sanitized error returned by the file I/O boundary.

        RenameExecutor deliberately returns a BatchResult instead of leaking
        platform exceptions through controllers.  This adapter preserves that
        boundary while producing a stable user-visible code.
        """
        text = str(detail or "")
        lowered = text.lower()
        if any(marker in lowered for marker in (
            "winerror 32", "being used", "used by another process",
            "resource busy", "file is locked",
        )):
            code = "file_locked"
        elif any(marker in lowered for marker in (
            "errno 28", "no space left", "disk full", "not enough space",
        )):
            code = "disk_full"
        elif any(marker in lowered for marker in (
            "permission denied", "access denied", "errno 13", "winerror 5",
        )):
            code = "permission"
        elif any(marker in lowered for marker in (
            "not found", "no such file", "winerror 2", "errno 2",
        )):
            code = "file_missing"
        elif any(marker in lowered for marker in (
            "already exists", "file exists", "winerror 183", "errno 17",
        )):
            code = "conflict"
        else:
            code = "file_io"
        return ErrorHandler.route(ErrorHandler.build(code, scope=scope, detail=detail))

    @staticmethod
    def build(code: str, *, scope: ErrorScope, detail: object = "",
              severity: ErrorSeverity = ErrorSeverity.ERROR) -> AppError:
        retryable, message, action = _POLICIES.get(
            code, (False, "error.generic", "review_details")
        )
        return AppError(
            code=code, scope=scope, severity=severity,
            retryable=retryable, user_message_id=message,
            recommended_action=action,
            sanitized_detail=sanitize_detail(detail),
        )

    @staticmethod
    def route(error: AppError) -> ErrorPresentation:
        if error.severity is ErrorSeverity.CRITICAL:
            layer = PresentationLayer.BLOCKING
        elif error.scope is ErrorScope.FILE:
            layer = PresentationLayer.FILE_CARD
        elif error.scope is ErrorScope.BATCH:
            layer = PresentationLayer.BATCH
        else:
            layer = PresentationLayer.TOAST
        return ErrorPresentation(layer, error)
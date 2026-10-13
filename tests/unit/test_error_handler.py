import pytest

from src.core.app_error import AppError, ErrorScope, ErrorSeverity
from src.core.error_handler import ErrorHandler, PresentationLayer


@pytest.mark.parametrize("code,retryable", [
    ("http_401", False), ("http_403", False), ("http_404", False),
    ("http_429", True), ("timeout", True), ("network", True),
    ("server_5xx", True), ("json_invalid", False), ("no_vision", False),
    ("resource_limit", False), ("file_missing", False),
    ("file_locked", True), ("permission", False), ("conflict", False),
    ("disk_full", False), ("invalid_name", False),
])
def test_known_error_codes_have_retry_policy(code, retryable):
    error = ErrorHandler.build(code, scope=ErrorScope.FILE, detail="safe")
    assert error.retryable is retryable
    assert error.user_message_id


def test_error_scope_and_severity_route_to_four_layers():
    assert ErrorHandler.route(AppError("x", ErrorScope.FILE, ErrorSeverity.ERROR)).layer is PresentationLayer.FILE_CARD
    assert ErrorHandler.route(AppError("x", ErrorScope.BATCH, ErrorSeverity.ERROR)).layer is PresentationLayer.BATCH
    assert ErrorHandler.route(AppError("x", ErrorScope.APP, ErrorSeverity.WARNING)).layer is PresentationLayer.TOAST
    assert ErrorHandler.route(AppError("x", ErrorScope.APP, ErrorSeverity.CRITICAL)).layer is PresentationLayer.BLOCKING


def test_sanitized_detail_contains_no_key_body_stack_or_full_path():
    raw = "Authorization: Bearer sk-secret API_KEY=abc C:/Users/alice/private.pdf request_body={payload} Traceback boom"
    error = ErrorHandler.build("network", scope=ErrorScope.APP, detail=raw)
    lowered = error.sanitized_detail.lower()
    for forbidden in ("sk-secret", "api_key", "c:/users", "request_body", "traceback", "payload"):
        assert forbidden not in lowered
    assert error.correlation_id
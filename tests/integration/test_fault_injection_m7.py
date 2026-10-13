"""M7 bounded retry and local file-I/O fault injection."""

from __future__ import annotations

import errno

import src.core.rename_executor as rename_module
from src.core.app_error import ErrorScope
from src.core.error_handler import ErrorHandler, PresentationLayer
from src.core.preflight_service import PreflightService
from src.core.rename_executor import RenameExecutor
from src.core.rename_plan import RenamePlan, SourceFingerprint
from src.services.retry_policy import (
    ClassifiedProviderError,
    ErrorCategory,
    RetryExecutor,
    RetryPolicy,
)


class InjectedProviderFailure(RuntimeError):
    def __init__(self, category):
        super().__init__(category.value)
        self.category = category


def _categorize(error):
    return ClassifiedProviderError(error.category)


def test_429_retries_once_then_succeeds_without_network():
    calls = []
    sleeps = []

    def operation():
        calls.append(1)
        if len(calls) == 1:
            raise InjectedProviderFailure(ErrorCategory.RATE_LIMIT)
        return "ok"

    result = RetryExecutor(
        RetryPolicy(max_retries=2, base_delay=0), sleeper=sleeps.append,
    ).execute(operation, _categorize)
    assert result.success is True
    assert result.total_attempts == 2
    assert sleeps == [0]


def test_timeout_and_5xx_exhaust_at_configured_limit():
    for category in (ErrorCategory.TIMEOUT, ErrorCategory.SERVER):
        calls = []

        def operation():
            calls.append(1)
            raise InjectedProviderFailure(category)

        result = RetryExecutor(
            RetryPolicy(max_retries=2, base_delay=0), sleeper=lambda _delay: None,
        ).execute(operation, _categorize)
        assert result.success is False
        assert result.total_attempts == 3
        assert result.final_category is category


def _plan(tmp_path):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    return source, RenamePlan(
        "task-1", str(source),
        SourceFingerprint(source.stat().st_size, source.stat().st_mtime_ns),
        "renamed.pdf", str(tmp_path), ".pdf",
    )


def test_opaque_disk_full_boundary_exception_requires_nonretryable_recovery(tmp_path, monkeypatch):
    source, plan = _plan(tmp_path)
    calls = []
    def fail_before_effect(src, dst, **approval):
        calls.append((src, dst, approval))
        assert (src, dst) == (str(source), plan.target_path)
        assert approval == dict(expected_fingerprint=plan.source_fingerprint, expected_identity=None,
                                allowed_roots=(str(tmp_path),))
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(rename_module, "_safe_move", fail_before_effect)
    result = RenameExecutor(PreflightService([str(tmp_path)])).execute([plan], "batch-1")[0]
    assert len(calls) == 1 and result.success is False and result.recovery_required
    assert result.error == 'fileops.error.nativeRecovery' and result.new_path == ''
    assert result.owned_residue_paths == (str(source), plan.target_path)
    assert source.read_bytes() == b'pdf' and not source.with_name(plan.target_name).exists()
    assert SourceFingerprint(source.stat().st_size, source.stat().st_mtime_ns) == plan.source_fingerprint
    assert list(tmp_path.iterdir()) == [source]
    presentation = ErrorHandler.from_execution_error(result.error, scope=ErrorScope.FILE)
    assert presentation.layer is PresentationLayer.FILE_CARD
    assert presentation.error.code == 'file_io' and presentation.error.retryable is False


def test_raw_disk_full_classifier_routes_to_file_card():
    presentation = ErrorHandler.from_execution_error(
        str(OSError(errno.ENOSPC, 'No space left on device')), scope=ErrorScope.FILE)
    assert presentation.layer is PresentationLayer.FILE_CARD
    assert presentation.error.code == "disk_full"


def test_opaque_permission_boundary_exception_requires_nonretryable_recovery(tmp_path, monkeypatch):
    source, plan = _plan(tmp_path)
    calls = []
    def fail_before_effect(src, dst, **approval):
        calls.append((src, dst, approval))
        assert (src, dst) == (str(source), plan.target_path)
        assert approval == dict(expected_fingerprint=plan.source_fingerprint, expected_identity=None,
                                allowed_roots=(str(tmp_path),))
        raise PermissionError(errno.EACCES, "Access denied")
    monkeypatch.setattr(rename_module, "_safe_move", fail_before_effect)
    result = RenameExecutor(PreflightService([str(tmp_path)])).execute([plan], "batch-1")[0]
    assert len(calls) == 1 and result.success is False and result.recovery_required
    assert result.error == 'fileops.error.nativeRecovery' and result.new_path == ''
    assert result.owned_residue_paths == (str(source), plan.target_path)
    assert source.read_bytes() == b'pdf' and not source.with_name(plan.target_name).exists()
    assert SourceFingerprint(source.stat().st_size, source.stat().st_mtime_ns) == plan.source_fingerprint
    assert list(tmp_path.iterdir()) == [source]
    presentation = ErrorHandler.from_execution_error(result.error, scope=ErrorScope.FILE)
    assert presentation.layer is PresentationLayer.FILE_CARD
    assert presentation.error.code == 'file_io' and presentation.error.retryable is False


def test_raw_permission_classifier_is_explicit_and_non_retryable():
    presentation = ErrorHandler.from_execution_error(
        str(PermissionError(errno.EACCES, 'Access denied')), scope=ErrorScope.FILE)
    assert presentation.error.code == "permission"
    assert presentation.error.retryable is False


def test_file_locked_is_retryable_and_stays_per_file():
    presentation = ErrorHandler.from_execution_error(
        "OS error: [WinError 32] The process cannot access the file because it is being used",
        scope=ErrorScope.FILE,
    )
    assert presentation.layer is PresentationLayer.FILE_CARD
    assert presentation.error.code == "file_locked"
    assert presentation.error.retryable is True

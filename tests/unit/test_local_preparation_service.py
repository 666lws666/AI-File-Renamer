"""Lifecycle contract tests with exact owned-runner seam."""
import importlib
import time
import threading
from dataclasses import replace

import pytest


def test_service_is_available():
    assert importlib.util.find_spec("src.services.local_ai.preparation_service") is not None


def setup_service(runner):
    p = importlib.import_module("src.services.local_ai.preparation_protocol")
    s = importlib.import_module("src.services.local_ai.preparation_service")
    return p, s.BoundedLocalPreparationService(_runner=runner)


def completed(p, **kwargs):
    from src.services.local_ai.native.process import ProcessResult
    value = p.LocalPreparationResult("actual text", (), p.PreparationCoverage(content_kind="text", sections_processed=1, sections_total=1), (), "balanced")
    return replace(ProcessResult("completed", 0, p.encode_result(value), b"private stderr", 123, True, .01), **kwargs)


def test_fixed_isolated_launch_and_sanitized_environment(tmp_path, monkeypatch):
    calls = []
    p, service = setup_service(lambda *args, **kw: calls.append((args, kw)) or completed(p))
    monkeypatch.setenv("OPENAI_API_KEY", "private")
    monkeypatch.setenv("PYTHONPATH", "hostile")
    result = service.prepare(tmp_path / "a.txt", limits=p.LocalPreparationLimits(), quality_mode="balanced", deadline=time.monotonic()+10, cancelled=lambda: False)
    assert result.text == "actual text"
    args, kw = calls[0]
    assert args[1][:2] == ("-I", "-c")
    assert "OPENAI_API_KEY" not in kw["environment"] and "PYTHONPATH" not in kw["environment"]
    assert kw["stdout_limit"] == 17*1024*1024 and kw["stderr_limit"] == 65536
    assert 0 < kw["timeout_seconds"] < 10


@pytest.mark.parametrize("change", [{"exit_code":1}, {"status":"output_limit"}, {"stdout": b"private invalid stream"}])
def test_no_raw_stream_or_unsuccessful_result_escapes(tmp_path, change):
    p, service = setup_service(lambda *a, **k: completed(p, **change))
    with pytest.raises(p.PreparationError) as caught:
        service.prepare(tmp_path / "secret.txt", limits=p.LocalPreparationLimits(), quality_mode="balanced", deadline=time.monotonic()+10, cancelled=lambda:False)
    assert "private" not in str(caught.value) and "secret" not in str(caught.value)


def test_cancel_callback_exception_latches_and_denies_launch(tmp_path):
    p, service = setup_service(lambda *a, **k: pytest.fail("must not launch"))
    def broken():
        raise RuntimeError("private")
    with pytest.raises(p.PreparationError) as caught:
        service.prepare(tmp_path / "a.txt", limits=p.LocalPreparationLimits(), quality_mode="balanced", deadline=time.monotonic()+10, cancelled=broken)
    assert caught.value.code == "cancelled"


def test_pending_exact_owner_blocks_new_worker_until_retry(tmp_path):
    from src.services.local_ai.native.process import ProcessCleanupResult
    class Owner:
        complete = False
        def retry_reap(self, *, deadline):
            return ProcessCleanupResult(self.complete, self.complete)
    owner, calls = Owner(), []
    p, service = setup_service(lambda *a, **k: calls.append(1) or completed(p, status="cleanup_incomplete", cleanup_complete=False, pending_owner=owner))
    def prepare():
        return service.prepare(tmp_path / "a.txt", limits=p.LocalPreparationLimits(), quality_mode="balanced", deadline=time.monotonic()+1, cancelled=lambda:False)
    with pytest.raises(p.PreparationError):
        prepare()
    with pytest.raises(p.PreparationError):
        prepare()
    assert len(calls) == 1 and service._pending_owner is owner
    assert service.retry_cleanup(time.monotonic()+.1) is False
    owner.complete = True
    assert service.retry_cleanup(time.monotonic()+.1) is True
    assert service._pending_owner is None


def test_ownership_interruption_retains_original_owner_and_close_is_bounded(tmp_path):
    from src.services.local_ai.native.process import ProcessOwnershipInterrupted
    class Owner:
        def retry_reap(self, *, deadline):
            raise ProcessOwnershipInterrupted(self, "keyboard_interrupt")
    owner = Owner()
    def runner(*a, **k):
        raise ProcessOwnershipInterrupted(owner, "keyboard_interrupt")
    p, service = setup_service(runner)
    with pytest.raises(p.PreparationError) as caught:
        service.prepare(tmp_path / "a.txt", limits=p.LocalPreparationLimits(), quality_mode="balanced", deadline=time.monotonic()+1, cancelled=lambda:False)
    assert caught.value.code == "cleanup_incomplete" and service._pending_owner is owner
    started = time.monotonic()
    assert service.close(started+.02) is False
    assert time.monotonic()-started < .2 and service._pending_owner is owner


def test_cancellation_latches_even_if_callback_recovers(tmp_path):
    state = {"broken": False}
    def callback():
        if state["broken"]:
            raise RuntimeError("private")
        return False
    def runner(*a, **kwargs):
        state["broken"] = True
        assert kwargs["cancellation_event"].is_set()
        state["broken"] = False
        assert kwargs["cancellation_event"].is_set()
        return completed(p)
    p, service = setup_service(runner)
    with pytest.raises(p.PreparationError) as caught:
        service.prepare(tmp_path / "a.txt", limits=p.LocalPreparationLimits(), quality_mode="balanced", deadline=time.monotonic()+1, cancelled=callback)
    assert caught.value.code == "cancelled"


def test_queue_cancel_timeout_and_close_do_not_launch_second_child(tmp_path):
    started, release = threading.Event(), threading.Event()
    calls, outcomes = [], []
    def runner(*a, **k):
        calls.append(1)
        started.set()
        assert release.wait(2)
        return completed(p)
    p, service = setup_service(runner)
    def first():
        try:
            service.prepare(tmp_path / "first.txt", limits=p.LocalPreparationLimits(), quality_mode="balanced", deadline=time.monotonic()+3, cancelled=lambda:False)
        except p.PreparationError as error:
            outcomes.append(error.code)
    thread = threading.Thread(target=first)
    thread.start()
    assert started.wait(1)
    try:
        with pytest.raises(p.PreparationError) as caught:
            service.prepare(tmp_path / "second.txt", limits=p.LocalPreparationLimits(), quality_mode="balanced", deadline=time.monotonic()+.05, cancelled=lambda:False)
        assert caught.value.code == "timeout"
        assert service.close(time.monotonic()+.02) is False
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive() and calls == [1] and outcomes == ["closed"]
    assert service.close(time.monotonic()+.1)


def test_stale_callback_after_decode_and_late_result_never_published(tmp_path, monkeypatch):
    from src.services.local_ai import preparation_service as s
    cancelled = {"value": False}
    real_decode = s.decode_result
    def decode(*a, **k):
        result = real_decode(*a, **k)
        cancelled["value"] = True
        return result
    monkeypatch.setattr(s, "decode_result", decode)
    p, service = setup_service(lambda *a, **k: completed(p))
    with pytest.raises(p.PreparationError) as caught:
        service.prepare(tmp_path / "a.txt", limits=p.LocalPreparationLimits(), quality_mode="balanced", deadline=time.monotonic()+1, cancelled=lambda:cancelled["value"])
    assert caught.value.code == "cancelled"


def test_full_frame_through_owned_runner_seam(tmp_path):
    from tests.unit.test_local_preparation_protocol import valid_visual_result
    from src.services.local_ai.native.process import ProcessResult
    p, service = setup_service(lambda *a, **k: ProcessResult("completed", 0, p.encode_result(valid_visual_result(giant=True)), b"", 123, True, .1))
    result = service.prepare(tmp_path / "a.pdf", limits=p.LocalPreparationLimits(max_text_chars=32768), quality_mode="balanced", deadline=time.monotonic()+5, cancelled=lambda:False)
    assert len(result.visuals) == 8 and len(result.text.encode()) == 32768


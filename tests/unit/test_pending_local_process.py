"""Retry ownership checks using harmless native children and exact-handle faults."""
import ctypes as C
import math
import threading
import time

import pytest

from .test_local_probe_process import runner, run, assert_gone


@pytest.fixture
def tracked(runner, monkeypatch):
    api = runner._api
    originals = {name: getattr(api, name) for name in (
        "CreateJobObjectW", "CreatePipe", "CreateProcessW", "CloseHandle",
        "TerminateJobObject", "TerminateProcess", "WaitForSingleObject",
        "QueryInformationJobObject", "DeleteProcThreadAttributeList")}
    live, acquired, closed, deleted = {}, [], [], []

    def adopt(handle, kind):
        if handle:
            live[handle] = kind
            acquired.append((handle, kind))

    def job(*args):
        handle = originals["CreateJobObjectW"](*args)
        adopt(handle, "job")
        return handle

    def pipe(*args):
        result = originals["CreatePipe"](*args)
        adopt(args[0]._obj.value, "pipe")
        adopt(args[1]._obj.value, "pipe")
        return result

    def create(*args):
        result = originals["CreateProcessW"](*args)
        adopt(args[-1]._obj.hProcess, "process")
        adopt(args[-1]._obj.hThread, "thread")
        return result

    def close(handle):
        assert handle in live, "successfully closed handle was closed again"
        result = originals["CloseHandle"](handle)
        if result:
            del live[handle]
            closed.append(handle)
        return result

    def delete(attributes):
        deleted.append(C.addressof(attributes))
        return originals["DeleteProcThreadAttributeList"](attributes)

    for name, method in (("CreateJobObjectW", job), ("CreatePipe", pipe),
                         ("CreateProcessW", create), ("CloseHandle", close),
                         ("DeleteProcThreadAttributeList", delete)):
        monkeypatch.setattr(api, name, method)
    state = dict(live=live, acquired=acquired, closed=closed, deleted=deleted,
                 close=close, create=create, pipe=pipe, originals=originals)
    yield state
    # RED failures must also release exactly the original handles, never reopen PID.
    for handle, kind in list(live.items()):
        if kind == "job":
            originals["TerminateJobObject"](handle, 1)
        elif kind == "process":
            originals["TerminateProcess"](handle, 1)
            originals["WaitForSingleObject"](handle, 3000)
    for handle in list(live):
        originals["CloseHandle"](handle)


def pending(result):
    assert result.status == "cleanup_incomplete" and not result.cleanup_complete
    owner = getattr(result, "pending_owner", None)
    assert owner is not None, "incomplete cleanup must retain its exact native owner"
    return owner


@pytest.mark.parametrize("fault", ["query", "wait", "termination"])
def test_cancelled_owner_retries_same_handles_despite_original_cancel(runner, tmp_path, monkeypatch, tracked, fault):
    event = threading.Event()
    resume = runner._api.ResumeThread

    def cancel_after_resume(handle):
        result = resume(handle)
        event.set()
        return result

    monkeypatch.setattr(runner._api, "ResumeThread", cancel_after_resume)
    names = {"query": ["QueryInformationJobObject"], "wait": ["WaitForSingleObject"],
             "termination": ["TerminateJobObject", "TerminateProcess"]}[fault]
    for name in names:
        monkeypatch.setattr(runner._api, name, lambda *args: 0xFFFFFFFF if fault == "wait" else 0)
    result = run(runner, tmp_path, "import time; time.sleep(60)", cancellation_event=event,
                 cleanup_timeout_seconds=.03)
    owner = pending(result)
    assert result.stop_reason == "cancelled" and event.is_set()
    exact = {h for h, kind in tracked["acquired"] if kind in {"job", "process"}}
    assert exact <= tracked["live"].keys()
    assert len(tracked["deleted"]) == 1
    for name in names:
        monkeypatch.setattr(runner._api, name, tracked["originals"][name])
    cleanup = owner.retry_reap(deadline=time.monotonic() + 1)
    assert cleanup.tree_exited and cleanup.handles_closed
    assert not tracked["live"]
    assert owner.retry_reap(deadline=time.monotonic() + 1) == cleanup
    assert_gone(result.pid)


@pytest.mark.parametrize("reason", ["completed", "timeout", "output_limit"])
def test_pending_preserves_original_stop_reason(runner, tmp_path, monkeypatch, tracked, reason):
    monkeypatch.setattr(runner._api, "QueryInformationJobObject", lambda *args: 0)
    code, options = {
        "completed": ("print('private-stream')", {}),
        "timeout": ("import time; time.sleep(60)", {"timeout_seconds": .1}),
        "output_limit": ("import os; os.write(1,b'x'*10000)", {"stdout_limit": 8}),
    }[reason]
    result = run(runner, tmp_path, code, cleanup_timeout_seconds=.02, **options)
    owner = pending(result)
    assert result.stop_reason == reason
    assert "private-stream" not in repr(result)
    monkeypatch.setattr(runner._api, "QueryInformationJobObject", tracked["originals"]["QueryInformationJobObject"])
    assert owner.retry_reap(deadline=time.monotonic() + 1).handles_closed


def test_failed_final_close_retains_only_failed_handle_and_confirmed_exit(runner, tmp_path, monkeypatch, tracked):
    def close(handle):
        if tracked["live"].get(handle) == "job":
            C.set_last_error(6)
            return False
        return tracked["close"](handle)

    monkeypatch.setattr(runner._api, "CloseHandle", close)
    result = run(runner, tmp_path, "pass")
    owner = pending(result)
    cleanup = owner.retry_reap(deadline=time.monotonic() + 1)
    assert cleanup.tree_exited and not cleanup.handles_closed
    assert (cleanup.error_stage, cleanup.win32_error) == ("handle_close", 6)
    assert list(tracked["live"].values()) == ["job"]
    monkeypatch.setattr(runner, "_reap", lambda *args: pytest.fail("confirmed tree queried again"))
    monkeypatch.setattr(runner._api, "CloseHandle", tracked["close"])
    assert owner.retry_reap(deadline=time.monotonic() + 1).handles_closed
    assert not tracked["live"]


@pytest.mark.parametrize("where", ["limits", "pipe", "partial_create"])
def test_partial_acquisition_retains_handles_for_retry(runner, tmp_path, monkeypatch, tracked, where):
    failed = where != "partial_create"
    if where == "limits":
        monkeypatch.setattr(runner._api, "SetInformationJobObject", lambda *args: 0)
    elif where == "pipe":
        def pipe(*args):
            assert tracked["pipe"](*args)
            raise RuntimeError("private-pipe-failure")
        monkeypatch.setattr(runner._api, "CreatePipe", pipe)
    else:
        def create(*args):
            nonlocal failed
            assert tracked["create"](*args)
            failed = True
            return False
        monkeypatch.setattr(runner._api, "CreateProcessW", create)
    monkeypatch.setattr(runner._api, "CloseHandle", lambda h: 0 if failed else tracked["close"](h))
    result = run(runner, tmp_path, "pass")
    owner = pending(result)
    assert result.stop_reason == "launch_error"
    assert len(tracked["live"]) == len(tracked["acquired"]) - len(tracked["closed"])
    monkeypatch.setattr(runner._api, "CloseHandle", tracked["close"])
    assert owner.retry_reap(deadline=time.monotonic() + 1).handles_closed
    assert not tracked["live"]


@pytest.mark.parametrize("where", ["launch", "cleanup", "close", "metadata"])
def test_interrupted_unwind_hands_off_owner_with_safe_category(runner, tmp_path, monkeypatch, tracked, where):
    def interrupt(*args):
        raise KeyboardInterrupt("private-interruption-text")

    if where == "launch":
        monkeypatch.setattr(runner._api, "ResumeThread", interrupt)
        monkeypatch.setattr(runner._api, "QueryInformationJobObject", lambda *args: 0)
    elif where == "cleanup":
        monkeypatch.setattr(runner._api, "TerminateJobObject", interrupt)
    elif where == "close":
        def close(handle):
            if tracked["live"].get(handle) == "job":
                interrupt()
            return tracked["close"](handle)
        monkeypatch.setattr(runner._api, "CloseHandle", close)
    else:
        delete = runner._api.DeleteProcThreadAttributeList
        def delete_then_interrupt(attributes):
            delete(attributes)
            interrupt()
        monkeypatch.setattr(runner._api, "DeleteProcThreadAttributeList", delete_then_interrupt)
        monkeypatch.setattr(runner._api, "QueryInformationJobObject", lambda *args: 0)
    with pytest.raises(BaseException) as captured:
        run(runner, tmp_path, "print('private-stream')", cleanup_timeout_seconds=.02)
    exc = captured.value
    assert type(exc).__name__ == "ProcessOwnershipInterrupted"
    assert exc.original_category == "keyboard_interrupt"
    assert "private" not in str(exc) + repr(exc)
    assert len(tracked["deleted"]) == 1
    monkeypatch.setattr(runner._api, "TerminateJobObject", tracked["originals"]["TerminateJobObject"])
    monkeypatch.setattr(runner._api, "QueryInformationJobObject", tracked["originals"]["QueryInformationJobObject"])
    monkeypatch.setattr(runner._api, "CloseHandle", tracked["close"])
    assert exc.pending_owner.retry_reap(deadline=time.monotonic() + 1).handles_closed
    assert len(tracked["deleted"]) == 1 and not tracked["live"]


def test_clean_interruption_preserves_original_exception(runner, tmp_path, monkeypatch, tracked):
    original = KeyboardInterrupt("original")
    def interrupt(*args):
        raise original
    monkeypatch.setattr(runner._api, "ResumeThread", interrupt)
    with pytest.raises(KeyboardInterrupt) as captured:
        run(runner, tmp_path, "pass")
    assert captured.value is original and not tracked["live"]


@pytest.mark.parametrize("interrupt", [False, True])
def test_drain_error_does_not_undo_confirmed_tree_exit(runner, tmp_path, monkeypatch, tracked, interrupt):
    reaped = False
    reap, read = runner._reap, runner._read_chunk
    def confirm(*args):
        nonlocal reaped
        reaped = reap(*args)
        return reaped
    def drain(*args):
        if reaped:
            if interrupt:
                raise KeyboardInterrupt("private-drain")
            raise RuntimeError("private-drain")
        return read(*args)
    monkeypatch.setattr(runner, "_reap", confirm)
    monkeypatch.setattr(runner, "_read_chunk", drain)
    if interrupt:
        with pytest.raises(KeyboardInterrupt):
            run(runner, tmp_path, "pass")
    else:
        result = run(runner, tmp_path, "pass")
        assert result.cleanup_complete and result.pending_owner is None
        assert result.status == "launch_error"
    assert not tracked["live"]


@pytest.mark.parametrize("deadline", [True, None, "private", math.inf, -math.inf, math.nan, 10**400])
def test_retry_rejects_invalid_deadlines_without_native_work(runner, tmp_path, monkeypatch, tracked, deadline):
    monkeypatch.setattr(runner._api, "QueryInformationJobObject", lambda *args: 0)
    owner = pending(run(runner, tmp_path, "pass", cleanup_timeout_seconds=.01))
    monkeypatch.setattr(runner, "_reap", lambda *args: pytest.fail("invalid budget did native work"))
    with pytest.raises(ValueError, match="^invalid cleanup deadline$"):
        owner.retry_reap(deadline=deadline)


def test_expired_retry_is_bounded_and_does_not_discard_owner(runner, tmp_path, monkeypatch, tracked):
    monkeypatch.setattr(runner._api, "QueryInformationJobObject", lambda *args: 0)
    owner = pending(run(runner, tmp_path, "pass", cleanup_timeout_seconds=.01))
    monkeypatch.setattr(runner, "_reap", lambda *args: pytest.fail("expired budget started cleanup"))
    result = owner.retry_reap(deadline=time.monotonic() - 1)
    assert not result.tree_exited and not result.handles_closed


def test_concurrent_retries_never_double_close(runner, tmp_path, monkeypatch, tracked):
    monkeypatch.setattr(runner._api, "QueryInformationJobObject", lambda *args: 0)
    owner = pending(run(runner, tmp_path, "pass", cleanup_timeout_seconds=.01))
    monkeypatch.setattr(runner._api, "QueryInformationJobObject", tracked["originals"]["QueryInformationJobObject"])
    results, errors = [], []
    def retry():
        try:
            results.append(owner.retry_reap(deadline=time.monotonic() + 1))
        except BaseException as exc:
            errors.append(exc)
    threads = [threading.Thread(target=retry) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
    assert not errors and len(results) == 6 and not tracked["live"]
    assert all(result.tree_exited and result.handles_closed for result in results)


@pytest.mark.parametrize("where", ["lock", "reap", "close"])
@pytest.mark.parametrize("exception,category", [(SystemExit, "system_exit"),
                                               (GeneratorExit, "generator_exit"),
                                               (BaseException, "base_exception")])
def test_retry_interrupt_always_preserves_owner(runner, tmp_path, monkeypatch, tracked, where, exception, category):
    monkeypatch.setattr(runner._api, "QueryInformationJobObject", lambda *args: 0)
    owner = pending(run(runner, tmp_path, "pass", cleanup_timeout_seconds=.01))
    monkeypatch.setattr(runner._api, "QueryInformationJobObject", tracked["originals"]["QueryInformationJobObject"])
    def interrupt(*args, **kwargs):
        raise exception("private-retry-interruption")
    with monkeypatch.context() as fault:
        if where == "lock":
            class InterruptedLock:
                acquire = staticmethod(interrupt)
            fault.setattr(owner, "_lock", InterruptedLock())
        elif where == "reap":
            fault.setattr(runner, "_reap", interrupt)
        else:
            fault.setattr(runner._api, "CloseHandle", interrupt)
        with pytest.raises(BaseException) as captured:
            owner.retry_reap(deadline=time.monotonic() + 1)
    exc = captured.value
    assert isinstance(exc, runner.ProcessOwnershipInterrupted)
    assert exc.pending_owner is owner and exc.original_category == category
    assert "private" not in repr(exc) + str(exc)
    assert owner.retry_reap(deadline=time.monotonic() + 1).handles_closed
    assert not tracked["live"]


def test_retry_lock_wait_obeys_deadline(runner, tmp_path, monkeypatch, tracked):
    monkeypatch.setattr(runner._api, "QueryInformationJobObject", lambda *args: 0)
    owner = pending(run(runner, tmp_path, "pass", cleanup_timeout_seconds=.01))
    results = []
    with owner._lock:
        thread = threading.Thread(target=lambda: results.append(owner.retry_reap(deadline=time.monotonic() + .02)))
        thread.start()
        thread.join(1)
        assert not thread.is_alive()
    assert len(results) == 1 and not results[0].handles_closed
    monkeypatch.setattr(runner._api, "QueryInformationJobObject", tracked["originals"]["QueryInformationJobObject"])
    assert owner.retry_reap(deadline=time.monotonic() + 1).handles_closed


def test_complete_return_has_no_pending_owner_and_hides_stream_repr(runner, tmp_path, tracked):
    result = run(runner, tmp_path, "import os; os.write(1,b'private-out'); os.write(2,b'private-err')")
    assert result.cleanup_complete and result.pending_owner is None
    assert result.stop_reason == result.status == "completed"
    assert (result.stdout, result.stderr) == (b"private-out", b"private-err")
    assert "private" not in repr(result) and not tracked["live"]

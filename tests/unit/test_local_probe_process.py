"""Native, harmless Windows process lifecycle checks (never loads a model)."""
import importlib.util
import ctypes as C
from ctypes import wintypes as W
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import win32api
import win32event
import pywintypes


MODULE = Path(__file__).resolve().parents[2] / "src" / "services" / "local_ai" / "native" / "process.py"


def test_stdout_only_accepts_preparation_frame_upper_bound(runner, tmp_path):
    runner._validated(Path(sys.executable), (), tmp_path, {}, 1, (17*1024*1024, 16*1024*1024), 1)
    for bounds in ((17*1024*1024+1, 1), (1, 16*1024*1024+1)):
        with pytest.raises(ValueError):
            runner._validated(Path(sys.executable), (), tmp_path, {}, 1, bounds, 1)


def test_result_token_evidence_preserves_positional_compatibility(runner):
    result = runner.ProcessResult("completed", 0, b"", b"", None, True, 0)
    assert result.token_evidence is None
    assert result.pending_owner is None and result.stop_reason is None


@pytest.mark.parametrize("kind", ["arbitrary", "inactive", "closed", "modified", "subclass"])
def test_invalid_security_is_rejected_before_resources(runner, tmp_path, monkeypatch, kind):
    from scripts.local_probe_security import AppContainerSecurity, SecurityContextError
    monkeypatch.setattr(runner._api, "CreateJobObjectW", lambda *args: pytest.fail("resources created"))
    if kind == "arbitrary":
        ctx = object()
    elif kind == "subclass":
        class CallerContext(AppContainerSecurity):
            pass
        ctx = CallerContext("S-1-15-2-1-2-3-4-5-6-7")
    else:
        ctx = AppContainerSecurity("S-1-15-2-1-2-3-4-5-6-7")
    try:
        if kind in {"closed", "modified"}:
            ctx.__enter__()
        if kind == "closed":
            ctx.close()
        if kind == "modified":
            ctx.capabilities.CapabilityCount = 1
        with pytest.raises(SecurityContextError):
            run(runner, tmp_path, "pass", security_context=ctx)
    finally:
        if isinstance(ctx, AppContainerSecurity):
            ctx.close()


@pytest.fixture
def token_boundary(runner, monkeypatch):
    """Real ordinary child/job/pipes; simulated security attribute and token data.

    Never claims that the resulting ordinary child is an AppContainer.
    """
    from scripts.local_probe_security import AppContainerSecurity
    ctx = AppContainerSecurity("S-1-15-2-1-2-3-4-5-6-7").__enter__()
    state = {"events": [], "counts": [], "creates": [], "fault": None,
             "attached": None, "deleted_pointer": None, "cancel": None, "expired": False}
    expected = ctx.capabilities
    expected_bytes = C.string_at(expected.AppContainerSid, 40)
    original_init = runner._api.InitializeProcThreadAttributeList
    original_update = runner._api.UpdateProcThreadAttribute
    original_create = runner._api.CreateProcessW
    original_member = runner._api.IsProcessInJob
    original_resume = runner._api.ResumeThread
    original_delete = runner._api.DeleteProcThreadAttributeList
    def initialize(attributes, count, flags, size):
        state["counts"].append(count)
        return original_init(attributes, count, flags, size)
    def update(attributes, flags, key, value, size, previous, returned):
        state["events"].append(f"attribute:{key}")
        if key == 0x00020009:
            assert C.addressof(value._obj) == C.addressof(expected)
            assert size == C.sizeof(expected)
            assert not expected.Capabilities and expected.CapabilityCount == expected.Reserved == 0
            state["attached"] = expected.AppContainerSid
            if state["fault"] == "attach":
                C.set_last_error(50)
                return False
            return True  # intercepted: DO NOT attach security to the native child
        return original_update(attributes, flags, key, value, size, previous, returned)
    def create(*args):
        state["events"].append("create")
        assert args[4] is True and args[5] & 4 and args[5] & 0x08000000
        result = original_create(*args)
        state["creates"].append(args[-1]._obj.hProcess)
        return result
    def member(*args):
        state["events"].append("membership")
        return original_member(*args)
    def resume(handle):
        state["events"].append("resume")
        return original_resume(handle)
    def delete(attributes):
        state["deleted_pointer"] = ctx.capabilities.AppContainerSid
        return original_delete(attributes)
    def open_token(process, access, out):
        assert process == state["creates"][0] and access == 8
        state["events"].append("token_open")
        C.cast(out, C.POINTER(W.HANDLE))[0] = 987654
        return True
    def token_info(token, kind, buffer, capacity, returned):
        assert token == 987654
        state["events"].append(f"token:{kind}")
        size = 48 if kind == 31 else 4
        C.cast(returned, C.POINTER(W.DWORD))[0] = size
        if state["fault"] == "query_exception":
            raise RuntimeError("sensitive-native-text-must-not-leak")
        if state["fault"] == "query":
            C.set_last_error(5)
            return False
        if not buffer:
            C.set_last_error(122)
            return False
        if kind == 31:
            sid = C.addressof(buffer) + C.sizeof(C.c_void_p)
            C.memmove(sid, expected_bytes, 40)
            if state["fault"] == "identity":
                C.c_ubyte.from_address(sid + 36).value = 8
            C.c_void_p.from_buffer(buffer).value = sid
        else:
            W.DWORD.from_buffer(buffer).value = int(kind == 29)
            if state["fault"] == "noncontainer" and kind == 29:
                W.DWORD.from_buffer(buffer).value = 0
            if state["fault"] == "capabilities" and kind == 30:
                W.DWORD.from_buffer(buffer).value = 1
        if kind == 30 and state["cancel"] is not None:
            state["cancel"].set()
        if kind == 30 and state["fault"] == "expire":
            state["expired"] = True
        return True
    def close_token(handle):
        assert handle == 987654
        state["events"].append("token_close")
        if state["fault"] == "token_close":
            C.set_last_error(6)
            return False
        return True
    for name, value in (("InitializeProcThreadAttributeList", initialize),
                        ("UpdateProcThreadAttribute", update), ("CreateProcessW", create),
                        ("IsProcessInJob", member), ("ResumeThread", resume),
                        ("DeleteProcThreadAttributeList", delete)):
        monkeypatch.setattr(runner._api, name, value)
    monkeypatch.setattr(ctx._bindings, "OpenProcessToken", open_token)
    monkeypatch.setattr(ctx._bindings, "GetTokenInformation", token_info)
    monkeypatch.setattr(ctx._bindings, "CloseHandle", close_token)
    try:
        yield ctx, state
    finally:
        ctx.close()


def test_security_attached_and_verified_before_resume(runner, tmp_path, token_boundary):
    ctx, state = token_boundary
    result = run(runner, tmp_path, "print('synthetic-output')", security_context=ctx)
    assert result.status == "completed" and result.cleanup_complete
    assert result.token_evidence.package_sid == "S-1-15-2-1-2-3-4-5-6-7"
    assert result.token_evidence.is_appcontainer and result.token_evidence.capability_count == 0
    assert state["counts"] == [3, 3]
    assert state["attached"] == state["deleted_pointer"] == ctx.capabilities.AppContainerSid
    events = state["events"]
    assert events.index("membership") < events.index("token_open") < events.index("token_close") < events.index("resume")
    assert len(state["creates"]) == 1
    assert [event for event in events if event.startswith("attribute:")] == [
        "attribute:131074", "attribute:131085", "attribute:131081"]


@pytest.mark.parametrize("fault,stage,code", [
    ("attach", "security_capabilities", 50), ("query", "token_size", 5),
    ("identity", "token_sid_mismatch", 5), ("noncontainer", "token_is_appcontainer", 5),
    ("capabilities", "token_capabilities", 5), ("token_close", "token_close", 6),
    ("query_exception", "token_size", 13),
])
def test_security_failure_never_resumes_or_retries(runner, tmp_path, token_boundary, fault, stage, code):
    ctx, state = token_boundary
    state["fault"] = fault
    marker = tmp_path / "must-not-run"
    result = run(runner, tmp_path, f"from pathlib import Path; Path({str(marker)!r}).touch()", security_context=ctx)
    assert result.status == "launch_error" and result.cleanup_complete
    assert (result.error_stage, result.win32_error) == (stage, code)
    assert result.token_evidence is None and "resume" not in state["events"]
    assert "sensitive-native" not in repr(result)
    assert len(state["creates"]) == (0 if fault == "attach" else 1)
    assert not marker.exists() and ctx.capabilities.AppContainerSid
    if result.pid:
        assert_gone(result.pid)


def test_cancel_during_token_verification_does_not_resume(runner, tmp_path, token_boundary):
    ctx, state = token_boundary
    event = threading.Event()
    state["cancel"] = event
    result = run(runner, tmp_path, "pass", security_context=ctx, cancellation_event=event)
    assert result.status == "cancelled" and result.cleanup_complete
    assert "resume" not in state["events"] and len(state["creates"]) == 1
    assert result.token_evidence is not None  # identity evidence != lifecycle success
    assert_gone(result.pid)


def test_default_attributes_remain_two_and_stdout_cannot_supply_evidence(runner, tmp_path, monkeypatch):
    counts = []
    initialize = runner._api.InitializeProcThreadAttributeList
    def record(attributes, count, flags, size):
        counts.append(count)
        return initialize(attributes, count, flags, size)
    monkeypatch.setattr(runner._api, "InitializeProcThreadAttributeList", record)
    result = run(runner, tmp_path, "print('TokenEvidence: verified')")
    assert result.status == "completed" and result.token_evidence is None
    assert counts == [2, 2]


def test_deadline_during_token_verification_does_not_resume(runner, tmp_path, token_boundary, monkeypatch):
    ctx, state = token_boundary
    state["fault"] = "expire"
    monotonic = time.monotonic
    monkeypatch.setattr(runner.time, "monotonic", lambda: monotonic() + (100 if state["expired"] else 0))
    result = run(runner, tmp_path, "pass", security_context=ctx)
    assert result.status == "timeout" and result.cleanup_complete
    assert "resume" not in state["events"] and len(state["creates"]) == 1
    assert result.token_evidence is not None
    assert_gone(result.pid)


def test_instance_verifier_callback_cannot_supply_evidence(runner, tmp_path, token_boundary):
    from scripts.local_probe_security import AppContainerSecurity
    assert runner.AppContainerSecurity is AppContainerSecurity
    ctx, state = token_boundary
    state["fault"] = "noncontainer"
    ctx.verify_process = lambda handle: pytest.fail("caller verifier executed")
    result = run(runner, tmp_path, "pass", security_context=ctx)
    assert result.status == "launch_error" and result.cleanup_complete
    assert result.error_stage == "token_is_appcontainer" and result.token_evidence is None
    assert "resume" not in state["events"]


def test_module_contract_exists():
    assert MODULE.is_file(), "bounded process module/API is not implemented"
    spec = importlib.util.spec_from_file_location("local_probe_process", MODULE)
    assert spec is not None


@pytest.fixture
def runner():
    assert sys.platform == "win32", "native Windows proof must run on Windows"
    assert MODULE.is_file(), "bounded process module/API is not implemented"
    spec = importlib.util.spec_from_file_location("local_probe_process", MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def environment():
    return {"SystemRoot": os.environ["SystemRoot"], "PYTHONIOENCODING": "utf-8"}


def run(runner, tmp_path, code, **kwargs):
    options = dict(cwd=tmp_path, environment=environment(), timeout_seconds=5)
    options.update(kwargs)
    return runner.run_bounded(Path(sys.executable), ["-I", "-u", "-c", code], **options)


def assert_gone(pid):
    try:
        handle = win32api.OpenProcess(0x00100000, False, pid)
    except pywintypes.error as exc:
        assert exc.winerror == 87
        return
    try:
        assert win32event.WaitForSingleObject(handle, 3000) == 0
    finally:
        handle.Close()


def test_capture_nonzero_exit(runner, tmp_path):
    result = run(runner, tmp_path, "import os; os.write(1,b'out'); os.write(2,b'err'); raise SystemExit(7)")
    assert (result.status, result.exit_code, result.stdout, result.stderr) == ("completed", 7, b"out", b"err")
    assert result.cleanup_complete and result.pid
    assert_gone(result.pid)
    with pytest.raises(AttributeError):
        result.status = "changed"


def test_unicode_quotes_spaces_and_empty_argv(runner, tmp_path):
    values = ["hello world", "中文", 'a"b', "", "back\\slash\\", 'space and end\\']
    result = runner.run_bounded(Path(sys.executable), ["-I", "-c", "import json,sys; print(json.dumps(sys.argv[1:]))", *values], cwd=tmp_path, environment=environment(), timeout_seconds=5)
    assert result.status == "completed"
    assert json.loads(result.stdout) == values


def test_explicit_environment_and_stdin_eof(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("BOUNDED_TEST_AMBIENT", "must-not-leak")
    result = run(runner, tmp_path, "import os,sys,json; print(json.dumps([os.getenv('BOUNDED_TEST_AMBIENT'),os.getenv('BOUNDED_TEST_EXPLICIT'),sys.stdin.buffer.read().hex()]))", environment={**environment(), "BOUNDED_TEST_EXPLICIT": "only-this"})
    assert result.status == "completed"
    assert json.loads(result.stdout) == [None, "only-this", ""]


def test_precancel_does_not_open_handles(runner, tmp_path, monkeypatch):
    event = threading.Event()
    event.set()
    monkeypatch.setattr(runner._api, "CreateJobObjectW", lambda *args: pytest.fail("must not open handles"))
    result = run(runner, tmp_path, "raise RuntimeError", cancellation_event=event)
    assert result.status == "cancelled" and result.pid is None and result.cleanup_complete


@pytest.mark.parametrize("options", [
    {"timeout_seconds": 0}, {"timeout_seconds": float("inf")}, {"timeout_seconds": float("nan")},
    {"cleanup_timeout_seconds": 0}, {"cleanup_timeout_seconds": 11}, {"cleanup_timeout_seconds": float("nan")},
    {"stdout_limit": 0}, {"stdout_limit": True}, {"stdout_limit": 1.5}, {"stdout_limit": 17825793},
    {"stderr_limit": -1}, {"environment": {"BAD=KEY": "value"}}, {"environment": {"": "value"}},
    {"environment": {"OK": "nul\x00"}}, {"environment": {"nul\x00": "value"}},
    {"cwd": Path("relative")}, {"cwd": Path("Z:/bounded-definitely-missing")},
])
def test_rejects_invalid_input_before_opening_handles(runner, tmp_path, monkeypatch, options):
    monkeypatch.setattr(runner._api, "CreateJobObjectW", lambda *args: pytest.fail("must not open handles"))
    with pytest.raises((ValueError, TypeError)):
        run(runner, tmp_path, "pass", **options)


@pytest.mark.parametrize("executable,args", [(Path("relative.exe"), []), (Path("Z:/bounded-missing.exe"), []), (Path(sys.executable), ["nul\x00"])])
def test_invalid_executable_or_argument(runner, tmp_path, monkeypatch, executable, args):
    monkeypatch.setattr(runner._api, "CreateJobObjectW", lambda *args: pytest.fail("must not open handles"))
    with pytest.raises((ValueError, TypeError)):
        runner.run_bounded(executable, args, cwd=tmp_path, environment=environment(), timeout_seconds=1)


def test_timeout_reaps_root(runner, tmp_path):
    result = run(runner, tmp_path, "import time; time.sleep(60)", timeout_seconds=.25)
    assert result.status == "timeout" and result.cleanup_complete
    assert result.elapsed_seconds < 4
    assert_gone(result.pid)


def test_active_cancellation(runner, tmp_path):
    event = threading.Event()
    timer = threading.Timer(.25, event.set)
    timer.start()
    try:
        result = run(runner, tmp_path, "import time; time.sleep(60)", cancellation_event=event)
    finally:
        timer.cancel()
        timer.join()
    assert result.status == "cancelled" and result.cleanup_complete
    assert_gone(result.pid)


@pytest.mark.parametrize("fd,limit_name", [(1, "stdout_limit"), (2, "stderr_limit")])
def test_output_overflow(runner, tmp_path, fd, limit_name):
    result = run(runner, tmp_path, f"import os,time; os.write({fd},b'x'*65536); time.sleep(60)", **{limit_name: 1024})
    assert result.status == "output_limit" and result.cleanup_complete
    assert len(result.stdout if fd == 1 else result.stderr) == 1024
    assert_gone(result.pid)


@pytest.mark.parametrize("cancel", [False, True])
def test_stream_flood_cannot_postpone_deadline_or_cancel(runner, tmp_path, cancel):
    event = threading.Event()
    timer = threading.Timer(.25, event.set)
    if cancel:
        timer.start()
    try:
        result = run(runner, tmp_path, "import os,time\nwhile True:\n os.write(1,b'x'*2048); os.write(2,b'y'*2048); time.sleep(.001)", timeout_seconds=5 if cancel else .25, cancellation_event=event, stdout_limit=16777216, stderr_limit=16777216)
    finally:
        if cancel:
            timer.cancel()
            timer.join()
    assert result.status == ("cancelled" if cancel else "timeout")
    assert result.cleanup_complete and result.elapsed_seconds < 4
    assert result.stdout and result.stderr


def test_normal_root_exit_kills_sleeping_grandchild(runner, tmp_path):
    code = "import subprocess,sys; p=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(60)']); print(p.pid,flush=True)"
    result = run(runner, tmp_path, code)
    assert result.status == "completed" and result.exit_code == 0 and result.cleanup_complete
    assert_gone(int(result.stdout.strip()))


def test_extra_inheritable_event_is_excluded(runner, tmp_path):
    security = pywintypes.SECURITY_ATTRIBUTES()
    security.bInheritHandle = True
    handle = win32event.CreateEvent(security, True, False, None)
    try:
        code = f"import ctypes; k=ctypes.WinDLL('kernel32',use_last_error=True); k.SetEvent.argtypes=[ctypes.c_void_p]; print(k.SetEvent({int(handle)}))"
        result = run(runner, tmp_path, code)
        assert result.status == "completed" and result.stdout.strip() == b"0"
        assert win32event.WaitForSingleObject(handle, 0) == 258
    finally:
        handle.Close()


def test_resume_failure_never_runs_suspended_child(runner, tmp_path, monkeypatch):
    marker = tmp_path / "must-not-exist"
    monkeypatch.setattr(runner._api, "ResumeThread", lambda handle: 0xFFFFFFFF)
    result = run(runner, tmp_path, f"from pathlib import Path; Path({str(marker)!r}).touch()")
    assert result.status == "launch_error" and result.cleanup_complete and result.pid
    assert result.error_stage == "resume"
    assert not marker.exists()
    assert_gone(result.pid)


def test_membership_check_failure_never_resumes(runner, tmp_path, monkeypatch):
    monkeypatch.setattr(runner._api, "IsProcessInJob", lambda *args: 0)
    monkeypatch.setattr(runner._api, "ResumeThread", lambda *args: pytest.fail("unverified process resumed"))
    result = run(runner, tmp_path, "pass")
    assert result.status == "launch_error" and result.cleanup_complete and result.pid
    assert_gone(result.pid)


@pytest.mark.parametrize("raise_after_create", [False, True])
def test_partial_create_failure_closes_returned_process_handles(runner, tmp_path, monkeypatch, raise_after_create):
    original_create = runner._api.CreateProcessW
    original_close = runner._api.CloseHandle
    created, closed = [], []

    def create_then_fail(*args):
        assert original_create(*args)
        info = args[-1]._obj
        created.extend([info.hProcess, info.hThread])
        if raise_after_create:
            raise RuntimeError("sensitive exception text must not be returned")
        return 0

    def record_close(handle):
        closed.append(handle)
        return original_close(handle)

    monkeypatch.setattr(runner._api, "CreateProcessW", create_then_fail)
    monkeypatch.setattr(runner._api, "CloseHandle", record_close)
    monkeypatch.setattr(runner._api, "ResumeThread", lambda *args: pytest.fail("partial-created child resumed"))
    result = run(runner, tmp_path, "import time; time.sleep(60)")
    assert result.status == "launch_error" and result.cleanup_complete and result.pid
    assert_gone(result.pid)
    assert all(handle in closed for handle in created)
    assert "sensitive" not in repr(result)


def test_unconfirmed_job_cleanup_is_not_success(runner, tmp_path, monkeypatch):
    query = runner._api.QueryInformationJobObject
    monkeypatch.setattr(runner._api, "QueryInformationJobObject", lambda *args: 0)
    result = run(runner, tmp_path, "pass", cleanup_timeout_seconds=.05)
    try:
        assert result.status == "cleanup_incomplete" and not result.cleanup_complete
        assert result.pending_owner is not None
        assert_gone(result.pid)
    finally:
        monkeypatch.setattr(runner._api, "QueryInformationJobObject", query)
        cleanup = result.pending_owner.retry_reap(deadline=time.monotonic() + 3)
        assert cleanup.tree_exited and cleanup.handles_closed


@pytest.mark.parametrize("size,status", [(1024, "completed"), (1025, "output_limit")])
def test_exact_raw_byte_boundary(runner, tmp_path, size, status):
    result = run(runner, tmp_path, f"import os; os.write(1,b'\\xe4\\xb8\\xad'*{size})", stdout_limit=3072)
    assert result.status == status and len(result.stdout) == 3072
    assert result.cleanup_complete


def test_supervisor_crash_kill_on_close(runner, tmp_path):
    handshake = tmp_path / "owned-pids.json"
    child = f"import os,json,time; from pathlib import Path; Path({str(handshake)!r}).write_text(json.dumps([os.getppid(),os.getpid()])); time.sleep(60)"
    supervisor_code = f"import sys; from pathlib import Path; sys.path.insert(0,{str(MODULE.parents[4])!r}); from scripts.local_probe_process import run_bounded; run_bounded(Path(sys.executable),['-I','-u','-c',{child!r}],cwd=Path({str(tmp_path)!r}),environment={environment()!r},timeout_seconds=30)"
    # The Windows venv executable is a redirector; crash the actual supervisor,
    # not an intermediate launcher that does not own the Job handle.
    supervisor = subprocess.Popen([sys._base_executable, "-I", "-c", supervisor_code], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW, env=environment())
    child_handle = None
    try:
        deadline = time.monotonic() + 5
        pids = None
        while time.monotonic() < deadline:
            if handshake.exists():
                try:
                    pids = json.loads(handshake.read_text())
                    break
                except json.JSONDecodeError:
                    pass
            assert supervisor.poll() is None, "supervisor exited before handshake"
            time.sleep(.01)
        assert pids and pids[0] == supervisor.pid
        child_handle = win32api.OpenProcess(0x00100001, False, pids[1])
        supervisor.kill()
        supervisor.wait(timeout=3)
        assert win32event.WaitForSingleObject(child_handle, 3000) == 0
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
        supervisor.wait(timeout=3)
        if child_handle is not None:
            if win32event.WaitForSingleObject(child_handle, 0) != 0:
                win32api.TerminateProcess(child_handle, 99)
                win32event.WaitForSingleObject(child_handle, 3000)
            child_handle.Close()

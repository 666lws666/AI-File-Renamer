"""Bounded Windows trusted child lifetime; NOT a privacy/network sandbox.

Callers must separately validate executable/DLL/model identities and resource
budgets. Used by fixed product workers and trusted local diagnostics.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass, field
import math
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Mapping, Sequence

from src.services.local_ai.native.security import AppContainerSecurity, SecurityContextError, TokenEvidence


@dataclass(frozen=True)
class ProcessResult:
    status: str
    exit_code: int | None
    stdout: bytes = field(repr=False)
    stderr: bytes = field(repr=False)
    pid: int | None
    cleanup_complete: bool
    elapsed_seconds: float
    win32_error: int | None = None
    error_stage: str | None = None
    token_evidence: TokenEvidence | None = None
    pending_owner: PendingProcessOwner | None = field(default=None, repr=False)
    stop_reason: str | None = None


@dataclass(frozen=True)
class ProcessCleanupResult:
    tree_exited: bool
    handles_closed: bool
    win32_error: int | None = None
    error_stage: str | None = None


class ProcessOwnershipInterrupted(BaseException):
    """An interrupted unwind still owns native resources; retry via pending_owner."""

    def __init__(self, pending_owner: PendingProcessOwner, original_category: str):
        super().__init__("process cleanup interrupted with pending ownership")
        self.pending_owner = pending_owner  # BaseException repr includes only args.
        self.original_category = original_category


def _interruption_category(exc):
    if isinstance(exc, KeyboardInterrupt):
        return "keyboard_interrupt"
    if isinstance(exc, SystemExit):
        return "system_exit"
    if isinstance(exc, GeneratorExit):
        return "generator_exit"
    return "base_exception"


class _SecurityAttributes(C.Structure):
    _fields_ = [("nLength", W.DWORD), ("lpSecurityDescriptor", C.c_void_p), ("bInheritHandle", W.BOOL)]


class _StartupInfo(C.Structure):
    _fields_ = [
        ("cb", W.DWORD), ("lpReserved", W.LPWSTR), ("lpDesktop", W.LPWSTR), ("lpTitle", W.LPWSTR),
        ("dwX", W.DWORD), ("dwY", W.DWORD), ("dwXSize", W.DWORD), ("dwYSize", W.DWORD),
        ("dwXCountChars", W.DWORD), ("dwYCountChars", W.DWORD), ("dwFillAttribute", W.DWORD),
        ("dwFlags", W.DWORD), ("wShowWindow", W.WORD), ("cbReserved2", W.WORD),
        ("lpReserved2", C.POINTER(W.BYTE)), ("hStdInput", W.HANDLE),
        ("hStdOutput", W.HANDLE), ("hStdError", W.HANDLE),
    ]


class _StartupInfoEx(C.Structure):
    _fields_ = [("StartupInfo", _StartupInfo), ("lpAttributeList", C.c_void_p)]


class _ProcessInformation(C.Structure):
    _fields_ = [("hProcess", W.HANDLE), ("hThread", W.HANDLE), ("dwProcessId", W.DWORD), ("dwThreadId", W.DWORD)]


class _BasicLimit(C.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", C.c_int64), ("PerJobUserTimeLimit", C.c_int64),
        ("LimitFlags", W.DWORD), ("MinimumWorkingSetSize", C.c_size_t),
        ("MaximumWorkingSetSize", C.c_size_t), ("ActiveProcessLimit", W.DWORD),
        ("Affinity", C.c_size_t), ("PriorityClass", W.DWORD), ("SchedulingClass", W.DWORD),
    ]


class _IoCounters(C.Structure):
    _fields_ = [(name, C.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _ExtendedLimit(C.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimit), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", C.c_size_t), ("JobMemoryLimit", C.c_size_t),
                ("PeakProcessMemoryUsed", C.c_size_t), ("PeakJobMemoryUsed", C.c_size_t)]


class _Accounting(C.Structure):
    _fields_ = [("TotalUserTime", C.c_int64), ("TotalKernelTime", C.c_int64),
                ("ThisPeriodTotalUserTime", C.c_int64), ("ThisPeriodTotalKernelTime", C.c_int64),
                ("TotalPageFaultCount", W.DWORD), ("TotalProcesses", W.DWORD),
                ("ActiveProcesses", W.DWORD), ("TotalTerminatedProcesses", W.DWORD)]


class _Bindings:
    """Typed binding boundary; individual calls can be fault-injected privately."""

    def __init__(self):
        kernel = C.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": (W.HANDLE, [C.c_void_p, W.LPCWSTR]),
            "SetInformationJobObject": (W.BOOL, [W.HANDLE, C.c_int, C.c_void_p, W.DWORD]),
            "QueryInformationJobObject": (W.BOOL, [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]),
            "TerminateJobObject": (W.BOOL, [W.HANDLE, W.UINT]),
            "CreatePipe": (W.BOOL, [C.POINTER(W.HANDLE), C.POINTER(W.HANDLE), C.POINTER(_SecurityAttributes), W.DWORD]),
            "SetHandleInformation": (W.BOOL, [W.HANDLE, W.DWORD, W.DWORD]),
            "CloseHandle": (W.BOOL, [W.HANDLE]),
            "InitializeProcThreadAttributeList": (W.BOOL, [C.c_void_p, W.DWORD, W.DWORD, C.POINTER(C.c_size_t)]),
            "UpdateProcThreadAttribute": (W.BOOL, [C.c_void_p, W.DWORD, C.c_size_t, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p]),
            "DeleteProcThreadAttributeList": (None, [C.c_void_p]),
            "CreateProcessW": (W.BOOL, [W.LPCWSTR, W.LPWSTR, C.c_void_p, C.c_void_p, W.BOOL, W.DWORD, C.c_void_p, W.LPCWSTR, C.POINTER(_StartupInfoEx), C.POINTER(_ProcessInformation)]),
            "IsProcessInJob": (W.BOOL, [W.HANDLE, W.HANDLE, C.POINTER(W.BOOL)]),
            "ResumeThread": (W.DWORD, [W.HANDLE]),
            "TerminateProcess": (W.BOOL, [W.HANDLE, W.UINT]),
            "WaitForSingleObject": (W.DWORD, [W.HANDLE, W.DWORD]),
            "GetExitCodeProcess": (W.BOOL, [W.HANDLE, C.POINTER(W.DWORD)]),
            "PeekNamedPipe": (W.BOOL, [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.POINTER(W.DWORD), C.POINTER(W.DWORD)]),
            "ReadFile": (W.BOOL, [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]),
        }
        for name, (restype, argtypes) in signatures.items():
            function = getattr(kernel, name)
            function.restype, function.argtypes = restype, argtypes
            setattr(self, name, function)


_api = _Bindings() if sys.platform == "win32" else None
_CHUNK = 16384
_BROKEN_PIPE = 109
_HANDLE_LIST = 0x00020002
_JOB_LIST = 0x0002000D
_SECURITY_CAPABILITIES = 0x00020009
_FLAGS = 0x4 | 0x08000000 | 0x00080000 | 0x00000400


class _WinFailure(Exception):
    def __init__(self, stage: str, code: int | None = None):
        self.stage = stage
        self.code = int(C.get_last_error() if code is None else code)


def _check(value, stage):
    if not value:
        raise _WinFailure(stage)
    return value


def _validated(executable, arguments, cwd, environment, timeout, limits, cleanup):
    for path, kind in ((executable, "executable"), (cwd, "cwd")):
        if not isinstance(path, Path) or "\0" in str(path) or not path.is_absolute():
            raise ValueError(f"invalid {kind}")
        if not (path.is_file() if kind == "executable" else path.is_dir()):
            raise ValueError(f"missing {kind}")
    for duration in (timeout, cleanup):
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
            raise ValueError("invalid deadline")
    if cleanup > 10:
        raise ValueError("cleanup deadline exceeds bound")
    for limit, maximum in zip(limits, (17 * 1024 * 1024, 16 * 1024 * 1024), strict=True):
        if type(limit) is not int or not 0 < limit <= maximum:
            raise ValueError("invalid output bound")
    if isinstance(arguments, (str, bytes)):
        raise TypeError("arguments must be a sequence of strings")
    argv = list(arguments)
    if any(not isinstance(arg, str) or "\0" in arg for arg in argv):
        raise ValueError("invalid argument")
    items = list(environment.items())
    if any(not isinstance(k, str) or not k or "=" in k or "\0" in k or not isinstance(v, str) or "\0" in v for k, v in items):
        raise ValueError("invalid environment")
    if len({k.upper() for k, _ in items}) != len(items):
        raise ValueError("duplicate environment key")
    command = subprocess.list2cmdline([str(executable), *argv])
    block = "\0".join(f"{k}={v}" for k, v in sorted(items, key=lambda pair: pair[0].upper())) + "\0\0"
    # Conversion failures and command length are rejected before resource creation.
    if len(command.encode("utf-16-le")) // 2 >= 32767:
        raise ValueError("command line exceeds Windows limit")
    block.encode("utf-16-le")
    return C.create_unicode_buffer(command), C.create_unicode_buffer(block)


def _read_chunk(handle, output, limit):
    available = W.DWORD()
    if not _api.PeekNamedPipe(handle, None, 0, None, C.byref(available), None):
        if C.get_last_error() == _BROKEN_PIPE:
            return False, False
        raise _WinFailure("peek")
    if not available.value:
        return False, False
    # Read one extra byte to distinguish an exact cap from overflow, never store it.
    amount = min(available.value, _CHUNK, limit - len(output) + 1)
    buffer = C.create_string_buffer(amount)
    read = W.DWORD()
    _check(_api.ReadFile(handle, buffer, amount, C.byref(read), None), "read")
    remaining = limit - len(output)
    output.extend(buffer.raw[:min(read.value, remaining)])
    return bool(read.value), read.value > remaining


def _is_exited(process):
    result = _api.WaitForSingleObject(process, 0)
    if result == 0xFFFFFFFF:
        raise _WinFailure("wait")
    return result == 0


def _reap(job, process, deadline):
    """Terminate only owned handles, then independently confirm root and job empty."""
    if job:
        _api.TerminateJobObject(job, 1)
    if process:
        _api.TerminateProcess(process, 1)  # also covers failed membership confirmation
    while True:
        accounting = _Accounting()
        job_empty = not job or bool(_api.QueryInformationJobObject(job, 1, C.byref(accounting), C.sizeof(accounting), None) and accounting.ActiveProcesses == 0)
        root_dead = not process or _api.WaitForSingleObject(process, 0) == 0
        if root_dead and job_empty:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(min(.005, max(0, deadline - time.monotonic())))


class PendingProcessOwner:
    """Retain exact acquired handles until exit and successful closes are proven.

    There is no destructor, PID adoption, reader or background reaper. The caller
    must keep this owner and explicitly retry when cleanup remains incomplete.
    """

    def __init__(self):
        self._handles = []
        self._job = None
        self._process = None
        self._tree_exited = False
        self._error = None
        self._stage = None
        self._lock = threading.Lock()
        self._result = ProcessCleanupResult(False, False)

    def _adopt(self, handle, *, role=None):
        if handle:
            self._handles.append(handle)
            if role == "job":
                self._job = handle
            elif role == "process":
                self._process = handle
        return handle

    def _close(self, handle):
        _check(_api.CloseHandle(handle), "handle_close")
        self._handles.remove(handle)

    def _record_error(self, exc, stage="cleanup"):
        self._error, self._stage = (exc.code, exc.stage) if isinstance(exc, _WinFailure) else (None, stage)

    def _confirm_exit(self, deadline):
        if not self._tree_exited:
            self._tree_exited = _reap(self._job, self._process, deadline)
            if not self._tree_exited:
                self._error, self._stage = None, "cleanup_unconfirmed"

    def _close_remaining(self, deadline):
        if not self._tree_exited:
            return
        for handle in reversed(tuple(self._handles)):
            if time.monotonic() >= deadline:
                self._error, self._stage = None, "cleanup_deadline"
                break
            try:
                self._close(handle)
            except Exception as exc:
                self._record_error(exc, "handle_close")

    def _publish(self):
        complete = self._tree_exited and not self._handles
        self._result = ProcessCleanupResult(self._tree_exited, not self._handles,
                                            None if complete else self._error,
                                            None if complete else self._stage)
        return self._result

    def retry_reap(self, *, deadline: float) -> ProcessCleanupResult:
        """Retry only owned cleanup within a finite monotonic absolute budget."""
        try:
            valid = type(deadline) in (int, float) and math.isfinite(deadline)
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("invalid cleanup deadline")
        # Lock waiting is part of the caller's budget, not an unbounded wait.
        remaining = max(0, deadline - time.monotonic())
        try:
            acquired = self._lock.acquire(timeout=min(remaining, threading.TIMEOUT_MAX))
        except BaseException as exc:
            if self._result.tree_exited and self._result.handles_closed:
                raise
            raise ProcessOwnershipInterrupted(self, _interruption_category(exc)) from None
        if not acquired:
            return self._result
        try:
            if self._result.tree_exited and self._result.handles_closed:
                return self._result
            if time.monotonic() >= deadline:
                self._error, self._stage = None, "cleanup_deadline"
                return self._publish()
            self._error = self._stage = None
            try:
                self._confirm_exit(deadline)
                self._close_remaining(deadline)
            except BaseException as exc:
                self._record_error(exc)
                result = self._publish()
                if not isinstance(exc, Exception):
                    if result.tree_exited and result.handles_closed:
                        raise
                    raise ProcessOwnershipInterrupted(self, _interruption_category(exc)) from None
            return self._publish()
        finally:
            self._lock.release()


def run_bounded(executable: Path, arguments: Sequence[str], *, cwd: Path,
                environment: Mapping[str, str], timeout_seconds: float,
                cancellation_event: threading.Event | None = None,
                stdout_limit: int = 262144, stderr_limit: int = 1048576,
                cleanup_timeout_seconds: float = 3.0,
                security_context: AppContainerSecurity | None = None) -> ProcessResult:
    """Capture bounded raw output and reap a creation-time-job-bound process tree.

    A completed lifecycle may have a nonzero exit code. Arguments, environment,
    captured bytes and exception text are never logged. Job membership does not
    deny network or filesystem access. Unsupported JOB_LIST fails closed.
    Optional security must be a caller-owned active exact AppContainerSecurity;
    retain its lifetime through this call. Token evidence does not itself prove
    network denial, runtime compatibility, or successful lifecycle completion.
    """
    started = time.monotonic()
    capabilities = None
    if security_context is not None:
        if type(security_context) is not AppContainerSecurity:
            raise SecurityContextError("security_context", 87)
        capabilities = security_context.capabilities  # validate before resources
    command, env_block = _validated(executable, arguments, cwd, environment,
                                    timeout_seconds, (stdout_limit, stderr_limit), cleanup_timeout_seconds)
    if _api is None:
        raise OSError("Windows is required")
    if cancellation_event is not None and cancellation_event.is_set():
        return ProcessResult("cancelled", None, b"", b"", None, True,
                             time.monotonic() - started, stop_reason="cancelled")
    owner = PendingProcessOwner()
    job = None
    info = _ProcessInformation()
    attributes = None
    startup = None
    initialized = False
    stdout, stderr = bytearray(), bytearray()
    streams = []
    status, exit_code, error, stage = "launch_error", None, None, None
    cleanup_complete = False
    pending_exception = None
    token_evidence = None

    def pipe(parent_read):
        read, write = W.HANDLE(), W.HANDLE()
        security = _SecurityAttributes(C.sizeof(_SecurityAttributes), None, True)
        try:
            _check(_api.CreatePipe(C.byref(read), C.byref(write), C.byref(security), 0), "pipe")
        finally:
            owner._adopt(read.value)
            owner._adopt(write.value)
        _check(_api.SetHandleInformation(read.value if parent_read else write.value, 1, 0), "pipe_inheritance")
        return read.value, write.value

    def interrupted():
        if cancellation_event is not None and cancellation_event.is_set():
            return "cancelled"
        if time.monotonic() >= started + timeout_seconds:
            return "timeout"
        return None

    try:
        job = owner._adopt(_check(_api.CreateJobObjectW(None, None), "job_create"), role="job")
        limit = _ExtendedLimit()
        limit.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE, no breakaway
        _check(_api.SetInformationJobObject(job, 9, C.byref(limit), C.sizeof(limit)), "job_limits")
        stdin_read, stdin_write = pipe(False)
        stdout_read, stdout_write = pipe(True)
        stderr_read, stderr_write = pipe(True)
        owner._close(stdin_write)  # EOF is available from the first child instruction.
        streams = [(stdout_read, stdout, stdout_limit), (stderr_read, stderr, stderr_limit)]
        size = C.c_size_t()
        attribute_count = 3 if capabilities is not None else 2
        _api.InitializeProcThreadAttributeList(None, attribute_count, 0, C.byref(size))
        if not size.value:
            raise _WinFailure("attribute_size")
        attributes = C.create_string_buffer(size.value)
        _check(_api.InitializeProcThreadAttributeList(attributes, attribute_count, 0, C.byref(size)), "attribute_init")
        initialized = True
        # Retain both arrays until DeleteProcThreadAttributeList in finally.
        inherited_handles = (W.HANDLE * 3)(stdin_read, stdout_write, stderr_write)
        job_handles = (W.HANDLE * 1)(job)
        _check(_api.UpdateProcThreadAttribute(attributes, 0, _HANDLE_LIST, inherited_handles, C.sizeof(inherited_handles), None, None), "handle_list")
        _check(_api.UpdateProcThreadAttribute(attributes, 0, _JOB_LIST, job_handles, C.sizeof(job_handles), None, None), "job_list")
        if capabilities is not None:
            _check(_api.UpdateProcThreadAttribute(attributes, 0, _SECURITY_CAPABILITIES,
                   C.byref(capabilities), C.sizeof(capabilities), None, None), "security_capabilities")
        startup = _StartupInfoEx()
        startup.StartupInfo.cb = C.sizeof(startup)
        startup.StartupInfo.dwFlags = 0x100  # STARTF_USESTDHANDLES
        startup.StartupInfo.hStdInput = stdin_read
        startup.StartupInfo.hStdOutput = stdout_write
        startup.StartupInfo.hStdError = stderr_write
        startup.lpAttributeList = C.cast(attributes, C.c_void_p)
        status = interrupted() or "launch_error"
        if status not in ("cancelled", "timeout"):
            try:
                _check(_api.CreateProcessW(str(executable), command, None, None, True, _FLAGS, env_block, str(cwd), C.byref(startup), C.byref(info)), "create")
            finally:
                # Even a partial binding failure must adopt returned handles
                # before the outer termination/reap/close path takes ownership.
                if info.hProcess:
                    owner._adopt(info.hProcess, role="process")
                if info.hThread:
                    owner._adopt(info.hThread)
            for handle in (stdin_read, stdout_write, stderr_write):
                owner._close(handle)
            member = W.BOOL()
            _check(_api.IsProcessInJob(info.hProcess, job, C.byref(member)), "membership")
            if not member.value:
                raise _WinFailure("membership", 87)
            if security_context is not None:
                # Call the canonical implementation, never an instance-supplied
                # verifier callback. Child is still suspended and job-confirmed.
                token_evidence = AppContainerSecurity.verify_process(security_context, info.hProcess)
            status = interrupted() or "launch_error"
            if status not in ("cancelled", "timeout"):
                if _api.ResumeThread(info.hThread) == 0xFFFFFFFF:
                    raise _WinFailure("resume")
                owner._close(info.hThread)
                status = "completed"
                while True:
                    reason = interrupted()
                    if reason:
                        status = reason
                        break
                    # One bounded chunk per stream per turn; no reader threads.
                    progress = False
                    for handle, output, cap in streams:
                        reason = interrupted()
                        if reason:
                            status = reason
                            break
                        read, overflow = _read_chunk(handle, output, cap)
                        progress |= read
                        if overflow:
                            status = "output_limit"
                            break
                    if status != "completed":
                        break
                    if _is_exited(info.hProcess):
                        code = W.DWORD()
                        _check(_api.GetExitCodeProcess(info.hProcess, C.byref(code)), "exit_code")
                        exit_code = code.value
                        break
                    if not progress:
                        time.sleep(.005)
    except BaseException as exc:
        status = "launch_error"
        if isinstance(exc, _WinFailure):
            error, stage = exc.code, exc.stage
        elif isinstance(exc, SecurityContextError):
            error, stage = exc.win32_error, exc.stage
        else:
            stage = "internal"
            if not isinstance(exc, Exception):
                pending_exception = exc
    finally:
        stop_reason = status
        cleanup_deadline = time.monotonic() + cleanup_timeout_seconds
        # Metadata is no longer needed after launch use, even if process cleanup
        # remains pending. Detach the pointer and delete it only once.
        try:
            if initialized:
                initialized = False
                try:
                    _api.DeleteProcThreadAttributeList(attributes)
                finally:
                    if startup is not None:
                        startup.lpAttributeList = None
                    attributes = None
        except BaseException as exc:
            stage = "attribute_delete"
            status = "launch_error"
            if not isinstance(exc, Exception) and pending_exception is None:
                pending_exception = exc
        try:
            owner._confirm_exit(cleanup_deadline)
            if owner._tree_exited and info.hProcess:
                if exit_code is None:
                    code = W.DWORD()
                    if _api.GetExitCodeProcess(info.hProcess, C.byref(code)):
                        exit_code = code.value
                # All writers in the owned tree are dead: only finite buffered data.
                while time.monotonic() < cleanup_deadline:
                    progress = False
                    for handle, output, cap in streams:
                        read, overflow = _read_chunk(handle, output, cap)
                        progress |= read
                        if overflow and status == "completed":
                            status = stop_reason = "output_limit"
                    if not progress or status == "output_limit":
                        break
        except BaseException as exc:
            if isinstance(exc, _WinFailure):
                error, stage = exc.code, exc.stage
            else:
                stage = "cleanup"
            status = "launch_error"
            owner._record_error(exc)
            if not isinstance(exc, Exception) and pending_exception is None:
                pending_exception = exc
        finally:
            try:
                owner._close_remaining(cleanup_deadline)
            except BaseException as exc:
                owner._record_error(exc, "handle_close")
                if not isinstance(exc, Exception) and pending_exception is None:
                    pending_exception = exc
            cleanup = owner._publish()
            cleanup_complete = cleanup.tree_exited and cleanup.handles_closed
        if not cleanup_complete:
            status = "cleanup_incomplete"
            error, stage = cleanup.win32_error, cleanup.error_stage
    if pending_exception is not None:
        if not cleanup_complete:
            raise ProcessOwnershipInterrupted(owner, _interruption_category(pending_exception)) from None
        raise pending_exception
    return ProcessResult(status, exit_code, bytes(stdout), bytes(stderr),
                         info.dwProcessId or None, cleanup_complete,
                         time.monotonic() - started, error, stage, token_evidence,
                         None if cleanup_complete else owner, stop_reason)

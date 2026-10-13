"""Single-owner, hard-cancellable preparation using the existing Windows Job runner.

The Job bounds lifetime, not network/filesystem authority. No parser is imported
or called in the parent. Uncertain native ownership permanently blocks admission
until that exact owner's explicit bounded cleanup succeeds.
"""
from __future__ import annotations

import ctypes
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

from .native.process import ProcessOwnershipInterrupted, run_bounded
from .preparation_protocol import (
    LocalPreparationLimits, PreparationError, PreparationRequest,
    decode_result, encode_request,
)

_APP_ROOT = Path(__file__).resolve().parents[3]
_BOOTSTRAP = "import sys;sys.path.insert(0,sys.argv[1]);from src.services.local_ai.preparation_worker import main;raise SystemExit(main(sys.argv[2:]))"


def _environment():
    """Only trusted OS/interpreter search paths and the normal local OS temp."""
    if sys.platform != "win32":
        raise PreparationError("worker_failed")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetWindowsDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    kernel.GetWindowsDirectoryW.restype = ctypes.c_uint
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel.GetWindowsDirectoryW(buffer, len(buffer))
    if not 0 < length < len(buffer):
        raise PreparationError("worker_failed")
    windows = Path(buffer.value)
    interpreter = Path(sys.executable).resolve()
    runtime = Path(sys.base_prefix).resolve()
    temp = Path(tempfile.gettempdir()).resolve()
    # No inherited PATH/PYTHONPATH/proxy/token/cache/model settings.
    return {"SystemRoot": str(windows), "WINDIR": str(windows),
            "TEMP": str(temp), "TMP": str(temp),
            "PATH": os.pathsep.join(map(str, (interpreter.parent, runtime, runtime / "DLLs", windows / "System32", windows)))}


def _deadline(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise PreparationError("invalid_request")
    return value


class _Cancellation:
    def __init__(self, predicate, closed):
        self.predicate = predicate
        self.closed = closed
        self.latched = False

    def is_set(self):
        if self.latched or self.closed.is_set():
            self.latched = True
            return True
        try:
            self.latched = bool(self.predicate())
        except BaseException:
            # Never allow a faulty callback to escape a native-owned lifetime.
            self.latched = True
        return self.latched


class BoundedLocalPreparationService:
    """prepare shares admission deadline with later inference (queue included).

    `_runner` is a trusted construction-only dependency seam. Public prepare has
    no executable, environment, flags, arbitrary callbacks-in-child or imports.
    """

    def __init__(self, *, _runner=run_bounded):
        self._runner = _runner
        self._slot = threading.Lock()
        self._closed = threading.Event()
        self._pending_owner = None
        self._ownership_uncertain = False

    def prepare(self, source_path, *, limits: LocalPreparationLimits,
                quality_mode: str, deadline: float, cancelled):
        deadline = _deadline(deadline)
        if not callable(cancelled) or type(limits) is not LocalPreparationLimits:
            raise PreparationError("invalid_request")
        request = PreparationRequest(str(source_path), limits, quality_mode)
        encoded = encode_request(request)
        own_deadline = min(deadline, time.monotonic()+limits.timeout_seconds)
        cancel = _Cancellation(cancelled, self._closed)

        def checkpoint():
            if self._closed.is_set():
                raise PreparationError("closed")
            if cancel.is_set():
                raise PreparationError("cancelled")
            if time.monotonic() >= own_deadline:
                raise PreparationError("timeout")

        acquired = False
        try:
            while not acquired:
                checkpoint()
                acquired = self._slot.acquire(timeout=min(.025, max(0, own_deadline-time.monotonic())))
            checkpoint()
            if self._pending_owner is not None or self._ownership_uncertain:
                raise PreparationError("cleanup_incomplete")
            executable = Path(sys.executable).resolve(strict=True)
            if getattr(sys, "frozen", False):
                arguments = ("--local-preparation-worker-v1", encoded)
            else:
                arguments = ("-I", "-c", _BOOTSTRAP, str(_APP_ROOT), encoded)
            environment = _environment()
            checkpoint()
            remaining = own_deadline - time.monotonic()
            if remaining < .05:
                raise PreparationError("timeout")
            cleanup_budget = min(3.0, remaining / 4)
            try:
                native = self._runner(executable, arguments, cwd=_APP_ROOT,
                    environment=environment, timeout_seconds=remaining-cleanup_budget,
                    cancellation_event=cancel, stdout_limit=17*1024*1024,
                    stderr_limit=64*1024, cleanup_timeout_seconds=cleanup_budget)
            except ProcessOwnershipInterrupted as interruption:
                self._pending_owner = interruption.pending_owner
                raise PreparationError("cleanup_incomplete") from None
            except Exception:
                raise PreparationError("worker_failed") from None
            # Retain even an inconsistent result's owner; never trade certainty
            # for a cancelled/success label or silently start a second child.
            if native.pending_owner is not None:
                self._pending_owner = native.pending_owner
            if not native.cleanup_complete or self._pending_owner is not None:
                self._ownership_uncertain = self._pending_owner is None
                raise PreparationError("cleanup_incomplete")
            checkpoint()
            if native.status == "cancelled":
                raise PreparationError("cancelled")
            if native.status == "timeout":
                raise PreparationError("timeout")
            if native.status != "completed" or native.exit_code != 0:
                raise PreparationError("worker_failed")
            result = decode_result(native.stdout, limits=limits, quality_mode=quality_mode)
            checkpoint()  # Recheck currentness/deadline after all validation work.
            return result
        except (PreparationError, KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            raise PreparationError("worker_failed") from None
        finally:
            if acquired:
                self._slot.release()

    def retry_cleanup(self, deadline: float) -> bool:
        deadline = min(_deadline(deadline), time.monotonic()+3.0)
        if not self._slot.acquire(timeout=max(0, deadline-time.monotonic())):
            return False
        try:
            if self._pending_owner is None:
                return not self._ownership_uncertain
            owner = self._pending_owner
            try:
                result = owner.retry_reap(deadline=deadline)
            except ProcessOwnershipInterrupted:
                return False  # Keep the original exact owner.
            except Exception:
                return False
            if result.tree_exited and result.handles_closed:
                self._pending_owner = None
                self._ownership_uncertain = False
                return True
            return False
        finally:
            self._slot.release()

    def close(self, deadline: float) -> bool:
        deadline = _deadline(deadline)
        self._closed.set()
        return self.retry_cleanup(deadline)

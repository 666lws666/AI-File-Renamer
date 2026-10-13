"""Exact invocation ownership and ordered release, without inference policy."""
from __future__ import annotations

from dataclasses import dataclass
import math
import time

@dataclass(frozen=True, slots=True)
class InvocationCleanup:
    complete: bool
    error: str | None = None


class InvocationOwner:
    """A retained cursor: a failed dependency prevents every later release.

    Resource generator exits and durable journal failures are terminal because
    neither API promises a safely repeatable failed exit/write.
    """
    def __init__(self, *, _clock=time.monotonic):
        self.process = None
        self.child_cleanup_confirmed = True  # no runner entered yet
        self.security = None
        self.stage = None
        self.exemption = None
        self.profile = None
        self.resource_context = None
        self.journal = None
        self.run_id = None
        self.recovery_required = False
        self._clock = _clock

    def __repr__(self):
        return "InvocationOwner()"

    def cleanup(self, *, deadline: float) -> InvocationCleanup:
        # The process module binds Win32 functions at import.  Keeping this
        # dependency here makes service import/construction cloud-only cheap.
        from .native.process import ProcessCleanupResult, ProcessOwnershipInterrupted
        try:
            valid = type(deadline) in (int, float) and math.isfinite(deadline)
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("INVALID_DEADLINE")
        if self.recovery_required:
            return InvocationCleanup(False, "RECOVERY_REQUIRED")
        for name in ("process", "security", "stage", "exemption", "profile", "resource_context", "journal"):
            if self._clock() >= deadline:
                return InvocationCleanup(False, "CLEANUP_PENDING")
            obj = getattr(self, name)
            if name == "process" and obj is None and not self.child_cleanup_confirmed:
                self.recovery_required = True
                return InvocationCleanup(False, "RECOVERY_REQUIRED")
            if obj is None:
                continue
            try:
                if name == "process":
                    result = obj.retry_reap(deadline=deadline)
                    if (type(result) is not ProcessCleanupResult or result.tree_exited is not True
                            or result.handles_closed is not True):
                        return InvocationCleanup(False, "CLEANUP_PENDING")
                    self.child_cleanup_confirmed = True
                elif name == "stage":
                    if obj.cleanup(child_cleanup_confirmed=True).complete is not True:
                        return InvocationCleanup(False, "CLEANUP_PENDING")
                elif name == "resource_context":
                    obj.__exit__(None, None, None)
                elif name == "journal":
                    obj.complete(self.run_id)
                else:
                    obj.close()
            except ProcessOwnershipInterrupted as exc:
                self.process = exc.pending_owner
                raise
            except BaseException as exc:
                if name in ("resource_context", "journal"):
                    self.recovery_required = True
                if not isinstance(exc, Exception):
                    raise
                return InvocationCleanup(False, "RECOVERY_REQUIRED" if self.recovery_required else "CLEANUP_PENDING")
            setattr(self, name, None)
        return InvocationCleanup(True)

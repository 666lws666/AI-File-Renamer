"""Retain one asynchronous shutdown attempt for the exact runtime-owned service.

Polling never joins a native cleanup thread on Qt. CLOSED is necessary but not
sufficient: the actual thread must also return before this owner can drain.
"""
from __future__ import annotations

import math
from threading import Lock, Thread
import time


class RuntimeShutdownOwner:
    def __init__(self, service, *, attempt_seconds=30.0):
        if (type(attempt_seconds) not in (int, float)
                or not math.isfinite(attempt_seconds) or not 0 < attempt_seconds <= 30):
            raise ValueError('RUNTIME_SHUTDOWN_DEADLINE_ERROR')
        self.service = service
        self.attempt_seconds = attempt_seconds
        self._lock = Lock()
        self._worker = None
        self._result = None
        self._failure = None
        self._poll_deadline = None

    @property
    def worker(self):
        with self._lock: return self._worker

    @property
    def result(self):
        with self._lock: return self._result

    @property
    def failure(self):
        with self._lock: return self._failure

    def _run(self, deadline):
        try:
            result = self.service.shutdown(deadline=deadline)
        except BaseException as failure:
            with self._lock: self._failure = failure
        else:
            with self._lock: self._result = result

    def close(self, *, deadline):
        try:
            valid = type(deadline) in (int, float) and math.isfinite(deadline)
        except OverflowError: valid = False
        if not valid: raise ValueError('RUNTIME_SHUTDOWN_DEADLINE_ERROR')
        with self._lock:
            if self._worker is not None and self._worker.is_alive(): return False
            if (self._result is not None and self._result.phase == 'CLOSED'
                    and getattr(self._result, 'error', None) is None
                    and getattr(self._result, 'waiting_count', 0) == 0):
                return True
            if time.monotonic() >= deadline: return False
            # One finite caller poll admits at most one real attempt. An
            # incomplete native result is retryable under a later poll budget,
            # not an invitation to spin fresh threads within this same call.
            if self._poll_deadline == deadline: return False
            self._poll_deadline = deadline
            self._result, self._failure = None, None
            self._worker = Thread(target=self._run,
                args=(time.monotonic()+self.attempt_seconds,),
                name='local-runtime-shutdown', daemon=False)
            self._worker.start()
            return False

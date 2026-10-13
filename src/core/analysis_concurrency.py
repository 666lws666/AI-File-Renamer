"""Shared managed CLOUD analysis capacity; no threads, I/O or Qt."""
import math
from threading import Condition, Lock
import time

from src.core.processing_authority import ProcessingSuperseded


CLOUD_QUEUE_TIMEOUT_SECONDS = 600.0


class CloudLaneQueueFull(RuntimeError):
    pass


class CloudLaneQueueTimeout(RuntimeError):
    pass


class CloudAnalysisLane:
    def __init__(self, *, max_waiters=64, clock=None):
        if (type(max_waiters) is not int or not 1 <= max_waiters <= 1000
                or (clock is not None and not callable(clock))):
            raise ValueError('invalid_cloud_lane_configuration')
        self._condition = Condition(Lock())
        self._clock = clock if clock is not None else time.monotonic
        self._max_waiters = max_waiters
        self._tokens = {}
        self._waiting = 0

    def acquire(self, limit, *, cancelled, deadline):
        if (type(limit) is not int or not 1 <= limit <= 20
                or not callable(cancelled)
                or type(deadline) not in (int, float)
                or not math.isfinite(deadline)):
            raise ValueError('invalid_cloud_lane_acquisition')
        registered = False
        try:
            while True:
                try:
                    if cancelled() is not False:
                        raise ProcessingSuperseded()
                except BaseException:
                    raise ProcessingSuperseded() from None
                now = self._clock()
                if type(now) not in (int, float) or not math.isfinite(now):
                    raise ValueError('invalid_cloud_lane_clock')
                if now >= deadline:
                    raise CloudLaneQueueTimeout('cloud_queue_timeout')
                with self._condition:
                    ceiling = min((limit, *self._tokens.values()))
                    if len(self._tokens) < ceiling:
                        token = object()
                        self._tokens[token] = limit
                        return token
                    if not registered:
                        if self._waiting >= self._max_waiters:
                            raise CloudLaneQueueFull('cloud_queue_full')
                        self._waiting += 1
                        registered = True
                    self._condition.wait(min(.05, deadline-now))
        finally:
            if registered:
                with self._condition:
                    self._waiting -= 1
                    self._condition.notify_all()

    def release(self, token):
        if type(token) is not object:
            return False
        with self._condition:
            if token not in self._tokens:
                return False
            del self._tokens[token]
            self._condition.notify_all()
            return True

    @property
    def active_count(self):
        with self._condition:
            return len(self._tokens)

    @property
    def waiting_count(self):
        with self._condition:
            return self._waiting

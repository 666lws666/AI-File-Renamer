"""Real bounded cloud lane holders and waiters; no synthetic counters."""
import time
from dataclasses import FrozenInstanceError
from threading import Event, Thread

import pytest

from src.core.analysis_concurrency import (
    CloudAnalysisLane, CloudLaneQueueFull, CloudLaneQueueTimeout,
)
from src.core.processing_authority import ProcessingSuperseded
from src.core.processing_analysis import AnalysisSettings
from src.models.app_config import AppConfig


def until(predicate, timeout=2):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        Event().wait(.002)
    assert predicate(), "bounded thread state did not arrive"


class Acquisition:
    def __init__(self, lane, limit=1, cancelled=lambda: False, deadline=None):
        self.token = self.error = None
        self.done = Event()
        def run():
            try:
                self.token = lane.acquire(limit, cancelled=cancelled,
                    deadline=deadline or time.monotonic()+3)
            except BaseException as error:
                self.error = error
            finally:
                self.done.set()
        self.thread = Thread(target=run)
        self.thread.start()
        self.lane = lane

    def close(self):
        # Release known owners before joining, then release a late genuine token.
        if self.token is not None:
            self.lane.release(self.token)
        self.thread.join(4)
        assert not self.thread.is_alive()
        if self.token is not None:
            self.lane.release(self.token)


def acquire(lane, limit=1):
    return lane.acquire(limit, cancelled=lambda: False, deadline=time.monotonic()+3)


def test_exact_token_release_cannot_release_another_job():
    lane = CloudAnalysisLane()
    token = acquire(lane)
    try:
        assert lane.active_count == 1
        assert lane.release(object()) is False
        assert lane.release(None) is False
        assert lane.active_count == 1
        assert lane.release(token) is True
        assert lane.release(token) is False
        assert lane.active_count == 0
    finally:
        lane.release(token)


def test_captured_concurrency_remains_immutable():
    config = AppConfig(max_concurrent_requests=2)
    captured = AnalysisSettings.capture(config)
    config.max_concurrent_requests = 20
    assert captured.max_concurrent_requests == 2
    assert AnalysisSettings.capture(config).max_concurrent_requests == 20
    with pytest.raises(FrozenInstanceError):
        captured.max_concurrent_requests = 3


@pytest.mark.parametrize('bad', [True, False, 0, 21, 1.0, '2', None])
def test_invalid_limit_has_zero_ownership(bad):
    lane = CloudAnalysisLane()
    with pytest.raises(ValueError, match='invalid_cloud_lane_acquisition'):
        lane.acquire(bad, cancelled=lambda: False, deadline=time.monotonic()+2)
    assert lane.active_count == lane.waiting_count == 0


@pytest.mark.parametrize('bad', [True, False, 0, 21, 1.0, '2', None])
def test_capture_rejects_invalid_concurrency(bad):
    config = AppConfig()
    config.max_concurrent_requests = bad
    with pytest.raises(ValueError, match='Invalid analysis settings'):
        AnalysisSettings.capture(config)


def test_defaulted_field_retains_direct_constructor_compatibility():
    value = AnalysisSettings(4000, 10, 10, 2, 'balanced', 30, 0, True, True, True)
    assert value.max_concurrent_requests == 4


def test_second_real_thread_waits_until_exact_owner_release():
    lane = CloudAnalysisLane()
    first = acquire(lane)
    second = Acquisition(lane)
    try:
        until(lambda: lane.waiting_count == 1)
        assert lane.active_count == 1 and not second.done.is_set()
        releaser = Thread(target=lambda: lane.release(first))
        releaser.start(); releaser.join(2)
        assert not releaser.is_alive()
        assert second.done.wait(2) and second.error is None
        assert lane.active_count == 1 and lane.waiting_count == 0
    finally:
        lane.release(first); second.close()
    assert lane.active_count == lane.waiting_count == 0


@pytest.mark.parametrize('behavior', ['cancel', 'raises', 'non_false'])
def test_cancel_callback_retires_only_waiter(behavior):
    lane = CloudAnalysisLane()
    first = acquire(lane)
    stop = Event()
    def cancelled():
        if not stop.is_set():
            return False
        if behavior == 'raises':
            raise RuntimeError('private callback payload')
        return True if behavior == 'cancel' else 0
    second = Acquisition(lane, cancelled=cancelled)
    try:
        until(lambda: lane.waiting_count == 1)
        stop.set()
        assert second.done.wait(2)
        assert isinstance(second.error, ProcessingSuperseded)
        assert 'private' not in str(second.error)
        assert lane.active_count == 1 and lane.waiting_count == 0
    finally:
        lane.release(first); second.close()


def test_timeout_retires_waiter_not_real_owner():
    lane = CloudAnalysisLane()
    first = acquire(lane)
    second = Acquisition(lane, deadline=time.monotonic()+.15)
    try:
        until(lambda: lane.waiting_count == 1)
        assert second.done.wait(2)
        assert isinstance(second.error, CloudLaneQueueTimeout)
        assert lane.active_count == 1 and lane.waiting_count == 0
    finally:
        lane.release(first); second.close()


def test_waiter_cap_rejection_does_not_steal_first_waiter():
    lane = CloudAnalysisLane(max_waiters=1)
    first = acquire(lane)
    second = Acquisition(lane)
    try:
        until(lambda: lane.waiting_count == 1)
        with pytest.raises(CloudLaneQueueFull):
            acquire(lane)
        assert lane.waiting_count == lane.active_count == 1
        assert not second.done.is_set()
        lane.release(first)
        assert second.done.wait(2) and second.error is None
    finally:
        lane.release(first); second.close()


def test_callbacks_and_clock_run_outside_condition_lock():
    holder = {}
    def clock():
        if 'lane' in holder:
            assert holder['lane'].active_count >= 0
        return time.monotonic()
    lane = holder['lane'] = CloudAnalysisLane(clock=clock)
    first = acquire(lane)
    def cancelled():
        assert lane.active_count in (0, 1)
        lane.release(first)
        return False
    second = Acquisition(lane, cancelled=cancelled)
    try:
        assert second.done.wait(2) and second.error is None
        assert lane.active_count == 1
    finally:
        lane.release(first); second.close()


@pytest.mark.parametrize('older,newer', [(2, 1), (1, 20)])
def test_new_limit_cannot_weaken_real_older_holders(older, newer):
    lane = CloudAnalysisLane()
    tokens = [acquire(lane, older) for _ in range(older)]
    waiting = Acquisition(lane, newer)
    try:
        until(lambda: lane.waiting_count == 1)
        assert lane.active_count == older and not waiting.done.is_set()
        if older == 2:
            lane.release(tokens.pop())
            assert lane.active_count == 1 and lane.waiting_count == 1
            assert not waiting.done.is_set()
        lane.release(tokens.pop())
        assert waiting.done.wait(2) and waiting.error is None
        assert lane.active_count == 1
    finally:
        for token in tokens:
            lane.release(token)
        waiting.close()


def test_genuine_holder_peak_is_bounded():
    lane = CloudAnalysisLane()
    first, second = acquire(lane, 2), acquire(lane, 2)
    third = Acquisition(lane, 2)
    try:
        until(lambda: lane.waiting_count == 1)
        assert lane.active_count == 2 and not third.done.is_set()
        lane.release(first)
        assert third.done.wait(2) and third.error is None
        assert lane.active_count == 2
    finally:
        lane.release(first); lane.release(second); third.close()


@pytest.mark.parametrize('kwargs', [dict(max_waiters=True), dict(max_waiters=0),
    dict(max_waiters=1001), dict(clock=1)])
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError, match='invalid_cloud_lane_configuration'):
        CloudAnalysisLane(**kwargs)


@pytest.mark.parametrize('deadline', [True, None, float('nan'), float('inf'), '1'])
def test_invalid_deadline_has_no_ownership(deadline):
    lane = CloudAnalysisLane()
    with pytest.raises(ValueError, match='invalid_cloud_lane_acquisition'):
        lane.acquire(1, cancelled=lambda: False, deadline=deadline)
    assert lane.active_count == lane.waiting_count == 0


@pytest.mark.parametrize('now', [True, None, float('nan'), float('inf')])
def test_invalid_clock_has_no_ownership(now):
    lane = CloudAnalysisLane(clock=lambda: now)
    with pytest.raises(ValueError, match='invalid_cloud_lane_clock'):
        acquire(lane)
    assert lane.active_count == lane.waiting_count == 0

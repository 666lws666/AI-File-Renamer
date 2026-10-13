"""Actual asynchronous shutdown lifetime, independent of logical CLOSED."""
import importlib.util
import math
from threading import Event, get_ident
import time

import pytest

from src.services.local_ai.inference_service import LocalServiceSnapshot


def api():
    assert importlib.util.find_spec('src.services.local_ai.runtime_shutdown_owner') is not None
    from src.services.local_ai.runtime_shutdown_owner import RuntimeShutdownOwner
    return RuntimeShutdownOwner


class Service:
    def __init__(self):
        self.started, self.release = Event(), Event()
        self.release.set()
        self.calls = []
        self.phase = 'CLOSED'
        self.value = LocalServiceSnapshot('NOT_READY', None, None, 0)

    def snapshot(self): return self.value

    def shutdown(self, *, deadline):
        self.calls.append((get_ident(), deadline))
        self.started.set()
        assert self.release.wait(3)
        self.value = LocalServiceSnapshot(self.phase, None,
            None if self.phase == 'CLOSED' else self.phase, 0)
        return self.value


def wait(predicate):
    limit = time.monotonic()+2
    while not predicate() and time.monotonic() < limit: time.sleep(.001)
    assert predicate()


def test_inert_and_delayed_real_thread_does_not_block_or_duplicate_shutdown():
    service = Service(); service.release.clear()
    owner = api()(service)
    assert owner.service is service and owner.worker is None and not service.calls
    start = time.monotonic()
    try:
        assert not owner.close(deadline=start+.02)
        assert time.monotonic()-start < .1
        assert service.started.wait(1)
        worker = owner.worker
        for _ in range(5): assert not owner.close(deadline=time.monotonic()+.01)
        assert owner.worker is worker and len(service.calls) == 1
        assert service.calls[0][0] != get_ident()
        assert math.isfinite(service.calls[0][1])
    finally: service.release.set()
    wait(lambda: owner.close(deadline=time.monotonic()+.02))
    assert not worker.is_alive()


def test_cleanup_pending_is_retryable_but_not_closed():
    service = Service(); service.phase = 'CLEANUP_PENDING'
    owner = api()(service)
    assert not owner.close(deadline=time.monotonic()+.02)
    wait(lambda: owner.worker is not None and not owner.worker.is_alive())
    service.phase = 'CLOSED'
    wait(lambda: owner.close(deadline=time.monotonic()+.02))
    assert len(service.calls) >= 2


def test_one_poll_budget_cannot_spin_sequential_shutdown_attempts():
    service=Service();service.phase='CLEANUP_PENDING';owner=api()(service)
    deadline=time.monotonic()+2
    assert not owner.close(deadline=deadline)
    worker=owner.worker
    wait(lambda:not worker.is_alive())
    for _ in range(5):assert not owner.close(deadline=deadline)
    assert owner.worker is worker and len(service.calls)==1
    service.phase='CLOSED'
    wait(lambda:owner.close(deadline=time.monotonic()+.02))


def test_recovery_required_refuses_full_close_even_when_worker_finished():
    service = Service(); service.phase = 'RECOVERY_REQUIRED'
    owner = api()(service)
    assert not owner.close(deadline=time.monotonic()+.02)
    wait(lambda: owner.worker is not None and not owner.worker.is_alive())
    assert not owner.close(deadline=time.monotonic()+.02)
    wait(lambda: not owner.worker.is_alive())
    assert service.snapshot().phase == 'RECOVERY_REQUIRED'


def test_actual_completion_tail_retained_even_if_service_already_reports_closed():
    service = Service(); service.release.clear()
    owner = api()(service)
    assert not owner.close(deadline=time.monotonic()+.02)
    assert service.started.wait(1)
    service.value = LocalServiceSnapshot('CLOSED', None, None, 0)
    try: assert not owner.close(deadline=time.monotonic()+.02)
    finally: service.release.set()
    wait(lambda: owner.close(deadline=time.monotonic()+.02))


def test_completed_service_result_does_not_release_actual_shutdown_thread_tail():
    service=Service();entered,release=Event(),Event()
    class TailedOwner(api()):
        def _run(self,deadline):
            super()._run(deadline)
            entered.set();assert release.wait(3)
    owner=TailedOwner(service)
    assert not owner.close(deadline=time.monotonic()+.02)
    assert entered.wait(1) and owner.result.phase=='CLOSED'
    try:assert not owner.close(deadline=time.monotonic()+.02)
    finally:release.set()
    wait(lambda:owner.close(deadline=time.monotonic()+.02))


def test_shutdown_exception_is_retained_off_caller_thread_and_retryable():
    service=Service();owner=api()(service)
    def fail(*,deadline):raise RuntimeError('synthetic shutdown failure')
    service.shutdown=fail
    assert not owner.close(deadline=time.monotonic()+.02)
    wait(lambda:not owner.worker.is_alive())
    assert isinstance(owner.failure,RuntimeError) and owner.result is None
    service.shutdown=Service.shutdown.__get__(service)
    wait(lambda:owner.close(deadline=time.monotonic()+.02))


@pytest.mark.parametrize('error,waiting', [('RECOVERY_REQUIRED',0),(None,1)])
def test_closed_label_with_error_or_waiters_is_not_genuine_closed(error,waiting):
    service=Service()
    def inconsistent(*,deadline):
        return LocalServiceSnapshot('CLOSED',None,error,waiting)
    service.shutdown=inconsistent
    owner=api()(service)
    assert not owner.close(deadline=time.monotonic()+.02)
    wait(lambda:owner.worker is not None and not owner.worker.is_alive())
    assert not owner.close(deadline=time.monotonic()+.02)
    wait(lambda:not owner.worker.is_alive())


@pytest.mark.parametrize('deadline', [None, True, float('nan'), float('inf')])
def test_invalid_deadline_cannot_start_shutdown(deadline):
    service = Service(); owner = api()(service)
    with pytest.raises(ValueError, match='RUNTIME_SHUTDOWN_DEADLINE_ERROR'):
        owner.close(deadline=deadline)
    assert not service.calls and owner.worker is None

"""Real worker/Future ownership with public-resource-only fake boundaries."""
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
import importlib.util
from pathlib import Path
from threading import Event, get_ident
import time
from types import SimpleNamespace

import pytest

from src.core.processing_authority import ProcessingAuthority, ProcessingMode
from src.services.local_ai.production_resources import load_production_resources
from src.services.local_ai.resource_manager import ResourceSnapshot, ResourceState
from src.services.local_ai.inference_journal import InferenceRecoveryState
from src.services.local_ai.inference_service import LocalServiceSnapshot
from src.services.local_ai.resource_store import StoreOwnershipUncertain


def api():
    assert importlib.util.find_spec('src.services.local_ai.resource_operation_runner') is not None
    from src.services.local_ai import resource_operation_runner
    return resource_operation_runner


class Manager:
    def __init__(self, config):
        self.catalog, self.root = config.catalog, config.resource_root
        self.calls, self.threads = [], []
        self.started, self.release = Event(), Event()
        self.release.set()
        self.failure = None
        self.flood = 0
        self.value = ResourceSnapshot(ResourceState.AVAILABLE, config.catalog.identity,
            tuple(x.id for x in config.catalog.resources), None, config.catalog.total_bytes,
            config.catalog.total_bytes, None, config.catalog.total_bytes,
            config.catalog.total_bytes, 0)

    def snapshot(self):
        return self.value

    def call(self, name, **kwargs):
        self.calls.append(name)
        self.threads.append(get_ident())
        self.started.set()
        assert self.release.wait(5)
        if self.failure:
            raise self.failure
        cancelled = kwargs.get('cancelled', lambda: False)
        paused = kwargs.get('paused', lambda: False)
        if paused():
            self.value = replace(self.value, state=ResourceState.PAUSED, error_code='PAUSED')
        elif cancelled():
            self.value = replace(self.value, state=ResourceState.CANCELLED, error_code='CANCELLED')
        for count in range(self.flood):
            kwargs['progress']('model-q4', count, self.catalog.resources[1].bytes)
        return self.value

    def inspect(self, **kwargs): return self.call('inspect', **kwargs)
    def import_bundled_runtime(self, source, **kwargs): return self.call('bundle', **kwargs)
    def download(self, **kwargs): return self.call('download', **kwargs)
    def import_offline(self, source, **kwargs): return self.call('import', **kwargs)
    def repair_resource(self, resource_id): return self.call('repair')


class Journal:
    def __init__(self):
        self.calls = 0
        self.value = InferenceRecoveryState.MISSING
    def inspect_recovery_state(self):
        self.calls += 1
        return self.value


class Service:
    def __init__(self, config):
        self._config = SimpleNamespace(catalog=config.catalog, resource_root=config.resource_root,
            runtime_root=config.runtime_root, state_root=config.state_root)
        self.value = LocalServiceSnapshot('NOT_READY', None, None, 0)
        self.calls, self.deadlines, self.threads = [], [], []
        self.started, self.release = Event(), Event()
        self.release.set()
        self.ready = LocalServiceSnapshot('READY', 'a' * 64, None, 0)
    def snapshot(self): return self.value
    def check_ready(self, *, cancelled, deadline, is_current):
        self.calls.append('ready')
        self.deadlines.append(deadline)
        self.threads.append(get_ident())
        self.started.set()
        assert self.release.wait(5)
        self.value = (LocalServiceSnapshot('NOT_READY', None, 'CANCELLED', 0)
                      if cancelled() or not is_current() else self.ready)
        return self.value
    def retry_cleanup(self, *, deadline):
        self.calls.append('cleanup')
        self.value = LocalServiceSnapshot('NOT_READY', None, None, 0)
        return self.value


class Parents:
    def __init__(self):
        self.calls, self.active, self.failure = [], False, None
    @contextmanager
    def __call__(self, config, **kwargs):
        self.calls.append((get_ident(), kwargs))
        if self.failure:
            raise self.failure
        self.active = True
        try: yield self
        finally: self.active = False


def dependencies(tmp_path):
    config = load_production_resources(user_data_root=tmp_path / 'data')
    return config, Manager(config), Journal(), Service(config), Parents()


def request(module, authority, config, kind='prepare', **kwargs):
    snap = authority.snapshot()
    return module.ResourceOperationRequest.create(session_id=snap.session_id,
        generation=snap.generation, choice_revision=snap.revision,
        catalog_id=config.catalog.identity, kind=kind, **kwargs)


@pytest.fixture
def runner_setup(tmp_path):
    module = api()
    config, manager, journal, service, parents = dependencies(tmp_path)
    authority = ProcessingAuthority(initial_mode=ProcessingMode.LOCAL)
    delivered, notified = [], []
    runner = module.ResourceOperationRunner(config, manager, service, authority=authority,
        trusted_anchor=tmp_path, journal=journal, prepare_parents=parents,
        completion_callback=lambda req, result: delivered.append((req, result)),
        progress_callback=lambda: notified.append(True))
    yield module, config, manager, journal, service, parents, authority, runner, delivered, notified
    manager.release.set(); service.release.set()
    runner.begin_close()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        for req, result in list(delivered): runner.acknowledge(req, result)
        runner.take_progress()
        if runner.close(deadline=deadline): break
    assert runner.close(deadline=time.monotonic() + .1)


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.001)
    assert predicate()


def test_missing_runner_api_is_a_real_red():
    assert hasattr(api(), 'ResourceOperationRunner')


def test_inert_borrowing_and_immutable_records(runner_setup):
    m, config, manager, journal, service, parents, authority, runner, *_ = runner_setup
    assert runner.manager is manager and runner.service is service and runner.authority is authority
    assert runner.config is config
    assert manager.calls == [] and journal.calls == 0 and parents.calls == [] and service.calls == []
    assert runner.worker is None
    req = request(m, authority, config)
    with pytest.raises(FrozenInstanceError): req.generation = 99
    assert 'data' not in repr(req)


def test_prepare_offthread_holds_parent_through_real_selfcheck_and_ack(runner_setup):
    m, config, manager, journal, service, parents, authority, runner, delivered, _ = runner_setup
    service.release.clear()
    req = request(m, authority, config)
    assert runner.submit(req)
    assert service.started.wait(2) and parents.active
    assert not runner.close(deadline=time.monotonic() + .01)
    service.release.set()
    wait_for(lambda: len(delivered) == 1)
    assert not parents.active
    assert all(x != get_ident() for x in manager.threads + service.threads)
    assert time.monotonic() < service.deadlines[0] <= time.monotonic() + 900
    assert not runner.close(deadline=time.monotonic() + .01)
    runner.acknowledge(*delivered[0])
    assert runner.close(deadline=time.monotonic() + 1)


@pytest.mark.parametrize('consent', [False, None, 0, 1, 'true'])
def test_invalid_consent_has_zero_backend_calls(runner_setup, consent):
    m, config, manager, journal, service, parents, authority, runner, *_ = runner_setup
    assert not runner.submit(request(m, authority, config, 'download', consent=consent))
    assert manager.calls == [] and parents.calls == [] and service.calls == []


@pytest.mark.parametrize('field,value', [('catalog_id','b'*64),('session_id','foreign'),('generation',999)])
def test_foreign_provenance_is_refused(runner_setup, field, value):
    m, config, manager, journal, service, parents, authority, runner, *_ = runner_setup
    assert not runner.submit(replace(request(m, authority, config), **{field: value}))
    assert manager.calls == []


def test_only_latest_pending_and_single_progress_notification(runner_setup):
    m, config, manager, journal, service, parents, authority, runner, delivered, notified = runner_setup
    manager.release.clear(); manager.flood = 10000
    first = request(m, authority, config, 'download', consent=True)
    assert runner.submit(first) and manager.started.wait(2)
    middle = request(m, authority, config, 'inspect')
    latest = request(m, authority, config, 'inspect')
    assert runner.submit(middle) and runner.submit(latest)
    assert runner.pending is latest and middle.cancel_event.is_set()
    manager.release.set()
    wait_for(lambda: len(delivered) == 1)
    runner.acknowledge(*delivered[0])
    wait_for(lambda: len(delivered) == 2)
    assert [r for r, _ in delivered] == [first, latest]
    assert len(notified) == 1
    progress = runner.take_progress()
    assert progress.request is first
    assert progress.acquired_bytes == 0  # transfer callbacks are not durable bytes
    assert not runner.take_progress()


@pytest.mark.parametrize('state', [InferenceRecoveryState.MISSING, InferenceRecoveryState.CLEAN,
                                  InferenceRecoveryState.BUSY])
def test_busy_observation_delegates_to_same_service(runner_setup, state):
    m, config, manager, journal, service, parents, authority, runner, delivered, _ = runner_setup
    journal.value = state
    req = request(m, authority, config)
    assert runner.submit(req)
    wait_for(lambda: len(delivered) == 1)
    assert service.calls == ['ready']
    assert delivered[0][1].recovery_state is state


def test_dirty_journal_is_never_repaired_or_selfchecked(runner_setup):
    m, config, manager, journal, service, parents, authority, runner, delivered, _ = runner_setup
    journal.value = InferenceRecoveryState.RECOVERY_REQUIRED
    assert runner.submit(request(m, authority, config))
    wait_for(lambda: bool(delivered))
    assert delivered[0][1].error_code == 'RECOVERY_REQUIRED' and service.calls == []


def test_parent_entry_uncertainty_is_retained_after_future_completion(runner_setup):
    m, config, manager, journal, service, parents, authority, runner, delivered, _ = runner_setup
    native = SimpleNamespace(idle=False)
    parents.failure = StoreOwnershipUncertain(native)
    assert runner.submit(request(m, authority, config))
    wait_for(lambda: bool(delivered))
    runner.acknowledge(*delivered[0])
    assert delivered[0][1].error_code == 'NATIVE_OWNERSHIP_UNCERTAIN'
    assert not runner.close(deadline=time.monotonic() + .02)
    assert runner.retained_native_owners == (native,)
    native.idle = True
    assert runner.close(deadline=time.monotonic() + 1)


def test_future_and_completion_callback_tail_is_owned(runner_setup):
    m, config, manager, journal, service, parents, authority, runner, delivered, _ = runner_setup
    entered, release = Event(), Event()
    original = runner.completion_callback
    def callback(req, result):
        original(req, result); entered.set(); assert release.wait(5)
    runner.completion_callback = callback
    assert runner.submit(request(m, authority, config, 'inspect'))
    assert entered.wait(2)
    runner.acknowledge(*delivered[0])
    try:
        assert runner.active_future.done()
        assert not runner.close(deadline=time.monotonic() + .02)
    finally: release.set()
    assert runner.close(deadline=time.monotonic() + 1)


def test_cancel_callable_exception_fails_closed(runner_setup):
    m, config, manager, journal, service, parents, authority, runner, delivered, _ = runner_setup
    def broken(): raise RuntimeError('private path/key')
    req = request(m, authority, config, cancelled=broken)
    assert runner.submit(req)
    wait_for(lambda: bool(delivered))
    assert delivered[0][1].error_code == 'CALLBACK_FAILED'
    assert manager.calls == []


def test_download_sequence_and_invalid_repair(runner_setup):
    m, config, manager, journal, service, parents, authority, runner, delivered, _ = runner_setup
    assert not runner.submit(request(m, authority, config, 'repair', resource_id='../unknown'))
    assert runner.submit(request(m, authority, config, 'download', consent=True))
    wait_for(lambda: bool(delivered))
    assert manager.calls == ['bundle', 'download', 'inspect']
    assert service.calls == ['ready']


def test_stale_pending_is_not_recaptured(runner_setup):
    m, config, manager, journal, service, parents, authority, runner, delivered, _ = runner_setup
    manager.release.clear()
    assert runner.submit(request(m, authority, config, 'inspect'))
    assert manager.started.wait(2)
    pending = request(m, authority, config)
    assert runner.submit(pending)
    authority.select_local()
    manager.release.set()
    wait_for(lambda: len(delivered) == 1)
    runner.acknowledge(*delivered[0])
    wait_for(lambda: len(delivered) == 2)
    assert delivered[-1][1].error_code == 'STALE_CONTEXT' and service.calls == []


def test_current_service_native_cleanup_tail_prevents_runner_close(runner_setup):
    m, config, manager, journal, service, parents, authority, runner, delivered, _ = runner_setup
    service.ready = LocalServiceSnapshot('CLEANUP_PENDING',None,'CLEANUP_PENDING',0)
    assert runner.submit(request(m,authority,config))
    wait_for(lambda:bool(delivered))
    runner.acknowledge(*delivered[0])
    try: assert not runner.close(deadline=time.monotonic()+.01)
    finally: service.retry_cleanup(deadline=time.monotonic()+1)
    assert runner.close(deadline=time.monotonic()+1)


@pytest.mark.parametrize('change', ['catalog','manager','service','anchor','path'])
def test_wrong_composition_is_refused_without_backend_calls(tmp_path,change):
    module=api()
    config,manager,journal,service,parents=dependencies(tmp_path)
    anchor=tmp_path
    if change=='catalog': config=replace(config,catalog=replace(config.catalog,identity='b'*64))
    if change=='manager': manager.catalog=replace(config.catalog)
    if change=='service': service._config.catalog=replace(config.catalog)
    if change=='anchor': anchor=Path('relative')
    if change=='path': config=replace(config,resource_root=tmp_path/'foreign')
    with pytest.raises(ValueError,match='^INVALID_RESOURCE_COMPOSITION$'):
        module.ResourceOperationRunner(config,manager,service,
            authority=ProcessingAuthority(initial_mode=ProcessingMode.LOCAL), trusted_anchor=anchor,
            journal=journal,prepare_parents=parents,completion_callback=lambda *_:None,
            progress_callback=lambda:None)
    assert manager.calls==[] and service.calls==[] and journal.calls==0 and parents.calls==[]


def test_offline_import_uses_exact_borrowed_importer_without_download(runner_setup,tmp_path):
    m,config,manager,journal,service,parents,authority,runner,delivered,_=runner_setup
    assert runner.submit(request(m,authority,config,'import',source_directory=str(tmp_path)))
    wait_for(lambda:bool(delivered))
    assert manager.calls==['import','inspect'] and service.calls==['ready']


def test_foreign_busy_journal_is_enforced_by_same_borrowed_service(runner_setup):
    m,config,manager,journal,service,parents,authority,runner,delivered,_=runner_setup
    journal.value=InferenceRecoveryState.BUSY
    service.ready=LocalServiceSnapshot('RECOVERY_REQUIRED',None,'RECOVERY_REQUIRED',0)
    assert runner.submit(request(m,authority,config))
    wait_for(lambda:bool(delivered))
    assert service.calls==['ready'] and delivered[0][1].error_code=='RECOVERY_REQUIRED'
    service.value=LocalServiceSnapshot('NOT_READY',None,None,0)


def test_future_own_synchronous_done_callback_tail_is_retained(runner_setup):
    m,config,manager,journal,service,parents,authority,runner,delivered,_=runner_setup
    manager.release.clear()
    entered,release=Event(),Event()
    assert runner.submit(request(m,authority,config,'inspect'))
    assert manager.started.wait(2)
    future=runner.active_future
    def done(_): entered.set(); assert release.wait(5)
    future.add_done_callback(done)
    manager.release.set()
    assert entered.wait(2) and future.done()
    try: assert not runner.close(deadline=time.monotonic()+.01)
    finally: release.set()
    wait_for(lambda:bool(delivered))
    runner.acknowledge(*delivered[0])
    assert runner.close(deadline=time.monotonic()+1)


def test_progress_bytes_are_bounded_by_exact_fixed_resource(runner_setup):
    m,config,manager,journal,service,parents,authority,runner,delivered,_=runner_setup
    original=manager.import_bundled_runtime
    def corrupt(source,**kwargs):
        kwargs['progress']('model-q4',0,10**100)
        return original(source,**kwargs)
    manager.import_bundled_runtime=corrupt
    assert runner.submit(request(m,authority,config,'download',consent=True))
    wait_for(lambda:bool(delivered))
    assert delivered[0][1].error_code=='CALLBACK_FAILED' and service.calls==[]


@pytest.mark.parametrize('deadline',[True,float('inf'),float('nan'),10**1000])
def test_invalid_close_deadline_does_not_close_admission(runner_setup,deadline):
    m,config,manager,journal,service,parents,authority,runner,delivered,_=runner_setup
    with pytest.raises(ValueError,match='^RESOURCE_DRAIN_DEADLINE_ERROR$'):
        runner.close(deadline=deadline)
    assert runner.submit(request(m,authority,config,'inspect'))
    wait_for(lambda:bool(delivered))


def test_no_source_path_or_unknown_raw_error_enters_public_result(runner_setup,tmp_path):
    m,config,manager,journal,service,parents,authority,runner,delivered,_=runner_setup
    manager.failure=RuntimeError('private source path '+str(tmp_path))
    req=request(m,authority,config,'import',source_directory=str(tmp_path))
    assert runner.submit(req)
    wait_for(lambda:bool(delivered))
    result=delivered[0][1]
    assert result.error_code=='PREPARATION_FAILED' and str(tmp_path) not in repr(result)
    assert not any(name in req.__dataclass_fields__ for name in ('provider','profile','prompt','key','document'))


def test_raw_service_error_and_invalid_identity_do_not_enter_qt_result_record(runner_setup,tmp_path):
    m,config,manager,journal,service,parents,authority,runner,delivered,_=runner_setup
    service.ready=LocalServiceSnapshot('NOT_READY',str(tmp_path),'secret raw source path',0)
    assert runner.submit(request(m,authority,config))
    wait_for(lambda:bool(delivered))
    result=delivered[0][1]
    assert str(tmp_path) not in repr(result) and 'secret raw' not in repr(result)
    assert result.service.identity is None and result.service.error=='LOCAL_INFERENCE_FAILED'


def test_r1_owned_drain_separates_borrowed_cleanup_pending(runner_setup):
    m, config, manager, journal, service, parents, authority, runner, delivered, _ = runner_setup
    service.ready = LocalServiceSnapshot('CLEANUP_PENDING',None,'CLEANUP_PENDING',0)
    assert runner.submit(request(m,authority,config))
    wait_for(lambda:bool(delivered))
    runner.acknowledge(*delivered[0])
    try:
        assert runner.drain_owned_operations(deadline=time.monotonic()+1)
        assert not runner.close(deadline=time.monotonic()+.01)
        assert service.calls==['ready']
        assert not runner.submit(request(m,authority,config))
    finally: service.retry_cleanup(deadline=time.monotonic()+1)


def test_r1_owned_drain_retains_real_future_and_ack(runner_setup):
    m, config, manager, journal, service, parents, authority, runner, delivered, _ = runner_setup
    service.release.clear()
    entered, release=Event(),Event()
    assert runner.submit(request(m,authority,config)) and service.started.wait(2)
    future=runner.active_future
    def held(done):
        entered.set(); assert release.wait(5)
    future.add_done_callback(held)
    service.release.set(); assert entered.wait(2)
    try:
        assert future.done() and runner.pending_ack_count==1
        assert not runner.drain_owned_operations(deadline=time.monotonic()+.01)
    finally: release.set()
    wait_for(lambda:bool(delivered))
    assert not runner.drain_owned_operations(deadline=time.monotonic()+.01)
    runner.acknowledge(*delivered[0])
    assert runner.drain_owned_operations(deadline=time.monotonic()+1)


def test_r1_owned_drain_retains_ambiguous_native_owner(runner_setup):
    m, config, manager, journal, service, parents, authority, runner, delivered, _ = runner_setup
    native=SimpleNamespace(idle=False)
    parents.failure=StoreOwnershipUncertain(native)
    assert runner.submit(request(m,authority,config)); wait_for(lambda:bool(delivered))
    runner.acknowledge(*delivered[0])
    try: assert not runner.drain_owned_operations(deadline=time.monotonic()+.01)
    finally: native.idle=True
    assert runner.drain_owned_operations(deadline=time.monotonic()+1)


def test_r1_owned_drain_from_worker_callback_is_recursive_safe(runner_setup):
    m, config, manager, journal, service, parents, authority, runner, delivered, _ = runner_setup
    observed=[]
    original=runner.completion_callback
    def callback(req,result):
        original(req,result)
        observed.append(runner.drain_owned_operations(deadline=time.monotonic()+.01))
    runner.completion_callback=callback
    assert runner.submit(request(m,authority,config,'inspect'))
    wait_for(lambda:bool(observed))
    assert observed==[False]
    runner.acknowledge(*delivered[0])
    assert runner.drain_owned_operations(deadline=time.monotonic()+1)

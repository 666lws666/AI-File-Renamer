"""Qt actions authenticated against the actual shared processing coordinator."""
from dataclasses import replace
import importlib.util
from threading import Event, Thread, get_ident
import time

import pytest
from PySide6.QtWidgets import QApplication

from src.controllers.processing_coordinator import ProcessingCoordinator
from src.core.processing_authority import LocalReadiness, CloudDispatchBlocked
from src.core.processing_intent_store import ProcessingIntentStore
from src.services.local_ai.inference_service import LocalServiceSnapshot
from tests.unit.test_local_resource_operation_runner import dependencies


def api():
    assert importlib.util.find_spec('src.controllers.local_resources_controller') is not None
    from src.controllers.local_resources_controller import LocalResourcesController
    return LocalResourcesController


@pytest.fixture(scope='module')
def app(): return QApplication.instance() or QApplication([])


@pytest.fixture
def setup(tmp_path, app):
    controller_type = api()
    coordinator = ProcessingCoordinator(ProcessingIntentStore(tmp_path / 'intent.json'))
    config, manager, journal, service, parents = dependencies(tmp_path)
    controller = controller_type(coordinator, config, manager, service, trusted_anchor=tmp_path,
        journal=journal, prepare_parents=parents)
    yield app, coordinator, controller, manager, journal, service, parents
    manager.release.set(); service.release.set()
    if service.value.phase in ('CLEANUP_PENDING','RECOVERY_REQUIRED'):
        service.retry_cleanup(deadline=time.monotonic()+1)
    try: assert controller.close(deadline=time.monotonic()+2)
    finally: assert coordinator.drain_choice_writer(deadline=time.monotonic()+2)


def spin(app, predicate):
    deadline = time.monotonic()+2
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.001)
    assert predicate()


def local(app, coordinator):
    coordinator.selectLocal()
    spin(app, lambda: coordinator.pending_ack_count == 0)


def test_qt_api_properties_are_inert_readonly_and_exact_borrowing(setup):
    app, c, r, manager, journal, service, parents = setup
    assert r.coordinator is c and r.runner.service is service and r.runner.manager is manager
    for name in ('phase','resourceState','errorCode','operationId','busy','canPause',
        'verifiedBytes','acquiredBytes','remainingTransferBytes','totalBytes',
        'currentResourceId','resourceRoot','modelName','runtimeVersion','recoveryState',
        'canPrepare','canDownload','canImport','canRetryCleanup'):
        getattr(r, name)
        prop = r.metaObject().property(r.metaObject().indexOfProperty(name))
        assert prop.hasNotifySignal() and not prop.isWritable()
    assert manager.calls == [] and journal.calls == 0 and parents.calls == []
    assert r.runner.worker is None and r.phase == 'NOT_READY'
    assert not r.prepareExisting() and not r.downloadAndEnable(True)


def test_ready_comes_from_real_borrowed_selfcheck_and_generation_after_preparing(setup):
    app, c, r, manager, journal, service, parents = setup
    local(app, c)
    c.publish_local_state(c.snapshot.generation, LocalReadiness.READY, engine_fingerprint='b'*64)
    previous = c.snapshot.generation
    assert r.prepareExisting()
    assert c.snapshot.generation == previous+1
    spin(app, lambda: not r.busy)
    assert r.phase == 'READY' and c.localReadiness == 'ready'
    assert c.snapshot.engine_fingerprint == 'a'*64 and service.calls == ['ready']
    assert r.prepareExisting()
    spin(app, lambda: not r.busy)
    assert service.calls == ['ready','ready']


@pytest.mark.parametrize('consent',[False,None,0,1,'yes'])
def test_consent_and_resource_id_refusal_has_zero_backend_calls(setup, consent):
    app, c, r, manager, journal, service, parents = setup
    local(app,c)
    assert not r.downloadAndEnable(consent) and not r.repairResource('../unknown')
    assert manager.calls == [] and parents.calls == [] and service.calls == []


@pytest.mark.parametrize('method', ['cancel','pause'])
def test_cancel_pause_stays_local_with_truthful_terminal_snapshot(setup, method):
    app, c, r, manager, journal, service, parents = setup
    local(app,c); manager.release.clear()
    assert r.downloadAndEnable(True) and manager.started.wait(2)
    assert getattr(r, method)()
    assert r.busy and c.processingMode == 'local'
    manager.release.set()
    spin(app, lambda: not r.busy)
    assert r.resourceState == manager.snapshot().state.value
    assert r.acquiredBytes == manager.snapshot().acquired_bytes
    assert c.processingMode == 'local' and c.localReadiness != 'ready'


def test_select_local_fences_existing_cloud_candidate_before_preparation(setup):
    app,c,r,*_ = setup
    c.bind_cloud_engine('c'*64)
    candidate = c.authority.capture_cloud_probe(candidate_fingerprint='c'*64,
        candidate_model='public-model', request_id='probe')
    local(app,c)
    assert not c.authority.is_current_cloud_probe(candidate)
    with pytest.raises(CloudDispatchBlocked): c.authority.commit_cloud_probe_attempt(candidate,'attempt')
    assert r.prepareExisting()
    spin(app, lambda:not r.busy)


def test_cloud_fences_running_and_latest_pending_result(setup):
    app,c,r,manager,journal,service,parents = setup
    local(app,c); service.release.clear()
    assert r.prepareExisting() and service.started.wait(2)
    assert r.prepareExisting()
    c.selectCloud()
    spin(app, lambda:c.processingMode == 'cloud')
    service.release.set()
    spin(app, lambda:not r.busy)
    assert c.processingMode == 'cloud' and c.localReadiness != 'ready'


def test_reentrant_preparing_mode_change_refuses_backend_start(setup):
    app,c,r,manager,journal,service,parents = setup
    local(app,c)
    switched=[]
    def switch():
        if c.localReadiness == 'preparing' and not switched:
            switched.append(True)
            c.invalidate_work()
    c.stateChanged.connect(switch)
    assert not r.prepareExisting()
    c.stateChanged.disconnect(switch)
    assert manager.calls == [] and service.calls == []


def test_terminal_reentrant_new_request_survives_old_cleanup(setup):
    app,c,r,manager,journal,service,parents = setup
    local(app,c)
    queued=[]
    def again():
        if r.phase == 'READY' and not queued:
            queued.append(None)
            queued[0] = r.prepareExisting()
    r.stateChanged.connect(again)
    assert r.prepareExisting()
    spin(app, lambda:len(service.calls)==2 and not r.busy)
    assert queued == [True] and c.localReadiness == 'ready'


@pytest.mark.parametrize('ready', [LocalServiceSnapshot('READY',None,None,0),
    LocalServiceSnapshot('READY','a'*64,'private detail',0),
    LocalServiceSnapshot('NOT_READY','a'*64,None,0),
    LocalServiceSnapshot('CLEANUP_PENDING',None,'CLEANUP_PENDING',0),
    LocalServiceSnapshot('RECOVERY_REQUIRED',None,'RECOVERY_REQUIRED',0)])
def test_no_resource_available_or_bad_service_result_can_invent_ready(setup,ready):
    app,c,r,manager,journal,service,parents = setup
    local(app,c); service.ready=ready
    assert r.prepareExisting()
    spin(app,lambda:not r.busy)
    assert c.localReadiness != 'ready' and c.processingMode == 'local'
    assert 'private' not in r.errorCode


def test_terminal_ack_tail_and_recursive_close_are_retained(setup):
    app,c,r,manager,journal,service,parents = setup
    local(app,c)
    outcomes=[]
    def close():
        if r.phase=='READY': outcomes.append(r.close(deadline=time.monotonic()+.01))
    r.stateChanged.connect(close)
    assert r.prepareExisting()
    spin(app,lambda:bool(outcomes))
    assert outcomes and all(value is False for value in outcomes)
    assert not r.prepareExisting()
    assert r.close(deadline=time.monotonic()+1)


def test_delayed_qt_ack_makes_close_false_then_drain_true(setup):
    app,c,r,manager,journal,service,parents = setup
    local(app,c)
    assert r.inspect()
    deadline=time.monotonic()+2
    while not r.runner.pending_ack_count and time.monotonic()<deadline: time.sleep(.001)
    assert r.runner.pending_ack_count == 1
    assert not r.close(deadline=time.monotonic())
    assert r.close(deadline=time.monotonic()+1)


def test_owner_thread_required_for_all_mutating_actions(setup):
    app,c,r,*_ = setup
    errors=[]
    def offthread():
        for action in (r.inspect,r.prepareExisting,r.pause,r.cancel,r.begin_close,
                       lambda:r.close(deadline=time.monotonic()+1)):
            try: action()
            except RuntimeError as exc: errors.append(str(exc))
    thread=Thread(target=offthread); thread.start(); thread.join(2)
    assert not thread.is_alive() and len(errors)==6


@pytest.mark.parametrize('changed', [{}, {'session_id':'foreign-session'},
    {'catalog_id':'b'*64}, {'operation_id':'f'*32}])
def test_same_generation_foreign_result_identity_cannot_publish(setup,changed):
    app,c,r,manager,journal,service,parents = setup
    local(app,c); service.release.clear()
    assert r.prepareExisting() and service.started.wait(2)
    request=r._current
    from src.services.local_ai.resource_operation_runner import ResourceOperationResult
    result=ResourceOperationResult(request,manager.snapshot(),service.ready,journal.value,None)
    r._consume_completion(replace(request,**changed),result)
    assert c.localReadiness == 'preparing' and r.busy
    service.release.set(); spin(app,lambda:not r.busy)


def test_close_with_unstarted_pending_retires_logical_owner_but_not_worker(setup):
    app,c,r,manager,journal,service,parents = setup
    local(app,c); manager.release.clear()
    assert r.prepareExisting() and manager.started.wait(2)
    assert r.prepareExisting()
    assert not r.close(deadline=time.monotonic()+.01)
    manager.release.set()
    assert r.close(deadline=time.monotonic()+1)
    assert not r.busy


def test_inspection_error_is_truthfully_projected(setup):
    app,c,r,manager,journal,service,parents = setup
    from src.services.local_ai.resource_manager import ResourceState
    manager.value = replace(manager.value, state=ResourceState.ERROR, error_code='VERIFICATION_FAILED')
    assert r.inspect()
    spin(app,lambda:not r.busy)
    assert r.errorCode=='VERIFICATION_FAILED' and r.phase=='FAILED'


def test_explicit_cloud_choice_fences_before_persistence_ack(setup,monkeypatch):
    app,c,r,manager,journal,service,parents = setup
    local(app,c); service.release.clear()
    saved,release=Event(),Event()
    real_save=c._store.save
    def blocked_save(intent):
        saved.set()
        assert release.wait(5)
        return real_save(intent)
    monkeypatch.setattr(c._store,'save',blocked_save)
    try:
        assert r.prepareExisting() and service.started.wait(2)
        old_generation=c.snapshot.generation
        active=r._current
        assert r.prepareExisting()
        pending=r._current
        c.selectCloud()
        assert saved.wait(2)
        assert c.processingMode=='local' and c.snapshot.generation==old_generation
        assert active.cancel_event.is_set() and pending.cancel_event.is_set()
        service.release.set()
        spin(app,lambda:not r.busy)
        assert c.localReadiness != 'ready'
    finally:
        release.set(); service.release.set()
    spin(app,lambda:c.pending_ack_count==0)


def test_preparing_reentrant_explicit_cloud_intent_refuses_backend(setup):
    app,c,r,manager,journal,service,parents=setup
    local(app,c)
    switched=[]
    def switch():
        if c.localReadiness=='preparing' and not switched:
            switched.append(True)
            c.selectCloud()
    c.stateChanged.connect(switch)
    try: assert not r.prepareExisting()
    finally: c.stateChanged.disconnect(switch)
    assert manager.calls==[] and service.calls==[]


def test_qml_byte_binding_preserves_real_catalog_total_without_int32_overflow(setup):
    app,c,r,*_=setup
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtCore import QUrl
    engine=QQmlEngine()
    engine.rootContext().setContextProperty('resources',r)
    component=QQmlComponent(engine)
    component.setData(b'import QtQml\nQtObject { property double total: resources.totalBytes; '
        b'property double retained: resources.acquiredBytes; property double remaining: '
        b'resources.remainingTransferBytes }',QUrl())
    item=component.create()
    assert item is not None, component.errors()
    assert item.property('total')==3431786583 and item.property('remaining')==3431786583
    assert item.property('retained')==0
    for name in ('totalBytes','verifiedBytes','acquiredBytes','remainingTransferBytes'):
        prop=r.metaObject().property(r.metaObject().indexOfProperty(name))
        assert prop.typeName()=='qlonglong'
    import shiboken6
    shiboken6.delete(item)
    shiboken6.delete(engine)


def test_reentrant_preparing_new_action_wins_without_outer_recapture(setup):
    app,c,r,manager,journal,service,parents=setup
    local(app,c)
    queued=[]
    def nested():
        if c.localReadiness=='preparing' and not queued:
            queued.append(None)
            queued[0]=r.inspect()
    c.stateChanged.connect(nested)
    try: assert not r.prepareExisting()
    finally: c.stateChanged.disconnect(nested)
    spin(app,lambda:not r.busy)
    assert queued==[True] and manager.calls==['inspect'] and service.calls==[]


@pytest.mark.parametrize('foreign',[False,True])
def test_actual_borrowed_service_with_actual_journal_busy_semantics(tmp_path,app,foreign):
    from src.services.local_ai.inference_journal import LocalInferenceJournal,InferenceRecoveryState
    from src.services.local_ai.inference_service import LocalInferenceConfig,LocalInferenceService
    from tests.unit.test_local_inference_service import Rig
    config,manager,_,_,parents=dependencies(tmp_path)
    # Only a tiny public-state journal is real. Attestation/profile/stage/process
    # remain the existing synthetic service seams, with no model/native policy.
    config.state_root.parent.mkdir()
    rig=Rig()
    deps=rig.deps()
    deps.journal_factory=LocalInferenceJournal
    deps.stage_model_bundle=lambda parent,sid,members,entrypoint,**kwargs: rig.stage(
        r'C:\state',sid,members,entrypoint,**kwargs)
    service=LocalInferenceService(LocalInferenceConfig(config.resource_root,config.runtime_root,
        config.state_root,config.catalog),_dependencies=deps)
    observer=LocalInferenceJournal(config.state_root)
    coordinator=ProcessingCoordinator(ProcessingIntentStore(tmp_path/'intent.json'))
    controller=api()(coordinator,config,manager,service,trusted_anchor=tmp_path,
        journal=observer,prepare_parents=parents)
    foreign_context=None
    try:
        local(app,coordinator)
        if foreign:
            foreign_context=LocalInferenceJournal(config.state_root).lease()
            foreign_context.__enter__()
            assert observer.inspect_recovery_state() is InferenceRecoveryState.BUSY
        assert controller.prepareExisting()
        spin(app,lambda:not controller.busy)
        if foreign:
            assert service.snapshot().phase=='RECOVERY_REQUIRED'
            assert controller.phase=='RECOVERY_REQUIRED' and 'run' not in rig.log
            assert not controller.close(deadline=time.monotonic()+.01)
        else:
            assert controller.phase=='READY' and coordinator.localReadiness=='ready'
            assert observer.inspect_recovery_state() is InferenceRecoveryState.BUSY
            assert controller.prepareExisting()
            spin(app,lambda:not controller.busy)
            assert controller.phase=='READY' and rig.log.count('run')==2
            assert controller.recoveryState=='busy'
    finally:
        if foreign_context is not None: foreign_context.__exit__(None,None,None)
        # A foreign-busy service genuinely remains RECOVERY_REQUIRED. Its lack
        # of launch is proven, not permission to reset/adopt its state. Drain
        # this controller's own worker/acks, then retain the borrowed service.
        controller.begin_close()
        app.processEvents()
        if foreign:
            assert controller.runner.worker is not None
            controller.runner.worker.join(1)
            assert not controller.runner.worker.is_alive()
            assert controller.runner.pending_ack_count==0
        else:
            assert service.shutdown(deadline=time.monotonic()+2).phase=='CLOSED'
            assert controller.close(deadline=time.monotonic()+2)
        assert coordinator.drain_choice_writer(deadline=time.monotonic()+2)


def test_retry_cleanup_only_borrowed_current_owner_and_keeps_local(setup):
    app,c,r,manager,journal,service,parents=setup
    local(app,c)
    assert not r.retryCleanup()
    service.ready=LocalServiceSnapshot('CLEANUP_PENDING',None,'CLEANUP_PENDING',0)
    assert r.prepareExisting()
    spin(app,lambda:not r.busy)
    assert r.canRetryCleanup and r.phase=='CLEANUP_PENDING'
    assert r.retryCleanup()
    spin(app,lambda:not r.busy)
    assert service.calls==['ready','cleanup'] and c.processingMode=='local'
    assert not r.canRetryCleanup and c.localReadiness!='ready'


def test_failed_preparation_preserves_truthful_manager_and_offline_source(setup,tmp_path):
    app,c,r,manager,journal,service,parents=setup
    local(app,c)
    source=tmp_path/'public-source'; source.mkdir()
    sentinel=source/'unrelated-public.txt'
    sentinel.write_bytes(b'synthetic public source')
    before=manager.snapshot()
    manager.failure=OSError('private file detail')
    assert r.importAndEnable(str(source))
    spin(app,lambda:not r.busy)
    assert r.phase=='FAILED' and r.errorCode=='PREPARATION_FAILED'
    assert c.processingMode=='local' and c.localReadiness=='failed'
    assert r.resourceState==manager.snapshot().state.value
    assert r.acquiredBytes==before.acquired_bytes and sentinel.read_bytes()==b'synthetic public source'


def test_reentrant_begin_close_during_preparing_has_no_backend(setup):
    app,c,r,manager,journal,service,parents=setup
    local(app,c)
    once=[]
    def closing():
        if c.localReadiness=='preparing' and not once:
            once.append(True)
            r.begin_close()
            assert not r.close(deadline=time.monotonic()+.01)
    c.stateChanged.connect(closing)
    try: assert not r.prepareExisting()
    finally: c.stateChanged.disconnect(closing)
    assert manager.calls==[] and service.calls==[]
    assert r.close(deadline=time.monotonic()+1)


@pytest.mark.parametrize('literal',['false','1','"true"'])
def test_qml_nonbool_consent_is_not_coerced_into_download_authority(setup,literal):
    app,c,r,manager,journal,service,parents=setup
    from PySide6.QtQml import QQmlComponent,QQmlEngine
    from PySide6.QtCore import QUrl
    import shiboken6
    local(app,c)
    engine=QQmlEngine()
    engine.rootContext().setContextProperty('resources',r)
    component=QQmlComponent(engine)
    component.setData(('import QtQml\nQtObject { property bool accepted: '
        'resources.downloadAndEnable('+literal+') }').encode(),QUrl())
    item=component.create()
    try:
        assert item is not None,component.errors()
        assert item.property('accepted') is False
        assert manager.calls==[] and parents.calls==[] and service.calls==[]
    finally:
        if item is not None: shiboken6.delete(item)
        shiboken6.delete(engine)


def test_qml_actual_true_consent_admits_exact_public_download(setup):
    app,c,r,manager,journal,service,parents=setup
    from PySide6.QtQml import QQmlComponent,QQmlEngine
    from PySide6.QtCore import QUrl
    import shiboken6
    local(app,c)
    manager.release.clear()
    engine=QQmlEngine()
    engine.rootContext().setContextProperty('resources',r)
    component=QQmlComponent(engine)
    component.setData(b'import QtQml\nQtObject { property bool accepted: '
        b'resources.downloadAndEnable(true) }',QUrl())
    item=component.create()
    try:
        assert item is not None,component.errors()
        assert item.property('accepted') is True
        assert manager.started.wait(2) and r.busy and manager.calls==['bundle']
    finally:
        manager.release.set()
        if item is not None: shiboken6.delete(item)
        shiboken6.delete(engine)
    spin(app,lambda:not r.busy)
    assert manager.calls==['bundle','download','inspect'] and r.phase=='READY'


@pytest.mark.parametrize('action,phase',[('cancel','CANCELLED'),('pause','PAUSED')])
def test_r1_late_stop_after_computed_ready_held_future_fences_publication(setup,action,phase):
    app,c,r,manager,journal,service,parents=setup
    local(app,c); service.release.clear()
    entered,release=Event(),Event()
    terminal_owners=[]
    def done(_): entered.set(); assert release.wait(3)
    def terminal():
        if r.phase==phase:
            terminal_owners.append(r.runner.pending_ack_count)
    r.stateChanged.connect(terminal)
    try:
        assert r.downloadAndEnable(True) and service.started.wait(2)
        future=r.runner.active_future
        future.add_done_callback(done)
        service.release.set()
        assert entered.wait(2) and future.done()
        assert future.result().service.phase=='READY'
        assert getattr(r,action)() is True
        assert r.busy and r.runner.pending_ack_count==1 and r.runner.worker.is_alive()
        release.set()
        spin(app,lambda:not r.busy)
        assert r.phase==phase and r.errorCode==phase
        assert c.processingMode=='local' and c.localReadiness=='cancelled'
        assert c.snapshot.engine_fingerprint is None
        assert r.resourceState==manager.snapshot().state.value=='available'
        assert r.verifiedBytes==manager.snapshot().verified_bytes
        assert r.acquiredBytes==manager.snapshot().acquired_bytes
        assert terminal_owners and all(count==1 for count in terminal_owners)
    finally:
        release.set(); service.release.set()
        r.stateChanged.disconnect(terminal)


@pytest.mark.parametrize('action,phase',[('cancel','CANCELLED'),('pause','PAUSED')])
def test_r1_stop_acceptance_during_queued_ack_tail(setup,action,phase):
    app,c,r,manager,journal,service,parents=setup
    local(app,c)
    assert r.downloadAndEnable(True)
    deadline=time.monotonic()+2
    while (r.runner.pending_ack_count!=1 or r.runner.active_future is not None) and time.monotonic()<deadline:
        time.sleep(.001)
    assert r.runner.pending_ack_count==1 and r.runner.active_future is None
    assert getattr(r,action)() is True
    spin(app,lambda:not r.busy)
    assert r.phase==phase and c.localReadiness=='cancelled'


def test_r1_cancel_after_terminal_logical_retirement_refuses_old_callback_tail(setup):
    app,c,r,manager,journal,service,parents=setup
    local(app,c)
    posted,release=Event(),Event()
    actual=r.runner.completion_callback
    def held(request,result):
        actual(request,result); posted.set(); assert release.wait(3)
    r.runner.completion_callback=held
    try:
        assert r.prepareExisting() and posted.wait(2)
        spin(app,lambda:not r.busy)
        assert r.phase=='READY' and r.runner.active_future.done()
        assert r.cancel() is False
    finally: release.set()


def test_r1_incomplete_cleanup_keeps_explicit_second_retry(setup):
    app,c,r,manager,journal,service,parents=setup
    local(app,c)
    service.ready=LocalServiceSnapshot('CLEANUP_PENDING',None,'CLEANUP_PENDING',0)
    assert r.prepareExisting(); spin(app,lambda:not r.busy)
    responses=[LocalServiceSnapshot('CLEANUP_PENDING',None,'CLEANUP_PENDING',0),
        LocalServiceSnapshot('NOT_READY',None,None,0)]
    def cleanup(*,deadline):
        service.calls.append('cleanup')
        service.value=responses.pop(0)
        return service.value
    service.retry_cleanup=cleanup
    assert r.retryCleanup(); spin(app,lambda:not r.busy)
    assert r.phase=='CLEANUP_PENDING' and r.errorCode=='CLEANUP_PENDING' and r.canRetryCleanup
    assert c.processingMode=='local' and c.localReadiness!='ready'
    assert r.retryCleanup(); spin(app,lambda:not r.busy)
    assert service.calls==['ready','cleanup','cleanup']
    assert not r.canRetryCleanup and c.localReadiness=='not_ready'


def test_r1_cleanup_recovery_required_remains_distinct_and_not_retryable(setup):
    app,c,r,manager,journal,service,parents=setup
    local(app,c)
    service.ready=LocalServiceSnapshot('CLEANUP_PENDING',None,'CLEANUP_PENDING',0)
    assert r.prepareExisting(); spin(app,lambda:not r.busy)
    def cleanup(*,deadline):
        service.calls.append('cleanup')
        service.value=LocalServiceSnapshot('RECOVERY_REQUIRED',None,'RECOVERY_REQUIRED',0)
        return service.value
    actual=service.retry_cleanup
    service.retry_cleanup=cleanup
    try:
        assert r.retryCleanup(); spin(app,lambda:not r.busy)
        assert r.phase=='RECOVERY_REQUIRED' and r.errorCode=='RECOVERY_REQUIRED'
        assert not r.canRetryCleanup and not r.retryCleanup()
        assert c.processingMode=='local' and c.localReadiness!='ready'
    finally: service.retry_cleanup=actual


@pytest.mark.parametrize('outcome',['available','partial','missing','error','exception'])
def test_r1_repair_revokes_ready_before_mutation_and_never_selfchecks(setup,outcome):
    app,c,r,manager,journal,service,parents=setup
    from src.services.local_ai.resource_manager import ResourceState
    local(app,c)
    assert r.prepareExisting(); spin(app,lambda:not r.busy)
    assert c.localReadiness=='ready'
    before=c.snapshot
    observations=[]
    untouched=('runtime-cpu','vision-f16')
    def repair(identifier):
        observations.append(c.snapshot)
        manager.calls.append('repair')
        assert identifier=='model-q4'
        if outcome=='exception': raise OSError('private repair detail')
        state=ResourceState(outcome)
        if outcome=='available': return manager.value
        manager.value=replace(manager.value,state=state,
            verified_ids=untouched if outcome!='missing' else (),
            verified_bytes=sum(x.bytes for x in manager.catalog.resources if x.id in untouched)
                if outcome!='missing' else 0,
            error_code='VERIFICATION_FAILED' if outcome=='error' else None)
        return manager.value
    manager.repair_resource=repair
    assert r.repairResource('model-q4'); spin(app,lambda:not r.busy)
    assert observations and observations[0].local_readiness is LocalReadiness.PREPARING
    assert observations[0].engine_fingerprint is None and observations[0].generation==before.generation+1
    assert c.snapshot.engine_fingerprint is None and c.localReadiness in ('not_ready','failed')
    assert c.processingMode=='local' and service.calls==['ready']
    assert r.resourceState==manager.snapshot().state.value
    assert manager.calls==['inspect','repair']


@pytest.mark.parametrize('change',['cloud','invalidate'])
def test_r1_repair_preparing_reentrant_choice_refuses_mutation(setup,change):
    app,c,r,manager,journal,service,parents=setup
    local(app,c)
    assert r.prepareExisting(); spin(app,lambda:not r.busy)
    once=[]
    def changed():
        if c.localReadiness=='preparing' and not once:
            once.append(True)
            (c.selectCloud if change=='cloud' else c.invalidate_work)()
    c.stateChanged.connect(changed)
    try: assert not r.repairResource('model-q4')
    finally: c.stateChanged.disconnect(changed)
    assert manager.calls==['inspect'] and service.calls==['ready']
    assert c.snapshot.engine_fingerprint is None


def test_r1_blocked_prepare_superseded_inspect_retires_preparing_after_drain(setup):
    app,c,r,manager,journal,service,parents=setup
    local(app,c); service.release.clear()
    try:
        assert r.prepareExisting() and service.started.wait(2)
        assert r.inspect()
        service.release.set(); spin(app,lambda:not r.busy)
        assert c.processingMode=='local' and c.localReadiness=='cancelled'
        assert c.snapshot.engine_fingerprint is None and r.phase=='AVAILABLE'
        assert r.runner.pending_ack_count==0 and service.calls==['ready']
    finally: service.release.set()


def test_r1_nested_preparing_inspect_retires_unstarted_projection(setup):
    app,c,r,manager,journal,service,parents=setup
    local(app,c)
    admitted=[]
    def nested():
        if c.localReadiness=='preparing' and not admitted:
            admitted.append(None); admitted[0]=r.inspect()
    c.stateChanged.connect(nested)
    try: assert not r.prepareExisting()
    finally: c.stateChanged.disconnect(nested)
    spin(app,lambda:not r.busy)
    assert admitted==[True] and manager.calls==['inspect'] and service.calls==[]
    assert c.localReadiness=='cancelled' and c.processingMode=='local' and r.phase=='AVAILABLE'


def test_r1_standalone_inspect_preserves_current_genuine_ready(setup):
    app,c,r,manager,journal,service,parents=setup
    local(app,c)
    assert r.prepareExisting(); spin(app,lambda:not r.busy)
    before=c.snapshot
    assert r.inspect(); spin(app,lambda:not r.busy)
    assert c.snapshot==before and r.resourceState=='available' and service.calls==['ready']


def test_r1_inspect_retirement_callback_new_preparation_survives(setup):
    app,c,r,manager,journal,service,parents=setup
    local(app,c); service.release.clear()
    assert r.prepareExisting() and service.started.wait(2)
    assert r.inspect()
    queued=[]
    def again():
        if c.localReadiness=='cancelled' and not queued:
            queued.append(None); queued[0]=r.prepareExisting()
    c.stateChanged.connect(again)
    try:
        service.release.set()
        spin(app,lambda:bool(queued) and not r.busy)
        assert queued==[True] and c.localReadiness=='ready' and r.phase=='READY'
    finally:
        service.release.set(); c.stateChanged.disconnect(again)


def test_r1_inspect_does_not_clear_newer_explicit_choice(setup):
    app,c,r,manager,journal,service,parents=setup
    local(app,c); service.release.clear()
    try:
        assert r.prepareExisting() and service.started.wait(2)
        assert r.inspect()
        c.selectCloud(); spin(app,lambda:c.processingMode=='cloud')
        expected=c.snapshot
        service.release.set(); spin(app,lambda:not r.busy)
        assert c.snapshot==expected and c.processingMode=='cloud'
    finally: service.release.set()


@pytest.mark.parametrize('kind',['prepare','inspect'])
@pytest.mark.parametrize('publication',['invalidate','catalog'])
def test_r1_same_choice_generation_invalidation_retires_owned_preparing(setup,kind,publication):
    app,c,r,manager,journal,service,parents=setup
    local(app,c); service.release.clear()
    try:
        assert r.prepareExisting() and service.started.wait(2)
        if kind=='inspect': assert r.inspect()
        revision=c.snapshot.revision
        if publication=='invalidate': c.invalidate_work()
        else:
            from src.core.analysis_catalog import AnalysisCatalog, AnalysisCatalogSource
            from src.core.processing_analysis import AnalysisSettings
            catalog=AnalysisCatalog(AnalysisSettings(1000,10,5,2,'balanced',30,0,
                False,False,False),None,'',())
            source=AnalysisCatalogSource(catalog)
            c.publish_catalog(source,catalog)
            assert source.get() is catalog
        assert c.snapshot.revision==revision and c.localReadiness=='preparing'
        service.release.set(); spin(app,lambda:not r.busy)
        assert c.localReadiness=='cancelled' and c.snapshot.engine_fingerprint is None
    finally: service.release.set()


def test_r1_controller_owned_drain_separates_borrowed_cleanup(setup):
    app,c,r,manager,journal,service,parents=setup
    local(app,c)
    service.ready=LocalServiceSnapshot('CLEANUP_PENDING',None,'CLEANUP_PENDING',0)
    assert r.prepareExisting()
    spin(app,lambda:not r.busy)
    assert service.snapshot().phase=='CLEANUP_PENDING'
    try:
        assert r.drain_owned_operations(deadline=time.monotonic()+1)
        assert not r.close(deadline=time.monotonic()+.01)
        assert service.calls==['ready'] and service.snapshot().phase=='CLEANUP_PENDING'
    finally: service.retry_cleanup(deadline=time.monotonic()+1)


def test_r1_controller_owned_drain_retains_emission_and_is_recursive_safe(setup):
    app,c,r,manager,journal,service,parents=setup
    observed=[]
    def changed():
        if not observed:
            observed.append(None)
            observed[0]=r.drain_owned_operations(deadline=time.monotonic()+.01)
    r.stateChanged.connect(changed)
    try:
        r.inspect()
        assert observed==[False]
    finally: r.stateChanged.disconnect(changed)
    assert r.drain_owned_operations(deadline=time.monotonic()+1)


def test_r1_controller_owned_drain_retains_real_public_callback_and_qt_ack(setup):
    app,c,r,manager,journal,service,parents=setup
    entered,release=Event(),Event()
    post=r.runner.completion_callback
    def held(req,result):
        post(req,result); entered.set(); assert release.wait(5)
    r.runner.completion_callback=held
    assert r.inspect() and entered.wait(2)
    try:
        assert r.runner.pending_ack_count==1 and r.runner.active_future.done()
        assert not r.drain_owned_operations(deadline=time.monotonic()+.01)
        assert r.runner.pending_ack_count==0  # real queued Qt delivery consumed
        assert r.runner.worker.is_alive() and r.runner.active_future.done()
    finally: release.set()
    assert r.drain_owned_operations(deadline=time.monotonic()+1)

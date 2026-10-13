"""Synthetic boundaries exercise the one real runtime/controller/worker graph."""
from dataclasses import replace
import json
from threading import Event, get_ident
import time

import pytest
from PySide6.QtWidgets import QApplication

from src.controllers.local_resources_controller import LocalResourcesController
from src.core.processing_authority import LocalReadiness, ProcessingMode
from src.models.app_config import AppConfig
from src.qml_bootstrap import build_qml_runtime, build_default_local_config
from src.services.local_ai.inference_service import LocalServiceSnapshot
from src.services.local_ai.production_resources import load_production_resources, PRODUCT_CATALOG_ID
from src.services.local_ai.resource_manager import ResourceState
from tests.integration.test_managed_processing_runtime import Credentials
from tests.unit.test_local_resource_operation_runner import Manager, Journal, Parents, Service


class ManagedService(Service):
    def __init__(self, config):
        super().__init__(config)
        self._config = config
        self.shutdown_started, self.shutdown_release = Event(), Event()
        self.shutdown_release.set()
        self.shutdown_phase = 'CLOSED'

    def shutdown(self, *, deadline):
        self.calls.append('shutdown')
        self.threads.append(get_ident())
        self.shutdown_started.set()
        assert self.shutdown_release.wait(5)
        self.value = LocalServiceSnapshot(self.shutdown_phase, None,
            None if self.shutdown_phase == 'CLOSED' else self.shutdown_phase, 0)
        return self.value


@pytest.fixture(scope='module')
def app(): return QApplication.instance() or QApplication([])


def spin(app, predicate):
    limit = time.monotonic()+3
    while not predicate() and time.monotonic() < limit:
        app.processEvents(); time.sleep(.001)
    assert predicate()


@pytest.fixture
def graph(tmp_path, app, monkeypatch):
    anchor = tmp_path / 'trusted'; anchor.mkdir()
    monkeypatch.setenv('LOCALAPPDATA', str(anchor))
    config = load_production_resources(user_data_root=anchor / 'Xuxia/local-ai')
    manager, journal, parents = Manager(config), Journal(), Parents()
    runtimes, services, bound = [], [], []
    def service_factory(value):
        service = ManagedService(value); services.append(service); return service
    def controller_factory(coordinator, product, actual_manager, service, *, trusted_anchor):
        assert actual_manager.catalog is product.catalog
        assert actual_manager.root == product.resource_root
        assert product.catalog is config.catalog or product.catalog == config.catalog
        bound.append((coordinator, product, actual_manager, service, trusted_anchor))
        # Real single manager/controller/runner; replace only public I/O methods.
        manager.catalog, manager.root = product.catalog, product.resource_root
        for name in ('snapshot','inspect','import_bundled_runtime','download','import_offline','repair_resource'):
            monkeypatch.setattr(actual_manager,name,getattr(manager,name))
        return LocalResourcesController(coordinator, product, actual_manager, service,
            trusted_anchor=trusted_anchor, journal=journal, prepare_parents=parents)
    def make(**kwargs):
        defaults = dict(config_file=tmp_path/'settings.json', live_config=AppConfig(),
            credential_store=Credentials(), usage_recorder=None, diagnostics_service=None,
            local_inference_factory=service_factory, resource_controller_factory=controller_factory,
            managed_adapter_factory=lambda *a, **k: pytest.fail('cloud submission'),
            connection_test_service=lambda *a, **k: pytest.fail('cloud probe'))
        defaults.update(kwargs)
        runtime = build_qml_runtime(**defaults); runtimes.append(runtime); return runtime
    yield make, config, manager, journal, parents, services, bound
    manager.release.set()
    for service in services:
        service.release.set(); service.shutdown_release.set(); service.shutdown_phase='CLOSED'
    for runtime in runtimes:
        assert runtime.cleanup(deadline=time.monotonic()+3)
        runtime.assert_zero_warnings()


def test_default_is_exact_product_independent_of_cwd(tmp_path, monkeypatch):
    anchor = tmp_path/'trusted'; anchor.mkdir()
    monkeypatch.setenv('LOCALAPPDATA', str(anchor))
    monkeypatch.chdir(tmp_path)
    config = build_default_local_config()
    assert config.catalog.identity == PRODUCT_CATALOG_ID
    assert config.catalog.purpose == 'managed-local-resources-v1'
    assert config.resource_root == anchor/'Xuxia/local-ai/resources'/PRODUCT_CATALOG_ID
    assert config.runtime_root == anchor/'Xuxia/local-ai/runtime'/PRODUCT_CATALOG_ID
    assert config.state_root == anchor/'Xuxia/local-ai/state'
    assert not (anchor/'Xuxia').exists()


def test_omitted_resources_bind_same_graph_before_qml_and_cloud_is_inert(graph):
    make, config, manager, journal, parents, services, bound = graph
    runtime = make()
    controller = runtime.local_resources_controller
    service = runtime.local_inference_service
    assert controller.coordinator is runtime.processing_coordinator
    assert controller.runner.service is service
    assert controller.config.catalog is service._config.catalog
    assert controller.runner.manager.catalog is service._config.catalog
    assert controller.runner.manager is runtime.resource_manager
    assert controller.runner.authority is runtime.processing_coordinator.authority
    assert runtime.shutdown_owner.service is service
    assert runtime.batch_controller._managed_analyzer is runtime.analysis_service
    assert runtime.watch_owner.analysis_service is runtime.analysis_service
    assert runtime.engine.rootContext().contextProperty('localResourcesController') is controller
    assert controller.runner.worker is None and runtime.shutdown_owner.worker is None
    assert manager.calls == [] and journal.calls == 0 and parents.calls == [] and service.calls == []


def test_explicit_trusted_product_config_reuses_exact_catalog_without_discovery(graph):
    make, config, *_ = graph
    runtime = make(production_resources=config, trusted_local_anchor=config.state_root.parents[2])
    assert runtime.local_resources_controller.config is config
    assert runtime.local_inference_service._config.catalog is config.catalog


@pytest.mark.parametrize('anchor', ['relative','missing'])
def test_untrusted_or_nonexisting_anchor_never_creates_parents(graph,tmp_path,anchor):
    make,_,manager,_,parents,_,_=graph
    target='relative' if anchor=='relative' else tmp_path/'missing'
    with pytest.raises(ValueError,match='INVALID_RESOURCE_COMPOSITION'):
        make(trusted_local_anchor=target)
    assert manager.calls==[] and parents.calls==[] and not (tmp_path/'missing').exists()


def test_foreign_supplied_controller_refused_without_sealing_its_operations(graph,tmp_path,app):
    from src.controllers.processing_coordinator import ProcessingCoordinator
    from src.core.processing_intent_store import ProcessingIntentStore
    make,config,*_=graph
    coordinator=ProcessingCoordinator(ProcessingIntentStore(tmp_path/'foreign-intent.json'))
    service=ManagedService(config)
    resources=LocalResourcesController(coordinator,config,Manager(config),service,
        trusted_anchor=config.state_root.parents[2],journal=Journal(),prepare_parents=Parents())
    coordinator.selectLocal()
    try:
        with pytest.raises(ValueError,match='INVALID_RESOURCE_COMPOSITION'):
            make(production_resources=config,resource_controller=resources)
        assert resources.canPrepare and resources.runner.worker is None
        assert service.calls==[]
    finally:
        assert resources.close(deadline=time.monotonic()+2)
        assert coordinator.drain_choice_writer(deadline=time.monotonic()+2)


def test_explicit_none_is_unavailable_not_silent_default_disable(graph):
    make, *_ = graph
    runtime = make(resource_controller=None)
    assert runtime.local_resources_controller is None
    assert runtime.engine.rootContext().contextProperty('localResourcesController') is None


def test_factory_cannot_substitute_an_equal_but_second_resource_manager(graph):
    make,*_=graph
    def wrong(coordinator,config,manager,service,*,trusted_anchor):
        return LocalResourcesController(coordinator,config,Manager(config),service,
            trusted_anchor=trusted_anchor,journal=Journal(),prepare_parents=Parents())
    with pytest.raises(ValueError,match='INVALID_RESOURCE_COMPOSITION'):
        make(resource_controller_factory=wrong)


def test_supplied_same_graph_controller_borrows_qobject_lifetime_hands_over_drain(tmp_path,app,monkeypatch):
    from shiboken6 import isValid
    from src.controllers.processing_coordinator import ProcessingCoordinator
    from src.core.processing_intent_store import ProcessingIntentStore
    from src.services.local_ai.inference_service import LocalInferenceConfig
    from src.services.local_ai.resource_manager import ResourceManager
    anchor=tmp_path/'trusted';anchor.mkdir()
    config=load_production_resources(user_data_root=anchor/'data')
    local_config=LocalInferenceConfig(config.resource_root,config.runtime_root,config.state_root,config.catalog)
    service=ManagedService(local_config)
    manager=ResourceManager(config.resource_root,config.catalog)
    coordinator=ProcessingCoordinator(ProcessingIntentStore(tmp_path/'processing-intent.json'))
    resources=LocalResourcesController(coordinator,config,manager,service,trusted_anchor=anchor)
    monkeypatch.setattr('src.controllers.processing_coordinator.ProcessingCoordinator',lambda *a,**k:coordinator)
    runtime=build_qml_runtime(config_file=tmp_path/'settings.json',live_config=AppConfig(),
        credential_store=Credentials(),usage_recorder=None,diagnostics_service=None,
        batch_controller=None,watch_controller=None,template_controller=None,
        connection_test_service=lambda *a:None,production_resources=config,
        trusted_local_anchor=anchor,local_inference_factory=lambda _:service,
        resource_controller=resources)
    try:
        assert runtime.resource_manager is manager
        assert runtime.local_resources_controller is resources
        assert not runtime.owns_local_resources_controller
    finally:assert runtime.cleanup(deadline=time.monotonic()+3)
    assert isValid(resources) and not resources.prepareExisting()


def test_foreign_inference_config_requires_explicit_unavailable_seam(graph, tmp_path):
    make, config, *_ = graph
    from src.services.local_ai.inference_service import LocalInferenceConfig
    foreign = LocalInferenceConfig(tmp_path/'foreign', config.runtime_root, config.state_root, config.catalog)
    with pytest.raises(ValueError, match='INVALID_RESOURCE_COMPOSITION'):
        make(local_config=foreign)
    runtime = make(local_config=foreign, resource_controller=None)
    assert runtime.local_inference_service._config is foreign


def test_deliberate_foreign_config_unavailable_needs_no_product_root_discovery(graph,tmp_path,monkeypatch):
    make,config,*_=graph
    from src.services.local_ai.inference_service import LocalInferenceConfig
    foreign=LocalInferenceConfig(tmp_path/'foreign',tmp_path/'runtime',tmp_path/'state',config.catalog)
    monkeypatch.delenv('LOCALAPPDATA')
    runtime=make(local_config=foreign,resource_controller=None)
    assert runtime.local_inference_service._config is foreign


def test_fresh_real_production_default_constructs_inert_without_test_factory(tmp_path,app,monkeypatch):
    anchor=tmp_path/'trusted';anchor.mkdir();monkeypatch.setenv('LOCALAPPDATA',str(anchor))
    runtime=build_qml_runtime(config_file=tmp_path/'settings.json',live_config=AppConfig(),
        credential_store=Credentials(),usage_recorder=None,diagnostics_service=None,
        batch_controller=None,watch_controller=None,template_controller=None,
        connection_test_service=lambda *a:pytest.fail('probe'))
    try:
        resources=runtime.local_resources_controller
        assert type(resources) is LocalResourcesController
        assert resources.runner.manager is runtime.resource_manager
        assert resources.runner.service is runtime.local_inference_service
        assert resources.runner.config is runtime.production_resources
        assert resources.runner.worker is None and runtime.shutdown_owner.worker is None
        assert not (anchor/'Xuxia').exists()
        runtime.assert_zero_warnings()
    finally:assert runtime.cleanup(deadline=time.monotonic()+3)


def test_saved_local_queues_only_existing_after_binding(graph, tmp_path, app):
    make, config, manager, journal, parents, services, _ = graph
    (tmp_path/'processing-intent.json').write_text(json.dumps(
        {'schema_version':1,'revision':1,'mode':'local'}))
    runtime = make()
    controller = runtime.local_resources_controller
    seen=[]
    controller.stateChanged.connect(lambda: seen.append(
        runtime.engine.rootContext().contextProperty('localResourcesController') is controller))
    spin(app, lambda: controller.phase=='READY')
    assert seen and all(seen)
    assert services[0].calls == ['ready'] and manager.calls == ['inspect']
    assert runtime.processing_coordinator.snapshot.mode is ProcessingMode.LOCAL
    assert runtime.processing_coordinator.snapshot.engine_fingerprint == 'a'*64


@pytest.mark.parametrize('reason', ['missing','dirty'])
def test_saved_local_missing_or_dirty_never_repairs_downloads_or_falls_back(graph, tmp_path, app, reason):
    from src.services.local_ai.inference_journal import InferenceRecoveryState
    make, config, manager, journal, parents, services, _ = graph
    if reason=='missing': manager.value = replace(manager.value,state=ResourceState.MISSING)
    else: journal.value=InferenceRecoveryState.RECOVERY_REQUIRED
    (tmp_path/'processing-intent.json').write_text(json.dumps(
        {'schema_version':1,'revision':1,'mode':'local'}))
    runtime=make()
    spin(app,lambda:runtime.local_resources_controller.phase in ('FAILED','RECOVERY_REQUIRED'))
    assert manager.calls==['inspect'] and services[0].calls==[]
    assert runtime.processing_coordinator.processingMode=='local'
    assert runtime.processing_coordinator.localReadiness!='ready'


def test_invalid_intent_does_not_invent_preparation(graph, tmp_path, app):
    make, _, manager, _, parents, services, _=graph
    (tmp_path/'processing-intent.json').write_text('{"invalid":"intent"}')
    runtime=make(); app.processEvents()
    assert runtime.processing_coordinator.processingMode=='local'
    assert manager.calls==[] and parents.calls==[] and services[0].calls==[]


def test_delayed_resource_operation_drains_before_shutdown_and_keeps_qt(graph, app):
    make, _, manager, _, _, services, _=graph
    runtime=make(); c=runtime.processing_coordinator; c.selectLocal()
    service=services[0]; service.started.clear(); service.release.clear()
    resources=runtime.local_resources_controller
    assert resources.prepareExisting() and service.started.wait(2)
    try:
        assert not runtime.cleanup(deadline=time.monotonic()+.02)
        assert runtime.engine is not None and runtime.local_resources_controller is resources
        assert 'shutdown' not in service.calls
    finally: service.release.set()
    assert runtime.cleanup(deadline=time.monotonic()+3)
    assert service.calls==['ready','shutdown']
    assert resources.runner.worker is not None and not resources.runner.worker.is_alive()
    assert not runtime.shutdown_owner.worker.is_alive()


def test_delayed_shutdown_is_off_qt_retained_and_single(graph):
    make, _, _, _, _, services, _=graph
    runtime=make(); service=services[0]; service.shutdown_release.clear()
    try:
        assert not runtime.cleanup(deadline=time.monotonic()+.02)
        assert service.shutdown_started.wait(2)
        worker=runtime.shutdown_owner.worker
        assert not runtime.cleanup(deadline=time.monotonic()+.02)
        assert runtime.shutdown_owner.worker is worker and service.calls==['shutdown']
        assert service.threads[-1]!=get_ident() and runtime.root is not None
    finally: service.shutdown_release.set()
    assert runtime.cleanup(deadline=time.monotonic()+3)


def test_cleanup_pending_does_not_circularly_block_owned_drain(graph):
    make, _, _, _, _, services, _=graph
    runtime=make(); service=services[0]
    service.value=LocalServiceSnapshot('CLEANUP_PENDING',None,'CLEANUP_PENDING',0)
    service.shutdown_phase='CLEANUP_PENDING'
    assert not runtime.cleanup(deadline=time.monotonic()+.02)
    assert service.calls and all(x=='shutdown' for x in service.calls)
    assert runtime.root is not None
    service.shutdown_phase='CLOSED'
    assert runtime.cleanup(deadline=time.monotonic()+3)


def test_reentrant_terminal_signal_retains_actual_ack_before_shutdown(graph, app):
    make, _, _, _, _, services, _=graph
    runtime=make(); c=runtime.processing_coordinator; c.selectLocal()
    resources=runtime.local_resources_controller; seen=[]
    def close():
        if resources.phase=='READY' and not seen:
            seen.append(None)
            seen[0]=runtime.cleanup(deadline=time.monotonic()+.01)
            assert 'shutdown' not in services[0].calls
    resources.stateChanged.connect(close)
    assert resources.prepareExisting()
    spin(app,lambda:bool(seen))
    assert seen==[False] and runtime.root is not None
    assert runtime.cleanup(deadline=time.monotonic()+3)


def test_catalog_and_settings_callbacks_cancel_preparation_preserve_ready_identity(graph, app):
    make, _, _, _, _, services, _=graph
    runtime=make(); coordinator=runtime.processing_coordinator
    coordinator.selectLocal(); resources=runtime.local_resources_controller
    assert resources.prepareExisting(); spin(app,lambda:resources.phase=='READY')
    identity=coordinator.snapshot.engine_fingerprint
    candidate=AppConfig(language='en_US')
    prepared=runtime.controller._runtime_input_preparer(candidate)
    runtime.controller._runtime_inputs_committed(candidate,prepared)
    assert coordinator.processingMode=='local' and coordinator.localReadiness=='ready'
    assert coordinator.snapshot.engine_fingerprint==identity
    service=services[0]; service.release.clear()
    assert resources.prepareExisting() and service.started.wait(2)
    candidate=AppConfig(language='zh_HK')
    runtime.controller._runtime_inputs_committed(candidate,runtime.controller._runtime_input_preparer(candidate))
    service.release.set(); spin(app,lambda:not resources.busy)
    assert coordinator.processingMode=='local' and coordinator.localReadiness!='ready'


def test_actual_settings_and_template_publication_fence_work_and_preparation(graph,app):
    make,_,_,_,_,services,_=graph
    runtime=make();c=runtime.processing_coordinator;r=runtime.local_resources_controller
    c.selectLocal();assert r.prepareExisting();spin(app,lambda:r.phase=='READY')
    identity=c.snapshot.engine_fingerprint
    old=runtime.analysis_service.capture_work('synthetic.txt','task',task_attempt_id='old',
        task_cancel_event=Event(),naming_mode='smart')
    settings=runtime.controller;settings.openSession();settings.language='en_US';settings.saveAll()
    assert settings.last_result.success
    assert not c.authority.is_current(old.context)
    assert c.processingMode=='local' and c.localReadiness=='ready'
    assert c.snapshot.engine_fingerprint==identity
    service=services[0];service.started.clear();service.release.clear()
    assert r.prepareExisting() and service.started.wait(2)
    generation=c.snapshot.generation
    templates=runtime.template_controller
    templates.beginCreateTemplate();templates.setDraftName('Synthetic composition')
    assert templates.saveDraft()
    assert c.snapshot.generation>generation
    assert c.processingMode=='local'
    service.release.set();spin(app,lambda:not r.busy)
    assert c.localReadiness!='ready' and r.phase=='CANCELLED'


def test_real_resource_future_callback_tail_blocks_shutdown_even_when_future_done(graph,app):
    make,_,_,_,_,services,_=graph
    runtime=make();c=runtime.processing_coordinator;c.selectLocal()
    service=services[0];service.release.clear();r=runtime.local_resources_controller
    entered,release=Event(),Event()
    assert r.prepareExisting() and service.started.wait(2)
    future=r.runner.active_future
    def callback(_):
        entered.set();assert release.wait(3)
    future.add_done_callback(callback);service.release.set()
    assert entered.wait(2) and future.done()
    try:
        assert not runtime.cleanup(deadline=time.monotonic()+.02)
        assert 'shutdown' not in service.calls
        assert runtime.local_resources_controller is r and runtime.engine is not None
    finally:release.set()
    assert runtime.cleanup(deadline=time.monotonic()+3)
    assert not r.runner.worker.is_alive()


def test_unknown_native_resource_owner_retained_without_service_shutdown(graph,app):
    from types import SimpleNamespace
    from src.services.local_ai.resource_store import StoreOwnershipUncertain
    make,_,manager,_,_,services,_=graph
    runtime=make();c=runtime.processing_coordinator;c.selectLocal()
    retained=SimpleNamespace(idle=False)
    manager.failure=StoreOwnershipUncertain(retained)
    r=runtime.local_resources_controller
    assert r.prepareExisting();spin(app,lambda:not r.busy)
    assert r.runner.retained_native_owners==(retained,)
    assert not runtime.cleanup(deadline=time.monotonic()+.02)
    assert services[0].calls==[] and runtime.engine is not None
    assert r.runner.retained_native_owners==(retained,)
    retained.idle=True
    assert runtime.cleanup(deadline=time.monotonic()+3)


def test_partial_construction_failure_retains_registered_resource_and_delayed_shutdown(graph):
    from src.qml_bootstrap import RuntimeConstructionPending,_INCOMPLETE_CONSTRUCTIONS
    make,_,_,_,_,services,bound=graph
    def fail_preparation():
        services[0].shutdown_release.clear()
        raise RuntimeError('synthetic later constructor failure')
    with pytest.raises(RuntimeConstructionPending) as failure:
        make(local_preparation_factory=fail_preparation)
    runtime=failure.value.runtime
    try:
        assert runtime in _INCOMPLETE_CONSTRUCTIONS
        assert runtime.local_resources_controller is not None
        assert runtime.local_resources_controller.runner.service is services[0]
        assert runtime.shutdown_owner.service is services[0]
        assert services[0].shutdown_started.wait(2)
        assert not runtime.cleanup(deadline=time.monotonic()+.02)
    finally:services[0].shutdown_release.set()
    assert runtime.cleanup(deadline=time.monotonic()+3)
    assert runtime not in _INCOMPLETE_CONSTRUCTIONS
    assert not runtime.shutdown_owner.worker.is_alive()


def test_runtime_recovery_required_refuses_disposal_after_actual_thread_finished(graph,app):
    make,_,_,_,_,services,_=graph
    runtime=make();service=services[0];service.shutdown_phase='RECOVERY_REQUIRED'
    assert not runtime.cleanup(deadline=time.monotonic()+.02)
    assert runtime.root is not None
    spin(app,lambda:not runtime.shutdown_owner.worker.is_alive())
    assert runtime.shutdown_owner.result.phase=='RECOVERY_REQUIRED'
    assert not runtime.shutdown_owner.worker.is_alive()
    # Synthetic external proof can permit a later test-only retry, not recovery reset.
    service.shutdown_phase='CLOSED'
    assert runtime.cleanup(deadline=time.monotonic()+3)


def test_shutdown_owner_factory_is_exact_service_owned_inert_and_registered(graph):
    from src.services.local_ai.runtime_shutdown_owner import RuntimeShutdownOwner
    make,_,_,_,_,services,_=graph;owners=[]
    def factory(service):
        owner=RuntimeShutdownOwner(service);owners.append(owner);return owner
    runtime=make(shutdown_owner_factory=factory)
    assert runtime.shutdown_owner is owners[0]
    assert owners[0].service is services[0] and owners[0].worker is None
    assert runtime.cleanup(deadline=time.monotonic()+3)
    assert services[0].calls==['shutdown'] and not owners[0].worker.is_alive()


def test_default_status_uses_current_same_service_readiness_not_resource_availability(graph,app):
    from src.controllers.status_controller import StatusLevel
    make,*_=graph
    runtime=make();status=runtime.status_controller;coordinator=runtime.processing_coordinator
    def local_status():
        return next(row for row in status.check_all(force=True).components if row.id=='local')
    assert local_status().status is StatusLevel.UNAVAILABLE
    coordinator.selectLocal()
    assert local_status().status is StatusLevel.UNAVAILABLE
    assert runtime.local_resources_controller.prepareExisting()
    spin(app,lambda:runtime.local_resources_controller.phase=='READY')
    assert local_status().status is StatusLevel.READY
    assert local_status().detail=='status.detail.available'
    coordinator.publish_local_state(coordinator.snapshot.generation,LocalReadiness.FAILED)
    assert local_status().status is StatusLevel.UNAVAILABLE

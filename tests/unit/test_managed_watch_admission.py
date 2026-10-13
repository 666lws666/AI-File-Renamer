"""Authentic sealed admission tests; synthetic catalog, no inference or transport."""
from dataclasses import replace
import importlib
from threading import Event, Thread

import pytest

from src.core.analysis_catalog import AnalysisCatalogSource, build_analysis_catalog
from src.core.batch_analysis import BatchAnalysisService
from src.core.processing_authority import LocalReadiness, ProcessingAuthority, ProcessingMode
from src.core.processing_identity import cloud_engine_fingerprint
from src.core.rename_plan import SourceFingerprint
from src.core.template_model import OutputLanguage, Template, TemplateField
from src.core.watch_config import WatchConfig
from src.models.app_config import AppConfig
from src.services.local_ai.inference_request import LocalNamingRequest


def api():
    spec = importlib.util.find_spec("src.controllers.managed_watch_ingress")
    assert spec is not None, "authentic managed Watch ingress missing"
    return importlib.import_module("src.controllers.managed_watch_ingress")


@pytest.fixture
def lane(tmp_path):
    template = Template(id="one", name="Synthetic", pattern="{dcTitle}",
                        fields=(TemplateField("dcTitle", "Title"),))
    config = AppConfig(default_template_id="one", active_provider_id="active",
        provider_profiles=[dict(id="active", model="synthetic", base_url="https://example.invalid/v1",
            enabled=True, needs_connection_verification=False, capabilities=dict(text=True))])
    source = AnalysisCatalogSource(build_analysis_catalog(config, [template]))
    authority = ProcessingAuthority(initial_mode=ProcessingMode.CLOUD)
    authority.bind_cloud_engine(cloud_engine_fingerprint(source.get().active_profile))
    def forbidden(*args, **kwargs): pytest.fail("execution/credential access during admission")
    service = BatchAnalysisService(profile_provider=lambda: source.get().active_profile,
        credential_provider=forbidden, config_provider=lambda: source.get().settings,
        template_provider=lambda key: source.get().template(key), processing_authority=authority,
        local_inference_service=object(), local_preparation_service=object(),
        managed_adapter_factory=forbidden, capture_guard=source.guard, content_extractor=forbidden)
    service.analyze = forbidden
    service.run_work = forbidden
    watch = WatchConfig(id="watch", source_dir=str(tmp_path), template_id="one")
    return service, authority, source, watch


def make(lane, post=None):
    service, authority, source, watch = lane
    return api().ManagedWatchIngress(service, authority, capture_guard=source.guard,
                                    post_event=post or (lambda event: None))


def capture(ingress, lane, event="event"):
    return ingress.capture(lane[3], "incarnation", lane[3].source_dir + "/synthetic.txt", event)


def test_capture_preserves_exact_sealed_service_return_and_cancellation(lane, monkeypatch):
    ingress = make(lane)
    seen = []
    original = lane[0].capture_work
    def observe(*args, **kwargs):
        assert kwargs["defer_execution_deadline"] is True
        assert kwargs["output_language"] == ""
        work = original(*args, **kwargs); seen.append(work); return work
    monkeypatch.setattr(lane[0], "capture_work", observe)
    event = capture(ingress, lane)
    assert event.work is seen[0] and event.watch_config is lane[3]
    assert event.work.context.task_cancel_event is event.cancel_event
    assert ingress.is_current(event)
    assert not ingress.is_current(replace(event))
    assert not ingress.retire(replace(event))
    assert ingress.retire(event) and not ingress.retire(event)
    assert event.cancel_event.is_set() and ingress.workers_idle


def test_generation_change_never_promotes_cloud_admission(lane):
    posted = []
    ingress = make(lane, posted.append)
    event = capture(ingress, lane)
    lane[1].select_local()
    assert not ingress.is_current(event)
    assert not ingress.post_stable(event, SourceFingerprint(4, 2))
    assert not posted
    ingress.retire(event)


def test_unavailable_failure_preserves_prior_snapshot_and_exact_identity(lane):
    lane[1].select_local()
    ingress = make(lane)
    event = capture(ingress, lane)
    assert event.reason == "local_unavailable"
    assert event.snapshot.mode is ProcessingMode.LOCAL
    assert not hasattr(event, "work")
    assert ingress.is_current(event) and not ingress.is_current(replace(event))
    lane[1].invalidate_work()
    assert not ingress.is_current(event)
    assert event.snapshot.generation != lane[1].snapshot().generation
    ingress.retire(event)


def test_stable_delivery_remains_owned_until_consumed_and_not_repostable(lane):
    posted = []
    ingress = make(lane, posted.append)
    event = capture(ingress, lane)
    assert ingress.post_stable(event, SourceFingerprint(4, 2))
    delivery = posted[0]
    assert delivery.admission is event and delivery.protected_extension == ".txt"
    assert delivery.target_dir == lane[3].source_dir
    assert ingress.owned_count == 1 and not ingress.workers_idle
    assert not ingress.post_stable(event, SourceFingerprint(4, 2))
    assert not ingress.retire(event)  # transfer cannot be withdrawn using its old handle
    assert not ingress.is_current(replace(delivery))
    assert ingress.is_current(delivery)
    ingress.begin_close()
    assert ingress.owned_count == 1 and not ingress.workers_idle
    assert not ingress.is_current(delivery)
    assert ingress.retire(delivery) and ingress.workers_idle


def test_capacity_is_reserved_before_capture_and_one_retirement_frees_one(lane, monkeypatch):
    ingress = make(lane)
    calls = []
    original = lane[0].capture_work
    def observed(*args, **kwargs): calls.append(1); return original(*args, **kwargs)
    monkeypatch.setattr(lane[0], "capture_work", observed)
    events = [capture(ingress, lane, str(i)) for i in range(1000)]
    assert all(event is not None for event in events)
    assert ingress.owned_count == 1000
    assert capture(ingress, lane, "overflow") is None and len(calls) == 1000
    assert ingress.retire(events[0])
    assert capture(ingress, lane, "replacement") is not None and len(calls) == 1001
    assert capture(ingress, lane, "overflow-again") is None
    ingress.begin_close()
    assert ingress.workers_idle and capture(ingress, lane) is None


@pytest.mark.parametrize("path", ["relative.txt", "../other.txt", "", "a" * 32769],
                         ids=["relative", "parent", "empty", "oversize"])
def test_invalid_fields_are_nonadmissions_without_service_capture(lane, monkeypatch, path):
    ingress = make(lane)
    monkeypatch.setattr(lane[0], "capture_work", lambda *a, **k: pytest.fail("invalid capture"))
    assert ingress.capture(lane[3], "incarnation", path, "event") is None
    assert ingress.workers_idle


def test_capture_is_source_io_free(lane, monkeypatch):
    ingress = make(lane)
    monkeypatch.setattr("os.stat", lambda *a, **k: pytest.fail("source stat during capture"))
    event = capture(ingress, lane)
    assert event.work is not None
    ingress.retire(event)


def test_close_during_capture_retains_inflight_owner_until_actual_return(lane, monkeypatch):
    ingress = make(lane)
    entered, release = Event(), Event()
    original = lane[0].capture_work
    def blocked(*args, **kwargs):
        entered.set(); assert release.wait(2); return original(*args, **kwargs)
    monkeypatch.setattr(lane[0], "capture_work", blocked)
    result = []
    thread = Thread(target=lambda: result.append(capture(ingress, lane)))
    thread.start(); assert entered.wait(2)
    ingress.begin_close()
    assert ingress.owned_count == 1 and not ingress.workers_idle
    release.set(); thread.join(2)
    assert not thread.is_alive() and result == [None] and ingress.workers_idle


def test_callback_tail_is_owned_even_after_synchronous_consumption(lane):
    entered, release = Event(), Event()
    def post(delivery):
        assert ingress.retire(delivery)
        entered.set(); assert release.wait(2)
    ingress = make(lane, post)
    event = capture(ingress, lane)
    thread = Thread(target=lambda: ingress.post_stable(event, SourceFingerprint(4, 2)))
    thread.start(); assert entered.wait(2)
    assert ingress.owned_count == 1 and not ingress.workers_idle
    release.set(); thread.join(2)
    assert ingress.workers_idle


def test_cancel_incarnation_preserves_queued_owner_but_invalidates_it(lane):
    posted = []
    ingress = make(lane, posted.append)
    event = capture(ingress, lane)
    assert ingress.post_stable(event, SourceFingerprint(4, 2))
    ingress.cancel_incarnation("watch", "different-incarnation")
    assert ingress.is_current(posted[0])
    ingress.cancel_incarnation("watch", "incarnation")
    assert not ingress.is_current(posted[0]) and ingress.owned_count == 1
    assert ingress.retire(posted[0]) and ingress.workers_idle


def test_failure_delivery_is_exact_and_never_refreshed_after_generation_change(lane):
    lane[1].select_local()
    posted = []
    ingress = make(lane, posted.append)
    failure = capture(ingress, lane)
    assert ingress.post_failure(failure) and posted == [failure] and posted[0] is failure
    old_snapshot = failure.snapshot
    lane[1].invalidate_work()
    assert failure.snapshot is old_snapshot and not ingress.is_current(failure)
    assert ingress.owned_count == 1
    ingress.retire(failure)


def test_publication_blocks_capture_until_complete_new_catalog_and_generation(lane):
    service, authority, source, watch = lane
    entered, done = Event(), Event()
    ingress = make(lane)
    events = []
    def admit():
        entered.set(); events.append(capture(ingress, lane)); done.set()
    with source.guard():
        thread = Thread(target=admit); thread.start()
        assert entered.wait(2) and not done.wait(.03)
        old = source.get()
        authority.invalidate_work()
        source.install(replace(old, settings=replace(old.settings, max_content_chars=42)))
    thread.join(2)
    assert not thread.is_alive() and events[0].work.settings.max_content_chars == 42
    assert events[0].work.context.generation == authority.snapshot().generation
    ingress.retire(events[0])


def controller_lane(lane, tmp_path):
    from src.controllers.watch_controller import FakeClock, FakeScheduler, ObserverFactory, WatchController
    from src.core.watch_config import WatchConfigStore
    posted = []
    ingress = make(lane, posted.append)
    clock = FakeClock(); scheduler = FakeScheduler(clock)
    controller = WatchController(WatchConfigStore(tmp_path / "watch.json"),
        ObserverFactory(use_mock=True), clock, scheduler, managed_ingress=ingress)
    controller.add_watch(lane[3])
    controller.on_file_ready = lambda *a: pytest.fail("managed legacy callback")
    class ForbiddenPipeline:
        def handle_file_ready(self, *a): pytest.fail("managed legacy pipeline")
        def on_watch_resumed(self, *a): pytest.fail("managed legacy resume")
        def on_watch_removed(self, *a): pytest.fail("managed queue mutation")
    controller._review_first_handler = ForbiddenPipeline()
    controller._auto_apply_handler = ForbiddenPipeline()
    return controller, ingress, clock, scheduler, posted


def test_controller_capture_precedes_schedule_and_stale_cloud_cannot_dispatch(lane, tmp_path, monkeypatch):
    from src.controllers.watch_controller import FileEvent
    controller, ingress, clock, scheduler, posted = controller_lane(lane, tmp_path)
    events = []
    original_capture = lane[0].capture_work
    def observe(*args, **kwargs):
        assert scheduler.pending_count == 0
        result = original_capture(*args, **kwargs); events.append(result); return result
    monkeypatch.setattr(lane[0], "capture_work", observe)
    source = tmp_path / "synthetic.txt"; source.write_text("synthetic")
    import os
    os.utime(source, (1, 1))
    controller._simulate_file_event("watch", str(source), FileEvent.CREATED)
    assert events[0].context.mode is ProcessingMode.CLOUD
    lane[1].select_local()
    clock.advance(2); scheduler.run_pending()
    assert not posted and ingress.workers_idle
    controller.begin_close()


def test_stability_reset_keeps_exact_work_but_external_event_recaptures(lane, tmp_path):
    from src.controllers.watch_controller import FileEvent
    controller, ingress, clock, scheduler, posted = controller_lane(lane, tmp_path)
    source = tmp_path / "synthetic.txt"; source.write_text("synthetic")
    controller._simulate_file_event("watch", str(source), FileEvent.CREATED)
    entry = next(iter(controller._pending_debounce.values()))
    original = entry.admission
    clock.advance(2); scheduler.run_pending()
    assert not posted and next(iter(controller._pending_debounce.values())).admission is original
    controller._simulate_file_event("watch", str(source), FileEvent.MODIFIED)
    newer = next(iter(controller._pending_debounce.values())).admission
    assert newer is not original and newer.work is not original.work
    assert original.cancel_event.is_set() and newer.cancel_event is not original.cancel_event
    import os
    os.utime(source, (1, 1))
    clock.advance(2); scheduler.run_pending()
    assert posted[0].admission is newer and posted[0].admission.work is newer.work
    ingress.retire(posted[0]); controller.begin_close()


def test_old_observer_and_directory_temp_outside_events_never_capture(lane, tmp_path, monkeypatch):
    from src.controllers.watch_controller import FileEvent
    from types import SimpleNamespace
    controller, ingress, clock, scheduler, posted = controller_lane(lane, tmp_path)
    old = controller._get_observer("watch").handlers[lane[3].source_dir]
    monkeypatch.setattr(lane[0], "capture_work", lambda *a, **k: pytest.fail("filtered capture"))
    old.dispatch(SimpleNamespace(is_directory=True, event_type="created", src_path=str(tmp_path)))
    old.on_file_event(str(tmp_path / "part.tmp"), FileEvent.CREATED)
    old.on_file_event(str(tmp_path) + "-sibling/file.txt", FileEvent.CREATED)
    controller.pause_watch("watch"); controller.resume_watch("watch")
    old.on_file_event(str(tmp_path / "synthetic.txt"), FileEvent.CREATED)
    assert not posted and scheduler.pending_count == 0 and ingress.workers_idle
    controller.begin_close()


def test_pause_racing_capture_retires_work_without_installing_it(lane, tmp_path, monkeypatch):
    from src.controllers.watch_controller import FileEvent
    controller, ingress, clock, scheduler, posted = controller_lane(lane, tmp_path)
    entered, release = Event(), Event()
    original = lane[0].capture_work
    def blocked(*a, **k):
        work = original(*a, **k); entered.set(); assert release.wait(2); return work
    monkeypatch.setattr(lane[0], "capture_work", blocked)
    thread = Thread(target=lambda: controller._simulate_file_event(
        "watch", str(tmp_path / "synthetic.txt"), FileEvent.CREATED))
    thread.start(); assert entered.wait(2)
    controller.pause_watch("watch")
    assert not ingress.workers_idle
    release.set(); thread.join(2)
    assert not thread.is_alive() and not posted and not controller._pending_debounce
    assert ingress.workers_idle
    controller.begin_close()


def test_failed_pause_persist_keeps_observer_and_authentic_admission(lane, tmp_path, monkeypatch):
    from src.controllers.watch_controller import FileEvent
    from src.core.watch_config import WatchConfigPersistenceError, WatchStatus
    controller, ingress, clock, scheduler, posted = controller_lane(lane, tmp_path)
    controller._simulate_file_event("watch", str(tmp_path / "synthetic.txt"), FileEvent.CREATED)
    entry = next(iter(controller._pending_debounce.values()))
    observer = controller._get_observer("watch")
    def fail(*a): raise WatchConfigPersistenceError("synthetic")
    with monkeypatch.context() as patch:
        patch.setattr(controller._store, "update", fail)
        with pytest.raises(WatchConfigPersistenceError): controller.pause_watch("watch")
    assert controller._get_observer("watch") is observer
    assert controller.get_status("watch") is WatchStatus.ACTIVE
    assert ingress.is_current(entry.admission) and not entry.admission.cancel_event.is_set()
    controller.pause_watch("watch")
    assert ingress.workers_idle
    controller.begin_close()


def test_pause_invalidates_queued_delivery_without_forgetting_it(lane, tmp_path):
    from src.controllers.watch_controller import FileEvent
    import os
    controller, ingress, clock, scheduler, posted = controller_lane(lane, tmp_path)
    source = tmp_path / "synthetic.txt"; source.write_text("synthetic"); os.utime(source, (1, 1))
    controller._simulate_file_event("watch", str(source), FileEvent.CREATED)
    clock.advance(2); scheduler.run_pending()
    assert ingress.is_current(posted[0])
    controller.pause_watch("watch")
    assert not ingress.is_current(posted[0]) and ingress.owned_count == 1
    assert not controller.drain(__import__("time").monotonic() + .01)
    ingress.retire(posted[0]); controller.begin_close()
    assert controller.drain(__import__("time").monotonic() + 1)


def test_oversize_template_field_is_rejected_before_shared_capture(lane, monkeypatch):
    ingress = make(lane)
    config = replace(lane[3], template_id="x" * 129)
    monkeypatch.setattr(lane[0], "capture_work", lambda *a, **k: pytest.fail("unbounded capture"))
    assert ingress.capture(config, "incarnation", config.source_dir + "/synthetic.txt", "event") is None
    assert ingress.workers_idle


@pytest.mark.parametrize("transition", ["remove", "update"])
def test_failed_lifecycle_persist_retains_config_incarnation_and_observer(lane, tmp_path, monkeypatch, transition):
    from src.controllers.watch_controller import FileEvent, WatchControllerError
    from src.core.watch_config import WatchConfigPersistenceError, WatchStatus
    controller, ingress, clock, scheduler, posted = controller_lane(lane, tmp_path)
    if transition == "update": controller.pause_watch("watch")
    config = controller.get_config("watch")
    observer = controller._get_observer("watch")
    incarnation = controller._watches["watch"].incarnation
    event = None
    if transition == "remove":
        controller._simulate_file_event("watch", str(tmp_path / "synthetic.txt"), FileEvent.CREATED)
        event = next(iter(controller._pending_debounce.values())).admission
    def fail(*a): raise WatchConfigPersistenceError("synthetic")
    with monkeypatch.context() as patch:
        patch.setattr(controller._store, "remove" if transition == "remove" else "update", fail)
        with pytest.raises((WatchConfigPersistenceError, WatchControllerError)):
            if transition == "remove": controller.remove_watch("watch")
            else: controller.update_watch(replace(config, template_id="changed"))
    assert controller.get_config("watch") is config
    assert controller._get_observer("watch") is observer
    assert controller._watches["watch"].incarnation == incarnation
    if event is not None: assert ingress.is_current(event)
    controller.begin_close()


def test_local_failure_then_new_cloud_generation_never_recaptures_or_dispatches(lane, tmp_path, monkeypatch):
    from src.controllers.watch_controller import FileEvent
    lane[1].select_local()
    controller, ingress, clock, scheduler, posted = controller_lane(lane, tmp_path)
    source = str(tmp_path / "synthetic.txt")
    controller._simulate_file_event("watch", source, FileEvent.CREATED)
    failure = posted[0]
    assert failure.reason == "local_unavailable" and failure.snapshot.mode is ProcessingMode.LOCAL
    monkeypatch.setattr(lane[0], "capture_work", lambda *a, **k: pytest.fail("late recapture"))
    intent = lane[1].request_cloud_choice()
    assert lane[1].complete_choice(intent, persisted=True)
    clock.advance(10); scheduler.run_pending()
    assert posted == [failure] and not ingress.is_current(failure)
    ingress.retire(failure); controller.begin_close()


def test_deleted_event_cancels_only_matching_unaccepted_admission(lane, tmp_path):
    from src.controllers.watch_controller import FileEvent
    controller, ingress, clock, scheduler, posted = controller_lane(lane, tmp_path)
    for name in ("one.txt", "two.txt"):
        controller._simulate_file_event("watch", str(tmp_path / name), FileEvent.CREATED)
    entries = list(controller._pending_debounce.values())
    controller._simulate_file_event("watch", str(tmp_path / "one.txt"), FileEvent.DELETED)
    assert entries[0].admission.cancel_event.is_set()
    assert ingress.is_current(entries[1].admission) and ingress.owned_count == 1
    assert scheduler.pending_count == 1 and not posted
    controller.begin_close()


def test_failed_observer_start_retires_admission_collected_during_start(lane, tmp_path):
    from src.controllers.watch_controller import FileEvent, FakeClock, FakeScheduler, WatchController
    from src.core.watch_config import WatchConfigStore, WatchStatus
    posted = []; ingress = make(lane, posted.append)
    clock = FakeClock(); scheduler = FakeScheduler(clock)
    class Observer:
        def schedule(self, handler, *a, **k): self.handler = handler
        def start(self):
            self.handler.on_file_event(str(tmp_path / "synthetic.txt"), FileEvent.CREATED)
            raise RuntimeError("synthetic failure")
        def unschedule_all(self): pass
        def stop(self): pass
        def is_alive(self): return False
    class Factory:
        def create(self): return Observer()
    controller = WatchController(WatchConfigStore(tmp_path / "watch.json"), Factory(),
        clock, scheduler, managed_ingress=ingress)
    controller.add_watch(lane[3])
    assert controller.get_status("watch") is WatchStatus.ERROR
    assert not controller._pending_debounce and ingress.workers_idle
    assert not posted and scheduler.pending_count == 1  # bounded restart only
    controller.begin_close()


def test_old_observer_after_remove_recreate_same_id_has_zero_capture(lane, tmp_path, monkeypatch):
    from src.controllers.watch_controller import FileEvent
    controller, ingress, clock, scheduler, posted = controller_lane(lane, tmp_path)
    old = controller._get_observer("watch").handlers[lane[3].source_dir]
    controller.remove_watch("watch"); controller.add_watch(lane[3])
    monkeypatch.setattr(lane[0], "capture_work", lambda *a, **k: pytest.fail("old observer captured"))
    old.on_file_event(str(tmp_path / "synthetic.txt"), FileEvent.CREATED)
    assert not posted and not controller._pending_debounce and ingress.workers_idle
    controller.begin_close()


def test_managed_resource_pause_collects_without_legacy_resume_or_activation(lane, tmp_path):
    from src.controllers.watch_controller import FileEvent
    from src.core.watch_config import WatchStatus
    import os
    controller, ingress, clock, scheduler, posted = controller_lane(lane, tmp_path)
    observer = controller._get_observer("watch")
    controller.resource_pause("watch")
    source = tmp_path / "synthetic.txt"; source.write_text("synthetic"); os.utime(source, (1, 1))
    controller._simulate_file_event("watch", str(source), FileEvent.CREATED)
    clock.advance(2); scheduler.run_pending()
    assert controller.get_status("watch") is WatchStatus.RESOURCE_PAUSED
    assert controller._get_observer("watch") is observer
    assert posted[0].admission.watch_config.status is WatchStatus.RESOURCE_PAUSED
    controller.resume_watch("watch")  # no guard cannot activate
    assert controller.get_status("watch") is WatchStatus.RESOURCE_PAUSED
    ingress.retire(posted[0]); controller.begin_close()


def test_failure_race_preserves_snapshot_taken_before_real_capture_exception(lane, monkeypatch):
    from src.core.processing_authority import LocalProcessingUnavailable
    lane[1].select_local()
    ingress = make(lane)
    original = lane[0].capture_work
    captured_snapshot = lane[1].snapshot()
    def raced(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except LocalProcessingUnavailable:
            lane[1].invalidate_work()
            raise
    monkeypatch.setattr(lane[0], "capture_work", raced)
    failure = capture(ingress, lane)
    assert failure.snapshot == captured_snapshot
    assert not ingress.is_current(failure) and failure.reason == "local_unavailable"
    assert not ingress.post_failure(failure)
    ingress.retire(failure)


def test_internal_stability_reset_eventually_delivers_the_original_sealed_work(lane, tmp_path, monkeypatch):
    from src.controllers.watch_controller import FileEvent
    import os
    controller, ingress, clock, scheduler, posted = controller_lane(lane, tmp_path)
    source = tmp_path / "synthetic.txt"; source.write_text("synthetic")
    observed = os.stat(source)
    now = [observed.st_mtime_ns + 1]
    monkeypatch.setattr("src.controllers.watch_controller.time.time_ns", lambda: now[0])
    controller._simulate_file_event("watch", str(source), FileEvent.CREATED)
    original = next(iter(controller._pending_debounce.values())).admission
    clock.advance(2); scheduler.run_pending()
    assert not posted
    monkeypatch.setattr(lane[0], "capture_work", lambda *a, **k: pytest.fail("internal recapture"))
    now[0] += 3_000_000_000
    clock.advance(2); scheduler.run_pending()
    assert posted[0].admission is original and posted[0].admission.work is original.work
    assert posted[0].admission.cancel_event is original.cancel_event
    ingress.retire(posted[0]); controller.begin_close()


def test_saved_hk_local_watch_keeps_plain_locale_and_deferred_deadline_across_reset(lane, tmp_path, monkeypatch):
    from src.controllers.watch_controller import FileEvent
    import os
    service, authority, catalog, watch = lane
    selected = Template(id="one", name="Saved HK", pattern="{dcTitle}",
        fields=(TemplateField("dcTitle", "Title"),), output_language=OutputLanguage.ZH_HK)
    with catalog.guard():
        catalog.install(build_analysis_catalog(AppConfig(default_template_id="one"), [selected]))
    authority.select_local()
    authority.set_local_state(authority.snapshot().generation, LocalReadiness.READY,
                              engine_fingerprint="a" * 64)
    controller, ingress, clock, scheduler, posted = controller_lane(lane, tmp_path)
    try:
        source = tmp_path / "synthetic.txt"; source.write_text("synthetic")
        observed = os.stat(source)
        now = [observed.st_mtime_ns + 1]
        monkeypatch.setattr("src.controllers.watch_controller.time.time_ns", lambda: now[0])
        controller._simulate_file_event("watch", str(source), FileEvent.CREATED)
        original = next(iter(controller._pending_debounce.values())).admission
        work = original.work
        assert original.watch_config is watch and work.template == selected
        assert type(work.locale) is str and work.locale == "zh-HK"
        assert work.deadline is None and work._seal._deadline is None
        assert work._seal.deferred and not work._seal._started
        request = LocalNamingRequest("synthetic evidence", (), work.locale, "template", template=work.template)
        assert request.locale == "zh-HK"
        clock.advance(2); scheduler.run_pending()
        assert not posted and next(iter(controller._pending_debounce.values())).admission is original
        monkeypatch.setattr(service, "capture_work", lambda *a, **k: pytest.fail("internal recapture"))
        now[0] += 3_000_000_000
        clock.advance(2); scheduler.run_pending()
        assert posted[0].admission is original and posted[0].admission.work is work
        assert work.deadline is None and work._seal._deadline is None
        assert not work._seal._started and work.locale is request.locale
        assert ingress.retire(posted[0])
    finally:
        controller.begin_close()
    assert ingress.workers_idle


def test_queued_capacity_and_close_cannot_forget_unconsumed_deliveries(lane):
    posted = []; ingress = make(lane, posted.append)
    for i in range(1000):
        event = capture(ingress, lane, str(i))
        assert ingress.post_stable(event, SourceFingerprint(4, 2))
    assert ingress.owned_count == 1000 and capture(ingress, lane, "overflow") is None
    ingress.begin_close()
    assert ingress.owned_count == 1000 and not ingress.workers_idle
    for delivery in posted: assert ingress.retire(delivery)
    assert ingress.workers_idle


def test_restart_of_actually_exited_observer_cancels_its_old_admissions(lane, tmp_path):
    from src.controllers.watch_controller import FileEvent
    controller, ingress, clock, scheduler, posted = controller_lane(lane, tmp_path)
    controller._simulate_file_event("watch", str(tmp_path / "synthetic.txt"), FileEvent.CREATED)
    admission = next(iter(controller._pending_debounce.values())).admission
    observer = controller._get_observer("watch")
    observer.stop()  # actual exit without the explicit observer-error helper
    controller.start_all()
    assert controller._get_observer("watch") is not observer
    assert admission.cancel_event.is_set() and ingress.workers_idle
    assert not controller._pending_debounce and scheduler.pending_count == 0
    controller.begin_close()

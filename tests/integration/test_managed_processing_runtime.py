"""C1D integration boundary, not product readiness or managed Watch completion."""
import json
import time
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from src.core.processing_authority import (
    CloudDispatchBlocked, LocalProcessingUnavailable, LocalReadiness,
    ProcessingMode, ProcessingSuperseded,
)
from src.core.processing_identity import cloud_engine_fingerprint
from src.core.provider_profile import ProviderProfile
from src.core.provider_protocol import ProviderCapabilities
from src.models.app_config import AppConfig
from src.qml_bootstrap import build_qml_runtime


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


class Credentials:
    def __init__(self): self.calls = []
    def get(self, service, account):
        self.calls.append(("get", service, account))
        return "synthetic-key"
    def set(self, *args): self.calls.append(("set", *args)); return True
    def delete(self, *args): self.calls.append(("delete", *args)); return True


class Inference:
    def __init__(self, config): self.config = config; self.closed = False
    def shutdown(self, *, deadline):
        self.closed = True
        return SimpleNamespace(phase="CLOSED")


class Preparation:
    def __init__(self): self.closed = False
    def close(self, deadline): self.closed = True; return True


@pytest.fixture
def make_runtime(tmp_path, app):
    owned = []
    def make(**kwargs):
        defaults = dict(config_file=tmp_path / "settings.json", credential_store=Credentials(),
            usage_recorder=None, diagnostics_service=None,
            local_inference_factory=Inference, local_preparation_factory=Preparation,
            resource_controller=None)
        defaults.update(kwargs)
        runtime = build_qml_runtime(**defaults)
        owned.append(runtime)
        return runtime
    yield make
    for runtime in owned:
        assert runtime.cleanup(deadline=time.monotonic() + 2)
        runtime.assert_zero_warnings()


@pytest.mark.parametrize("intent", [
    {"schema_version": 1, "revision": 2, "mode": "local"}, {"bad": "intent"},
])
def test_saved_local_or_invalid_intent_never_reads_credentials_or_migrates(
        make_runtime, tmp_path, monkeypatch, intent):
    path = tmp_path / "settings.json"
    data = json.dumps({"schema_version": 0, "api_key": "synthetic-legacy-key", "language": "en_US"}).encode()
    path.write_bytes(data)
    (tmp_path / "processing-intent.json").write_text(json.dumps(intent))
    monkeypatch.setattr("src.config.get_credential_strict", lambda: pytest.fail("credential read"))
    monkeypatch.setattr("src.config.set_credential", lambda *_: pytest.fail("credential migration"))
    store = Credentials()
    runtime = make_runtime(credential_store=store)
    assert runtime.processing_coordinator.processingMode == "local"
    assert runtime.processing_coordinator.localReadiness == "not_ready"
    assert not store.calls
    assert path.read_bytes() == data
    with pytest.raises(LocalProcessingUnavailable):
        runtime.analysis_service.capture_work("synthetic.txt", "task",
            task_attempt_id="attempt", task_cancel_event=Event(), naming_mode="smart")


def test_explicit_missing_config_uses_its_parent_and_does_not_read_global(
        make_runtime, tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.CONFIG_FILE", tmp_path / "must-not-read.json")
    runtime = make_runtime(config_file=tmp_path / "isolated" / "settings.json")
    assert runtime.controller._config_file_path == tmp_path / "isolated" / "settings.json"
    assert runtime.processing_coordinator._store.path == tmp_path / "isolated" / "processing-intent.json"
    assert not (tmp_path / "must-not-read.json").exists()


def test_future_schema_aborts_before_any_credential_or_local_factory(
        make_runtime, tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    payload = b'{"schema_version":999,"api_key":"synthetic"}'
    path.write_bytes(payload)
    store = Credentials()
    from src.config import UnsupportedConfigVersionError
    with pytest.raises(UnsupportedConfigVersionError):
        make_runtime(credential_store=store,
            local_inference_factory=lambda _: pytest.fail("constructed before schema check"))
    assert not store.calls
    assert path.read_bytes() == payload


def profile(model="first"):
    return ProviderProfile(id="captured", provider_id="custom", base_url="https://synthetic.test/v1",
        model=model, enabled=True, needs_connection_verification=False,
        capabilities=ProviderCapabilities(text=True, json_schema=True))


def cloud_config(model="first"):
    return AppConfig(provider_profiles=[profile(model).to_safe_dict()], active_provider_id="captured")


def capture(runtime, attempt="attempt"):
    return runtime.analysis_service.capture_work("synthetic.txt", "task",
        task_attempt_id=attempt, task_cancel_event=Event(), naming_mode="smart")


def test_catalog_commit_installs_before_reentrant_coordinator_signal(make_runtime):
    runtime = make_runtime(live_config=cloud_config())
    old = capture(runtime)
    seen = []
    runtime.processing_coordinator.stateChanged.connect(lambda: seen.append(capture(runtime, "new")))
    config = cloud_config("second")
    prepared = runtime.controller._runtime_input_preparer(config)
    runtime.controller._runtime_inputs_committed(config, prepared)
    assert seen and seen[-1].profile.model == "second"
    assert seen[-1].context.engine_fingerprint == cloud_engine_fingerprint(profile("second"))
    assert not runtime.processing_coordinator.authority.is_current(old.context)
    runtime.processing_coordinator.stateChanged.disconnect()


def test_no_active_profile_unbinds_previous_cloud_engine(make_runtime):
    runtime = make_runtime(live_config=cloud_config())
    old = capture(runtime)
    config = AppConfig()
    prepared = runtime.controller._runtime_input_preparer(config)
    runtime.controller._runtime_inputs_committed(config, prepared)
    assert runtime.catalog_source.get().active_profile is None
    assert runtime.processing_coordinator.snapshot.engine_fingerprint is None
    assert not runtime.processing_coordinator.authority.is_current(old.context)
    with pytest.raises(CloudDispatchBlocked): capture(runtime)


def test_non_qt_capture_cannot_observe_mid_publication_catalog(make_runtime):
    runtime = make_runtime(live_config=cloud_config())
    source = runtime.catalog_source
    entered, release, done = Event(), Event(), Event()
    seen = []
    config = cloud_config("second")
    prepared = runtime.controller._runtime_input_preparer(config)
    install = source.install
    def blocked_install(catalog):
        entered.set()
        thread = Thread(target=lambda: (seen.append(capture(runtime)), done.set()))
        thread.start()
        # This call runs under the publication guard: the non-Qt capture waits.
        assert not done.wait(.03)
        install(catalog)
        release.set()
    source.install = blocked_install
    runtime.controller._runtime_inputs_committed(config, prepared)
    assert entered.is_set() and release.is_set()
    assert done.wait(2)
    assert seen[0].profile.model == "second"
    assert seen[0].context.engine_fingerprint == cloud_engine_fingerprint(profile("second"))


def test_explicit_none_watch_preserves_saved_watch_and_journal_bytes(make_runtime, tmp_path):
    paths = [tmp_path / name for name in (
        "watch_folders.json", "watch_review_queue.json", "watch_auto_apply.json", "rename_history.jsonl")]
    for path in paths: path.write_bytes(b'synthetic stored active watch and interrupted journal')
    runtime = make_runtime(watch_controller=None)
    assert runtime.watch_controller is None
    for path in paths: assert path.read_bytes() == b'synthetic stored active watch and interrupted journal'


def test_cleanup_timeout_keeps_all_qt_owners_until_preparation_and_local_close(make_runtime):
    class BlockedPreparation(Preparation):
        released = False
        def close(self, deadline): self.closed = True; return self.released
    class BlockedInference(Inference):
        released = False
        def shutdown(self, *, deadline):
            return SimpleNamespace(phase="CLOSED" if self.released else "CLEANUP_PENDING")
    runtime = make_runtime(live_config=cloud_config(),
        local_preparation_factory=BlockedPreparation, local_inference_factory=BlockedInference)
    owners = (runtime.root, runtime.component, runtime.engine, runtime.controller, runtime.batch_controller)
    assert runtime.cleanup(deadline=time.monotonic() + .02) is False
    assert owners == (runtime.root, runtime.component, runtime.engine, runtime.controller, runtime.batch_controller)
    with pytest.raises(ProcessingSuperseded): capture(runtime)
    runtime.local_preparation_service.released = True
    runtime.local_inference_service.released = True
    assert runtime.cleanup(deadline=time.monotonic() + 2) is True
    assert runtime.root is None


def test_default_catalog_is_exact_pin_and_fixed_os_roots(monkeypatch, tmp_path):
    from src.qml_bootstrap import build_default_local_config
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "os-data"))
    config = build_default_local_config()
    assert config.catalog.identity == "1b3ca415eff1c7c2c91b0f6e743550ac6c2e75a7e4a750bb319c7d330ba6b859"
    assert config.catalog.total_bytes == 3431786583
    assert config.catalog.purpose == "managed-local-resources-v1"
    assert config.resource_root == tmp_path / "os-data" / "Xuxia" / "local-ai" / "resources" / config.catalog.identity
    assert not config.resource_root.exists()


def test_packaging_includes_only_the_exact_inert_catalog():
    from tests.packaging.test_local_bundle_resources import collected_data
    root = Path(__file__).resolve().parents[2]
    entries = collected_data()
    catalogs = {(path.relative_to(root).as_posix(), destination)
        for path, destination in entries
        if path.is_relative_to(root / "resources/local-models") and path.suffix == ".json"}
    assert catalogs == {("resources/local-models/qwen35-4b-managed-v1.json",
        "resources/local-models")}
    assert not any(path.name == "qwen35-4b-feasibility.json" for path, _ in entries)
    assert not any(path.suffix.lower() == ".gguf" for path, _ in entries)


def test_application_config_disables_unmanaged_last_window_quit(app):
    from src.main_qml import _configure_application
    _configure_application(app)
    assert app.quitOnLastWindowClosed() is False


def test_smoke_uses_managed_default_not_legacy_probe_injection(tmp_path, app, monkeypatch):
    from src.main_qml import run_smoke_test
    monkeypatch.setattr("src.main_qml._verify_media_dependencies", lambda _: {})
    captured = {}
    class Runtime:
        root = SimpleNamespace(show=lambda: None)
        warnings = []
        def assert_zero_warnings(self): pass
        def cleanup(self, deadline=None): return True
    def builder(**kwargs): captured.update(kwargs); return Runtime()
    assert run_smoke_test(data_dir=tmp_path, runtime_builder=builder) == 0
    assert "connection_test_service" not in captured


def test_smoke_does_not_claim_success_before_owner_drain(tmp_path, app, monkeypatch):
    from src.main_qml import run_smoke_test
    monkeypatch.setattr("src.main_qml._verify_media_dependencies", lambda _: {})
    class Runtime:
        root = SimpleNamespace(show=lambda: None)
        warnings = []
        clean_calls = 0
        def assert_zero_warnings(self): pass
        def cleanup(self, deadline=None):
            self.clean_calls += 1
            return self.clean_calls > 1
        def manage_window_close(self, **kwargs): pass
    report = tmp_path / "report.json"
    runtime = Runtime()
    assert run_smoke_test(data_dir=tmp_path, report_path=report,
        runtime_builder=lambda **_: runtime) == 0
    assert runtime.clean_calls > 1
    assert json.loads(report.read_text())["status"] == "ok"


def test_module_reload_preserves_omitted_dependency_semantics(tmp_path, app):
    import importlib
    import src.qml_bootstrap as module
    original = module.build_qml_runtime
    importlib.reload(module)
    runtime = original(config_file=tmp_path / "settings.json", credential_store=Credentials(),
        usage_recorder=None, diagnostics_service=None, watch_controller=None)
    try:
        assert runtime.owns_batch and runtime.watch_controller is None
    finally:
        assert runtime.cleanup()


def test_local_factory_failure_closes_constructed_choice_writer(tmp_path, app):
    from src.core.processing_intent_store import ProcessingIntentWriter
    writers = []
    def factory(*args, **kwargs):
        writer = ProcessingIntentWriter(*args, **kwargs)
        writers.append(writer)
        return writer
    def fail(_): raise RuntimeError("synthetic factory failure")
    try:
        with pytest.raises(RuntimeError):
            build_qml_runtime(config_file=tmp_path / "settings.json", credential_store=Credentials(),
                usage_recorder=None, processing_writer_factory=factory, local_inference_factory=fail)
        assert len(writers) == 1
        assert not writers[0]._thread.is_alive()
    finally:
        for writer in writers: writer.close(timeout=.25)


def test_qml_creation_failure_drains_all_created_managed_owners(tmp_path, app):
    from src.core.processing_intent_store import ProcessingIntentWriter
    writers, services = [], []
    def writer_factory(*args, **kwargs):
        writer = ProcessingIntentWriter(*args, **kwargs); writers.append(writer); return writer
    def inference_factory(config):
        service = Inference(config); services.append(service); return service
    qml = tmp_path / "invalid.qml"
    qml.write_text("this is not valid QML")
    try:
        with pytest.raises(RuntimeError):
            build_qml_runtime(config_file=tmp_path / "settings.json", main_qml=qml,
                credential_store=Credentials(), usage_recorder=None,
                resource_controller=None,
                processing_writer_factory=writer_factory, local_inference_factory=inference_factory,
                local_preparation_factory=Preparation)
        assert services and services[0].closed
        assert writers and not writers[0]._thread.is_alive()
    finally:
        for writer in writers: writer.close(timeout=.25)


def pump(app, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert predicate()


def smart_fields():
    return {"understood": True, "language": "zh-CN", "parts": [
        {"role": "topic", "value": "项目报告", "evidence": "项目报告", "evidence_source": "text"}]}


def test_default_batch_cloud_uses_exact_admitted_profile_and_late_key_read(make_runtime, tmp_path):
    from src.core.provider_protocol import ProviderResponse
    from src.services.retry_policy import RetryExecutionResult
    calls = []
    live, store = cloud_config(), Credentials()
    def factory(profile, key, *, processing_dispatch, retry_executor):
        calls.append((profile, key, processing_dispatch, retry_executor))
        def invoke(request, *, cancellation_token):
            receipt = processing_dispatch.authority.commit_cloud_attempt(processing_dispatch.context, "fake-send")
            processing_dispatch.authority.finish_attempt(receipt)
            return RetryExecutionResult(True, ProviderResponse(fields=smart_fields()), (), None, None)
        return SimpleNamespace(invoke=invoke)
    runtime = make_runtime(live_config=live, credential_store=store,
        managed_adapter_factory=factory, analysis_content_extractor=lambda *_: ("项目报告", {}))
    assert runtime.batch_controller._managed_analyzer is runtime.analysis_service
    path = tmp_path / "source.txt"
    path.write_text("synthetic")
    work = runtime.analysis_service.capture_work(str(path), "task", task_attempt_id="attempt",
        task_cancel_event=Event(), naming_mode="smart")
    assert not store.calls and not calls
    # Mutating caller-owned config cannot alter frozen worker inputs.
    live.provider_profiles[0]["model"] = "mutated-without-commit"
    result = runtime.analysis_service.run_prepared(work)
    assert result.suggested_name == "项目报告.txt"
    assert len(store.calls) == 1 and store.calls[0][2] == "provider:captured"
    assert calls[0][0].model == "first"
    assert calls[0][2].context is work.context
    assert runtime.processing_coordinator.snapshot.committed_attempts == 0


def test_default_batch_local_uses_bounded_services_with_no_cloud_fallback(make_runtime, tmp_path):
    from src.services.local_ai.preparation_protocol import LocalPreparationResult, PreparationCoverage
    from src.services.local_ai.inference_request import LocalInferenceResult
    calls, store = [], Credentials()
    class LocalPreparation(Preparation):
        def prepare(self, source, **kwargs):
            calls.append(("prepare", kwargs))
            return LocalPreparationResult("项目报告", (), PreparationCoverage("text", sections_processed=1), (), "balanced")
    class LocalInference(Inference):
        def infer(self, request, **kwargs):
            calls.append(("infer", kwargs))
            return LocalInferenceResult(True, smart_fields(), None, "a" * 64, .1)
    runtime = make_runtime(live_config=cloud_config(), credential_store=store,
        local_preparation_factory=LocalPreparation, local_inference_factory=LocalInference,
        managed_adapter_factory=lambda *args, **kwargs: pytest.fail("cloud fallback"))
    coordinator = runtime.processing_coordinator
    coordinator.selectLocal()
    # Synthetic test-only readiness, never the default engineering constructor.
    coordinator.publish_local_state(coordinator.snapshot.generation, LocalReadiness.READY,
        engine_fingerprint="a" * 64)
    path = tmp_path / "source.txt"; path.write_text("synthetic")
    work = runtime.analysis_service.capture_work(str(path), "task", task_attempt_id="attempt",
        task_cancel_event=Event(), naming_mode="smart")
    assert runtime.analysis_service.run_prepared(work).suggested_name == "项目报告.txt"
    assert [call[0] for call in calls] == ["prepare", "infer"]
    assert calls[0][1]["deadline"] == calls[1][1]["deadline"]
    assert not store.calls


def test_managed_default_probe_uses_actual_fixed_adapter_path(make_runtime, app):
    from src.core.connection_test import ConnectionOutcome
    from src.providers.openai_compatible import UrllibJsonTransport
    from tests.providers.contracts.test_processing_dispatch import Response
    calls = []
    def opener(request, *, timeout):
        calls.append(json.loads(request.data))
        assert runtime.processing_coordinator.snapshot.committed_attempts == 1
        return Response(raw=json.dumps({"choices": [{"message": {"content": "pong"},
            "finish_reason": "stop"}]}).encode())
    transport = UrllibJsonTransport(opener=opener)
    runtime = make_runtime(connection_transport=transport)
    ctrl = runtime.controller
    completions = []
    runtime.probe_runner.completed.connect(completions.append)
    ctrl.openSession()
    ctrl.testConnectionCandidate({"id": "synthetic", "display_name": "Synthetic",
        "base_url": "https://synthetic.test/v1", "model": "model", "capabilities": {"text": True}},
        "synthetic-typed-key")
    pump(app, lambda: ctrl.connectionTestState != "testing")
    assert ctrl.connectionTestState == "success", (completions, len(calls),
        runtime.processing_coordinator.snapshot)
    assert runtime.probe_runner is ctrl._probe_runner
    assert len(calls) == 1
    assert calls[0]["messages"] == [{"role": "user", "content": "ping"}]


def test_actual_window_close_retains_live_visible_owners_then_finishes(make_runtime, app):
    from shiboken6 import isValid
    class BlockedPreparation(Preparation):
        released = False
        def close(self, deadline): return self.released
    runtime = make_runtime(live_config=cloud_config(), local_preparation_factory=BlockedPreparation)
    root, engine, settings = runtime.root, runtime.engine, runtime.controller
    root.show()
    app.processEvents()
    assert root.isVisible()
    root.close()
    assert runtime.root is root and root.isVisible()
    assert isValid(root) and isValid(engine) and isValid(settings)
    with pytest.raises(ProcessingSuperseded): capture(runtime)
    runtime.local_preparation_service.released = True
    pump(app, lambda: runtime.root is None)
    assert not isValid(root) and not isValid(engine)
    runtime.assert_zero_warnings()


def test_qml_creation_failure_retains_partial_runtime_while_batch_worker_is_blocked(tmp_path, app):
    from src.controllers.batch_workspace_controller import BatchWorkspaceController
    from src.qml_bootstrap import RuntimeConstructionPending
    from shiboken6 import isValid
    source = tmp_path / "source.txt"; source.write_text("synthetic")
    saved = BatchWorkspaceController(workspace_path=tmp_path / "batch_workspace.json", background=False)
    saved.add_files([str(source)])
    saved.close()
    entered, release = Event(), Event()
    def extractor(*_):
        entered.set()
        assert release.wait(3)
        return "项目报告", {}
    qml = tmp_path / "invalid.qml"; qml.write_text("invalid QML")
    partial = None
    try:
        with pytest.raises(RuntimeConstructionPending) as failure:
            build_qml_runtime(config_file=tmp_path / "settings.json", live_config=cloud_config(),
                credential_store=Credentials(), usage_recorder=None, main_qml=qml,
                local_inference_factory=Inference, local_preparation_factory=Preparation,
                resource_controller=None,
                analysis_content_extractor=extractor)
        partial = failure.value.runtime
        assert entered.is_set()
        assert partial.batch_controller is not None and not partial.batch_controller.workers_idle
        assert partial.catalog_source is not None
        assert partial.analysis_service is partial.batch_controller._managed_analyzer
        assert isValid(partial.engine) and isValid(partial.controller)
        assert not partial.processing_coordinator.is_open
    finally:
        release.set()
        if partial is not None: assert partial.cleanup(deadline=time.monotonic() + 2)


def test_failure_hook_permanently_closes_before_reentrant_observers(make_runtime):
    runtime = make_runtime(live_config=cloud_config())
    work = capture(runtime)
    seen = []
    def observe():
        with pytest.raises(ProcessingSuperseded): capture(runtime)
        seen.append(True)
    runtime.processing_coordinator.stateChanged.connect(observe)
    runtime.controller._runtime_admission_failed("synthetic-fixed-reason")
    assert seen and not runtime.processing_coordinator.authority.is_current(work.context)
    runtime.processing_coordinator.stateChanged.disconnect()


def test_local_metadata_save_and_view_remain_usable_without_secret_reads(make_runtime, tmp_path):
    (tmp_path / "processing-intent.json").write_text(json.dumps(
        {"schema_version": 1, "revision": 1, "mode": "local"}))
    store = Credentials()
    runtime = make_runtime(credential_store=store)
    ctrl = runtime.controller
    ctrl.openSession()
    assert all(row["credentialState"] == "unavailable" for row in ctrl.providerProfiles)
    ctrl.language = "en_US"
    ctrl.saveAll()
    assert ctrl.last_result.success
    assert runtime.catalog_source.get().settings == runtime.analysis_service._config_provider()
    assert runtime.processing_coordinator.processingMode == "local"
    assert store.calls == []


def test_key_only_commit_revokes_previous_catalog_work(make_runtime):
    runtime = make_runtime(live_config=cloud_config())
    old = capture(runtime)
    ctrl = runtime.controller
    ctrl.openSession()
    ctrl.stageProviderKey("captured", "synthetic-replacement")
    ctrl.saveAll()
    assert ctrl.last_result.success
    assert not runtime.processing_coordinator.authority.is_current(old.context)


def test_default_catalog_rejects_tampered_valid_metadata_without_cwd_fallback(tmp_path, monkeypatch):
    import src.qml_bootstrap as module
    from src.services.local_ai import production_resources
    loader = production_resources.load_production_resources
    data = json.loads((Path(module.SRC_DIR).parent / "resources/local-models/qwen35-4b-managed-v1.json").read_text())
    data["purpose"] = "otherwise-valid-but-unreviewed"
    packaged = tmp_path / "resources/local-models/qwen35-4b-managed-v1.json"
    packaged.parent.mkdir(parents=True)
    packaged.write_text(json.dumps(data))
    monkeypatch.setattr(production_resources, "load_production_resources",
        lambda: loader(bundle_root=tmp_path, user_data_root=tmp_path/'userdata'))
    from src.services.local_ai.resource_transport import ResourceError
    with pytest.raises(ResourceError, match="INVALID_PRODUCT_CATALOG"):
        module.build_default_local_config()


def test_blocked_committed_probe_cleanup_retains_owner_and_truthful_receipt(make_runtime, app):
    from src.providers.openai_compatible import UrllibJsonTransport
    from tests.providers.contracts.test_processing_dispatch import Response
    from shiboken6 import isValid
    entered, release = Event(), Event()
    def opener(request, *, timeout):
        entered.set()
        assert release.wait(3)
        return Response()
    runtime = make_runtime(connection_transport=UrllibJsonTransport(opener=opener))
    ctrl = runtime.controller
    ctrl.openSession()
    ctrl.testConnectionCandidate({"id": "synthetic", "display_name": "Synthetic",
        "base_url": "https://synthetic.test/v1", "model": "model", "capabilities": {"text": True}},
        "synthetic-typed-key")
    assert entered.wait(2)
    coordinator, root, runner = runtime.processing_coordinator, runtime.root, runtime.probe_runner
    try:
        assert coordinator.snapshot.committed_attempts == 1
        assert runtime.cleanup(deadline=time.monotonic() + .02) is False
        assert isValid(root) and isValid(ctrl) and isValid(runner)
        assert coordinator.snapshot.committed_attempts == 1
        assert not runner.workers_idle
        assert ctrl._passive_reads_allowed() is False
    finally:
        release.set()
    assert runtime.cleanup(deadline=time.monotonic() + 2)
    assert coordinator.snapshot.committed_attempts == 0


def test_blocked_choice_writer_cleanup_and_late_cloud_ack_never_reopen(make_runtime, app):
    from src.core.processing_intent_store import ProcessingIntentWriter
    entered, release = Event(), Event()
    def factory(store, authority, *, completion_callback):
        class Store:
            def save(self, intent):
                entered.set()
                assert release.wait(3)
                store.save(intent)
        return ProcessingIntentWriter(Store(), authority, completion_callback=completion_callback)
    runtime = make_runtime(live_config=cloud_config(), processing_writer_factory=factory)
    coordinator = runtime.processing_coordinator
    coordinator.selectCloud()
    assert entered.wait(2)
    try:
        assert runtime.cleanup(deadline=time.monotonic() + .02) is False
        assert runtime.root is not None
        with pytest.raises(ProcessingSuperseded): capture(runtime)
    finally:
        release.set()
    assert runtime.cleanup(deadline=time.monotonic() + 2)
    assert coordinator.pending_ack_count == 0 and not coordinator.is_open
    with pytest.raises(ProcessingSuperseded):
        coordinator.authority.capture_work(engine_fingerprint=cloud_engine_fingerprint(profile()),
            task_attempt_id="late")


def test_explicit_injected_watch_and_batch_remain_caller_owned(make_runtime):
    from src.controllers.batch_workspace_controller import BatchWorkspaceController
    from PySide6.QtCore import QObject
    from shiboken6 import isValid
    class Watch(QObject):
        closed = False
        def close(self): self.closed = True
    batch = BatchWorkspaceController(background=False)
    watch = Watch()
    runtime = make_runtime(batch_controller=batch, watch_controller=watch)
    assert runtime.watch_controller is watch and runtime.batch_controller is batch
    assert runtime.cleanup()
    assert not batch.closed
    assert isValid(watch) and not watch.closed
    batch.close()


def test_saved_unready_local_pending_batch_never_enters_cloud(tmp_path, make_runtime):
    from src.controllers.batch_workspace_controller import BatchWorkspaceController
    source = tmp_path / "source.txt"; source.write_text("synthetic")
    saved = BatchWorkspaceController(workspace_path=tmp_path / "batch_workspace.json", background=False)
    saved.add_files([str(source)])
    saved.close()
    (tmp_path / "processing-intent.json").write_text(json.dumps(
        {"schema_version": 1, "revision": 1, "mode": "local"}))
    store = Credentials()
    runtime = make_runtime(live_config=cloud_config(), credential_store=store,
        managed_adapter_factory=lambda *args, **kwargs: pytest.fail("cloud fallback"),
        analysis_content_extractor=lambda *_: pytest.fail("unready extraction"))
    task = runtime.batch_controller.task_snapshot(runtime.batch_controller.task_ids[0])
    assert task["status"] == "failed" and task["errorMessage"] == "batch.error.localUnavailable"
    assert not store.calls


def test_real_main_entry_keeps_event_loop_alive_until_actual_close_drains(make_runtime, app):
    from src.main_qml import run_application
    from PySide6.QtCore import QTimer
    class BlockedPreparation(Preparation):
        released = False
        def close(self, deadline): return self.released
    runtime = make_runtime(local_preparation_factory=BlockedPreparation)
    root = runtime.root
    seen = []
    QTimer.singleShot(10, root.close)
    QTimer.singleShot(60, lambda: seen.append(runtime.root is root and root.isVisible()))
    QTimer.singleShot(120, lambda: setattr(runtime.local_preparation_service, "released", True))
    safety = QTimer()
    safety.setSingleShot(True)
    safety.timeout.connect(lambda: (setattr(runtime.local_preparation_service, "released", True), app.quit()))
    safety.start(2000)
    try:
        assert run_application(runtime_builder=lambda: runtime) == 0
    finally:
        safety.stop()
    assert seen == [True]
    assert runtime.root is None
    runtime.assert_zero_warnings()


def test_real_isolated_smoke_reports_only_after_managed_owner_cleanup(tmp_path, app, monkeypatch):
    from src.main_qml import run_smoke_test
    monkeypatch.setattr("src.main_qml._verify_media_dependencies", lambda _: {})
    owned = []
    def builder(**kwargs):
        runtime = build_qml_runtime(**kwargs)
        owned.append(runtime)
        assert runtime.probe_runner is not None
        assert runtime.batch_controller._managed_analyzer is runtime.analysis_service
        return runtime
    report = tmp_path / "smoke-report.json"
    assert run_smoke_test(data_dir=tmp_path / "isolated", report_path=report, runtime_builder=builder) == 0
    assert len(owned) == 1 and owned[0].root is None
    assert owned[0].local_inference_service.snapshot().phase == "CLOSED"
    assert json.loads(report.read_text())["qml_warning_count"] == 0


def test_batch_close_save_failure_retains_owners_until_successful_retry(make_runtime, tmp_path):
    from shiboken6 import isValid
    entered, release = Event(), Event()
    def extractor(*_):
        entered.set()
        assert release.wait(3)
        return "项目报告", {}
    runtime = make_runtime(live_config=cloud_config(), analysis_content_extractor=extractor)
    batch = runtime.batch_controller
    source = tmp_path / "source.txt"
    source.write_text("synthetic")
    batch.add_files([str(source)])
    assert entered.wait(2)
    save = batch._save_workspace
    def fail_save(*_):
        raise OSError("synthetic workspace save failure")
    batch._save_workspace = fail_save
    root, engine, controller = runtime.root, runtime.engine, runtime.controller
    try:
        assert runtime.cleanup(deadline=time.monotonic() + .02) is False
        assert runtime.root is root and isValid(root) and isValid(engine) and isValid(controller)
        assert not runtime.processing_coordinator.is_open
        release.set()
        # A finished worker does not make the failed owner close successful.
        assert runtime.cleanup(deadline=time.monotonic() + .02) is False
        assert runtime.root is root
    finally:
        release.set()
        batch._save_workspace = save
        assert runtime.cleanup(deadline=time.monotonic() + 2)
    assert batch.task_snapshot(batch.task_ids[0])["status"] == "cancelled"


def test_construction_close_save_failure_returns_retained_partial_runtime(tmp_path, app, monkeypatch):
    from src.controllers.batch_workspace_controller import BatchWorkspaceController
    from src.qml_bootstrap import QmlRuntime, RuntimeConstructionPending
    from shiboken6 import isValid
    source = tmp_path / "source.txt"
    source.write_text("synthetic")
    saved = BatchWorkspaceController(workspace_path=tmp_path / "batch_workspace.json", background=False)
    saved.add_files([str(source)])
    saved.close()
    entered, release = Event(), Event()
    def extractor(*_):
        entered.set()
        assert release.wait(3)
        return "项目报告", {}
    original_close = BatchWorkspaceController.close
    original_save = BatchWorkspaceController._save_workspace
    def fail_save(*_):
        raise OSError("synthetic workspace save failure")
    def close_with_save_failure(batch):
        batch._save_workspace = fail_save
        return original_close(batch)
    monkeypatch.setattr(BatchWorkspaceController, "close", close_with_save_failure)
    retained = []
    original_cleanup = QmlRuntime.cleanup
    def tracked_cleanup(runtime, deadline=None):
        if not retained:
            retained.append(runtime)
        return original_cleanup(runtime, deadline=deadline)
    monkeypatch.setattr(QmlRuntime, "cleanup", tracked_cleanup)
    qml = tmp_path / "invalid.qml"
    qml.write_text("invalid QML")
    partial = None
    try:
        with pytest.raises(RuntimeConstructionPending) as failure:
            build_qml_runtime(config_file=tmp_path / "settings.json", live_config=cloud_config(),
                credential_store=Credentials(), usage_recorder=None, main_qml=qml,
                local_inference_factory=Inference, local_preparation_factory=Preparation,
                resource_controller=None,
                analysis_content_extractor=extractor)
        partial = failure.value.runtime
        assert entered.is_set() and isValid(partial.engine) and isValid(partial.controller)
        assert partial.root is None and not partial.processing_coordinator.is_open
    finally:
        release.set()
        monkeypatch.setattr(BatchWorkspaceController, "close", original_close)
        for runtime in retained:
            runtime.batch_controller._save_workspace = original_save.__get__(runtime.batch_controller)
            assert runtime.cleanup(deadline=time.monotonic() + 2)

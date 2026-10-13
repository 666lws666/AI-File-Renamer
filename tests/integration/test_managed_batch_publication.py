"""Real Qt publication and authentic authority/work; no product/model Gate claim."""
from dataclasses import replace
from threading import Event, Thread, get_ident
import copy
import json
import time
from types import SimpleNamespace
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QEvent, QThread
from shiboken6 import isValid

import src.controllers.batch_workspace_controller as batch
from src.core.analysis_catalog import AnalysisCatalogSource, build_analysis_catalog
from src.core.batch_analysis import BatchAnalysisService
from src.core.naming_fields import NamingFields
from src.core.processing_authority import ProcessingAuthority, ProcessingMode, LocalReadiness
from src.core.processing_analysis import cloud_engine_fingerprint
from src.core.provider_profile import ProviderProfile
from src.core.provider_protocol import ProviderCapabilities, ProviderResponse
from src.core.template_model import Template, TemplateField
from src.models.app_config import AppConfig
from src.services.local_ai.inference_request import LocalInferenceResult
from src.services.local_ai.preparation_protocol import LocalPreparationResult, PreparationCoverage
from src.services.retry_policy import RetryExecutionResult


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    assert isinstance(instance, QApplication)
    return instance


_UNDRAINED_TEST_CONTROLLERS = []


def _teardown_test_controllers(app, controllers, timeout=5.):
    """Retain Qt targets until real emission idle, then destroy on their owner."""
    live = [controller for controller in controllers if isValid(controller)]
    assert all(QThread.currentThread() == controller.thread() for controller in live)
    for controller in live:
        controller.close()  # Requests cancellation only; not proof of drain.
    until = time.monotonic() + timeout
    while True:
        app.processEvents()
        if all(controller.workers_idle for controller in live):
            break
        assert time.monotonic() < until, "unfinished completion callbacks at bounded test teardown"
        time.sleep(.005)
    # Emission has returned for every runner; now drain its queued delivery while
    # all targets remain strongly held. No worker can subsequently emit to them.
    app.processEvents()
    for controller in live:
        controller._prune_workers()
        controller.deleteLater()
    for controller in live:
        QCoreApplication.sendPostedEvents(controller, QEvent.Type.DeferredDelete)
    assert all(not isValid(controller) for controller in live), "Qt test targets were not destroyed"


@pytest.fixture(autouse=True)
def retained_test_controllers(app, monkeypatch):
    # Covers every constructor in this module, including temporary restore and
    # legacy fixtures, not just the controller returned by environment().
    controllers = []
    constructor = batch.BatchWorkspaceController
    def retained(*args, **kwargs):
        controller = constructor(*args, **kwargs)
        controllers.append(controller)
        return controller
    monkeypatch.setattr(batch, "BatchWorkspaceController", retained)
    yield
    try:
        _teardown_test_controllers(app, _UNDRAINED_TEST_CONTROLLERS + controllers)
    except BaseException:
        # A failed timeout is a test failure, not permission to drop a live Qt
        # callback target. Keep refs so a later teardown can safely finish it.
        _UNDRAINED_TEST_CONTROLLERS.extend(controllers)
        raise
    else:
        _UNDRAINED_TEST_CONTROLLERS.clear()


def pump(app, predicate, timeout=3):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        app.processEvents()
        if predicate():
            return
        time.sleep(.005)
    assert predicate(), "Qt completion did not arrive"


def wait_workers_without_qt_delivery(controller):
    until = time.monotonic() + 3
    while not controller.workers_idle and time.monotonic() < until:
        time.sleep(.005)
    assert controller.workers_idle


def environment(tmp_path, app, *, background=True, ready=True, limit=1000, restore=False, cloud=False):
    authority = ProcessingAuthority(initial_mode=ProcessingMode.CLOUD if cloud else ProcessingMode.LOCAL)
    if ready and not cloud:
        authority.set_local_state(authority.snapshot().generation, LocalReadiness.READY, engine_fingerprint="a" * 64)
    config = AppConfig(default_template_id="one", api_key="synthetic-secret")
    if cloud:
        profile = ProviderProfile(id="active", model="synthetic", base_url="https://example.invalid",
            needs_connection_verification=False, capabilities=ProviderCapabilities(text=True, json_schema=True))
        config.provider_profiles = [profile.to_safe_dict()]
        config.active_provider_id = profile.id
        authority.bind_cloud_engine(cloud_engine_fingerprint(profile))
    template = Template(id="one", name="Synthetic", pattern="{dcTitle}", fields=(TemplateField("dcTitle", "Title"),))
    source = AnalysisCatalogSource(build_analysis_catalog(config, [template]))
    calls, captured, execution_threads = [], [], []
    hooks = SimpleNamespace(prepare=lambda: None, infer=lambda: None)
    def prepare(path, **kwargs):
        execution_threads.append(get_ident())
        calls.append(("prepare", kwargs))
        hooks.prepare()
        return LocalPreparationResult("项目报告", (), PreparationCoverage("text", sections_processed=1), (), kwargs["quality_mode"])
    def infer(request, **kwargs):
        calls.append(("infer", request, kwargs))
        hooks.infer()
        return LocalInferenceResult(True, NamingFields(dcTitle="项目报告"), None, "b" * 64, .1)
    def forbidden(*args, **kwargs):
        pytest.fail("cloud/credential boundary touched")
    def extract(path, max_chars):
        execution_threads.append(get_ident())
        calls.append(("extract", max_chars))
        hooks.prepare()
        return "项目报告", {"sections_processed": 1}
    def credential(profile):
        calls.append(("credential", profile))
        return "synthetic-only"
    def adapter(profile, credential, *, processing_dispatch, retry_executor):
        calls.append(("factory", profile))
        def invoke(request, *, cancellation_token):
            receipt = authority.commit_cloud_attempt(processing_dispatch.context, "synthetic-send")
            calls.append(("invoke", request))
            try:
                hooks.infer()
            finally:
                authority.finish_attempt(receipt)
            return RetryExecutionResult(True, ProviderResponse(fields={"dcTitle": "项目报告"}), (), None, None)
        return SimpleNamespace(invoke=invoke)
    service = BatchAnalysisService(profile_provider=lambda: source.get().active_profile,
        credential_provider=credential if cloud else forbidden, config_provider=lambda: source.get().settings,
        template_provider=lambda ident: source.get().template(ident), capture_guard=source.guard,
        processing_authority=authority, local_preparation_service=SimpleNamespace(prepare=prepare),
        local_inference_service=SimpleNamespace(infer=infer), managed_adapter_factory=adapter if cloud else forbidden,
        **({"content_extractor": extract} if cloud else {}))
    capture = service.capture_work
    def record_capture(*args, **kwargs):
        result = capture(*args, **kwargs)
        captured.append((get_ident(), result, kwargs))
        return result
    service.capture_work = record_capture
    path = tmp_path / "synthetic.txt"
    path.write_text("synthetic", encoding="utf-8")
    workspace = tmp_path / "workspace.json"
    controller = batch.BatchWorkspaceController(background=background, max_workers=1,
        pending_work_limit=limit, workspace_path=workspace, history_path=tmp_path / "history.json")
    controller.configure_templates([dict(id="one", name="Synthetic", outputLanguage="zh")], "one")
    if restore:
        controller.add_files([str(path)])
        controller.close()
        controller = batch.BatchWorkspaceController(background=background, max_workers=1,
            pending_work_limit=limit, workspace_path=workspace, history_path=tmp_path / "history.json")
        assert controller.task_snapshot(controller.task_ids[0])["status"] == "pending"
        assert not captured
    assert hasattr(controller, "set_managed_analyzer"), "explicit managed route missing"
    controller.set_managed_analyzer(service, authority)
    return SimpleNamespace(controller=controller, authority=authority, service=service,
        config=config, source=source, template=template, path=path, calls=calls,
        captured=captured, hooks=hooks, execution_threads=execution_threads)


def import_one(env):
    env.controller.add_files([str(env.path)])
    return env.controller.task_ids[0]


def test_qt_capture_worker_execution_and_final_publication_are_separate(app, tmp_path):
    env = environment(tmp_path, app)
    entered, release = Event(), Event()
    env.hooks.prepare = lambda: (entered.set(), release.wait(3))
    updates = []
    env.controller.tasksChanged.connect(lambda: updates.append(get_ident()))
    task_id = import_one(env)
    try:
        assert entered.wait(2)
        thread, work, options = env.captured[0]
        assert thread == get_ident() and options["defer_execution_deadline"] is True
        assert work.context.task_cancel_event is env.controller._cancellation_events[task_id]
        env.config.max_content_chars = 99
        env.source.install(build_analysis_catalog(env.config, [replace(env.template, pattern="prefix-{dcTitle}")]))
        assert work.settings.max_content_chars == 4000 and work.template.pattern == "{dcTitle}"
        release.set()
        pump(app, lambda: env.controller.task_snapshot(task_id)["status"] == "review_pending")
        assert env.controller.task_snapshot(task_id)["suggestedName"] == "项目报告.txt"
        assert env.execution_threads[0] != get_ident()
        assert set(updates) == {get_ident()}
        assert env.controller.workers_idle and env.controller.pending_worker_count == 0
    finally:
        release.set()
        env.controller.close()


@pytest.mark.parametrize("failure", [False, True])
def test_changed_generation_fences_success_and_failure_without_readmission(app, tmp_path, failure):
    env = environment(tmp_path, app)
    entered, release = Event(), Event()
    def stalled():
        entered.set()
        assert release.wait(3)
        if failure:
            raise RuntimeError("synthetic-secret " + str(env.path))
    env.hooks.infer = stalled
    task_id = import_one(env)
    try:
        assert entered.wait(2)
        env.authority.select_local()
        release.set()
        pump(app, lambda: env.controller.task_snapshot(task_id)["status"] == "cancelled")
        task = env.controller.task_snapshot(task_id)
        assert task["suggestedName"] == "" and task["errorMessage"] == "batch.error.processingChanged"
        assert len(env.captured) == 1 and len(env.calls) == 2
        assert "synthetic-secret" not in json.dumps(task)
    finally:
        release.set()
        env.controller.close()


@pytest.mark.parametrize("action", ["cancelTask", "clearWorkspace", "close"])
def test_cancel_clear_close_reject_late_completion_and_report_true_runner_exit(app, tmp_path, action):
    env = environment(tmp_path, app)
    entered, release = Event(), Event()
    env.hooks.infer = lambda: (entered.set(), release.wait(3))
    task_id = import_one(env)
    try:
        assert entered.wait(2)
        getattr(env.controller, action)(*([task_id] if action == "cancelTask" else []))
        assert not env.controller.workers_idle and env.controller.pending_worker_count == 1
        if action == "close":
            assert env.controller.closed
            assert env.controller.task_snapshot(task_id)["status"] == "cancelled"
            before = env.controller.task_ids
            env.controller.add_files([str(env.path)])
            assert env.controller.task_ids == before
        release.set()
        pump(app, lambda: env.controller.workers_idle)
        app.processEvents()
        if action == "clearWorkspace":
            assert not env.controller.task_ids
        else:
            assert env.controller.task_snapshot(task_id)["status"] == "cancelled"
    finally:
        release.set()
        env.controller.close()


@pytest.mark.parametrize("mutation", ["copy", "foreign", "attempt", "context", "outcome", "generation", "session"])
def test_final_envelope_identity_and_currentness_fence(app, tmp_path, mutation):
    env = environment(tmp_path, app, background=False)
    task_id = import_one(env)
    wait_workers_without_qt_delivery(env.controller)
    work = env.captured[0][1]
    # Real run already returned its authentic outcome; queued Qt delivery not yet processed.
    coverage = PreparationCoverage("text", sections_processed=1)
    from src.core.processing_analysis import AnalysisOutcome
    from src.core.degradation import ContentKind
    value = AnalysisOutcome("injected.txt", work.context, "balanced", ContentKind.TEXT, "b" * 64, coverage, ())
    completion = batch._ManagedCompletion(task_id, work.task_attempt_id, work, work.context, value, "")
    if mutation == "copy":
        completion = replace(completion, work=copy.copy(work))
    elif mutation == "foreign":
        other = env.service.capture_work(str(env.path), task_id, task_attempt_id="foreign", task_cancel_event=Event())
        completion = replace(completion, work=other)
    elif mutation == "attempt":
        completion = replace(completion, attempt_id="other")
    elif mutation == "context":
        completion = replace(completion, context=replace(work.context))
    elif mutation == "outcome":
        completion = replace(completion, outcome=replace(value, context=replace(work.context)))
    elif mutation == "session":
        env.controller._processing_authority = ProcessingAuthority(initial_mode=ProcessingMode.LOCAL)
    else:
        env.authority.select_local()
    env.controller._accept_managed_completion(completion)
    assert env.controller.task_snapshot(task_id)["suggestedName"] != "injected.txt"
    app.processEvents()
    assert env.controller.task_snapshot(task_id)["suggestedName"] != "injected.txt"
    env.controller.close()


def test_terminal_ownership_removed_before_reentrant_retry_and_duplicate_delivery(app, tmp_path):
    env = environment(tmp_path, app, background=False)
    task_id = import_one(env)
    wait_workers_without_qt_delivery(env.controller)
    old = env.captured[0][1]
    retried = []
    def on_change():
        if env.controller.task_snapshot(task_id)["status"] == "review_pending" and not retried:
            assert task_id not in env.controller._analysis_attempts
            assert task_id not in env.controller._analysis_work
            retried.append(True)
            env.controller.retryTask(task_id)
    env.controller.tasksChanged.connect(on_change)
    app.processEvents()
    assert len(env.captured) == 2
    new = env.captured[1][1]
    assert new is not old and not new.context.task_cancel_event.is_set()
    assert env.controller._analysis_work.get(task_id) is new
    pump(app, lambda: env.controller.task_snapshot(task_id)["status"] == "review_pending")
    env.controller.close()


def test_unready_admission_is_safe_no_io_and_restore_waits_for_install(app, tmp_path):
    env = environment(tmp_path, app, ready=False, restore=True)
    task_id = env.controller.task_ids[0]
    task = env.controller.task_snapshot(task_id)
    assert task["status"] == "failed" and task["errorMessage"] == "batch.error.localUnavailable"
    assert not env.calls and not env.captured
    env.controller.close()


def test_off_thread_managed_mutation_rejects_before_any_changes(app, tmp_path):
    env = environment(tmp_path, app, background=False)
    failures = []
    def wrong_thread():
        try:
            env.controller.add_files([str(env.path)])
        except RuntimeError as error:
            failures.append(str(error))
    thread = Thread(target=wrong_thread)
    thread.start()
    thread.join(2)
    assert failures == ["Managed Batch requires its owning Qt thread"]
    assert not env.controller.task_ids and not env.captured
    env.controller.close()


def test_finite_admission_cap_reports_import_overflow_and_retains_no_hidden_queue(app, tmp_path):
    env = environment(tmp_path, app, limit=2)
    entered, release = Event(), Event()
    env.hooks.prepare = lambda: (entered.set(), release.wait(3))
    paths = [env.path]
    for i in range(3):
        path = tmp_path / f"synthetic-{i}.txt"
        path.write_text("synthetic", encoding="utf-8")
        paths.append(path)
    overflow = []
    env.controller.importOverflow.connect(overflow.append)
    try:
        env.controller.add_files([str(path) for path in paths])
        assert entered.wait(2)
        assert env.controller.totalCount == 2 and len(env.captured) == 2
        assert env.controller.pending_worker_count == 2
        assert overflow == [2] and env.controller.lastImportError == "batch.error.queueFull"
        env.controller.close()
        assert not env.controller.workers_idle
        release.set()
        pump(app, lambda: env.controller.workers_idle)
        assert all(env.controller.task_snapshot(tid)["status"] == "cancelled" for tid in env.controller.task_ids)
    finally:
        release.set()
        env.controller.close()


def test_accepted_applied_and_undo_history_survive_later_mode_change(app, tmp_path):
    env = environment(tmp_path, app, background=False)
    task_id = import_one(env)
    pump(app, lambda: env.controller.task_snapshot(task_id)["status"] == "review_pending")
    env.authority.select_local()
    assert env.controller.task_snapshot(task_id)["status"] == "review_pending"
    env.controller.applyTask(task_id)
    assert env.controller.task_snapshot(task_id)["status"] == "applied"
    env.authority.select_local()
    assert env.controller.task_snapshot(task_id)["status"] == "applied"
    env.controller.undoTask(task_id)
    assert env.controller.task_snapshot(task_id)["status"] == "undone"
    env.authority.select_local()
    assert env.controller.task_snapshot(task_id)["status"] == "undone"
    assert env.path.exists()
    env.controller.close()


@pytest.mark.parametrize("action", ["cancelTask", "ignoreTask", "stopPending", "clearWorkspace"])
def test_reentrant_cancellation_does_not_steal_retry_ownership(app, tmp_path, action):
    env = environment(tmp_path, app, background=False)
    task_id = import_one(env)
    old = env.captured[0][1]
    retried = []
    def retry():
        current = env.controller._find_task(task_id)
        if not retried and current is not None and current["status"] in {"cancelled", "ignored"}:
            retried.append(True)
            env.controller.retryTask(task_id)
    env.controller.tasksChanged.connect(retry)
    getattr(env.controller, action)(*([task_id] if action in {"cancelTask", "ignoreTask"} else []))
    assert old.context.task_cancel_event.is_set()
    if retried:
        new = env.captured[1][1]
        assert env.controller._analysis_work.get(task_id) is new
        assert env.controller._cancellation_events.get(task_id) is new.context.task_cancel_event
        assert not new.context.task_cancel_event.is_set()
        pump(app, lambda: env.controller.task_snapshot(task_id)["status"] == "review_pending")
    else:
        app.processEvents()
        assert not env.controller.task_ids
    env.controller.close()


@pytest.mark.parametrize("method,args", [("setNamingMode", ("smart",)), ("setNamingLanguage", ("en",)),
    ("set_search", ("new",)), ("set_filter", ("failed",)), ("setTargetDirectory", ("",))])
def test_off_thread_managed_choices_reject_without_mutation(app, tmp_path, method, args):
    env = environment(tmp_path, app, background=False)
    failures = []
    before = (env.controller.namingMode, env.controller.namingLanguage, env.controller.searchText,
              env.controller.statusFilter, env.controller.targetDirectory)
    def wrong_thread():
        try:
            getattr(env.controller, method)(*args)
        except RuntimeError:
            failures.append(True)
    runner = Thread(target=wrong_thread)
    runner.start()
    runner.join(2)
    assert failures == [True]
    assert before == (env.controller.namingMode, env.controller.namingLanguage, env.controller.searchText,
                      env.controller.statusFilter, env.controller.targetDirectory)
    env.controller.close()


def test_three_locales_have_identical_fixed_managed_error_keys():
    required = {"processingChanged", "localUnavailable", "cloudBlocked", "analysisFailed", "localFailed",
                "cloudFailed", "invalidOutcome", "queueFull"}
    root = Path(__file__).resolve().parents[2] / "src/utils/i18n/locales"
    keys = []
    for language in ("zh_CN", "zh_HK", "en_US"):
        values = json.loads((root / (language + ".json")).read_text(encoding="utf-8"))
        present = {key.removeprefix("batch.error.") for key in values if key.startswith("batch.error.")}
        assert required <= present
        assert all(type(values["batch.error." + name]) is str and values["batch.error." + name] for name in required)
        keys.append(present)
    assert keys[0] == keys[1] == keys[2]


@pytest.mark.parametrize("failure", [False, True])
def test_local_choice_cancels_inflight_and_queued_cloud_without_new_dispatch(app, tmp_path, failure):
    env = environment(tmp_path, app, cloud=True)
    entered, release = Event(), Event()
    def stalled():
        entered.set()
        assert release.wait(3)
        if failure:
            raise RuntimeError("synthetic-secret " + str(env.path))
    env.hooks.infer = stalled
    second = tmp_path / "queued.txt"
    second.write_text("synthetic", encoding="utf-8")
    env.controller.add_files([str(env.path), str(second)])
    try:
        assert entered.wait(2) and len(env.captured) == 2
        env.authority.select_local()
        release.set()
        pump(app, lambda: all(env.controller.task_snapshot(tid)["status"] == "cancelled" for tid in env.controller.task_ids))
        assert [call[0] for call in env.calls] == ["extract", "credential", "factory", "invoke"]
        assert len(env.captured) == 2
        assert all(env.controller.task_snapshot(tid)["errorMessage"] == "batch.error.processingChanged" for tid in env.controller.task_ids)
    finally:
        release.set()
        env.controller.close()


def test_cloud_catalog_profile_mutation_after_capture_keeps_old_request(app, tmp_path):
    env = environment(tmp_path, app, cloud=True)
    entered, release = Event(), Event()
    env.hooks.prepare = lambda: (entered.set(), release.wait(3))
    task_id = import_one(env)
    try:
        assert entered.wait(2)
        work = env.captured[0][1]
        env.config.provider_profiles[0]["model"] = "new-model"
        env.source.install(build_analysis_catalog(env.config, [replace(env.template, pattern="new-{dcTitle}")]))
        release.set()
        pump(app, lambda: env.controller.task_snapshot(task_id)["status"] == "review_pending")
        assert work.profile.model == "synthetic"
        assert env.calls[-1][1].model == "synthetic"
        assert env.controller.task_snapshot(task_id)["suggestedName"] == "项目报告.txt"
    finally:
        release.set()
        env.controller.close()


def test_source_publication_capture_interleaving_never_combines_old_catalog_new_generation(app, tmp_path):
    env = environment(tmp_path, app, background=False)
    old = env.service.capture_work(str(env.path), "old", task_attempt_id="old", task_cancel_event=Event())
    entered, begin, captured = Event(), Event(), []
    def capture_concurrently():
        entered.set()
        assert begin.wait(2)
        captured.append(env.service.capture_work(str(env.path), "new", task_attempt_id="new", task_cancel_event=Event()))
    thread = Thread(target=capture_concurrently)
    with env.source.guard():
        thread.start()
        assert entered.wait(2)
        env.authority.select_local()
        begin.set()
        env.config.max_content_chars = 42
        env.source.install(build_analysis_catalog(env.config, [replace(env.template, pattern="new-{dcTitle}")]))
        env.authority.set_local_state(env.authority.snapshot().generation, LocalReadiness.READY, engine_fingerprint="c" * 64)
        assert env.source.get().settings.max_content_chars == 42
        assert not captured
    # The caller releases the shared guard BEFORE any public notification/I/O.
    notified = []
    def public_notification():
        other = Thread(target=lambda: notified.append(env.source.get()))
        other.start()
        other.join(2)
        assert not other.is_alive()
    public_notification()
    thread.join(2)
    assert len(captured) == 1 and notified
    new = captured[0]
    assert old.settings.max_content_chars == 4000 and old.template.pattern == "{dcTitle}"
    assert new.settings.max_content_chars == 42 and new.template.pattern == "new-{dcTitle}"
    assert new.context.generation > old.context.generation and new.context.engine_fingerprint == "c" * 64
    env.controller.close()


def test_managed_execution_is_off_qt_even_when_legacy_sync_option_was_requested(app, tmp_path):
    env = environment(tmp_path, app, background=False)
    task_id = import_one(env)
    try:
        pump(app, lambda: env.controller.task_snapshot(task_id)["status"] == "review_pending")
        assert env.execution_threads and all(thread != get_ident() for thread in env.execution_threads)
    finally:
        env.controller.close()


def test_generation_change_during_filename_validation_is_fenced_at_mutation(app, tmp_path, monkeypatch):
    env = environment(tmp_path, app, background=False)
    task_id = import_one(env)
    wait_workers_without_qt_delivery(env.controller)
    original = env.controller._validate_suggested_name
    def changed(task, value):
        env.authority.select_local()
        return original(task, value)
    monkeypatch.setattr(env.controller, "_validate_suggested_name", changed)
    try:
        pump(app, lambda: env.controller.task_snapshot(task_id)["status"] != "analyzing")
        task = env.controller.task_snapshot(task_id)
        assert task["status"] == "cancelled"
        assert task["suggestedName"] == "" and task["errorMessage"] == "batch.error.processingChanged"
    finally:
        env.controller.close()


def test_explicit_legacy_reinstallation_preserves_existing_inflight_attempt(app, tmp_path):
    entered, release = Event(), Event()
    def first(path, task_id):
        entered.set()
        assert release.wait(3)
        return "first.txt"
    path = tmp_path / "synthetic.txt"
    path.write_text("synthetic", encoding="utf-8")
    controller = batch.BatchWorkspaceController(analyzer=first, max_workers=1)
    try:
        controller.add_files([str(path)])
        task_id = controller.task_ids[0]
        assert entered.wait(2)
        attempt = controller._analysis_attempts[task_id]
        controller.set_analyzer(lambda path, task_id: "second.txt")
        assert controller._analysis_attempts.get(task_id) == attempt
        release.set()
        pump(app, lambda: controller.task_snapshot(task_id)["status"] == "review_pending")
        assert controller.task_snapshot(task_id)["suggestedName"] == "first.txt"
    finally:
        release.set()
        controller.close()


def test_current_local_failure_uses_fixed_error_without_legacy_or_cloud_fallback(app, tmp_path):
    env = environment(tmp_path, app)
    def broken():
        raise RuntimeError("synthetic-secret " + str(env.path))
    env.hooks.prepare = broken
    env.controller._analyzer = lambda *args, **kwargs: pytest.fail("legacy fallback invoked")
    task_id = import_one(env)
    try:
        pump(app, lambda: env.controller.task_snapshot(task_id)["status"] == "failed")
        task = env.controller.task_snapshot(task_id)
        assert task["errorMessage"] == "batch.error.localFailed"
        assert str(env.path) not in task["errorMessage"] and "synthetic-secret" not in task["errorMessage"]
        assert [call[0] for call in env.calls] == ["prepare"]
        assert len(env.captured) == 1
    finally:
        env.controller.close()


def test_stale_success_does_not_touch_new_retry_work(app, tmp_path):
    env = environment(tmp_path, app, background=False)
    task_id = import_one(env)
    wait_workers_without_qt_delivery(env.controller)
    old = env.captured[0][1]
    env.controller.cancelTask(task_id)
    env.controller.retryTask(task_id)
    new = env.captured[1][1]
    assert new is not old
    # The first queued success is delivered before this retry's queued completion.
    app.processEvents()
    current = env.controller._analysis_work.get(task_id)
    if current is not None:
        assert current is new
        assert env.controller._cancellation_events.get(task_id) is new.context.task_cancel_event
    pump(app, lambda: env.controller.task_snapshot(task_id)["status"] == "review_pending")
    assert not new.context.task_cancel_event.is_set()
    env.controller.close()


@pytest.mark.parametrize("field,value", [("work", None), ("outcome", object()), ("failure", ["synthetic-secret"])])
def test_malformed_private_completion_cannot_publish_or_raise_raw_errors(app, tmp_path, field, value):
    env = environment(tmp_path, app, background=False)
    task_id = import_one(env)
    wait_workers_without_qt_delivery(env.controller)
    work = env.captured[0][1]
    completion = batch._ManagedCompletion("absent" if field == "work" else task_id,
        work.task_attempt_id, work, work.context, None, "batch.error.localFailed")
    env.controller._accept_managed_completion(replace(completion, **{field: value}))
    task = env.controller.task_snapshot(task_id)
    assert task["suggestedName"] == "" and "synthetic-secret" not in task["errorMessage"]
    env.controller.close()


def test_cancelled_still_running_work_occupies_finite_admission_capacity(app, tmp_path):
    env = environment(tmp_path, app, limit=1)
    entered, release = Event(), Event()
    env.hooks.prepare = lambda: (entered.set(), release.wait(3))
    task_id = import_one(env)
    extra = tmp_path / "extra.txt"
    extra.write_text("synthetic", encoding="utf-8")
    overflow = []
    env.controller.importOverflow.connect(overflow.append)
    try:
        assert entered.wait(2)
        env.controller.cancelTask(task_id)
        env.controller.add_files([str(extra)])
        assert overflow == [1] and len(env.captured) == 1
        assert env.controller.totalCount == env.controller.pending_worker_count == 1
        assert env.controller.lastImportError == "batch.error.queueFull"
        release.set()
        pump(app, lambda: env.controller.workers_idle)
    finally:
        release.set()
        env.controller.close()


def test_controller_public_task_notifications_are_outside_catalog_guard(app, tmp_path):
    env = environment(tmp_path, app, background=False)
    observed = []
    def notified():
        reader = Thread(target=lambda: observed.append(env.source.get()))
        reader.start()
        reader.join(2)
        assert not reader.is_alive(), "public notification ran under catalog guard"
    env.controller.tasksChanged.connect(notified)
    task_id = import_one(env)
    try:
        pump(app, lambda: env.controller.task_snapshot(task_id)["status"] == "review_pending")
        assert len(observed) >= 3
    finally:
        env.controller.close()


def test_repeated_terminal_delivery_never_changes_already_accepted_row(app, tmp_path):
    from src.core.processing_analysis import AnalysisOutcome
    from src.core.degradation import ContentKind
    env = environment(tmp_path, app)
    task_id = import_one(env)
    try:
        pump(app, lambda: env.controller.task_snapshot(task_id)["status"] == "review_pending")
        work = env.captured[0][1]
        original = env.controller.task_snapshot(task_id)
        value = AnalysisOutcome("replayed.txt", work.context, "balanced", ContentKind.TEXT,
            "b" * 64, PreparationCoverage("text", sections_processed=1), ())
        completion = batch._ManagedCompletion(task_id, work.task_attempt_id, work, work.context, value, "")
        env.controller._accept_managed_completion(completion)
        env.controller._accept_managed_completion(completion)
        env.authority.select_local()
        env.controller._accept_managed_completion(replace(completion, outcome=None, failure="batch.error.localFailed"))
        assert env.controller.task_snapshot(task_id) == original
    finally:
        env.controller.close()


@pytest.mark.parametrize("case,cloud", [("partial", False), ("partial", True),
    ("video", False), ("no_text", False), ("metadata", False), ("combined", False)])
def test_safe_coverage_warnings_remain_reviewable_and_survive_reload(app, tmp_path, case, cloud):
    from src.core.processing_analysis import CloudAnalysisCoverage
    from src.core.degradation import ContentKind
    env = environment(tmp_path, app, cloud=cloud)
    cls = CloudAnalysisCoverage if cloud else PreparationCoverage
    facts = {
        "partial": (cls("text", sections_processed=1, sections_total=2,
                        text_truncated=True, text_limit_reason="character_limit"),
                    ("text_character_limit",), "partialRead"),
        "video": (cls("video", text_source="none", video_duration_seconds=10.,
                        video_timestamps_seconds=(0., 5.)), ("video_sampled",), "videoSampled"),
        "no_text": (cls("image", text_source="none"), ("no_text_content",), "noTextContent"),
        "metadata": (cls("image", text_source="metadata_only"), ("metadata_only",), "metadataOnly"),
        "combined": (cls("video", text_truncated=True, text_limit_reason="character_limit",
                            video_duration_seconds=10., video_timestamps_seconds=(0., 5.)),
                    ("text_character_limit", "video_sampled"), "limitedEvidence"),
    }
    coverage, codes, message = facts[case]
    original = env.service.run_prepared
    def run(work):
        return replace(original(work), coverage=coverage, warning_codes=codes,
            content_kind=ContentKind.VIDEO if case in {"video", "combined"} else ContentKind.TEXT)
    env.service.run_prepared = run
    task_id = import_one(env)
    pump(app, lambda: env.controller.task_snapshot(task_id)["status"] == "review_pending")
    task = env.controller.task_snapshot(task_id)
    assert task["canApply"] and task["canRetry"]
    assert task["errorMessage"] == "batch.error." + message
    assert task["analysisWarningCodes"] == list(codes)
    assert task["analysisCoverage"]["content_kind"] == coverage.content_kind
    assert task["analysisCoverage"]["text_truncated"] == coverage.text_truncated
    assert "synthetic-secret" not in json.dumps(task["analysisCoverage"])
    env.controller.close()
    restored = batch.BatchWorkspaceController(background=False, workspace_path=tmp_path / "workspace.json",
        history_path=tmp_path / "history.json")
    try:
        reloaded = restored.task_snapshot(task_id)
        assert reloaded["status"] == "review_pending" and reloaded["canApply"]
        for key in ("analysisCoverage", "analysisWarningCodes", "errorMessage"):
            assert reloaded[key] == task[key]
    finally:
        restored.close()


@pytest.mark.parametrize("mutation", ["raw_warning", "warning_list", "duplicate_warning", "raw_coverage",
    "coverage_subclass", "mutated_coverage", "missing_required_warning"])
def test_malformed_outcome_coverage_warnings_fail_closed_without_leak(app, tmp_path, mutation):
    env = environment(tmp_path, app)
    coverage = PreparationCoverage("text", sections_processed=1)
    codes = ()
    if mutation == "raw_warning":
        codes = ("synthetic-secret " + str(env.path),)
    elif mutation == "warning_list":
        codes = ["video_sampled"]
    elif mutation == "duplicate_warning":
        codes = ("video_sampled", "video_sampled")
    elif mutation == "raw_coverage":
        coverage = {"private": "synthetic-secret " + str(env.path)}
    elif mutation == "coverage_subclass":
        class ExtendedCoverage(PreparationCoverage):
            pass
        coverage = ExtendedCoverage("text")
    elif mutation == "mutated_coverage":
        object.__setattr__(coverage, "text_limit_reason", "synthetic-secret")
    else:
        coverage = PreparationCoverage("text", text_truncated=True, text_limit_reason="character_limit")
    original = env.service.run_prepared
    env.service.run_prepared = lambda work: replace(original(work), coverage=coverage, warning_codes=codes)
    task_id = import_one(env)
    try:
        pump(app, lambda: env.controller.task_snapshot(task_id)["status"] != "analyzing")
        task = env.controller.task_snapshot(task_id)
        assert task["status"] == "failed" and task["errorMessage"] == "batch.error.invalidOutcome"
        assert task["suggestedName"] == ""
        assert "synthetic-secret" not in json.dumps(task)
    finally:
        env.controller.close()


def test_lane_overflow_maps_to_fixed_visible_queue_full(app, tmp_path):
    from src.core.batch_analysis import BatchAnalysisError
    env = environment(tmp_path, app)
    def overflow(work):
        raise BatchAnalysisError("Local analysis queue is full")
    env.service.run_prepared = overflow
    task_id = import_one(env)
    try:
        pump(app, lambda: env.controller.task_snapshot(task_id)["status"] == "failed")
        assert env.controller.task_snapshot(task_id)["errorMessage"] == "batch.error.queueFull"
    finally:
        env.controller.close()


def test_three_locales_have_fixed_coverage_warning_messages():
    required = {"partialRead", "videoSampled", "noTextContent", "metadataOnly", "limitedEvidence"}
    root = Path(__file__).resolve().parents[2] / "src" / "utils" / "i18n" / "locales"
    for locale in ("en_US", "zh_CN", "zh_HK"):
        messages = json.loads((root / (locale + ".json")).read_text(encoding="utf-8"))
        assert {"batch.error." + key for key in required} <= messages.keys()
        assert all(type(messages["batch.error." + key]) is str and messages["batch.error." + key] for key in required)


def test_reload_rejects_raw_warning_codes_without_coverage(app, tmp_path):
    env = environment(tmp_path, app)
    task_id = import_one(env)
    pump(app, lambda: env.controller.task_snapshot(task_id)["status"] == "review_pending")
    env.controller.close()
    workspace = tmp_path / "workspace.json"
    data = json.loads(workspace.read_text(encoding="utf-8"))
    data["tasks"][0].update(analysisCoverage=None, analysisWarningCodes=["synthetic-secret private-source"])
    workspace.write_text(json.dumps(data), encoding="utf-8")
    restored = batch.BatchWorkspaceController(background=False, workspace_path=workspace)
    try:
        task = restored.task_snapshot(task_id)
        assert task["status"] == "failed" and task["errorMessage"] == "batch.error.invalidOutcome"
        assert "synthetic-secret" not in json.dumps(task)
    finally:
        restored.close()


@pytest.mark.parametrize("reentrant", [False, True])
def test_managed_admission_save_failure_cancels_unsubmitted_owner_and_allows_retry(app, tmp_path, reentrant):
    env = environment(tmp_path, app)
    original_save = env.controller._save_workspace
    before = []
    notifications = []
    def save(tasks=None):
        if any(task["status"] == "analyzing" for task in tasks or []):
            before.append((tmp_path / "workspace.json").read_bytes())
            raise OSError("synthetic-secret " + str(tmp_path))
        return original_save(tasks)
    env.controller._save_workspace = save
    def changed():
        if not env.controller.task_ids:
            return
        task_id = env.controller.task_ids[0]
        task = env.controller.task_snapshot(task_id)
        if task["status"] == "failed":
            notifications.append(task)
            assert (tmp_path / "workspace.json").read_bytes() == before[0]
            assert not env.controller._analysis_work and not env.controller._analysis_attempts
            assert not env.controller._cancellation_events
            if reentrant:
                env.controller._save_workspace = original_save
                env.controller.retryTask(task_id)
    env.controller.tasksChanged.connect(changed)
    escaped = []
    try:
        try:
            import_one(env)
        except Exception as error:
            escaped.append(type(error).__name__)
        assert not escaped, "managed save failure escaped the safe boundary"
        old = env.captured[0][1]
        assert old.context.task_cancel_event.is_set()
        assert notifications and notifications[0]["canRetry"]
        assert notifications[0]["errorMessage"] == "batch.error.workspaceSaveFailed"
        assert "synthetic-secret" not in json.dumps(notifications)
        if reentrant:
            assert len(env.captured) == 2 and env.captured[1][1] is not old
            pump(app, lambda: env.controller.task_snapshot(old.task_id)["status"] == "review_pending")
        else:
            assert not env.calls and env.controller.workers_idle
            assert (tmp_path / "workspace.json").read_bytes() == before[0]
            env.controller._save_workspace = original_save
            env.controller.retryTask(old.task_id)
            pump(app, lambda: env.controller.task_snapshot(old.task_id)["status"] == "review_pending")
    finally:
        env.controller._save_workspace = original_save
        env.controller.close()


@pytest.mark.parametrize("analysis_error", [False, True])
@pytest.mark.parametrize("reentrant", [False, True])
def test_managed_terminal_save_failure_retires_exact_owner_without_unsaved_success(app, tmp_path, analysis_error, reentrant):
    env = environment(tmp_path, app)
    if analysis_error:
        def fail():
            raise RuntimeError("synthetic-secret " + str(tmp_path))
        env.hooks.infer = fail
    task_id = import_one(env)
    wait_workers_without_qt_delivery(env.controller)
    old = env.captured[0][1]
    future = next(iter(env.controller._submitted_futures))
    completion = future.result()
    original_save = env.controller._save_workspace
    before = (tmp_path / "workspace.json").read_bytes()
    failed_notifications = []
    def save(tasks=None):
        raise OSError("synthetic-secret " + str(tmp_path))
    env.controller._save_workspace = save
    def changed():
        task = env.controller.task_snapshot(task_id)
        if task["status"] == "failed":
            failed_notifications.append(task)
            assert (tmp_path / "workspace.json").read_bytes() == before
            assert task["suggestedName"] == "" and not task["canApply"] and task["canRetry"]
            assert task_id not in env.controller._analysis_work
            assert task_id not in env.controller._analysis_attempts
            assert task_id not in env.controller._cancellation_events
            if reentrant:
                env.hooks.infer = lambda: None
                env.controller._save_workspace = original_save
                env.controller.retryTask(task_id)
    env.controller.tasksChanged.connect(changed)
    escaped = []
    try:
        try:
            env.controller._accept_managed_completion(completion)
        except Exception as error:
            escaped.append(type(error).__name__)
        assert not escaped, "terminal save failure escaped the safe boundary"
        assert failed_notifications[0]["errorMessage"] == "batch.error.workspaceSaveFailed"
        assert "synthetic-secret" not in json.dumps(failed_notifications)
        if not reentrant:
            assert (tmp_path / "workspace.json").read_bytes() == before
            env.controller._save_workspace = original_save
            env.hooks.infer = lambda: None
            env.controller.retryTask(task_id)
        assert len(env.captured) == 2 and env.captured[1][1] is not old
        pump(app, lambda: env.controller.task_snapshot(task_id)["status"] == "review_pending")
        assert env.controller.task_snapshot(task_id)["suggestedName"] == "项目报告.txt"
    finally:
        env.controller._save_workspace = original_save
        env.controller.close()


def test_managed_durable_save_precedes_ownership_swap_and_public_notifications(app, tmp_path):
    env = environment(tmp_path, app)
    original_save = env.controller._save_workspace
    observations = []
    def save(tasks=None):
        task = tasks[0] if tasks else None
        if task and task["status"] == "analyzing":
            assert not env.controller._analysis_work and not env.controller._analysis_attempts
            assert not env.controller._cancellation_events
            observations.append("save_admission")
        elif task and task["status"] == "review_pending":
            assert env.controller._analysis_work.get(task["taskId"]) is env.captured[0][1]
            observations.append("save_terminal")
        return original_save(tasks)
    env.controller._save_workspace = save
    def changed():
        if not env.controller.task_ids:
            return
        task_id = env.controller.task_ids[0]
        state = env.controller.task_snapshot(task_id)["status"]
        if state == "analyzing":
            assert env.controller._analysis_work[task_id] is env.captured[0][1]
            observations.append("publish_admission")
        elif state == "review_pending":
            assert task_id not in env.controller._analysis_work
            observations.append("publish_terminal")
    env.controller.tasksChanged.connect(changed)
    try:
        task_id = import_one(env)
        pump(app, lambda: env.controller.task_snapshot(task_id)["status"] == "review_pending")
        assert observations == ["save_admission", "publish_admission", "save_terminal", "publish_terminal"]
    finally:
        env.controller.close()


@pytest.mark.parametrize("analysis_error", [False, True])
def test_workers_idle_requires_done_callback_emission_to_finish(app, tmp_path, analysis_error):
    env = environment(tmp_path, app)
    runner_entered, runner_release = Event(), Event()
    callback_entered, callback_release = Event(), Event()
    env.hooks.prepare = lambda: (runner_entered.set(), runner_release.wait(3))
    if analysis_error:
        def fail():
            raise RuntimeError("synthetic-only")
        env.hooks.infer = fail
    original_emit = env.controller._emit_managed_future
    def emit(*args):
        callback_entered.set()
        assert callback_release.wait(3)
        original_emit(*args)
    env.controller._emit_managed_future = emit
    task_id = import_one(env)
    assert runner_entered.wait(2)
    future = next(iter(env.controller._submitted_futures))
    runner_release.set()
    try:
        assert callback_entered.wait(2) and future.done()
        assert not env.controller.workers_idle and env.controller.pending_worker_count == 1
        env.controller._prune_workers()
        assert future in env.controller._submitted_futures
        started = time.monotonic()
        env.controller.close()
        assert time.monotonic() - started < .5
        assert not env.controller.workers_idle and env.controller.pending_worker_count == 1
        assert future in env.controller._submitted_futures
        assert env.controller.task_snapshot(task_id)["status"] == "cancelled"
        callback_release.set()
        wait_workers_without_qt_delivery(env.controller)
        assert env.controller.workers_idle
        env.controller._prune_workers()
        assert future not in env.controller._submitted_futures
        app.processEvents()
        assert env.controller.task_snapshot(task_id)["status"] == "cancelled"
    finally:
        runner_release.set()
        callback_release.set()
        env.controller.close()


def test_three_locales_have_fixed_workspace_save_failure_message():
    root = Path(__file__).resolve().parents[2] / "src" / "utils" / "i18n" / "locales"
    for locale in ("en_US", "zh_CN", "zh_HK"):
        messages = json.loads((root / (locale + ".json")).read_text(encoding="utf-8"))
        assert "batch.error.workspaceSaveFailed" in messages
        assert messages["batch.error.workspaceSaveFailed"]


def test_test_teardown_rejects_unfinished_callback_before_destroying_qobject(app, tmp_path):
    from shiboken6 import isValid
    env = environment(tmp_path, app)
    runner_entered, runner_release = Event(), Event()
    callback_entered, callback_release = Event(), Event()
    env.hooks.prepare = lambda: (runner_entered.set(), runner_release.wait(3))
    original_emit = env.controller._emit_managed_future
    def emit(*args):
        callback_entered.set()
        assert callback_release.wait(3)
        original_emit(*args)
    env.controller._emit_managed_future = emit
    import_one(env)
    assert runner_entered.wait(2)
    runner_release.set()
    try:
        assert callback_entered.wait(2)
        assert all(future.done() for future in env.controller._submitted_futures)
        teardown = globals().get("_teardown_test_controllers")
        assert callable(teardown), "bounded owner-thread test teardown is missing"
        with pytest.raises(AssertionError, match="unfinished completion callbacks"):
            teardown(app, [env.controller], timeout=.02)
        assert isValid(env.controller) and not env.controller.workers_idle
        callback_release.set()
        teardown(app, [env.controller])
        assert not isValid(env.controller)
    finally:
        runner_release.set()
        callback_release.set()
        if isValid(env.controller):
            env.controller.close()
            wait_workers_without_qt_delivery(env.controller)
            app.processEvents()

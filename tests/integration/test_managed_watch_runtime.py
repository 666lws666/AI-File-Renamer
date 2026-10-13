"""Owned Watch composition gates; synthetic adapters, never real cloud/model."""
import time
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from src.qml_bootstrap import build_qml_runtime
from src.core.watch_config import WatchConfig, WatchConfigStore, WatchMode
from src.core.watch_review_queue import ReviewItem, ReviewItemState, ReviewQueue
from src.controllers.watch_controller import MockObserver, ObserverFactory, FileEvent
from tests.integration.test_managed_watch_analysis import outcome, pump_until
from tests.integration.test_managed_processing_runtime import cloud_config


class Credentials:
    def __init__(self): self.calls = []
    def get(self, *args): self.calls.append(args); return "synthetic-key"
    def set(self, *args): return True
    def delete(self, *args): return True


class Inference:
    def __init__(self, config): pass
    def shutdown(self, *, deadline): return SimpleNamespace(phase="CLOSED")


class Preparation:
    def close(self, deadline): return True


@pytest.fixture
def make_runtime(tmp_path):
    app = QApplication.instance() or QApplication([])
    owned = []
    def make(**options):
        defaults = dict(config_file=tmp_path / "settings.json", credential_store=Credentials(),
            usage_recorder=None, diagnostics_service=None, local_inference_factory=Inference,
            local_preparation_factory=Preparation, resource_controller=None)
        defaults.update(options)
        runtime = build_qml_runtime(**defaults)
        owned.append(runtime)
        return runtime
    yield make
    for runtime in owned:
        assert runtime.cleanup(deadline=time.monotonic() + 3)
        runtime.assert_zero_warnings()


def test_default_watch_borrows_exact_analysis_and_serial_lane(make_runtime):
    runtime = make_runtime()
    assert runtime.watch_controller is not None
    assert runtime.watch_owner.page is runtime.watch_controller
    assert runtime.watch_owner.analysis_service is runtime.analysis_service
    assert runtime.watch_owner.file_lane is runtime.file_operation_lane
    assert runtime.watch_owner.delivery._consume.__self__ is runtime.watch_owner.results
    assert runtime.watch_controller.approveResult("absent") is False


def test_explicit_none_disables_watch_without_ownership(make_runtime):
    runtime = make_runtime(watch_controller=None)
    assert runtime.watch_controller is None
    assert getattr(runtime, "watch_owner", None) is None


def test_default_watch_with_batch_none_still_owns_exact_lane(make_runtime):
    runtime = make_runtime(batch_controller=None)
    assert runtime.batch_controller is None
    assert runtime.watch_controller is not None
    assert runtime.watch_owner.file_lane is runtime.file_operation_lane
    assert runtime.owns_file_operation_lane is True


@pytest.mark.parametrize("mode", list(WatchMode))
def test_owned_publication_review_or_auto_then_public_undo(make_runtime, tmp_path, monkeypatch, mode):
    from src.core.batch_analysis import BatchAnalysisService
    from src.controllers.watch_controller import WatchController
    from src.controllers.managed_file_operation_lane import FileOperationProgress
    monkeypatch.setattr(WatchController, "DEFAULT_DEBOUNCE_SECONDS", .01)
    monkeypatch.setattr(ObserverFactory, "create", lambda _: MockObserver())
    calls = []
    def run(service, work, **kw):
        calls.append((work, threading.get_ident())); return outcome(work)
    monkeypatch.setattr(BatchAnalysisService, "run_prepared", run)
    source = tmp_path / "watched"; source.mkdir()
    store = WatchConfigStore(tmp_path / "watch_folders.json")
    store.add(WatchConfig("watch", str(source), mode=mode))
    runtime = make_runtime(live_config=cloud_config())
    owner = runtime.watch_owner
    lane = runtime.file_operation_lane
    progress_posted, release = threading.Event(), threading.Event()
    post = lane._post
    def post_then_hold_apply_tail(payload, job, signal):
        post(payload, job, signal)
        if type(payload) is FileOperationProgress and payload.reservation.request.kind == "apply":
            progress_posted.set()
            assert release.wait(5)
    monkeypatch.setattr(lane, "_post", post_then_hold_apply_tail)
    path = source / "original.txt"; path.write_bytes(b"synthetic test content")
    try:
        owner.controller._simulate_file_event("watch", str(path), FileEvent.CREATED)
        pump_until(lambda: bool(owner.results.items()), timeout=3)
        if mode is WatchMode.REVIEW_FIRST:
            row, = owner.results.items()
            assert row.state is ReviewItemState.AWAITING_APPROVAL
            assert runtime.watch_controller.approveResult(row.id) is True
        pump_until(lambda: owner.results.items()[0].state is ReviewItemState.APPLIED
                   and progress_posted.is_set(), timeout=3)
        applied, = owner.results.items()
        assert calls and all(ident != threading.get_ident() for _, ident in calls)
        runtime.watch_controller.refresh()
        assert len(calls) == 1
        # Progress publishes APPLIED before terminal completion retires its owner.
        assert applied.id in owner.file_actions._rows
        assert lane.pending_job_count == lane.owned_item_count == 1
        assert not lane.workers_idle and not owner.file_actions.workers_idle
        assert runtime.watch_controller.undoResult(applied.id) is False
    finally:
        release.set()
    pump_until(lambda: owner.file_actions.workers_idle and lane.workers_idle, timeout=3)
    assert runtime.watch_controller.undoResult(applied.id) is True
    pump_until(lambda: owner.results.item(applied.id).state is ReviewItemState.UNDONE, timeout=3)
    assert path.read_bytes() == b"synthetic test content"
    assert runtime.watch_controller.approveResult("absent") is False
    assert runtime.watch_controller.ignoreResult("absent") is False


def test_corrupt_stores_are_preserved_and_owned_page_unavailable(make_runtime, tmp_path):
    path = tmp_path / "watch_review_queue.json"
    path.write_bytes(b"CORRUPT SYNTHETIC QUEUE")
    runtime = make_runtime()
    assert runtime.watch_controller is not None
    assert runtime.watch_controller.available is False
    assert runtime.watch_controller.approveResult("absent") is False
    assert path.read_bytes() == b"CORRUPT SYNTHETIC QUEUE"


def test_restored_interrupted_rows_hold_without_ai_or_disk_replay(make_runtime, tmp_path, monkeypatch):
    from src.core.batch_analysis import BatchAnalysisService
    monkeypatch.setattr(BatchAnalysisService, "run_prepared", lambda *a, **k: pytest.fail("startup replay"))
    queue = ReviewQueue(tmp_path / "watch_review_queue.json")
    rows = [queue.add(ReviewItem(state.value, "watch", str(tmp_path / (state.value + ".txt")),
        1, 1, ".txt", state.value, state)) for state in ReviewItemState]
    runtime = make_runtime()
    owner = runtime.watch_owner
    for row in rows:
        current = owner.results.item(row.id)
        if row.state in {ReviewItemState.PENDING, ReviewItemState.ANALYZING}:
            assert current.state is ReviewItemState.CANCELLED and current.error_category == "interrupted"
        elif row.state is ReviewItemState.APPLYING:
            assert current.recovery_required
            assert runtime.watch_controller.approveResult(row.id) is False
            assert runtime.watch_controller.retryResult(row.id) is False
        else:
            assert current == row
    assert runtime.file_operation_lane.owned_item_count == 0


def test_retry_captures_new_current_work_and_preserves_source_extension(make_runtime, tmp_path, monkeypatch):
    from src.core.batch_analysis import BatchAnalysisService
    from src.controllers.watch_controller import WatchController
    monkeypatch.setattr(WatchController, "DEFAULT_DEBOUNCE_SECONDS", .01)
    monkeypatch.setattr(ObserverFactory, "create", lambda _: MockObserver())
    calls = []
    def run(service, work, **kw): calls.append(work); return outcome(work)
    monkeypatch.setattr(BatchAnalysisService, "run_prepared", run)
    source = tmp_path / "watched"; source.mkdir()
    path = source / "original.txt"; path.write_bytes(b"synthetic retry")
    WatchConfigStore(tmp_path / "watch_folders.json").add(WatchConfig("watch", str(source)))
    value = path.stat()
    queue = ReviewQueue(tmp_path / "watch_review_queue.json")
    old = queue.add(ReviewItem("old", "watch", str(path), value.st_size, value.st_mtime_ns,
        ".txt", "original", ReviewItemState.FAILED))
    runtime = make_runtime(live_config=cloud_config())
    owner = runtime.watch_owner
    assert runtime.watch_controller.retryResult(old.id) is True
    assert runtime.watch_controller.retryResult(old.id) is False
    pump_until(lambda: len(owner.results.items()) == 2, timeout=3)
    new = next(row for row in owner.results.items() if row.id != old.id)
    assert new.source_path == old.source_path and new.extension == old.extension
    assert new.state is ReviewItemState.AWAITING_APPROVAL
    assert owner.results.item(old.id).state is ReviewItemState.CANCELLED
    assert calls[0].source_path == old.source_path


def _active_runtime(make_runtime, tmp_path, monkeypatch, *, mode=WatchMode.AUTO_APPLY, run=None):
    from src.core.batch_analysis import BatchAnalysisService
    from src.controllers.watch_controller import WatchController
    monkeypatch.setattr(WatchController, "DEFAULT_DEBOUNCE_SECONDS", .01)
    monkeypatch.setattr(ObserverFactory, "create", lambda _: MockObserver())
    monkeypatch.setattr(BatchAnalysisService, "run_prepared", run or (lambda _, work, **kw: outcome(work)))
    source = tmp_path / "watched"; source.mkdir()
    WatchConfigStore(tmp_path / "watch_folders.json").add(WatchConfig("watch", str(source), mode=mode))
    runtime = make_runtime(live_config=cloud_config())
    path = source / "original.txt"; path.write_bytes(b"synthetic bounded runtime")
    return runtime, path


def test_pending_count_includes_original_predebounce_admission(make_runtime, tmp_path, monkeypatch):
    runtime, path = _active_runtime(make_runtime, tmp_path, monkeypatch)
    runtime.watch_owner.controller._debounce_seconds = 10
    runtime.watch_owner.controller._simulate_file_event("watch", str(path), FileEvent.CREATED)
    assert runtime.watch_owner.actions.get_counts("watch")["pending"] == 1
    assert runtime.watch_owner.guard.pending_count("watch") == 1


@pytest.mark.parametrize("invalidate", ["mode", "pause", "edit", "remove", "close"])
def test_auto_final_intent_reentrancy_never_commits(make_runtime, tmp_path, monkeypatch, invalidate):
    from dataclasses import replace
    runtime, path = _active_runtime(make_runtime, tmp_path, monkeypatch)
    owner = runtime.watch_owner
    original = owner.results._replace_for_file_operation
    called = []
    def write_then_invalidate(changes, **kwargs):
        saved = original(changes, **kwargs)
        if not called and any(row.state is ReviewItemState.APPLYING for row in saved):
            called.append(invalidate)
            if invalidate == "mode": runtime.processing_coordinator.selectLocal()
            elif invalidate == "pause": owner.controller.pause_watch("watch")
            elif invalidate == "edit":
                assert runtime.watch_controller.beginEdit("watch") is True
                config = owner.controller.get_config("watch")
                owner.controller.update_watch(replace(config, mode=WatchMode.REVIEW_FIRST, version=config.version + 1))
            elif invalidate == "remove": owner.controller.remove_watch("watch")
            else: owner.begin_close()
        return saved
    monkeypatch.setattr(owner.results, "_replace_for_file_operation", write_then_invalidate)
    owner.controller._simulate_file_event("watch", str(path), FileEvent.CREATED)
    pump_until(lambda: bool(called) and owner.delivery.workers_idle, timeout=3)
    row, = owner.results.items()
    assert path.exists() and not (path.parent / "suggestion.txt").exists()
    assert runtime.file_operation_lane.owned_item_count == 0
    assert row.state is ReviewItemState.AWAITING_APPROVAL and row.file_operation is None


@pytest.mark.parametrize("facts", ["partial", "unknown", "degraded", "metadata_only"])
def test_new_auto_result_with_ineligible_facts_stays_review(make_runtime, tmp_path, monkeypatch, facts):
    from src.core.processing_analysis import CloudAnalysisCoverage
    def run(_, work, **kw):
        if facts == "partial": return outcome(work, coverage=CloudAnalysisCoverage("text", sections_processed=1, sections_total=2))
        if facts == "unknown": return outcome(work, coverage=CloudAnalysisCoverage("text"))
        if facts == "degraded": return outcome(work, effective_quality="economy")
        return outcome(work, coverage=CloudAnalysisCoverage("text", text_source="metadata_only"), warning_codes=("metadata_only",))
    runtime, path = _active_runtime(make_runtime, tmp_path, monkeypatch, run=run)
    owner = runtime.watch_owner
    owner.controller._simulate_file_event("watch", str(path), FileEvent.CREATED)
    pump_until(lambda: bool(owner.results.items()) and owner.delivery.workers_idle, timeout=3)
    row, = owner.results.items()
    assert row.state is ReviewItemState.AWAITING_APPROVAL
    runtime.watch_controller.openResults("watch")
    assert runtime.watch_controller.results[0]["autoApplyReviewReason"]
    assert path.exists() and runtime.file_operation_lane.owned_item_count == 0


@pytest.mark.parametrize("case", ["vision-off", "legacy", "unsupported", "render-cap", "complete"])
@pytest.mark.parametrize("mode", [WatchMode.AUTO_APPLY, WatchMode.REVIEW_FIRST])
def test_actual_mixed_pdf_routing_evidence_controls_watch_file_lane(
        make_runtime, tmp_path, monkeypatch, case, mode):
    from dataclasses import replace
    from src.controllers.watch_controller import WatchController
    from src.core.provider_protocol import ProviderCapabilities, ProviderResponse
    from src.services.retry_policy import RetryExecutionResult
    from tests.integration.test_local_analysis_routing import synthetic_pdf
    from tests.integration.test_managed_processing_runtime import profile
    monkeypatch.setattr(WatchController, "DEFAULT_DEBOUNCE_SECONDS", .01)
    monkeypatch.setattr(ObserverFactory, "create", lambda _: MockObserver())
    source = tmp_path / "watched"; source.mkdir()
    path = source / "original.pdf"
    synthetic_pdf(path, scan_pages=7 if case == "render-cap" else 1)
    original_bytes = path.read_bytes()
    WatchConfigStore(tmp_path / "watch_folders.json").add(WatchConfig("watch", str(source), mode=mode))
    selected = replace(profile(), capabilities=ProviderCapabilities(
        text=True, vision=case != "unsupported", multi_image=True, json_schema=True))
    config = cloud_config()
    config.provider_profiles = [selected.to_safe_dict()]
    config.allow_vision_cloud = case != "vision-off"
    requests, reservations = [], []
    def factory(profile, key, *, processing_dispatch, retry_executor):
        def invoke(request, *, cancellation_token):
            requests.append(request)
            receipt = processing_dispatch.authority.commit_cloud_attempt(
                processing_dispatch.context, "synthetic-mixed-pdf")
            processing_dispatch.authority.finish_attempt(receipt)
            fields = {name: "2026-10-12" if name == "dcDate" else "synthetic"
                      for name in request.requested_schema["properties"]}
            return RetryExecutionResult(True, ProviderResponse(fields=fields), (), None, None)
        return SimpleNamespace(invoke=invoke)
    options = dict(live_config=config, managed_adapter_factory=factory)
    if case == "legacy":
        options["analysis_content_extractor"] = lambda *_: ("Synthetic cover title", {
            "pages": 2, "pages_processed": 2, "sections_processed": 2,
            "sections_total": 2, "coverage_reason": "complete"})
    runtime = make_runtime(**options)
    owner = runtime.watch_owner
    reserve = runtime.file_operation_lane.reserve
    def observed_reserve(*args, **kwargs):
        reservations.append(args)
        return reserve(*args, **kwargs)
    monkeypatch.setattr(runtime.file_operation_lane, "reserve", observed_reserve)
    owner.controller._simulate_file_event("watch", str(path), FileEvent.CREATED)
    expected = (ReviewItemState.FAILED if case == "unsupported" else
                ReviewItemState.APPLIED if case == "complete" and mode is WatchMode.AUTO_APPLY else
                ReviewItemState.AWAITING_APPROVAL)
    pump_until(lambda: bool(owner.results.items()) and owner.results.items()[0].state is expected
               and owner.delivery.workers_idle and runtime.file_operation_lane.workers_idle, timeout=5)
    row, = owner.results.items()
    assert row.state is expected
    if expected is ReviewItemState.APPLIED:
        assert len(reservations) == 1 and not path.exists()
        from pathlib import Path
        assert Path(row.applied_path).read_bytes() == original_bytes
    else:
        assert reservations == [] and path.read_bytes() == original_bytes
    runtime.watch_controller.openResults("watch")
    if case != "unsupported":
        reason = runtime.watch_controller.results[0]["autoApplyReviewReason"]
        assert reason == ("" if case == "complete" else "partial_content")
        assert len(requests) == 1
        expected_images = 6 if case == "render-cap" else 1 if case == "complete" else 0
        assert len(requests[0].visual_payloads) == expected_images
    else:
        assert requests == []


def test_actual_commit_and_file_publication_survive_mode_change_and_finite_close(make_runtime, tmp_path, monkeypatch):
    from shiboken6 import isValid
    runtime, path = _active_runtime(make_runtime, tmp_path, monkeypatch)
    owner, lane = runtime.watch_owner, runtime.file_operation_lane
    entered, release = threading.Event(), threading.Event()
    execute = lane._backend.execute_item
    def physically_move_then_block(request, index):
        result = execute(request, index)
        assert result.success
        entered.set()
        assert release.wait(5)
        return result
    monkeypatch.setattr(lane._backend, "execute_item", physically_move_then_block)
    owner.controller._simulate_file_event("watch", str(path), FileEvent.CREATED)
    pump_until(entered.is_set, timeout=3)
    root, engine = runtime.root, runtime.engine
    try:
        assert not path.exists() and (path.parent / "suggestion.txt").exists()
        assert owner.results.items()[0].state is ReviewItemState.APPLYING
        runtime.processing_coordinator.selectLocal()
        assert runtime.cleanup(deadline=time.monotonic() + .02) is False
        assert runtime.watch_owner is owner and runtime.file_operation_lane is lane
        assert runtime.root is root and isValid(root) and isValid(engine)
        assert not owner.workers_idle and not owner.receipts.workers_idle
    finally:
        release.set()
    assert runtime.cleanup(deadline=time.monotonic() + 3)
    saved, = ReviewQueue(tmp_path / "watch_review_queue.json").items()
    assert saved.state is ReviewItemState.APPLIED and saved.applied_path.endswith("suggestion.txt")
    assert saved.file_operation is None and not saved.recovery_required


def test_observer_start_emits_only_after_all_consumers_and_cleanup_bind(make_runtime, tmp_path, monkeypatch):
    from src.controllers.managed_watch_runtime import ManagedWatchRuntime
    from src.core.batch_analysis import BatchAnalysisService
    from src.controllers.watch_controller import WatchController
    source = tmp_path / "watched"; source.mkdir()
    path = source / "original.txt"; path.write_bytes(b"synchronous startup fixture")
    WatchConfigStore(tmp_path / "watch_folders.json").add(WatchConfig("watch", str(source)))
    monkeypatch.setattr(WatchController, "DEFAULT_DEBOUNCE_SECONDS", .01)
    monkeypatch.setattr(BatchAnalysisService, "run_prepared", lambda _, work, **kw: outcome(work))
    bound = []
    original = ManagedWatchRuntime.start
    def assert_bound(owner):
        assert all(value is not None for value in (owner.page, owner.controller, owner.results,
            owner.actions, owner.delivery, owner.file_actions, owner.receipts, owner.file_lane))
        assert owner.delivery._consume.__self__ is owner.results
        assert owner.file_lane._receipts is owner.receipts
        bound.append(owner)
        original(owner)
    monkeypatch.setattr(ManagedWatchRuntime, "start", assert_bound)
    class EmitsDuringStart(MockObserver):
        def start(self):
            super().start()
            self.simulate_event(str(path), FileEvent.CREATED)
    monkeypatch.setattr(ObserverFactory, "create", lambda _: EmitsDuringStart())
    runtime = make_runtime(live_config=cloud_config())
    assert bound == [runtime.watch_owner]
    pump_until(lambda: bool(runtime.watch_owner.results.items()), timeout=3)
    assert runtime.watch_owner.results.items()[0].state is ReviewItemState.AWAITING_APPROVAL


def test_batch_and_watch_real_shared_cloud_gate_limits_actual_active_calls(make_runtime, tmp_path, monkeypatch):
    from src.controllers.watch_controller import WatchController
    from src.core.provider_protocol import ProviderResponse
    from src.services.retry_policy import RetryExecutionResult
    from tests.integration.test_managed_processing_runtime import smart_fields
    entered, release = threading.Event(), threading.Event()
    lock, active, maximum, calls = threading.Lock(), [0], [0], []
    def factory(profile, key, *, processing_dispatch, retry_executor):
        def invoke(request, *, cancellation_token):
            receipt = processing_dispatch.authority.commit_cloud_attempt(processing_dispatch.context, "synthetic-shared-cloud")
            with lock:
                active[0] += 1; maximum[0] = max(maximum[0], active[0]); calls.append(request.metadata["naming_mode"])
            entered.set()
            try:
                assert release.wait(5)
                fields = smart_fields() if request.metadata["naming_mode"] == "smart" else {
                    key: "2026-10-12" if key == "dcDate" else "synthetic"
                    for key in request.requested_schema["properties"]}
                return RetryExecutionResult(True, ProviderResponse(fields=fields), (), None, None)
            finally:
                with lock: active[0] -= 1
                processing_dispatch.authority.finish_attempt(receipt)
        return SimpleNamespace(invoke=invoke)
    source = tmp_path / "watched"; source.mkdir()
    watch_path = source / "watch.txt"; watch_path.write_bytes(b"synthetic watch")
    batch_path = tmp_path / "batch.txt"; batch_path.write_bytes(b"synthetic batch")
    WatchConfigStore(tmp_path / "watch_folders.json").add(WatchConfig("watch", str(source)))
    monkeypatch.setattr(ObserverFactory, "create", lambda _: MockObserver())
    monkeypatch.setattr(WatchController, "DEFAULT_DEBOUNCE_SECONDS", .01)
    config = cloud_config(); config.max_concurrent_requests = 1
    runtime = make_runtime(live_config=config, managed_adapter_factory=factory,
        analysis_content_extractor=lambda *_: ("synthetic text", {"sections_processed": 1, "sections_total": 1}))
    try:
        runtime.batch_controller.add_files([str(batch_path)])
        assert entered.wait(3)
        runtime.watch_owner.controller._simulate_file_event("watch", str(watch_path), FileEvent.CREATED)
        pump_until(lambda: runtime.analysis_service._cloud_lane.waiting_count == 1, timeout=3)
        assert runtime.analysis_service._cloud_lane.active_count == active[0] == maximum[0] == 1
        assert calls == ["template"]  # Saved/default Batch naming policy is preserved.
    finally:
        release.set()
    pump_until(lambda: len(calls) == 2 and runtime.watch_owner.delivery.workers_idle, timeout=3)
    assert calls == ["template", "template"] and maximum[0] == 1
    assert runtime.watch_owner.results.items()[0].state is ReviewItemState.AWAITING_APPROVAL


def test_runtime_resource_pause_holds_original_work_until_explicit_recovery(make_runtime, tmp_path, monkeypatch):
    from src.core.watch_config import WatchStatus
    entered, release, calls = threading.Event(), threading.Event(), []
    def run(_, work, **kwargs):
        calls.append(work)
        if len(calls) == 1:
            entered.set(); assert release.wait(5)
        return outcome(work)
    runtime, path = _active_runtime(make_runtime, tmp_path, monkeypatch, mode=WatchMode.REVIEW_FIRST, run=run)
    owner = runtime.watch_owner
    now = [time.monotonic()]; owner.guard._clock = lambda: now[0]
    second = path.parent / "second.txt"; second.write_bytes(b"second original admission")
    try:
        owner.controller._simulate_file_event("watch", str(path), FileEvent.CREATED)
        pump_until(entered.is_set, timeout=3)
        owner.controller._simulate_file_event("watch", str(second), FileEvent.CREATED)
        pump_until(lambda: owner.controller.get_config("watch").status is WatchStatus.RESOURCE_PAUSED, timeout=3)
        waiting = next(state.event.admission.work for state in owner.delivery._owners.values()
            if state.event.admission.work.source_path == str(second))
        assert owner.guard.pending_count("watch") == 2 and owner.guard.active_analyses("watch") == 1
        assert owner.guard.consecutive_failures("watch") == 0
        release.set()
        pump_until(lambda: owner.guard.active_analyses("watch") == 0, timeout=3)
        assert len(calls) == 1 and owner.controller.get_config("watch").status is WatchStatus.RESOURCE_PAUSED
        now[0] += 31
        assert runtime.watch_controller.resumeWatch("watch") is True
        pump_until(lambda: len(calls) == 2 and owner.delivery.workers_idle, timeout=3)
        assert calls[1] is waiting and calls[1].context is waiting.context
        assert owner.guard.consecutive_failures("watch") == 0
    finally:
        release.set()


def test_runtime_local_unavailable_watch_reads_no_cloud_or_key(make_runtime, tmp_path, monkeypatch):
    import json
    from src.controllers.watch_controller import WatchController
    (tmp_path / "processing-intent.json").write_text(json.dumps({"schema_version": 1, "revision": 1, "mode": "local"}))
    source = tmp_path / "watched"; source.mkdir()
    path = source / "original.txt"; path.write_bytes(b"unready local fixture")
    WatchConfigStore(tmp_path / "watch_folders.json").add(WatchConfig("watch", str(source)))
    monkeypatch.setattr(ObserverFactory, "create", lambda _: MockObserver())
    monkeypatch.setattr(WatchController, "DEFAULT_DEBOUNCE_SECONDS", .01)
    keys = Credentials()
    runtime = make_runtime(live_config=cloud_config(), credential_store=keys,
        managed_adapter_factory=lambda *a, **k: pytest.fail("cloud fallback"),
        analysis_content_extractor=lambda *a, **k: pytest.fail("unready extraction"))
    runtime.watch_owner.controller._simulate_file_event("watch", str(path), FileEvent.CREATED)
    pump_until(lambda: runtime.watch_owner.notice("watch") == "local_unavailable", timeout=3)
    assert keys.calls == [] and path.exists() and runtime.file_operation_lane.owned_item_count == 0


def test_historic_widget_configs_are_loaded_without_rewriting_saved_bytes(make_runtime, tmp_path):
    import json
    source = tmp_path / "historic"; source.mkdir()
    config = tmp_path / "watch_folders.json"
    saved = json.dumps([dict(id="historic", source_dir=str(source), target_dir="", template_id="",
        recursive=True, mode="auto_apply", active=False, file_types=[])]).encode()
    config.write_bytes(saved)
    runtime = make_runtime()
    restored, = runtime.watch_owner.controller.list_configs()
    assert restored.mode is WatchMode.AUTO_APPLY and restored.status.value == "paused"
    assert config.read_bytes() == saved and runtime.watch_owner.available


@pytest.mark.parametrize("blocked", ["timer", "observer"])
def test_owned_real_observer_and_timer_close_retain_qt_until_actual_tail(make_runtime, tmp_path, monkeypatch, blocked):
    from src.controllers.watch_controller import WatchController
    from src.core.batch_analysis import BatchAnalysisService
    from shiboken6 import isValid
    source = tmp_path / "real-observer"; source.mkdir()
    path = source / "original.txt"; path.write_bytes(b"actual watchdog fixture")
    WatchConfigStore(tmp_path / "watch_folders.json").add(WatchConfig("watch", str(source)))
    monkeypatch.setattr(WatchController, "DEFAULT_DEBOUNCE_SECONDS", .01)
    monkeypatch.setattr(BatchAnalysisService, "run_prepared", lambda _, work, **kw: outcome(work))
    runtime = make_runtime(live_config=cloud_config())
    owner, entered, release = runtime.watch_owner, threading.Event(), threading.Event()
    observer = owner.controller._watches["watch"].observer
    assert observer.is_alive()
    if blocked == "timer":
        def decision(path): entered.set(); assert release.wait(5); return "allow"
        monkeypatch.setattr(owner.receipts, "decision", decision)
        owner.controller._simulate_file_event("watch", str(path), FileEvent.CREATED)
        assert entered.wait(3)
    else:
        stop = observer.stop
        def blocked_stop():
            result = stop()
            entered.set(); assert release.wait(5)
            return result
        monkeypatch.setattr(observer, "stop", blocked_stop)
    try:
        root, engine = runtime.root, runtime.engine
        assert runtime.cleanup(deadline=time.monotonic() + .02) is False
        assert runtime.watch_owner is owner and runtime.root is root
        assert isValid(root) and isValid(engine) and not owner.workers_idle
        assert entered.wait(3)
    finally:
        release.set()
    assert runtime.cleanup(deadline=time.monotonic() + 3)
    assert not observer.is_alive()


def test_native_readfile_actual_worker_tail_retained_without_hard_cancel(make_runtime, tmp_path, monkeypatch):
    from src.core import safe_file_move as native
    runtime, path = _active_runtime(make_runtime, tmp_path, monkeypatch)
    owner, entered, release = runtime.watch_owner, threading.Event(), threading.Event()
    read = native._kernel.ReadFile
    def delayed_read(*args):
        accepted = read(*args)
        entered.set(); assert release.wait(5)
        return accepted
    monkeypatch.setattr(native._kernel, "ReadFile", delayed_read)
    owner.controller._simulate_file_event("watch", str(path), FileEvent.CREATED)
    pump_until(entered.is_set, timeout=3)
    try:
        assert runtime.cleanup(deadline=time.monotonic() + .02) is False
        assert runtime.watch_owner is owner and not owner.receipts._reader.workers_idle
        assert path.exists()  # Observation does not grant or perform a move.
    finally:
        release.set()
    assert runtime.cleanup(deadline=time.monotonic() + 3)
    saved, = ReviewQueue(tmp_path / "watch_review_queue.json").items()
    assert saved.state is ReviewItemState.APPLIED  # Genuine committed outcome survives cancelled observation.


def test_batch_output_into_watch_is_suppressed_before_second_analysis(make_runtime, tmp_path, monkeypatch):
    from src.controllers.watch_controller import WatchController
    from src.core.batch_analysis import BatchAnalysisService
    source = tmp_path / "watched"; source.mkdir()
    outside = tmp_path / "batch-original.txt"; outside.write_bytes(b"shared Batch output")
    WatchConfigStore(tmp_path / "watch_folders.json").add(WatchConfig("watch", str(source), mode=WatchMode.AUTO_APPLY))
    monkeypatch.setattr(WatchController, "DEFAULT_DEBOUNCE_SECONDS", .01)
    calls = []
    def run(_, work, **kw): calls.append(work.source_path); return outcome(work)
    monkeypatch.setattr(BatchAnalysisService, "run_prepared", run)
    runtime = make_runtime(live_config=cloud_config())
    owner, events = runtime.watch_owner, []
    admit = owner.controller._admit_raw_file_event
    def record(*args, **kwargs): events.append(args[1]); return admit(*args, **kwargs)
    monkeypatch.setattr(owner.controller, "_admit_raw_file_event", record)
    batch = runtime.batch_controller
    batch.setTargetDirectory(str(source))
    batch.add_files([str(outside)])
    task_id, = batch.task_ids
    pump_until(lambda: batch.task_snapshot(task_id)["status"] == "review_pending", timeout=3)
    batch.applyTask(task_id)
    pump_until(lambda: runtime.file_operation_lane.workers_idle and (source / "suggestion.txt").exists(), timeout=3)
    pump_until(lambda: bool(events) and owner.guard.pending_count("watch") == 0, timeout=3)
    assert calls == [str(outside)] and not owner.results.items()
    assert events and (source / "suggestion.txt").read_bytes() == b"shared Batch output"


def test_self_event_hold_keeps_original_context_stale_after_mode_switch(make_runtime, tmp_path, monkeypatch):
    from src.core.rename_plan import RenamePlan, SourceFingerprint
    from src.services.file_operation_backend import FileOperationRequest
    calls = []
    def run(_, work, **kw): calls.append(work); return outcome(work)
    runtime, path = _active_runtime(make_runtime, tmp_path, monkeypatch, run=run)
    owner = runtime.watch_owner
    value = path.stat()
    plan = RenamePlan("synthetic-batch-row", str(path), SourceFingerprint(value.st_size, value.st_mtime_ns),
        "target.txt", str(path.parent), ".txt")
    reserved = runtime.file_operation_lane.reserve(FileOperationRequest("held", "apply", "batch", (plan,)))
    assert reserved is not None
    try:
        owner.controller._simulate_file_event("watch", str(path), FileEvent.CREATED)
        original, = owner.controller._pending_debounce.values()
        context = original.admission.work.context
        pump_until(lambda: owner.notice("watch") == "self_event_held", timeout=3)
        assert next(iter(owner.controller._pending_debounce.values())) is original
        runtime.processing_coordinator.selectLocal()
        assert not runtime.processing_coordinator.authority.is_current(context)
        assert runtime.file_operation_lane.cancel(reserved)
        pump_until(lambda: owner.guard.pending_count("watch") == 0, timeout=3)
        assert calls == [] and not owner.results.items()
    finally:
        runtime.file_operation_lane.cancel(reserved)


@pytest.mark.parametrize("entrypoint", ["poll", "refresh"])
def test_regular_bridge_retains_real_public_refresh_tail_during_reentrant_cleanup(make_runtime, entrypoint):
    import json
    from shiboken6 import isValid
    runtime = make_runtime()
    owner, root, engine = runtime.watch_owner, runtime.root, runtime.engine
    entered, witnesses, nested_idle = [False], [], []
    def close_inside_public_refresh():
        if entered[0]:
            nested_idle.append(owner.workers_idle)
            return
        entered[0] = True
        accepted = runtime.cleanup(deadline=time.monotonic() + .05)
        witnesses.append(dict(cleanup_return=accepted, root_retained=runtime.root is root,
            owner_retained=runtime.watch_owner is owner, root_valid=isValid(root),
            engine_valid=isValid(engine), active_tail_idle=owner.workers_idle))
        print("R1_FIX_BRIDGE_WITNESS=" + json.dumps(witnesses[-1]), flush=True)
        # A nested real public refresh must not retire the outer callback owner.
        owner._changed()
    owner.page.stateChanged.connect(close_inside_public_refresh)
    try:
        if entrypoint == "poll":
            owner._snapshot = None
            owner.poll()
        else:
            owner._changed()
    finally:
        assert runtime.cleanup(deadline=time.monotonic() + 3)
    assert len(witnesses) == 1
    witness, = witnesses
    assert witness["cleanup_return"] is False
    assert witness["root_retained"] and witness["owner_retained"]
    assert witness["root_valid"] and witness["engine_valid"]
    assert witness["active_tail_idle"] is False
    assert nested_idle and not any(nested_idle)
    assert not owner._timer.isActive()


@pytest.mark.parametrize("entrypoint", ["poll", "refresh"])
def test_bridge_exception_retires_depth_only_after_real_boundary_unwinds(make_runtime, monkeypatch, entrypoint):
    runtime = make_runtime()
    owner, idle_inside = runtime.watch_owner, []
    def interrupted_refresh():
        idle_inside.append(owner.workers_idle)
        raise RuntimeError("synthetic public refresh interruption")
    # Fault only at the real refresh boundary; do not fake child idle/Futures.
    with monkeypatch.context() as fault:
        fault.setattr(owner.page, "refresh", interrupted_refresh)
        with pytest.raises(RuntimeError, match="synthetic public refresh interruption"):
            if entrypoint == "poll":
                owner._snapshot = None
                owner.poll()
            else:
                owner._changed()
    assert idle_inside == [False]
    assert owner.workers_idle and not owner.closing
    assert runtime.cleanup(deadline=time.monotonic() + 3)
    assert not owner._timer.isActive()


@pytest.mark.parametrize("entrypoint", ["poll", "refresh"])
def test_bridge_rejects_non_owner_thread_without_refresh_or_depth_leak(make_runtime, entrypoint):
    runtime = make_runtime()
    owner, errors = runtime.watch_owner, []
    def call():
        try:
            if entrypoint == "poll": owner.poll()
            else: owner._changed()
        except RuntimeError as error:
            errors.append(str(error))
    worker = threading.Thread(target=call)
    worker.start(); worker.join(2)
    assert not worker.is_alive() and errors == ["watch_owner_thread_required"]
    assert owner.workers_idle

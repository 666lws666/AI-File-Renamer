"""Synthetic managed Watch analysis; real Qt delivery, no inference or credentials."""
from dataclasses import FrozenInstanceError, replace
import importlib
import os
from pathlib import Path
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QThread

from src.core.analysis_catalog import AnalysisCatalogSource, build_analysis_catalog
from src.core.batch_analysis import BatchAnalysisService
from src.core.degradation import ContentKind
from src.core.processing_analysis import AnalysisOutcome, CloudAnalysisCoverage
from src.core.processing_authority import ProcessingAuthority, ProcessingMode
from src.core.processing_identity import cloud_engine_fingerprint
from src.core.rename_plan import SourceFingerprint
from src.core.template_model import Template, TemplateField
from src.core.watch_config import WatchConfig
from src.models.app_config import AppConfig
from src.services.local_ai.preparation_protocol import PreparationCoverage


def api():
    return importlib.import_module("src.controllers.managed_watch_analysis")


def pump_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    assert predicate()


def fingerprint(path):
    """The synthetic observer's fingerprint computation is explicitly off Qt."""
    values, errors = [], []
    def read():
        try:
            value = os.stat(path, follow_symlinks=False)
            values.append(SourceFingerprint(value.st_size, value.st_mtime_ns))
        except BaseException as error:
            errors.append(error)
    thread = threading.Thread(target=read)
    thread.start(); thread.join(2)
    assert not thread.is_alive()
    if errors:
        raise errors[0]
    return values[0]


def outcome(work, **changes):
    result = AnalysisOutcome("suggestion.txt", work.context, "balanced", ContentKind.TEXT,
        "synthetic-engine", CloudAnalysisCoverage("text", sections_processed=1,
        sections_total=1), ())
    return replace(result, **changes)


@pytest.fixture
def lane(tmp_path, monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    assert app.thread().isCurrentThread()
    template = Template(id="one", name="Synthetic", pattern="{dcTitle}",
                        fields=(TemplateField("dcTitle", "Title"),))
    config = AppConfig(default_template_id="one", active_provider_id="active",
        provider_profiles=[dict(id="active", model="synthetic", base_url="https://example.invalid/v1",
            enabled=True, needs_connection_verification=False, capabilities=dict(text=True))])
    source = AnalysisCatalogSource(build_analysis_catalog(config, [template]))
    authority = ProcessingAuthority(initial_mode=ProcessingMode.CLOUD)
    authority.bind_cloud_engine(cloud_engine_fingerprint(source.get().active_profile))
    def forbidden(*args, **kwargs):
        pytest.fail("forbidden synthetic credential/adapter/extraction/legacy access")
    service = BatchAnalysisService(profile_provider=lambda: source.get().active_profile,
        credential_provider=forbidden, config_provider=lambda: source.get().settings,
        template_provider=lambda key: source.get().template(key), processing_authority=authority,
        local_inference_service=object(), local_preparation_service=object(),
        managed_adapter_factory=forbidden, capture_guard=source.guard, content_extractor=forbidden)
    service.analyze = forbidden
    service.run_work = forbidden
    monkeypatch.setattr(service, "run_prepared", lambda work, **kwargs: outcome(work))
    watch = WatchConfig(id="watch", source_dir=str(tmp_path), template_id="one")
    owners, releases, threads = [], [], []
    class Lane:
        def make(self, callback=None, binding=None, cls=None, **kwargs):
            owner = (cls or api().ManagedWatchAnalysisDelivery)(service, authority,
                capture_guard=source.guard, is_binding_current=binding or (lambda event: True),
                on_result=callback or self.seen.append, **kwargs)
            owners.append(owner)
            return owner

        def capture(self, owner, name="synthetic.txt", event_id="event"):
            path = tmp_path / name
            if not path.exists():
                path.write_text("synthetic fixture", encoding="utf-8")
            admission = owner.ingress.capture(watch, "incarnation", str(path), event_id)
            assert admission is not None
            return admission, path

        def post(self, owner, name="synthetic.txt", event_id="event"):
            admission, path = self.capture(owner, name, event_id)
            assert owner.ingress.post_stable(admission, fingerprint(path))
            return admission, path

        def block(self):
            entered, release = threading.Event(), threading.Event()
            releases.append(release)
            def run(work, **kwargs):
                self.calls.append(work)
                entered.set()
                assert release.wait(3), "synthetic runner release deadline"
                return outcome(work)
            monkeypatch.setattr(service, "run_prepared", run)
            return entered, release
    result = Lane()
    result.seen, result.calls = [], []
    result.service, result.authority, result.source, result.watch = service, authority, source, watch
    result.releases, result.threads = releases, threads
    yield result
    for release in releases:
        release.set()
    for thread in threads:
        thread.join(3)
        assert not thread.is_alive()
    for owner in owners:
        owner.begin_close()
        assert owner.drain(time.monotonic() + 3), "owned Qt/worker tail leaked"
        assert owner.workers_idle and owner.owned_count == 0
        assert not owner._timer.isActive()
        for thread in owner._pool._threads:
            thread.join(2)
            assert not thread.is_alive()


def test_authentic_outcome_runs_off_qt_and_publishes_exact_identity_on_qt(lane, monkeypatch):
    runner_threads, callback_threads = [], []
    def run(work, **kwargs):
        runner_threads.append(threading.get_ident())
        return outcome(work)
    def consume(result):
        lane.seen.append(result); callback_threads.append(threading.get_ident())
    monkeypatch.setattr(lane.service, "run_prepared", run)
    owner = lane.make(consume)
    original = owner._fingerprint
    def check(path):
        assert threading.get_ident() != owner._ident
        return original(path)
    monkeypatch.setattr(owner.__class__, "_fingerprint", staticmethod(check))
    admission, _ = lane.post(owner)
    pump_until(lambda: bool(lane.seen))
    assert lane.seen[0].event.admission is admission
    assert lane.seen[0].outcome.context is admission.work.context
    assert lane.seen[0].metadata.confidence is None
    assert lane.seen[0].failure == ""
    assert runner_threads and runner_threads[0] != threading.get_ident()
    assert callback_threads == [threading.get_ident()]
    with pytest.raises(FrozenInstanceError):
        lane.seen[0].failure = "changed"
    assert owner.drain(time.monotonic() + 2)


def test_cloned_forged_and_duplicate_stable_delivery(lane):
    entered, release = lane.block()
    owner = lane.make()
    admission, _ = lane.post(owner)
    # Recover the authentic object from ingress solely to inject duplicate/private traffic.
    real = owner.ingress._issued[next(iter(owner.ingress._issued))][1].event
    owner._incoming.emit(replace(real))
    owner._incoming.emit(object())
    owner._incoming.emit(real)
    pump_until(entered.is_set)
    assert lane.calls == [admission.work] and owner.owned_count == 1
    release.set()
    pump_until(lambda: owner.workers_idle)
    assert len(lane.seen) == 1 and lane.seen[0].event is real


def test_unavailable_failure_exact_snapshot_no_runner_or_source_io(lane, monkeypatch):
    lane.authority.select_local()
    owner = lane.make()
    failure = owner.ingress.capture(lane.watch, "incarnation", str(Path(lane.watch.source_dir) / "missing.txt"), "event")
    snapshot = failure.snapshot
    monkeypatch.setattr(lane.service, "run_prepared", lambda *a, **k: pytest.fail("failure ran"))
    monkeypatch.setattr(owner.__class__, "_fingerprint", lambda *a: pytest.fail("failure source I/O"))
    assert owner.ingress.post_failure(failure)
    assert not owner.workers_idle and owner.owned_count == 1
    pump_until(lambda: owner.workers_idle)
    assert len(lane.seen) == 1
    assert lane.seen[0].event is failure and lane.seen[0].event.snapshot is snapshot
    assert lane.seen[0].failure == "local_unavailable"
    assert lane.seen[0].outcome is lane.seen[0].metadata is None


def test_stale_duplicate_cannot_retire_still_running_owner(lane):
    entered, release = lane.block()
    owner = lane.make(pending_limit=1)
    admission, path = lane.post(owner)
    pump_until(entered.is_set)
    real = next(iter(owner._owners.values())).event
    lane.authority.invalidate_work()
    owner._incoming.emit(real)
    QCoreApplication.processEvents()
    assert owner.owned_count == 1 and not owner.workers_idle
    assert not admission.cancel_event.is_set()
    assert owner.ingress.capture(lane.watch, "incarnation", str(path), "overflow") is None
    release.set()
    pump_until(lambda: owner.workers_idle)
    assert admission.cancel_event.is_set() and not lane.seen


@pytest.mark.parametrize("outer_rejection", ["binding", "authority"])
def test_initial_binding_reentrancy_cannot_retire_nested_running_owner(lane, outer_rejection):
    entered, release = lane.block()
    first, bound = [True], [True]
    nested_owners = []
    def binding(event):
        if first[0]:
            first[0] = False
            assert not owner._owners
            owner._incoming.emit(event)
            QCoreApplication.processEvents()
            assert entered.wait(2), "nested real worker did not start"
            nested_owners.append(owner._owners[id(event)])
            if outer_rejection == "authority":
                lane.authority.invalidate_work()
                return True
            bound[0] = False
        return bound[0]
    owner = lane.make(binding=binding, pending_limit=1)
    admission, path = lane.post(owner)
    QCoreApplication.processEvents()
    assert len(nested_owners) == 1
    assert owner._owners[id(nested_owners[0].event)] is nested_owners[0]
    assert owner.owned_count == 1 and not owner.workers_idle
    assert not admission.cancel_event.is_set()
    assert owner.ingress.capture(lane.watch, "incarnation", str(path), "overflow") is None
    assert lane.calls == [admission.work]
    release.set()
    assert owner.drain(time.monotonic() + 2)
    assert admission.cancel_event.is_set() and not lane.seen


@pytest.mark.parametrize("outer_rejection", ["binding", "authority"])
def test_initial_failure_binding_reentrancy_retains_exact_callback_owner(lane, monkeypatch, outer_rejection):
    lane.authority.select_local()
    first, bound = [True], [True]
    callback_owners, observations = [], []
    def binding(event):
        if first[0]:
            first[0] = False
            assert not owner._owners
            owner._incoming.emit(event)
            QCoreApplication.processEvents()
            if outer_rejection == "authority":
                lane.authority.invalidate_work()
                return True
            bound[0] = False
        return bound[0]
    def consume(result):
        assert result.event is failure and result.event.snapshot is snapshot
        callback_owners.append(owner._owners[id(failure)])
        observations.append((owner.workers_idle, owner.owned_count))
        owner._incoming.emit(failure)
        QCoreApplication.processEvents()
        assert owner._owners[id(failure)] is callback_owners[0]
        observations.append((owner.workers_idle, owner.owned_count))
        assert owner.ingress.capture(lane.watch, "incarnation", path, "overflow") is None
        lane.seen.append(result)
    owner = lane.make(consume, binding=binding, pending_limit=1)
    path = str(Path(lane.watch.source_dir) / "missing.txt")
    failure = owner.ingress.capture(lane.watch, "incarnation", path, "event")
    snapshot = failure.snapshot
    monkeypatch.setattr(lane.service, "run_prepared", lambda *a, **k: pytest.fail("failure ran"))
    monkeypatch.setattr(owner.__class__, "_fingerprint", lambda *a: pytest.fail("failure source I/O"))
    assert owner.ingress.post_failure(failure)
    assert owner.drain(time.monotonic() + 2)
    assert len(callback_owners) == len(lane.seen) == 1
    assert observations == [(False, 1), (False, 1)]
    assert lane.seen[0].failure == "local_unavailable"
    assert lane.seen[0].outcome is lane.seen[0].metadata is None


def test_failure_nested_duplicate_is_not_republished_or_retired_inside_callback(lane):
    lane.authority.select_local()
    observations = []
    def consume(result):
        lane.seen.append(result)
        if len(lane.seen) == 1:
            owner._incoming.emit(result.event)
            QCoreApplication.processEvents()
            observations.append((owner.workers_idle, owner.owned_count))
    owner = lane.make(consume)
    failure = owner.ingress.capture(lane.watch, "incarnation",
        str(Path(lane.watch.source_dir) / "missing.txt"), "event")
    assert owner.ingress.post_failure(failure)
    pump_until(lambda: owner.workers_idle)
    assert len(lane.seen) == 1 and lane.seen[0].event is failure
    assert observations == [(False, 1)]


@pytest.mark.parametrize("invalid", ["none", "base_exception"])
def test_empty_outcome_and_base_exception_future_are_safe_failures(lane, monkeypatch, invalid, capsys):
    def run(work, **kwargs):
        if invalid == "base_exception":
            raise SystemExit("SYNTHETIC_BASE_SECRET C:/private")
        return None
    monkeypatch.setattr(lane.service, "run_prepared", run)
    owner = lane.make(); lane.post(owner)
    pump_until(lambda: owner.workers_idle)
    assert lane.seen[0].failure == ("invalid_outcome" if invalid == "none" else "analysis_failed")
    assert lane.seen[0].outcome is lane.seen[0].metadata is None
    assert "SYNTHETIC_BASE_SECRET" not in str(capsys.readouterr())


@pytest.mark.parametrize("when", ["before_intake", "during_runner"])
def test_stale_generation_suppresses_and_retires_actual_ownership(lane, when):
    entered, release = lane.block()
    owner = lane.make()
    admission, _ = lane.post(owner)
    if when == "during_runner":
        pump_until(entered.is_set)
    lane.authority.invalidate_work()
    if when == "during_runner":
        assert not owner.workers_idle and owner.owned_count == 1
        assert not admission.cancel_event.is_set()
    release.set()
    pump_until(lambda: owner.workers_idle)
    assert not lane.seen and len(lane.calls) == (when == "during_runner")
    assert admission.cancel_event.is_set()


def test_cancel_incarnation_during_runner_keeps_owner_until_actual_tail(lane):
    entered, release = lane.block()
    owner = lane.make(); admission, _ = lane.post(owner)
    pump_until(entered.is_set)
    owner.ingress.cancel_incarnation("watch", "incarnation")
    assert admission.cancel_event.is_set()
    assert owner.owned_count == 1 and not owner.workers_idle
    assert not owner.drain(time.monotonic() + .03)
    release.set()
    assert owner.drain(time.monotonic() + 2)
    assert not lane.seen


@pytest.mark.parametrize("change", ["removed", "replaced"])
@pytest.mark.parametrize("when", ["before_intake", "during_runner"])
def test_binding_removed_or_replaced_suppresses_result(lane, change, when):
    current = ["incarnation"]
    entered, release = lane.block()
    owner = lane.make(binding=lambda event: current[0] == event.admission.incarnation)
    admission, _ = lane.post(owner)
    if when == "during_runner":
        pump_until(entered.is_set)
    current[0] = None if change == "removed" else "replacement"
    release.set()
    pump_until(lambda: owner.workers_idle)
    assert not lane.seen and len(lane.calls) == (when == "during_runner")
    assert admission.cancel_event.is_set()


def test_reentrant_binding_cannot_publish_after_authority_change(lane):
    count = [0]
    def binding(event):
        count[0] += 1
        if count[0] == 3:  # completion check, not admission/start checks
            lane.authority.invalidate_work()
        return True
    owner = lane.make(binding=binding)
    lane.post(owner)
    pump_until(lambda: owner.workers_idle)
    assert count[0] == 3 and not lane.seen


@pytest.mark.parametrize("when", ["before_start", "during_runner"])
def test_source_replacement_or_mutation_returns_source_changed(lane, when):
    entered, release = lane.block()
    owner = lane.make()
    _, path = lane.post(owner)
    if when == "during_runner":
        pump_until(entered.is_set)
        path.write_text("mutated synthetic fixture with changed size", encoding="utf-8")
    else:
        replacement = path.with_name("replacement.tmp")
        replacement.write_text("different source", encoding="utf-8")
        os.replace(replacement, path)
    release.set()
    pump_until(lambda: owner.workers_idle)
    assert len(lane.seen) == 1 and lane.seen[0].failure == "source_changed"
    assert lane.seen[0].outcome is lane.seen[0].metadata is None
    assert len(lane.calls) == (when == "during_runner")


@pytest.mark.parametrize("kind", ["missing", "directory", "symlink"])
def test_missing_nonregular_and_symlink_source_rejected_safely(lane, kind, monkeypatch):
    owner = lane.make()
    _, path = lane.post(owner)
    path.unlink()
    if kind == "directory":
        path.mkdir()
    elif kind == "symlink":
        target = path.with_name("target.txt"); target.write_text("synthetic target")
        try:
            path.symlink_to(target)
        except OSError:
            # Windows without symlink privilege: exercise the exact non-follow stat result.
            original = os.stat
            def symbolic(value, **kwargs):
                if str(value) == str(path):
                    assert kwargs == {"follow_symlinks": False}
                    return os.stat_result((0o120777, 0, 0, 1, 0, 0, 16, 0, 0, 0))
                return original(value, **kwargs)
            monkeypatch.setattr("src.controllers.managed_watch_analysis.os.stat", symbolic)
    monkeypatch.setattr(lane.service, "run_prepared", lambda *a, **k: pytest.fail("invalid source ran"))
    pump_until(lambda: owner.workers_idle)
    assert lane.seen[0].failure == "source_changed"
    assert lane.seen[0].outcome is lane.seen[0].metadata is None


@pytest.mark.parametrize("invalid", ["extension", "reserved", "parent", "empty_part", "backslash",
    "context", "type", "coverage_type", "quality", "warnings", "kind"])
def test_invalid_outcome_is_bounded_no_suggestion(lane, monkeypatch, invalid):
    def run(work, **kwargs):
        good = outcome(work)
        return {
            "extension": lambda: replace(good, suggested_name="suggestion.pdf"),
            "reserved": lambda: replace(good, suggested_name="CON.txt"),
            "parent": lambda: replace(good, suggested_name="../suggestion.txt"),
            "empty_part": lambda: replace(good, suggested_name="/suggestion.txt"),
            "backslash": lambda: replace(good, suggested_name="dir\\suggestion.txt"),
            "context": lambda: replace(good, context=replace(work.context)),
            "type": lambda: object(),
            "coverage_type": lambda: replace(good, coverage=PreparationCoverage("text")),
            "quality": lambda: replace(good, effective_quality="secret-quality"),
            "warnings": lambda: replace(good, warning_codes=("C:/synthetic-secret",)),
            "kind": lambda: replace(good, content_kind="text"),
        }[invalid]()
    monkeypatch.setattr(lane.service, "run_prepared", run)
    owner = lane.make(); lane.post(owner)
    pump_until(lambda: owner.workers_idle)
    assert lane.seen[0].failure == "invalid_outcome"
    assert lane.seen[0].outcome is lane.seen[0].metadata is None


def test_synthetic_exception_text_and_path_do_not_escape(lane, monkeypatch, capsys, caplog):
    secret = "SYNTHETIC_SECRET C:/synthetic/private/path.txt"
    def run(work, **kwargs):
        raise RuntimeError(secret)
    monkeypatch.setattr(lane.service, "run_prepared", run)
    owner = lane.make(); lane.post(owner)
    pump_until(lambda: owner.workers_idle)
    assert lane.seen[0].failure == "analysis_failed"
    assert secret not in repr(lane.seen[0]) + caplog.text + str(capsys.readouterr())


def test_exact_capacity_reserved_before_capture_and_queued_ingress_counts(lane, monkeypatch):
    captured = []
    original = lane.service.capture_work
    def observe(*args, **kwargs):
        captured.append(1); return original(*args, **kwargs)
    monkeypatch.setattr(lane.service, "capture_work", observe)
    owner = lane.make(pending_limit=2)
    lane.post(owner, event_id="one"); lane.post(owner, event_id="two")
    assert owner.owned_count == 2 and not owner.workers_idle
    assert owner.ingress.capture(lane.watch, "incarnation", str(Path(lane.watch.source_dir) / "overflow.txt"), "overflow") is None
    assert len(captured) == 2
    owner.begin_close()
    assert owner.owned_count == 2 and not owner.workers_idle
    assert owner.drain(time.monotonic() + 2)
    assert not lane.seen


@pytest.mark.parametrize("tail", ["before_emit", "after_emit"])
def test_future_done_and_blocked_emission_tail_retain_submission_capacity(lane, tail):
    held, release = threading.Event(), threading.Event()
    lane.releases.append(release)
    class HeldDelivery(api().ManagedWatchAnalysisDelivery):
        def _emit(self, owner, future):
            # Real queued Qt signal, actual Future, deterministic actual emission tail.
            try:
                completion = future.result()
                with owner.lock:
                    owner.issued = completion
                if tail == "before_emit":
                    held.set(); assert release.wait(3)
                self._completed.emit(completion)
                if tail == "after_emit":
                    held.set(); assert release.wait(3)
            finally:
                owner.bridge_done.set()
    # Force Future completion only after its callback is registered off Qt.
    entered, runner_release = lane.block()
    owner = lane.make(cls=HeldDelivery, max_workers=1, pending_limit=2)
    lane.post(owner, event_id="one"); lane.post(owner, event_id="two")
    pump_until(entered.is_set); runner_release.set()
    pump_until(held.is_set)
    actual = next(iter(owner._owners.values()))
    assert actual.future.done() and not actual.bridge_done.is_set()
    assert len(lane.calls) == 1 and owner.owned_count == 2 and not owner.workers_idle
    if tail == "after_emit":
        pump_until(lambda: len(lane.seen) == 1)
        owner.poll()
        assert len(lane.calls) == 1 and owner.owned_count == 2
    release.set()
    pump_until(lambda: owner.workers_idle)
    assert len(lane.calls) == len(lane.seen) == 2


def test_submission_failure_owns_queued_acknowledgement_and_drains(lane, monkeypatch):
    owner = lane.make()
    def failed(*args, **kwargs):
        raise RuntimeError("SYNTHETIC_SUBMISSION_SECRET C:/private")
    monkeypatch.setattr(owner._pool, "submit", failed)
    admission, _ = lane.post(owner)
    QCoreApplication.processEvents()  # intake posts a second, genuinely queued signal
    assert owner.owned_count == 1 and not owner.workers_idle and not lane.seen
    pump_until(lambda: owner.workers_idle)
    assert len(lane.seen) == 1 and lane.seen[0].event.admission is admission
    assert lane.seen[0].failure == "analysis_failed"


def test_close_blocked_worker_finite_deadline_then_actual_release_and_drain(lane):
    entered, release = lane.block()
    owner = lane.make(); admission, _ = lane.post(owner)
    pump_until(entered.is_set)
    start = time.monotonic(); owner.begin_close()
    assert time.monotonic() - start < .5
    assert admission.cancel_event.is_set() and not owner.workers_idle
    assert not owner.drain(time.monotonic() + .03)
    assert owner.owned_count == 1
    release.set()
    assert owner.drain(time.monotonic() + 2)
    assert not lane.seen


def test_close_queued_failure_ingress_and_unstarted_work_without_fallback(lane):
    entered, release = lane.block()
    owner = lane.make(max_workers=1)
    lane.post(owner, event_id="running")
    pump_until(entered.is_set)
    lane.post(owner, event_id="queued")
    QCoreApplication.processEvents()
    assert len(owner._queued) == 1
    lane.authority.select_local()
    failure = owner.ingress.capture(lane.watch, "incarnation", str(Path(lane.watch.source_dir) / "missing.txt"), "failure")
    assert owner.ingress.post_failure(failure)
    owner.begin_close()
    assert not owner.workers_idle
    release.set()
    assert owner.drain(time.monotonic() + 2)
    assert len(lane.calls) == 1 and not lane.seen


@pytest.mark.parametrize("raise_callback", [False, True])
def test_nested_callback_remains_owned_and_exception_closes_safely(lane, raise_callback, capsys, caplog):
    observations = []
    def consume(result):
        observations.append((owner.workers_idle, owner.owned_count))
        QCoreApplication.processEvents()
        owner.poll()
        observations.append((owner.workers_idle, owner.owned_count))
        lane.seen.append(result)
        if raise_callback:
            raise RuntimeError("SYNTHETIC_CALLBACK_SECRET C:/private")
    owner = lane.make(consume); lane.post(owner)
    pump_until(lambda: owner.workers_idle)
    assert observations == [(False, 1), (False, 1)]
    assert owner.publication_failed is raise_callback
    assert "SYNTHETIC_CALLBACK_SECRET" not in caplog.text + str(capsys.readouterr())
    if raise_callback:
        assert owner.ingress.capture(lane.watch, "incarnation", str(Path(lane.watch.source_dir) / "closed.txt"), "closed") is None


def test_two_real_workers_and_queued_work_reuse_only_after_callback(lane, monkeypatch):
    lock = threading.Lock(); releases = [threading.Event() for _ in range(3)]
    lane.releases.extend(releases)
    entered = [threading.Event() for _ in range(3)]
    running = [0, 0]
    def run(work, **kwargs):
        index = int(work.task_id)
        with lock:
            lane.calls.append(work); running[0] += 1; running[1] = max(running)
        entered[index].set(); assert releases[index].wait(3)
        with lock:
            running[0] -= 1
        return outcome(work)
    def consume(result):
        assert not owner.workers_idle
        if result.event.admission.event_id == "0":
            QCoreApplication.processEvents(); owner.poll()
            assert not entered[2].is_set()
        lane.seen.append(result)
    monkeypatch.setattr(lane.service, "run_prepared", run)
    owner = lane.make(consume)
    for index in range(3):
        lane.post(owner, name=f"synthetic-{index}.txt", event_id=str(index))
    pump_until(lambda: entered[0].is_set() and entered[1].is_set())
    assert not entered[2].is_set() and owner.owned_count == 3
    releases[0].set()
    pump_until(entered[2].is_set)
    assert lane.seen[0].event.admission.event_id == "0"
    releases[1].set(); releases[2].set()
    pump_until(lambda: owner.workers_idle)
    assert running[1] == 2 and len(lane.calls) == len(lane.seen) == 3


def test_wrong_python_and_qt_thread_rejected_owner_remains_usable(lane):
    owner = lane.make(); errors = []
    calls = [lambda: owner.owned_count, lambda: owner.workers_idle,
        lambda: owner.publication_failed, owner.poll, owner.begin_close,
        lambda: owner.drain(time.monotonic() + .1),
        lambda: owner._accept_event(object()), lambda: owner._accept_completion(object())]
    def foreign():
        for call in calls:
            try:
                call()
            except RuntimeError as error:
                errors.append(str(error))
    class ForeignQt(QThread):
        def run(self):
            foreign()
    python_thread = threading.Thread(target=foreign)
    python_thread.start(); python_thread.join(2)
    assert not python_thread.is_alive()
    qt_thread = ForeignQt(); qt_thread.start()
    assert qt_thread.wait(2000)
    assert errors == ["watch_owner_thread_required"] * (len(calls) * 2)
    assert owner.workers_idle and not owner.publication_failed
    lane.post(owner); pump_until(lambda: owner.workers_idle)
    assert len(lane.seen) == 1


@pytest.mark.parametrize("kwargs", [{"max_workers": 0}, {"max_workers": 3}, {"max_workers": True},
    {"pending_limit": 0}, {"pending_limit": 1001}, {"pending_limit": True}])
def test_invalid_bounds_rejected_before_executor_creation(lane, kwargs):
    with pytest.raises(ValueError, match="^invalid_managed_watch_owner$"):
        lane.make(**kwargs)


@pytest.mark.parametrize("deadline", [float("nan"), float("inf"), True, "later"])
def test_invalid_drain_deadline_rejected(lane, deadline):
    owner = lane.make()
    with pytest.raises(ValueError, match="^invalid_watch_drain_deadline$"):
        owner.drain(deadline)


def test_start_gate_holds_exact_owner_capacity_then_timer_starts_same_work(lane, monkeypatch):
    allowed, checks = [False], []
    def gate(event):
        checks.append(event)
        return allowed[0]
    def run(work, **kwargs):
        lane.calls.append(work)
        return outcome(work)
    monkeypatch.setattr(lane.service, "run_prepared", run)
    owner = lane.make(can_start=gate, pending_limit=1)
    admission, path = lane.post(owner)
    pump_until(lambda: bool(checks))
    owned = next(iter(owner._owners.values()))
    assert owned.event.admission is admission and owned.future is None
    assert owner.owned_count == 1 and not owner.workers_idle
    assert not admission.cancel_event.is_set() and not lane.calls and not owner._pool._threads
    assert owner.ingress.capture(lane.watch, "incarnation", str(path), "overflow") is None
    checks.clear()
    owner.poll()
    assert checks == [owned.event] and owner._queued == [owned]
    allowed[0] = True
    pump_until(lambda: owner.workers_idle)
    assert lane.calls == [admission.work]
    assert len(lane.seen) == 1 and lane.seen[0].event is owned.event


def test_start_gate_bounded_pass_allows_ready_work_behind_held_work(lane, monkeypatch):
    allowed, checks = [False], []
    def gate(event):
        checks.append(event.admission.event_id)
        return allowed[0] or event.admission.event_id == "ready"
    def run(work, **kwargs):
        lane.calls.append(work)
        return outcome(work)
    monkeypatch.setattr(lane.service, "run_prepared", run)
    owner = lane.make(can_start=gate, max_workers=1)
    held, _ = lane.post(owner, event_id="held")
    ready, _ = lane.post(owner, event_id="ready")
    pump_until(lambda: len(lane.seen) == 1)
    assert lane.calls == [ready.work] and owner.owned_count == 1
    exact = next(iter(owner._owners.values()))
    checks.clear(); owner.poll()
    assert checks == ["held"] and owner._queued == [exact]
    assert not held.cancel_event.is_set() and exact.future is None
    allowed[0] = True
    pump_until(lambda: owner.workers_idle)
    assert lane.calls == [ready.work, held.work]
    assert lane.seen[1].event is exact.event


@pytest.mark.parametrize("returned", [False, None, 1, "ready", object(), "exception"])
def test_start_gate_requires_exact_true_and_exception_holds_fail_closed(lane, returned):
    checks, allowed = [], [False]
    def gate(event):
        checks.append(event)
        if allowed[0]:
            return True
        if returned == "exception":
            raise RuntimeError("synthetic gate failure")
        return returned
    owner = lane.make(can_start=gate)
    admission, _ = lane.post(owner)
    pump_until(lambda: bool(checks))
    exact = next(iter(owner._owners.values()))
    assert exact.future is None and owner.owned_count == 1
    assert not admission.cancel_event.is_set() and not lane.seen and not owner._pool._threads
    allowed[0] = True
    pump_until(lambda: owner.workers_idle)
    assert len(lane.seen) == 1 and lane.seen[0].event is exact.event


def test_reentrant_start_gate_duplicate_qt_intake_preserves_exact_owner(lane):
    entered, release = lane.block()
    checks, exact = [], []
    def gate(event):
        checks.append(event)
        exact.append(owner._owners[id(event)])
        owner._incoming.emit(event)
        QCoreApplication.processEvents()
        owner.poll()
        assert owner._owners[id(event)] is exact[0]
        return True
    owner = lane.make(can_start=gate, pending_limit=1)
    admission, _ = lane.post(owner)
    pump_until(entered.is_set)
    assert len(checks) == 2 and checks[0] is checks[1] and lane.calls == [admission.work]
    release.set(); pump_until(lambda: owner.workers_idle)
    assert len(lane.seen) == 1 and lane.seen[0].event is checks[0]


@pytest.mark.parametrize("change", ["close", "authority", "cancel", "binding"])
def test_reentrant_start_gate_cannot_submit_withdrawn_owner(lane, change):
    bound, checks = [True], []
    def gate(event):
        checks.append(event)
        if change == "close": owner.begin_close()
        elif change == "authority": lane.authority.invalidate_work()
        elif change == "cancel": owner.ingress.cancel_incarnation("watch", "incarnation")
        else: bound[0] = False
        QCoreApplication.processEvents()
        return True
    owner = lane.make(can_start=gate, binding=lambda event: bound[0])
    admission, _ = lane.post(owner)
    pump_until(lambda: bool(checks))
    assert owner.drain(time.monotonic() + 1)
    assert not owner._pool._threads and not lane.seen
    assert admission.cancel_event.is_set()


@pytest.mark.parametrize("change", ["close", "authority", "cancel"])
def test_held_queue_retires_on_withdrawal_and_closes_without_worker(lane, change):
    checks = []
    owner = lane.make(can_start=lambda event: (checks.append(event), False)[1])
    admission, _ = lane.post(owner)
    pump_until(lambda: bool(checks))
    if change == "close": owner.begin_close()
    elif change == "authority": lane.authority.select_local()
    else: owner.ingress.cancel_incarnation("watch", "incarnation")
    pump_until(lambda: owner.workers_idle)
    assert admission.cancel_event.is_set() and not lane.seen and not owner._pool._threads
    owner.begin_close()
    assert owner.drain(time.monotonic() + 1) and not owner._timer.isActive()


def test_admitted_failure_bypasses_start_gate_without_io_or_worker(lane, monkeypatch):
    lane.authority.select_local()
    def forbidden(*args, **kwargs):
        pytest.fail("held admission failure must not use start gate, source or inference")
    owner = lane.make(can_start=forbidden)
    monkeypatch.setattr(owner.__class__, "_fingerprint", forbidden)
    monkeypatch.setattr(lane.service, "run_prepared", forbidden)
    failure = owner.ingress.capture(lane.watch, "incarnation",
        str(Path(lane.watch.source_dir) / "missing.txt"), "failure")
    assert owner.ingress.post_failure(failure)
    owner._incoming.emit(failure)
    pump_until(lambda: owner.workers_idle)
    assert len(lane.seen) == 1 and lane.seen[0].event is failure
    assert lane.seen[0].failure == "local_unavailable" and not owner._pool._threads


@pytest.mark.parametrize("invalid", [False, True, 0, "ready", object()])
def test_invalid_start_gate_rejected_before_timer_or_executor(lane, monkeypatch, invalid):
    created = []
    def forbidden(*args, **kwargs):
        created.append(1)
        pytest.fail("invalid gate constructed an orphan timer/executor")
    monkeypatch.setattr(api(), "ThreadPoolExecutor", forbidden)
    monkeypatch.setattr(api(), "QTimer", forbidden)
    with pytest.raises(TypeError, match="^invalid_managed_watch_start_predicate$"):
        lane.make(can_start=invalid)
    assert not created


@pytest.mark.parametrize("close_check", [2, 3])
def test_binding_reentrant_close_during_scheduling_retires_only_unsubmitted_owner(lane, close_check):
    checks = []
    def binding(event):
        checks.append(event)
        if len(checks) == close_check:
            owned = owner._owners[id(event)]
            assert owned.future is None and owned.issued is None
            owner.begin_close()
            QCoreApplication.processEvents()
        return True
    owner = lane.make(binding=binding, can_start=lambda event: True)
    admission, _ = lane.post(owner)
    pump_until(lambda: len(checks) >= close_check)
    assert owner.drain(time.monotonic() + 1)
    assert not owner._timer.isActive() and not owner._pool._threads and not lane.seen
    assert admission.cancel_event.is_set()


@pytest.mark.parametrize("change", ["close", "authority", "cancel", "retire"])
def test_final_readiness_boundary_rechecks_exact_owner_and_authentication(lane, change):
    checks = []
    def gate(event):
        checks.append(event)
        if len(checks) == 2:
            if change == "close": owner.begin_close()
            elif change == "authority": lane.authority.invalidate_work()
            elif change == "cancel": owner.ingress.cancel_incarnation("watch", "incarnation")
            else: owner.ingress.retire(event)
            owner._incoming.emit(event)
            QCoreApplication.processEvents()
        return True
    owner = lane.make(can_start=gate)
    admission, _ = lane.post(owner)
    QCoreApplication.processEvents()
    assert len(checks) == 2
    assert owner.drain(time.monotonic() + 1)
    assert not owner._pool._threads and not lane.seen and admission.cancel_event.is_set()


@pytest.mark.parametrize("returned", [False, None, 1, "ready", "exception"])
def test_final_readiness_requires_exact_true_and_holds_on_exception(lane, returned):
    checks, allowed = [], [False]
    def gate(event):
        checks.append(event)
        if len(checks) == 1 or allowed[0]:
            return True
        if returned == "exception":
            raise RuntimeError("synthetic final readiness failure")
        return returned
    owner = lane.make(can_start=gate, pending_limit=1)
    admission, _ = lane.post(owner)
    QCoreApplication.processEvents()
    assert len(checks) >= 2
    exact = owner._owners[id(checks[0])]
    assert exact.future is None and owner._queued == [exact] and owner.owned_count == 1
    assert not admission.cancel_event.is_set() and not lane.seen and not owner._pool._threads
    allowed[0] = True
    pump_until(lambda: owner.workers_idle)
    assert len(lane.seen) == 1 and lane.seen[0].event is exact.event

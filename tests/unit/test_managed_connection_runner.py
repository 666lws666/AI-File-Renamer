"""Actual worker and queued Qt probes; synthetic fixed services only."""
from threading import Event, get_ident
from pathlib import Path
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QThread
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from src.controllers.managed_connection_runner import ManagedConnectionRunner, ProbeRequest
from src.controllers.settings_controller import SettingsController
from src.core.connection_test import ConnectionOutcome, ConnectionResult
from src.core.processing_authority import ProcessingAuthority, ProcessingMode
from src.core.provider_presets import create_profile_from_preset
from src.providers.openai_compatible import ProcessingDispatch
from src.models.app_config import AppConfig
from tests.unit.test_settings_processing_policy import CountingStore


def pump(app, predicate, timeout=3):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        app.processEvents()
        if predicate():
            return
        time.sleep(.002)
    assert predicate(), "bounded Qt delivery timeout"


@pytest.fixture
def owned():
    app = QApplication.instance() or QApplication([])
    targets, releases = [], []
    yield app, targets, releases
    for release in releases:
        release.set()
    for target in targets:
        target.begin_close()
    pump(app, lambda: all(target.workers_idle for target in targets))
    for target in targets:
        assert target.thread() == QThread.currentThread()
        target.deleteLater()
        QCoreApplication.sendPostedEvents(target, QEvent.Type.DeferredDelete)
        assert not isValid(target)


def request(authority, number):
    profile = create_profile_from_preset("deepseek", profile_id="deepseek")
    event = Event()
    context = authority.capture_cloud_probe(candidate_fingerprint="a" * 64,
        candidate_model=profile.model, request_id=str(number), task_cancel_event=event)
    return ProbeRequest(str(number), 1, 1, "candidate", profile, "fake-key", "typed",
        "b" * 64, ProcessingDispatch(authority, context))


def test_bounded_worker_latest_pending_owner_delivery_and_actual_close(owned):
    app, targets, releases = owned
    entered, release = Event(), Event()
    releases.append(release)
    calls, delivery_threads = [], []
    owner = get_ident()
    def service(profile, key, *, processing_dispatch):
        calls.append((processing_dispatch.context.request_id, get_ident()))
        entered.set()
        assert release.wait(3)
        return ConnectionResult(ConnectionOutcome.SUCCESS)
    runner = ManagedConnectionRunner(service)
    targets.append(runner)
    runner.completed.connect(lambda completion: delivery_threads.append(get_ident()))
    authority = ProcessingAuthority(initial_mode=ProcessingMode.CLOUD)
    first, second, third = (request(authority, i) for i in range(3))
    assert runner.submit(first)
    assert entered.wait(1)
    assert runner.submit(second) and runner.submit(third)
    assert runner.active_count == 1 and runner.pending_count == 1
    assert first.cancel_event.is_set() and second.cancel_event.is_set()
    assert not runner.workers_idle
    release.set()
    pump(app, lambda: runner.workers_idle)
    assert [call[0] for call in calls] == ["0", "2"]
    assert all(call[1] != owner for call in calls)
    assert delivery_threads == [owner, owner]
    runner.begin_close()
    assert not runner.submit(request(authority, 4))


def test_close_retains_target_until_emission_exits(owned):
    app, targets, releases = owned
    entered, release = Event(), Event()
    releases.append(release)
    def service(profile, key, *, processing_dispatch):
        entered.set()
        release.wait(3)
        raise RuntimeError("fake-key private/path")
    runner = ManagedConnectionRunner(service)
    targets.append(runner)
    values = []
    runner.completed.connect(values.append)
    runner.submit(request(ProcessingAuthority(initial_mode=ProcessingMode.CLOUD), 1))
    assert entered.wait(1)
    runner.begin_close()
    assert not runner.workers_idle and isValid(runner)
    release.set()
    pump(app, lambda: runner.workers_idle)
    assert values[0].result.outcome is ConnectionOutcome.UNKNOWN_ERROR
    assert "fake-key" not in repr(values[0])


def managed(tmp_path, owned, service, mode=ProcessingMode.CLOUD):
    app, targets, _ = owned
    authority = ProcessingAuthority(initial_mode=mode)
    runner = ManagedConnectionRunner(service)
    ctrl = SettingsController(AppConfig(), tmp_path / "settings.json", CountingStore(),
        managed_connection_runner=runner, processing_authority=authority)
    targets.extend([ctrl, runner])
    ctrl.openSession()
    return ctrl, runner, authority


CANDIDATE = {"id": "custom", "display_name": "Custom", "base_url": "https://example.invalid/v1", "model": "fake"}


@pytest.mark.parametrize("operation", ["edit", "cancel", "key", "save", "reopen", "remove", "mode"])
@pytest.mark.parametrize("success", [True, False])
def test_stale_success_and_failure_never_publish_or_remove_new_key(tmp_path, owned, operation, success):
    app, _, releases = owned
    entered, release = Event(), Event()
    releases.append(release)
    def service(profile, key, *, processing_dispatch):
        entered.set()
        release.wait(3)
        return ConnectionResult(ConnectionOutcome.SUCCESS if success else ConnectionOutcome.AUTH_ERROR)
    ctrl, runner, authority = managed(tmp_path, owned, service)
    ctrl.addOrUpdateProvider(CANDIDATE, "fake-old")
    ctrl.stageProviderKey("custom", "fake-old")
    ctrl.testConnectionCandidate(CANDIDATE, "fake-old")
    assert entered.wait(1) and ctrl.connectionTestState == "testing"
    if operation == "edit":
        ctrl.invalidateConnectionCandidate()
    elif operation == "cancel":
        ctrl.cancel()
    elif operation == "reopen":
        ctrl.cancel()
        ctrl.openSession()
    elif operation == "save":
        ctrl.saveAll()
    elif operation == "remove":
        ctrl.removeProvider("custom")
    elif operation == "mode":
        authority.select_local()
        authority.complete_choice(authority.request_cloud_choice(), persisted=True)
    else:
        ctrl.stageProviderKey("custom", "fake-new")
    release.set()
    pump(app, lambda: runner.workers_idle)
    assert ctrl.connectionTestState != "success"
    assert not ctrl._verified_fingerprints
    if operation == "key":
        assert ctrl._staged_keys["custom"] == "fake-new"


def test_permission_captured_before_credential_and_no_active_binding_required(tmp_path, owned):
    app, _, _ = owned
    calls = []
    def service(profile, key, *, processing_dispatch):
        calls.append(processing_dispatch)
        assert processing_dispatch.is_current()
        assert processing_dispatch.context.candidate_model == profile.model
        return ConnectionResult(ConnectionOutcome.SUCCESS)
    ctrl, runner, authority = managed(tmp_path, owned, service)
    ctrl.testConnectionCandidate(CANDIDATE, "fake-key")
    pump(app, lambda: runner.workers_idle)
    assert ctrl.connectionTestState == "success" and len(calls) == 1
    assert authority.snapshot().engine_fingerprint is None


def test_local_managed_typed_key_blocks_before_read_or_submit(tmp_path, owned):
    calls = []
    ctrl, runner, authority = managed(tmp_path, owned, lambda *a, **kw: calls.append(a), ProcessingMode.LOCAL)
    ctrl.testConnectionCandidate(CANDIDATE, "fake-key")
    ctrl.testConnection("deepseek", "fake-key")
    assert ctrl.connectionTestState == "failure"
    assert ctrl._credentials.calls == [] and calls == [] and runner.workers_idle


@pytest.mark.parametrize("lifecycle", ["edit", "close", "openNew", "openExisting", "hide"])
def test_real_provider_form_invalidates_running_candidate(tmp_path, owned, lifecycle):
    from PySide6.QtQml import QQmlExpression
    from PySide6.QtQuick import QQuickItem
    from tests.qml.conftest import make_handle
    app, _, releases = owned
    entered, release = Event(), Event()
    releases.append(release)
    def service(profile, key, *, processing_dispatch):
        entered.set()
        release.wait(3)
        return ConnectionResult(ConnectionOutcome.SUCCESS)
    ctrl, runner, _ = managed(tmp_path, owned, service)
    handle = make_handle(Path(__file__).parents[2] / "src/ui_qml/ProviderForm.qml", ctrl=ctrl)
    def js(code):
        expr = QQmlExpression(handle.engine.rootContext(), handle.root, code)
        expr.evaluate()
        assert not expr.hasError(), expr.error().toString()
        app.processEvents()
    try:
        js("openNew(); providerId='custom'; providerName='Custom'; baseUrl='https://example.invalid/v1'; model='fake'; apiKey='fake-key'; doTestConnection()")
        assert entered.wait(1)
        assert ctrl._owned_probe is not None
        if lifecycle == "edit":
            handle.root.findChild(QQuickItem, "pfModelField").setProperty("text", "changed")
        elif lifecycle == "close":
            js("doCancel()")
        elif lifecycle == "hide":
            handle.root.setProperty("visible", False)
        elif lifecycle == "openExisting":
            js("openExisting({id:'custom', displayName:'Custom', baseUrl:'https://example.invalid/v1', model:'fake'})")
        else:
            js("openNew()")
        assert ctrl._owned_probe is None
        # Reopen same ID: a local display flag alone must not revive old results.
        js("openNew(); providerId='custom'")
        release.set()
        pump(app, lambda: runner.workers_idle)
        assert handle.root.property("testState") == "idle"
        assert not ctrl._verified_fingerprints
        handle.assert_zero_warnings()
    finally:
        release.set()
        ctrl.begin_close()
        pump(app, lambda: runner.workers_idle)
        handle.cleanup()


def test_permission_precedes_passive_key_and_mode_change_during_get_blocks_worker(tmp_path, owned):
    ctrl, runner, authority = managed(tmp_path, owned, lambda *a, **kw: pytest.fail("must not dispatch"))
    events = []
    capture = authority.capture_cloud_probe
    def capture_probe(**kwargs):
        events.append("capture")
        return capture(**kwargs)
    authority.capture_cloud_probe = capture_probe
    def get(*args):
        events.append("get")
        authority.select_local()
        return "fake-key"
    ctrl._credentials.get = get
    ctrl.testConnection("deepseek", "")
    assert events == ["capture", "get"]
    assert ctrl.connectionTestState == "failure" and runner.workers_idle


def test_known_success_removes_ownership_before_reentrant_observer(tmp_path, owned):
    ctrl, runner, _ = managed(tmp_path, owned,
        lambda *a, **kw: ConnectionResult(ConnectionOutcome.SUCCESS))
    observations = []
    def changed():
        observations.append(ctrl._owned_probe)
        if ctrl.sessionOpen:
            ctrl.cancel()
    ctrl.providerProfilesChanged.connect(changed)
    ctrl.testConnection("deepseek", "fake-key")
    pump(owned[0], lambda: runner.workers_idle)
    assert observations and all(item is None for item in observations)
    assert not ctrl.sessionOpen and ctrl.connectionTestState != "success"


def test_known_success_reentrant_new_request_keeps_new_provider_identity(tmp_path, owned):
    ctrl, runner, _ = managed(tmp_path, owned,
        lambda *a, **kw: ConnectionResult(ConnectionOutcome.SUCCESS))
    first = []
    observed = []
    ctrl.connectionTestStateChanged.connect(lambda: observed.append((ctrl.connectionTestProviderId,
        ctrl._owned_probe.profile.id if ctrl._owned_probe is not None else None)))
    def changed():
        if not first:
            first.append(True)
            ctrl.testConnectionCandidate(CANDIDATE, "fake-new")
    ctrl.providerProfilesChanged.connect(changed)
    ctrl.testConnection("deepseek", "fake-key")
    pump(owned[0], lambda: runner.workers_idle)
    assert ctrl.connectionTestProviderId == "custom"
    assert ctrl.connectionTestState == "success"
    assert all(visible == owned_id for visible, owned_id in observed if owned_id is not None)


def test_terminal_authority_stale_result_leaves_no_loading_state(tmp_path, owned):
    app, _, releases = owned
    entered, release = Event(), Event()
    releases.append(release)
    def service(*args, **kwargs):
        entered.set()
        release.wait(3)
        return ConnectionResult(ConnectionOutcome.SUCCESS)
    ctrl, runner, authority = managed(tmp_path, owned, service)
    ctrl.testConnectionCandidate(CANDIDATE, "fake-key")
    assert entered.wait(1)
    authority.select_local()
    release.set()
    pump(app, lambda: runner.workers_idle)
    assert ctrl._owned_probe is None and ctrl.connectionTestState == "idle"


def test_owned_drain_includes_actual_callback_emission_exit(owned):
    from PySide6.QtCore import Qt
    app, targets, releases = owned
    entered, release = Event(), Event()
    releases.append(release)
    runner = ManagedConnectionRunner(lambda *a, **kw: ConnectionResult(ConnectionOutcome.SUCCESS))
    targets.append(runner)
    def block_emission(completion):
        entered.set()
        release.wait(3)
    runner._ready.connect(block_emission, Qt.ConnectionType.DirectConnection)
    runner.submit(request(ProcessingAuthority(initial_mode=ProcessingMode.CLOUD), 1))
    assert entered.wait(1)
    app.processEvents()  # queued delivery can finish while worker emit still runs
    runner.begin_close()
    assert not runner.workers_idle
    release.set()
    pump(app, lambda: runner.workers_idle)


def test_all_candidate_capabilities_are_part_of_verification_fingerprint(tmp_path, owned):
    ctrl, runner, _ = managed(tmp_path, owned,
        lambda *a, **kw: ConnectionResult(ConnectionOutcome.SUCCESS))
    candidate = dict(CANDIDATE, capabilities={"text": True, "vision": True, "multi_image": False})
    ctrl.testConnectionCandidate(candidate, "fake-key")
    pump(owned[0], lambda: runner.workers_idle)
    assert ctrl.connectionTestState == "success"
    candidate["capabilities"] = {"text": True, "vision": True, "multi_image": True}
    ctrl.addOrUpdateProvider(candidate, "fake-key")
    assert ctrl._draft_profiles[0]["needs_connection_verification"] is True


def test_replayed_old_completion_after_new_success_cannot_replace_current_state(tmp_path, owned):
    ctrl, runner, _ = managed(tmp_path, owned,
        lambda *a, **kw: ConnectionResult(ConnectionOutcome.SUCCESS))
    completions = []
    runner.completed.connect(completions.append)
    ctrl.testConnectionCandidate(CANDIDATE, "fake-old")
    pump(owned[0], lambda: runner.workers_idle)
    old = completions[0]
    ctrl.invalidateConnectionCandidate()
    newer = dict(CANDIDATE, id="newer")
    ctrl.testConnectionCandidate(newer, "fake-new")
    pump(owned[0], lambda: runner.workers_idle)
    verified = dict(ctrl._verified_fingerprints)
    # Real Qt signal delivery, deliberately reversed relative to the new terminal.
    runner.completed.emit(old)
    owned[0].processEvents()
    assert ctrl.connectionTestProviderId == "newer" and ctrl.connectionTestState == "success"
    assert ctrl._verified_fingerprints == verified


def test_changed_stored_credential_rejects_terminal_success(tmp_path, owned):
    app, _, releases = owned
    entered, release = Event(), Event()
    releases.append(release)
    def service(*a, **kw):
        entered.set()
        release.wait(3)
        return ConnectionResult(ConnectionOutcome.SUCCESS)
    ctrl, runner, _ = managed(tmp_path, owned, service)
    ctrl.testConnection("deepseek", "")
    assert entered.wait(1)
    from src.core.provider_manager import PROVIDER_CREDENTIAL_SERVICE
    ctrl._credentials.values[PROVIDER_CREDENTIAL_SERVICE, "provider:deepseek"] = "fake-other"
    release.set()
    pump(app, lambda: runner.workers_idle)
    assert ctrl.connectionTestState == "idle" and not ctrl._verified_fingerprints


def test_runner_never_falls_back_to_unguarded_signature_on_type_error(owned):
    app, targets, _ = owned
    calls = []
    def service(profile, key, **kwargs):
        calls.append(kwargs)
        raise TypeError("synthetic-private-error")
    runner = ManagedConnectionRunner(service)
    targets.append(runner)
    results = []
    runner.completed.connect(results.append)
    runner.submit(request(ProcessingAuthority(initial_mode=ProcessingMode.CLOUD), 1))
    pump(app, lambda: runner.workers_idle)
    assert len(calls) == 1 and set(calls[0]) == {"processing_dispatch"}
    assert results[0].result.outcome is ConnectionOutcome.UNKNOWN_ERROR
    assert results[0].result.error_message == ""


def test_managed_probe_matches_actual_adapter_fixed_probe_contract(tmp_path, owned):
    from io import BytesIO
    import json
    from src.core.processing_identity import cloud_engine_fingerprint
    from src.providers.openai_compatible import OpenAICompatibleAdapter, UrllibJsonTransport
    from src.services.retry_policy import RetryExecutor, RetryPolicy
    calls = []
    class Response(BytesIO):
        status = 200
        headers = {}
    def opener(request, **kwargs):
        body = json.loads(request.data)
        assert body == {"model": "fake", "messages": [{"role": "user", "content": "ping"}],
            "stream": False, "max_tokens": 1}
        calls.append(body)
        return Response(b'{"choices":[{"message":{"content":"pong"},"finish_reason":"stop"}]}')
    def service(profile, key, *, processing_dispatch):
        assert processing_dispatch.context.candidate_fingerprint == cloud_engine_fingerprint(profile)
        adapter = OpenAICompatibleAdapter(profile=profile, credential=key,
            processing_dispatch=processing_dispatch, transport=UrllibJsonTransport(opener=opener),
            retry_executor=RetryExecutor(RetryPolicy(max_retries=0, base_delay=0)))
        result = adapter.invoke_probe()
        return ConnectionResult(ConnectionOutcome.SUCCESS if result.success else ConnectionOutcome.UNKNOWN_ERROR)
    ctrl, runner, authority = managed(tmp_path, owned, service)
    ctrl.testConnectionCandidate(CANDIDATE, "fake-key")
    pump(owned[0], lambda: runner.workers_idle)
    assert ctrl.connectionTestState == "success" and len(calls) == 1
    assert authority.snapshot().engine_fingerprint is None


@pytest.mark.parametrize("site", ["get", "policy"])
@pytest.mark.parametrize("operation", ["session", "edit", "newer"])
@pytest.mark.parametrize("raises", [False, True])
def test_admission_reentry_never_adopts_old_attempt_or_clobbers_newer(tmp_path, owned, site, operation, raises):
    calls, contexts = [], []
    def service(profile, key, *, processing_dispatch):
        calls.append((profile.id, key))
        return ConnectionResult(ConnectionOutcome.SUCCESS)
    ctrl, runner, authority = managed(tmp_path, owned, service)
    capture = authority.capture_cloud_probe
    def captured(**kwargs):
        context = capture(**kwargs)
        contexts.append(context)
        return context
    authority.capture_cloud_probe = captured
    entered = []
    def reentry():
        if not entered:
            entered.append(True)
            if operation == "session":
                ctrl.cancel()
                ctrl.openSession()
            elif operation == "edit":
                ctrl.invalidateConnectionCandidate()
            else:
                ctrl.testConnectionCandidate(CANDIDATE, "fake-new")
            if raises:
                raise RuntimeError("fake-old private/path")
    def get(*args):
        reentry()
        return "fake-old"
    def policy():
        reentry()
        return True
    if site == "get":
        ctrl._credentials.get = get
    else:
        ctrl._credential_read_allowed = policy
    ctrl.testConnection("deepseek", "")
    pump(owned[0], lambda: runner.workers_idle)
    assert calls == ([("custom", "fake-new")] if operation == "newer" else [])
    assert ctrl.connectionTestState == ("success" if operation == "newer" else "idle")
    assert ctrl.connectionTestProviderId == ("custom" if operation == "newer" else "")
    assert "deepseek" not in ctrl._verified_fingerprints
    for context in contexts:
        if context.candidate_model != "fake":
            assert context.task_cancel_event.is_set()


@pytest.mark.parametrize("operation", ["stage", "clear", "save", "cancel", "remove", "close"])
def test_actual_form_supersession_binding_does_not_strand_loading(tmp_path, owned, operation):
    from tests.qml.conftest import make_handle
    from PySide6.QtQml import QQmlExpression
    app, _, releases = owned
    entered, release = Event(), Event()
    releases.append(release)
    def service(*a, **kw):
        entered.set()
        release.wait(3)
        return ConnectionResult(ConnectionOutcome.SUCCESS)
    ctrl, runner, _ = managed(tmp_path, owned, service)
    ctrl.addOrUpdateProvider(CANDIDATE, "fake-old")
    handle = make_handle(Path(__file__).parents[2] / "src/ui_qml/ProviderForm.qml", ctrl=ctrl)
    try:
        expr = QQmlExpression(handle.engine.rootContext(), handle.root,
            "openExisting({id:'custom',displayName:'Custom',baseUrl:'https://example.invalid/v1',model:'fake'})")
        expr.evaluate()
        assert not expr.hasError()
        ctrl.testConnectionCandidate(CANDIDATE, "fake-old")
        assert entered.wait(1)
        app.processEvents()
        assert handle.root.property("testState") == "testing"
        if operation == "stage":
            ctrl.stageProviderKey("custom", "fake-new")
        elif operation == "clear":
            ctrl.clearProviderKey("custom")
        elif operation == "save":
            ctrl.saveAll()
        elif operation == "cancel":
            ctrl.cancel()
        elif operation == "remove":
            ctrl.removeProvider("custom")
        else:
            ctrl.begin_close()
        app.processEvents()
        assert handle.root.property("testState") == "idle"
        assert ctrl.connectionTestProviderId == ""
        release.set()
        pump(app, lambda: runner.workers_idle)
        assert handle.root.property("testState") == "idle"
        handle.assert_zero_warnings()
    finally:
        release.set()
        ctrl.begin_close()
        pump(app, lambda: runner.workers_idle)
        handle.cleanup()


@pytest.mark.parametrize("operation", ["stage", "clear", "save", "remove"])
def test_supersession_notification_listener_new_request_is_not_clobbered(tmp_path, owned, operation):
    ctrl, runner, _ = managed(tmp_path, owned,
        lambda *a, **kw: ConnectionResult(ConnectionOutcome.SUCCESS))
    ctrl.addOrUpdateProvider(CANDIDATE, "fake-old")
    ctrl.testConnectionCandidate(CANDIDATE, "fake-old")
    pump(owned[0], lambda: runner.workers_idle)
    notified = []
    def observe():
        if ctrl.connectionTestState == "idle" and not notified:
            notified.append(True)
            ctrl.testConnectionCandidate(dict(CANDIDATE, id="newer"), "fake-new")
    ctrl.connectionTestStateChanged.connect(observe)
    if operation == "stage":
        ctrl.stageProviderKey("custom", "fake-new")
    elif operation == "clear":
        ctrl.clearProviderKey("custom")
    elif operation == "remove":
        ctrl.removeProvider("custom")
    else:
        ctrl.saveAll()
    pump(owned[0], lambda: runner.workers_idle)
    assert notified == [True]
    assert ctrl.connectionTestProviderId == "newer" and ctrl.connectionTestState == "success"


@pytest.mark.parametrize("site", ["policy", "get"])
def test_completion_passive_callback_reentry_cannot_clear_new_request_loading(tmp_path, owned, site):
    app, _, releases = owned
    entered, release = Event(), Event()
    releases.append(release)
    def service(*a, **kw):
        entered.set()
        release.wait(3)
        return ConnectionResult(ConnectionOutcome.SUCCESS)
    ctrl, runner, _ = managed(tmp_path, owned, service)
    ctrl.testConnection("deepseek", "")
    assert entered.wait(1)
    observed, reentered = [], []
    ctrl.connectionTestStateChanged.connect(lambda: observed.append((ctrl.connectionTestProviderId,
        ctrl.connectionTestState, ctrl._owned_probe.profile.id if ctrl._owned_probe else None)))
    def callback(*args):
        if not reentered:
            reentered.append(True)
            ctrl.testConnectionCandidate(CANDIDATE, "fake-new")
            raise RuntimeError("synthetic-private-failure")
        return True if site == "policy" else "fake-old"
    if site == "policy":
        ctrl._credential_read_allowed = callback
    else:
        ctrl._credentials.get = callback
    release.set()
    pump(app, lambda: runner.workers_idle)
    assert all(visible == owned_id and state == "testing" for visible, state, owned_id in observed if owned_id)
    assert ctrl.connectionTestState == "success" and ctrl.connectionTestProviderId == "custom"
    assert "deepseek" not in ctrl._verified_fingerprints


@pytest.mark.parametrize("signal", ["connection", "draft"])
@pytest.mark.parametrize("reopen", [False, True])
@pytest.mark.parametrize("operation", ["stage", "clear", "profile", "remove", "field"])
def test_mutation_signal_cancellation_finishes_private_state_first(tmp_path, owned, signal, reopen, operation):
    ctrl, runner, _ = managed(tmp_path, owned,
        lambda *a, **kw: ConnectionResult(ConnectionOutcome.SUCCESS))
    ctrl.addOrUpdateProvider(CANDIDATE, "fake-old")
    observed = []
    def cancel_once():
        if not observed:
            observed.append(True)
            ctrl.cancel()
            if reopen:
                ctrl.openSession()
    if signal == "connection" and operation == "field":
        # Ordinary draft fields have no connection notifier; this case uses the
        # real draftChanged boundary, preserving the helper's ordinary contract.
        ctrl.draftChanged.connect(cancel_once)
    else:
        (ctrl.connectionTestStateChanged if signal == "connection" else ctrl.draftChanged).connect(cancel_once)
    if operation == "stage":
        ctrl.stageProviderKey("custom", "fake-old-write")
    elif operation == "clear":
        ctrl.clearProviderKey("custom")
    elif operation == "profile":
        ctrl.addOrUpdateProvider(dict(CANDIDATE, display_name="Changed"), "fake-old")
    elif operation == "remove":
        ctrl.removeProvider("custom")
    else:
        # Start clean to exercise _mark_dirty's false→true private mutation.
        ctrl._dirty = False
        ctrl.language = "en_US"
    assert observed == [True]
    assert ctrl.sessionOpen is reopen and ctrl.dirty is False
    assert ctrl.staged_key_count == 0 and ctrl.last_result is None
    assert (ctrl.draft_config is not None) is reopen


@pytest.mark.parametrize("boundary", ["connection", "saving", "validate", "prepare"])
@pytest.mark.parametrize("reopen", [False, True])
def test_save_stops_originating_session_before_transaction_on_reentry(tmp_path, owned, monkeypatch, boundary, reopen):
    ctrl, runner, _ = managed(tmp_path, owned,
        lambda *a, **kw: ConnectionResult(ConnectionOutcome.SUCCESS))
    ctrl.stageProviderKey("deepseek", "fake-old")
    commits, observed = [], []
    def cancel_once(*args):
        if not observed:
            observed.append(True)
            ctrl.cancel()
            if reopen:
                ctrl.openSession()
                ctrl.language = "en_US"
                ctrl.stageProviderKey("deepseek", "fake-replacement")
                ctrl._save_error = "replacement-visible-state"
        return True
    if boundary == "connection":
        ctrl.connectionTestStateChanged.connect(cancel_once)
    elif boundary == "saving":
        ctrl.savingChanged.connect(cancel_once)
    elif boundary == "validate":
        validate = ctrl._validate
        ctrl._validate = lambda: (cancel_once(), validate())[1]
    else:
        ctrl._runtime_input_preparer = cancel_once
    from src.controllers.settings_transaction import SettingsSaveResult
    def commit(transaction, candidate, **kwargs):
        commits.append((candidate.language, kwargs["credential_operations"]))
        return SettingsSaveResult(False, ["synthetic-stop"])
    monkeypatch.setattr("src.controllers.settings_controller.SettingsSaveTransaction.commit", commit)
    ctrl.saveAll()
    assert observed == [True] and commits == []
    assert ctrl.last_result is None and not ctrl.saving
    if reopen:
        assert ctrl.sessionOpen and ctrl.language == "en_US" and ctrl.dirty
        assert ctrl._staged_keys == {"deepseek": "fake-replacement"}
        assert ctrl.saveError == "replacement-visible-state"
    else:
        assert not ctrl.sessionOpen and ctrl.draft_config is None and not ctrl.dirty
        assert ctrl.staged_key_count == 0 and ctrl.saveError == ""


@pytest.mark.parametrize("outcome", ["success", "publication-failure", "rollback-indeterminate"])
def test_durable_or_indeterminate_save_runs_runtime_hooks_without_clobbering_replacement_session(tmp_path, owned, monkeypatch, outcome):
    from src.controllers.settings_transaction import SettingsSaveResult
    ctrl, runner, _ = managed(tmp_path, owned,
        lambda *a, **kw: ConnectionResult(ConnectionOutcome.SUCCESS))
    ctrl.language = "en_US"
    ctrl.stageProviderKey("deepseek", "fake-old")
    runtime, public = [], []
    def published(candidate, prepared):
        runtime.append(("commit", candidate.language))
        if outcome == "publication-failure":
            raise RuntimeError("synthetic-private-error")
    ctrl._runtime_inputs_committed = published
    ctrl._runtime_admission_failed = lambda reason: runtime.append(("closed", reason))
    ctrl._managed_publication = True
    ctrl._event_publisher = lambda *args: public.append("external")
    ctrl.saveSucceeded.connect(lambda: public.append("success"))
    ctrl.saveFailed.connect(lambda *args: public.append("failure"))
    def commit(transaction, candidate, **kwargs):
        assert candidate.language == "en_US"
        assert kwargs["credential_operations"][0].value == "fake-old"
        ctrl.cancel()
        ctrl.openSession()
        ctrl.stageProviderKey("deepseek", "fake-replacement")
        ctrl._save_error = "replacement-visible-state"
        if outcome == "rollback-indeterminate":
            return SettingsSaveResult(False, ["synthetic-stop"], ["synthetic-rollback"])
        # Synthetic durable boundary: no persistence, but transaction's live
        # config publication is completed to model an already committed save.
        transaction._config_setter(candidate)
        return SettingsSaveResult(True)
    monkeypatch.setattr("src.controllers.settings_controller.SettingsSaveTransaction.commit", commit)
    ctrl.saveAll()
    assert ctrl._staged_keys == {"deepseek": "fake-replacement"}
    assert ctrl.saveError == "replacement-visible-state" and ctrl.last_result is None
    assert ctrl.sessionOpen and ctrl.dirty and not ctrl.saving
    assert public == []
    if outcome == "success":
        assert runtime == [("commit", "en_US")]
    elif outcome == "publication-failure":
        assert runtime == [("commit", "en_US"), ("closed", "runtime-input-publication-failed")]
    else:
        assert runtime == [("closed", "settings-rollback-indeterminate")]


@pytest.mark.parametrize("success", [False, True])
@pytest.mark.parametrize("signal_name", ["savingChanged", "draftChanged", "dirtyChanged"])
def test_result_signal_replacement_stops_old_success_or_failure_notifications(tmp_path, owned, monkeypatch, success, signal_name):
    from src.controllers.settings_transaction import SettingsSaveResult
    ctrl, runner, _ = managed(tmp_path, owned,
        lambda *a, **kw: ConnectionResult(ConnectionOutcome.SUCCESS))
    ctrl.stageProviderKey("deepseek", "fake-old")
    returned, observed, terminal = [], [], []
    def commit(transaction, candidate, **kwargs):
        returned.append(True)
        if success:
            transaction._config_setter(candidate)
        return SettingsSaveResult(success, [] if success else ["synthetic-failure"])
    monkeypatch.setattr("src.controllers.settings_controller.SettingsSaveTransaction.commit", commit)
    def replace_once():
        if returned and not observed:
            observed.append(True)
            ctrl.cancel()
            ctrl.openSession()
            ctrl.stageProviderKey("deepseek", "fake-replacement")
            ctrl._save_error = "replacement-visible-state"
    getattr(ctrl, signal_name).connect(replace_once)
    ctrl.saveSucceeded.connect(lambda: terminal.append("success"))
    ctrl.saveFailed.connect(lambda *args: terminal.append("failure"))
    ctrl.saveAll()
    assert observed == [True] and terminal == []
    assert ctrl._staged_keys == {"deepseek": "fake-replacement"}
    assert ctrl.saveError == "replacement-visible-state" and ctrl.last_result is None
    assert ctrl.sessionOpen and ctrl.dirty and not ctrl.saving


def test_failed_executor_submit_cancels_unexecuted_request_and_close_is_idle(monkeypatch):
    app = QApplication.instance() or QApplication([])
    runner = ManagedConnectionRunner(lambda *a, **kw: pytest.fail("unexecuted request"))
    authority = ProcessingAuthority(initial_mode=ProcessingMode.CLOUD)
    pending = request(authority, "start-failure")
    delivered = []
    runner.completed.connect(delivered.append)
    def fail_submit(*args, **kwargs):
        # This seam fails BEFORE scheduling anything; no thread/callback can
        # emit, even during RED where ownership accounting is deliberately bad.
        raise RuntimeError("synthetic-private-key/private-path")
    monkeypatch.setattr(runner._executor, "submit", fail_submit)
    try:
        assert runner.submit(pending) is False
        assert pending.cancel_event.is_set()
        assert runner.active_count == 0 and runner.pending_count == 0 and runner.workers_idle
        runner.begin_close()
        app.processEvents()
        assert runner.workers_idle and delivered == []
    finally:
        runner.begin_close()
        assert not runner._executor._threads  # injected seam proves actual no worker
        runner.deleteLater()
        QCoreApplication.sendPostedEvents(runner, QEvent.Type.DeferredDelete)
        assert not isValid(runner)

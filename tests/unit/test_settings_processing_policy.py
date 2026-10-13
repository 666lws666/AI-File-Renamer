"""Managed Settings policy; all secrets and stores are synthetic."""
from pathlib import Path

import pytest

from src.controllers.settings_controller import SettingsController
from src.controllers.settings_transaction import SettingsSaveResult
from src.core.provider_presets import create_profile_from_preset
from src.core.provider_manager import PROVIDER_CREDENTIAL_SERVICE
from src.models.app_config import AppConfig


class CountingStore:
    def __init__(self):
        self.calls = []
        self.values = {(PROVIDER_CREDENTIAL_SERVICE, "provider:deepseek"): "fake-old"}

    def get(self, service, account):
        self.calls.append("get")
        return self.values.get((service, account))

    def set(self, service, account, value):
        self.calls.append("set")
        self.values[service, account] = value
        return True

    def delete(self, service, account):
        self.calls.append("delete")
        self.values.pop((service, account), None)
        return True


def controller(tmp_path, **kwargs):
    profile = create_profile_from_preset("deepseek", profile_id="deepseek").to_safe_dict()
    profile["needs_connection_verification"] = False
    live = AppConfig(provider_profiles=[profile], active_provider_id="deepseek")
    store = CountingStore()
    ctrl = SettingsController(live, tmp_path / "settings.json", store, **kwargs)
    ctrl.openSession()
    return ctrl, store, live


def test_local_passive_paths_and_metadata_save_have_zero_credential_access(tmp_path):
    ctrl, store, live = controller(tmp_path, credential_read_allowed=lambda: False)
    rows = ctrl.providerProfiles
    assert all(row["credentialState"] == "unavailable" for row in rows)
    ctrl.setActiveProvider("deepseek")
    ctrl.stageProviderKey("deepseek", "")
    ctrl.addOrUpdateProvider({"id": "deepseek", "model": "deepseek-v4-pro"}, "")
    # Restore structural verification, since editing must not forge a test.
    ctrl._draft_profiles[0]["needs_connection_verification"] = False
    ctrl.language = "en_US"
    ctrl.saveAll()
    assert ctrl.last_result.success
    assert live.language == "en_US"
    assert store.calls == []


def test_local_typed_probe_cannot_bypass_gate(tmp_path):
    calls = []
    ctrl, store, _ = controller(tmp_path, credential_read_allowed=lambda: False,
        connection_test_service=lambda *args: calls.append(args))
    ctrl.testConnection("deepseek", "fake-typed")
    ctrl.testConnectionCandidate({"id": "deepseek"}, "fake-typed")
    assert ctrl.connectionTestState == "failure"
    assert calls == [] and store.calls == []


def test_explicit_local_key_edits_still_use_transaction(tmp_path):
    ctrl, store, _ = controller(tmp_path, credential_read_allowed=lambda: False)
    ctrl.stageProviderKey("deepseek", "fake-new")
    ctrl.saveAll()
    assert ctrl.last_result.success and "set" in store.calls
    store.calls.clear()
    ctrl.clearProviderKey("deepseek")
    ctrl.saveAll()
    assert ctrl.last_result.success and "delete" in store.calls


def test_preparation_and_publication_precede_success_observers(tmp_path):
    events = []
    catalog = ("immutable",)
    ctrl, _, _ = controller(tmp_path,
        runtime_input_preparer=lambda candidate: events.append("prepare") or catalog,
        runtime_inputs_committed=lambda candidate, prepared: events.append(("install", prepared)),
        runtime_admission_failed=lambda reason: events.append(("closed", reason)),
        event_publisher=lambda *args: events.append("external"))
    ctrl.draftChanged.connect(lambda: events.append("draft"))
    ctrl.saveSucceeded.connect(lambda: events.append("success"))
    ctrl.saveAll()
    assert events[:2] == ["prepare", ("install", catalog)]
    assert events.index("external") > 1 and events.index("success") > 1


def test_preparation_failure_does_not_save_or_publish(tmp_path):
    def fail(candidate):
        raise RuntimeError("fake-secret private/path")
    events = []
    ctrl, store, live = controller(tmp_path, runtime_input_preparer=fail, credential_read_allowed=lambda: False,
        runtime_inputs_committed=lambda *args: events.append("install"))
    ctrl.language = "en_US"
    ctrl.saveAll()
    assert not ctrl.last_result.success
    assert live.language == "zh_CN" and not (tmp_path / "settings.json").exists()
    assert store.calls == [] and events == []
    assert "fake-secret" not in ctrl.saveError


@pytest.mark.parametrize("rollback_errors", [[], ["rollback-failed"]])
def test_uncertain_rollback_closes_before_failure_observers(tmp_path, monkeypatch, rollback_errors):
    events = []
    ctrl, _, _ = controller(tmp_path,
        runtime_inputs_committed=lambda *args: events.append("install"),
        runtime_admission_failed=lambda reason: events.append("closed"))
    monkeypatch.setattr("src.controllers.settings_controller.SettingsSaveTransaction.commit",
        lambda *args, **kwargs: SettingsSaveResult(False, ["failed"], rollback_errors))
    ctrl.saveFailed.connect(lambda reason: events.append("failure"))
    ctrl.saveAll()
    assert events == (["closed", "failure"] if rollback_errors else ["failure"])


def test_post_durable_publication_failure_is_truthful_and_closes_first(tmp_path):
    events = []
    def fail(*args):
        raise RuntimeError("fake-secret")
    ctrl, _, live = controller(tmp_path, runtime_inputs_committed=fail,
        runtime_admission_failed=lambda reason: events.append("closed"),
        event_publisher=lambda *args: events.append("external"))
    ctrl.saveFailed.connect(lambda reason: events.append("failure"))
    ctrl.saveSucceeded.connect(lambda: events.append("success"))
    ctrl.language = "en_US"
    ctrl.saveAll()
    assert live.language == "en_US" and (tmp_path / "settings.json").exists()
    assert not ctrl.last_result.success
    assert ctrl.last_result.errors == ["runtime-input-publication-failed"]
    assert events == ["closed", "failure"]


@pytest.mark.parametrize("rollback_fails", [False, True])
def test_actual_compensation_with_fake_store_closes_only_if_uncertain(tmp_path, rollback_fails):
    events = []
    ctrl, store, live = controller(tmp_path, credential_read_allowed=lambda: False,
        runtime_inputs_committed=lambda *args: events.append("install"),
        runtime_admission_failed=lambda reason: events.append("closed"),
        event_publisher=lambda *args: events.append("event"))
    original_set = store.set
    sets = []
    def set_key(service, account, value):
        sets.append(value)
        if rollback_fails and len(sets) == 2:
            return False
        return original_set(service, account, value)
    store.set = set_key
    def apply(candidate):
        if candidate.language == "en_US":
            raise RuntimeError("synthetic failure")
    ctrl._config_applier = apply
    ctrl.saveFailed.connect(lambda reason: events.append("failure"))
    ctrl.language = "en_US"
    ctrl.stageProviderKey("deepseek", "fake-new")
    ctrl.saveAll()
    assert not ctrl.last_result.success
    assert bool(ctrl.last_result.rollback_errors) is rollback_fails
    assert events == (["closed", "event", "failure"] if rollback_fails else ["event", "failure"])
    assert live.language == "zh_CN" and not (tmp_path / "settings.json").exists()
    assert store.values[PROVIDER_CREDENTIAL_SERVICE, "provider:deepseek"] == ("fake-new" if rollback_fails else "fake-old")


@pytest.mark.parametrize("closing", [False, True])
def test_local_or_closing_saved_custom_views_selection_and_candidate_fallback_are_unavailable(tmp_path, closing):
    ctrl, store, _ = controller(tmp_path, credential_read_allowed=lambda: closing)
    ctrl.addOrUpdateProvider({"id": "custom", "display_name": "Custom",
        "model": "fake", "base_url": "https://example.invalid/v1"}, "fake-typed")
    ctrl._draft_profiles[-1]["needs_connection_verification"] = False
    if closing:
        ctrl.begin_close()
    store.calls.clear()
    custom = next(row for row in ctrl.providerProfiles if row["id"] == "custom")
    assert custom["credentialState"] == "unavailable" and not custom["canActivate"]
    ctrl.setActiveProvider("custom")
    ctrl.stageProviderKey("custom", "")
    assert ctrl._candidate_credential("custom", "") == ""
    assert ctrl.activeProviderId == "deepseek" and store.calls == []


def test_passive_rows_check_live_policy_before_every_lookup(tmp_path):
    allowed = [True]
    ctrl, store, _ = controller(tmp_path, credential_read_allowed=lambda: allowed[0])
    ctrl.addOrUpdateProvider({"id": "custom", "model": "fake", "base_url": "https://example.invalid/v1"}, "fake")
    reads = []
    def get(*args):
        reads.append(allowed[0])
        allowed[0] = False
        return "fake"
    store.get = get
    rows = ctrl.providerProfiles
    assert reads == [True]
    assert all(row["credentialState"] == "unavailable" for row in rows[1:])


def test_policy_callback_closing_controller_prevents_actual_lookup(tmp_path):
    ctrl, store, _ = controller(tmp_path)
    def policy():
        ctrl.begin_close()
        return True
    ctrl._credential_read_allowed = policy
    rows = ctrl.providerProfiles
    assert store.calls == []
    assert all(row["credentialState"] == "unavailable" for row in rows)


def test_metadata_validation_skips_existence_when_policy_closes_between_checks(tmp_path):
    checks = []
    def policy():
        checks.append(True)
        return len(checks) == 1
    ctrl, store, _ = controller(tmp_path, credential_read_allowed=policy)
    ctrl.saveAll()
    assert ctrl.last_result.success and store.calls == []

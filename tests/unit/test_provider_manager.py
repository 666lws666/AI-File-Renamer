"""M3 Task 4: single-active ProviderManager and compensation tests."""
from __future__ import annotations

from dataclasses import replace

import pytest

from src.core.provider_manager import (
    PROVIDER_CREDENTIAL_SERVICE,
    ProviderCredentialError,
    ProviderManager,
    ProviderPersistenceError,
    ProviderValidationError,
)
from src.core.provider_profile import ProviderProfile
from src.core.provider_protocol import ProviderCapabilities
from src.models.app_config import AppConfig


class FakeCredentialStore:
    def __init__(self):
        self.values: dict[tuple[str, str], str] = {}
        self.calls: list[tuple] = []
        self.fail_get = False
        self.fail_set = False
        self.fail_delete = False
        self.fail_delete_accounts: set[tuple[str, str]] = set()

    def get(self, service: str, account: str) -> str | None:
        self.calls.append(("get", service, account))
        if self.fail_get:
            raise OSError("simulated credential read failure")
        return self.values.get((service, account))

    def set(self, service: str, account: str, secret: str) -> bool:
        self.calls.append(("set", service, account, secret))
        if self.fail_set:
            return False
        self.values[(service, account)] = secret
        return True

    def delete(self, service: str, account: str) -> bool:
        self.calls.append(("delete", service, account))
        if self.fail_delete or (service, account) in self.fail_delete_accounts:
            return False
        self.values.pop((service, account), None)
        return True


class RecordingPersister:
    def __init__(self):
        self.saved: list[AppConfig] = []
        self.fail = False

    def __call__(self, config: AppConfig) -> None:
        if self.fail:
            raise OSError("simulated atomic JSON failure")
        self.saved.append(config.model_copy(deep=True))


@pytest.fixture
def credential_store():
    return FakeCredentialStore()


@pytest.fixture
def persister():
    return RecordingPersister()


@pytest.fixture
def manager(credential_store, persister):
    return ProviderManager(AppConfig(), persister, credential_store)


def profile(
    profile_id: str = "qwen-main",
    *,
    enabled: bool = True,
    needs_verification: bool = True,
) -> ProviderProfile:
    return ProviderProfile(
        id=profile_id,
        display_name="Qwen Main",
        protocol_kind="openai_compatible",
        base_url_mode="REGIONAL",
        base_url="https://workspace.example.invalid/v1",
        region="singapore",
        workspace_id="workspace",
        model="qwen-model",
        capabilities=ProviderCapabilities(text=True, vision=True, json_mode=True),
        enabled=enabled,
        needs_connection_verification=needs_verification,
    )


def account(profile_id: str) -> str:
    return f"provider:{profile_id}"


def test_add_profile_persists_only_metadata_and_profile_credential(
    manager, credential_store, persister
):
    saved = manager.add_profile(profile(), credential="top-secret")
    assert saved.credential_account_id == account("qwen-main")
    assert credential_store.values[
        (PROVIDER_CREDENTIAL_SERVICE, account("qwen-main"))
    ] == "top-secret"
    persisted = persister.saved[-1].model_dump()
    assert persisted["active_provider_id"] == ""
    assert persisted["provider_profiles"][0]["id"] == "qwen-main"
    assert "top-secret" not in repr(persisted)
    assert "api_key" not in persisted["provider_profiles"][0]


def test_profile_collection_is_immutable_from_the_caller(manager):
    manager.add_profile(profile())
    listed = manager.list_profiles()
    assert isinstance(listed, tuple)
    with pytest.raises((AttributeError, TypeError)):
        listed[0].model = "changed"
    assert manager.get_profile("qwen-main").model == "qwen-model"


def test_add_credential_failure_writes_no_metadata(
    manager, credential_store, persister
):
    credential_store.fail_set = True
    with pytest.raises(ProviderCredentialError):
        manager.add_profile(profile(), credential="secret")
    assert manager.list_profiles() == ()
    assert persister.saved == []


def test_profile_credential_must_be_text(manager):
    with pytest.raises(ProviderValidationError):
        manager.add_profile(profile(), credential=b"raw-secret")
    assert manager.list_profiles() == ()


def test_add_metadata_failure_restores_prior_credential(
    manager, credential_store, persister
):
    persister.fail = True
    with pytest.raises(ProviderPersistenceError):
        manager.add_profile(profile(), credential="secret")
    assert manager.list_profiles() == ()
    assert credential_store.values == {}


def test_update_metadata_failure_restores_profile_and_old_credential(
    manager, credential_store, persister
):
    manager.add_profile(profile(), credential="old-secret")
    persister.fail = True
    with pytest.raises(ProviderPersistenceError):
        manager.update_profile(
            replace(profile(), model="new-model"), credential="new-secret"
        )
    assert manager.get_profile("qwen-main").model == "qwen-model"
    assert credential_store.values[
        (PROVIDER_CREDENTIAL_SERVICE, account("qwen-main"))
    ] == "old-secret"


def test_remove_credential_failure_retains_metadata(
    manager, credential_store, persister
):
    manager.add_profile(profile(), credential="secret")
    saves_before = len(persister.saved)
    credential_store.fail_delete = True
    with pytest.raises(ProviderCredentialError):
        manager.remove_profile("qwen-main")
    assert manager.get_profile("qwen-main").id == "qwen-main"
    assert len(persister.saved) == saves_before


def test_remove_metadata_failure_restores_credential(
    manager, credential_store, persister
):
    manager.add_profile(profile(), credential="secret")
    persister.fail = True
    with pytest.raises(ProviderPersistenceError):
        manager.remove_profile("qwen-main")
    assert manager.get_profile("qwen-main").id == "qwen-main"
    assert credential_store.values[
        (PROVIDER_CREDENTIAL_SERVICE, account("qwen-main"))
    ] == "secret"


@pytest.mark.parametrize(
    "candidate,credential,expected_message",
    [
        (None, None, "not found"),
        (profile(enabled=False, needs_verification=False), "secret", "disabled"),
        (profile(needs_verification=True), "secret", "verified"),
        (profile(needs_verification=False), None, "credential"),
    ],
)
def test_set_active_rejects_unusable_profile(
    candidate, credential, expected_message, credential_store, persister
):
    local_manager = ProviderManager(AppConfig(), persister, credential_store)
    if candidate is None:
        with pytest.raises(ProviderValidationError, match=expected_message):
            local_manager.set_active("missing")
        return
    local_manager.add_profile(candidate, credential=credential)
    with pytest.raises(ProviderValidationError, match=expected_message):
        local_manager.set_active(candidate.id)


def test_exactly_one_active_profile_id(manager):
    manager.add_profile(
        profile("one", needs_verification=False), credential="one-secret"
    )
    manager.add_profile(
        profile("two", needs_verification=False), credential="two-secret"
    )
    manager.set_active("one")
    assert manager.get_active().id == "one"
    manager.set_active("two")
    assert manager.get_active().id == "two"
    assert manager.config.active_provider_id == "two"
    assert all("active" not in p.to_safe_dict() for p in manager.list_profiles())


def test_active_save_failure_keeps_previous_active(
    manager, credential_store, persister
):
    manager.add_profile(
        profile("one", needs_verification=False), credential="one-secret"
    )
    manager.add_profile(
        profile("two", needs_verification=False), credential="two-secret"
    )
    manager.set_active("one")
    persister.fail = True
    with pytest.raises(ProviderPersistenceError):
        manager.set_active("two")
    assert manager.get_active().id == "one"


def test_removing_active_profile_clears_active_id(manager):
    manager.add_profile(
        profile("one", needs_verification=False), credential="secret"
    )
    manager.set_active("one")
    manager.remove_profile("one")
    assert manager.get_active() is None
    assert manager.config.active_provider_id == ""


@pytest.mark.parametrize(
    ("replacement", "credential", "message"),
    [
        (profile("one", enabled=False, needs_verification=False), "secret", "disabled"),
        (profile("one", needs_verification=True), "secret", "verified"),
        (profile("one", needs_verification=False), None, "credential"),
        (profile("one", needs_verification=False), "", "credential"),
    ],
)
def test_update_cannot_make_active_profile_unusable(
    replacement, credential, message, manager
):
    manager.add_profile(
        profile("one", needs_verification=False), credential="old-secret"
    )
    manager.set_active("one")

    with pytest.raises(ProviderValidationError, match=message):
        manager.update_profile(replacement, credential=credential)

    assert manager.get_active().id == "one"
    assert manager.get_credential_status("one") is True


@pytest.mark.parametrize(
    ("enabled", "needs_verification", "expected"),
    [
        (False, False, "disabled"),
        (True, True, "verified"),
    ],
)
def test_loaded_active_profile_must_be_usable_metadata(
    enabled, needs_verification, expected, credential_store, persister
):
    active = replace(
        profile(
            "one",
            enabled=enabled,
            needs_verification=needs_verification,
        ),
        credential_account_id=account("one"),
    )
    config = AppConfig(
        provider_profiles=[active.to_safe_dict()],
        active_provider_id="one",
    )
    with pytest.raises(ProviderValidationError, match=expected):
        ProviderManager(config, persister, credential_store)


def test_loaded_active_profile_requires_existing_credential(
    credential_store, persister
):
    active = replace(
        profile("one", needs_verification=False),
        credential_account_id=account("one"),
    )
    config = AppConfig(
        provider_profiles=[active.to_safe_dict()],
        active_provider_id="one",
    )

    with pytest.raises(ProviderValidationError, match="credential"):
        ProviderManager(config, persister, credential_store)


def test_credential_status_returns_boolean_without_exposing_secret(
    manager, credential_store
):
    manager.add_profile(profile(), credential="secret")
    status = manager.get_credential_status("qwen-main")
    assert status is True
    assert status != "secret"


def test_credential_read_failure_aborts_before_any_mutation(
    manager, credential_store, persister
):
    credential_store.fail_get = True
    with pytest.raises(ProviderCredentialError, match="read"):
        manager.add_profile(profile(), credential="new-secret")
    assert manager.list_profiles() == ()
    assert persister.saved == []
    assert not any(call[0] in {"set", "delete"} for call in credential_store.calls)


def test_loaded_profile_cannot_point_at_another_profiles_credential(
    credential_store, persister
):
    unsafe = replace(
        profile("one"), credential_account_id="provider:someone-else"
    )
    config = AppConfig(provider_profiles=[unsafe.to_safe_dict()])
    with pytest.raises(ProviderValidationError, match="credential account"):
        ProviderManager(config, persister, credential_store)


def legacy_config() -> AppConfig:
    return AppConfig(
        provider="deepseek",
        base_url="https://api.deepseek.com",
        model="legacy-model",
    )


def seed_legacy(credential_store: FakeCredentialStore):
    credential_store.values[("AIRenamer", "api_key")] = "legacy-secret"


def test_legacy_migration_is_transactional_and_never_auto_active(
    credential_store, persister
):
    seed_legacy(credential_store)
    local_manager = ProviderManager(legacy_config(), persister, credential_store)
    migrated = local_manager.migrate_legacy_profile()
    assert migrated.display_name == "迁移的旧配置"
    assert migrated.needs_connection_verification is True
    assert migrated.model == "legacy-model"
    assert local_manager.config.active_provider_id == ""
    assert ("AIRenamer", "api_key") not in credential_store.values
    assert credential_store.values[
        (PROVIDER_CREDENTIAL_SERVICE, account(migrated.id))
    ] == "legacy-secret"
    assert "legacy-secret" not in repr(persister.saved[-1].model_dump())


def test_legacy_migration_preserves_an_existing_active_provider(
    credential_store, persister
):
    existing = replace(
        profile("existing", needs_verification=False),
        credential_account_id=account("existing"),
    )
    config = legacy_config().model_copy(deep=True)
    config.provider_profiles = [existing.to_safe_dict()]
    config.active_provider_id = "existing"
    credential_store.values[
        (PROVIDER_CREDENTIAL_SERVICE, account("existing"))
    ] = "existing-secret"
    seed_legacy(credential_store)
    local_manager = ProviderManager(config, persister, credential_store)

    migrated = local_manager.migrate_legacy_profile()

    assert migrated.id == "legacy-migrated"
    assert local_manager.config.active_provider_id == "existing"
    assert local_manager.get_active().id == "existing"


def test_legacy_migration_new_credential_failure_has_zero_side_effects(
    credential_store, persister
):
    seed_legacy(credential_store)
    credential_store.fail_set = True
    local_manager = ProviderManager(legacy_config(), persister, credential_store)
    with pytest.raises(ProviderCredentialError):
        local_manager.migrate_legacy_profile()
    assert local_manager.list_profiles() == ()
    assert credential_store.values[("AIRenamer", "api_key")] == "legacy-secret"
    assert persister.saved == []


def test_legacy_migration_persist_failure_compensates_new_credential(
    credential_store, persister
):
    seed_legacy(credential_store)
    persister.fail = True
    local_manager = ProviderManager(legacy_config(), persister, credential_store)
    with pytest.raises(ProviderPersistenceError):
        local_manager.migrate_legacy_profile()
    assert local_manager.list_profiles() == ()
    assert credential_store.values == {("AIRenamer", "api_key"): "legacy-secret"}


def test_legacy_delete_failure_rolls_back_metadata_and_new_credential(
    credential_store, persister
):
    seed_legacy(credential_store)
    local_manager = ProviderManager(legacy_config(), persister, credential_store)
    credential_store.fail_delete_accounts.add(("AIRenamer", "api_key"))
    with pytest.raises(ProviderCredentialError):
        local_manager.migrate_legacy_profile()
    assert local_manager.list_profiles() == ()
    assert credential_store.values == {("AIRenamer", "api_key"): "legacy-secret"}
    assert persister.saved[-1].provider_profiles == []

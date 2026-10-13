"""Transactional management of saved provider profiles and their credentials."""
from __future__ import annotations

from dataclasses import replace
from typing import Callable, Protocol

from src.models.app_config import AppConfig
from src.utils import credential_manager

from .provider_profile import ProviderProfile
from .provider_protocol import ProviderCapabilities


PROVIDER_CREDENTIAL_SERVICE = "Xuxia.Provider"
LEGACY_CREDENTIAL_SERVICE = "AIRenamer"
LEGACY_CREDENTIAL_ACCOUNT = "api_key"
LEGACY_PROFILE_ID = "legacy-migrated"
_UNCHANGED = object()


class ProviderManagerError(RuntimeError):
    """Base class for profile transaction failures."""


class ProviderValidationError(ProviderManagerError):
    """The requested profile state violates a product invariant."""


class ProviderCredentialError(ProviderManagerError):
    """A credential operation failed and the profile change was rejected."""


class ProviderPersistenceError(ProviderManagerError):
    """Metadata persistence failed and compensating actions were attempted."""


class ProviderCompensationError(ProviderManagerError):
    """A primary operation and its compensation both failed."""


class CredentialStore(Protocol):
    def get(self, service: str, account: str) -> str | None: ...

    def set(self, service: str, account: str, secret: str) -> bool: ...

    def delete(self, service: str, account: str) -> bool: ...


class SystemCredentialStore:
    """Adapter over Windows Credential Manager-backed helper functions."""

    def get(self, service: str, account: str) -> str | None:
        return credential_manager.get_credential_strict(service, account)

    def set(self, service: str, account: str, secret: str) -> bool:
        return credential_manager.set_credential(secret, service, account)

    def delete(self, service: str, account: str) -> bool:
        return credential_manager.delete_credential(service, account)


class ProviderManager:
    """Own saved profiles while keeping exactly one active profile ID.

    The manager owns a private ``AppConfig`` snapshot.  Candidate metadata is
    persisted before the in-memory snapshot changes.  Credential mutations are
    compensated when metadata persistence fails.
    """

    def __init__(
        self,
        config: AppConfig,
        persist_config: Callable[[AppConfig], None],
        credential_store: CredentialStore | None = None,
    ) -> None:
        self._config = config.model_copy(deep=True)
        self._persist_config = persist_config
        self._credentials = credential_store or SystemCredentialStore()
        self._validate_loaded_state()

    @property
    def config(self) -> AppConfig:
        return self._config.model_copy(deep=True)

    def list_profiles(self) -> tuple[ProviderProfile, ...]:
        return tuple(
            ProviderProfile.from_safe_dict(item)
            for item in self._config.provider_profiles
        )

    def get_profile(self, profile_id: str) -> ProviderProfile:
        for profile in self.list_profiles():
            if profile.id == profile_id:
                return profile
        raise ProviderValidationError(f"Provider profile not found: {profile_id}")

    def get_active(self) -> ProviderProfile | None:
        if not self._config.active_provider_id:
            return None
        try:
            return self.get_profile(self._config.active_provider_id)
        except ProviderValidationError:
            return None

    def get_credential_status(self, profile_id: str) -> bool:
        profile = self.get_profile(profile_id)
        return bool(
            self._read_credential(
                PROVIDER_CREDENTIAL_SERVICE, profile.credential_account_id
            )
        )

    def add_profile(
        self, profile: ProviderProfile, credential: str | None = None
    ) -> ProviderProfile:
        if any(item.id == profile.id for item in self.list_profiles()):
            raise ProviderValidationError(
                f"Provider profile already exists: {profile.id}"
            )
        normalized = self._normalize_profile(profile)
        account = normalized.credential_account_id
        old_secret = self._read_credential(PROVIDER_CREDENTIAL_SERVICE, account)
        credential_changed = credential is not None
        if credential_changed:
            self._apply_credential(account, credential)

        candidate = self._candidate_with(
            profiles=(*self.list_profiles(), normalized)
        )
        try:
            self._persist_candidate(candidate)
        except ProviderPersistenceError:
            if credential_changed:
                self._restore_credential(account, old_secret)
            raise
        return normalized

    def update_profile(
        self,
        profile: ProviderProfile,
        credential: str | None | object = _UNCHANGED,
    ) -> ProviderProfile:
        existing = self.get_profile(profile.id)
        normalized = self._normalize_profile(profile)
        account = existing.credential_account_id
        if normalized.credential_account_id != account:
            normalized = replace(normalized, credential_account_id=account)

        if self._config.active_provider_id == normalized.id:
            if not normalized.enabled:
                raise ProviderValidationError("Active provider profile cannot be disabled")
            if normalized.needs_connection_verification:
                raise ProviderValidationError(
                    "Active provider profile must remain verified"
                )
            if credential is not _UNCHANGED and not credential:
                raise ProviderValidationError(
                    "Active provider profile must retain a credential"
                )

        old_secret = self._read_credential(PROVIDER_CREDENTIAL_SERVICE, account)
        credential_changed = credential is not _UNCHANGED
        if credential_changed:
            self._apply_credential(account, credential)

        profiles = tuple(
            normalized if item.id == normalized.id else item
            for item in self.list_profiles()
        )
        candidate = self._candidate_with(profiles=profiles)
        try:
            self._persist_candidate(candidate)
        except ProviderPersistenceError:
            if credential_changed:
                self._restore_credential(account, old_secret)
            raise
        return normalized

    def remove_profile(self, profile_id: str) -> None:
        profile = self.get_profile(profile_id)
        account = profile.credential_account_id
        old_secret = self._read_credential(PROVIDER_CREDENTIAL_SERVICE, account)
        if not self._credentials.delete(PROVIDER_CREDENTIAL_SERVICE, account):
            raise ProviderCredentialError(
                f"Unable to delete credential for provider:{profile_id}"
            )

        remaining = tuple(
            item for item in self.list_profiles() if item.id != profile_id
        )
        active_id = self._config.active_provider_id
        if active_id == profile_id:
            active_id = ""
        candidate = self._candidate_with(
            profiles=remaining, active_provider_id=active_id
        )
        try:
            self._persist_candidate(candidate)
        except ProviderPersistenceError:
            self._restore_credential(account, old_secret)
            raise

    def set_active(self, profile_id: str) -> ProviderProfile:
        profile = self.get_profile(profile_id)
        if not profile.enabled:
            raise ProviderValidationError("Provider profile is disabled")
        if profile.needs_connection_verification:
            raise ProviderValidationError(
                "Provider profile must be verified before activation"
            )
        if not self.get_credential_status(profile_id):
            raise ProviderValidationError("Provider profile has no credential")
        candidate = self._candidate_with(active_provider_id=profile_id)
        self._persist_candidate(candidate)
        return profile

    def migrate_legacy_profile(self) -> ProviderProfile | None:
        """Move the Phase-1A credential to a non-active, unverified profile."""
        legacy_secret = self._read_credential(
            LEGACY_CREDENTIAL_SERVICE, LEGACY_CREDENTIAL_ACCOUNT
        )
        if not legacy_secret:
            return None
        if any(item.id == LEGACY_PROFILE_ID for item in self.list_profiles()):
            raise ProviderValidationError("Legacy migration profile already exists")

        migrated = self._normalize_profile(
            ProviderProfile(
                id=LEGACY_PROFILE_ID,
                display_name="迁移的旧配置",
                protocol_kind="openai_compatible",
                base_url_mode=(
                    "FIXED" if self._config.base_url else "USER_CONFIGURED"
                ),
                base_url=self._config.base_url,
                model=self._config.model,
                capabilities=ProviderCapabilities(text=True),
                needs_connection_verification=True,
            )
        )
        account = migrated.credential_account_id
        previous_new_secret = self._read_credential(
            PROVIDER_CREDENTIAL_SERVICE, account
        )
        if not self._credentials.set(
            PROVIDER_CREDENTIAL_SERVICE, account, legacy_secret
        ):
            raise ProviderCredentialError(
                "Unable to create migrated provider credential"
            )

        original = self._config.model_copy(deep=True)
        candidate = self._candidate_with(
            profiles=(*self.list_profiles(), migrated),
            active_provider_id=self._config.active_provider_id,
        )
        try:
            self._persist_config(candidate.model_copy(deep=True))
        except Exception as error:
            self._restore_credential(account, previous_new_secret)
            raise ProviderPersistenceError(
                "Unable to persist migrated provider metadata"
            ) from error

        if not self._credentials.delete(
            LEGACY_CREDENTIAL_SERVICE, LEGACY_CREDENTIAL_ACCOUNT
        ):
            try:
                self._persist_config(original.model_copy(deep=True))
                self._restore_credential(account, previous_new_secret)
            except ProviderManagerError as compensation_error:
                raise ProviderCompensationError(
                    "Legacy credential deletion and compensation both failed"
                ) from compensation_error
            except Exception as compensation_error:
                raise ProviderCompensationError(
                    "Legacy credential deletion and metadata rollback both failed"
                ) from compensation_error
            raise ProviderCredentialError(
                "Unable to delete legacy credential; migration was rolled back"
            )

        self._config = candidate
        return migrated

    def _validate_loaded_state(self) -> None:
        profiles = self.list_profiles()
        identifiers = [profile.id for profile in profiles]
        if len(identifiers) != len(set(identifiers)):
            raise ProviderValidationError("Duplicate provider profile IDs")
        for profile in profiles:
            normalized = self._normalize_profile(profile)
            if profile.credential_account_id != normalized.credential_account_id:
                raise ProviderValidationError(
                    f"Provider credential account is not canonical: {profile.id}"
                )
        if self._config.active_provider_id:
            if self._config.active_provider_id not in set(identifiers):
                raise ProviderValidationError("Active provider profile does not exist")
            active = next(
                profile
                for profile in profiles
                if profile.id == self._config.active_provider_id
            )
            if not active.enabled:
                raise ProviderValidationError("Active provider profile is disabled")
            if active.needs_connection_verification:
                raise ProviderValidationError(
                    "Active provider profile must be verified"
                )
            if not self._read_credential(
                PROVIDER_CREDENTIAL_SERVICE, active.credential_account_id
            ):
                raise ProviderValidationError(
                    "Active provider profile has no credential"
                )

    def _normalize_profile(self, profile: ProviderProfile) -> ProviderProfile:
        profile_id = profile.id.strip()
        if not profile_id:
            raise ProviderValidationError("Provider profile id is required")
        if profile_id != profile.id or any(
            character in profile_id for character in ("/", "\\", ":")
        ):
            raise ProviderValidationError("Provider profile id is not safe")
        if not profile.display_name.strip():
            raise ProviderValidationError("Provider display name is required")
        return replace(
            profile,
            credential_account_id=f"provider:{profile_id}",
        )

    def _candidate_with(
        self,
        *,
        profiles: tuple[ProviderProfile, ...] | None = None,
        active_provider_id: str | None = None,
    ) -> AppConfig:
        candidate = self._config.model_copy(deep=True)
        if profiles is not None:
            candidate.provider_profiles = [
                profile.to_safe_dict() for profile in profiles
            ]
        if active_provider_id is not None:
            candidate.active_provider_id = active_provider_id
        return candidate

    def _persist_candidate(self, candidate: AppConfig) -> None:
        try:
            self._persist_config(candidate.model_copy(deep=True))
        except Exception as error:
            raise ProviderPersistenceError(
                "Unable to persist provider profile metadata"
            ) from error
        self._config = candidate

    def _read_credential(self, service: str, account: str) -> str | None:
        try:
            return self._credentials.get(service, account)
        except Exception as error:
            raise ProviderCredentialError(
                f"Unable to read credential for {account}"
            ) from error

    def _apply_credential(self, account: str, secret: str | None | object) -> None:
        if secret is _UNCHANGED:
            return
        if secret is not None and not isinstance(secret, str):
            raise ProviderValidationError("Provider credential must be text")
        if isinstance(secret, str) and secret and not secret.strip():
            raise ProviderValidationError("Provider credential cannot be whitespace")
        if secret:
            succeeded = self._credentials.set(
                PROVIDER_CREDENTIAL_SERVICE, account, secret
            )
        else:
            succeeded = self._credentials.delete(
                PROVIDER_CREDENTIAL_SERVICE, account
            )
        if not succeeded:
            raise ProviderCredentialError(
                f"Unable to update credential for {account}"
            )

    def _restore_credential(self, account: str, old_secret: str | None) -> None:
        if old_secret is None:
            succeeded = self._credentials.delete(
                PROVIDER_CREDENTIAL_SERVICE, account
            )
        else:
            succeeded = self._credentials.set(
                PROVIDER_CREDENTIAL_SERVICE, account, old_secret
            )
        if not succeeded:
            raise ProviderCompensationError(
                f"Unable to restore credential for {account}"
            )

"""M6 Task 1: SettingsSaveTransaction — cross-storage compensation transaction tests.

Covers 17 scenarios (every failure path, success, and safety invariants):
 1. candidate validation failure → zero file writes, zero credential ops
 2. temp JSON serialisation failure
 3. temp file flush/fsync failure
 4. first credential write failure
 5. mid credential write failure, prior changed credentials restored
 6. credential delete failure
 7. JSON replace failure, all credentials restored
 8. rollback itself fails → high severity rollback_errors, not marked success
 9. success path → JSON succeeds, global config updated ONCE
10. any failure does not mutate original app_config
11. any failure does not emit success event
12. API key sentinel scan — no key in JSON, logs, errors, repr, results
13. clear key deletes correct credential
14. previously non-existent credential still non-existent after rollback
15. temp file no residue after success AND failure
16. same-directory temp file + os.replace order verifiable by fake
17. old Phase 1A behaviour not degraded
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from src.controllers.settings_transaction import (
    SCHEMA_VERSION,
    CredentialOperation,
    CredentialSnapshot,
    SettingsSaveResult,
    SettingsSaveTransaction,
)
from src.models.app_config import AppConfig


# ============================================================================
# Fakes
# ============================================================================


class FakeCredentialStore:
    """In-memory credential store with per-account failure injection."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.calls: list[tuple[str, str, str]] = []
        # Per-account failure flags
        self._fail_get: set[tuple[str, str]] = set()
        self._fail_set: set[tuple[str, str]] = set()
        self._fail_delete: set[tuple[str, str]] = set()
        # Global failure — raises OSError
        self._global_get_fail: bool = False
        self._global_set_fail: bool = False
        self._global_delete_fail: bool = False
        # Set failures for specific attempts (first, second, etc.)
        self._set_fail_attempt: int | None = None
        self._set_attempt_count: int = 0
        self._delete_fail_attempt: int | None = None
        self._delete_attempt_count: int = 0

    def get(self, service: str, account: str) -> str | None:
        self.calls.append(("get", service, account))
        if self._global_get_fail or (service, account) in self._fail_get:
            raise OSError(f"Simulated get failure for {service}/{account}")
        return self.values.get((service, account))

    def set(self, service: str, account: str, secret: str) -> bool:
        self.calls.append(("set", service, account, secret))
        self._set_attempt_count += 1
        if self._set_fail_attempt == self._set_attempt_count:
            return False
        if self._global_set_fail or (service, account) in self._fail_set:
            return False
        self.values[(service, account)] = secret
        return True

    def delete(self, service: str, account: str) -> bool:
        self.calls.append(("delete", service, account))
        self._delete_attempt_count += 1
        if self._delete_fail_attempt == self._delete_attempt_count:
            return False
        if self._global_delete_fail or (service, account) in self._fail_delete:
            return False
        self.values.pop((service, account), None)
        return True


class FakeFileOps:
    """Records file operations and can inject failures at specific steps.

    Tracks:
    - temp file creation (path, content)
    - os.replace calls
    - temp file cleanup

    Can be configured to fail on: write, flush, fsync, replace.
    """

    def __init__(self, tmp_dir: Path) -> None:
        self.tmp_dir = tmp_dir
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.temp_files_created: list[Path] = []
        self.temp_content: dict[str, str] = {}  # path str → content
        self.replace_calls: list[tuple[Path, Path]] = []  # (src, dst)
        self.unlink_calls: list[Path] = []

        # Failure injection
        self.fail_write: bool = False
        self.fail_flush: bool = False
        self.fail_fsync: bool = False
        self.fail_replace: bool = False
        self.fail_replace_with: Exception | None = None

    def _create_temp(self, json_str: str) -> Path:
        """Simulate _write_temp_json but with injectable failures."""
        if self.fail_write:
            raise OSError("Simulated write failure")

        fd, name = tempfile.mkstemp(suffix=".tmp", dir=str(self.tmp_dir))
        tmp_path = Path(name)

        try:
            os.write(fd, json_str.encode("utf-8"))
        finally:
            os.close(fd)

        if self.fail_flush:
            # Simulate flush failure — raise after writing
            tmp_path.unlink()
            raise OSError("Simulated flush failure")

        if self.fail_fsync:
            tmp_path.unlink()
            raise OSError("Simulated fsync failure")

        self.temp_files_created.append(tmp_path)
        self.temp_content[str(tmp_path)] = json_str
        return tmp_path

    def _do_replace(self, src: Path, dst: Path) -> None:
        """Simulate os.replace with injectable failure."""
        self.replace_calls.append((src, dst))
        if self.fail_replace:
            if self.fail_replace_with:
                raise self.fail_replace_with
            raise OSError("Simulated replace failure")
        # Actually move the file
        if src.exists():
            src.replace(dst)

    def _do_unlink(self, path: Path) -> None:
        """Best-effort unlink."""
        self.unlink_calls.append(path)
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    def temp_files_remaining(self) -> list[Path]:
        """Return any temp files that still exist on disk."""
        return [p for p in self.temp_files_created if p.exists()]


# ============================================================================
# Helpers
# ============================================================================


def make_config(**overrides: object) -> AppConfig:
    """Build an AppConfig with sensible defaults for testing."""
    kwargs: dict[str, object] = {
        "provider": "deepseek",
        "api_key": "",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-pro",
        "max_file_size_mb": 50,
        "max_content_chars": 4000,
        "language": "zh",
        "theme": "light",
        "provider_profiles": [],
        "active_provider_id": "",
    }
    kwargs.update(overrides)
    return AppConfig(**kwargs)  # type: ignore[arg-type]


class EventCollector:
    """Collects published events for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def __call__(self, name: str, payload: object) -> None:
        self.events.append((name, payload))

    @property
    def success_events(self) -> list[tuple[str, object]]:
        return [(n, p) for n, p in self.events if n == "settings_saved"]

    @property
    def failure_events(self) -> list[tuple[str, object]]:
        return [(n, p) for n, p in self.events if n == "settings_save_failed"]


def scan_for_key(text: str) -> list[str]:
    """Return any substrings that look like API keys in *text*."""
    import re

    hits: list[str] = []
    # Common key prefixes
    patterns = [
        r'sk-[a-zA-Z0-9_-]{8,}',
        r'sk-ant-[a-zA-Z0-9_-]{8,}',
        r'Bearer\s+[a-zA-Z0-9_-]{8,}',
    ]
    for pat in patterns:
        hits.extend(re.findall(pat, text))
    return hits


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def store() -> FakeCredentialStore:
    return FakeCredentialStore()


@pytest.fixture
def events() -> EventCollector:
    return EventCollector()


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    d = tmp_path / "config"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def config_file(tmp_dir: Path) -> Path:
    return tmp_dir / "settings.json"


@pytest.fixture
def current_config() -> AppConfig:
    return make_config()


@pytest.fixture
def file_ops(tmp_dir: Path) -> FakeFileOps:
    return FakeFileOps(tmp_dir)


# ============================================================================
# Test 1: candidate validation failure — zero file writes, zero credential ops
# ============================================================================


def test_candidate_validation_fails_blocks_all(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
    current_config: AppConfig,
) -> None:
    """Pre-validation failure must not write files or touch credentials."""
    txn = SettingsSaveTransaction(
        current_config=current_config,
        config_file_path=config_file,
        credential_store=store,
        validator=lambda _: ["provider 字段不能为空"],
        event_publisher=events,
    )

    result = txn.commit(make_config(provider=""))

    assert result.success is False
    assert len(result.errors) == 1
    assert "provider" in result.errors[0]
    assert result.rollback_errors == []

    # Zero credential operations
    assert len(store.calls) == 0
    # Failure event published
    assert len(events.failure_events) == 1
    assert len(events.success_events) == 0
    # JSON file not created
    assert not config_file.exists()


# ============================================================================
# Test 2: temp JSON serialisation failure
# ============================================================================


def test_temp_serialisation_fails(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
    current_config: AppConfig,
) -> None:
    """When candidate serialisation to JSON fails, report properly."""
    # Use a candidate that can't be serialised
    bad_candidate = make_config()

    # Monkey-patch model_dump to fail
    with patch.object(bad_candidate, "model_dump", side_effect=TypeError("cannot serialize")):
        txn = SettingsSaveTransaction(
            current_config=current_config,
            config_file_path=config_file,
            credential_store=store,
            event_publisher=events,
        )
        result = txn.commit(bad_candidate)

    assert result.success is False
    assert any("序列化" in e for e in result.errors)
    assert result.rollback_errors == []
    # No credential operations
    assert len(store.calls) == 0
    # No file written
    assert not config_file.exists()
    # Failure event
    assert len(events.failure_events) == 1
    assert len(events.success_events) == 0


# ============================================================================
# Test 3: temp file flush/fsync failure
# ============================================================================


def test_temp_fsync_fails(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
    current_config: AppConfig,
) -> None:
    """When fsync fails on the temp file, report failure, no side effects."""
    # Patch tempfile.NamedTemporaryFile to raise on flush/fsync
    original_named_temp = tempfile.NamedTemporaryFile

    def _failing_temp(*args: object, **kwargs: object) -> object:
        t = original_named_temp(*args, **kwargs)
        original_flush = t.flush
        original_fsync = os.fsync

        def _fail_flush() -> None:
            original_flush()
            raise OSError("Simulated flush failure")

        t.flush = _fail_flush  # type: ignore[method-assign]
        return t

    with patch("tempfile.NamedTemporaryFile", side_effect=_failing_temp):
        txn = SettingsSaveTransaction(
            current_config=current_config,
            config_file_path=config_file,
            credential_store=store,
            event_publisher=events,
        )
        result = txn.commit(make_config(api_key="sk-test"))

    assert result.success is False
    assert any("临时文件" in e for e in result.errors)
    # No credential ops executed
    assert len(store.calls) == 0
    # Failure event
    assert len(events.failure_events) == 1
    assert len(events.success_events) == 0


# ============================================================================
# Test 4: first credential write fails — no prior ops to compensate
# ============================================================================


def test_first_credential_write_fails(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
    current_config: AppConfig,
) -> None:
    """When the first (and only) credential write fails, temp file cleaned up."""
    store._global_set_fail = True

    config_setter_called: list[AppConfig] = []

    txn = SettingsSaveTransaction(
        current_config=make_config(api_key="sk-old"),
        config_file_path=config_file,
        credential_store=store,
        config_setter=lambda c: config_setter_called.append(c),
        event_publisher=events,
    )

    result = txn.commit(make_config(api_key="sk-new"))

    assert result.success is False
    assert any("凭据操作失败" in e for e in result.errors)
    assert result.rollback_errors == []  # no prior ops to compensate
    # Config setter NOT called
    assert len(config_setter_called) == 0
    # Failure event
    assert len(events.failure_events) == 1
    assert len(events.success_events) == 0
    # JSON not replaced
    assert not config_file.exists()


# ============================================================================
# Test 5: mid-credential write fails, prior changed credentials restored
# ============================================================================


def test_mid_credential_write_fails_rollback(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
    current_config: AppConfig,
) -> None:
    """When the second credential operation fails, the first is rolled back."""

    # We need two credential operations.  Extend the transaction to accept
    # an explicit credential_operations list via a subclass or custom planner.
    # For the standard transaction, only api_key produces one op.
    # We test this scenario by injecting a custom _derive_credential_operations.
    class MultiCredTxn(SettingsSaveTransaction):
        def _derive_credential_operations(self, candidate: AppConfig) -> list[CredentialOperation]:
            return [
                CredentialOperation("SvcA", "acct1", "set", "secret-a"),
                CredentialOperation("SvcB", "acct2", "set", "secret-b"),
            ]

    # Make the second operation fail
    store._set_fail_attempt = 2
    # Pre-populate existing values in store
    store.values[("SvcA", "acct1")] = "old-secret-a"
    store.values[("SvcB", "acct2")] = "old-secret-b"

    config_setter_called: list[AppConfig] = []

    txn = MultiCredTxn(
        current_config=current_config,
        config_file_path=config_file,
        credential_store=store,
        config_setter=lambda c: config_setter_called.append(c),
        event_publisher=events,
    )

    result = txn.commit(make_config())

    assert result.success is False
    assert any("凭据操作失败" in e for e in result.errors)
    assert result.rollback_errors == []  # compensation succeeded

    # First credential ("SvcA", "acct1") was set then rolled back
    assert store.values.get(("SvcA", "acct1")) == "old-secret-a", (
        "First credential NOT restored to old value"
    )
    # Second credential never changed
    assert store.values.get(("SvcB", "acct2")) == "old-secret-b"

    # Config not updated
    assert len(config_setter_called) == 0
    # JSON not replaced
    assert not config_file.exists()
    # Failure event
    assert len(events.failure_events) == 1
    assert len(events.success_events) == 0


# ============================================================================
# Test 6: credential delete failure
# ============================================================================


def test_credential_delete_fails(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
    current_config: AppConfig,
) -> None:
    """When credential deletion fails (clearing key), fail-closed."""
    store.values[("AIRenamer", "api_key")] = "sk-existing"
    store._global_delete_fail = True

    config_setter_called: list[AppConfig] = []

    txn = SettingsSaveTransaction(
        current_config=make_config(api_key="sk-existing"),
        config_file_path=config_file,
        credential_store=store,
        config_setter=lambda c: config_setter_called.append(c),
        event_publisher=events,
    )

    # Candidate clears the key
    result = txn.commit(make_config(api_key=""))

    assert result.success is False
    assert any("凭据操作失败" in e for e in result.errors)
    # Config NOT updated
    assert len(config_setter_called) == 0
    # JSON NOT written
    assert not config_file.exists()
    # Credential still exists (delete failed)
    assert store.values.get(("AIRenamer", "api_key")) == "sk-existing"


# ============================================================================
# Test 7: JSON replace fails, all credentials restored
# ============================================================================


def test_json_replace_fails_rollback_all_credentials(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
    current_config: AppConfig,
) -> None:
    """When os.replace fails, ALL credential changes are compensated."""
    # Pre-populate credentials
    store.values[("AIRenamer", "api_key")] = "sk-old-key"

    config_setter_called: list[AppConfig] = []

    txn = SettingsSaveTransaction(
        current_config=make_config(api_key="sk-old-key"),
        config_file_path=config_file,
        credential_store=store,
        config_setter=lambda c: config_setter_called.append(c),
        event_publisher=events,
    )

    # Patch os.replace to fail
    with patch("os.replace", side_effect=OSError("Simulated replace failure")):
        result = txn.commit(make_config(api_key="sk-new-key"))

    assert result.success is False
    assert any("JSON" in e or "替换" in e for e in result.errors)
    assert result.rollback_errors == []  # compensation succeeded

    # Credential restored to old value
    assert store.values.get(("AIRenamer", "api_key")) == "sk-old-key", (
        "Credential NOT restored after JSON replace failure"
    )
    # Config NOT updated
    assert len(config_setter_called) == 0
    # Failure event
    assert len(events.failure_events) == 1


# ============================================================================
# Test 8: rollback itself fails — high severity rollback_errors
# ============================================================================


def test_rollback_failure_reports_high_severity(
    store: FakeCredentialStore,
    config_file: Path,
    current_config: AppConfig,
) -> None:
    """When compensation itself fails, report rollback_errors, NOT success.

    Strategy: use a store whose *second* set() call for each account fails.
    The first set (initial credential write) succeeds for both accounts.
    JSON replace then fails → compensation tries to set() again to restore
    old values.  The second set() for the first compensated account fails,
    producing rollback_errors.
    """

    # Inject multiple credential ops — two set operations
    class TwoCredTxn(SettingsSaveTransaction):
        def _derive_credential_operations(self, candidate: AppConfig) -> list[CredentialOperation]:
            return [
                CredentialOperation("Svc1", "a", "set", "secret-1"),
                CredentialOperation("Svc2", "b", "set", "secret-2"),
            ]

    # Pre-populate old values so compensation has something to restore
    store.values[("Svc1", "a")] = "old-1"
    store.values[("Svc2", "b")] = "old-2"

    # Make the 3rd set() call fail.
    # Call order: set(Svc1)=ok(1), set(Svc2)=ok(2), JSON fails,
    #   compensate-reverse: set(Svc2, old-2)=FAIL(3), set(Svc1, old-1)=ok(4)
    store._set_fail_attempt = 3

    txn = TwoCredTxn(
        current_config=current_config,
        config_file_path=config_file,
        credential_store=store,
    )

    # JSON replace fails → triggers compensation
    with patch("os.replace", side_effect=OSError("Simulated replace failure")):
        result = txn.commit(make_config())

    assert result.success is False, "Must NOT report success when rollback also fails"
    assert len(result.errors) > 0, "Primary errors must be populated"
    assert len(result.rollback_errors) > 0, (
        "Rollback errors must be populated when compensation fails"
    )


# ============================================================================
# Test 9: success path — JSON succeeds, global config updated ONCE
# ============================================================================


def test_success_updates_global_once(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
    current_config: AppConfig,
) -> None:
    """Successful transaction: JSON written, credential saved, config updated once."""
    store.values[("AIRenamer", "api_key")] = "sk-old"

    global_configs: list[AppConfig] = []

    txn = SettingsSaveTransaction(
        current_config=make_config(api_key="sk-old", provider="openai"),
        config_file_path=config_file,
        credential_store=store,
        config_setter=lambda c: global_configs.append(c),
        event_publisher=events,
    )

    candidate = make_config(api_key="sk-new", provider="deepseek", max_file_size_mb=99)
    result = txn.commit(candidate)

    assert result.success is True
    assert result.errors == []
    assert result.rollback_errors == []

    # Config setter called exactly ONCE
    assert len(global_configs) == 1
    assert global_configs[0].provider == "deepseek"
    assert global_configs[0].max_file_size_mb == 99
    assert global_configs[0].api_key == "sk-new"

    # JSON file exists with correct content
    assert config_file.exists()
    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert "api_key" not in saved, "api_key MUST NOT appear in saved JSON"
    assert saved["provider"] == "deepseek"
    assert saved["max_file_size_mb"] == 99
    assert saved.get("schema_version") == SCHEMA_VERSION

    # Credential stored
    assert store.values.get(("AIRenamer", "api_key")) == "sk-new"

    # Success event published
    assert len(events.success_events) == 1
    assert len(events.failure_events) == 0


# ============================================================================
# Test 10: any failure does not mutate original app_config
# ============================================================================


def test_failure_does_not_mutate_global(
    store: FakeCredentialStore,
    config_file: Path,
) -> None:
    """When save fails, the original AppConfig object stays unchanged."""
    original = make_config(
        api_key="sk-original",
        provider="openai",
        model="gpt-4o",
        base_url="https://api.openai.com/v1",
        max_file_size_mb=30,
    )

    global_ref: list[AppConfig] = [original]

    store._global_set_fail = True  # force credential write failure

    txn = SettingsSaveTransaction(
        current_config=original,
        config_file_path=config_file,
        credential_store=store,
        config_setter=lambda c: global_ref.__setitem__(0, c),
    )

    result = txn.commit(make_config(api_key="sk-new", provider="deepseek"))

    assert result.success is False
    # Original must be UNCHANGED
    assert global_ref[0] is original, "Global config reference was replaced despite failure"
    assert original.provider == "openai"
    assert original.api_key == "sk-original"
    assert original.model == "gpt-4o"


# ============================================================================
# Test 11: any failure does not emit success event
# ============================================================================


def test_failure_never_emits_success(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
    current_config: AppConfig,
) -> None:
    """Every failure path must publish settings_save_failed, never settings_saved."""

    # Path 1: validation failure — inject a validator that always rejects
    events.events.clear()
    txn_v = SettingsSaveTransaction(
        current_config=make_config(),
        config_file_path=config_file,
        credential_store=store,
        validator=lambda _: ["validation error"],
        event_publisher=events,
    )
    r_v = txn_v.commit(make_config())
    assert r_v.success is False, "validation failure: expected failure"
    assert len(events.success_events) == 0, (
        "validation failure: must NOT emit settings_saved"
    )

    # Path 2: credential write failure
    events.events.clear()
    store_2 = FakeCredentialStore()
    store_2._global_set_fail = True
    txn_c = SettingsSaveTransaction(
        current_config=make_config(api_key="sk-old"),
        config_file_path=config_file,
        credential_store=store_2,
        event_publisher=events,
    )
    r_c = txn_c.commit(make_config(api_key="sk-new"))
    assert r_c.success is False, "credential failure: expected failure"
    assert len(events.success_events) == 0, (
        "credential failure: must NOT emit settings_saved"
    )


# ============================================================================
def test_serialise_json_recursively_removes_credential_like_extra_fields():
    candidate = AppConfig.model_validate({
        "provider": "qwen",
        "api-key": "TOP-LEVEL-SENTINEL",
        "future": {
            "access_token": "NESTED-SENTINEL",
            "safe_value": "kept",
        },
    })
    payload = SettingsSaveTransaction._serialise_json(candidate)
    assert payload is not None
    assert "TOP-LEVEL-SENTINEL" not in payload
    assert "NESTED-SENTINEL" not in payload
    assert "api-key" not in payload
    assert "access_token" not in payload
    assert json.loads(payload)["future"]["safe_value"] == "kept"


# Test 12: API key sentinel scan — no key in JSON, errors, repr, results
# ============================================================================


def test_key_never_in_json_or_errors(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
    current_config: AppConfig,
) -> None:
    """API key must not appear in JSON output, error messages, or repr."""
    test_key = "sk-super-secret-test-key-do-not-leak"

    # --- Successful save: JSON must NOT contain the key ---
    txn = SettingsSaveTransaction(
        current_config=make_config(api_key=""),
        config_file_path=config_file,
        credential_store=store,
        event_publisher=events,
    )

    result = txn.commit(make_config(api_key=test_key, provider="deepseek"))
    assert result.success is True

    # Check JSON
    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert "api_key" not in saved, "api_key leaked into saved JSON"
    # Scan JSON text for key patterns
    json_text = config_file.read_text(encoding="utf-8")
    assert test_key not in json_text, "API key value found in JSON text"
    assert scan_for_key(json_text) == [], f"API key pattern found in JSON: {scan_for_key(json_text)}"

    # Check result repr
    repr_text = repr(result)
    assert test_key not in repr_text, "API key leaked into result repr"

    # Check error objects
    for err in result.errors:
        assert test_key not in err, "API key leaked into error message"


def test_key_not_in_failure_errors(
    store: FakeCredentialStore,
    config_file: Path,
    current_config: AppConfig,
) -> None:
    """Even on failure, error messages must not leak API key material."""
    test_key = "sk-leak-test-key-12345678"
    store.values[("AIRenamer", "api_key")] = "sk-old"

    # Force JSON replace failure AFTER credential write
    class KeyLeakTxn(SettingsSaveTransaction):
        def _derive_credential_operations(self, candidate: AppConfig) -> list[CredentialOperation]:
            return [
                CredentialOperation("AIRenamer", "api_key", "set", candidate.api_key)
            ]

    txn = KeyLeakTxn(
        current_config=make_config(api_key="sk-old"),
        config_file_path=config_file,
        credential_store=store,
    )

    with patch("os.replace", side_effect=OSError("disk full")):
        result = txn.commit(make_config(api_key=test_key))

    assert result.success is False

    # Scan ALL error text for key
    all_text = repr(result) + " ".join(result.errors) + " ".join(result.rollback_errors)
    assert test_key not in all_text, f"API key leaked into error output: {all_text[:200]}"
    assert scan_for_key(all_text) == [], f"Key pattern found in output: {scan_for_key(all_text)}"


# ============================================================================
# Test 13: clear key deletes correct credential
# ============================================================================


def test_clear_key_deletes_correct_credential(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
    current_config: AppConfig,
) -> None:
    """When api_key is cleared, the correct credential is deleted."""
    store.values[("AIRenamer", "api_key")] = "sk-to-be-deleted"

    txn = SettingsSaveTransaction(
        current_config=make_config(api_key="sk-to-be-deleted"),
        config_file_path=config_file,
        credential_store=store,
        event_publisher=events,
    )

    result = txn.commit(make_config(api_key=""))

    assert result.success is True
    # Credential must be gone
    assert ("AIRenamer", "api_key") not in store.values, (
        "Credential should be deleted when key is cleared"
    )
    # JSON must NOT contain api_key
    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert "api_key" not in saved
    # Success event
    assert len(events.success_events) == 1


# ============================================================================
# Test 14: previously non-existent credential still non-existent after rollback
# ============================================================================


def test_nonexistent_credential_remains_nonexistent_after_rollback(
    store: FakeCredentialStore,
    config_file: Path,
    current_config: AppConfig,
) -> None:
    """When a credential didn't exist before and we roll back, it must not exist."""
    # No pre-existing credential at ("AIRenamer", "api_key")
    assert ("AIRenamer", "api_key") not in store.values

    txn = SettingsSaveTransaction(
        current_config=make_config(api_key=""),  # no existing key
        config_file_path=config_file,
        credential_store=store,
    )

    # Force JSON replace to fail, triggering compensation of the credential set
    with patch("os.replace", side_effect=OSError("simulated")):
        result = txn.commit(make_config(api_key="sk-new-key"))

    assert result.success is False
    # After compensation, credential must NOT exist (it didn't before)
    assert ("AIRenamer", "api_key") not in store.values, (
        "Credential should NOT exist after rollback — it did not exist before"
    )


# ============================================================================
# Test 15: temp file no residue after success AND failure
# ============================================================================


def test_temp_file_no_residue_after_success(
    store: FakeCredentialStore,
    config_file: Path,
    current_config: AppConfig,
    tmp_dir: Path,
) -> None:
    """After a successful transaction, no .tmp files remain."""
    txn = SettingsSaveTransaction(
        current_config=make_config(),
        config_file_path=config_file,
        credential_store=store,
    )

    # Count .tmp files before
    tmps_before = set(tmp_dir.glob("*.tmp"))
    result = txn.commit(make_config(api_key="sk-test"))
    assert result.success is True

    # No NEW .tmp files
    tmps_after = set(tmp_dir.glob("*.tmp"))
    assert tmps_before == tmps_after, f"Temp files left behind: {tmps_after - tmps_before}"


def test_temp_file_no_residue_after_failure(
    store: FakeCredentialStore,
    config_file: Path,
    current_config: AppConfig,
    tmp_dir: Path,
) -> None:
    """After a failed transaction, no .tmp files remain."""
    store._global_set_fail = True  # force credential failure

    txn = SettingsSaveTransaction(
        current_config=make_config(),
        config_file_path=config_file,
        credential_store=store,
    )

    tmps_before = set(tmp_dir.glob("*.tmp"))
    result = txn.commit(make_config(api_key="sk-test"))
    assert result.success is False

    tmps_after = set(tmp_dir.glob("*.tmp"))
    assert tmps_before == tmps_after, f"Temp files left behind after failure: {tmps_after - tmps_before}"


# ============================================================================
# Test 16: same-dir temp file + os.replace order verifiable by fake
# ============================================================================


def test_temp_file_same_directory_and_replace_order(
    store: FakeCredentialStore,
    config_file: Path,
    current_config: AppConfig,
    tmp_dir: Path,
) -> None:
    """Verify that the temp file is created in the same directory as settings.json
    and that os.replace is called with (temp, real) arguments."""
    replace_args: list[tuple[str, str]] = []

    original_replace = os.replace

    def _tracking_replace(src: str, dst: str) -> None:
        replace_args.append((src, dst))
        original_replace(src, dst)

    txn = SettingsSaveTransaction(
        current_config=make_config(),
        config_file_path=config_file,
        credential_store=store,
    )

    with patch("os.replace", side_effect=_tracking_replace):
        result = txn.commit(make_config(api_key="sk-test"))

    assert result.success is True
    assert len(replace_args) == 1, f"Expected 1 os.replace call, got {len(replace_args)}"
    src, dst = replace_args[0]
    # Source is in the same directory as dst
    assert str(Path(src).parent) == str(Path(dst).parent), (
        f"Temp file {src} not in same dir as config {dst}"
    )
    # Source is a .tmp file
    assert src.endswith(".tmp"), f"Source not a .tmp file: {src}"
    # Destination is the config file
    assert Path(dst) == config_file, f"Replace dst {dst} != config file {config_file}"


# ============================================================================
# Test 17: old Phase 1A behaviour not degraded
# ============================================================================


def test_legacy_save_config_still_works(
    temp_config_dir: tuple[Path, Path],
    mock_keyring: dict[str, str],
) -> None:
    """Phase 1A save_config() must still work correctly."""
    from src.config import load_config, save_config

    config_dir, config_file = temp_config_dir
    config_dir.mkdir(parents=True, exist_ok=True)

    config = AppConfig(
        provider="deepseek",
        api_key="sk-legacy-test",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
    )
    save_config(config)

    # Verify credential saved
    assert mock_keyring.get("AIRenamer/api_key") == "sk-legacy-test"

    # Verify JSON has no api_key
    with open(config_file, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert "api_key" not in saved

    # Load back
    loaded = load_config()
    assert loaded.api_key == "sk-legacy-test"
    assert loaded.provider == "deepseek"


def test_legacy_load_config_still_works(
    temp_config_dir: tuple[Path, Path],
    mock_keyring: dict[str, str],
) -> None:
    """Phase 1A load_config() still correctly loads and migrates."""
    from src.config import load_config

    config_dir, config_file = temp_config_dir
    config_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
    }
    config_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    mock_keyring["AIRenamer/api_key"] = "sk-from-ring"

    config = load_config()
    assert config.provider == "openai"
    assert config.api_key == "sk-from-ring"


def test_legacy_fail_closed_still_works(
    temp_config_dir: tuple[Path, Path],
    mock_keyring_failing: dict[str, str],
) -> None:
    """Phase 1A fail-closed behaviour: CredentialSaveError on keyring failure."""
    from src.config import CredentialSaveError, save_config

    config_dir, config_file = temp_config_dir
    config_dir.mkdir(parents=True, exist_ok=True)

    config = AppConfig(api_key="sk-should-fail", provider="deepseek")

    with pytest.raises(CredentialSaveError):
        save_config(config)

    # JSON NOT written
    assert not config_file.exists() or config_file.read_text() == ""


def test_legacy_save_no_key_succeeds_when_keyring_fails(
    temp_config_dir: tuple[Path, Path],
    mock_keyring_failing: dict[str, str],
) -> None:
    """Phase 1A: no key → no credential save needed → succeeds."""
    from src.config import save_config

    config_dir, config_file = temp_config_dir
    config_dir.mkdir(parents=True, exist_ok=True)

    config = AppConfig(api_key="", provider="deepseek", model="deepseek-v4-pro")
    save_config(config)

    with open(config_file, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved.get("provider") == "deepseek"
    assert "api_key" not in saved


# ============================================================================
# Additional edge-case tests
# ============================================================================


def test_no_credential_changes_succeeds(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
) -> None:
    """When api_key hasn't changed, no credential ops — still succeeds."""
    txn = SettingsSaveTransaction(
        current_config=make_config(api_key="sk-same", provider="openai"),
        config_file_path=config_file,
        credential_store=store,
        event_publisher=events,
    )

    result = txn.commit(make_config(api_key="sk-same", provider="deepseek"))
    assert result.success is True
    # No credential calls (api_key unchanged)
    cred_calls = [c for c in store.calls if c[0] in ("set", "delete")]
    assert len(cred_calls) == 0
    # JSON updated
    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved["provider"] == "deepseek"


# ---------------------------------------------------------------------------
# P0-1: Credential snapshot get() failure MUST abort immediately (fail-closed)
# ---------------------------------------------------------------------------


def test_snapshot_get_failure_aborts_transaction(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
    current_config: AppConfig,
    tmp_dir: Path,
) -> None:
    """When credential_store.get() raises during snapshot, the transaction MUST:
    - return success=False immediately
    - execute ZERO set/delete credential operations
    - NOT call os.replace
    - NOT call config_setter
    - NOT publish settings_saved
    - clean up the temp file

    OLD BEHAVIOUR (defective): caught the exception, forged existed=False,
    and continued — would delete a real credential during compensation.
    """
    # Pre-populate a real credential — if we forge existed=False and then
    # something fails, compensation would delete this real credential.
    store.values[("AIRenamer", "api_key")] = "sk-existing-real-value"
    store._global_get_fail = True  # get() will raise

    config_setter_called: list[AppConfig] = []
    tmps_before = set(tmp_dir.glob("*.tmp"))

    txn = SettingsSaveTransaction(
        current_config=make_config(api_key="sk-existing-real-value"),
        config_file_path=config_file,
        credential_store=store,
        config_setter=lambda c: config_setter_called.append(c),
        event_publisher=events,
    )

    result = txn.commit(make_config(api_key="sk-new"))

    # Must report failure
    assert result.success is False, (
        "P0-1: snapshot read failure MUST fail-closed, not forge existed=False"
    )
    # Error message must NOT contain key material
    all_text = " ".join(result.errors) + " ".join(result.rollback_errors) + repr(result)
    assert "sk-existing-real-value" not in all_text, "P0-1: error must not leak credentials"
    assert "sk-new" not in all_text, "P0-1: error must not leak credentials"

    # Zero credential mutations
    set_or_delete = [c for c in store.calls if c[0] in ("set", "delete")]
    assert len(set_or_delete) == 0, (
        "P0-1: must not execute any credential mutation when snapshot read fails"
    )

    # No config_setter call
    assert len(config_setter_called) == 0

    # Existing credential untouched
    assert store.values.get(("AIRenamer", "api_key")) == "sk-existing-real-value", (
        "P0-1: existing credential must not be altered"
    )

    # No JSON written
    assert not config_file.exists(), "P0-1: JSON must not be written"

    # No temp file residue
    tmps_after = set(tmp_dir.glob("*.tmp"))
    assert tmps_before == tmps_after, "P0-1: temp file must be cleaned up"

    # No success event
    assert len(events.success_events) == 0, "P0-1: must not publish settings_saved"


def test_multiple_credential_types_in_transaction(
    store: FakeCredentialStore,
    config_file: Path,
    current_config: AppConfig,
) -> None:
    """Transaction correctly handles set + delete operations in sequence."""

    class MixedCredTxn(SettingsSaveTransaction):
        def _derive_credential_operations(self, candidate: AppConfig) -> list[CredentialOperation]:
            return [
                CredentialOperation("SvcA", "a", "set", "val-a"),
                CredentialOperation("SvcB", "b", "delete"),
                CredentialOperation("SvcC", "c", "set", "val-c"),
            ]

    store.values[("SvcA", "a")] = "old-a"
    store.values[("SvcB", "b")] = "old-b"
    # ("SvcC", "c") does NOT pre-exist

    config_setter_called: list[AppConfig] = []

    txn = MixedCredTxn(
        current_config=current_config,
        config_file_path=config_file,
        credential_store=store,
        config_setter=lambda c: config_setter_called.append(c),
    )

    result = txn.commit(make_config())
    assert result.success is True
    assert store.values.get(("SvcA", "a")) == "val-a"
    assert ("SvcB", "b") not in store.values
    assert store.values.get(("SvcC", "c")) == "val-c"
    assert len(config_setter_called) == 1


def test_settings_save_result_repr_is_safe(
    store: FakeCredentialStore,
    config_file: Path,
    current_config: AppConfig,
) -> None:
    """SettingsSaveResult.__repr__ must not leak any credential values."""
    result_ok = SettingsSaveResult(success=True)
    r = repr(result_ok)
    assert "sk-" not in r
    assert "key" not in r.lower()

    result_fail = SettingsSaveResult(
        success=False,
        errors=["something went wrong"],
        rollback_errors=["compensation failed"],
    )
    r = repr(result_fail)
    assert "sk-" not in r


# ============================================================================
# P0-2: Event payloads must never carry API keys
# ============================================================================


SENTINEL_KEY = "sk-super-secret-event-key-20260801-do-not-leak"


def _all_event_text(events_collector: EventCollector) -> str:
    """Concatenate repr(payload) for every event."""
    parts: list[str] = []
    for _name, payload in events_collector.events:
        parts.append(repr(payload))
    return " ".join(parts)


def test_success_event_payload_has_no_key(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
) -> None:
    """settings_saved payload MUST NOT be the AppConfig (contains api_key)."""
    txn = SettingsSaveTransaction(
        current_config=make_config(api_key=""),
        config_file_path=config_file,
        credential_store=store,
        event_publisher=events,
    )

    result = txn.commit(make_config(api_key=SENTINEL_KEY, provider="deepseek"))
    assert result.success is True

    # Event payload scan
    all_text = _all_event_text(events)
    assert SENTINEL_KEY not in all_text, (
        f"P0-2: settings_saved event payload leaked API key: {all_text[:200]}"
    )
    assert scan_for_key(all_text) == [], (
        f"P0-2: event payload contains sk- pattern: {scan_for_key(all_text)}"
    )


def test_failure_event_payload_has_no_key(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
) -> None:
    """settings_save_failed payload MUST NOT contain key material."""
    store._global_set_fail = True  # force credential failure

    txn = SettingsSaveTransaction(
        current_config=make_config(api_key="sk-old-key"),
        config_file_path=config_file,
        credential_store=store,
        event_publisher=events,
    )

    result = txn.commit(make_config(api_key=SENTINEL_KEY))
    assert result.success is False

    all_text = _all_event_text(events)
    assert SENTINEL_KEY not in all_text, (
        f"P0-2: failure event payload leaked API key: {all_text[:200]}"
    )
    assert scan_for_key(all_text) == [], (
        f"P0-2: failure event payload contains sk- pattern: {scan_for_key(all_text)}"
    )


# ============================================================================
# P0-3: CredentialOperation / CredentialSnapshot repr must never leak secrets
# ============================================================================


def test_credential_operation_repr_safe() -> None:
    """CredentialOperation.__repr__ must not output .value."""
    op_set = CredentialOperation("Svc", "acct", "set", SENTINEL_KEY)
    r = repr(op_set)
    assert SENTINEL_KEY not in r, f"P0-3: CredentialOperation repr leaked value: {r}"
    assert scan_for_key(r) == [], f"P0-3: CredentialOperation repr sk- pattern: {r}"
    # Must still identify the operation
    assert "Svc" in r
    assert "acct" in r

    op_del = CredentialOperation("Svc", "acct", "delete")
    r2 = repr(op_del)
    assert scan_for_key(r2) == []


def test_credential_snapshot_repr_safe() -> None:
    """CredentialSnapshot.__repr__ must not output .old_value."""
    snap = CredentialSnapshot("Svc", "acct", SENTINEL_KEY, True)
    r = repr(snap)
    assert SENTINEL_KEY not in r, f"P0-3: CredentialSnapshot repr leaked old_value: {r}"
    assert scan_for_key(r) == [], f"P0-3: CredentialSnapshot repr sk- pattern: {r}"
    # Must still identify the snapshot
    assert "Svc" in r
    assert "acct" in r


# ============================================================================
# Config setter failure fault path (new transaction path)
# ============================================================================


def test_config_setter_failure_restores_json(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
    tmp_dir: Path,
) -> None:
    """When config_setter raises after os.replace succeeds, the transaction
    MUST restore the original JSON bytes and credentials."""
    sentinel_cs = "sk-cs-json-restore-key"

    # Pre-write a known settings.json
    original_json = json.dumps(
        {"provider": "openai", "model": "gpt-4o", "schema_version": 2},
        indent=2, ensure_ascii=False,
    )
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(original_json, encoding="utf-8")

    # Pre-populate credential
    store.values[("AIRenamer", "api_key")] = "sk-old-cred"

    config_setter_called: list[AppConfig] = []

    def _failing_setter(cfg: AppConfig) -> None:
        config_setter_called.append(cfg)
        raise RuntimeError("Simulated config setter failure")

    txn = SettingsSaveTransaction(
        current_config=make_config(api_key="sk-old-cred", provider="openai"),
        config_file_path=config_file,
        credential_store=store,
        config_setter=_failing_setter,
        event_publisher=events,
    )

    candidate = make_config(api_key=sentinel_cs, provider="deepseek", model="deepseek-v4-pro")
    tmps_before = set(tmp_dir.glob("*.tmp"))

    result = txn.commit(candidate)

    # Must report failure
    assert result.success is False, (
        "config_setter failure: must return controlled failure, not propagate exception"
    )
    # No success event
    assert len(events.success_events) == 0

    # JSON must be RESTORED to original content
    assert config_file.exists(), "Original JSON must still exist after restoration"
    restored_text = config_file.read_text(encoding="utf-8")
    restored = json.loads(restored_text)
    assert restored.get("provider") == "openai", (
        f"JSON not restored: {restored_text[:200]}"
    )
    assert restored.get("model") == "gpt-4o"

    # Credential must be RESTORED to old value
    assert store.values.get(("AIRenamer", "api_key")) == "sk-old-cred", (
        "Credential not restored after config_setter failure"
    )

    # Sentinel key NOT in errors/repr/JSON
    all_text = " ".join(result.errors) + " ".join(result.rollback_errors)
    all_text += repr(result) + restored_text
    assert sentinel_cs not in all_text, "P0: sentinel key leaked into error/JSON after config_setter failure"

    # No temp file residue
    tmps_after = set(tmp_dir.glob("*.tmp"))
    assert tmps_before == tmps_after, "Temp file must be cleaned up"


def test_config_setter_failure_restores_nonexistent_json(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
    tmp_dir: Path,
) -> None:
    """When config_setter raises and settings.json did NOT exist before,
    the file must be restored to non-existence."""
    # Ensure no settings.json exists
    assert not config_file.exists()

    store.values[("AIRenamer", "api_key")] = "sk-old"

    def _failing_setter(cfg: AppConfig) -> None:
        raise RuntimeError("setter failure")

    txn = SettingsSaveTransaction(
        current_config=make_config(api_key="sk-old"),
        config_file_path=config_file,
        credential_store=store,
        config_setter=_failing_setter,
        event_publisher=events,
    )

    result = txn.commit(make_config(api_key="sk-new-key"))
    assert result.success is False
    assert len(events.success_events) == 0

    # JSON must NOT exist (restored to pre-transaction state)
    assert not config_file.exists(), (
        "settings.json must be removed when it did not exist before"
    )
    # Credential restored
    assert store.values.get(("AIRenamer", "api_key")) == "sk-old"


def test_config_setter_failure_compensation_errors(
    store: FakeCredentialStore,
    config_file: Path,
) -> None:
    """When config_setter fails AND compensation partially fails,
    report rollback_errors MUST be non-empty, NOT success."""
    # Pre-write original JSON
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        json.dumps({"provider": "openai", "schema_version": 2}),
        encoding="utf-8",
    )
    store.values[("AIRenamer", "api_key")] = "sk-old"

    def _failing_setter(cfg: AppConfig) -> None:
        raise RuntimeError("setter failure")

    txn = SettingsSaveTransaction(
        current_config=make_config(api_key="sk-old"),
        config_file_path=config_file,
        credential_store=store,
        config_setter=_failing_setter,
    )

    # Make credential compensation fail
    store._set_fail_attempt = 2  # initial set = ok (1), compensation set = fail (2)

    result = txn.commit(make_config(api_key="sk-new-key"))
    assert result.success is False
    assert len(result.errors) > 0
    # FIXED assertion: must NOT be weak "may have failed"
    assert len(result.rollback_errors) > 0, (
        "rollback_errors MUST be non-empty when credential compensation fails"
    )
    assert not result.success, "Must not report success when compensation fails"


def test_config_setter_failure_key_not_in_any_output(
    store: FakeCredentialStore,
    config_file: Path,
) -> None:
    """After config_setter failure, no sentinel key appears in errors,
    rollback_errors, repr, or JSON."""
    sentinel = "sk-cs-output-leak-check-12345"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        json.dumps({"provider": "openai", "schema_version": 2}),
        encoding="utf-8",
    )

    def _failing_setter(cfg: AppConfig) -> None:
        raise RuntimeError("setter failure")

    txn = SettingsSaveTransaction(
        current_config=make_config(api_key="sk-old"),
        config_file_path=config_file,
        credential_store=store,
        config_setter=_failing_setter,
    )

    result = txn.commit(make_config(api_key=sentinel))
    assert result.success is False

    all_text = repr(result)
    all_text += " ".join(result.errors)
    all_text += " ".join(result.rollback_errors)
    if config_file.exists():
        all_text += config_file.read_text(encoding="utf-8")

    assert sentinel not in all_text, (
        f"P0: sentinel key leaked into output after config_setter failure: {all_text[:200]}"
    )
    assert scan_for_key(all_text) == [], (
        f"P0: sk- key pattern found in output: {scan_for_key(all_text)}"
    )


# ============================================================================
# 一、Original JSON read failure (three-state semantics)
# ============================================================================

SENTINEL_K2 = "sk-json-read-fail-permission-20260801"


def test_original_json_read_failure_aborts_before_all_side_effects(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
    current_config: AppConfig,
    tmp_dir: Path,
) -> None:
    """When read_bytes() raises PermissionError during JSON snapshot,
    the transaction MUST abort before ANY side effect:
    - no temp file created
    - no credential read or write
    - no os.replace
    - no config_setter
    - no settings_saved event
    """
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        json.dumps({"provider": "openai", "schema_version": 2}),
        encoding="utf-8",
    )

    config_setter_called: list[AppConfig] = []
    tmps_before = set(tmp_dir.glob("*.tmp"))

    original_read_bytes = config_file.read_bytes

    def _failing_read_bytes() -> bytes:
        raise PermissionError("Simulated permission denied reading settings.json")

    txn = SettingsSaveTransaction(
        current_config=current_config,
        config_file_path=config_file,
        credential_store=store,
        config_setter=lambda c: config_setter_called.append(c),
        event_publisher=events,
    )

    with patch.object(config_file.__class__, "read_bytes", side_effect=_failing_read_bytes):
        result = txn.commit(make_config(api_key=SENTINEL_K2))

    assert result.success is False, "JSON read failure must abort transaction"
    # Generic safe error, no permission error text or key
    all_err = " ".join(result.errors)
    assert SENTINEL_K2 not in all_err
    assert "Permission" not in all_err
    assert scan_for_key(all_err) == []

    assert len(config_setter_called) == 0, "config_setter must not be called"
    assert len(events.success_events) == 0, "no success event"
    # Zero credential operations
    set_or_del = [c for c in store.calls if c[0] in ("set", "delete")]
    assert len(set_or_del) == 0, "no credential mutations"
    # No temp file residue
    tmps_after = set(tmp_dir.glob("*.tmp"))
    assert tmps_before == tmps_after, "no temp files"


# ============================================================================
# 二、Config setter failure restores in-memory state
# ============================================================================


def test_config_setter_failure_restores_memory_state(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
    tmp_dir: Path,
) -> None:
    """When config_setter(candidate) partially mutates memory then raises,
    the transaction must call config_setter(current_config) to restore."""
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        json.dumps({"provider": "openai", "schema_version": 2}),
        encoding="utf-8",
    )
    store.values[("AIRenamer", "api_key")] = "sk-old-mem"

    current = make_config(api_key="sk-old-mem", provider="openai", model="gpt-4o")
    holder: list[AppConfig] = [current]

    def _partially_mutating_setter(cfg: AppConfig) -> None:
        # Simulate partial mutation: change the holder first, then raise
        holder[0] = cfg
        raise RuntimeError("setter failed after mutation")

    txn = SettingsSaveTransaction(
        current_config=current,
        config_file_path=config_file,
        credential_store=store,
        config_setter=_partially_mutating_setter,
        event_publisher=events,
    )

    candidate = make_config(api_key="sk-new-mem", provider="deepseek", model="deepseek-v4-pro")
    result = txn.commit(candidate)

    assert result.success is False
    assert len(events.success_events) == 0

    # Memory MUST be restored to current_config
    assert holder[0].provider == "openai", f"Memory not restored: provider={holder[0].provider}"
    assert holder[0].api_key == "sk-old-mem", f"Memory not restored: api_key={holder[0].api_key}"
    assert holder[0].model == "gpt-4o", f"Memory not restored: model={holder[0].model}"

    # JSON restored
    assert config_file.exists()
    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved.get("provider") == "openai"

    # Credential restored
    assert store.values.get(("AIRenamer", "api_key")) == "sk-old-mem"


def test_config_setter_failure_with_memory_restore_failure(
    store: FakeCredentialStore,
    config_file: Path,
) -> None:
    """When BOTH candidate setter AND current_config restore fail,
    result.success=False, rollback_errors non-empty, explicitly states memory restore failed."""
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        json.dumps({"provider": "openai", "schema_version": 2}),
        encoding="utf-8",
    )
    store.values[("AIRenamer", "api_key")] = "sk-old-doublefail"

    current = make_config(api_key="sk-old-doublefail", provider="openai")
    call_count = [0]

    def _always_failing_setter(cfg: AppConfig) -> None:
        call_count[0] += 1
        raise RuntimeError("always fails")

    txn = SettingsSaveTransaction(
        current_config=current,
        config_file_path=config_file,
        credential_store=store,
        config_setter=_always_failing_setter,
    )

    result = txn.commit(make_config(api_key="sk-new-doublefail"))
    assert result.success is False
    # Both candidate setter (1) and current_config restore (2) attempted
    assert call_count[0] == 2, f"Expected 2 setter calls, got {call_count[0]}"
    assert len(result.rollback_errors) > 0, (
        "rollback_errors MUST be non-empty when memory restore also fails"
    )
    assert any("内存" in e or "memory" in e.lower() for e in result.rollback_errors), (
        "rollback_errors must indicate memory restore failure"
    )


def test_compensation_independent_execution(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
) -> None:
    """When JSON restore fails, credential and memory restoration must
    still execute (independent compensation)."""
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        json.dumps({"provider": "openai", "schema_version": 2}),
        encoding="utf-8",
    )
    store.values[("AIRenamer", "api_key")] = "sk-old-indep"

    current = make_config(api_key="sk-old-indep", provider="openai", max_file_size_mb=30)
    holder: list[AppConfig] = [current]

    setter_calls: list[str] = []

    def _tracking_setter(cfg: AppConfig) -> None:
        setter_calls.append("candidate" if cfg.max_file_size_mb == 99 else "restore")
        holder[0] = cfg
        if setter_calls[-1] == "candidate":
            raise RuntimeError("candidate setter failed")

    txn = SettingsSaveTransaction(
        current_config=current,
        config_file_path=config_file,
        credential_store=store,
        config_setter=_tracking_setter,
        event_publisher=events,
    )

    # Make os.replace work but then we'll patch _restore_original_json to fail
    original_restore = txn._restore_original_json

    def _failing_json_restore(original_bytes: bytes | None) -> list[str]:
        # Credential compensation NOT yet called at this point in commit()
        # We just fail the JSON restore
        return ["Simulated JSON restore failure"]

    txn._restore_original_json = _failing_json_restore  # type: ignore[method-assign]

    result = txn.commit(make_config(api_key="sk-new-indep", max_file_size_mb=99))

    assert result.success is False
    # JSON restore failed → in rollback_errors
    assert any("JSON" in e for e in result.rollback_errors), "JSON restore failure must be reported"
    # Credential MUST still be restored (independent)
    assert store.values.get(("AIRenamer", "api_key")) == "sk-old-indep", (
        "Credential must be restored even when JSON restore fails"
    )
    # Memory MUST be restored (independent)
    assert holder[0].provider == "openai", "Memory must be restored even when JSON restore fails"
    assert "restore" in setter_calls, "config_setter(current_config) must be called"
    assert len(events.success_events) == 0


# ============================================================================
# 三、Sanitize exception text in ALL public surface
# ============================================================================


def test_exception_text_sanitized_config_setter(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
) -> None:
    """When config_setter raises with sentinel key in exception message,
    no errors/rollback_errors/events/repr/json contain the sentinel."""
    sentinel = "sk-setter-exc-text-leak-98765"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        json.dumps({"provider": "openai", "schema_version": 2}),
        encoding="utf-8",
    )

    def _leaky_setter(cfg: AppConfig) -> None:
        raise RuntimeError(f"connection failed with key {sentinel}")

    txn = SettingsSaveTransaction(
        current_config=make_config(api_key="sk-old"),
        config_file_path=config_file,
        credential_store=store,
        config_setter=_leaky_setter,
        event_publisher=events,
    )

    result = txn.commit(make_config(api_key="sk-new-safe"))
    assert result.success is False

    # Scan all output surfaces
    surfaces = [
        repr(result),
        " ".join(result.errors),
        " ".join(result.rollback_errors),
        _all_event_text(events),
    ]
    if config_file.exists():
        surfaces.append(config_file.read_text(encoding="utf-8"))

    all_text = " ".join(surfaces)
    assert sentinel not in all_text, (
        f"Sentinel leaked via config_setter exception: {all_text[:300]}"
    )
    assert scan_for_key(all_text) == [], (
        f"sk- pattern leaked via config_setter exception: {scan_for_key(all_text)}"
    )


def test_exception_text_sanitized_validator(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
    current_config: AppConfig,
) -> None:
    """When validator returns an error message containing the API key,
    the result and event payload must NOT leak the key."""
    sentinel = "sk-validator-leak-check-abc"

    txn = SettingsSaveTransaction(
        current_config=current_config,
        config_file_path=config_file,
        credential_store=store,
        validator=lambda c: [f"Provider {c.provider} key {c.api_key} is invalid"],
        event_publisher=events,
    )

    result = txn.commit(make_config(api_key=sentinel, provider="deepseek"))
    assert result.success is False

    all_text = " ".join(result.errors) + " " + repr(result) + " " + _all_event_text(events)
    assert sentinel not in all_text, (
        f"Validator error leaked sentinel key: {all_text[:300]}"
    )
    assert scan_for_key(all_text) == [], (
        f"Validator error leaked sk- pattern: {scan_for_key(all_text)}"
    )


def test_exception_text_sanitized_json_operation(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
    current_config: AppConfig,
) -> None:
    """When a JSON/file operation raises with sentinel in message,
    public output must not leak it."""
    sentinel = "sk-json-op-leak-55555"

    original = tempfile.NamedTemporaryFile

    def _failing_temp(*args: object, **kwargs: object) -> object:
        t = original(*args, **kwargs)
        original_write = t.write

        def _leaky_write(data: str) -> int:
            original_write(data)
            raise OSError(f"Disk full while writing {sentinel}")
        t.write = _leaky_write  # type: ignore[method-assign]
        return t

    txn = SettingsSaveTransaction(
        current_config=make_config(api_key=""),
        config_file_path=config_file,
        credential_store=store,
        event_publisher=events,
    )

    with patch("tempfile.NamedTemporaryFile", side_effect=_failing_temp):
        result = txn.commit(make_config(api_key="sk-json-op-test"))

    assert result.success is False

    all_text = " ".join(result.errors) + " " + repr(result) + " " + _all_event_text(events)
    assert sentinel not in all_text, (
        f"JSON op exception leaked sentinel: {all_text[:300]}"
    )
    assert scan_for_key(all_text) == [], (
        f"JSON op exception leaked sk- pattern: {scan_for_key(all_text)}"
    )


# ============================================================================
# 四、Original JSON atomic restore
# ============================================================================


def test_original_json_atomic_restore_uses_temp_and_replace(
    store: FakeCredentialStore,
    config_file: Path,
    tmp_dir: Path,
) -> None:
    """When restoring original JSON, the implementation must use
    same-directory temp file + fsync + os.replace, not direct write_bytes."""
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        json.dumps({"provider": "openai", "schema_version": 2}),
        encoding="utf-8",
    )
    store.values[("AIRenamer", "api_key")] = "sk-old-atomic"

    replace_calls: list[tuple[str, str]] = []
    _real_replace = os.replace  # capture before patching

    def _tracking_replace(src: str, dst: str) -> None:
        replace_calls.append((src, dst))
        _real_replace(src, dst)  # use original, not patched

    def _failing_setter(cfg: AppConfig) -> None:
        raise RuntimeError("setter fails")

    txn = SettingsSaveTransaction(
        current_config=make_config(api_key="sk-old-atomic"),
        config_file_path=config_file,
        credential_store=store,
        config_setter=_failing_setter,
    )

    with patch("os.replace", side_effect=_tracking_replace):
        result = txn.commit(make_config(api_key="sk-new-atomic"))

    assert result.success is False

    # First replace: candidate temp → settings.json
    # Second replace: restore temp → settings.json
    restore_replaces = [
        (s, d) for s, d in replace_calls
        if Path(d) == config_file
    ]
    assert len(restore_replaces) >= 1, (
        f"os.replace must be called to restore JSON, got {len(restore_replaces)}"
    )
    # The restore replace source must be a .tmp file in same directory
    for src, dst in restore_replaces:
        assert src.endswith(".tmp"), f"Restore source not .tmp: {src}"
        assert str(Path(src).parent) == str(config_file.parent), (
            f"Restore temp not in same directory: {src}"
        )

    # No .tmp residue
    tmps = list(tmp_dir.glob("*.tmp"))
    assert len(tmps) == 0, f"Temp files left: {[str(t) for t in tmps]}"


def test_original_json_atomic_restore_write_fails(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
) -> None:
    """When the atomic restore write fails, rollback_errors is non-empty
    but credential and memory restoration are still attempted."""
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        json.dumps({"provider": "openai", "schema_version": 2}),
        encoding="utf-8",
    )
    store.values[("AIRenamer", "api_key")] = "sk-old-writefail"

    current = make_config(api_key="sk-old-writefail", provider="openai")
    holder: list[AppConfig] = [current]

    setter_calls: list[str] = []

    def _tracking_setter(cfg: AppConfig) -> None:
        setter_calls.append("candidate" if cfg.provider == "deepseek" else "restore")
        holder[0] = cfg
        if setter_calls[-1] == "candidate":
            raise RuntimeError("setter fails")

    txn = SettingsSaveTransaction(
        current_config=current,
        config_file_path=config_file,
        credential_store=store,
        config_setter=_tracking_setter,
        event_publisher=events,
    )

    # Patch os.replace to fail ONLY during restore (second call)
    replace_count = [0]
    original_replace = os.replace

    def _replace_fail_on_second(src: str, dst: str) -> None:
        replace_count[0] += 1
        if replace_count[0] == 2:  # restore call
            raise OSError("Simulated restore disk full")
        original_replace(src, dst)

    with patch("os.replace", side_effect=_replace_fail_on_second):
        result = txn.commit(make_config(api_key="sk-new-wf", provider="deepseek"))

    assert result.success is False
    assert len(result.rollback_errors) > 0, "JSON restore failure must be in rollback_errors"
    # Credential still restored
    assert store.values.get(("AIRenamer", "api_key")) == "sk-old-writefail"
    # Memory still restored
    assert "restore" in setter_calls
    assert holder[0].provider == "openai"
    assert len(events.success_events) == 0


# ============================================================================
# 五、Temp file cleanup on write failure in _write_temp_json
# ============================================================================


def test_temp_file_cleanup_on_write_failure(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
    current_config: AppConfig,
    tmp_dir: Path,
) -> None:
    """When write() itself raises OSError inside _write_temp_json,
    the created temp file must be cleaned up — no residue."""
    original = tempfile.NamedTemporaryFile
    leaked_paths: list[Path] = []

    def _failing_temp(*args: object, **kwargs: object) -> object:
        t = original(*args, **kwargs)
        tmp_path = Path(t.name)
        leaked_paths.append(tmp_path)

        def _fail_write(data: str) -> int:
            raise OSError("Simulated write failure")
        t.write = _fail_write  # type: ignore[method-assign]
        return t

    tmps_before = set(tmp_dir.glob("*.tmp"))

    with patch("tempfile.NamedTemporaryFile", side_effect=_failing_temp):
        txn = SettingsSaveTransaction(
            current_config=current_config,
            config_file_path=config_file,
            credential_store=store,
            event_publisher=events,
        )
        result = txn.commit(make_config(api_key="sk-test-writefail"))

    assert result.success is False
    # Verify our fake tracked the path
    assert len(leaked_paths) > 0
    # The temp file must NOT exist on disk
    for p in leaked_paths:
        assert not p.exists(), f"Temp file left behind: {p}"
    # No new tmp files
    tmps_after = set(tmp_dir.glob("*.tmp"))
    assert tmps_before == tmps_after, f"Temp residue: {tmps_after - tmps_before}"


# ============================================================================
# Task 0: Non-sk-prefixed key redaction
# ============================================================================

NON_SK_SENTINEL = "DASHSCOPE_SECRET_20260801_NOT_SK_PREFIX"


def test_non_sk_prefixed_key_redacted_from_validator_errors(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
    current_config: AppConfig,
) -> None:
    """Validator returns error containing a non-sk-prefixed key.
    The key MUST be precisely redacted from result.errors and events."""
    txn = SettingsSaveTransaction(
        current_config=make_config(api_key=""),
        config_file_path=config_file,
        credential_store=store,
        validator=lambda c: [f"Invalid key: {c.api_key} for provider {c.provider}"],
        event_publisher=events,
    )

    result = txn.commit(make_config(api_key=NON_SK_SENTINEL, provider="qwen"))

    assert result.success is False
    all_text = " ".join(result.errors) + " " + repr(result) + " " + _all_event_text(events)
    assert NON_SK_SENTINEL not in all_text, (
        f"Non-sk key leaked: {all_text[:300]}"
    )
    # "[REDACTED]" should appear where the key was
    assert "[REDACTED]" in all_text, "Key should be replaced with [REDACTED]"


def test_non_sk_prefixed_key_redacted_comprehensive(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
) -> None:
    """Comprehensive scan: non-sk key must not appear in JSON, errors,
    rollback_errors, repr, events, or restored JSON."""
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        json.dumps({"provider": "openai", "schema_version": 2}),
        encoding="utf-8",
    )
    store.values[("AIRenamer", "api_key")] = "sk-old-for-nonsk"

    def _failing_setter(cfg: AppConfig) -> None:
        raise RuntimeError("setter fails")

    txn = SettingsSaveTransaction(
        current_config=make_config(api_key="sk-old-for-nonsk"),
        config_file_path=config_file,
        credential_store=store,
        config_setter=_failing_setter,
        event_publisher=events,
    )

    result = txn.commit(make_config(api_key=NON_SK_SENTINEL, provider="qwen"))

    assert result.success is False

    surfaces = [
        repr(result),
        " ".join(result.errors),
        " ".join(result.rollback_errors),
        _all_event_text(events),
    ]
    if config_file.exists():
        surfaces.append(config_file.read_text(encoding="utf-8"))

    all_text = " ".join(surfaces)
    assert NON_SK_SENTINEL not in all_text, (
        f"Non-sk key leaked in comprehensive scan: {all_text[:300]}"
    )


def test_read_original_json_no_exists_call(
    store: FakeCredentialStore,
    events: EventCollector,
    config_file: Path,
    current_config: AppConfig,
    tmp_dir: Path,
) -> None:
    """_read_original_json calls read_bytes() directly.
    PermissionError still aborts with zero side effects."""
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        json.dumps({"provider": "openai", "schema_version": 2}),
        encoding="utf-8",
    )

    config_setter_called: list[AppConfig] = []

    txn = SettingsSaveTransaction(
        current_config=current_config,
        config_file_path=config_file,
        credential_store=store,
        config_setter=lambda c: config_setter_called.append(c),
        event_publisher=events,
    )

    with patch.object(config_file.__class__, "read_bytes",
                      side_effect=PermissionError("denied")):
        result = txn.commit(make_config(api_key="sk-test"))

    assert result.success is False
    assert len(config_setter_called) == 0
    assert len(events.success_events) == 0

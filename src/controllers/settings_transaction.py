"""SettingsSaveTransaction — cross-storage compensation transaction.

Provides all-or-nothing semantics when persisting AppConfig (JSON) and
credentials (Windows Credential Manager) simultaneously.

The two stores have no native shared transaction.  This module implements a
compensating transaction with candidate config, temp-file, credential
snapshots, and ordered rollback so every failure path leaves both stores
consistent with the pre-transaction state.

Security invariants (non-negotiable):
- API keys / credential values MUST NOT appear in JSON, log messages,
  error objects, repr output, event payloads, or diagnostics.
- Credential-manager unavailability MUST fail closed — never fall back to
  plaintext JSON; never forge "did not exist" when the store is unreadable.
- Clearing a key MUST delete the correct system credential; failure
  restores from snapshot.
- The in-memory global AppConfig MUST NOT be mutated until JSON replace
  succeeds AND config_setter succeeds.
- Temporary files MUST reside in the same directory as settings.json and
  MUST be cleaned up on every path (success and failure).
- Event payloads MUST NOT carry AppConfig (contains api_key) or any
  credential-bearing object.
- Public error messages / event payloads MUST NOT contain raw exception
  text, API keys, or credential values (only stable error codes / fixed
  safe messages).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from src.models.app_config import AppConfig, sanitise_persisted_config

SCHEMA_VERSION = 2

# Broad regex fallback — catches common key-like patterns that the known-secret
# list didn't already cover.  Never the primary defence.
_KEY_FALLBACK_PATTERN = re.compile(r'(?:sk|AKIA|AIza|dashscope|glm|qwen|mimo|kimi)[-_a-zA-Z0-9]{12,}',
                                   re.IGNORECASE)


def _redact_secrets(text: str, known_secrets: frozenset[str]) -> str:
    """Exact-match replace of every *known_secret* in *text*, then apply
    the broad regex fallback for anything that still looks like a key.

    Callers MUST pass every non-empty credential value the transaction is
    aware of (candidate.api_key, current_config.api_key, and any
    provider-key values in CredentialOperation lists).
    """
    for secret in known_secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return _KEY_FALLBACK_PATTERN.sub("[REDACTED]", text)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class CredentialOperation:
    """Describes a single credential mutation to perform.

    The transaction snapshots the *current* value before executing the
    operation so it can be rolled back on failure.

    Security: ``value`` is excluded from repr — the raw secret MUST NOT
    appear in logs, error messages, or diagnostics.
    """

    service: str
    account: str
    action: str  # "set" or "delete"
    value: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.action not in ("set", "delete"):
            raise ValueError(f"Unknown credential action: {self.action}")
        if self.action == "set" and self.value is None:
            raise ValueError("CredentialOperation action='set' requires a value")
        if self.action == "delete":
            self.value = None  # Normalise

    def __repr__(self) -> str:
        return (
            f"CredentialOperation(service={self.service!r}, "
            f"account={self.account!r}, action={self.action!r})"
        )


@dataclass
class CredentialSnapshot:
    """Immutable record of a credential's state *before* mutation.

    Security: ``old_value`` is excluded from repr — the raw secret MUST NOT
    appear in logs, error messages, or diagnostics.
    """

    service: str
    account: str
    old_value: str | None = field(default=None, repr=False)
    existed: bool = True

    def __repr__(self) -> str:
        return (
            f"CredentialSnapshot(service={self.service!r}, "
            f"account={self.account!r}, existed={self.existed})"
        )


@dataclass
class SettingsSaveResult:
    """Outcome of a SettingsSaveTransaction.commit() call.

    ``success`` is True only when JSON and every credential operation
    completed.  ``errors`` lists primary failures; ``rollback_errors``
    lists compensation failures (always empty on success).

    Callers MUST treat any result where ``success`` is False as a hard
    failure: do not close the settings dialog, do not report success, and
    do not assume the global config was updated.
    """

    success: bool
    errors: list[str] = field(default_factory=list)
    rollback_errors: list[str] = field(default_factory=list)

    # Security: __repr__ MUST NOT include credential values, error details
    # that may contain keys, or diagnostic data.
    def __repr__(self) -> str:
        return (
            f"SettingsSaveResult(success={self.success}, "
            f"error_count={len(self.errors)}, "
            f"rollback_error_count={len(self.rollback_errors)})"
        )


# ---------------------------------------------------------------------------
# Private: three-state original JSON snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _OriginalJsonSnapshot:
    """Captures the state of settings.json before any mutation.

    Three states:
    - ``existed=True``, ``contents=b'...'`` — file was present and read
    - ``existed=False``, ``contents=None`` — file definitively absent
    - On read failure the caller receives a sentinel failure result
      instead of an instance of this class.
    """

    existed: bool
    contents: bytes | None = field(default=None, repr=False)

    def __repr__(self) -> str:
        return f"_OriginalJsonSnapshot(existed={self.existed})"


# Sentinel returned by _read_original_json on permission/IO failure.
_JSON_READ_FAILED = object()


# ---------------------------------------------------------------------------
# Injectable protocols / type aliases
# ---------------------------------------------------------------------------


class CredentialStore(Protocol):
    """Protocol for credential read / write / delete.

    Mirrors :class:`src.core.provider_manager.CredentialStore` so the
    transaction can use the same fake in tests.
    """

    def get(self, service: str, account: str) -> str | None: ...

    def set(self, service: str, account: str, secret: str) -> bool: ...

    def delete(self, service: str, account: str) -> bool: ...


Validator = Callable[[AppConfig], list[str]]
"""Return a (possibly-empty) list of error messages.  Empty list = valid."""

ConfigSetter = Callable[[AppConfig], None]
"""Atomically replace the in-memory global AppConfig.  May raise."""

EventPublisher = Callable[[str, Any], None]
"""Publish a named event with a sanitised payload."""


# Error codes (stable, safe to expose)
ERR_JSON_SERIALISE = "ERR_JSON_SERIALISE"
ERR_TEMP_FILE = "ERR_TEMP_FILE"
ERR_CREDENTIAL_SNAPSHOT_READ = "ERR_CREDENTIAL_SNAPSHOT_READ"
ERR_CREDENTIAL_OP = "ERR_CREDENTIAL_OP"
ERR_JSON_REPLACE = "ERR_JSON_REPLACE"
ERR_CONFIG_SETTER = "ERR_CONFIG_SETTER"
ERR_JSON_RESTORE = "ERR_JSON_RESTORE"
ERR_ORIGINAL_JSON_READ = "ERR_ORIGINAL_JSON_READ"
ERR_COMPENSATION = "ERR_COMPENSATION"


# ---------------------------------------------------------------------------
# SettingsSaveTransaction
# ---------------------------------------------------------------------------


class SettingsSaveTransaction:
    """Compensating transaction that persists AppConfig JSON + credentials.

    All external side-effects are injected so the class is fully testable
    without touching real Windows services, the real filesystem, or the
    real Credential Manager.

    Usage::

        txn = SettingsSaveTransaction(
            current_config=app.app_config,
            config_file_path=Path("config/settings.json"),
            credential_store=SystemCredentialStore(),
            validator=my_validate,
            config_setter=lambda cfg: setattr(app, "app_config", cfg),
            event_publisher=lambda name, payload: bus.emit(name, payload),
        )
        result = txn.commit(candidate)
        if not result.success:
            ...  # stay on settings page, show errors
    """

    def __init__(
        self,
        current_config: AppConfig,
        config_file_path: Path,
        credential_store: CredentialStore,
        *,
        validator: Validator | None = None,
        config_setter: ConfigSetter | None = None,
        event_publisher: EventPublisher | None = None,
    ) -> None:
        self._current_config = current_config
        self._config_file_path = config_file_path
        self._credentials = credential_store
        self._validator = validator
        self._config_setter = config_setter
        self._event_publisher = event_publisher

    def _build_known_secrets(
        self,
        candidate: AppConfig,
        credential_operations: list[CredentialOperation] | None = None,
    ) -> frozenset[str]:
        """Collect every non-empty credential value the transaction is
        aware of so ``_redact_secrets`` can do exact-match replacement.

        These are NEVER logged, serialised, or returned in errors.
        """
        secrets: set[str] = set()
        cur_key = (self._current_config.api_key or "").strip()
        cand_key = (candidate.api_key or "").strip()
        if cur_key:
            secrets.add(cur_key)
        if cand_key:
            secrets.add(cand_key)
        if credential_operations:
            for op in credential_operations:
                if op.value:
                    secrets.add(op.value)
        return frozenset(secrets)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def commit(
        self,
        candidate: AppConfig,
        credential_operations: list[CredentialOperation] | None = None,
    ) -> SettingsSaveResult:
        """Execute the compensating transaction.

        If *credential_operations* is provided those operations are used
        instead of (in addition to) the auto-derived legacy api_key
        operation.  This lets SettingsController bundle provider-key
        mutations into the same atomic transaction.

        Returns a result that is ``.success == True`` **only** when the
        JSON file was atomically replaced, every credential operation
        completed, AND the config_setter succeeded.

        Any failure triggers compensation and attempts to leave all three
        stores (JSON, credentials, in-memory config) unchanged relative
        to the pre-transaction state.
        """
        # Build the set of known secrets for precise redaction
        known_secrets = self._build_known_secrets(candidate, credential_operations)

        # ---- Step 0: capture original JSON file state *before* ANY mutation
        original_snapshot = self._read_original_json()
        if original_snapshot is _JSON_READ_FAILED:
            msg = "无法读取配置文件，拒绝执行保存操作（fail-closed）"
            self._publish("settings_save_failed", [msg])
            return SettingsSaveResult(success=False, errors=[msg])

        # ---- Step 1–2: candidate is provided by caller ---------------
        # ---- Step 3: pre-validate candidate ---------------------------
        validation_errors = self._run_validation(candidate)
        if validation_errors:
            safe_errors = [_redact_secrets(e, known_secrets) for e in validation_errors]
            self._publish("settings_save_failed", safe_errors)
            return SettingsSaveResult(success=False, errors=safe_errors)

        # ---- Step 4: serialise JSON (NEVER include api_key) -----------
        json_str = self._serialise_json(candidate)
        if json_str is None:
            msg = "JSON 序列化失败：无法将候选配置序列化为 JSON"
            self._publish("settings_save_failed", [msg])
            return SettingsSaveResult(success=False, errors=[msg])

        # ---- Step 5–6: write temp JSON, flush, fsync -----------------
        tmp_path: Path | None = None
        try:
            tmp_path = self._write_temp_json(json_str)
        except OSError:
            msg = "临时文件写入失败"
            self._publish("settings_save_failed", [msg])
            return SettingsSaveResult(success=False, errors=[msg])

        # ---- Derive credential operations ------------------------------
        if credential_operations is not None:
            cred_ops = list(credential_operations)
            # Also auto-derive legacy api_key op (if any) so the legacy
            # key is never silently dropped when caller provides only
            # provider-key operations.
            legacy_ops = self._derive_credential_operations(candidate)
            for lop in legacy_ops:
                if not any(
                    c.service == lop.service and c.account == lop.account
                    for c in cred_ops
                ):
                    cred_ops.append(lop)
        else:
            cred_ops = self._derive_credential_operations(candidate)

        # ---- Step 7: snapshot current credential state ----------------
        snapshot_result = self._snapshot_credentials(cred_ops)
        if snapshot_result is None:
            self._cleanup_temp(tmp_path)
            msg = "无法读取系统凭据管理器状态，拒绝执行保存操作（fail-closed）"
            self._publish("settings_save_failed", [msg])
            return SettingsSaveResult(success=False, errors=[msg])
        snapshots = snapshot_result

        # ---- Step 8–9: execute credential operations one-by-one -------
        completed: list[CredentialOperation] = []
        for op in cred_ops:
            if not self._execute_op(op):
                rollback_errs = self._compensate(snapshots, completed)
                self._cleanup_temp(tmp_path)
                msg = f"凭据操作失败: {op.service}/{op.account}"
                self._publish("settings_save_failed", [msg])
                return SettingsSaveResult(
                    success=False,
                    errors=[msg],
                    rollback_errors=rollback_errs,
                )
            completed.append(op)

        # ---- Step 10: atomically replace real JSON --------------------
        try:
            os.replace(str(tmp_path), str(self._config_file_path))
            tmp_path = None  # replaced successfully — do NOT clean up
        except OSError:
            rollback_errs = self._compensate(snapshots, completed)
            self._cleanup_temp(tmp_path)
            msg = "JSON 原子替换失败"
            self._publish("settings_save_failed", [msg])
            return SettingsSaveResult(
                success=False,
                errors=[msg],
                rollback_errors=rollback_errs,
            )

        # ---- Step 12: update in-memory global config ------------------
        config_setter_ok = True
        config_setter_error = ""
        if self._config_setter is not None:
            try:
                self._config_setter(candidate)
            except Exception:
                config_setter_ok = False
                config_setter_error = "内存配置更新失败"

        if not config_setter_ok:
            # ---- Compensate: JSON + credentials + memory, independently
            all_rollback: list[str] = []

            # 1) Restore JSON (atomic: temp + fsync + os.replace)
            json_restore_errs = self._restore_original_json(original_snapshot)
            all_rollback.extend(json_restore_errs)

            # 2) Compensate ALL credentials
            cred_rollback_errs = self._compensate(snapshots, completed)
            all_rollback.extend(cred_rollback_errs)

            # 3) Restore in-memory config via config_setter(current_config)
            if self._config_setter is not None:
                try:
                    self._config_setter(self._current_config)
                except Exception:
                    all_rollback.append("内存配置恢复失败（回滚未完整）")

            self._publish("settings_save_failed", [config_setter_error])
            return SettingsSaveResult(
                success=False,
                errors=[config_setter_error],
                rollback_errors=all_rollback,
            )

        # ---- Step 13: publish success event ---------------------------
        self._publish("settings_saved", SettingsSaveResult(success=True))

        return SettingsSaveResult(success=True)

    # ------------------------------------------------------------------
    # Internal: validation
    # ------------------------------------------------------------------

    def _run_validation(self, candidate: AppConfig) -> list[str]:
        """Run the injected validator (if any), return list of errors."""
        if self._validator is not None:
            return self._validator(candidate)
        return []

    # ------------------------------------------------------------------
    # Internal: JSON serialisation
    # ------------------------------------------------------------------

    @staticmethod
    def _serialise_json(candidate: AppConfig) -> str | None:
        """Dump candidate to indented JSON string.

        Explicitly removes ``api_key`` and any other credential-bearing
        key before serialisation so keys NEVER leak into JSON.
        """
        try:
            data = sanitise_persisted_config(candidate.model_dump())
            data["schema_version"] = SCHEMA_VERSION
            return json.dumps(data, indent=2, ensure_ascii=False)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Internal: temp JSON file (with self-cleanup on failure)
    # ------------------------------------------------------------------

    def _write_temp_json(self, json_str: str) -> Path:
        """Write *json_str* to a temp file in the same directory as the
        real config file, then flush + fsync.

        Returns the ``Path`` of the (now-closed) temp file.
        **Cleans up the temp file on write/flush/fsync failure.**
        Caller is still responsible for cleanup on success-path.
        """
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(self._config_file_path.parent),
            suffix=".tmp",
            delete=False,
        )
        tmp_path = Path(tmp.name)
        try:
            tmp.write(json_str)
            tmp.flush()
            os.fsync(tmp.fileno())
        except Exception:
            # Clean up the temp file we already created
            tmp.close()
            try:
                tmp_path.unlink()
            except OSError:
                pass
            raise
        finally:
            tmp.close()
        return tmp_path

    # ------------------------------------------------------------------
    # Internal: original JSON capture / restore
    # ------------------------------------------------------------------

    def _read_original_json(self) -> _OriginalJsonSnapshot | object:
        """Read the current settings.json bytes before any mutation.

        Uses ``read_bytes()`` directly — does NOT call ``Path.exists()``
        first (which would be a separate syscall and a TOCTOU opportunity).

        Returns:
        - ``_OriginalJsonSnapshot(existed=True, contents=...)`` on success
        - ``_OriginalJsonSnapshot(existed=False, contents=None)`` if absent
        - ``_JSON_READ_FAILED`` sentinel on PermissionError / OSError
          (caller MUST abort the transaction immediately)
        """
        try:
            return _OriginalJsonSnapshot(
                existed=True,
                contents=self._config_file_path.read_bytes(),
            )
        except FileNotFoundError:
            return _OriginalJsonSnapshot(existed=False, contents=None)
        except (PermissionError, OSError):
            return _JSON_READ_FAILED

    def _restore_original_json(
        self, snapshot: _OriginalJsonSnapshot
    ) -> list[str]:
        """Atomically restore settings.json to its pre-transaction state.

        Uses the same temp-file + fsync + os.replace pattern for atomicity
        when the original file existed.  If the file did not exist before
        the transaction, it is deleted.

        Returns a list of error messages (empty on success).  Does NOT
        prevent other compensation steps from executing.
        """
        errors: list[str] = []

        if snapshot.existed and snapshot.contents is not None:
            # ---- Write original bytes to temp, then os.replace ----
            restore_tmp: Path | None = None
            try:
                fd, name = tempfile.mkstemp(
                    suffix=".tmp", dir=str(self._config_file_path.parent)
                )
                restore_tmp = Path(name)
                try:
                    os.write(fd, snapshot.contents)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                os.replace(str(restore_tmp), str(self._config_file_path))
                restore_tmp = None  # replaced successfully
            except OSError:
                if restore_tmp is not None:
                    try:
                        restore_tmp.unlink()
                    except OSError:
                        pass
                errors.append("JSON 原子恢复失败")
        else:
            # File did not exist before — delete it
            try:
                if self._config_file_path.exists():
                    self._config_file_path.unlink()
            except OSError:
                errors.append("JSON 删除失败（恢复至不存在状态）")

        return errors

    # ------------------------------------------------------------------
    # Internal: credential derivation
    # ------------------------------------------------------------------

    def _derive_credential_operations(
        self, candidate: AppConfig
    ) -> list[CredentialOperation]:
        """Build the ordered list of credential mutations implied by the
        difference between the current config and *candidate*.

        Maps the ``api_key`` field to the ``AIRenamer/api_key`` credential.
        """
        ops: list[CredentialOperation] = []

        new_key = (candidate.api_key or "").strip()
        old_key = (self._current_config.api_key or "").strip()

        if new_key != old_key:
            if new_key:
                ops.append(
                    CredentialOperation(
                        service="AIRenamer",
                        account="api_key",
                        action="set",
                        value=new_key,
                    )
                )
            else:
                ops.append(
                    CredentialOperation(
                        service="AIRenamer",
                        account="api_key",
                        action="delete",
                    )
                )

        return ops

    # ------------------------------------------------------------------
    # Internal: credential snapshot / execute / compensate
    # ------------------------------------------------------------------

    def _snapshot_credentials(
        self, operations: list[CredentialOperation]
    ) -> list[CredentialSnapshot] | None:
        """Read current state for every credential that *operations* will
        touch and return an immutable snapshot list.

        If ANY ``credential_store.get()`` raises, returns ``None`` to
        signal that the store is unreliable.  The transaction MUST abort
        immediately — it must never forge ``existed=False`` for a
        credential it could not read.

        The snapshot is stored ONLY in memory (return value).  It MUST
        NOT be logged or serialised.
        """
        snapshots: list[CredentialSnapshot] = []
        for op in operations:
            try:
                old = self._credentials.get(op.service, op.account)
                snapshots.append(
                    CredentialSnapshot(
                        service=op.service,
                        account=op.account,
                        old_value=old,
                        existed=old is not None,
                    )
                )
            except Exception:
                return None
        return snapshots

    def _execute_op(self, op: CredentialOperation) -> bool:
        """Execute a single credential operation.  Returns True on success."""
        try:
            if op.action == "set":
                return self._credentials.set(op.service, op.account, op.value)  # type: ignore[arg-type]
            else:
                return self._credentials.delete(op.service, op.account)
        except Exception:
            return False

    def _compensate(
        self,
        snapshots: list[CredentialSnapshot],
        completed: list[CredentialOperation],
    ) -> list[str]:
        """Roll back every *completed* operation to its snapshot state.

        Returns a (possibly-empty) list of compensation error messages.
        The caller MUST treat a non-empty return as high-severity and
        MUST NOT mark the overall operation as successful.

        Messages are safe — no credential values or raw exception text.
        """
        errors: list[str] = []
        snap_map = {(s.service, s.account): s for s in snapshots}

        for op in reversed(completed):
            snap = snap_map.get((op.service, op.account))
            if snap is None:
                try:
                    self._credentials.delete(op.service, op.account)
                except Exception:
                    errors.append(
                        f"凭据补偿删除失败: {op.service}/{op.account}"
                    )
                continue

            try:
                if snap.existed and snap.old_value is not None:
                    ok = self._credentials.set(
                        op.service, op.account, snap.old_value
                    )
                    if not ok:
                        errors.append(
                            f"凭据补偿恢复失败: {op.service}/{op.account}"
                        )
                else:
                    ok = self._credentials.delete(op.service, op.account)
                    if not ok:
                        errors.append(
                            f"凭据补偿删除失败: {op.service}/{op.account}"
                        )
            except Exception:
                errors.append(
                    f"凭据补偿异常: {op.service}/{op.account}"
                )

        return errors

    # ------------------------------------------------------------------
    # Internal: cleanup
    # ------------------------------------------------------------------

    @staticmethod
    def _cleanup_temp(tmp_path: Path | None) -> None:
        """Delete *tmp_path* if it still exists.  Best-effort — never raises."""
        if tmp_path is None:
            return
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Internal: event publishing
    # ------------------------------------------------------------------

    def _publish(self, name: str, payload: Any) -> None:
        """Publish a named event with a sanitised payload.

        Never raises.  Payload MUST already be sanitised by the caller.
        """
        if self._event_publisher is None:
            return
        try:
            self._event_publisher(name, payload)
        except Exception:
            pass

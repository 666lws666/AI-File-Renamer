"""M5 Watch Config Domain Model — immutable, validatable, serializable.

- Immutable frozen dataclass
- Path overlap detection using real path semantics (not string prefix)
- JSON serialization without Key, Provider creds, file content, or observer
- Persistence store with schema versioning, fail-closed on invalid data
- mode: ReviewFirst, AutoApply only
- status: Active, Paused, Error, ResourcePaused only (no BudgetPaused)
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Optional


# ── Enums ──────────────────────────────────────────────────────────────────────

class WatchMode(Enum):
    """Watch processing mode."""
    REVIEW_FIRST = "review_first"
    AUTO_APPLY = "auto_apply"


class WatchStatus(Enum):
    """Watch lifecycle status. ResourcePaused replaces the retired BudgetPaused."""
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    RESOURCE_PAUSED = "resource_paused"


# ── Errors ─────────────────────────────────────────────────────────────────────

class WatchConfigValidationError(ValueError):
    """Raised when WatchConfig data fails validation."""


class WatchConfigPersistenceError(ValueError):
    """Raised when persistence store encounters invalid or corrupted data."""


# ── Path Helpers ───────────────────────────────────────────────────────────────

def _resolve_path(path_str: str) -> str:
    """Resolve a path string to its canonical absolute form.

    Returns empty string if input is empty.
    """
    if not path_str or not path_str.strip():
        return ""
    return str(Path(path_str).resolve())


def _is_subpath(inner: Path, outer: Path) -> bool:
    """Check if `inner` path is strictly inside `outer` path.

    Uses Path.relative_to which raises ValueError when not a subpath.
    This function isolates the ValueError from our own exception hierarchy.
    """
    try:
        inner.relative_to(outer)
        return True
    except ValueError:
        return False


def _check_path_overlap(source_dir: str, target_dir: str) -> None:
    """Validate that source and target directories do not overlap.

    Uses real path semantics — not string prefix comparison.
    Prevents re-entry loops where watcher monitors its own output.
    """
    if not source_dir or not target_dir:
        return  # No target, no conflict

    try:
        src = Path(source_dir).resolve()
        tgt = Path(target_dir).resolve()
    except (ValueError, OSError) as e:
        raise WatchConfigValidationError(
            f"Cannot resolve path for overlap check: {e}"
        )

    # Source equals target
    if src == tgt:
        raise WatchConfigValidationError(
            "source_dir and target_dir must not be the same directory"
        )

    # Target is inside source (source contains target → re-entry)
    if _is_subpath(tgt, src):
        raise WatchConfigValidationError(
            "target_dir must not be inside source_dir (would cause re-entry loop)"
        )

    # Source is inside target (target contains source)
    if _is_subpath(src, tgt):
        raise WatchConfigValidationError(
            "source_dir must not be inside target_dir (would cause re-entry loop)"
        )


# ── WatchConfig ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class WatchConfig:
    """Immutable configuration for one watched folder.

    Fields:
        id: Unique identifier (non-empty).
        source_dir: Directory to monitor (required, resolved to absolute).
        target_dir: Optional output directory for renamed files.
        template_id: Associated template ID for AI naming.
        recursive: Whether to watch subdirectories.
        mode: ReviewFirst or AutoApply.
        status: Active, Paused, Error, or ResourcePaused.
        created_at: ISO timestamp of creation.
        updated_at: ISO timestamp of last update.
        version: Monotonic version counter.
    """

    id: str
    source_dir: str
    target_dir: str = ""
    template_id: str = ""
    recursive: bool = True
    mode: WatchMode = WatchMode.REVIEW_FIRST
    status: WatchStatus = WatchStatus.ACTIVE
    created_at: str = ""
    updated_at: str = ""
    version: int = 1

    def __post_init__(self) -> None:
        """Validate all fields on construction. Fail-closed — any violation raises."""
        # Validate id
        if not self.id or not self.id.strip():
            raise WatchConfigValidationError("id must not be empty")
        if self.id != self.id.strip():
            raise WatchConfigValidationError("id must not have leading/trailing whitespace")

        # Validate source_dir
        if not self.source_dir or not self.source_dir.strip():
            raise WatchConfigValidationError("source_dir is required and must not be empty")

        # Resolve and normalize source_dir
        resolved_source = _resolve_path(self.source_dir)
        if resolved_source != self.source_dir:
            object.__setattr__(self, "source_dir", resolved_source)

        # Validate source_dir exists
        source_path = Path(self.source_dir)
        if not source_path.exists():
            raise WatchConfigValidationError(
                f"source_dir does not exist: {self.source_dir}"
            )
        if not source_path.is_dir():
            raise WatchConfigValidationError(
                f"source_dir is not a directory: {self.source_dir}"
            )

        # Resolve and validate target_dir
        if self.target_dir and self.target_dir.strip():
            resolved_target = _resolve_path(self.target_dir)
            if resolved_target != self.target_dir:
                object.__setattr__(self, "target_dir", resolved_target)

        # Validate mode
        if not isinstance(self.mode, WatchMode):
            raise WatchConfigValidationError(
                f"mode must be a WatchMode enum value, got {type(self.mode).__name__}: {self.mode}"
            )

        # Validate status
        if not isinstance(self.status, WatchStatus):
            raise WatchConfigValidationError(
                f"status must be a WatchStatus enum value, got {type(self.status).__name__}: {self.status}"
            )

        # Validate recursive
        if not isinstance(self.recursive, bool):
            raise WatchConfigValidationError(
                f"recursive must be a bool, got {type(self.recursive).__name__}"
            )

        # Validate template_id
        if not isinstance(self.template_id, str):
            raise WatchConfigValidationError(
                f"template_id must be a string, got {type(self.template_id).__name__}"
            )

        # Validate version
        if not isinstance(self.version, int) or self.version < 1:
            raise WatchConfigValidationError(
                f"version must be a positive integer, got {self.version}"
            )

        # Path overlap detection (real path semantics)
        _check_path_overlap(self.source_dir, self.target_dir)

    # ── Factory helpers ────────────────────────────────────────────────────────

    def with_status(self, status: WatchStatus) -> "WatchConfig":
        """Return a new WatchConfig with the given status (immutable update)."""
        return replace(self, status=status)

    def with_mode(self, mode: WatchMode) -> "WatchConfig":
        """Return a new WatchConfig with the given mode (immutable update)."""
        return replace(self, mode=mode)

    # ── Serialization ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict.

        NEVER includes: API Key, Provider credentials, file content, observer,
        runtime objects, or any other sensitive data.
        """
        return {
            "id": self.id,
            "source_dir": self.source_dir,
            "target_dir": self.target_dir,
            "template_id": self.template_id,
            "recursive": self.recursive,
            "mode": self.mode.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "version": self.version,
        }

    @staticmethod
    def from_dict(d: dict) -> "WatchConfig":
        """Deserialize from a dict with fail-closed validation.

        Unknown keys, invalid enums, missing required fields all raise.
        """
        # Known allowed keys (exact set — extra keys fail)
        allowed_keys = {
            "id", "source_dir", "target_dir", "template_id",
            "recursive", "mode", "status",
            "created_at", "updated_at", "version",
        }

        extra_keys = set(d.keys()) - allowed_keys
        if extra_keys:
            raise WatchConfigValidationError(
                f"Unknown keys in WatchConfig dict: {sorted(extra_keys)}"
            )

        # Required keys
        if "id" not in d:
            raise WatchConfigValidationError("Missing required key: id")
        if "source_dir" not in d:
            raise WatchConfigValidationError("Missing required key: source_dir")
        if "mode" not in d:
            raise WatchConfigValidationError("Missing required key: mode")
        if "status" not in d:
            raise WatchConfigValidationError("Missing required key: status")

        # Validate mode enum
        try:
            mode = WatchMode(d["mode"])
        except ValueError:
            raise WatchConfigValidationError(
                f"Invalid mode value: {d['mode']!r}. "
                f"Allowed: {[m.value for m in WatchMode]}"
            )

        # Validate status enum
        try:
            status = WatchStatus(d["status"])
        except ValueError:
            raise WatchConfigValidationError(
                f"Invalid status value: {d['status']!r}. "
                f"Allowed: {[s.value for s in WatchStatus]}"
            )

        # Validate recursive is boolean
        recursive = d.get("recursive", True)
        if not isinstance(recursive, bool):
            raise WatchConfigValidationError(
                f"recursive must be a boolean, got {type(recursive).__name__}"
            )

        return WatchConfig(
            id=d["id"],
            source_dir=d["source_dir"],
            target_dir=d.get("target_dir", ""),
            template_id=d.get("template_id", ""),
            recursive=recursive,
            mode=mode,
            status=status,
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            version=d.get("version", 1),
        )


# ── WatchConfigStore ───────────────────────────────────────────────────────────

class WatchConfigStore:
    """Persistent CRUD store for WatchConfig with schema versioning.

    Atomic writes, fail-closed validation on load.
    """

    SCHEMA_VERSION = 1

    def __init__(self, file_path: str | Path, strict: bool = True):
        self._file_path = Path(file_path)
        self._lock = threading.Lock()
        self._configs: dict[str, WatchConfig] = {}
        self._load_errors: list[dict] = []
        self._load(strict=strict)

    # ── Public API ─────────────────────────────────────────────────────────────

    def add(self, config: WatchConfig) -> WatchConfig:
        """Add a config. Raises WatchConfigPersistenceError on duplicate ID."""
        with self._lock:
            if config.id in self._configs:
                raise WatchConfigPersistenceError(
                    f"Duplicate WatchConfig ID: {config.id}"
                )
            candidate = dict(self._configs)
            candidate[config.id] = config
            self._save(candidate)
            self._configs = candidate
            return config

    def get(self, config_id: str) -> WatchConfig:
        """Get a config by ID. Raises WatchConfigPersistenceError if not found."""
        with self._lock:
            if config_id not in self._configs:
                raise WatchConfigPersistenceError(
                    f"WatchConfig not found: {config_id}"
                )
            return self._configs[config_id]

    def list_all(self) -> list[WatchConfig]:
        """Return all configs."""
        with self._lock:
            return list(self._configs.values())

    def update(self, config: WatchConfig) -> WatchConfig:
        """Update an existing config. Raises if not found."""
        with self._lock:
            if config.id not in self._configs:
                raise WatchConfigPersistenceError(
                    f"Cannot update — WatchConfig not found: {config.id}"
                )
            candidate = dict(self._configs)
            candidate[config.id] = config
            self._save(candidate)
            self._configs = candidate
            return config

    def remove(self, config_id: str) -> None:
        """Remove a config. Raises if not found."""
        with self._lock:
            if config_id not in self._configs:
                raise WatchConfigPersistenceError(
                    f"Cannot remove — WatchConfig not found: {config_id}"
                )
            candidate = dict(self._configs)
            del candidate[config_id]
            self._save(candidate)
            self._configs = candidate

    def count(self) -> int:
        """Return number of stored configs."""
        return len(self._configs)

    # ── Persistence ────────────────────────────────────────────────────────────

    def _serialize_all(self, configs: dict[str, WatchConfig] | None = None) -> dict:
        """Serialize a candidate snapshot with schema version wrapper."""
        snapshot = self._configs if configs is None else configs
        return {
            "schema_version": self.SCHEMA_VERSION,
            "configs": [c.to_dict() for c in snapshot.values()],
        }

    def _save(self, configs: dict[str, WatchConfig] | None = None) -> None:
        """Atomically write a candidate snapshot without mutating live state."""
        data = self._serialize_all(configs)
        json_text = json.dumps(data, ensure_ascii=False, indent=2)

        tmp = None
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                suffix=".tmp",
                prefix="watch_configs_",
                dir=str(self._file_path.parent),
            )
            tmp = Path(tmp_path)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json_text)
            os.replace(tmp_path, str(self._file_path))
        except Exception:
            if tmp is not None and tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            raise

    def _load(self, strict: bool = True) -> None:
        """Load configs from JSON file with fail-closed validation.

        In strict mode (default), any invalid entry raises.
        In non-strict mode, invalid entries are collected in _load_errors
        and skipped; valid entries are still loaded.

        Raises WatchConfigPersistenceError on:
        - Corrupted JSON
        - Unknown schema version
        - Non-list/object container (structural errors always raise)
        """
        self._load_errors = []

        if not self._file_path.exists():
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            self._save()  # Write empty store
            return

        # Read raw JSON
        try:
            raw_text = self._file_path.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except json.JSONDecodeError as e:
            raise WatchConfigPersistenceError(
                f"Corrupted watch config file: {e}"
            ) from e

        # Validate top-level structure (always fail-closed)
        if not isinstance(data, dict):
            raise WatchConfigPersistenceError(
                f"Watch config file must contain a JSON object, got {type(data).__name__}"
            )

        # Validate schema version (always fail-closed)
        schema_ver = data.get("schema_version")
        if schema_ver is None:
            raise WatchConfigPersistenceError(
                "Watch config file missing schema_version"
            )
        if not isinstance(schema_ver, int):
            raise WatchConfigPersistenceError(
                f"schema_version must be an integer, got {type(schema_ver).__name__}"
            )
        if schema_ver != self.SCHEMA_VERSION:
            raise WatchConfigPersistenceError(
                f"Unsupported schema version: {schema_ver}. "
                f"Expected: {self.SCHEMA_VERSION}"
            )

        # Validate configs list (always fail-closed)
        configs_raw = data.get("configs")
        if configs_raw is None:
            raise WatchConfigPersistenceError(
                "Watch config file missing 'configs' key"
            )
        if not isinstance(configs_raw, list):
            raise WatchConfigPersistenceError(
                f"'configs' must be a JSON array, got {type(configs_raw).__name__}"
            )

        # Reject unknown top-level keys (always fail-closed)
        allowed_top_keys = {"schema_version", "configs"}
        extra_top_keys = set(data.keys()) - allowed_top_keys
        if extra_top_keys:
            raise WatchConfigPersistenceError(
                f"Unknown top-level keys in watch config file: {sorted(extra_top_keys)}"
            )

        # Validate each config entry
        seen_ids: set[str] = set()
        parsed: dict[str, WatchConfig] = {}

        for i, item in enumerate(configs_raw):
            entry_id = item.get("id", f"<unknown-{i}>") if isinstance(item, dict) else f"<item-{i}>"

            if not isinstance(item, dict):
                msg = f"Config entry {i} must be a JSON object, got {type(item).__name__}"
                if strict:
                    raise WatchConfigPersistenceError(msg)
                else:
                    self._load_errors.append({"index": i, "id": entry_id, "error": msg})
                    continue

            try:
                cfg = WatchConfig.from_dict(item)
            except WatchConfigValidationError as e:
                msg = f"Config entry {i} ({entry_id}) is invalid: {e}"
                if strict:
                    raise WatchConfigPersistenceError(msg) from e
                else:
                    self._load_errors.append({"index": i, "id": entry_id, "error": str(e)})
                    continue

            if cfg.id in seen_ids:
                msg = f"Duplicate WatchConfig ID in store: {cfg.id}"
                if strict:
                    raise WatchConfigPersistenceError(msg)
                else:
                    self._load_errors.append({"index": i, "id": cfg.id, "error": msg})
                    continue

            seen_ids.add(cfg.id)
            parsed[cfg.id] = cfg

        self._configs = parsed

    @property
    def load_errors(self) -> list[dict]:
        """Return errors from the last non-strict load (empty if strict or no errors)."""
        return list(self._load_errors)

"""Application configuration persistence.

Stores settings as JSON in the current OS user's local application-data directory.
API Key is stored in Windows Credential Manager via keyring, never in JSON.
"""

import json
import os
import tempfile
from pathlib import Path
from loguru import logger
from .models.app_config import AppConfig, sanitise_persisted_config
from .utils.credential_manager import (
    delete_credential,
    get_credential,
    get_credential_strict,
    set_credential,
)

SCHEMA_VERSION = 2


class CredentialSaveError(RuntimeError):
    """Raised when the API key cannot be persisted to or removed from the
    system credential manager.

    Callers (e.g. SettingsDialog) must treat this as a hard failure:
    do NOT close the dialog, do NOT report success, and do NOT fall
    back to writing the key as plaintext JSON.
    """

    def __init__(self, detail: str = ""):
        msg = (
            "无法将 API Key 保存到系统凭据管理器。\n"
            "请检查 Windows Credential Manager 服务是否正常运行。"
        )
        if detail:
            msg += f"\n\n详细信息: {detail}"
        super().__init__(msg)


class ConfigSaveError(RuntimeError):
    """Raised when the JSON configuration file cannot be written.

    This is distinct from CredentialSaveError — the credential manager
    succeeded (or was not needed) but the settings.json write failed.
    """

    def __init__(self, detail: str = ""):
        msg = "无法写入配置文件 settings.json。\n请检查磁盘空间和目录权限。"
        if detail:
            msg += f"\n\n详细信息: {detail}"
        super().__init__(msg)


class ConfigLoadError(RuntimeError):
    """Raised when the configuration file cannot be loaded."""

    def __init__(self, detail: str = ""):
        msg = "无法加载配置文件 settings.json。"
        if detail:
            msg += f"\n\n详细信息: {detail}"
        super().__init__(msg)


class UnsupportedConfigVersionError(ConfigLoadError):
    """Raised when the config file has a schema version higher than supported."""

    def __init__(self, file_version: int, current_version: int):
        detail = (
            f"Unsupported schema_version: file={file_version}, current={current_version}. "
            f"配置文件版本 {file_version} 高于当前支持的版本 {current_version}。"
            f"请使用更新版本的序匣。"
        )
        super().__init__(detail)


def default_config_dir() -> Path:
    """Return the per-user config directory, separate from program files."""

    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "Xuxia" / "config"
    return Path.home() / "AppData" / "Local" / "Xuxia" / "config"


CONFIG_DIR = default_config_dir()
CONFIG_FILE = CONFIG_DIR / "settings.json"
TEMPLATES_DIR = CONFIG_DIR / "templates"


def _ensure_dirs() -> None:
    """Create config directories if they don't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(filepath: Path, data: dict) -> None:
    """Atomically write JSON by writing to temp file then renaming.

    Uses os.replace which is atomic on Windows (same volume).
    """
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=filepath.parent,
        suffix=".tmp",
        delete=False,
    )
    try:
        json.dump(data, tmp, indent=2, ensure_ascii=False)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, str(filepath))
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


def load_config(config_file=None, *, load_credentials=True) -> AppConfig:
    """Load application configuration from disk.

    Migrates any legacy api_key from settings.json into Windows
    Credential Manager, then loads the key from the keychain at runtime.

    Returns default config on first run.
    """
    filepath = CONFIG_FILE if config_file is None else Path(config_file)
    if not load_credentials:
        # Read-only startup must precede directory creation, migration and every
        # credential call. Do not log validation exceptions containing input.
        try:
            if not filepath.exists():
                return AppConfig()
            with open(filepath, "r", encoding="utf-8") as file:
                config_data = json.load(file)
            file_version = config_data.get("schema_version", 0)
            if file_version > SCHEMA_VERSION:
                raise UnsupportedConfigVersionError(file_version, SCHEMA_VERSION)
            candidate = dict(config_data)
            candidate.pop("api_key", None)
            return AppConfig(**candidate, api_key="")
        except UnsupportedConfigVersionError:
            raise
        except Exception:
            logger.warning("配置元数据加载失败，使用默认配置")
            return AppConfig()

    if config_file is None:
        _ensure_dirs()
    else:
        filepath.parent.mkdir(parents=True, exist_ok=True)
    try:
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                config_data = json.load(f)

            # --- Step 1: Schema version check (MUST be first, before any mutation) ---
            file_version = config_data.get("schema_version", 0)
            if file_version > SCHEMA_VERSION:
                raise UnsupportedConfigVersionError(file_version, SCHEMA_VERSION)

            # --- Step 2: build one candidate copy before any JSON mutation ---
            candidate = dict(config_data)
            previous_legacy_credential = None
            credential_changed = False
            credential_migration_blocked = False
            legacy_key = candidate.get("api_key", "")
            if legacy_key and isinstance(legacy_key, str) and legacy_key.strip():
                logger.info("检测到 settings.json 中存在 api_key，正在迁移到凭据管理器...")
                previous_legacy_credential = get_credential_strict()
                if set_credential(legacy_key.strip()):
                    candidate.pop("api_key", None)
                    credential_changed = True
                    logger.info("api_key 已准备迁移到 Windows 凭据管理器")
                else:
                    credential_migration_blocked = True
                    logger.warning(
                        "凭据管理器写入失败；保留原配置字节与 schema 版本，等待下次重试"
                    )
            elif "api_key" in candidate:
                candidate.pop("api_key", None)

            if file_version < SCHEMA_VERSION and not credential_migration_blocked:
                candidate["provider_profiles"] = list(
                    candidate.get("provider_profiles") or []
                )
                candidate["active_provider_id"] = str(
                    candidate.get("active_provider_id") or ""
                )
                candidate["schema_version"] = SCHEMA_VERSION

            if candidate != config_data:
                try:
                    _atomic_write_json(filepath, candidate)
                except Exception:
                    if credential_changed:
                        restored = (
                            set_credential(previous_legacy_credential)
                            if previous_legacy_credential
                            else delete_credential()
                        )
                        if not restored:
                            raise CredentialSaveError(
                                "配置迁移写入失败，且旧凭据回滚失败。"
                            )
                    raise
                config_data = candidate
                logger.info(f"配置已迁移到版本 {SCHEMA_VERSION}")

            config = AppConfig(**config_data)
            logger.info(f"配置已加载: {filepath}")
        else:
            config = AppConfig()
    except (CredentialSaveError, ConfigSaveError, UnsupportedConfigVersionError):
        raise
    except Exception as e:
        logger.warning(f"配置加载失败，使用默认配置: {e}")
        config = AppConfig()

    # --- Load API key from credential manager at runtime ---
    try:
        credential_key = get_credential()
        if credential_key:
            config.api_key = credential_key
            logger.debug("API Key 已从凭据管理器加载")
    except Exception as e:
        logger.warning(f"无法从凭据管理器读取 API Key: {e}")

    return config


def save_config(config: AppConfig) -> None:
    """Persist application configuration to disk.

    API Key is saved to / deleted from Windows Credential Manager,
    never written to JSON.

    Raises:
        CredentialSaveError: If the API key cannot be written to the
            credential manager, OR if an existing credential cannot be
            deleted when the user clears the key.
        ConfigSaveError: If the JSON configuration file cannot be
            written (disk full, permission denied, etc.).
    """
    _ensure_dirs()

    # Snapshot the old credential before any mutation.  A JSON failure must
    # compensate the key change so the two stores cannot diverge.
    try:
        old_credential = get_credential_strict()
    except Exception as error:
        raise CredentialSaveError("无法读取旧凭据，拒绝保存。") from error

    # --- Phase 1: persist / delete the API key via credential manager ---
    if config.api_key:
        ok = set_credential(config.api_key)
        if not ok:
            logger.error("凭据保存失败，拒绝写入配置（fail-closed）")
            raise CredentialSaveError()
    else:
        # User cleared the key — delete any existing credential.
        # Deletion failure is also fail-closed: we must not silently
        # leave a stale credential behind while reporting success.
        ok = delete_credential()
        if not ok:
            logger.error("凭据删除失败，拒绝写入配置（fail-closed）")
            raise CredentialSaveError("无法删除旧凭据。")

    # --- Phase 2: persist everything else to JSON ---
    try:
        data = sanitise_persisted_config(config.model_dump())
        data["schema_version"] = SCHEMA_VERSION
        _atomic_write_json(CONFIG_FILE, data)
        logger.info("配置已保存")
    except Exception as error:
        restored = (
            set_credential(old_credential)
            if old_credential
            else delete_credential()
        )
        if not restored:
            logger.critical("配置写入失败且凭据补偿失败")
            raise ConfigSaveError("配置写入失败，且凭据补偿失败。") from error
        if isinstance(error, ConfigSaveError):
            raise
        logger.error(f"配置文件写入失败: {error}")
        raise ConfigSaveError(str(error)) from error


def save_config_metadata(config: AppConfig) -> None:
    """Atomically persist non-secret configuration only.

    ProviderManager uses this function so profile metadata transactions never
    create, overwrite, or delete the legacy ``AIRenamer/api_key`` credential.
    Per-profile credential compensation remains exclusively in ProviderManager.
    """
    _ensure_dirs()
    try:
        data = sanitise_persisted_config(config.model_dump())
        data["schema_version"] = SCHEMA_VERSION
        _atomic_write_json(CONFIG_FILE, data)
        logger.info("Provider 配置元数据已保存")
    except ConfigSaveError:
        raise
    except Exception as error:
        logger.error(f"Provider 配置元数据写入失败: {error}")
        raise ConfigSaveError(str(error)) from error


def get_templates_dir() -> Path:
    """Get the directory where user templates are stored."""
    _ensure_dirs()
    return TEMPLATES_DIR

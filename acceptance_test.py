"""Acceptance test suite for AI File Renamer.

ALL tests run against temporary paths and a mock keyring — the real
Windows Credential Manager and D:/文件AI-AGENT/config/settings.json
are NEVER touched.
"""

import atexit
import shutil
import sys
import os
import json
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# ═════════════════════════════════════════════════════════════════════════════
# ISOLATION: redirect config to temp + mock keyring (never touch real creds)
# ═════════════════════════════════════════════════════════════════════════════

_SAFE_CONFIG_DIR = Path(tempfile.mkdtemp(prefix="acceptance_test_config_"))
_SAFE_CONFIG_FILE = _SAFE_CONFIG_DIR / "settings.json"
_SAFE_TEMPLATES_DIR = _SAFE_CONFIG_DIR / "templates"
_SAFE_KEYRING_STORE = {}

import src.config
src.config.CONFIG_DIR = _SAFE_CONFIG_DIR
src.config.CONFIG_FILE = _SAFE_CONFIG_FILE
src.config.TEMPLATES_DIR = _SAFE_TEMPLATES_DIR


def _safe_get(service, account):
    return _SAFE_KEYRING_STORE.get(f"{service}/{account}")


def _safe_set(service, account, password):
    _SAFE_KEYRING_STORE[f"{service}/{account}"] = password


def _safe_delete(service, account):
    _SAFE_KEYRING_STORE.pop(f"{service}/{account}", None)


_patch_get = patch("keyring.get_password", side_effect=_safe_get)
_patch_set = patch("keyring.set_password", side_effect=_safe_set)
_patch_del = patch("keyring.delete_password", side_effect=_safe_delete)
_patch_get.start()
_patch_set.start()
_patch_del.start()

# Ensure safe config dirs exist
_SAFE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
_SAFE_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)


def _cleanup_temp_dirs():
    """Remove the temporary config directory tree on exit."""
    try:
        if _SAFE_CONFIG_DIR.exists():
            shutil.rmtree(_SAFE_CONFIG_DIR, ignore_errors=True)
    except Exception:
        pass  # Best-effort cleanup


atexit.register(_cleanup_temp_dirs)

PASS = 0
FAIL = 0
ERRORS = []

def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        msg = f"  [FAIL] {name} — {detail}"
        print(msg)
        ERRORS.append(msg)

def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ============================================================================
section("1. IMPORTS — All modules")

def test_imports():
    from src.models import FileItem, RenameRecord, AppConfig
    from src.core.file_scanner import FileScanner
    from src.core.content_extractor import extract
    from src.core.template_model import Template, TemplateField
    from src.core.template_renderer import TemplateRenderer
    from src.core.rename_executor import RenameExecutor
    from src.core.undo_manager import UndoManager
    from src.core.rename_history import RenameHistory
    from src.controllers.watch_controller import WatchController
    from src.core.watch_config import WatchConfig, WatchConfigStore
    from src.providers.presets import create_adapter
    from src.providers.factory import is_legacy_provider
    from src.config import load_config, save_config, get_templates_dir
    from src.utils.constants import SUPPORTED_EXTENSIONS, DEFAULT_SYSTEM_PROMPT, DEFAULT_TEMPLATE
    from src.utils.file_utils import sanitize_filename, resolve_conflict, normalize_path
    from src.utils.logger import setup_logging
    check("Imports.current_public_surface", True)
    check("Imports.legacy_brand_gate", is_legacy_provider("openai") and is_legacy_provider("claude"))

test_imports()

# ============================================================================
section("2. DATA MODELS — CRUD")

def test_models():
    from src.models.file_item import FileItem, FileStatus
    from src.models.rename_record import RenameRecord
    from src.core.template_model import Template, TemplateField
    from src.core.watch_config import WatchConfig, WatchMode, WatchStatus
    from src.models.app_config import AppConfig

    # FileItem
    item = FileItem(
        original_path=Path("D:/test/doc.pdf"),
        file_type="pdf",
        file_size=1024,
    )
    check("FileItem.default_id", len(item.id) > 0)
    check("FileItem.status_default", item.status == FileStatus.PENDING)
    check("FileItem.original_name", item.original_name == "doc.pdf")
    check("FileItem.original_ext", item.original_ext == ".pdf")
    check("FileItem.parent_dir", str(item.parent_dir) == str(Path("D:/test")))

    # FileStatus enum
    check("FileStatus.PENDING", FileStatus.PENDING == "pending")
    check("FileStatus.SUGGESTED", FileStatus.SUGGESTED == "suggested")
    check("FileStatus.APPLIED", FileStatus.APPLIED == "applied")
    check("FileStatus.FAILED", FileStatus.FAILED == "failed")

    # RenameRecord
    record = RenameRecord(
        batch_id="batch-001",
        old_path=Path("D:/test/old.txt"),
        new_path=Path("D:/test/new.txt"),
        file_size=100,
    )
    json_line = record.to_json_line()
    parsed = RenameRecord.from_json_line(json_line)
    check("RenameRecord.to_json", len(json_line) > 0)
    check("RenameRecord.from_json", parsed.old_path == record.old_path)
    check("RenameRecord.from_json.new_path", parsed.new_path == record.new_path)
    check("RenameRecord.from_json.batch_id", parsed.batch_id == "batch-001")

    # Current immutable template and watch models
    tmpl = Template(name="test", pattern="{dcDate}_{dcTitle}")
    check("Template.name", tmpl.name == "test")
    check("Template.pattern", tmpl.pattern == "{dcDate}_{dcTitle}")
    check("Template.fields", {"dcDate", "dcTitle"} <= {field.dc_name for field in tmpl.fields})
    with tempfile.TemporaryDirectory(prefix="acceptance-watch-model-") as directory:
        watch = WatchConfig(id="model-watch", source_dir=directory, mode=WatchMode.REVIEW_FIRST)
        check("WatchConfig.source", watch.source_dir == str(Path(directory).resolve()))
        check("WatchConfig.mode", watch.mode == WatchMode.REVIEW_FIRST)
        check("WatchConfig.active", watch.status == WatchStatus.ACTIVE)

    # AppConfig
    config = AppConfig()
    check("AppConfig.provider", config.provider == "deepseek")
    check("AppConfig.model", config.model == "deepseek-flash")
    check("AppConfig.base_url", "api.deepseek.com" in config.base_url)
    check("AppConfig.language", config.language == "zh_CN")
    check("AppConfig.max_file_size_mb", config.max_file_size_mb == 50)

    # AppConfig with API key
    config2 = AppConfig(api_key="sk-test12345")
    check("AppConfig.api_key_set", config2.api_key == "sk-test12345", config2.api_key)

test_models()

# ============================================================================
section("3. CONFIG — Persistence")

def test_config():
    from src.config import load_config, save_config, get_templates_dir, CONFIG_DIR
    from src.models.app_config import AppConfig

    # Backup existing config
    config_file = CONFIG_DIR / "settings.json"
    backup = None
    if config_file.exists():
        backup = config_file.read_text(encoding="utf-8")

    try:
        # Test save + load
        test_config = AppConfig(
            provider="openai",
            api_key="sk-save-test",
            max_file_size_mb=100,
        )
        save_config(test_config)
        check("Config.save", config_file.exists())

        loaded = load_config()
        check("Config.load.provider", loaded.provider == "openai", f"got: {loaded.provider}")
        check("Config.load.max_size", loaded.max_file_size_mb == 100, f"got: {loaded.max_file_size_mb}")

        # Templates dir
        tmpl_dir = get_templates_dir()
        check("Config.templates_dir", tmpl_dir.exists())

    finally:
        # Clean up test config
        if config_file.exists():
            config_file.unlink()
        if backup:
            config_file.write_text(backup, encoding="utf-8")

test_config()

# ============================================================================
section("4. FILE SCANNER")

def test_scanner():
    from src.core.file_scanner import FileScanner
    from src.utils.constants import SUPPORTED_EXTENSIONS

    scanner = FileScanner(max_file_size_mb=50)

    # Scan project src/ directory for .py files — the scanner only targets
    # supported document/media extensions, so .py files won't be found.
    # Verify by scanning test_files which has known files
    items = scanner.scan_directory(PROJECT_ROOT / "src")
    check("Scanner.src_dir_accessible", isinstance(items, list), f"type: {type(items)}")

    # Scan test_files
    test_dir = PROJECT_ROOT / "test_files"
    items = scanner.scan_directory(test_dir)
    check("Scanner.test_files_count", len(items) >= 2, f"found {len(items)}")

    # Check FileItem properties on scanned items
    for item in items:
        check(f"Scanner.item.{item.original_name}.exists", item.original_path.exists())
        check(f"Scanner.item.{item.original_name}.size>0", item.file_size > 0)
        check(f"Scanner.item.{item.original_name}.type_set", len(item.file_type) > 0)

    # Scan specific files
    file_list = [str(test_dir / "季度销售报告_2025Q1.txt")]
    items = scanner.scan_files(file_list)
    check("Scanner.scan_files_count", len(items) == 1, f"found {len(items)}")
    check("Scanner.scan_files_name", items[0].original_name == "季度销售报告_2025Q1.txt")

    # Non-existent files
    items = scanner.scan_files(["D:/nonexistent/file.pdf"])
    check("Scanner.nonexistent", len(items) == 0)

    # Unsupported extension
    if str(PROJECT_ROOT).count(":") > 0:  # Windows
        items = scanner.scan_files([str(PROJECT_ROOT / ".gitignore")])
        check("Scanner.unsupported_ext", len(items) == 0)

test_scanner()

# ============================================================================
section("5. CONTENT EXTRACTOR")

def test_extractor():
    from src.core.content_extractor import extract
    from src.models.file_item import FileItem, FileStatus
    from src.core.file_scanner import FileScanner

    scanner = FileScanner()
    test_dir = PROJECT_ROOT / "test_files"
    items = scanner.scan_directory(test_dir)

    for item in items:
        extract(item, max_chars=4000)
        check(f"Extract.{item.original_name}.status", item.status == FileStatus.EXTRACTED,
              f"got: {item.status.value}, error: {item.error_message}")
        check(f"Extract.{item.original_name}.text_length", len(item.extracted_text) > 10,
              f"got {len(item.extracted_text)} chars")
        check(f"Extract.{item.original_name}.metadata", isinstance(item.metadata, dict))

    # Test specific content detection
    for item in items:
        if "销售报告" in item.original_name:
            check("Extract.sales_report.content",
                  "销售额" in item.extracted_text or item.extracted_text != "",
                  f"text: {item.extracted_text[:100]}")

test_extractor()

# ============================================================================
section("6. FORMAL TEMPLATE RENDERER")

def test_template_engine():
    from dataclasses import replace
    from src.core.template_model import Template, DateFormat, Separator
    from src.core.template_renderer import TemplateRenderer, RenderStatus
    from src.core.naming_fields import NamingFields

    template = Template(name="Acceptance", pattern="{dcDate}_{dcTitle}")
    fields = NamingFields(dcDate="2025-07-26", dcTitle="Quarterly report", dcSubject="Sales")
    result = TemplateRenderer.render(template, fields, ".PDF")
    check("Template.render.exact_date_extension", result.rendered_name == "2025-07-26_Quarterly_report.pdf", repr(result))
    check("Template.render.ready", result.status == RenderStatus.READY and result.can_apply)
    hyphen = TemplateRenderer.render(replace(template, separator=Separator.HYPHEN), fields, "txt")
    check("Template.render.separator", hyphen.rendered_name == "2025-07-26-Quarterly-report.txt", repr(hyphen))
    compact = TemplateRenderer.render(replace(template, date_format=DateFormat.YYYYMMDD),
                                      replace(fields, dcDate="20250726"), ".pdf")
    check("Template.render.compact_date", compact.rendered_name == "20250726_Quarterly_report.pdf")
    for absent in ("dcDate", "dcTitle"):
        missing = TemplateRenderer.render(template, replace(fields, **{absent: None}), ".pdf")
        check(f"Template.missing.{absent}", missing.status == RenderStatus.NEEDS_REGENERATION
              and not missing.can_apply and missing.missing_fields == (absent,), repr(missing))
    missing_date = TemplateRenderer.render(template, replace(fields, dcDate=None), ".pdf")
    check("Template.missing_date_not_fabricated", missing_date.rendered_name == "Quarterly_report.pdf")
    invalid = TemplateRenderer.render(template, replace(fields, dcDate="unknown"), ".pdf")
    check("Template.unknown_date_rejected", invalid.status == RenderStatus.INVALID and not invalid.can_apply)
    sanitized = TemplateRenderer.render(template, replace(fields, dcTitle="test<file>name"), ".pdf")
    check("Template.sanitize", sanitized.rendered_name == "2025-07-26_testfilename.pdf")

test_template_engine()

# ============================================================================
section("7. RENAME HISTORY")

def test_history():
    from src.core.rename_history import RenameHistory
    from src.models.rename_record import RenameRecord

    # Use a test file
    test_file = _SAFE_CONFIG_DIR / "_test_history.jsonl"
    if test_file.exists():
        test_file.unlink()

    history = RenameHistory(test_file)

    # Empty state
    check("History.empty", len(history.get_all()) == 0)
    check("History.no_last_batch", history.get_last_batch_id() is None)

    # Write records
    record1 = RenameRecord(
        batch_id="batch-test-001",
        old_path=Path("D:/test/a.txt"),
        new_path=Path("D:/test/a_new.txt"),
        file_size=100,
    )
    record2 = RenameRecord(
        batch_id="batch-test-001",
        old_path=Path("D:/test/b.txt"),
        new_path=Path("D:/test/b_new.txt"),
        file_size=200,
    )
    history.record(record1)
    history.record(record2)

    # Read back
    all_records = history.get_all()
    check("History.write_count", len(all_records) == 2, f"got: {len(all_records)}")
    check("History.last_batch", history.get_last_batch_id() == "batch-test-001")

    # Get by batch
    batch = history.get_by_batch("batch-test-001")
    check("History.get_by_batch", len(batch) == 2, f"got: {len(batch)}")

    # JSONL integrity
    check("History.jsonl_record1", all_records[0].old_path.name == "a.txt")
    check("History.jsonl_record2", all_records[1].new_path.name == "b_new.txt")

    # Clean up
    if test_file.exists():
        test_file.unlink()

    # Thread safety basic check (use same RenameHistory instance for shared lock)
    import threading
    errors_lock = []
    shared_history = RenameHistory(test_file)

    def writer():
        try:
            for i in range(10):
                shared_history.record(RenameRecord(
                    batch_id=f"thread-{threading.get_ident()}",
                    old_path=Path(f"D:/test/t{threading.get_ident()}_{i}.txt"),
                    new_path=Path(f"D:/test/t{threading.get_ident()}_{i}_new.txt"),
                ))
        except Exception as e:
            errors_lock.append(str(e))

    t1 = threading.Thread(target=writer)
    t2 = threading.Thread(target=writer)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    check("History.thread_safety", len(errors_lock) == 0, str(errors_lock))
    if test_file.exists():
        records = shared_history.get_all()
        check("History.thread_records", len(records) == 20, f"got: {len(records)}")
        test_file.unlink()

test_history()

# ============================================================================
section("8. NATIVE APPLY / UNDO — Content, Association & Conflicts")

def test_rename_engine():
    from src.core.rename_executor import RenameExecutor
    from src.core.preflight_service import PreflightService
    from src.core.rename_plan import RenamePlan, SourceFingerprint
    from src.core.rename_history import RenameHistory
    from src.core.undo_manager import UndoManager
    from src.utils.file_utils import sanitize_filename, resolve_conflict

    check("Sanitize.illegal_chars", sanitize_filename("test<file>.txt") == "test_file_.txt")
    check("Sanitize.leading_dot", sanitize_filename(".hidden") == "hidden")
    check("Sanitize.control_chars", "\x00" not in sanitize_filename("test\x00.txt"))
    with tempfile.TemporaryDirectory(prefix="acceptance-native-") as directory:
        root = Path(directory)
        source = root / "original.txt"
        payload = b"SYNTHETIC ORIGINAL CONTENT"
        source.write_bytes(payload)
        collision = root / "renamed.txt"
        collision.write_bytes(b"DO NOT OVERWRITE")
        history_path = root / "history.jsonl"
        history = RenameHistory(history_path)
        executor = RenameExecutor(PreflightService([str(root)]), history)
        stamp = source.stat()
        plan = RenamePlan("native-task", str(source), SourceFingerprint(stamp.st_size, stamp.st_mtime_ns),
                          "renamed.txt", str(root), ".txt")
        check("Conflict.existing_file", resolve_conflict(root, "renamed.txt") == "renamed_1.txt")
        check("Conflict.unique_name", resolve_conflict(root, "unique.txt") == "unique.txt")
        results = executor.execute([plan], "native-batch")
        applied = results[0]
        check("Apply.success", applied.success, str(applied))
        check("Apply.association", applied.task_id == "native-task" and applied.batch_id == "native-batch")
        check("Apply.content", Path(applied.new_path).read_bytes() == payload)
        check("Apply.conflict_no_overwrite", collision.read_bytes() == b"DO NOT OVERWRITE"
              and Path(applied.new_path).name == "renamed_1.txt" and not source.exists())
        record = history.get_by_batch("native-batch")[0]
        check("History.apply_association", record.task_id == "native-task" and record.batch_id == "native-batch"
              and str(record.new_path) == applied.new_path and bool(record.move_evidence))
        undo = UndoManager(str(history_path), executor=executor).undo_last_batch()[0]
        check("Undo.success_association", undo.success and undo.task_id == "native-task" and undo.batch_id == "native-batch", str(undo))
        check("Undo.restored_original_bytes", source.read_bytes() == payload and not Path(applied.new_path).exists())
        check("Undo.history_mark", history.get_by_batch("native-batch")[0].undone)
        stamp = source.stat()
        wrong = RenamePlan("wrong-extension", str(source), SourceFingerprint(stamp.st_size, stamp.st_mtime_ns),
                           "incorrect.pdf", str(root), ".txt")
        rejected = executor.execute([wrong], "rejected-batch")[0]
        check("Apply.wrong_extension_rejected", not rejected.success and source.read_bytes() == payload
              and not (root / "incorrect.pdf").exists() and not history.get_by_batch("rejected-batch"))
        check("Apply.empty", executor.execute([], "empty-batch") == [])

test_rename_engine()

# ============================================================================
section("9. CURRENT PROVIDERS — Offline Wire Contracts")

def test_providers():
    from dataclasses import replace
    from src.core.provider_presets import FIRST_PHASE_PROVIDER_IDS, create_profile_from_preset
    from src.core.provider_protocol import ProviderRequest
    from src.providers.presets import create_adapter
    from src.providers.openai_compatible import ProviderAdapterConfigurationError, TransportResponse

    class FakeTransport:
        """External boundary only: deterministic wire response, no model quality claim."""
        def __init__(self):
            self.calls = []
        def send(self, **request):
            self.calls.append(request)
            return TransportResponse(status_code=200, headers={}, latency_ms=1.0, json_body={
                "choices": [{"message": {"content": '{"dcTitle": "Synthetic report"}'}, "finish_reason": "stop"}],
                "model": "synthetic-model",
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            })

    request = ProviderRequest(request_id="acceptance-request", task_id="acceptance-task",
                              extracted_text="Synthetic content", metadata={}, visual_payloads=(),
                              requested_schema={"type": "object", "properties": {"dcTitle": {"type": "string"}},
                                                "required": ["dcTitle"], "additionalProperties": False},
                              locale="en-US", correlation_id="acceptance-correlation")
    for provider_id in FIRST_PHASE_PROVIDER_IDS:
        options = {"profile_id": f"acceptance-{provider_id}"}
        if provider_id == "qwen":
            options["region"] = "virginia"
        if provider_id in {"zhipu", "kimi"}:
            options["model"] = f"{provider_id}-synthetic-model"
        profile = create_profile_from_preset(provider_id, **options)
        transport = FakeTransport()
        adapter = create_adapter(profile=profile, credential="synthetic-only-key", transport=transport)
        try:
            adapter.invoke(request)
            check(f"Provider.{provider_id}.unverified_rejected", False)
        except ProviderAdapterConfigurationError:
            check(f"Provider.{provider_id}.unverified_rejected", transport.calls == [])
        verified = create_adapter(profile=replace(profile, needs_connection_verification=False),
                                  credential="synthetic-only-key", transport=transport)
        outcome = verified.invoke(request)
        check(f"Provider.{provider_id}.fake_wire_contract", outcome.success
              and outcome.value.fields == {"dcTitle": "Synthetic report"}
              and outcome.value.provider_profile_id == profile.id
              and outcome.value.correlation_id == "acceptance-correlation"
              and len(transport.calls) == 1, str(outcome))
    for provider_id in ("unknown", "openai", "claude"):
        try:
            create_adapter(profile=replace(profile, provider_id=provider_id),
                           credential="synthetic-only-key", transport=FakeTransport())
            check(f"Provider.{provider_id}.rejected", False)
        except ProviderAdapterConfigurationError:
            check(f"Provider.{provider_id}.rejected", True)
    try:
        create_adapter(profile=profile, credential="", transport=FakeTransport())
        check("Provider.missing_credential_rejected", False)
    except ProviderAdapterConfigurationError:
        check("Provider.missing_credential_rejected", True)

test_providers()

# ============================================================================
section("10. FILE UTILS — Edge Cases")

def test_file_utils():
    from src.utils.file_utils import sanitize_filename, resolve_conflict, normalize_path, is_safe_path

    # Edge cases
    check("Sanitize.empty", sanitize_filename("") != "")
    check("Sanitize.whitespace", sanitize_filename("  test  ") == "test")
    check("Sanitize.dots_only", sanitize_filename("...") != "...")

    # Long filename
    long_name = "a" * 250 + ".txt"
    result = sanitize_filename(long_name)
    check("Sanitize.long_name", len(result) <= 200, f"len={len(result)}")

    # normalize_path
    p = normalize_path("D:/文件AI-AGENT/src")
    check("Normalize.absolute", p.is_absolute())

    # is_safe_path
    base = Path(r"D:\文件AI-AGENT")
    check("SafePath.inside", is_safe_path(base / "src" / "main.py", base))
    check("SafePath.outside", not is_safe_path(Path("C:/Windows"), base))

test_file_utils()

# ============================================================================
section("11. CONSTANTS — Integrity")

def test_constants():
    from src.utils.constants import (
        SUPPORTED_EXTENSIONS, EXT_TO_MIME,
        DOCUMENT_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS,
        TEXT_EXTRACTABLE_EXTENSIONS, ILLEGAL_CHARS,
        DEFAULT_SYSTEM_PROMPT, DEFAULT_TEMPLATE,
    )

    # Extension sets are consistent
    check("Constants.all_supported",
          SUPPORTED_EXTENSIONS == DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS | VIDEO_EXTENSIONS)
    check("Constants.doc_count", len(DOCUMENT_EXTENSIONS) > 0)
    check("Constants.img_count", len(IMAGE_EXTENSIONS) > 0)

    # MIME map covers all extensions
    for ext in SUPPORTED_EXTENSIONS:
        check(f"Constants.mime.{ext}", ext in EXT_TO_MIME, f"missing MIME for {ext}")

    # Default template
    check("Constants.template_valid", "{" in DEFAULT_TEMPLATE)
    check("Constants.illlegal_chars", "<" in ILLEGAL_CHARS and ">" in ILLEGAL_CHARS)

test_constants()

# ============================================================================
section("12. FORMAL TEMPLATE ORGANIZATION")

def test_organization():
    from src.core.template_model import Template, OrgMode
    from src.core.naming_fields import NamingFields
    from src.core.template_renderer import TemplateRenderer, RenderStatus

    fields = NamingFields(dcDate="2025-07-26", dcTitle="Report", dcSubject="Sales",
                          dcType="report", extProject="Atlas")
    expected = {OrgMode.FLAT: "2025-07-26_Report.txt",
                OrgMode.SUBJECT_TREE: "Sales/2025-07-26_Report.txt",
                OrgMode.TYPE_TREE: "report/2025-07-26_Report.txt",
                OrgMode.PROJECT_TREE: "Atlas/2025-07-26_Report.txt"}
    for mode, name in expected.items():
        result = TemplateRenderer.render(Template(name="Organization", org_mode=mode), fields, ".txt")
        check(f"Organization.{mode.value}", result.status == RenderStatus.READY
              and result.rendered_name == name, repr(result))

test_organization()

# ============================================================================
section("13. WATCH CONFIG / CONTROLLER LIFECYCLE")

def test_watcher():
    from dataclasses import replace
    from src.controllers.watch_controller import WatchController, ObserverFactory, FakeClock, FakeScheduler
    from src.core.watch_config import WatchConfig, WatchConfigStore, WatchMode, WatchStatus

    with tempfile.TemporaryDirectory(prefix="acceptance-watch-") as directory:
        root = Path(directory)
        source = root / "source"
        source.mkdir()
        store_path = root / "watches.json"
        store = WatchConfigStore(store_path)
        factory = ObserverFactory(use_mock=True)
        clock = FakeClock()
        scheduler = FakeScheduler(clock)
        controller = WatchController(store, observer_factory=factory, clock=clock, scheduler=scheduler)
        config = WatchConfig(id="acceptance-watch", source_dir=str(source))
        try:
            controller.add_watch(config)
            first = factory.created_observers[-1]
            check("Watch.start", controller.is_watching(config.id) and first.running
                  and controller.get_status(config.id) == WatchStatus.ACTIVE)
            check("Watch.create_read_persistence", WatchConfigStore(store_path).get(config.id) == store.get(config.id))
            controller.pause_watch(config.id)
            check("Watch.pause", not first.running and controller.get_status(config.id) == WatchStatus.PAUSED)
            edited = replace(controller.get_config(config.id), recursive=False, mode=WatchMode.AUTO_APPLY)
            controller.update_watch(edited)
            check("Watch.update_persistence", WatchConfigStore(store_path).get(config.id) == edited)
            controller.resume_watch(config.id)
            resumed = factory.created_observers[-1]
            check("Watch.resume", resumed.running and controller.get_status(config.id) == WatchStatus.ACTIVE)
            controller.stop_all()
            check("Watch.stop", not resumed.running and scheduler.workers_idle)
            controller.remove_watch(config.id)
            check("Watch.delete_persistence", not controller.is_watching(config.id)
                  and WatchConfigStore(store_path).list_all() == [] and source.is_dir())
        finally:
            controller.stop_all()

test_watcher()

# ============================================================================
section("14. GUI — Official QML Runtime (isolated)")

def test_gui():
    from src import main, main_qml

    report = _SAFE_CONFIG_DIR / "qml-smoke.json"
    data_dir = _SAFE_CONFIG_DIR / "qml-smoke-data"
    exit_code = main_qml.run_smoke_test(data_dir=data_dir, report_path=report)
    payload = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}
    media = payload.get("media", {})

    check("GUI.official_entry", main.main is main_qml.main)
    check(
        "GUI.retired_entry_removed",
        not (PROJECT_ROOT / "src" / "main_legacy.py").exists(),
    )
    check("GUI.QML.report_exists", report.is_file())
    check("GUI.QML.smoke_exit", exit_code == 0, f"exit={exit_code}")
    check("GUI.QML.status", payload.get("status") == "ok", str(payload))
    check("GUI.QML.brand", payload.get("brand") == "Xuxia", str(payload))
    check("GUI.QML.version", payload.get("version") == "1.0.0", str(payload))
    check(
        "GUI.QML.warning_count",
        payload.get("qml_warning_count") == 0,
        str(payload),
    )
    check(
        "GUI.QML.ephemeral_credentials",
        payload.get("credential_backend") == "ephemeral",
    )
    check("GUI.media.image", media.get("image_preprocess") == "ok", str(media))
    check("GUI.media.pdf", media.get("pdf_render") == "ok", str(media))
    check("GUI.media.video", media.get("video_keyframes") == "ok", str(media))
    check(
        "GUI.media.diagnostics",
        media.get("diagnostics_export") == "ok",
        str(media),
    )
    check(
        "GUI.media.credential_import",
        media.get("windows_credential_backend") == "import-ok",
        str(media),
    )
    check("GUI.isolated_data_dir", data_dir.is_relative_to(_SAFE_CONFIG_DIR))
    check("GUI.user_guide", (PROJECT_ROOT / "序匣用户手册.html").is_file())
    check(
        "GUI.windows_rc",
        (PROJECT_ROOT / "dist" / "Xuxia" / "Xuxia.exe").is_file(),
    )

test_gui()

# ============================================================================
section("15. SYNTHETIC FORMAL PIPELINE — Not Model Quality")

def test_e2e():
    """Synthetic fields validate plumbing, not real AI semantics."""
    from src.core.file_scanner import FileScanner
    from src.core.content_extractor import extract
    from src.core.naming_fields import NamingFields
    from src.core.template_model import Template
    from src.core.template_renderer import TemplateRenderer, RenderStatus
    from src.models.file_item import FileStatus
    from src.core.rename_history import RenameHistory
    from src.core.rename_executor import RenameExecutor
    from src.core.rename_plan import RenamePlan, SourceFingerprint
    from src.core.preflight_service import PreflightService
    from src.core.undo_manager import UndoManager

    with tempfile.TemporaryDirectory(prefix="acceptance-e2e-") as directory:
        root = Path(directory)
        source = root / "synthetic.txt"
        payload = b"Synthetic quarterly revenue report. No private inputs."
        source.write_bytes(payload)
        items = FileScanner().scan_files([str(source)])
        check("E2E.scan", len(items) == 1 and items[0].original_path == source)
        item = items[0]
        extract(item)
        check("E2E.extract", item.status == FileStatus.EXTRACTED and item.extracted_text.strip() == payload.decode())
        fields = NamingFields(dcDate="2025-07-26", dcTitle="Synthetic report")
        rendered = TemplateRenderer.render(Template(name="Synthetic"), fields, item.original_ext)
        check("E2E.formal_render", rendered.status == RenderStatus.READY
              and rendered.rendered_name == "2025-07-26_Synthetic_report.txt")
        history_path = root / "history.jsonl"
        history = RenameHistory(history_path)
        executor = RenameExecutor(PreflightService([str(root)]), history)
        stamp = source.stat()
        plan = RenamePlan(item.id, str(source), SourceFingerprint(stamp.st_size, stamp.st_mtime_ns),
                          rendered.rendered_name, str(root), item.original_ext)
        applied = executor.execute([plan], "synthetic-e2e-batch")[0]
        check("E2E.apply", applied.success and Path(applied.new_path).read_bytes() == payload, str(applied))
        record = history.get_all()[0]
        check("E2E.history_links", record.task_id == item.id and record.batch_id == "synthetic-e2e-batch"
              and record.old_path == source and str(record.new_path) == applied.new_path)
        restored = UndoManager(str(history_path), executor=executor).undo_last_batch()[0]
        check("E2E.undo_content_links", restored.success and restored.task_id == item.id
              and restored.batch_id == "synthetic-e2e-batch" and source.read_bytes() == payload
              and history.get_all()[0].undone, str(restored))

test_e2e()

# ============================================================================
section("16. MIDDLEWARE LAYER — Integration Wiring")

def test_integration():
    """Public current surface shares the same formal renderer and persistence."""
    from src.models import FileItem, RenameRecord, AppConfig
    from src.core.template_model import Template
    from src.core.naming_fields import NamingFields
    from src.core.template_renderer import TemplateRenderer, RenderStatus
    from src.providers.factory import is_legacy_provider
    from src.core.rename_history import RenameHistory

    result = TemplateRenderer.render(Template(name="Integration"),
                                     NamingFields(dcDate="2025-01-01", dcTitle="Test"), ".txt")
    check("Integration.formal_render_exact", result.status == RenderStatus.READY
          and result.rendered_name == "2025-01-01_Test.txt")
    check("Integration.history_persistence_only", not hasattr(RenameHistory, "undo_batch"))
    check("Integration.legacy_gate_preserved", is_legacy_provider(" CLAUDE "))

test_integration()

# ============================================================================
# SUMMARY
# ============================================================================
section("RESULTS")

total = PASS + FAIL
print(f"\n  Passed: {PASS}/{total}")
print(f"  Failed: {FAIL}/{total}")
print(f"  Rate:   {PASS/total*100:.1f}%")

if ERRORS:
    print(f"\n  Failures:")
    for e in ERRORS:
        print(f"    {e}")

if FAIL == 0:
    print("\n  *** ALL TESTS PASSED! ***")
else:
    print(f"\n  WARNING: {FAIL} test(s) failed — see above.")

sys.exit(0 if FAIL == 0 else 1)

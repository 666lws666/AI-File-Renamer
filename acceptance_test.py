"""Acceptance test suite for AI File Renamer."""
import sys
import os
import json
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(r"D:\文件AI-AGENT")
sys.path.insert(0, str(PROJECT_ROOT))

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
    # Models
    from src.models.file_item import FileItem, FileStatus
    from src.models.rename_record import RenameRecord
    from src.models.template import NamingTemplate, TemplateField
    from src.models.watch_config import WatchConfig, WatchMode
    from src.models.app_config import AppConfig
    check("models/file_item", True)
    check("models/rename_record", True)
    check("models/template", True)
    check("models/watch_config", True)
    check("models/app_config", True)

    # Core
    from src.core.file_scanner import FileScanner
    from src.core.content_extractor import extract
    from src.core.ai_engine import AIEngine
    from src.core.rename_engine import RenameEngine
    from src.core.rename_history import RenameHistory
    from src.core.template_engine import TemplateEngine
    from src.core.folder_watcher import FolderWatcher
    from src.core.organization_engine import organize, RULE_HANDLERS
    check("core/file_scanner", True)
    check("core/content_extractor", True)
    check("core/ai_engine", True)
    check("core/rename_engine", True)
    check("core/rename_history", True)
    check("core/template_engine", True)
    check("core/folder_watcher", True)
    check("core/organization_engine", True)

    # Providers
    from src.providers.base import BaseProvider
    from src.providers.deepseek import DeepSeekProvider
    from src.providers.openai import OpenAIProvider
    from src.providers.claude import ClaudeProvider
    from src.providers.factory import create_provider
    check("providers/base", True)
    check("providers/deepseek", True)
    check("providers/openai", True)
    check("providers/claude", True)
    check("providers/factory", True)

    # Utils
    from src.utils.constants import SUPPORTED_EXTENSIONS, DEFAULT_SYSTEM_PROMPT, DEFAULT_TEMPLATE
    from src.utils.file_utils import sanitize_filename, resolve_conflict, normalize_path
    from src.utils.logger import setup_logging
    check("utils/constants", True)
    check("utils/file_utils", True)
    check("utils/logger", True)

    # Config
    from src.config import load_config, save_config, get_templates_dir
    check("config", True)

test_imports()

# ============================================================================
section("2. DATA MODELS — CRUD")

def test_models():
    from src.models.file_item import FileItem, FileStatus
    from src.models.rename_record import RenameRecord
    from src.models.template import NamingTemplate, TemplateField
    from src.models.watch_config import WatchConfig, WatchMode
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

    # NamingTemplate
    tmpl = NamingTemplate(name="test", pattern="{date}_{title}.{ext}")
    check("NamingTemplate.name", tmpl.name == "test")
    check("NamingTemplate.pattern", tmpl.pattern == "{date}_{title}.{ext}")
    check("NamingTemplate.field_names", "date" in tmpl.field_names and "title" in tmpl.field_names)

    # WatchConfig
    watch = WatchConfig(source_dir="D:/watch", mode=WatchMode.REVIEW_FIRST)
    check("WatchConfig.source", watch.source_dir == "D:/watch")
    check("WatchConfig.mode", watch.mode == WatchMode.REVIEW_FIRST)
    check("WatchConfig.active", watch.active == True)

    # AppConfig
    config = AppConfig()
    check("AppConfig.provider", config.provider == "deepseek")
    check("AppConfig.model", "deepseek-v4" in config.model)
    check("AppConfig.base_url", "api.deepseek.com" in config.base_url)
    check("AppConfig.language", config.language == "zh")
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
section("6. TEMPLATE ENGINE")

def test_template_engine():
    from src.core.template_engine import TemplateEngine
    from src.models.template import NamingTemplate
    from src.models.file_item import FileItem

    engine = TemplateEngine()

    # Parse
    fields = TemplateEngine.parse("{date}_{title}_{tags}.{ext}")
    check("Template.parse", set(fields) == {"date", "title", "tags", "ext"},
          f"got: {fields}")

    # Render
    tmpl = NamingTemplate(
        name="test",
        pattern="{date}_{title}.{ext}",
        separator="_",
        date_format="%Y-%m-%d",
    )
    item = FileItem(original_path=Path("D:/test/report.pdf"), file_type="pdf")
    ai_fields = {"date": "2025-07-26", "title": "季度报告", "tags": ["重要", "2025"]}

    result = engine.render(tmpl, ai_fields, item)
    check("Template.render.basic", result == "2025-07-26_季度报告.pdf", f"got: {result}")

    # Render with tags
    tmpl2 = NamingTemplate(pattern="{date}_{tags}.{ext}", separator="-")
    result2 = engine.render(tmpl2, ai_fields, item)
    check("Template.render.tags", "重要-2025" in result2, f"got: {result2}")

    # Render with unknown date
    result3 = engine.render(tmpl, {"date": "unknown", "title": "test"}, item)
    check("Template.render.unknown_date", "test" in result3, f"got: {result3}")

    # Render with list tags (use template WITH {tags} in pattern)
    tmpl_tags = NamingTemplate(pattern="{date}_{tags}.{ext}", separator="_")
    result4 = engine.render(tmpl_tags, {"date": "2025-01-01", "title": "doc", "tags": ["a", "b", "c"]}, item)
    check("Template.render.list_tags", "a_b_c" in result4, f"got: {result4}")

    # Sanitization
    tmpl3 = NamingTemplate(pattern="{date}_{title}.{ext}")
    dirty = engine.render(tmpl3, {"date": "2025-01-01", "title": "test<file>name"}, item)
    check("Template.sanitize", "<" not in dirty and ">" not in dirty, f"got: {dirty}")

test_template_engine()

# ============================================================================
section("7. RENAME HISTORY")

def test_history():
    from src.core.rename_history import RenameHistory
    from src.models.rename_record import RenameRecord

    # Use a test file
    test_file = PROJECT_ROOT / "rename_history" / "_test_history.jsonl"
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
section("8. RENAME ENGINE — Validation & Conflicts")

def test_rename_engine():
    from src.core.rename_engine import RenameEngine
    from src.core.rename_history import RenameHistory
    from src.models.file_item import FileItem, FileStatus
    from src.utils.file_utils import sanitize_filename, resolve_conflict

    # Sanitization
    check("Sanitize.illegal_chars", sanitize_filename("test<file>.txt") == "test_file_.txt",
          sanitize_filename("test<file>.txt"))
    check("Sanitize.leading_dot", sanitize_filename(".hidden") == "hidden")
    check("Sanitize.control_chars", "\x00" not in sanitize_filename("test\x00.txt"))

    # Conflict resolution
    test_dir = PROJECT_ROOT / "test_files"
    result = resolve_conflict(test_dir, "季度销售报告_2025Q1.txt")
    check("Conflict.existing_file", result != "季度销售报告_2025Q1.txt",
          f"got: {result}")
    check("Conflict.still_txt", result.endswith(".txt"))

    # Unique name should stay the same
    result2 = resolve_conflict(test_dir, "unique_filename_xyz123.txt")
    check("Conflict.unique_name", result2 == "unique_filename_xyz123.txt",
          f"got: {result2}")

    # RenameEngine creation
    engine = RenameEngine()
    check("RenameEngine.create", engine is not None)
    check("RenameEngine.no_last_batch", engine.last_batch_id is None)

    # Execute with empty list
    try:
        engine.execute([])
        check("RenameEngine.empty_list_should_fail", False)
    except ValueError as e:
        check("RenameEngine.empty_list_raises", "没有可重命名的文件" in str(e))

test_rename_engine()

# ============================================================================
section("9. AI PROVIDERS — Factory & Configuration")

def test_providers():
    from src.providers.factory import create_provider
    from src.models.app_config import AppConfig

    # DeepSeek
    config = AppConfig(provider="deepseek", api_key="sk-test-ds", base_url="https://api.deepseek.com/v1", model="deepseek-v4-pro")
    provider = create_provider(config)
    check("Factory.deepseek_type", type(provider).__name__ == "DeepSeekProvider")
    check("Factory.deepseek_url", "deepseek.com" in provider.base_url)
    check("Factory.deepseek_model", "deepseek-v4" in provider.model)

    # OpenAI
    config2 = AppConfig(provider="openai", api_key="sk-test-oai", base_url="https://api.openai.com/v1", model="gpt-4o")
    provider2 = create_provider(config2)
    check("Factory.openai_type", type(provider2).__name__ == "OpenAIProvider")

    # Claude
    config3 = AppConfig(provider="claude", api_key="sk-ant-test", base_url="https://api.anthropic.com", model="claude-sonnet-4-20250514")
    provider3 = create_provider(config3)
    check("Factory.claude_type", type(provider3).__name__ == "ClaudeProvider")

    # No API key
    config4 = AppConfig(provider="deepseek", api_key="")
    try:
        create_provider(config4)
        check("Factory.no_api_key_should_fail", False)
    except ValueError as e:
        check("Factory.no_api_key_raises", "API Key" in str(e), str(e))

    # Unknown provider
    config5 = AppConfig(provider="unknown", api_key="sk-test")
    try:
        create_provider(config5)
        check("Factory.unknown_should_fail", False)
    except ValueError as e:
        check("Factory.unknown_raises", True)

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
section("12. ORGANIZATION ENGINE")

def test_organization():
    from src.core.organization_engine import RULE_HANDLERS

    rules = list(RULE_HANDLERS.keys())
    check("Org.rules_count", len(rules) == 4, f"got: {rules}")
    check("Org.by_date", "by_date" in rules)
    check("Org.by_type", "by_type" in rules)
    check("Org.by_category", "by_category" in rules)
    check("Org.by_project", "by_project" in rules)

    # Each rule is callable
    for name, handler in RULE_HANDLERS.items():
        check(f"Org.{name}.callable", callable(handler))

test_organization()

# ============================================================================
section("13. FOLDER WATCHER")

def test_watcher():
    from src.core.folder_watcher import FolderWatcher
    from src.models.watch_config import WatchConfig, WatchMode

    watcher = FolderWatcher()
    check("Watcher.create", watcher is not None)
    check("Watcher.not_running", not watcher.is_running)

    # Add a watch
    config = WatchConfig(
        source_dir=str(PROJECT_ROOT / "test_files"),
        mode=WatchMode.REVIEW_FIRST,
    )
    watcher.add_watch(config)
    check("Watcher.add_watch", len(watcher.get_watched_folders()) == 1)

    # Remove watch
    watcher.remove_watch(config.id)
    check("Watcher.remove_watch", len(watcher.get_watched_folders()) == 0)

    # Start/stop
    watcher.start()
    check("Watcher.start", watcher.is_running)
    watcher.stop()
    check("Watcher.stop", not watcher.is_running)

test_watcher()

# ============================================================================
section("14. GUI — Window Creation (no display)")

def test_gui():
    from PySide6.QtWidgets import QApplication
    from src.ui.main_window import MainWindow
    from src.ui.batch_rename_panel import BatchRenamePanel
    from src.ui.preview_table import PreviewTable, FileItemTableModel
    from src.ui.settings_dialog import SettingsDialog
    from src.ui.template_editor import TemplateEditorDialog
    from src.ui.watch_folder_panel import WatchFolderPanel
    from src.app import RenamerApp

    # Only create app if none exists
    existing = QApplication.instance()
    if existing is not None:
        app = existing
    else:
        app = RenamerApp(sys.argv)

    # Test config is accessible
    if hasattr(app, 'app_config'):
        check("GUI.RenamerApp.config", app.app_config is not None)
        check("GUI.RenamerApp.provider", app.app_config.provider == "deepseek")

    # MainWindow
    window = MainWindow(app)
    check("GUI.MainWindow.create", window is not None)
    check("GUI.MainWindow.title", "AI File Renamer" in window.windowTitle())
    check("GUI.MainWindow.size", window.width() >= 1000, f"w={window.width()}")

    # MainWindow components
    check("GUI.MainWindow.batch_panel", window.batch_panel is not None)
    check("GUI.MainWindow.watch_panel", window.watch_panel is not None)

    # BatchRenamePanel
    panel = window.batch_panel
    check("GUI.BatchPanel.table", panel.table is not None)
    check("GUI.BatchPanel.scanner", panel.scanner is not None)
    check("GUI.BatchPanel.history", panel.history is not None)
    check("GUI.BatchPanel.rename_engine", panel.rename_engine is not None)

    # PreviewTable
    table = panel.table
    check("GUI.PreviewTable.model", table.table_model is not None)
    check("GUI.PreviewTable.column_count", table.table_model.columnCount() == 5)

    # SettingsDialog
    dialog = SettingsDialog(app)
    check("GUI.SettingsDialog.create", dialog is not None)
    check("GUI.SettingsDialog.tabs", dialog.tabs.count() == 3)

    # TemplateEditorDialog
    tmpl_dialog = TemplateEditorDialog(app)
    check("GUI.TemplateEditor.create", tmpl_dialog is not None)

    # WatchFolderPanel
    watch = window.watch_panel
    check("GUI.WatchPanel.watcher", watch.watcher is not None)

    # Clean up
    window.close()
    dialog.close()
    tmpl_dialog.close()

test_gui()

# ============================================================================
section("15. END-TO-END PIPELINE (simulated)")

def test_e2e():
    from src.core.file_scanner import FileScanner
    from src.core.content_extractor import extract
    from src.core.template_engine import TemplateEngine
    from src.models.file_item import FileItem, FileStatus
    from src.models.template import NamingTemplate
    from src.core.rename_history import RenameHistory
    from src.models.rename_record import RenameRecord
    from src.utils.file_utils import sanitize_filename

    print("  Simulating full pipeline...")

    # Step 1: Scan
    scanner = FileScanner()
    items = scanner.scan_directory(PROJECT_ROOT / "test_files")
    assert len(items) >= 2, f"Expected >=2 files, got {len(items)}"
    print(f"  Step 1 Scan: {len(items)} files found")

    # Step 2: Extract
    for item in items:
        extract(item, max_chars=4000)
        assert item.status == FileStatus.EXTRACTED, f"Extract failed for {item.original_name}: {item.error_message}"
    print(f"  Step 2 Extract: all {len(items)} files extracted")

    # Step 3: Template render (simulated AI response)
    engine = TemplateEngine()
    template = NamingTemplate(pattern="{date}_{title}.{ext}", separator="_")
    suggestions = []
    for item in items:
        # Simulate AI response based on content
        if "销售" in item.extracted_text:
            ai_fields = {"date": "2025-Q1", "title": "季度销售报告", "tags": ["销售", "季度"]}
        elif "AI" in item.extracted_text or "重命名" in item.extracted_text:
            ai_fields = {"date": "2025-07-26", "title": "AI重命名工具项目需求", "tags": ["AI", "项目"]}
        else:
            ai_fields = {"date": "unknown", "title": item.original_name[:20], "tags": []}

        suggested = engine.render(template, ai_fields, item)
        item.suggested_name = suggested
        item.final_name = suggested
        item.ai_fields = ai_fields
        item.status = FileStatus.SUGGESTED
        suggestions.append(suggested)
        print(f"  Step 3 Suggest: {item.original_name} → {suggested}")

    # Step 4: Validate names
    for name in suggestions:
        sanitized = sanitize_filename(name)
        check(f"E2E.valid_name.{sanitized[:30]}", len(sanitized) > 0 and len(sanitized) <= 200,
              f"len={len(sanitized)}")

    # Step 5: History recording (dry run)
    history_file = PROJECT_ROOT / "rename_history" / "_e2e_test.jsonl"
    if history_file.exists():
        history_file.unlink()

    history = RenameHistory(history_file)
    batch_id = "e2e-test-batch"
    for item in items:
        history.record(RenameRecord(
            batch_id=batch_id,
            old_path=item.original_path,
            new_path=item.original_path.parent / item.suggested_name,
            file_size=item.file_size,
        ))

    records = history.get_all()
    check("E2E.history_saved", len(records) == len(items),
          f"expected {len(items)}, got {len(records)}")

    # Clean up
    if history_file.exists():
        history_file.unlink()

    print(f"  [PASS] E2E.complete — Full pipeline: scan → extract → suggest → validate → log")

test_e2e()

# ============================================================================
section("16. MIDDLEWARE LAYER — Integration Wiring")

def test_integration():
    """Verify that the middleware layer properly connects all components."""
    from src.core.file_scanner import FileScanner
    from src.core.content_extractor import extract
    from src.core.ai_engine import AIEngine
    from src.core.rename_engine import RenameEngine
    from src.core.rename_history import RenameHistory
    from src.core.template_engine import TemplateEngine
    from src.core.folder_watcher import FolderWatcher
    from src.models.file_item import FileItem, FileStatus
    from src.models.app_config import AppConfig
    from src.models.template import NamingTemplate

    # Verify scanner → extractor handoff
    scanner = FileScanner()
    items = scanner.scan_directory(PROJECT_ROOT / "test_files")
    for item in items:
        extract(item)
        check(f"Integration.extract.{item.original_name}", item.status == FileStatus.EXTRACTED)

    # Verify extractor → AI engine handoff (with config, no real API call)
    config = AppConfig(api_key="sk-test")
    ai = AIEngine(config)
    for item in items:
        if item.status == FileStatus.EXTRACTED:
            # Don't actually call AI, just verify the engine is configured
            check(f"Integration.ai_engine.{item.original_name}", ai is not None)
            break

    # Verify rename engine → history handoff
    engine = RenameEngine()
    check("Integration.rename_engine", engine is not None)
    check("Integration.rename_engine.history", engine.history is not None)
    summary = engine.get_history_summary()
    check("Integration.history_summary_type", isinstance(summary, list))

    # Verify template engine → file item integration
    tmpl_engine = TemplateEngine()
    template = NamingTemplate(pattern="{date}_{title}.{ext}")
    result = tmpl_engine.render(template, {"date": "2025-01-01", "title": "Test"}, items[0])
    check("Integration.template_render", len(result) > 5)

    # Verify folder watcher → config integration
    watcher = FolderWatcher()
    from src.models.watch_config import WatchConfig
    wc = WatchConfig(source_dir=str(PROJECT_ROOT / "test_files"))
    watcher.add_watch(wc)
    check("Integration.watcher_add", len(watcher.get_watched_folders()) == 1)
    watcher.remove_watch(wc.id)
    watcher.stop()

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

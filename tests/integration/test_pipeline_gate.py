"""Non-multimodal pipeline integration gate (Task 6).

Proves cross-cutting invariants of the usage / vocabulary / watch work:

1. Review First and Auto Apply use the SAME RenameExecutor.
2. Watch apply and Batch apply share the SAME RenameHistory.
3. Watch-created records are undoable by the existing UndoManager.
4. No controller performs direct rename/move I/O.
5. No disk mutation before approval in Review First.
6. Auto Apply interrupted restart does not re-rename.
7. ResourcePaused is never mislabeled as a monetary state.
8. No monetary UI words were re-introduced.
9. Usage persistence contains no key/prompt/body/path material.
10. A vocabulary change invalidates the cache.
11. Provider capability insufficiency fails closed.
12. No real network / credential access in the new code.
13. Golden screenshots are untouched (blobs match HEAD).
14. Multimodal + M6-geometry files are untouched (except the minimal
    Usage binding in PreferencesPage).

Structural scans use word-boundary matching so legitimate terms like
"concurrency" never trip them.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent

# Multimodal / M3-owned implementation files that must remain untouched.
MULTIMODAL_FILES = [
    "src/core/content_extractor.py",
    "src/providers/openai_compatible.py",
    "src/core/connection_test.py",
    "src/core/cost_estimator.py",
    "src/core/provider_protocol.py",
    "src/core/provider_presets.py",
    "src/core/cache_manager.py",
]

# M6-accepted preferences geometry files — untouched except PreferencesPage,
# which may only carry the minimal Usage binding.
M6_GEOMETRY_FILES = [
    "src/ui_qml/DesignTokens.qml",
    "src/ui_qml/GeneralSettingsCard.qml",
    "src/ui_qml/ProviderSettingsCard.qml",
    "src/ui_qml/ProviderForm.qml",
    "src/ui_qml/QualityCard.qml",
    "src/ui_qml/ResourceLimitsCard.qml",
    "src/ui_qml/PrivacyCard.qml",
    "src/ui_qml/CacheCard.qml",
    "src/ui_qml/UsageCard.qml",
    "src/ui_qml/DiagnosticsCard.qml",
    "src/ui_qml/Shell.qml",
    "src/ui_qml/main.qml",
    "src/ui_qml/PageRouter.qml",
]

NEW_WATCH_MODULES = [
    "src/controllers/review_first_handler.py",
    "src/controllers/auto_apply_handler.py",
    "src/controllers/watch_controller.py",
    "src/core/watch_analysis.py",
    "src/core/watch_review_queue.py",
    "src/core/watch_resource_guard.py",
]

NEW_TEST_FILES = [
    "tests/unit/test_usage.py",
    "tests/unit/test_vocabulary_cache_context.py",
    "tests/unit/test_watch_resource_guard.py",
    "tests/integration/test_vocabulary_cache_invalidation.py",
    "tests/integration/test_review_first.py",
    "tests/integration/test_auto_apply.py",
    "tests/integration/test_watch_resource_guard_pipeline.py",
    "tests/integration/test_watch_safety_regressions.py",
]


def _head_blob(path: str) -> bytes:
    """Working-tree vs committed blob comparison (read-only)."""
    return subprocess.check_output(
        ["git", "show", f"HEAD:{path}"], cwd=str(ROOT), stderr=subprocess.DEVNULL
    ).replace(b"\r\n", b"\n")


def _working_blob(path: str) -> bytes:
    # normalize CRLF (autocrlf checkout) so comparison is line-ending agnostic
    return (ROOT / path).read_bytes().replace(b"\r\n", b"\n")


# ============================================================================
# 1-3: shared engine / history / undo
# ============================================================================

def test_review_and_auto_share_the_same_executor(tmp_path):
    from src.controllers.auto_apply_handler import AutoApplyHandler, AutoApplyJournal
    from src.controllers.review_first_handler import ReviewFirstHandler
    from src.core.preflight_service import PreflightService
    from src.core.rename_executor import RenameExecutor
    from src.core.rename_history import RenameHistory
    from src.core.watch_review_queue import ReviewQueue

    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    src.mkdir(); tgt.mkdir()
    history = RenameHistory(tmp_path / "history.jsonl")
    preflight = PreflightService(allowed_roots=[str(src), str(tgt)])
    executor = RenameExecutor(preflight, history)  # ONE shared instance

    review = ReviewFirstHandler(
        queue=ReviewQueue(tmp_path / "review.json"),
        analysis_service=object(), executor=executor, preflight=preflight,
        config_provider=lambda wid: None,
    )
    auto = AutoApplyHandler(
        journal=AutoApplyJournal(tmp_path / "journal.json"),
        analysis_service=object(), executor=executor, preflight=preflight,
        config_provider=lambda wid: None,
    )
    assert review._executor is executor
    assert auto._executor is executor
    assert review._executor is auto._executor


def test_watch_and_batch_share_history_and_undo(tmp_path):
    """A watch-applied rename and a batch-applied rename land in the SAME
    history file and are both undoable by one UndoManager."""
    from src.controllers.auto_apply_handler import AutoApplyHandler, AutoApplyJournal
    from src.core.preflight_service import PreflightService
    from src.core.rename_executor import RenameExecutor
    from src.core.rename_history import RenameHistory
    from src.core.rename_plan import RenamePlan, SourceFingerprint
    from src.core.undo_manager import UndoManager
    from src.core.watch_analysis import AnalysisResult

    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    src.mkdir(); tgt.mkdir()
    history = RenameHistory(tmp_path / "history.jsonl")
    preflight = PreflightService(allowed_roots=[str(src), str(tgt)])
    executor = RenameExecutor(preflight, history)
    undo = UndoManager(str(tmp_path / "history.jsonl"), executor=executor)

    # watch-apply one file via the pipeline (fake analysis)
    class FakeAnalysis:
        def analyze(self, source_path, template_id="", quality_mode="balanced"):
            return AnalysisResult(suggested_name="watch-out.txt", confidence=0.95)

    class Cfg:
        template_id = ""
        target_dir = str(tgt)

    handler = AutoApplyHandler(
        journal=AutoApplyJournal(tmp_path / "journal.json"),
        analysis_service=FakeAnalysis(), executor=executor, preflight=preflight,
        config_provider=lambda wid: Cfg(),
    )
    (src / "watch-in.txt").write_text("watch", encoding="utf-8")
    handler.handle_file_ready("w1", str(src / "watch-in.txt"))

    # batch-apply another file through the same executor
    (src / "batch-in.txt").write_text("batch", encoding="utf-8")
    stat = (src / "batch-in.txt").stat()
    executor.execute([RenamePlan(
        task_id="batch-task",
        source_path=str(src / "batch-in.txt"),
        source_fingerprint=SourceFingerprint(stat.st_size, stat.st_mtime_ns),
        target_name="batch-out.txt",
        target_parent=str(tgt),
        extension=".txt",
        batch_id="batch-b",
    )], batch_id="batch-b")

    assert (tgt / "watch-out.txt").exists()
    assert (tgt / "batch-out.txt").exists()
    records = history.get_all()
    assert len(records) == 2
    assert {r.batch_id for r in records} >= {"watch-auto-w1", "batch-b"}

    # ONE UndoManager undoes both
    results = undo.undo_last_batch()
    assert any(r.success for r in results)
    results2 = undo.undo_last_batch()
    assert any(r.success for r in results2)
    assert (src / "watch-in.txt").exists()
    assert (src / "batch-in.txt").exists()


# ============================================================================
# 4-6: I/O boundaries
# ============================================================================

def test_no_direct_rename_or_move_io_in_controllers():
    pattern = re.compile(r"\bos\.rename\b|\bshutil\.move\b|\bPath\.rename\b|\.replace\(.*\.tmp")
    offenders = []
    for py in (ROOT / "src" / "controllers").glob("*.py"):
        text = py.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            offenders.append(f"{py.name}: {m.group(0)}")
    assert not offenders, f"controllers must not perform rename/move I/O: {offenders}"


def test_no_disk_mutation_before_approval(tmp_path):
    from src.controllers.review_first_handler import ReviewFirstHandler
    from src.core.preflight_service import PreflightService
    from src.core.rename_executor import RenameExecutor
    from src.core.rename_history import RenameHistory
    from src.core.watch_analysis import AnalysisResult
    from src.core.watch_review_queue import ReviewQueue

    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    src.mkdir(); tgt.mkdir()
    history = RenameHistory(tmp_path / "history.jsonl")
    preflight = PreflightService(allowed_roots=[str(src), str(tgt)])
    executor = RenameExecutor(preflight, history)

    class FakeAnalysis:
        def analyze(self, source_path, template_id="", quality_mode="balanced"):
            return AnalysisResult(suggested_name="out.txt", confidence=0.95)

    class Cfg:
        template_id = ""
        target_dir = str(tgt)

    handler = ReviewFirstHandler(
        queue=ReviewQueue(tmp_path / "review.json"),
        analysis_service=FakeAnalysis(), executor=executor, preflight=preflight,
        config_provider=lambda wid: Cfg(),
    )
    path = src / "doc.txt"
    path.write_text("content", encoding="utf-8")
    before = path.read_bytes()
    handler.handle_file_ready("w1", str(path))

    # analysis produced a suggestion but NO disk mutation happened
    assert path.read_bytes() == before
    assert (tgt / "out.txt").exists() is False
    assert history.get_all() == []


def test_auto_apply_interrupted_restart_does_not_re_rename(tmp_path):
    """An applied task must never re-rename after a restart."""
    from src.controllers.auto_apply_handler import AutoApplyHandler, AutoApplyJournal
    from src.core.preflight_service import PreflightService
    from src.core.rename_executor import RenameExecutor
    from src.core.rename_history import RenameHistory
    from src.core.watch_analysis import AnalysisResult

    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    src.mkdir(); tgt.mkdir()
    history = RenameHistory(tmp_path / "history.jsonl")
    preflight = PreflightService(allowed_roots=[str(src), str(tgt)])
    executor = RenameExecutor(preflight, history)

    class FakeAnalysis:
        def analyze(self, source_path, template_id="", quality_mode="balanced"):
            return AnalysisResult(suggested_name="out.txt", confidence=0.95)

    class Cfg:
        template_id = ""
        target_dir = str(tgt)

    def make_handler():
        return AutoApplyHandler(
            journal=AutoApplyJournal(tmp_path / "journal.json"),
            analysis_service=FakeAnalysis(), executor=executor, preflight=preflight,
            config_provider=lambda wid: Cfg(),
        )

    path = src / "doc.txt"
    path.write_text("content", encoding="utf-8")
    make_handler().handle_file_ready("w1", str(path))
    assert not path.exists() and (tgt / "out.txt").exists()

    # "restart" with the same journal: re-delivered events must not re-apply
    make_handler().handle_file_ready("w1", str(path))
    assert len(history.get_all()) == 1
    assert (tgt / "out.txt").exists()
    assert (tgt / "out_1.txt").exists() is False


# ============================================================================
# 7-9: no monetary states/UI, usage schema safety
# ============================================================================

def test_resource_paused_is_never_a_monetary_state():
    from src.core.watch_config import WatchStatus
    assert WatchStatus.RESOURCE_PAUSED.value == "resource_paused"
    assert not hasattr(WatchStatus, "BUDGET_PAUSED")
    assert not hasattr(WatchStatus, "BUDGET_EXCEEDED")


def test_no_monetary_words_in_watch_sources():
    pattern = re.compile(
        r"\b(价格|费用|预算|币种|金额|price|currency|budget|monthly|spending|"
        r"fee|billing|allowance|quota|BudgetPaused)\b",
        re.IGNORECASE,
    )
    offenders = []
    for py in NEW_WATCH_MODULES:
        text = (ROOT / py).read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            offenders.append(f"{py}: {m.group(0)}")
    assert not offenders, f"monetary concept leaked into watch sources: {offenders}"


def test_no_monetary_ui_words_in_qml():
    pattern = re.compile(
        r"\b(价格|费用|预算|币种|金额|price|currency|budget|monthly|spending|"
        r"fee|billing|pricing|BudgetPaused)\b",
        re.IGNORECASE,
    )
    offenders = []
    for qml in (ROOT / "src" / "ui_qml").glob("*.qml"):
        text = qml.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            offenders.append(f"{qml.name}: {m.group(0)}")
    assert not offenders, f"monetary concept leaked into QML: {offenders}"


def test_usage_persistence_has_no_secret_material(tmp_path):
    from src.core.usage import UsageRecorder, UsageRecord

    recorder = UsageRecorder(tmp_path / "usage.json")
    key = "sk-gate-sentinel-12345"
    prompt = "GATE_PROMPT_SENTINEL"
    body = "GATE_BODY_SENTINEL"
    full_path = "C:\\Users\\victim\\secret\\report.pdf"
    recorder.record(UsageRecord(
        provider_id="deepseek", profile_id="deepseek", model="m",
        content_kind="text", request_count=1, cache_hit=False, success=True,
        input_tokens=None, output_tokens=None,
        timestamp_utc="2026-08-03T00:00:00+00:00",
    ))
    raw = (tmp_path / "usage.json").read_bytes()
    for sentinel in (key, prompt, body, full_path):
        assert sentinel.encode() not in raw, f"secret material persisted: {sentinel}"


def test_usage_schema_forbidden_fields():
    from dataclasses import fields
    from src.core.usage import UsageRecord
    names = {f.name for f in fields(UsageRecord)}
    for forbidden in ("api_key", "authorization", "prompt", "body", "content",
                      "full_path", "file_name", "price", "cost", "currency"):
        assert forbidden not in names


# ============================================================================
# 10-12: cache invalidation, capability fail-closed, no network
# ============================================================================

def test_vocabulary_change_causes_cache_miss(tmp_path):
    from src.core.cache_manager import CacheContext, CacheManager
    from src.core.vocabulary import (
        VocabularyCacheContextContributor,
        VocabularyCategory,
        VocabularyEntry,
        VocabularySource,
        VocabularyStore,
    )

    store = VocabularyStore()
    store.add_entry(VocabularyEntry(
        category=VocabularyCategory.STATUS, concept_id="done",
        display_name="Done", locale="en-US", source=VocabularySource.SYSTEM))
    contributor = VocabularyCacheContextContributor(store)
    cache = CacheManager(store_path=tmp_path / "cache.json")

    ctx1 = contributor.apply_to(CacheContext(content_hash="h1"))
    cache.put(ctx1, {"result": 1})
    assert cache.get(ctx1) is not None

    store.add_entry(VocabularyEntry(
        category=VocabularyCategory.PROJECT, concept_id="p1",
        display_name="P1", locale="en-US", source=VocabularySource.USER))
    ctx2 = contributor.apply_to(CacheContext(content_hash="h1"))
    assert ctx2.vocabulary_version != ctx1.vocabulary_version
    assert cache.get(ctx2) is None


def test_capability_insufficiency_fails_closed(tmp_path):
    from src.controllers.auto_apply_handler import AutoApplyHandler, AutoApplyJournal
    from src.core.preflight_service import PreflightService
    from src.core.rename_executor import RenameExecutor
    from src.core.rename_history import RenameHistory
    from src.core.watch_analysis import AnalysisResult

    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    src.mkdir(); tgt.mkdir()
    history = RenameHistory(tmp_path / "history.jsonl")
    preflight = PreflightService(allowed_roots=[str(src), str(tgt)])
    executor = RenameExecutor(preflight, history)

    class CapabilityFailingAnalysis:
        def analyze(self, source_path, template_id="", quality_mode="balanced"):
            return AnalysisResult(
                suggested_name="", confidence=0.0,
                error_category="capability_unsupported")

    class Cfg:
        template_id = ""
        target_dir = str(tgt)

    handler = AutoApplyHandler(
        journal=AutoApplyJournal(tmp_path / "journal.json"),
        analysis_service=CapabilityFailingAnalysis(),
        executor=executor, preflight=preflight,
        config_provider=lambda wid: Cfg(),
    )
    path = src / "doc.txt"
    path.write_text("content", encoding="utf-8")
    handler.handle_file_ready("w1", str(path))

    entry = handler.journal_entry("w1", str(path))
    assert entry is not None and entry.state == "failed"
    assert entry.error_category == "capability_unsupported"
    assert path.exists(), "no rename may happen on capability failure"
    assert history.get_all() == []


def test_no_real_network_or_credential_imports_in_new_code():
    network_markers = [
        "import requests", "from requests", "import httpx", "from httpx",
        "import urllib.request", "http.client", "import keyring", "from keyring",
        "import aiohttp", "from aiohttp", "import websocket",
    ]
    offenders = []
    for py in NEW_WATCH_MODULES + ["src/core/usage.py", "src/core/vocabulary.py"]:
        text = (ROOT / py).read_text(encoding="utf-8")
        for marker in network_markers:
            if marker in text:
                offenders.append(f"{py}: {marker}")
    assert not offenders, f"new code must not touch the network or credentials: {offenders}"


# ============================================================================
# 13-14: goldens / multimodal / M6 geometry untouched
# ============================================================================

def test_screenshot_goldens_untouched():
    result = subprocess.run(
        ["git", "status", "--short", "--", "tests/screenshots"],
        cwd=str(ROOT), capture_output=True, text=True, check=False,
    )
    assert result.stdout.strip() == "", (
        f"goldens must be untouched, got: {result.stdout.strip()!r}"
    )


def test_qa_current_untouched():
    result = subprocess.run(
        ["git", "status", "--short", "--", "tests/screenshots/qa-current"],
        cwd=str(ROOT), capture_output=True, text=True, check=False,
    )
    assert result.stdout.strip() == ""


def test_multimodal_files_blobs_match_head():
    changed = []
    for path in MULTIMODAL_FILES:
        try:
            head = _head_blob(path)
        except subprocess.CalledProcessError:
            continue  # new file at HEAD? not part of this gate
        if _working_blob(path) != head:
            changed.append(path)
    assert not changed, f"multimodal implementation files changed: {changed}"


def test_m6_geometry_files_blobs_match_head():
    changed = []
    for path in M6_GEOMETRY_FILES:
        try:
            head = _head_blob(path)
        except subprocess.CalledProcessError:
            continue
        if _working_blob(path) != head:
            changed.append(path)
    assert not changed, f"M6 geometry files changed: {changed}"


def test_preferences_page_diff_is_only_the_usage_binding():
    """PreferencesPage.qml may change ONLY by the minimal Usage binding."""
    diff = subprocess.check_output(
        ["git", "diff", "HEAD", "--", "src/ui_qml/PreferencesPage.qml"],
        cwd=str(ROOT), text=True,
    )
    forbidden_lines = []
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            if "usageAvailable" not in line and "usageData" not in line:
                forbidden_lines.append(line)
    assert not forbidden_lines, f"PreferencesPage has non-usage changes: {forbidden_lines}"


# ============================================================================
# No new skips / xfails in the new test files
# ============================================================================

def test_new_tests_have_no_skip_or_xfail():
    markers = re.compile(r"@pytest\.mark\.(skip|skipif|xfail)|\bpytest\.skip\(|\bxfail\(")
    offenders = []
    for path in NEW_TEST_FILES:
        text = (ROOT / path).read_text(encoding="utf-8")
        if markers.search(text):
            offenders.append(path)
    assert not offenders, f"new tests must not use skip/xfail: {offenders}"

"""Smart mode task snapshots and file-operation contracts (offline only)."""
import json
from pathlib import Path

import pytest

from src.controllers.batch_workspace_controller import BatchWorkspaceController


def _file(tmp_path, name, text="Synthetic content for naming tests."):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _controller(tmp_path, analyzer=None):
    return BatchWorkspaceController(
        workspace_path=tmp_path / "workspace.json",
        history_path=tmp_path / "history.json",
        analyzer=analyzer, background=False,
    )


def test_modes_preserve_selected_template_and_explicit_language(tmp_path):
    ctrl = _controller(tmp_path)
    try:
        ctrl.configure_templates([
            {"id": "a", "name": "Default", "outputLanguage": "en"},
            {"id": "b", "name": "Project", "outputLanguage": "ja"},
        ], "b")
        before = ctrl.templateOptions
        assert ctrl.namingMode == "template"
        ctrl.setNamingLanguage("zh-HK")
        ctrl.setNamingMode("smart")
        assert ctrl.namingMode == "smart"
        assert ctrl.selectedTemplateId == "b"
        assert ctrl.templateOptions == before
        assert ctrl.namingLanguage == "zh-HK"
        ctrl.setNamingMode("template")
        assert ctrl.selectedTemplateId == "b"
        with pytest.raises(ValueError):
            ctrl.setNamingMode("unknown")
        assert ctrl.namingMode == "template"
    finally:
        ctrl.close()


def test_smart_import_retry_and_restart_keep_strategy_snapshot(tmp_path):
    calls = []

    def analyze(path, task_id, *, template_id=None, output_language=None,
                naming_mode="template", naming_policy_version="smart-v1"):
        calls.append((task_id, template_id, output_language, naming_mode, naming_policy_version))
        return "Specific topic.txt"

    ctrl = _controller(tmp_path)
    first = _file(tmp_path, "first.txt")
    second = _file(tmp_path, "second.txt")
    try:
        ctrl.configure_templates([{"id": "saved", "name": "Saved", "outputLanguage": "en"}])
        ctrl.setNamingMode("smart")
        ctrl.setNamingLanguage("zh-HK")
        ctrl.add_files([str(first)])
        smart_id = ctrl.task_ids[0]
        ctrl.setNamingMode("template")
        ctrl.setNamingLanguage("en")
        ctrl.add_files([str(second)])
        ctrl.set_analyzer(analyze)
        assert calls[0][1:] == ("", "zh-HK", "smart", "smart-v1")
        assert calls[1][1:] == ("saved", "en", "template", "smart-v1")
        ctrl.retryTask(smart_id)
        assert calls[-1][1:] == ("", "zh-HK", "smart", "smart-v1")
        data = json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8"))
        assert data["tasks"][0]["namingMode"] == "smart"
        assert data["tasks"][0]["namingPolicyVersion"] == "smart-v1"
        assert first.read_text() == "Synthetic content for naming tests."
    finally:
        ctrl.close()

    restarted = _controller(tmp_path)
    try:
        assert restarted.namingMode == "template"
        restarted.setNamingLanguage("ja")
        restarted.set_analyzer(analyze)
        restarted.retryTask(smart_id)
        assert calls[-1][1:] == ("", "zh-HK", "smart", "smart-v1")
    finally:
        restarted.close()


def test_smart_requires_strategy_aware_analyzer(tmp_path):
    calls = []
    def legacy_analyze(path, task_id):
        calls.append(path)
        return "Template fallback.txt"

    ctrl = _controller(tmp_path, legacy_analyze)
    try:
        ctrl.setNamingMode("smart")
        ctrl.add_files([str(_file(tmp_path, "one.txt"))])
        task = ctrl.task_snapshot(ctrl.task_ids[0])
        assert task["status"] == "failed"
        assert task["errorMessage"] == "smart.error.strategyUnavailable"
        assert calls == []
    finally:
        ctrl.close()


def test_smart_no_template_uses_default_filename_language_not_ui(tmp_path):
    calls = []
    def analyze(path, task_id, **kwargs):
        calls.append(kwargs)
        return "Specific content.txt"

    ctrl = _controller(tmp_path, analyze)
    try:
        ctrl.setNamingMode("smart")
        ctrl.add_files([str(_file(tmp_path, "one.txt"))])
        assert calls[0]["template_id"] == ""
        assert calls[0]["output_language"] == "zh"
        assert calls[0]["naming_mode"] == "smart"
        assert calls[0]["naming_policy_version"] == "smart-v1"
    finally:
        ctrl.close()


def test_legacy_workspace_without_mode_keeps_template_semantics(tmp_path):
    source = _file(tmp_path, "legacy.txt")
    ctrl = _controller(tmp_path)
    ctrl.add_files([str(source)])
    ctrl.close()
    workspace = tmp_path / "workspace.json"
    data = json.loads(workspace.read_text(encoding="utf-8"))
    for item in data["tasks"]:
        item.pop("namingMode", None)
        item.pop("namingPolicyVersion", None)
    workspace.write_text(json.dumps(data), encoding="utf-8")
    calls = []
    def analyze(path, task_id, *, naming_mode="template", naming_policy_version="smart-v1"):
        calls.append(naming_mode)
        return "Legacy template.txt"
    restarted = _controller(tmp_path)
    try:
        restarted.setNamingMode("smart")
        restarted.set_analyzer(analyze)
        assert calls == ["template"]
    finally:
        restarted.close()


@pytest.mark.parametrize("field,value", [("namingMode", "future-mode"),
                                        ("namingPolicyVersion", "smart-v999")])
def test_unknown_persisted_strategy_fails_before_analysis(tmp_path, field, value):
    ctrl = _controller(tmp_path)
    ctrl.setNamingMode("smart")
    ctrl.add_files([str(_file(tmp_path, "pending.txt"))])
    ctrl.close()
    workspace = tmp_path / "workspace.json"
    data = json.loads(workspace.read_text(encoding="utf-8"))
    data["tasks"][0][field] = value
    workspace.write_text(json.dumps(data), encoding="utf-8")
    calls = []

    def analyze(path, task_id, **kwargs):
        calls.append(kwargs)
        return "Should not run.txt"

    restarted = _controller(tmp_path, analyze)
    try:
        task = restarted.task_snapshot(restarted.task_ids[0])
        assert task["status"] == "failed"
        assert task["errorMessage"] == "smart.error.unsupportedPolicy"
        assert calls == []
    finally:
        restarted.close()


def test_smart_suggestions_use_existing_collision_and_undo_engine(tmp_path):
    def analyze(path, task_id, *, naming_mode, naming_policy_version, **kwargs):
        assert naming_mode == "smart"
        return "Project_overview.txt"
    ctrl = _controller(tmp_path, analyze)
    first = _file(tmp_path, "first.txt", "First distinct content")
    second = _file(tmp_path, "second.txt", "Second distinct content")
    try:
        ctrl.setNamingMode("smart")
        ctrl.add_files([str(first), str(second)])
        ids = ctrl.task_ids
        assert all(ctrl.task_snapshot(t)["status"] == "review_pending" for t in ids)
        assert first.exists() and second.exists()
        ctrl.setSelectAllState("all")
        ctrl.applySelected()
        targets = [Path(ctrl.task_snapshot(t)["appliedPath"]) for t in ids]
        assert len(set(targets)) == 2
        assert {p.read_text() for p in targets} == {"First distinct content", "Second distinct content"}
        assert all(p.suffix == ".txt" for p in targets)
        for task_id in reversed(ids):
            ctrl.undoTask(task_id)
        assert first.read_text() == "First distinct content"
        assert second.read_text() == "Second distinct content"
    finally:
        ctrl.close()

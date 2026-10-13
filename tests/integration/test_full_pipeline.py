"""M8 real Batch pipeline integration (all external AI is faked)."""

from pathlib import Path
import threading

from src.controllers.batch_workspace_controller import BatchWorkspaceController


def _suggest(path: str, _task_id: str) -> str:
    source = Path(path)
    return f"2026-项目资料{source.suffix.lower()}"


def _controller(tmp_path):
    return BatchWorkspaceController(
        workspace_path=tmp_path / "workspace.json",
        history_path=tmp_path / "undo.jsonl",
        analyzer=_suggest,
        background=False,
    )


def test_batch_import_suggest_apply_restart_and_undo(tmp_path):
    source_dir = tmp_path / "inbox"
    source_dir.mkdir()
    source = source_dir / "原始资料.pdf"
    source.write_bytes(b"local-test-pdf")

    ctrl = _controller(tmp_path)
    ctrl.addPaths([str(source)])
    task = ctrl.task_snapshot(ctrl.task_ids[0])
    assert task["status"] == "review_pending"
    assert task["suggestedName"] == "2026-项目资料.pdf"

    ctrl.applyTask(task["taskId"])
    applied = ctrl.task_snapshot(task["taskId"])
    assert applied["status"] == "applied"
    renamed = source_dir / "2026-项目资料.pdf"
    assert renamed.exists() and not source.exists()

    restarted = _controller(tmp_path)
    restored = restarted.task_snapshot(task["taskId"])
    assert restored["status"] == "applied"
    assert restored["appliedPath"] == str(renamed)

    restarted.undoTask(task["taskId"])
    undone = restarted.task_snapshot(task["taskId"])
    assert undone["status"] == "undone"
    assert source.exists() and not renamed.exists()


def test_batch_partial_apply_preserves_per_item_results(tmp_path):
    first = tmp_path / "一.pdf"
    second = tmp_path / "二.pdf"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    ctrl = _controller(tmp_path)
    ctrl.addPaths([str(first), str(second)])
    for task_id in ctrl.task_ids:
        ctrl.toggleTaskSelected(task_id)

    second.unlink()
    ctrl.applySelected()
    states = {ctrl.task_snapshot(tid)["status"] for tid in ctrl.task_ids}
    assert states == {"applied", "failed"}
    assert ctrl.applySuccess == 1
    assert ctrl.applyFailed == 1


def test_batch_rejects_apply_when_source_changed_after_suggestion(tmp_path):
    source = tmp_path / "原始.pdf"
    source.write_bytes(b"old")
    ctrl = _controller(tmp_path)
    ctrl.addPaths([str(source)])
    task_id = ctrl.task_ids[0]
    assert ctrl.task_snapshot(task_id)["status"] == "review_pending"

    source.write_bytes(b"new-content-with-different-size")
    ctrl.applyTask(task_id)

    task = ctrl.task_snapshot(task_id)
    assert task["status"] == "failed"
    assert "changed" in task["errorMessage"].lower()
    assert source.exists()
    assert not (tmp_path / "2026-项目资料.pdf").exists()


def test_cancel_task_propagates_to_running_analyzer(tmp_path):
    started = threading.Event()
    observed_cancel = threading.Event()

    def blocking_analyzer(_path, _task_id, *, cancellation_token):
        started.set()
        assert observed_cancel.wait(2)
        assert cancellation_token()
        raise RuntimeError("cancelled")

    source = tmp_path / "cancel.pdf"; source.write_bytes(b"pdf")
    ctrl = BatchWorkspaceController(
        workspace_path=tmp_path / "workspace.json",
        history_path=tmp_path / "undo.jsonl",
        analyzer=blocking_analyzer,
        background=True,
    )
    ctrl.addPaths([str(source)])
    assert started.wait(2)
    task_id = ctrl.task_ids[0]
    ctrl.cancelTask(task_id)
    observed_cancel.set()
    ctrl.close()
    assert ctrl.task_snapshot(task_id)["status"] == "cancelled"


def test_apply_workspace_save_failure_recovers_from_history_on_restart(tmp_path, monkeypatch):
    source = tmp_path / "original.pdf"
    source.write_bytes(b"pdf")
    ctrl = _controller(tmp_path)
    ctrl.addPaths([str(source)])
    task_id = ctrl.task_ids[0]
    original_save = ctrl._save_workspace

    def fail_applied(candidate=None):
        if candidate and any(task.get("status") == "applied" for task in candidate):
            raise OSError("workspace unavailable")
        return original_save(candidate)

    monkeypatch.setattr(ctrl, "_save_workspace", fail_applied)
    ctrl.applyTask(task_id)

    renamed = tmp_path / "2026-项目资料.pdf"
    assert renamed.exists() and not source.exists()
    assert ctrl.task_snapshot(task_id)["status"] == "applied"

    restarted = _controller(tmp_path)
    restored = restarted.task_snapshot(task_id)
    assert restored["status"] == "applied"
    assert restored["appliedPath"] == str(renamed)
    restarted.undoTask(task_id)
    assert source.exists() and not renamed.exists()


def test_clear_workspace_does_not_undo_applied_files(tmp_path):
    source = tmp_path / "原始.pdf"
    source.write_bytes(b"pdf")
    ctrl = _controller(tmp_path)
    ctrl.addPaths([str(source)])
    task_id = ctrl.task_ids[0]
    ctrl.applyTask(task_id)
    renamed = tmp_path / "2026-项目资料.pdf"
    assert renamed.exists()
    ctrl.clearWorkspace()
    assert ctrl.totalCount == 0
    assert renamed.exists(), "Clear Workspace must never be an implicit Undo"


def test_dropped_file_url_and_folder_are_imported_locally(tmp_path):
    from PySide6.QtCore import QUrl

    folder = tmp_path / "拖放目录"
    folder.mkdir()
    first = folder / "一.pdf"
    second = folder / "二.txt"
    first.write_bytes(b"pdf")
    second.write_text("text", encoding="utf-8")
    ctrl = _controller(tmp_path)

    ctrl.importDropped([
        QUrl.fromLocalFile(str(first)),
        QUrl.fromLocalFile(str(folder)),
    ])

    imported = {Path(ctrl.task_snapshot(task_id)["originalName"]).name for task_id in ctrl.task_ids}
    assert imported == {"一.pdf", "二.txt"}

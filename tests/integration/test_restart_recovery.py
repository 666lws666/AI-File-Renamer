import json

from src.controllers.batch_workspace_controller import BatchWorkspaceController


def test_analyzing_task_restores_as_pending_and_is_reprocessed(tmp_path):
    source = tmp_path / "恢复.txt"
    source.write_text("hello", encoding="utf-8")
    workspace = tmp_path / "workspace.json"
    workspace.write_text(json.dumps({
        "schema_version": 1,
        "tasks": [{
            "taskId": "task-recover", "originalName": str(source),
            "suggestedName": "", "extension": ".txt", "status": "analyzing",
            "selected": False, "errorMessage": "", "appliedPath": "",
        }],
    }, ensure_ascii=False), encoding="utf-8")

    ctrl = BatchWorkspaceController(
        workspace_path=workspace,
        history_path=tmp_path / "undo.jsonl",
        analyzer=lambda _path, _id: "恢复完成.txt",
        background=False,
    )
    assert ctrl.task_snapshot("task-recover")["status"] == "review_pending"


def test_corrupt_workspace_is_quarantined_not_silently_overwritten(tmp_path):
    workspace = tmp_path / "workspace.json"
    workspace.write_text("{broken", encoding="utf-8")
    ctrl = BatchWorkspaceController(
        workspace_path=workspace,
        history_path=tmp_path / "undo.jsonl",
        analyzer=lambda _path, _id: "unused.txt",
        background=False,
    )
    assert ctrl.totalCount == 0
    assert not workspace.exists()
    assert list(tmp_path.glob("workspace.json*.corrupted"))

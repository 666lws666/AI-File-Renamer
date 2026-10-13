"""Real-controller regressions for cancelled/stale analysis attempts.

The pool controls scheduling only. Controller state transitions, worker dispatch,
Future callbacks and Qt completion signals all use the production implementation.
No GUI, source-file I/O, credentials or network are required.
"""
from concurrent.futures import Future

import pytest

from src.controllers.batch_workspace_controller import BatchWorkspaceController


class ControlledPool:
    def __init__(self):
        self.jobs = []
        self.shutdown_calls = []

    def submit(self, function, *args):
        future = Future()
        self.jobs.append({"function": function, "args": args, "future": future})
        return future

    def start(self, index):
        job = self.jobs[index]
        try:
            job["result"] = job["function"](*job["args"])
        except Exception as error:
            job["error"] = error

    def complete(self, index):
        job = self.jobs[index]
        if "error" in job:
            job["future"].set_exception(job["error"])
        else:
            job["future"].set_result(job["result"])

    def run(self, index):
        self.start(index)
        self.complete(index)

    def shutdown(self, **kwargs):
        self.shutdown_calls.append(kwargs)


class RecordingAnalyzer:
    def __init__(self, *, first_error=False):
        self.calls = []
        self.first_error = first_error

    def __call__(self, path, task_id, **kwargs):
        self.calls.append((path, task_id, kwargs))
        if self.first_error and len(self.calls) == 1:
            raise ValueError("old attempt failed")
        return f"result-{len(self.calls)}.txt"


def make_controller(analyzer, *, background=True):
    controller = BatchWorkspaceController(analyzer=analyzer, background=False)
    pool = ControlledPool()
    controller._background = background
    controller._pool = pool if background else None
    task = controller._new_task("task-1", "synthetic.txt", ".txt", 1, 1)
    task.update(templateId="original-template", outputLanguage="zh-HK")
    controller._commit_tasks([task])
    return controller, pool


@pytest.mark.parametrize("first_error", [False, True], ids=["success", "error"])
@pytest.mark.parametrize("new_first", [False, True], ids=["old-finishes-first", "new-finishes-first"])
def test_stale_completion_never_overwrites_retry_or_steals_new_event(first_error, new_first):
    analyzer = RecordingAnalyzer(first_error=first_error)
    controller, pool = make_controller(analyzer)
    controller._start_analysis("task-1")
    old_event = controller._cancellation_events["task-1"]
    pool.start(0)  # Work finished, but its completion has not reached the UI yet.

    controller.cancelTask("task-1")
    controller.retryTask("task-1")
    new_event = controller._cancellation_events["task-1"]
    assert old_event.is_set()
    assert new_event is not old_event and not new_event.is_set()
    assert analyzer.calls[0][2]["cancellation_token"]()

    if new_first:
        pool.run(1)
        pool.complete(0)
    else:
        pool.complete(0)
        assert controller.task_snapshot("task-1")["status"] == "analyzing"
        assert controller._cancellation_events.get("task-1") is new_event
        pool.run(1)

    task = controller.task_snapshot("task-1")
    assert task["status"] == "review_pending"
    assert task["suggestedName"] == "result-2.txt"
    assert task["errorMessage"] == ""
    assert "task-1" not in controller._cancellation_events
    controller.close()


def test_cancelled_queued_attempt_cannot_borrow_retry_event_or_call_tokenless_analyzer():
    calls = []

    def analyzer(path, task_id):
        calls.append(task_id)
        return "current.txt"

    controller, pool = make_controller(analyzer)
    controller._start_analysis("task-1")
    old_event = controller._cancellation_events["task-1"]
    controller.cancelTask("task-1")
    controller.retryTask("task-1")
    new_event = controller._cancellation_events["task-1"]
    pool.run(0)
    assert calls == []
    assert old_event.is_set() and not new_event.is_set()
    assert controller._cancellation_events.get("task-1") is new_event
    assert controller.task_snapshot("task-1")["status"] == "analyzing"
    pool.run(1)
    assert calls == ["task-1"]
    assert controller.task_snapshot("task-1")["suggestedName"] == "current.txt"
    controller.close()


@pytest.mark.parametrize("action", ["ignoreTask", "stopPending", "clearWorkspace", "close"])
def test_removing_or_stopping_work_cancels_queued_analysis(action):
    analyzer = RecordingAnalyzer()
    controller, pool = make_controller(analyzer)
    controller._start_analysis("task-1")
    event = controller._cancellation_events["task-1"]
    getattr(controller, action)(*( ["task-1"] if action == "ignoreTask" else []))
    assert event.is_set()
    pool.run(0)
    assert analyzer.calls == []
    assert "task-1" not in controller._cancellation_events
    if action == "clearWorkspace":
        assert controller.totalCount == 0
    elif action != "close":
        expected = "ignored" if action == "ignoreTask" else "cancelled"
        assert controller.task_snapshot("task-1")["status"] == expected
    controller.close()


@pytest.mark.parametrize("action", ["cancelTask", "ignoreTask", "stopPending", "clearWorkspace"])
def test_failed_workspace_write_preserves_current_attempt(monkeypatch, action):
    analyzer = RecordingAnalyzer()
    controller, pool = make_controller(analyzer)
    controller._start_analysis("task-1")
    event = controller._cancellation_events["task-1"]
    original = controller.task_snapshot("task-1")

    def fail_save(*_args, **_kwargs):
        raise OSError("injected workspace write failure")

    with monkeypatch.context() as patch:
        patch.setattr(controller, "_save_workspace", fail_save)
        with pytest.raises(OSError, match="injected"):
            getattr(controller, action)(*( ["task-1"] if action in {"cancelTask", "ignoreTask"} else []))
    assert controller.task_snapshot("task-1") == original
    assert controller._cancellation_events.get("task-1") is event
    assert not event.is_set()
    pool.run(0)
    assert controller.task_snapshot("task-1")["suggestedName"] == "result-1.txt"
    controller.close()


@pytest.mark.parametrize("background", [False, True], ids=["sync", "background"])
def test_normal_analysis_keeps_import_choices_and_completes(background):
    analyzer = RecordingAnalyzer()
    controller, pool = make_controller(analyzer, background=background)
    controller._start_analysis("task-1")
    controller.setNamingMode("smart")
    controller.setNamingLanguage("en")
    if background:
        pool.run(0)
    task = controller.task_snapshot("task-1")
    assert task["status"] == "review_pending"
    assert task["suggestedName"] == "result-1.txt"
    kwargs = analyzer.calls[0][2]
    assert kwargs["template_id"] == "original-template"
    assert kwargs["output_language"] == "zh-HK"
    assert kwargs["naming_mode"] == "template"
    assert not kwargs["cancellation_token"]()
    assert "task-1" not in controller._cancellation_events
    controller.close()


def test_close_does_not_allow_new_analysis_to_be_submitted():
    analyzer = RecordingAnalyzer()
    controller, pool = make_controller(analyzer)
    controller._start_analysis("task-1")
    controller.cancelTask("task-1")
    controller.close()
    controller.retryTask("task-1")
    assert len(pool.jobs) == 1
    pool.run(0)
    assert analyzer.calls == []

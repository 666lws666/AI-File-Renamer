"""M2 Task 1: FileTask state machine tests."""
import pytest
from src.core.file_task import FileTask, FileTaskState, InvalidStateTransitionError, DISPLAY_MAP

@pytest.fixture
def base_task():
    return FileTask("t1", "/tmp/test.pdf", "report", ".pdf", 1024, 1000000)

def test_initial_pending(base_task):
    assert base_task.state == FileTaskState.PENDING

def test_valid_transition_pending_to_extracting(base_task):
    t = base_task.transition(FileTaskState.EXTRACTING)
    assert t.state == FileTaskState.EXTRACTING

def test_invalid_pending_to_applied(base_task):
    with pytest.raises(InvalidStateTransitionError):
        base_task.transition(FileTaskState.APPLIED)

def test_invalid_pending_to_undone(base_task):
    with pytest.raises(InvalidStateTransitionError):
        base_task.transition(FileTaskState.UNDONE)

def test_applied_to_undone(base_task):
    t = base_task.transition(FileTaskState.EXTRACTING).transition(FileTaskState.EXTRACTED).transition(FileTaskState.SUGGESTING).transition(FileTaskState.SUGGESTED).transition(FileTaskState.APPLIED)
    u = t.transition(FileTaskState.UNDONE)
    assert u.state == FileTaskState.UNDONE

def test_undone_to_pending(base_task):
    t = base_task.transition(FileTaskState.EXTRACTING).transition(FileTaskState.EXTRACTED).transition(FileTaskState.SUGGESTING).transition(FileTaskState.SUGGESTED).transition(FileTaskState.APPLIED).transition(FileTaskState.UNDONE)
    p = t.transition(FileTaskState.PENDING)
    assert p.state == FileTaskState.PENDING

def test_failed_to_retry(base_task):
    t = base_task.transition(FileTaskState.EXTRACTING).transition(FileTaskState.FAILED)
    assert t.state == FileTaskState.FAILED
    r = t.transition(FileTaskState.PENDING)
    assert r.state == FileTaskState.PENDING

def test_cancelled_to_retry(base_task):
    t = base_task.transition(FileTaskState.CANCELLED)
    assert t.state == FileTaskState.CANCELLED
    r = t.transition(FileTaskState.PENDING)
    assert r.state == FileTaskState.PENDING

def test_failed_cannot_apply(base_task):
    t = base_task.transition(FileTaskState.EXTRACTING).transition(FileTaskState.FAILED)
    with pytest.raises(InvalidStateTransitionError):
        t.transition(FileTaskState.APPLIED)

def test_ignored_to_pending(base_task):
    t = base_task.transition(FileTaskState.IGNORED)
    assert t.state == FileTaskState.IGNORED
    r = t.transition(FileTaskState.PENDING)
    assert r.state == FileTaskState.PENDING

def test_immutability(base_task):
    t = base_task.transition(FileTaskState.EXTRACTING)
    assert base_task.state == FileTaskState.PENDING  # original unchanged

def test_display_state_mapping():
    assert FileTask("t","/x","a",".pdf",0,0,FileTaskState.PENDING).display_state == "pending"
    assert FileTask("t","/x","a",".pdf",0,0,FileTaskState.EXTRACTING).display_state == "analyzing"
    assert FileTask("t","/x","a",".pdf",0,0,FileTaskState.EXTRACTED).display_state == "analyzing"
    assert FileTask("t","/x","a",".pdf",0,0,FileTaskState.SUGGESTING).display_state == "analyzing"
    assert FileTask("t","/x","a",".pdf",0,0,FileTaskState.SUGGESTED).display_state == "review_pending"
    assert FileTask("t","/x","a",".pdf",0,0,FileTaskState.APPLIED).display_state == "applied"
    assert FileTask("t","/x","a",".pdf",0,0,FileTaskState.FAILED).display_state == "failed"
    assert FileTask("t","/x","a",".pdf",0,0,FileTaskState.CANCELLED).display_state == "cancelled"
    assert FileTask("t","/x","a",".pdf",0,0,FileTaskState.IGNORED).display_state == "ignored"
    assert FileTask("t","/x","a",".pdf",0,0,FileTaskState.UNDONE).display_state == "undone"

"""Ordered retention tests for exact invocation owners; no native calls."""
from types import SimpleNamespace
import pytest

from src.services.local_ai.native.process import ProcessCleanupResult, ProcessOwnershipInterrupted


def api():
    from src.services.local_ai.inference_owner import InvocationOwner
    return InvocationOwner


class Step:
    def __init__(self, name, log, failure=None):
        self.name, self.log, self.failure = name, log, failure

    def call(self):
        self.log.append(self.name)
        if self.failure is not None:
            failure, self.failure = self.failure, None
            raise failure

    def close(self):
        self.call()

    def retry_reap(self, *, deadline):
        self.call()
        return ProcessCleanupResult(True, True)

    def cleanup(self, *, child_cleanup_confirmed):
        assert child_cleanup_confirmed is True
        self.call()
        return SimpleNamespace(complete=True)

    def __exit__(self, *args):
        self.call()

    def complete(self, run_id):
        assert run_id == "a" * 32
        self.call()


ORDER = ["process", "security", "stage", "exemption", "profile", "resources", "journal"]


def owned(failure_at=None, failure=None):
    log = []
    owner = api()(_clock=lambda: 10.0)
    for name in ORDER:
        step = Step(name, log, failure if name == failure_at else None)
        if name == "resources":
            owner.resource_context = step
        else:
            setattr(owner, name, step)
    owner.child_cleanup_confirmed = False
    owner.run_id = "a" * 32
    return owner, log


@pytest.mark.parametrize("failed", ORDER[:5])
def test_failed_cleanup_stops_before_dependents_then_resumes_exact_cursor(failed):
    owner, log = owned(failed, RuntimeError("private error"))
    result = owner.cleanup(deadline=20)
    assert not result.complete and result.error == "CLEANUP_PENDING"
    prefix = ORDER[:ORDER.index(failed) + 1]
    assert log == prefix
    assert owner.cleanup(deadline=20).complete
    assert log == prefix + ORDER[ORDER.index(failed):]
    assert owner.cleanup(deadline=20).complete
    assert log == prefix + ORDER[ORDER.index(failed):]


@pytest.mark.parametrize("failed", ["resources", "journal"])
def test_terminal_context_or_journal_failure_is_not_relabelled_success(failed):
    owner, log = owned(failed, RuntimeError("private error"))
    assert owner.cleanup(deadline=20).error == "RECOVERY_REQUIRED"
    first = list(log)
    assert owner.cleanup(deadline=20).error == "RECOVERY_REQUIRED"
    assert log == first
    assert "private error" not in repr(owner)


def test_expired_cleanup_deadline_changes_nothing():
    owner, log = owned()
    assert not owner.cleanup(deadline=10).complete
    assert log == []


def test_tree_exit_and_handles_closed_are_both_required_before_security_release():
    owner, log = owned()
    for result in (ProcessCleanupResult(False, True), ProcessCleanupResult(True, False)):
        owner.process = SimpleNamespace(retry_reap=lambda **kw: result)
        assert not owner.cleanup(deadline=20).complete
        assert log == []
    owner.process = Step("process", log)
    assert owner.cleanup(deadline=20).complete
    assert log == ORDER


def test_unexpected_runner_escape_never_guesses_tree_exit():
    owner, log = owned()
    owner.process = None
    assert owner.cleanup(deadline=20).error == "RECOVERY_REQUIRED"
    assert log == []


def test_baseexception_preserves_exact_failing_step_and_rethrows():
    owner, log = owned("security", KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        owner.cleanup(deadline=20)
    assert log == ["process", "security"]
    assert owner.security is not None
    assert owner.cleanup(deadline=20).complete
    assert log == ["process", "security", *ORDER[1:]]


def test_process_interruption_adopts_returned_owner_before_rethrow():
    owner, log = owned()
    replacement = Step("replacement", log)
    owner.process = Step("interrupted", log, ProcessOwnershipInterrupted(replacement, "keyboard_interrupt"))
    with pytest.raises(ProcessOwnershipInterrupted):
        owner.cleanup(deadline=20)
    assert owner.process is replacement
    assert owner.cleanup(deadline=20).complete
    assert log == ["interrupted", "replacement", *ORDER[1:]]


def test_unacquired_objects_are_not_closed_and_no_profile_name_is_adopted():
    log = []
    owner = api()(_clock=lambda: 10)
    owner.profile = Step("prepared-not-created", log)
    assert owner.cleanup(deadline=20).complete
    assert log == ["prepared-not-created"]


@pytest.mark.parametrize("deadline", [True, float("inf"), float("nan"), 10**1000])
def test_invalid_cleanup_deadline_is_fixed_and_does_not_release(deadline):
    owner, log = owned()
    with pytest.raises(ValueError, match="^INVALID_DEADLINE$"):
        owner.cleanup(deadline=deadline)
    assert not log

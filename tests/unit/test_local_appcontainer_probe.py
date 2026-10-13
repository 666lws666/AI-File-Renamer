import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.local_probe_hello import CANONICAL_HELLO_LINE
from scripts.local_probe_process import ProcessResult
from scripts.local_probe_security import TokenEvidence


@pytest.fixture(autouse=True)
def fixed_localappdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def result(*, token=None, stdout=CANONICAL_HELLO_LINE, status="completed", exit_code=0,
           cleanup=True):
    return ProcessResult(status, exit_code, stdout, b"", 123, cleanup, .1,
                         token_evidence=token)


class Fixture:
    def __init__(self, tmp_path):
        self.calls = []
        self.hello_cwds = []
        self.root = tmp_path
        self.sid = "S-1-15-2-1-2-3-4-5-6-7"
        self.ordinary = result()
        self.contained = result(token=TokenEvidence(self.sid, True, 0))
        self.fail_at = None
        self.owner = SimpleNamespace(evidence=SimpleNamespace(directory_path=str(tmp_path / "stage"),
              executable_path=str(tmp_path / "stage" / "hello.exe")),
              recheck=self.recheck, cleanup=self.cleanup)
        self.profile = SimpleNamespace(prepare=self.prepare, __enter__=self.enter,
                                       close=self.profile_close)
        self.security = SimpleNamespace(__enter__=self.security_enter,
                                        close=self.security_close)

    def mark(self, name):
        self.calls.append(name)
        if self.fail_at == name:
            raise RuntimeError(name)

    def prepare(self):
        self.mark("prepare")
        return SimpleNamespace(sid=self.sid)

    def enter(self):
        self.mark("profile_enter")
        return self.profile

    def profile_close(self):
        self.mark("profile_close")

    def security_enter(self):
        self.mark("security_enter")
        return self.security

    def security_close(self):
        self.mark("security_close")

    def recheck(self):
        self.mark("recheck")
        return self.owner.evidence

    def cleanup(self, *, child_cleanup_confirmed):
        self.mark("stage_cleanup")
        assert child_cleanup_confirmed is True
        return SimpleNamespace(complete=True, remaining_paths=(), uncertain_paths=(), failures=())

    def stage(self, *args):
        self.mark("stage")
        return self.owner

    def run(self, exe, args, **kwargs):
        self.mark("compile" if Path(exe).name == "csc.exe" else
                  "contained" if kwargs.get("security_context") else "ordinary")
        if Path(exe).name == "csc.exe":
            (Path(kwargs["cwd"]) / "hello.exe").write_bytes(b"MZprobe")
            return result(stdout=b"")
        self.hello_cwds.append(Path(kwargs["cwd"]))
        return self.contained if kwargs.get("security_context") else self.ordinary


def test_exact_sequence_and_completed_journal(tmp_path):
    from scripts import local_appcontainer_probe as probe
    f = Fixture(tmp_path)
    outcome = probe.run_diagnostic(probe.Dependencies(f.run, lambda name: f.profile,
                 f.stage, lambda sid: f.security), root=tmp_path,
                 source_bytes=b"source", compiler_bytes=b"compiler")
    assert outcome.ok
    assert f.calls == ["compile", "prepare", "stage", "recheck", "ordinary",
                       "profile_enter", "security_enter", "recheck", "contained",
                       "security_close", "stage_cleanup", "profile_close"]
    journal = json.loads(Path(outcome.journal).read_text())
    assert journal["state"] == "completed" and journal["outcome"] == "passed"
    assert journal["token_evidence"] == {"package_sid": f.sid,
                                           "is_appcontainer": True, "capability_count": 0}
    assert f.hello_cwds == [Path(f.owner.evidence.directory_path)] * 2


def test_only_contained_environment_receives_validated_localappdata(tmp_path):
    from scripts import local_appcontainer_probe as probe
    f = Fixture(tmp_path)
    environments = {}
    original_run = f.run
    def capture(exe, args, **kwargs):
        label = "compile" if Path(exe).name == "csc.exe" else (
            "contained" if kwargs.get("security_context") else "ordinary")
        environments[label] = kwargs["environment"].copy()
        return original_run(exe, args, **kwargs)
    outcome = probe.run_diagnostic(probe.Dependencies(capture, lambda name: f.profile,
                 f.stage, lambda sid: f.security), root=tmp_path,
                 source_bytes=b"source", compiler_bytes=b"compiler")
    assert outcome.ok
    assert "LOCALAPPDATA" not in environments["compile"]
    assert "LOCALAPPDATA" not in environments["ordinary"]
    assert environments["contained"]["LOCALAPPDATA"] == str(tmp_path)


@pytest.mark.parametrize("bad", [None, "", "relative", "\\\\server\\share", "C:\\missing\\path"])
def test_contained_environment_rejects_invalid_localappdata(tmp_path, monkeypatch, bad):
    from scripts import local_appcontainer_probe as probe
    if bad is None:
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
    else:
        monkeypatch.setenv("LOCALAPPDATA", bad)
    with pytest.raises(ValueError):
        probe._environment(tmp_path, contained=True)
    assert "LOCALAPPDATA" not in probe._environment(tmp_path)


def test_contained_environment_rejects_embedded_nul(tmp_path, monkeypatch):
    from scripts import local_appcontainer_probe as probe
    monkeypatch.setattr(probe.os, "environ", {"SystemRoot": r"C:\Windows",
                                            "LOCALAPPDATA": "C:\\bad\x00path"})
    with pytest.raises(ValueError):
        probe._environment(tmp_path, contained=True)


def test_missing_localappdata_fails_before_launch_and_cleans_confirmed_objects(tmp_path, monkeypatch):
    from scripts import local_appcontainer_probe as probe
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    f = Fixture(tmp_path)
    outcome = probe.run_diagnostic(probe.Dependencies(f.run, lambda name: f.profile,
                 f.stage, lambda sid: f.security), root=tmp_path,
                 source_bytes=b"source", compiler_bytes=b"compiler")
    assert not outcome.ok and outcome.error_stage == "localappdata"
    assert "contained" not in f.calls
    assert outcome.state == "completed"
    assert f.calls[-3:] == ["security_close", "stage_cleanup", "profile_close"]


def test_launch_failure_preserves_stage_and_numeric_error(tmp_path):
    from scripts import local_appcontainer_probe as probe
    f = Fixture(tmp_path)
    f.contained = ProcessResult("launch_error", None, b"", b"", None, True,
                                .1, win32_error=203, error_stage="create")
    outcome = probe.run_diagnostic(probe.Dependencies(f.run, lambda name: f.profile,
                 f.stage, lambda sid: f.security), root=tmp_path,
                 source_bytes=b"source", compiler_bytes=b"compiler")
    assert not outcome.ok and outcome.state == "completed"
    assert outcome.error_stage == "contained_launch" and outcome.error_code == 203
    journal = json.loads(Path(outcome.journal).read_text())
    assert journal["error"] == {"stage": "contained_launch", "code": 203}
    assert journal["process"]["contained"]["error_stage"] == "create"
    assert journal["process"]["contained"]["win32_error"] == 203


def test_incomplete_child_keeps_live_ownership(tmp_path):
    from scripts import local_appcontainer_probe as probe
    f = Fixture(tmp_path)
    f.contained = result(cleanup=False)
    outcome = probe.run_diagnostic(probe.Dependencies(f.run, lambda name: f.profile,
                 f.stage, lambda sid: f.security), root=tmp_path,
                 source_bytes=b"source", compiler_bytes=b"compiler")
    assert not outcome.ok and outcome.state == "cleanup_pending"
    assert "stage_cleanup" not in f.calls and "profile_close" not in f.calls
    assert outcome.retained_owner is f.owner and outcome.retained_profile is f.profile


def test_reject_arguments_before_effects():
    from scripts import local_appcontainer_probe as probe
    assert probe.main(["--sid", "x"]) != 0


@pytest.mark.parametrize("failure", ["compile", "prepare", "stage", "ordinary",
                                      "profile_enter", "security_enter", "contained"])
def test_failures_never_claim_success(tmp_path, failure):
    from scripts import local_appcontainer_probe as probe
    f = Fixture(tmp_path)
    f.fail_at = failure
    outcome = probe.run_diagnostic(probe.Dependencies(f.run, lambda name: f.profile,
                 f.stage, lambda sid: f.security), root=tmp_path,
                 source_bytes=b"source", compiler_bytes=b"compiler")
    assert not outcome.ok
    if failure in {"compile", "prepare", "stage", "ordinary"}:
        assert "profile_enter" not in f.calls
    if failure in {"ordinary", "contained"}:
        assert outcome.state == "cleanup_pending"
        assert "stage_cleanup" not in f.calls and "profile_close" not in f.calls


@pytest.mark.parametrize("token", [TokenEvidence("S-1-15-2-9-2-3-4-5-6-7", True, 0),
                                    TokenEvidence("S-1-15-2-1-2-3-4-5-6-7", False, 0),
                                    TokenEvidence("S-1-15-2-1-2-3-4-5-6-7", True, True),
                                    TokenEvidence("S-1-15-2-1-2-3-4-5-6-7", True, 1)])
def test_bad_parent_token_evidence_fails_after_cleanup(tmp_path, token):
    from scripts import local_appcontainer_probe as probe
    f = Fixture(tmp_path)
    f.contained = result(token=token)
    outcome = probe.run_diagnostic(probe.Dependencies(f.run, lambda name: f.profile,
                 f.stage, lambda sid: f.security), root=tmp_path,
                 source_bytes=b"source", compiler_bytes=b"compiler")
    assert not outcome.ok and outcome.state == "completed"
    assert f.calls[-3:] == ["security_close", "stage_cleanup", "profile_close"]
    assert json.loads(Path(outcome.journal).read_text())["outcome"] == "failed"


@pytest.mark.parametrize("bad", [b"bad", CANONICAL_HELLO_LINE + b"x", b""])
def test_malformed_contained_hello_fails(tmp_path, bad):
    from scripts import local_appcontainer_probe as probe
    f = Fixture(tmp_path)
    f.contained = result(stdout=bad)
    outcome = probe.run_diagnostic(probe.Dependencies(f.run, lambda name: f.profile,
                 f.stage, lambda sid: f.security), root=tmp_path,
                 source_bytes=b"source", compiler_bytes=b"compiler")
    assert not outcome.ok and outcome.state == "completed"


def test_atomic_journal_keeps_old_snapshot_when_replace_fails(tmp_path, monkeypatch):
    from scripts import local_appcontainer_probe as probe
    path = tmp_path / "journal.json"
    path.write_bytes(b"old")
    seen = []
    original_fsync = probe.os.fsync

    def fsync(fd):
        seen.append("fsync")
        original_fsync(fd)

    def replace(src, dst):
        seen.append("replace")
        assert Path(src).read_bytes() == b"new"
        raise OSError("injected")

    monkeypatch.setattr(probe.os, "fsync", fsync)
    monkeypatch.setattr(probe.os, "replace", replace)
    with pytest.raises(OSError):
        probe._atomic_write(path, b"new")
    assert seen == ["fsync", "replace"]
    assert path.read_bytes() == b"old"


def test_collision_is_not_owned_or_deleted(tmp_path):
    from scripts import local_appcontainer_probe as probe
    from scripts.local_probe_profile import ProfileError
    f = Fixture(tmp_path)
    def collision():
        f.calls.append("profile_enter")
        raise ProfileError("profile_create", probe.COLLISION)
    f.profile.__enter__ = collision
    outcome = probe.run_diagnostic(probe.Dependencies(f.run, lambda name: f.profile,
                 f.stage, lambda sid: f.security), root=tmp_path,
                 source_bytes=b"source", compiler_bytes=b"compiler")
    assert outcome.state == "collision" and not outcome.ok
    assert "stage_cleanup" in f.calls and "profile_close" not in f.calls
    assert json.loads(Path(outcome.journal).read_text())["state"] == "collision"


@pytest.mark.parametrize("failing_write", [1, 3])
def test_journal_failure_never_creates_or_claims_success(tmp_path, failing_write):
    from scripts import local_appcontainer_probe as probe
    f = Fixture(tmp_path)
    calls = []
    def write(path, doc):
        calls.append(doc["state"])
        if len(calls) == failing_write:
            raise OSError("injected")
        probe._write_journal(path, doc)
    outcome = probe.run_diagnostic(probe.Dependencies(f.run, lambda name: f.profile,
                 f.stage, lambda sid: f.security, write), root=tmp_path,
                 source_bytes=b"source", compiler_bytes=b"compiler")
    assert not outcome.ok
    assert "stage_cleanup" in f.calls
    if failing_write == 1:
        assert "profile_enter" not in f.calls
    else:
        assert "profile_enter" in f.calls and "profile_close" in f.calls


@pytest.mark.parametrize("failure", ["security_close", "stage_cleanup", "profile_close"])
def test_cleanup_failure_is_pending_and_retains_owner(tmp_path, failure):
    from scripts import local_appcontainer_probe as probe
    f = Fixture(tmp_path)
    f.fail_at = failure
    outcome = probe.run_diagnostic(probe.Dependencies(f.run, lambda name: f.profile,
                 f.stage, lambda sid: f.security), root=tmp_path,
                 source_bytes=b"source", compiler_bytes=b"compiler")
    assert not outcome.ok and outcome.state == "cleanup_pending"
    assert outcome.retained_owner is f.owner


@pytest.mark.parametrize("which", ["ordinary", "contained"])
@pytest.mark.parametrize("bad", [result(exit_code=1), result(status="output_limit"),
                                    result(stdout=b"x" * 1025)])
def test_bad_child_result_fails_without_claiming_hello(tmp_path, which, bad):
    from scripts import local_appcontainer_probe as probe
    f = Fixture(tmp_path)
    if which == "ordinary":
        f.ordinary = bad
    else:
        f.contained = bad
    outcome = probe.run_diagnostic(probe.Dependencies(f.run, lambda name: f.profile,
                 f.stage, lambda sid: f.security), root=tmp_path,
                 source_bytes=b"source", compiler_bytes=b"compiler")
    assert not outcome.ok
    assert "stage_cleanup" in f.calls and "profile_close" in f.calls if which == "contained" else "stage_cleanup" in f.calls


def test_compiler_nonzero_stops_before_profile(tmp_path):
    from scripts import local_appcontainer_probe as probe
    f = Fixture(tmp_path)
    def fail_compile(exe, args, **kwargs):
        f.calls.append("compile")
        return result(stdout=b"compiler failure", exit_code=1)
    outcome = probe.run_diagnostic(probe.Dependencies(fail_compile, lambda name: f.profile,
                 f.stage, lambda sid: f.security), root=tmp_path,
                 source_bytes=b"source", compiler_bytes=b"compiler")
    assert not outcome.ok and f.calls == ["compile"]
    assert (Path(outcome.run) / "compile.stdout").read_bytes() == b"compiler failure"


def test_compiler_exception_has_unconfirmed_cleanup(tmp_path):
    from scripts import local_appcontainer_probe as probe
    f = Fixture(tmp_path)
    f.fail_at = "compile"
    outcome = probe.run_diagnostic(probe.Dependencies(f.run, lambda name: f.profile,
                 f.stage, lambda sid: f.security), root=tmp_path,
                 source_bytes=b"source", compiler_bytes=b"compiler")
    assert not outcome.ok and outcome.state == "cleanup_pending"
    assert f.calls == ["compile"]


def test_compiler_returned_incomplete_cleanup_stops_before_profile(tmp_path):
    from scripts import local_appcontainer_probe as probe
    f = Fixture(tmp_path)
    def incomplete(exe, args, **kwargs):
        f.calls.append("compile")
        return result(stdout=b"", cleanup=False)
    outcome = probe.run_diagnostic(probe.Dependencies(incomplete, lambda name: f.profile,
                 f.stage, lambda sid: f.security), root=tmp_path,
                 source_bytes=b"source", compiler_bytes=b"compiler")
    assert not outcome.ok and outcome.state == "cleanup_pending"
    assert f.calls == ["compile"]


@pytest.mark.parametrize("close_fails", [False, True])
def test_prepare_release_failure_explicitly_closes_live_helper(tmp_path, close_fails):
    from scripts import local_appcontainer_probe as probe
    from scripts.local_probe_profile import ProfileError
    f = Fixture(tmp_path)
    def prepare_error():
        f.calls.append("prepare")
        raise ProfileError("sid_free", 5)
    def close():
        f.calls.append("profile_close")
        if close_fails:
            raise ProfileError("sid_free", 5)
    f.profile.prepare = prepare_error
    f.profile.close = close
    outcome = probe.run_diagnostic(probe.Dependencies(f.run, lambda name: f.profile,
                 f.stage, lambda sid: f.security), root=tmp_path,
                 source_bytes=b"source", compiler_bytes=b"compiler")
    assert not outcome.ok
    assert "stage" not in f.calls and "profile_enter" not in f.calls
    assert "profile_close" in f.calls
    if close_fails:
        assert outcome.state == "cleanup_pending" and outcome.retained_profile is f.profile


def test_final_journal_failure_is_nonzero(tmp_path):
    from scripts import local_appcontainer_probe as probe
    f = Fixture(tmp_path)
    def write(path, doc):
        if doc["state"] == "completed":
            raise OSError("injected")
        probe._write_journal(path, doc)
    outcome = probe.run_diagnostic(probe.Dependencies(f.run, lambda name: f.profile,
                 f.stage, lambda sid: f.security, write), root=tmp_path,
                 source_bytes=b"source", compiler_bytes=b"compiler")
    assert not outcome.ok and outcome.error_stage == "journal_write"
    assert f.calls[-3:] == ["security_close", "stage_cleanup", "profile_close"]


def test_post_create_entry_error_retries_live_profile_close(tmp_path):
    from scripts import local_appcontainer_probe as probe
    from scripts.local_probe_profile import ProfileError
    f = Fixture(tmp_path)
    def entry_error():
        f.calls.append("profile_enter")
        raise ProfileError("profile_delete", 5)
    f.profile.__enter__ = entry_error
    outcome = probe.run_diagnostic(probe.Dependencies(f.run, lambda name: f.profile,
                 f.stage, lambda sid: f.security), root=tmp_path,
                 source_bytes=b"source", compiler_bytes=b"compiler")
    assert not outcome.ok
    assert "profile_close" in f.calls

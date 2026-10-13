"""Access orchestration uses synthetic process facts and fake owned boundaries only."""
import json
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.local_probe_process import ProcessResult
from scripts.local_probe_security import TokenEvidence
from tests.unit.test_local_probe_access import record, SID
from tests.unit.test_local_appcontainer_probe import Fixture


def access_result(mode, *, token=None, data=None):
    wire = json.dumps(data or record(mode), separators=(",", ":")).encode() + b"\r\n"
    return ProcessResult("completed", 0, wire, b"", 123, True, .1, token_evidence=token)


class AccessFixture(Fixture):
    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.ordinary = access_result("ordinary")
        self.contained = access_result("contained", token=TokenEvidence(SID, True, 0))
        self.args = {}
        self.cleanup_report = None
        self.fixture_paths = (str(tmp_path / "stage" / "allowed.txt"),
                              str(tmp_path / "stage" / "denied.txt"))
        fixtures = tuple(SimpleNamespace(filename=name, path=path, sha256=sha256(name.encode()).hexdigest(),
                                         size=len(name)) for name, path in
                         zip(("allowed.txt", "denied.txt"), self.fixture_paths))
        self.owner.evidence.fixtures = fixtures
        self.listener = SimpleNamespace(port=49152, verify_control=self.verify_control,
                                        close=self.listener_close)
        self.exemption = SimpleNamespace(query=self.query, require_not_exempt=self.not_exempt,
                                         close=self.exemption_close)

    def stage(self, *args, **kwargs):
        assert kwargs == {"include_fixtures": True}
        return super().stage(*args)

    def cleanup(self, *, child_cleanup_confirmed):
        self.mark("stage_cleanup")
        assert child_cleanup_confirmed is True
        return self.cleanup_report or SimpleNamespace(
            complete=True, handles_closed=True, remaining_paths=(),
            uncertain_paths=(), failures=())

    def run(self, exe, args, **kwargs):
        label = "compile" if Path(exe).name == "csc.exe" else (
            "contained" if kwargs.get("security_context") else "ordinary")
        self.args[label] = args
        if label == "compile":
            (Path(kwargs["cwd"]) / "access.exe").write_bytes(b"MZprobe")
            self.calls.append("compile")
            return ProcessResult("completed", 0, b"", b"", 123, True, .1)
        self.calls.append(label)
        return self.contained if label == "contained" else self.ordinary

    def query(self):
        self.mark("exemption_query")
        return SimpleNamespace(package_sid=SID, exempt=False, count=0, cleanup_complete=True)
    def not_exempt(self):
        self.mark("not_exempt")
        return SimpleNamespace(package_sid=SID, exempt=False, count=0, cleanup_complete=True)
    def exemption_close(self): self.mark("exemption_close")
    def verify_control(self):
        self.mark("verify_control")
        return SimpleNamespace(byte_count=26, sha256=sha256(b"xuxia-loopback-control-v1\n").hexdigest())
    def listener_close(self): self.mark("listener_close")


def run_access(f):
    from scripts import local_appcontainer_probe as probe
    return probe.run_diagnostic(probe.Dependencies(
        f.run, lambda name: f.profile, f.stage, lambda sid: f.security,
        exemption=lambda sid: f.exemption, listener=lambda: f.listener),
        root=f.root, probe_kind="access", source_bytes=b"source",
        compiler_bytes=b"compiler", framework_bytes=b"framework")


def test_access_uses_fixed_compiler_stage_argv_and_typed_evidence(tmp_path):
    f = AccessFixture(tmp_path)
    outcome = run_access(f)
    assert outcome.ok
    assert f.args["ordinary"] == ["ordinary", *f.fixture_paths, "49152"]
    assert f.args["contained"] == ["contained", *f.fixture_paths, "49152"]
    assert "/reference:C:\\Windows\\Microsoft.NET\\Framework64\\v4.0.30319\\System.dll" in f.args["compile"]
    assert f.calls.index("not_exempt") < f.calls.index("ordinary")
    assert f.calls.index("verify_control") < f.calls.index("profile_enter")
    doc = json.loads(Path(outcome.journal).read_text())
    assert doc["sha256"]["framework"] == sha256(b"framework").hexdigest()
    assert doc["fixtures"][0]["path"] == f.fixture_paths[0]
    assert doc["measurements"]["contained"]["file_denied"]["open_error"] == 5
    assert doc["stage_cleanup"] == {"complete": True, "handles_closed": True,
                                    "remaining_paths": [], "uncertain_paths": [], "failures": []}
    assert doc["limitations"][-1] == "model_isolation_unverified"


def test_failed_positive_control_prevents_profile_entry(tmp_path):
    f = AccessFixture(tmp_path)
    def fail(): raise RuntimeError("fake listener failure")
    f.listener.verify_control = fail
    outcome = run_access(f)
    assert not outcome.ok and "profile_enter" not in f.calls


def test_unknown_kind_is_rejected_before_run_directory_or_dependencies(tmp_path):
    from scripts import local_appcontainer_probe as probe
    f = AccessFixture(tmp_path)
    with pytest.raises(ValueError, match="probe_kind"):
        probe.run_diagnostic(probe.Dependencies(f.run), root=tmp_path / "not-created",
                             probe_kind="ACCESS")
    assert not (tmp_path / "not-created").exists() and not f.calls


def test_exemption_failure_aborts_before_listener_and_child(tmp_path):
    from scripts.local_probe_exemptions import ExemptionError
    f = AccessFixture(tmp_path)
    def fail(): raise ExemptionError("query", 5)
    f.exemption.query = fail
    outcome = run_access(f)
    assert not outcome.ok and outcome.error_stage == "query" and outcome.error_code == 5
    assert "ordinary" not in f.calls and "profile_enter" not in f.calls
    assert "listener_close" not in f.calls and "exemption_close" in f.calls


def test_failed_exemption_close_retains_live_owner(tmp_path):
    from scripts.local_probe_exemptions import ExemptionError
    f = AccessFixture(tmp_path)
    def fail(): raise ExemptionError("query", 5)
    f.exemption.close = fail
    outcome = run_access(f)
    assert not outcome.ok and outcome.state == "cleanup_pending"
    assert outcome.retained_exemption is f.exemption


def test_wrong_contained_token_fails_after_supervised_cleanup(tmp_path):
    f = AccessFixture(tmp_path)
    f.contained = access_result("contained", token=TokenEvidence("wrong", True, 0))
    outcome = run_access(f)
    assert not outcome.ok and outcome.error_stage == "token_evidence"
    assert "stage_cleanup" in f.calls
    assert json.loads(Path(outcome.journal).read_text())["token_evidence"] is None


def test_incomplete_stage_report_is_persisted_before_pending_failure(tmp_path):
    f = AccessFixture(tmp_path)
    f.cleanup_report = SimpleNamespace(complete=False, handles_closed=False,
                                       remaining_paths=(f.fixture_paths[1],),
                                       uncertain_paths=(f.fixture_paths[1],),
                                       failures=("fixture_close",))
    outcome = run_access(f)
    assert not outcome.ok and outcome.state == "cleanup_pending"
    assert outcome.retained_owner is f.owner and outcome.retained_profile is f.profile
    doc = json.loads(Path(outcome.journal).read_text())
    assert doc["stage_cleanup"] == {
        "complete": False, "handles_closed": False,
        "remaining_paths": [f.fixture_paths[1]],
        "uncertain_paths": [f.fixture_paths[1]], "failures": ["fixture_close"]}
    assert doc["outcome"] == "failed" and doc["state"] == "cleanup_pending"


def test_checked_parent_token_survives_invalid_contained_measurement(tmp_path):
    f = AccessFixture(tmp_path)
    data = record("contained")
    data["external"]["connect_error"] = 10061
    f.contained = access_result("contained", token=TokenEvidence(SID, True, 0), data=data)
    outcome = run_access(f)
    assert not outcome.ok and outcome.error_stage == "contained_access"
    doc = json.loads(Path(outcome.journal).read_text())
    assert doc["token_evidence"] == {"package_sid": SID, "is_appcontainer": True,
                                      "capability_count": 0}
    assert Path(doc["streams"]["contained"]["stdout"]).read_bytes() == f.contained.stdout
    assert doc["outcome"] == "failed" and "contained" not in doc["measurements"]


def test_cli_rejects_unknown_args_without_run(monkeypatch):
    from scripts import local_appcontainer_probe as probe
    monkeypatch.setattr(probe, "run_diagnostic", lambda **kwargs: (_ for _ in ()).throw(AssertionError("run")))
    assert probe.main(["--access", "extra"]) == 2


@pytest.mark.parametrize("bad", [10061, 10060, 0, 2])
def test_contained_denial_alternatives_never_pass(tmp_path, bad):
    f = AccessFixture(tmp_path)
    data = record("contained")
    data["external"]["connect_error"] = bad
    f.contained = access_result("contained", token=TokenEvidence(SID, True, 0), data=data)
    assert not run_access(f).ok

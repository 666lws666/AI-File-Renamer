"""Lifecycle checks for the contained, synthetic Qwen compatibility diagnostic."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_contained_inference_probe as contained
from scripts.local_model_stage import StageMember
from scripts.local_probe_process import ProcessResult
from scripts.local_probe_stage import StageError


def test_public_runner_has_no_arbitrary_paths():
    import inspect
    assert list(inspect.signature(contained.run_contained_case).parameters) == [
        "case_id", "locale", "quality", "timeout_seconds", "cancellation_event"
    ]


def test_cli_rejects_arbitrary_resource_path():
    with pytest.raises(SystemExit) as caught:
        contained.main(["--case", "case_01", "--locale", "en-US", "--model", "x"])
    assert caught.value.code == 2


@pytest.fixture
def lifecycle(tmp_path, monkeypatch):
    calls = []
    output = tmp_path / "prepared"
    output.mkdir()
    for name in ("prompt.txt", "schema.json"):
        (output / name).write_text("{}", encoding="utf-8")
    resources = {"runtime_dir": tmp_path / "runtime",
                 "completion": tmp_path / "runtime" / "llama-completion.exe",
                 "mtmd": tmp_path / "runtime" / "llama-mtmd-cli.exe",
                 "model": tmp_path / "model.gguf", "projector": tmp_path / "projector.gguf"}
    monkeypatch.setattr(contained.ordinary, "_verify_resources", lambda: resources)
    members = (StageMember("llama-completion.exe", resources["completion"], 1, "0" * 64, True),
               StageMember("model.gguf", resources["model"], 1, "1" * 64),
               StageMember("prompt.txt", output / "prompt.txt", 2, "2" * 64),
               StageMember("schema.json", output / "schema.json", 2, "3" * 64))
    monkeypatch.setattr(contained, "_members", lambda *_: members)
    monkeypatch.setattr(contained, "_environment", lambda stage: {"PATH": str(stage)})
    monkeypatch.setattr(contained, "check_probe_memory", lambda value: None)
    sid = "S-1-15-2-1-2-3-4-5-6-7"
    stage = tmp_path / "model_run" / "stage_abc"
    stage.mkdir(parents=True)
    evidence = SimpleNamespace(directory_path=str(stage), directory_id=(1, 2),
        executable_path=str(stage / "llama-completion.exe"),
        members=tuple(SimpleNamespace(name=m.name, source_path=str(m.source),
            path=str(stage / m.name), identity=(1, i + 10), size=m.size,
            sha256=m.sha256) for i, m in enumerate(members)))

    class Profile:
        def __init__(self, name): self.name = name
        def prepare(self): calls.append("prepare"); return SimpleNamespace(sid=sid)
        def __enter__(self): calls.append("provision"); return self
        def close(self): calls.append("profile_close")

    class Stage:
        @property
        def evidence(self): return evidence
        def recheck(self): calls.append("recheck"); return evidence
        def cleanup(self, *, child_cleanup_confirmed):
            calls.append(("stage_cleanup", child_cleanup_confirmed))
            return SimpleNamespace(complete=True)

    class Exemption:
        def __init__(self, value): assert value == sid
        def query(self):
            calls.append("query")
            return SimpleNamespace(package_sid=sid, exempt=False, cleanup_complete=True)
        def require_not_exempt(self):
            calls.append("require_not_exempt")
            return SimpleNamespace(package_sid=sid, exempt=False, cleanup_complete=True)
        def close(self): calls.append("exemption_close")

    class Security:
        def __init__(self, value): assert value == sid
        def __enter__(self): calls.append("security_enter"); return self
        def close(self): calls.append("security_close")

    token = SimpleNamespace(package_sid=sid, is_appcontainer=True, capability_count=0)
    result = ProcessResult("completed", 0, b'{"understood":false}', b"diagnostic", 123,
                           True, 1.0, token_evidence=token)

    def run(executable, args, **kwargs):
        calls.append(("run", executable, args, kwargs))
        return result

    def journal_write(path, document):
        calls.append(("journal", document["state"], document["outcome"]))

    deps = contained.Dependencies(run=run, profile=Profile, stage=lambda *a, **k: Stage(),
        security=Security, exemption=Exemption, journal_write=journal_write,
        memory_reader=lambda: 6 * 1024**3,
        new_run=lambda *a, **k: stage.parent)
    return SimpleNamespace(calls=calls, output=output, resources=resources,
                           evidence=evidence, deps=deps, result=result, sid=sid)


def _invoke(fixture, deps=None):
    adapter = contained._ContainedAdapter(deps or fixture.deps)
    adapter.observe_request((
        {"name": "prompt.txt", "bytes": 2, "sha256": "2" * 64},
        {"name": "schema.json", "bytes": 2, "sha256": "3" * 64},
    ))
    result = adapter(fixture.resources["completion"], ["--offline", "-m", str(fixture.resources["model"]),
        "-f", "prompt.txt", "--json-schema-file", "schema.json"], cwd=fixture.output,
        environment={"SECRET": "must-not-inherit"}, timeout_seconds=30,
        cancellation_event=None, stdout_limit=262144, stderr_limit=1048576,
        cleanup_timeout_seconds=3.0)
    return adapter, result


def test_missing_request_manifest_blocks_stage_and_launch(lifecycle):
    adapter = contained._ContainedAdapter(lifecycle.deps)
    result = adapter(lifecycle.resources["completion"], ["--offline", "-m", str(lifecycle.resources["model"]),
        "-f", "prompt.txt", "--json-schema-file", "schema.json"], cwd=lifecycle.output,
        environment={}, timeout_seconds=30, cancellation_event=None,
        stdout_limit=262144, stderr_limit=1048576, cleanup_timeout_seconds=3.0)
    assert result is None
    assert adapter.containment["compatibility_pass"] is False
    assert "prepare" not in lifecycle.calls


def test_request_manifest_hash_mismatch_blocks_launch(lifecycle):
    adapter = contained._ContainedAdapter(lifecycle.deps)
    adapter.observe_request(({"name": "prompt.txt", "bytes": 2, "sha256": "f" * 64},
                             {"name": "schema.json", "bytes": 2, "sha256": "3" * 64}))
    result = adapter(lifecycle.resources["completion"], ["--offline", "-m", str(lifecycle.resources["model"]),
        "-f", "prompt.txt", "--json-schema-file", "schema.json"], cwd=lifecycle.output,
        environment={}, timeout_seconds=30, cancellation_event=None,
        stdout_limit=262144, stderr_limit=1048576, cleanup_timeout_seconds=3.0)
    assert result is None
    assert adapter.containment["compatibility_pass"] is False
    assert "prepare" not in lifecycle.calls


def test_intent_precedes_provision_and_launch_is_contained(lifecycle):
    adapter, result = _invoke(lifecycle)
    assert result is lifecycle.result
    calls = lifecycle.calls
    assert calls.index(("journal", "intent", "pending")) < calls.index("provision")
    launch = next(item for item in calls if isinstance(item, tuple) and item[0] == "run")
    assert launch[1] == Path(lifecycle.evidence.executable_path)
    assert launch[2][launch[2].index("-m") + 1].endswith("stage_abc\\model.gguf") or launch[2][launch[2].index("-m") + 1].endswith("stage_abc/model.gguf")
    assert launch[3]["security_context"].__class__.__name__ == "Security"
    assert "SECRET" not in launch[3]["environment"]
    assert adapter.containment["compatibility_pass"] is True


def test_wrong_token_fails_without_ordinary_retry(lifecycle):
    wrong = ProcessResult("completed", 0, b"raw", b"stderr", 123, True, 1.0,
        token_evidence=SimpleNamespace(package_sid="wrong", is_appcontainer=True, capability_count=0))
    deps = contained.Dependencies(**{**vars(lifecycle.deps), "run": lambda *a, **k: wrong})
    adapter, result = _invoke(lifecycle, deps)
    assert result is wrong
    assert adapter.containment["compatibility_pass"] is False
    assert adapter.containment["error_stage"] == "token_evidence"
    assert (lifecycle.evidence.directory_path and (lifecycle.output.parent / "model_run" / "stdout.bin").read_bytes() == b"raw")


def test_uncertain_child_retains_owners(lifecycle):
    def uncertain(*args, **kwargs):
        raise RuntimeError("supervisor state unknown")
    deps = contained.Dependencies(**{**vars(lifecycle.deps), "run": uncertain})
    before = len(contained._LIVE_PENDING)
    adapter, result = _invoke(lifecycle, deps)
    assert result is None
    assert len(contained._LIVE_PENDING) == before + 1
    assert adapter.containment["state"] == "cleanup_pending"
    assert "security_close" not in lifecycle.calls
    assert not any(isinstance(item, tuple) and item[0] == "stage_cleanup" for item in lifecycle.calls)


def test_failed_intent_write_blocks_profile_and_launch(lifecycle):
    def failed_write(*args): raise OSError("disk fault")
    deps = contained.Dependencies(**{**vars(lifecycle.deps), "journal_write": failed_write})
    adapter, result = _invoke(lifecycle, deps)
    assert result is None
    assert adapter.containment["compatibility_pass"] is False
    assert "provision" not in lifecycle.calls
    assert not any(isinstance(item, tuple) and item[0] == "run" for item in lifecycle.calls)


def test_exempt_sid_blocks_profile_and_launch(lifecycle):
    class Exempt:
        def __init__(self, sid): pass
        def query(self): return SimpleNamespace(package_sid=lifecycle.sid, exempt=True, cleanup_complete=True)
        def require_not_exempt(self): raise ValueError("exemption_evidence")
        def close(self): lifecycle.calls.append("exemption_close")
    deps = contained.Dependencies(**{**vars(lifecycle.deps), "exemption": Exempt})
    adapter, result = _invoke(lifecycle, deps)
    assert result is None
    assert adapter.containment["compatibility_pass"] is False
    assert "provision" not in lifecycle.calls


def test_timeout_preserves_raw_output_and_cleans_exact_owner(lifecycle):
    timed = ProcessResult("timeout", None, b"partial stdout", b"partial stderr", 123,
                          True, 30.0, token_evidence=lifecycle.result.token_evidence)
    deps = contained.Dependencies(**{**vars(lifecycle.deps), "run": lambda *a, **k: timed})
    adapter, result = _invoke(lifecycle, deps)
    assert result is timed
    assert adapter.containment["compatibility_pass"] is False
    assert adapter.containment["state"] == "completed"
    assert (lifecycle.output.parent / "model_run" / "stdout.bin").read_bytes() == b"partial stdout"
    assert lifecycle.calls.count(("stage_cleanup", True)) == 1


def test_cancellation_before_stage_prevents_profile_and_launch(lifecycle):
    adapter = contained._ContainedAdapter(lifecycle.deps)
    adapter.observe_request(({"name": "prompt.txt", "bytes": 2, "sha256": "2" * 64},
                             {"name": "schema.json", "bytes": 2, "sha256": "3" * 64}))
    event = SimpleNamespace(is_set=lambda: True)
    result = adapter(lifecycle.resources["completion"], ["--offline", "-m", str(lifecycle.resources["model"]),
        "-f", "prompt.txt", "--json-schema-file", "schema.json"], cwd=lifecycle.output,
        environment={}, timeout_seconds=30, cancellation_event=event,
        stdout_limit=262144, stderr_limit=1048576, cleanup_timeout_seconds=3.0)
    assert result is None
    assert adapter.containment["compatibility_pass"] is False
    assert "prepare" not in lifecycle.calls


def test_stage_error_partial_owner_is_recovered_and_cleaned(lifecycle):
    class Partial:
        def cleanup(self, *, child_cleanup_confirmed):
            lifecycle.calls.append(("partial_cleanup", child_cleanup_confirmed))
            return SimpleNamespace(complete=True)
    partial = Partial()
    def failing_stage(*args, **kwargs): raise StageError("source_hash", partial)
    deps = contained.Dependencies(**{**vars(lifecycle.deps), "stage": failing_stage})
    adapter, result = _invoke(lifecycle, deps)
    assert result is None
    assert ("partial_cleanup", True) in lifecycle.calls
    assert "provision" not in lifecycle.calls
    assert adapter.containment["compatibility_pass"] is False


def test_final_journal_failure_retains_live_owners_and_raw_output(lifecycle):
    def write(path, document):
        if document["state"] == "completed": raise OSError("disk fault")
        lifecycle.calls.append(("journal", document["state"], document["outcome"]))
    deps = contained.Dependencies(**{**vars(lifecycle.deps), "journal_write": write})
    before = len(contained._LIVE_PENDING)
    adapter, result = _invoke(lifecycle, deps)
    assert result is lifecycle.result
    assert adapter.containment["state"] == "cleanup_pending"
    assert adapter.containment["compatibility_pass"] is False
    assert len(contained._LIVE_PENDING) == before + 1
    assert (lifecycle.output.parent / "model_run" / "stdout.bin").read_bytes() == result.stdout

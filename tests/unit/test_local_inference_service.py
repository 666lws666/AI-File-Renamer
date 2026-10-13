"""Synthetic service composition tests: no model, native call, or private file."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from io import BytesIO
import json
import subprocess
import sys
import threading
import time

import pytest
from PIL import Image

from src.core.provider_protocol import prepare_visual_payload
from src.services.local_ai.inference_request import LocalNamingRequest
from src.services.local_ai.inference_resources import AttestedResources
from src.services.local_ai.native.model_stage import BundleEvidence, MemberEvidence, StageError, StageMember
from src.services.local_ai.native.process import ProcessCleanupResult, ProcessResult
from src.services.local_ai.native.security import TokenEvidence
from src.services.local_ai.resource_catalog import ResourceCatalog, ResourceSpec


SID = "S-1-15-2-1-2-3-4-5-6-7"
PUBLIC = (StageMember("llama-completion.exe", Path(r"C:\runtime\llama-completion.exe"), 2,
                      sha256(b"ex").hexdigest(), True),
          StageMember("llama-mtmd-cli.exe", Path(r"C:\runtime\llama-mtmd-cli.exe"), 2,
                      sha256(b"mt").hexdigest(), True),
          StageMember("model.gguf", Path(r"C:\model\model.gguf"), 2,
                      sha256(b"mo").hexdigest()))
VISION = StageMember("projector.gguf", Path(r"C:\model\projector.gguf"), 2,
                     sha256(b"vi").hexdigest())


def catalog():
    return ResourceCatalog("Qwen/Qwen3.5-4B", "a" * 40, "unsloth/Qwen3.5-4B-GGUF",
        "b" * 40, "b10885", "Apache-2.0", "MIT", "synthetic",
        (ResourceSpec("runtime-cpu", "runtime.zip", "https://example.invalid", 4, "1" * 64),
         ResourceSpec("model-q4", "model.gguf", "https://example.invalid", 2, "2" * 64),
         ResourceSpec("vision-f16", "projector.gguf", "https://example.invalid", 2, "3" * 64)),
        "a" * 64)


class FakeJournal:
    def __init__(self, log, hit=None):
        self.log = log
        self.hit = hit
        self.fail_complete = False
        self.fail_lease = False
        self.fail_begin = False

    @contextmanager
    def lease(self):
        self.log.append("journal.lease")
        if self.fail_lease:
            raise RuntimeError("stale private journal")
        try:
            yield self
        finally:
            self.log.append("journal.exit")

    def begin(self, *, catalog_id, profile_name, package_sid):
        (self.hit or self.log.append)("journal.begin")
        if self.fail_begin:
            from src.services.local_ai.inference_journal import InferenceJournalError
            raise InferenceJournalError("JOURNAL_WRITE_FAILED")
        assert catalog_id == "a" * 64 and package_sid == SID
        return SimpleNamespace(run_id=profile_name.removeprefix("xuxia_local_"))

    def attach_stage(self, run_id, *, name, identity):
        self.log.append("journal.attach")
        assert name.startswith("stage_") and identity == (1, 2)

    def complete(self, run_id):
        self.log.append("journal.complete")
        if self.fail_complete:
            raise RuntimeError("private journal failure")


class FakeProfile:
    def __init__(self, name, log, hit=None):
        self.name, self.log, self.hit = name, log, hit

    def prepare(self):
        (self.hit or self.log.append)("profile.prepare")
        return SimpleNamespace(name=self.name, sid=SID)

    def __enter__(self):
        (self.hit or self.log.append)("profile.enter")
        return self

    def close(self):
        self.log.append("profile.close")


class FakeExemption:
    def __init__(self, sid, log, hit=None):
        assert sid == SID
        self.log = log
        self.hit = hit

    def query(self):
        (self.hit or self.log.append)("exemption.query")
        return SimpleNamespace(package_sid=SID, exempt=False, cleanup_complete=True)

    def require_not_exempt(self):
        (self.hit or self.log.append)("exemption.require")

    def close(self):
        self.log.append("exemption.close")


class FakeSecurity:
    def __init__(self, sid, log, hit=None):
        assert sid == SID
        self.log = log
        self.hit = hit

    def __enter__(self):
        (self.hit or self.log.append)("security.enter")
        return self

    def close(self):
        self.log.append("security.close")


class FakeStage:
    def __init__(self, public, private, entrypoint, log, hit=None, on_recheck=None):
        self.log = log
        self.hit = hit
        self.on_recheck = on_recheck
        self.evidence = self._evidence(public, private, entrypoint)

    def _evidence(self, public, private, entrypoint):
        all_members = []
        for member in (*public, *private):
            payload = member.data if hasattr(member, "data") else None
            all_members.append(MemberEvidence(member.name, None, None,
                rf"C:\state\stage_{'a' * 32}\{member.name}", (1, 3),
                len(payload) if payload is not None else member.size,
                sha256(payload).hexdigest() if payload is not None else member.sha256,
                None))
        return BundleEvidence(rf"C:\state\stage_{'a' * 32}", (1, 2), None,
            rf"C:\state\stage_{'a' * 32}\{entrypoint}", tuple(all_members))

    def recheck(self):
        (self.hit or self.log.append)("stage.recheck")
        if self.on_recheck:
            self.on_recheck()
        return self.evidence

    def cleanup(self, *, child_cleanup_confirmed):
        assert child_cleanup_confirmed is True
        self.log.append("stage.cleanup")
        return SimpleNamespace(complete=True)


class Rig:
    def __init__(self):
        self.log = []
        self.journal = FakeJournal(self.log, self.hit)
        self.output = json.dumps({"understood": True, "language": "en-US",
            "topic": {"value": "Campus network maintenance", "evidence_source": "text",
                      "evidence": "T000"}, "date": None, "version": None}).encode()
        self.run_result = None
        self.fail_at = None
        self.last_stage = None
        self.attest_identity = None
        self.on_attest = None
        self.attest_cancelled = False
        self.attest_resource_timeout = False
        self.attest_invalid_if_expired = False
        self.token = TokenEvidence(SID, True, 0)
        self.on_run = None
        self.on_stage = None
        self.last_cancellation_event = None
        self.on_recheck = None
        self.corrupt_stage = False
        self.partial_stage = False
        self.capacity_calls = 0
        self.fail_capacity_at = None
        self.clock = time.monotonic
        self.attest_unwind_fails = False
        self.attest_exit_fails = False

    def deps(self):
        return SimpleNamespace(clock=lambda: self.clock(), journal_factory=lambda root: self.journal,
            discover_windows_paths=self.discover, attest_resources=self.attest,
            profile_factory=lambda name: FakeProfile(name, self.log, self.hit),
            measure_host_capacity=self.measure, require_host_capacity=self.require,
            stage_model_bundle=self.stage, exemption_factory=lambda sid: FakeExemption(sid, self.log, self.hit),
            security_factory=lambda sid: FakeSecurity(sid, self.log, self.hit), build_launch=self.launch,
            run_bounded=self.run)

    def hit(self, name):
        self.log.append(name)
        if self.fail_at == name:
            raise RuntimeError("secret failure")

    def discover(self):
        self.hit("discover")
        return SimpleNamespace(system_root=Path(r"C:\Windows"), local_app_data=Path(r"C:\AppData"))

    @contextmanager
    def attest(self, resource_root, runtime_root, catalog, *, include_vision, cancelled, deadline):
        self.hit("attest.vision" if include_vision else "attest.text")
        if self.on_attest:
            self.on_attest()
        if self.attest_cancelled and cancelled():
            from src.services.local_ai.resource_transport import ResourceCancelled
            raise ResourceCancelled("synthetic cancellation", code="CANCELLED")
        if self.attest_resource_timeout:
            from src.services.local_ai.resource_transport import ResourceError
            raise ResourceError("synthetic deadline", code="RESOURCE_TIMEOUT")
        if self.attest_invalid_if_expired and self.clock() >= deadline:
            from src.services.local_ai.resource_transport import ResourceError
            raise ResourceError("synthetic expired deadline", code="INVALID_INFERENCE_RESOURCES")
        if self.attest_unwind_fails:
            self.log.append("attest.acquired")
            raise RuntimeError("private failed unwind")
        try:
            yield AttestedResources(catalog.identity, catalog.runtime_release,
                self.attest_identity or "b" * 64, "model.gguf", "projector.gguf" if include_vision else None,
                PUBLIC + ((VISION,) if include_vision else ()))
        finally:
            self.log.append("attest.exit")
            if self.attest_exit_fails:
                raise RuntimeError("private attestation exit failure")

    def measure(self, root):
        self.hit("capacity.measure")
        return SimpleNamespace()

    def require(self, capacity, *, staging_bytes):
        self.capacity_calls += 1
        self.hit("capacity.require")
        if self.capacity_calls == self.fail_capacity_at:
            raise RuntimeError("secret capacity failure")
        assert type(staging_bytes) is int and staging_bytes >= 0

    def stage(self, parent, sid, members, entrypoint, *, cancelled):
        self.hit("stage.create")
        assert parent == r"C:\state" and sid == SID
        self.last_stage = FakeStage(tuple(m for m in members if not hasattr(m, "data")),
                                    tuple(m for m in members if hasattr(m, "data")), entrypoint, self.log, self.hit,
                                    self.on_recheck)
        if self.corrupt_stage:
            members = self.last_stage.evidence.members
            self.last_stage.evidence = replace(self.last_stage.evidence,
                members=members[:-1] + (replace(members[-1], sha256="0" * 64),))
        if self.partial_stage:
            raise StageError("file_write", self.last_stage)
        if self.on_stage:
            self.on_stage()
        if cancelled():
            raise StageError("cancelled", self.last_stage)
        return self.last_stage

    def launch(self, evidence, *, model_name, projector_name, visual_names, windows_paths):
        self.hit("launch")
        assert evidence is self.last_stage.evidence
        assert model_name == "model.gguf"
        return SimpleNamespace(executable=Path(r"C:\state\stage_a\llama-completion.exe"),
            arguments=("--offline",), cwd=Path(r"C:\state\stage_a"), environment={})

    def run(self, executable, arguments, *, cwd, environment, timeout_seconds,
            cancellation_event, stdout_limit, stderr_limit, cleanup_timeout_seconds, security_context):
        self.hit("run")
        self.last_cancellation_event = cancellation_event
        assert stdout_limit == 262144 and stderr_limit == 1048576
        assert 0 < timeout_seconds <= 900 and 0 < cleanup_timeout_seconds <= 3
        assert not cancellation_event.is_set()
        if self.on_run:
            self.on_run()
        return self.run_result or ProcessResult("completed", 0, self.output, b"secret stderr", 1,
            True, 0.01, token_evidence=self.token)


def service(rig):
    from src.services.local_ai.inference_service import LocalInferenceConfig, LocalInferenceService
    return LocalInferenceService(LocalInferenceConfig(Path(r"C:\resources"), Path(r"C:\runtime"),
                                 Path(r"C:\state"), catalog()), _dependencies=rig.deps())


def request(**kwargs):
    return LocalNamingRequest(**({"text": "Campus network maintenance", "visuals": (),
                                  "locale": "en-US", "naming_mode": "smart"} | kwargs))


def visual():
    stream = BytesIO()
    Image.new("RGB", (2, 2), (10, 80, 120)).save(stream, format="PNG")
    return prepare_visual_payload(kind="resized_image", mime_type="image/png",
        data=stream.getvalue(), width=2, height=2, source_index=0,
        preprocessing_version="synthetic-v1", provenance="synthetic test")


def limit():
    return time.monotonic() + 30


def test_constructor_and_unready_infer_have_no_native_side_effects():
    rig = Rig()
    svc = service(rig)
    assert svc.snapshot().phase == "NOT_READY"
    result = svc.infer(request(), deadline=limit())
    assert not result.success and result.error == "NOT_READY"
    assert rig.log == []


def test_cloud_only_import_and_constructor_do_not_bind_native_process():
    code = (
        "import ctypes, sys; from pathlib import Path; "
        "ctypes.WinDLL = lambda *a, **k: (_ for _ in ()).throw(AssertionError('native binding')); "
        "from src.services.local_ai.inference_service import LocalInferenceConfig, LocalInferenceService; "
        "svc = LocalInferenceService(LocalInferenceConfig(Path('C:/resources'), "
        "Path('C:/runtime'), Path('C:/state'), None)); "
        "assert svc.snapshot().phase == 'NOT_READY'; "
        "assert 'src.services.local_ai.native.process' not in sys.modules"
    )
    run = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[2],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr


@pytest.mark.parametrize("deadline", [True, float("inf"), float("nan"), 10**1000, -1])
def test_bad_deadline_fails_before_any_io(deadline):
    rig = Rig()
    snap = service(rig).check_ready(deadline=deadline)
    assert snap.error == "INVALID_DEADLINE" and rig.log == []


def test_selfcheck_then_infer_runs_exact_order_and_cleans_before_publication():
    rig = Rig()
    svc = service(rig)
    ready = svc.check_ready(deadline=limit())
    assert ready.phase == "READY" and ready.identity
    assert rig.log.index("journal.lease") < rig.log.index("attest.vision")
    assert rig.log.index("journal.begin") < rig.log.index("stage.create")
    assert rig.log.index("stage.create") < rig.log.index("exemption.query")
    assert rig.log.index("exemption.query") < rig.log.index("profile.enter")
    assert rig.log.index("profile.enter") < rig.log.index("security.enter")
    assert rig.log.index("security.enter") < rig.log.index("run")
    assert rig.log.index("security.close") < rig.log.index("stage.cleanup")
    assert rig.log.index("stage.cleanup") < rig.log.index("journal.complete")
    rig.log.clear()
    result = svc.infer(request(), deadline=limit())
    assert result.success and result.fields["parts"][0]["evidence"] == "Campus network maintenance"
    assert rig.log.count("journal.lease") == 0
    assert "secret stderr" not in repr(result)


def test_terminal_journal_failure_retains_owner_and_blocks_next_launch():
    rig = Rig()
    svc = service(rig)
    assert svc.check_ready(deadline=limit()).phase == "READY"
    rig.journal.fail_complete = True
    result = svc.infer(request(), deadline=limit())
    assert not result.success and result.error == "RECOVERY_REQUIRED"
    count = rig.log.count("run")
    assert svc.infer(request(), deadline=limit()).error == "RECOVERY_REQUIRED"
    assert rig.log.count("run") == count
    assert svc.retry_cleanup(deadline=limit()).phase == "RECOVERY_REQUIRED"


def test_shutdown_closes_journal_and_refuses_future_inference():
    rig = Rig()
    svc = service(rig)
    assert svc.check_ready(deadline=limit()).phase == "READY"
    assert svc.shutdown(deadline=limit()).phase == "CLOSED"
    assert rig.log[-1] == "journal.exit"
    assert svc.infer(request(), deadline=limit()).error == "CLOSED"


def test_stale_journal_is_recovery_required_and_starts_no_native_path():
    rig = Rig()
    rig.journal.fail_lease = True
    svc = service(rig)
    snap = svc.check_ready(deadline=limit())
    assert snap.phase == "RECOVERY_REQUIRED" and snap.error == "RECOVERY_REQUIRED"
    assert rig.log == ["journal.lease"]
    assert svc.infer(request(), deadline=limit()).error == "RECOVERY_REQUIRED"
    assert svc.shutdown(deadline=limit()).phase == "RECOVERY_REQUIRED"


def test_unknown_attestation_enter_unwind_failure_requires_recovery():
    rig = Rig()
    rig.attest_unwind_fails = True
    svc = service(rig)
    snap = svc.check_ready(deadline=limit())
    assert snap.phase == "RECOVERY_REQUIRED" and snap.error == "RECOVERY_REQUIRED"
    assert "attest.acquired" in rig.log and "profile.prepare" not in rig.log
    assert svc._owner is not None and svc._owner.resource_context is not None
    assert svc.infer(request(), deadline=limit()).error == "RECOVERY_REQUIRED"


def test_attestation_exit_failure_retains_owner_and_blocks_journal_completion():
    rig = Rig()
    rig.attest_exit_fails = True
    svc = service(rig)

    snap = svc.check_ready(deadline=limit())

    assert snap.phase == "RECOVERY_REQUIRED" and snap.error == "RECOVERY_REQUIRED"
    assert svc._owner is not None and svc._owner.resource_context is not None
    assert rig.log.count("attest.exit") == 1
    assert "journal.complete" not in rig.log
    assert svc.infer(request(), deadline=limit()).error == "RECOVERY_REQUIRED"
    assert svc.retry_cleanup(deadline=limit()).phase == "RECOVERY_REQUIRED"


@pytest.mark.parametrize("boundary", ["discover", "attest.vision", "profile.prepare",
    "journal.begin", "capacity.measure", "capacity.require", "stage.create",
    "exemption.query", "exemption.require", "profile.enter", "security.enter",
    "stage.recheck", "launch", "run"])
def test_ordered_boundary_failure_never_publishes_ready(boundary):
    rig = Rig()
    rig.fail_at = boundary
    snap = service(rig).check_ready(deadline=limit())
    assert snap.phase != "READY"
    assert snap.error is not None and "secret" not in snap.error
    if "journal.begin" in rig.log and boundary != "run":
        assert "profile.close" in rig.log
    if "stage.create" in rig.log and boundary not in ("stage.create", "run"):
        assert "stage.cleanup" in rig.log
    if boundary == "run":
        assert snap.phase == "RECOVERY_REQUIRED" and "profile.close" not in rig.log


def test_token_mismatch_fails_selfcheck_and_cleans_exact_owner():
    rig = Rig()
    rig.token = TokenEvidence("S-1-15-2-9-9-9-9-9-9-9", True, 0)
    snap = service(rig).check_ready(deadline=limit())
    assert snap.phase == "NOT_READY" and snap.error == "TOKEN_VERIFICATION_FAILED"
    assert rig.log.index("stage.cleanup") < rig.log.index("journal.complete")


def test_stdout_overflow_is_rejected_without_content_in_error_or_repr():
    rig = Rig()
    svc = service(rig)
    assert svc.check_ready(deadline=limit()).phase == "READY"
    rig.run_result = ProcessResult("completed", 0, b"secret" * 50000,
        b"secret stderr", 1, True, 0.01, token_evidence=rig.token)
    result = svc.infer(request(), deadline=limit())
    assert result.error == "INVALID_RESPONSE"
    assert "secret" not in repr(result) and "secret" not in repr(svc.snapshot())


@pytest.mark.parametrize("status,exit_code", [("failed", 0), ("completed", 1)])
def test_noncompleted_or_nonzero_model_result_never_publishes_fields(status, exit_code):
    rig = Rig()
    svc = service(rig)
    assert svc.check_ready(deadline=limit()).phase == "READY"
    rig.run_result = ProcessResult(status, exit_code, b"secret output",
        b"secret stderr", 1, True, 0.01, token_evidence=rig.token)
    result = svc.infer(request(), deadline=limit())
    assert not result.success and result.fields is None and result.error == "ENGINE_FAILED"


def test_callback_exception_is_fixed_and_does_not_leak_text():
    rig = Rig()
    svc = service(rig)
    assert svc.check_ready(deadline=limit()).phase == "READY"
    def broken():
        raise RuntimeError("secret callback text")
    result = svc.infer(request(), deadline=limit(), is_current=broken)
    assert result.error == "CALLBACK_FAILED" and "secret" not in repr(result)
    assert "run" not in rig.log[rig.log.index("journal.complete") + 1:]


def test_currentness_flip_during_run_discards_success_after_cleanup():
    rig = Rig()
    svc = service(rig)
    assert svc.check_ready(deadline=limit()).phase == "READY"
    current = [True]
    rig.on_run = lambda: current.__setitem__(0, False)
    result = svc.infer(request(), deadline=limit(), is_current=lambda: current[0])
    assert not result.success and result.error == "STALE_CONTEXT" and result.fields is None
    assert rig.log[-1] == "journal.complete"


def test_template_request_after_smart_text_selfcheck_has_same_readiness_anchor():
    from src.core.template_model import Template, TemplateField
    rig = Rig()
    svc = service(rig)
    assert svc.check_ready(deadline=limit()).phase == "READY"
    template = Template(id="t", name="t", pattern="{dcTitle}",
                        fields=(TemplateField("dcTitle", "Title"),))
    rig.output = json.dumps({"understood": True, "language": "en-US",
        "fields": {"dcTitle": None}}).encode()
    result = svc.infer(request(naming_mode="template", template=template), deadline=limit())
    assert result.error != "RESOURCE_VERIFICATION_FAILED"


def test_insufficient_user_content_does_not_erase_valid_readiness_anchor():
    rig = Rig()
    svc = service(rig)
    anchor = svc.check_ready(deadline=limit()).identity
    rig.output = b'{"understood":false,"language":"en-US"}'
    first = svc.infer(request(), deadline=limit())
    assert first.error == "INSUFFICIENT_CONTENT"
    assert svc.snapshot().phase == "READY" and svc.snapshot().identity == anchor
    rig.output = Rig().output
    second = svc.infer(request(), deadline=limit())
    assert second.success and second.fields is not None


def test_malformed_engine_output_invalidates_readiness():
    rig = Rig()
    svc = service(rig)
    assert svc.check_ready(deadline=limit()).phase == "READY"
    rig.output = b"private malformed output"
    assert svc.infer(request(), deadline=limit()).error == "INVALID_RESPONSE"
    assert svc.snapshot().phase == "NOT_READY"


def test_failed_durable_begin_is_recovery_required_after_acquired_owner_cleanup():
    rig = Rig()
    rig.journal.fail_begin = True
    svc = service(rig)
    snap = svc.check_ready(deadline=limit())
    assert snap.phase == "RECOVERY_REQUIRED" and snap.error == "RECOVERY_REQUIRED"
    assert "profile.close" in rig.log and "attest.exit" in rig.log
    assert "stage.create" not in rig.log
    assert svc.infer(request(), deadline=limit()).error == "RECOVERY_REQUIRED"


def test_ready_smart_text_accepts_prepared_visual_without_spurious_anchor_mismatch():
    rig = Rig()
    svc = service(rig)
    anchor = svc.check_ready(deadline=limit()).identity
    result = svc.infer(request(visuals=(visual(),)), deadline=limit())
    assert result.success and "attest.vision" in rig.log
    assert svc.snapshot().identity == anchor
    assert rig.last_stage.evidence.members[-1].name == "visual_00.png"


def test_pending_job_owner_blocks_next_launch_until_retry_reap_succeeds():
    rig = Rig()
    svc = service(rig)
    assert svc.check_ready(deadline=limit()).phase == "READY"
    class Pending:
        attempts = 0
        def retry_reap(self, *, deadline):
            self.attempts += 1
            return ProcessCleanupResult(self.attempts >= 2, self.attempts >= 2)
    pending = Pending()
    rig.run_result = ProcessResult("completed", 0, rig.output, b"secret stderr", 1,
        False, 0.01, token_evidence=rig.token, pending_owner=pending)
    first = svc.infer(request(), deadline=limit())
    assert first.error == "CLEANUP_PENDING" and svc.snapshot().phase == "CLEANUP_PENDING"
    run_count = rig.log.count("run")
    assert svc.infer(request(), deadline=limit()).error == "CLEANUP_PENDING"
    assert rig.log.count("run") == run_count
    assert svc.retry_cleanup(deadline=limit()).phase == "NOT_READY"
    assert pending.attempts == 2
    assert rig.log.index("stage.cleanup") < rig.log.index("journal.complete")


def test_one_model_slot_and_ninth_waiter_is_busy():
    rig = Rig()
    svc = service(rig)
    assert svc.check_ready(deadline=limit()).phase == "READY"
    entered, release = threading.Event(), threading.Event()
    rig.on_run = lambda: (entered.set(), release.wait(5))
    results = []
    first = threading.Thread(target=lambda: results.append(svc.infer(request(), deadline=limit())))
    first.start()
    assert entered.wait(2)
    waiters = [threading.Thread(target=lambda: results.append(svc.infer(request(), deadline=limit())))
               for _ in range(8)]
    for waiter in waiters:
        waiter.start()
    until = time.monotonic() + 2
    while svc.snapshot().waiting_count != 8 and time.monotonic() < until:
        time.sleep(.005)
    assert svc.snapshot().waiting_count == 8
    ninth = svc.infer(request(), deadline=limit())
    assert ninth.error == "BUSY"
    release.set()
    first.join(5)
    for waiter in waiters:
        waiter.join(5)
    assert all(not thread.is_alive() for thread in (first, *waiters))
    assert len(results) == 9 and all(result.success for result in results)


def test_stale_context_during_recheck_stops_before_journal_attach():
    rig = Rig()
    svc = service(rig)
    assert svc.check_ready(deadline=limit()).phase == "READY"
    current = [True]
    rig.on_recheck = lambda: current.__setitem__(0, False)
    before = rig.log.count("journal.attach")
    result = svc.infer(request(), deadline=limit(), is_current=lambda: current[0])
    assert result.error == "STALE_CONTEXT"
    assert rig.log.count("journal.attach") == before


def test_partial_stage_owner_is_retained_and_cleaned_before_profile():
    rig = Rig()
    rig.partial_stage = True
    snap = service(rig).check_ready(deadline=limit())
    assert snap.phase != "READY" and "stage.cleanup" in rig.log
    assert rig.log.index("stage.cleanup") < rig.log.index("profile.close")
    assert "run" not in rig.log


def test_mismatched_private_stage_evidence_blocks_launch_and_cleans():
    rig = Rig()
    rig.corrupt_stage = True
    snap = service(rig).check_ready(deadline=limit())
    assert snap.phase != "READY" and snap.error == "STAGE_VERIFICATION_FAILED"
    assert "launch" not in rig.log and "stage.cleanup" in rig.log


def test_second_capacity_failure_after_staging_never_runs_model():
    rig = Rig()
    rig.fail_capacity_at = 2
    snap = service(rig).check_ready(deadline=limit())
    assert snap.phase != "READY" and rig.capacity_calls == 2
    assert "stage.cleanup" in rig.log and "run" not in rig.log


def test_shutdown_cancels_running_invocation_then_closes_journal():
    rig = Rig()
    svc = service(rig)
    assert svc.check_ready(deadline=limit()).phase == "READY"
    entered, release = threading.Event(), threading.Event()
    rig.on_run = lambda: (entered.set(), release.wait(5))
    results = []
    inference = threading.Thread(target=lambda: results.append(svc.infer(request(), deadline=limit())))
    inference.start()
    assert entered.wait(2)
    shutdown = threading.Thread(target=lambda: results.append(svc.shutdown(deadline=limit())))
    shutdown.start()
    until = time.monotonic() + 2
    while not svc._shutdown.is_set() and time.monotonic() < until:
        time.sleep(.005)
    assert svc._shutdown.is_set()
    release.set()
    inference.join(5)
    shutdown.join(5)
    assert not inference.is_alive() and not shutdown.is_alive()
    assert results[0].error == "CANCELLED" and results[0].fields is None
    assert results[1].phase == "CLOSED" and rig.log[-1] == "journal.exit"


def test_work_budget_expiring_during_cancelled_runner_is_timeout_not_token_failure():
    rig = Rig()
    svc = service(rig)
    anchor = svc.check_ready(deadline=limit()).identity
    deadline = limit()
    rig.run_result = ProcessResult("cancelled", None, b"", b"", None,
        True, 0.01, token_evidence=None)
    rig.on_run = lambda: setattr(rig, "clock", lambda: deadline - 9)
    result = svc.infer(request(), deadline=deadline)
    assert result.error == "TIMEOUT" and result.fields is None
    assert svc.snapshot().phase == "READY" and svc.snapshot().identity == anchor


def test_stale_cancelled_runner_keeps_readiness_after_cleanup():
    rig = Rig()
    svc = service(rig)
    anchor = svc.check_ready(deadline=limit()).identity
    current = [True]
    rig.run_result = ProcessResult("cancelled", None, b"", b"", None,
        True, 0.01, token_evidence=None)
    rig.on_run = lambda: current.__setitem__(0, False)
    result = svc.infer(request(), deadline=limit(), is_current=lambda: current[0])
    assert result.error == "STALE_CONTEXT" and result.fields is None
    assert svc.snapshot().phase == "READY" and svc.snapshot().identity == anchor


@pytest.mark.parametrize("token", [None, TokenEvidence(SID, True, 0)])
def test_caller_cancelled_runner_with_or_without_token_keeps_readiness(token):
    rig = Rig()
    svc = service(rig)
    anchor = svc.check_ready(deadline=limit()).identity
    cancelled = [False]
    rig.run_result = ProcessResult("cancelled", None, b"", b"", None,
        True, 0.01, token_evidence=token)
    rig.on_run = lambda: cancelled.__setitem__(0, True)
    result = svc.infer(request(), deadline=limit(), cancelled=lambda: cancelled[0])
    assert result.error == "CANCELLED" and result.fields is None
    assert svc.snapshot().phase == "READY" and svc.snapshot().identity == anchor


@pytest.mark.parametrize("kind,expected", [("cancel", "CANCELLED"),
                                            ("stale", "STALE_CONTEXT")])
def test_runner_cancellation_reason_is_latched_if_caller_flag_recovers(kind, expected):
    rig = Rig()
    svc = service(rig)
    anchor = svc.check_ready(deadline=limit()).identity
    cancelled = [False]
    current = [True]
    rig.run_result = ProcessResult("cancelled", None, b"", b"", None,
        True, 0.01, token_evidence=None)

    def briefly_cancel():
        if kind == "cancel":
            cancelled[0] = True
        else:
            current[0] = False
        assert rig.last_cancellation_event.is_set()
        if kind == "cancel":
            cancelled[0] = False
        else:
            current[0] = True

    rig.on_run = briefly_cancel
    result = svc.infer(request(), deadline=limit(), cancelled=lambda: cancelled[0],
                       is_current=lambda: current[0])
    assert result.error == expected and result.fields is None
    assert svc.snapshot().phase == "READY" and svc.snapshot().identity == anchor


def test_runner_timeout_status_is_timeout_even_before_service_clock_reaches_deadline():
    rig = Rig()
    svc = service(rig)
    anchor = svc.check_ready(deadline=limit()).identity
    rig.run_result = ProcessResult("timeout", None, b"", b"", None,
        True, 0.01, token_evidence=None)

    result = svc.infer(request(), deadline=limit())

    assert result.error == "TIMEOUT" and result.fields is None
    assert svc.snapshot().phase == "READY" and svc.snapshot().identity == anchor


def test_deadline_during_resource_attestation_is_timeout_not_cancelled():
    rig = Rig()
    svc = service(rig)
    assert svc.check_ready(deadline=limit()).phase == "READY"
    deadline = limit()
    rig.attest_cancelled = True
    rig.on_attest = lambda: setattr(rig, "clock", lambda: deadline - 9)

    result = svc.infer(request(), deadline=deadline)

    assert result.error == "TIMEOUT" and result.fields is None
    assert svc.snapshot().phase == "READY"
    assert "profile.prepare" not in rig.log[rig.log.index("attest.text"):]


def test_attestation_deadline_error_is_public_timeout_and_keeps_readiness():
    rig = Rig()
    svc = service(rig)
    anchor = svc.check_ready(deadline=limit()).identity
    run_count = rig.log.count("run")
    rig.attest_resource_timeout = True

    result = svc.infer(request(), deadline=limit())

    assert result.error == "TIMEOUT" and result.fields is None
    assert svc.snapshot().phase == "READY" and svc.snapshot().identity == anchor
    assert rig.log.count("run") == run_count


def test_attestation_entry_deadline_race_is_timeout_not_invalid_resources():
    rig = Rig()
    svc = service(rig)
    anchor = svc.check_ready(deadline=limit()).identity
    deadline = limit()
    rig.on_attest = lambda: setattr(rig, "clock", lambda: deadline - 9)
    rig.attest_invalid_if_expired = True
    run_count = rig.log.count("run")

    result = svc.infer(request(), deadline=deadline)

    assert result.error == "TIMEOUT" and result.fields is None
    assert svc.snapshot().phase == "READY" and svc.snapshot().identity == anchor
    assert rig.log.count("run") == run_count


@pytest.mark.parametrize("kind,expected", [("cancel", "CANCELLED"),
                                            ("stale", "STALE_CONTEXT")])
def test_staging_cancellation_reason_survives_partial_stage_cleanup(kind, expected):
    rig = Rig()
    svc = service(rig)
    anchor = svc.check_ready(deadline=limit()).identity
    cancelled, current = [False], [True]

    def flip_context():
        if kind == "cancel":
            cancelled[0] = True
        else:
            current[0] = False

    rig.on_stage = flip_context
    prior_run_count = rig.log.count("run")
    prior_stage_cleanup_count = rig.log.count("stage.cleanup")
    result = svc.infer(request(), deadline=limit(), cancelled=lambda: cancelled[0],
                       is_current=lambda: current[0])

    assert result.error == expected and result.fields is None
    assert rig.log.count("run") == prior_run_count
    assert rig.log.count("stage.cleanup") == prior_stage_cleanup_count + 1
    assert svc.snapshot().phase == "READY" and svc.snapshot().identity == anchor

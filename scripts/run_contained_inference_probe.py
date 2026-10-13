"""Synthetic Qwen compatibility run in an owned, zero-capability AppContainer.

This diagnostic does not attest network isolation or product readiness.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256 as digest
import json
import math
import os
from pathlib import Path
import re
import secrets
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_local_inference_probe as ordinary
from scripts.local_appcontainer_probe import _new_run, _write_journal
from scripts.local_model_stage import StageMember, stage_model_bundle
from scripts.local_probe_exemptions import OwnedLoopbackExemptionQuery
from scripts.local_probe_process import ProcessResult, run_bounded
from scripts.local_probe_profile import OwnedAppContainerProfile, ProfileError
from scripts.local_probe_security import AppContainerSecurity
from scripts.local_probe_stage import StageError
from scripts.probe_local_model_native import check_probe_memory, windows_available_memory

QA_ROOT = ordinary.LOCAL_DIAGNOSTICS
_LIVE_PENDING = []
_COLLISION = 0x800700B7
_INPUT_NAMES = re.compile(r"(?:prompt\.txt|schema\.json|visual_[0-7][0-9]\.jpg)\Z")


@dataclass(frozen=True)
class Dependencies:
    run: object = run_bounded
    profile: object = OwnedAppContainerProfile
    stage: object = stage_model_bundle
    security: object = AppContainerSecurity
    exemption: object = OwnedLoopbackExemptionQuery
    journal_write: object = _write_journal
    memory_reader: object = windows_available_memory
    new_run: object = _new_run


def _hash_file(path: Path) -> str:
    hasher = digest()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            hasher.update(block)
    return hasher.hexdigest()


def _runtime_members(resources: dict) -> tuple[StageMember, ...]:
    """Pin each runtime member to archive bytes, not only current disk state."""
    runtime = resources["runtime_dir"]
    manifest = json.loads(ordinary.RESOURCE_MANIFEST.read_text(encoding="utf-8"))
    runtime_record = next(item for item in manifest["resources"] if item["id"] == "runtime-cpu")
    archive = ordinary.RESOURCE_DIR / runtime_record["filename"]
    members = []
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        if len(infos) > 78 or any(info.is_dir() or Path(info.filename).name != info.filename for info in infos):
            raise ValueError("runtime_layout")
        if {info.filename for info in infos} != {p.name for p in runtime.iterdir()}:
            raise ValueError("runtime_layout")
        for info in infos:
            path = runtime / info.filename
            if path.is_symlink() or not path.is_file() or path.stat().st_size != info.file_size:
                raise ValueError("runtime_member")
            with bundle.open(info) as source:
                hasher = digest()
                while block := source.read(1024 * 1024):
                    hasher.update(block)
            expected = hasher.hexdigest()
            if _hash_file(path) != expected:
                raise ValueError("runtime_member")
            members.append(StageMember(info.filename, path, info.file_size, expected,
                                       info.filename.lower().endswith((".exe", ".dll"))))
    return tuple(members)


def _input_member(path: Path, output: Path, max_size: int) -> StageMember:
    if (not _INPUT_NAMES.fullmatch(path.name) or path.parent != output
            or path.is_symlink() or not path.is_file()):
        raise ValueError("prepared_input")
    size = path.stat().st_size
    if not 0 < size <= max_size:
        raise ValueError("prepared_input")
    return StageMember(path.name, path, size, _hash_file(path))


def _members(resources: dict, arguments: list[str], output: Path) -> tuple[StageMember, ...]:
    runtime = _runtime_members(resources)
    manifest = json.loads(ordinary.RESOURCE_MANIFEST.read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in manifest["resources"]}
    weights = []
    for key, identifier in (("model", "model-q4"), ("projector", "vision-f16")):
        if key == "projector" and "--mmproj" not in arguments:
            continue
        source = resources[key]
        record = by_id[identifier]
        if (source != ordinary.RESOURCE_DIR / record["filename"] or source.is_symlink()
                or source.stat().st_size != record["bytes"] or _hash_file(source) != record["sha256"]):
            raise ValueError("weight_identity")
        weights.append(StageMember(source.name, source, record["bytes"], record["sha256"]))
    inputs = [_input_member(output / "prompt.txt", output, 128 * 1024),
              _input_member(output / "schema.json", output, 128 * 1024)]
    if "--image" in arguments:
        names = arguments[arguments.index("--image") + 1].split(",")
        if (not 1 <= len(names) <= ordinary.MAX_VISUALS
                or names != [f"visual_{i:02d}.jpg" for i in range(len(names))]):
            raise ValueError("prepared_visuals")
        inputs += [_input_member(output / name, output, ordinary.MAX_VISUAL_BYTES) for name in names]
        if sum(member.size for member in inputs[2:]) > ordinary.MAX_VISUAL_BYTES:
            raise ValueError("prepared_visuals")
    members = (*runtime, *weights, *inputs)
    if len(members) > 80 or sum(member.size for member in members) > 5 * 1024**3:
        raise ValueError("bundle_bounds")
    return members


def _environment(stage: Path) -> dict[str, str]:
    system = os.environ.get("SystemRoot", r"C:\Windows")
    local = os.environ.get("LOCALAPPDATA")
    if (not re.fullmatch(r"[A-Za-z]:\\[^\x00]+", system)
            or type(local) is not str or not re.fullmatch(r"[A-Za-z]:\\[^\x00/]+", local)
            or not Path(local).is_dir()):
        raise ValueError("environment")
    return {"SystemRoot": system, "WINDIR": system,
            "PATH": str(stage) + ";" + system + r"\System32",
            "TEMP": str(stage), "TMP": str(stage), "LOCALAPPDATA": local}


def _fixed_error(exc: BaseException) -> str:
    if isinstance(exc, (StageError, ProfileError)):
        return exc.stage if re.fullmatch(r"[a-z_]{1,40}", exc.stage) else "internal"
    if isinstance(exc, ValueError) and str(exc) in {
            "runtime_layout", "runtime_member", "weight_identity", "prepared_input",
            "prepared_visuals", "bundle_bounds", "environment", "exemption_evidence",
            "token_evidence", "process_result", "process_cleanup", "memory_blocked",
            "cancelled", "stage_evidence", "resource_translation"}:
        return str(exc)
    return "internal"


class _ContainedAdapter:
    def __init__(self, dependencies: Dependencies):
        self.deps = dependencies
        self._request_records = None
        self.containment = {"state": "not_started", "compatibility_pass": False,
                            "outbound_isolation_verified": False, "product_ready": False,
                            "journal": None, "error_stage": None, "token_evidence": None}

    def observe_request(self, records):
        if self._request_records is not None or type(records) is not tuple or not 2 <= len(records) <= 10:
            raise ValueError("prepared_input")
        names = ["prompt.txt", "schema.json"] + [f"visual_{i:02d}.jpg" for i in range(len(records) - 2)]
        if any(type(record) is not dict or set(record) != {"name", "bytes", "sha256"}
               or record["name"] != names[index]
               or type(record["bytes"]) is not int or not 0 < record["bytes"] <= ordinary.MAX_VISUAL_BYTES
               or type(record["sha256"]) is not str
               or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None
               for index, record in enumerate(records)):
            raise ValueError("prepared_input")
        self._request_records = tuple((r["name"], r["bytes"], r["sha256"]) for r in records)

    def __call__(self, executable, arguments, *, cwd, environment, timeout_seconds,
                 cancellation_event, stdout_limit, stderr_limit, cleanup_timeout_seconds):
        run = owner = profile = security = exemption = None
        profile_close_needed = False
        child_confirmed = True
        process = None
        journal = None
        path = None
        error = None
        state = "cleanup_pending"

        def persist():
            if journal is not None:
                self.deps.journal_write(path, journal)

        try:
            if self._request_records is None:
                raise ValueError("prepared_input")
            # run_case already verified resources; repeat immediately before staging.
            check_probe_memory(self.deps.memory_reader())
            resources = ordinary._verify_resources()
            members = _members(resources, arguments, Path(cwd))
            actual_inputs = tuple((m.name, m.size, m.sha256) for m in members
                                  if m.name in ("prompt.txt", "schema.json") or m.name.startswith("visual_"))
            if actual_inputs != self._request_records:
                raise ValueError("prepared_input")
            entry = "llama-mtmd-cli.exe" if "--mmproj" in arguments else "llama-completion.exe"
            if executable != resources["mtmd" if "--mmproj" in arguments else "completion"]:
                raise ValueError("resource_translation")
            if cancellation_event is not None and cancellation_event.is_set():
                raise ValueError("cancelled")
            run = self.deps.new_run(QA_ROOT, probe_kind="model")
            path = run / "journal.json"
            name = "xuxia_probe_" + secrets.token_hex(16)
            profile = self.deps.profile(name)
            profile_close_needed = True
            prepared = profile.prepare()
            try:
                owner = self.deps.stage(str(run), prepared.sid, members, entry,
                                        cancelled=(cancellation_event.is_set if cancellation_event else lambda: False))
            except StageError as exc:
                owner = exc.owner
                raise
            evidence = owner.evidence
            if (len(evidence.members) != len(members) or
                    {m.name for m in evidence.members} != {m.name for m in members}):
                raise ValueError("stage_evidence")
            by_source = {m.source_path: m.path for m in evidence.members}
            expected_sources = {str(m.source) for m in members}
            if set(by_source) != expected_sources:
                raise ValueError("stage_evidence")
            translated = [by_source.get(item, item) for item in arguments]
            if (any(item in (str(resources["model"]), str(resources["projector"])) for item in translated)
                    or translated[translated.index("-f") + 1] != "prompt.txt"
                    or translated[translated.index("--json-schema-file") + 1] != "schema.json"):
                raise ValueError("resource_translation")
            journal = {"schema": 1, "state": "intent", "outcome": "pending",
                       "profile_name": name, "sid": prepared.sid,
                       "stage": {"directory": evidence.directory_path,
                                 "directory_id": evidence.directory_id,
                                 "executable": evidence.executable_path,
                                 "members": [{"name": m.name, "path": m.path,
                                              "id": m.identity, "size": m.size,
                                              "sha256": m.sha256} for m in evidence.members]},
                       "input_hashes": {m.name: m.sha256 for m in members if
                                        m.name in ("prompt.txt", "schema.json") or m.name.startswith("visual_")},
                       "process": None, "streams": None, "token_evidence": None,
                       "exemption": None, "error_stage": None,
                       "outbound_isolation_verified": False, "product_ready": False}
            persist()  # Durable parent intent precedes any profile creation.
            exemption = self.deps.exemption(prepared.sid)
            queried = exemption.query()
            checked = exemption.require_not_exempt()
            if (queried != checked or queried.package_sid != prepared.sid
                    or queried.exempt is not False or queried.cleanup_complete is not True):
                raise ValueError("exemption_evidence")
            journal["exemption"] = {"sid": prepared.sid, "exempt": False,
                                    "cleanup_complete": True}
            persist()
            try:
                profile.__enter__()
            except ProfileError as exc:
                if exc.stage == "profile_create" and exc.code == _COLLISION:
                    profile_close_needed = False
                    state = "collision"
                raise
            journal["state"] = "created"
            persist()
            security = self.deps.security(prepared.sid)
            security.__enter__()
            owner.recheck()
            check_probe_memory(self.deps.memory_reader())
            if cancellation_event is not None and cancellation_event.is_set():
                raise ValueError("cancelled")
            contained_environment = _environment(Path(evidence.directory_path))
            child_confirmed = False
            process = self.deps.run(Path(evidence.executable_path), translated,
                cwd=Path(evidence.directory_path), environment=contained_environment,
                timeout_seconds=timeout_seconds, cancellation_event=cancellation_event,
                stdout_limit=stdout_limit, stderr_limit=stderr_limit,
                cleanup_timeout_seconds=cleanup_timeout_seconds, security_context=security)
            child_confirmed = isinstance(process, ProcessResult) and process.cleanup_complete is True
            if isinstance(process, ProcessResult):
                # Raw evidence survives cleanup and final-journal failures.
                (run / "stdout.bin").write_bytes(process.stdout)
                (run / "stderr.bin").write_bytes(process.stderr)
                journal["streams"] = {"stdout": str(run / "stdout.bin"),
                                      "stderr": str(run / "stderr.bin")}
                journal["process"] = {"status": process.status, "exit_code": process.exit_code,
                                      "pid": process.pid, "cleanup_complete": process.cleanup_complete,
                                      "elapsed_seconds": process.elapsed_seconds,
                                      "win32_error": process.win32_error, "error_stage": process.error_stage}
                token = process.token_evidence
                if token is not None:
                    journal["token_evidence"] = {"sid": token.package_sid,
                        "is_appcontainer": token.is_appcontainer,
                        "capability_count": token.capability_count}
                persist()
            if not child_confirmed:
                raise ValueError("process_cleanup")
            if (process.token_evidence is None or process.token_evidence.package_sid != prepared.sid
                    or process.token_evidence.is_appcontainer is not True
                    or type(process.token_evidence.capability_count) is not int
                    or process.token_evidence.capability_count != 0):
                raise ValueError("token_evidence")
            if process.status != "completed" or process.exit_code != 0:
                raise ValueError("process_result")
            journal["outcome"] = "compatible"
        except BaseException as exc:
            error = _fixed_error(exc)
            if journal is not None:
                journal["outcome"] = "failed"
                journal["error_stage"] = error
        if not child_confirmed:
            if journal is not None:
                journal["state"] = "cleanup_pending"
                try:
                    persist()
                except Exception:
                    error = "journal_write"
            _LIVE_PENDING.append((owner, profile, security, exemption, run, process))
            self.containment.update(state="cleanup_pending", error_stage=error,
                                    journal=str(path) if path else None)
            return process if isinstance(process, ProcessResult) else None
        cleanup_failed = False
        for label, action in (("security_close", lambda: security.close() if security else None),
                              ("stage_cleanup", lambda: owner.cleanup(child_cleanup_confirmed=True) if owner else None),
                              ("exemption_close", lambda: exemption.close() if exemption else None),
                              ("profile_close", lambda: profile.close() if profile_close_needed else None)):
            try:
                result = action()
                if label == "stage_cleanup" and result is not None and result.complete is not True:
                    raise ValueError("stage_incomplete")
            except Exception:
                cleanup_failed = True
                error = label
                break
        state = "cleanup_pending" if cleanup_failed else "completed" if state != "collision" else "collision"
        if journal is not None:
            journal["state"] = state
            if error:
                journal["outcome"] = "failed"
                journal["error_stage"] = error
            try:
                persist()
            except Exception:
                error = "journal_write"
                state = "cleanup_pending"
        if state == "cleanup_pending":
            _LIVE_PENDING.append((owner, profile, security, exemption, run, process))
        self.containment.update(state=state, error_stage=error,
                                journal=str(path) if path else None,
                                token_evidence=journal["token_evidence"] if journal else None,
                                compatibility_pass=bool(state == "completed" and error is None
                                                        and journal and journal["outcome"] == "compatible"))
        return process if isinstance(process, ProcessResult) else None


def run_contained_case(case_id, locale, *, quality="balanced", timeout_seconds=600,
                       cancellation_event=None):
    adapter = _ContainedAdapter(Dependencies())
    result = ordinary.run_case(case_id, locale, quality=quality,
        timeout_seconds=timeout_seconds, cancellation_event=cancellation_event,
        process_runner=adapter, request_observer=adapter.observe_request)
    result["containment"] = adapter.containment
    output = Path(result["evidence_directory"]) / "contained-result.json"
    ordinary._save_result(output, result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, choices=[f"case_{n:02d}" for n in range(1, 9)])
    parser.add_argument("--locale", required=True, choices=ordinary.LOCALES)
    parser.add_argument("--quality", choices=ordinary.QUALITIES, default="balanced")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args(argv)
    try:
        result = run_contained_case(args.case, args.locale, quality=args.quality,
                                    timeout_seconds=args.timeout)
        print(json.dumps({"case_id": args.case, "containment": result["containment"],
                          "policy_accepted": result["policy_accepted"],
                          "evidence_directory": result["evidence_directory"]}, ensure_ascii=False))
        return 0 if result["containment"]["compatibility_pass"] else 1
    except (OSError, ValueError, RuntimeError):
        print(json.dumps({"case_id": args.case, "error": "PREFLIGHT_FAILED",
                          "compatibility_pass": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

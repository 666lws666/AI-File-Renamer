"""Fixed, bounded AppContainer hello diagnostic; never a privacy attestation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import sys
from typing import Callable

from scripts.local_probe_access import AccessValidationError, validate_access_result
from scripts.local_probe_exemptions import ExemptionError, OwnedLoopbackExemptionQuery
from scripts.local_probe_hello import HelloValidationError, validate_hello_result
from scripts.local_probe_listener import ListenerError, OwnedControlListener
from scripts.local_probe_process import ProcessResult, run_bounded
from scripts.local_probe_profile import OwnedAppContainerProfile, ProfileError
from scripts.local_probe_security import AppContainerSecurity
from scripts.local_probe_stage import StageError, stage_probe


BASE = Path(__file__).resolve().parents[1]
QA_ROOT = BASE / "tests/screenshots/qa-current/local-privacy"
SOURCE = BASE / "scripts/native/AppContainerHello.cs"
ACCESS_SOURCE = BASE / "scripts/native/AppContainerAccess.cs"
COMPILER = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
FRAMEWORK = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\System.dll")
MAX_EXE = 4 * 1024 * 1024
MAX_JOURNAL = 64 * 1024
COLLISION = 0x800700B7
_LIVE_PENDING = []  # Deliberately retain sensitive live owners on uncertain child cleanup.


@dataclass(frozen=True)
class Dependencies:
    run: Callable = run_bounded
    profile: Callable = OwnedAppContainerProfile
    stage: Callable = stage_probe
    security: Callable = AppContainerSecurity
    journal_write: Callable | None = None
    exemption: Callable | None = None
    listener: Callable | None = None


@dataclass(frozen=True)
class Outcome:
    ok: bool
    state: str
    journal: str | None
    run: str | None
    error_stage: str | None
    error_code: int | None
    retained_evidence: tuple[str, ...]
    retained_owner: object = None
    retained_profile: object = None
    retained_security: object = None
    retained_exemption: object = None
    retained_listener: object = None


def _ancestors_not_reparse(path: Path) -> None:
    for part in (path, *path.parents):
        if part.exists() and part.is_symlink():
            raise ValueError("reparse_ancestor")
        if part.exists() and os.name == "nt" and part.lstat().st_file_attributes & 0x400:
            raise ValueError("reparse_ancestor")


def _new_run(root: Path, *, probe_kind: str = "hello") -> Path:
    _ancestors_not_reparse(root)
    root.mkdir(parents=True, exist_ok=True)
    _ancestors_not_reparse(root)
    for _ in range(8):
        run = root / (probe_kind + "_" + secrets.token_hex(16))
        try:
            run.mkdir()
            return run
        except FileExistsError:
            continue
    raise OSError("run_collision")


def _atomic_write(path: Path, data: bytes) -> None:
    if len(data) > MAX_JOURNAL:
        raise ValueError("journal_size")
    temporary = path.with_name(path.name + "." + secrets.token_hex(16) + ".tmp")
    with temporary.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _write_journal(path: Path, data: dict) -> None:
    encoded = json.dumps(data, ensure_ascii=True, sort_keys=True,
                         separators=(",", ":")).encode("ascii")
    _atomic_write(path, encoded)


def _environment(run: Path, *, contained: bool = False) -> dict[str, str]:
    system = os.environ.get("SystemRoot", r"C:\Windows")
    if not re.fullmatch(r"[A-Za-z]:\\[^\0]+", system):
        raise ValueError("system_root")
    environment = {"SystemRoot": system, "WINDIR": system,
                   "PATH": system + r"\System32", "TEMP": str(run), "TMP": str(run)}
    if contained:
        local = os.environ.get("LOCALAPPDATA")
        if (type(local) is not str or not re.fullmatch(r"[A-Za-z]:\\[^\x00/]+", local)
                or not Path(local).is_dir()):
            raise ValueError("localappdata")
        environment["LOCALAPPDATA"] = local
    return environment


def _process_record(run: Path, label: str, result: ProcessResult, journal: dict,
                    *, stdout_bound: int = 1024) -> None:
    # Bounded raw streams stay distinct from fixed/numeric journal fields.
    if type(result.stdout) is not bytes or type(result.stderr) is not bytes:
        raise ValueError("stream_type")
    if len(result.stdout) > (stdout_bound if label != "compile" else 4096):
        raise ValueError("stdout_bound")
    if len(result.stderr) > 4096:
        raise ValueError("stderr_bound")
    stdout = run / (label + ".stdout")
    stderr = run / (label + ".stderr")
    stdout.write_bytes(result.stdout)
    stderr.write_bytes(result.stderr)
    journal["streams"][label] = {"stdout": str(stdout), "stderr": str(stderr)}
    journal["process"][label] = {
        "status": result.status if result.status in
        ("completed", "launch_error", "timeout", "cancelled", "output_limit", "cleanup_incomplete") else "invalid",
        "exit_code": result.exit_code if type(result.exit_code) is int else None,
        "cleanup_complete": result.cleanup_complete is True,
        "win32_error": result.win32_error if type(result.win32_error) is int else None,
        "error_stage": result.error_stage if type(result.error_stage) is str and
        re.fullmatch(r"[a-z_]{1,40}", result.error_stage) else None,
    }


def _valid_lifecycle(result: ProcessResult) -> bool:
    return isinstance(result, ProcessResult) and result.cleanup_complete is True


def run_diagnostic(dependencies: Dependencies = Dependencies(), *, root: Path = QA_ROOT,
                   source_bytes: bytes | None = None,
                   compiler_bytes: bytes | None = None,
                   framework_bytes: bytes | None = None,
                   probe_kind: str = "hello") -> Outcome:
    """Orchestrate one new run; test inputs are injected, CLI has none."""
    if probe_kind not in ("hello", "access") or type(probe_kind) is not str:
        raise ValueError("probe_kind")
    access = probe_kind == "access"
    run = None
    journal_path = None
    owner = profile = security = exemption = listener = None
    profile_close_needed = False
    child_confirmed = True
    state = "cleanup_pending"
    error_stage = None
    error_code = None
    evidence = []
    doc = None
    compiler_records = {"process": {}, "streams": {}}
    write = dependencies.journal_write or _write_journal

    def persist():
        if doc is not None:
            write(journal_path, doc)

    try:
        run = _new_run(Path(root), probe_kind=probe_kind)
        journal_path = run / "journal.json"
        source_path = ACCESS_SOURCE if access else SOURCE
        source = source_path.read_bytes() if source_bytes is None else source_bytes
        compiler = COMPILER.read_bytes() if compiler_bytes is None else compiler_bytes
        framework = (FRAMEWORK.read_bytes() if framework_bytes is None else framework_bytes) if access else None
        if (type(source) is not bytes or not source or type(compiler) is not bytes or not compiler or
                (access and (type(framework) is not bytes or not framework))):
            raise ValueError("input_bytes")
        source_copy = run / (probe_kind + ".cs")
        source_copy.write_bytes(source)
        evidence.append(str(source_copy))
        output = run / (probe_kind + ".exe")
        args = ["/noconfig", "/nologo", "/target:exe", "/platform:x64",
                "/optimize+"]
        if access:
            args.append("/reference:" + str(FRAMEWORK))
        args += ["/out:" + probe_kind + ".exe", probe_kind + ".cs"]
        child_confirmed = False
        compiled = dependencies.run(COMPILER, args, cwd=run,
            environment=_environment(run), timeout_seconds=30,
            stdout_limit=4096, stderr_limit=4096)
        child_confirmed = _valid_lifecycle(compiled)
        _process_record(run, "compile", compiled, compiler_records)
        evidence += [compiler_records["streams"]["compile"][key] for key in ("stdout", "stderr")]
        if compiled.cleanup_complete is not True:
            raise ValueError("compile_cleanup")
        if compiled.status != "completed" or type(compiled.exit_code) is not int or compiled.exit_code != 0:
            raise ValueError("compile_result")
        if not output.is_file() or not 0 < output.stat().st_size <= MAX_EXE:
            raise ValueError("compiled_exe")
        built = output.read_bytes()
        if len(built) != output.stat().st_size:
            raise ValueError("compiled_exe")
        evidence.append(str(output))
        name = "xuxia_probe_" + secrets.token_hex(16)
        profile = dependencies.profile(name)
        # Constructed live helper may retain failed SID/string frees in prepare;
        # close() retries those and internally gates Delete on observed ownership.
        profile_close_needed = True
        prepared = profile.prepare()
        if access:
            owner = dependencies.stage(str(run), prepared.sid, built, sha256(built).hexdigest(),
                                       include_fixtures=True)
        else:
            owner = dependencies.stage(str(run), prepared.sid, built, sha256(built).hexdigest())
        paths = owner.evidence
        doc = {"schema": 1, "state": "intent", "outcome": "pending",
               "probe_kind": probe_kind,
               "run_id": run.name, "profile_name": name, "sid": prepared.sid,
               "stage": {"directory": paths.directory_path, "executable": paths.executable_path},
               "sha256": {"source": sha256(source).hexdigest(),
                          "compiler": sha256(compiler).hexdigest(), "executable": sha256(built).hexdigest()},
               "process": compiler_records["process"],
               "streams": compiler_records["streams"], "token_evidence": None,
               "error": None,
               "limitations": ["profile_delete_does_not_prove_storage_absence",
                               "file_denial_unverified", "network_denial_unverified"]}
        if access:
            doc["sha256"]["framework"] = sha256(framework).hexdigest()
            doc["limitations"] = ["fixed_synthetic_objects_and_two_endpoints_only",
                                  "standard_appcontainer_may_access_public_system_resources",
                                  "model_isolation_unverified"]
            doc["fixtures"] = None
            doc["exemption"] = None
            doc["control_receipt"] = None
            doc["measurements"] = {}
            doc["stage_cleanup"] = None
        persist()  # Durable intent must precede profile creation.
        checked = owner.recheck()
        child_args = []
        stdout_bound = 4096 if access else 1024
        if access:
            fixtures = checked.fixtures
            if (type(fixtures) is not tuple or len(fixtures) != 2 or
                    tuple(f.filename for f in fixtures) != ("allowed.txt", "denied.txt") or
                    any(type(f.path) is not str or type(f.sha256) is not str or
                        type(f.size) is not int for f in fixtures)):
                raise ValueError("fixture_evidence")
            doc["fixtures"] = [{"name": f.filename, "path": f.path,
                                "sha256": f.sha256, "size": f.size} for f in fixtures]
            persist()
            exemption_factory = dependencies.exemption or OwnedLoopbackExemptionQuery
            exemption = exemption_factory(prepared.sid)
            queried = exemption.query()
            checked_exemption = exemption.require_not_exempt()
            if (queried != checked_exemption or queried.package_sid != prepared.sid or
                    queried.exempt is not False or queried.cleanup_complete is not True or
                    type(queried.count) is not int or queried.count < 0):
                raise ValueError("exemption_evidence")
            doc["exemption"] = {"package_sid": queried.package_sid, "count": queried.count,
                                "exempt": False, "cleanup_complete": True}
            persist()
            listener_factory = dependencies.listener or OwnedControlListener
            listener = listener_factory()
            if type(listener.port) is not int or not 1 <= listener.port <= 65535:
                raise ValueError("listener_port")
            child_args = ["ordinary", fixtures[0].path, fixtures[1].path, str(listener.port)]
        child_confirmed = False
        ordinary = dependencies.run(Path(paths.executable_path), child_args, cwd=Path(paths.directory_path),
            environment=_environment(run), timeout_seconds=15,
            stdout_limit=stdout_bound, stderr_limit=4096)
        child_confirmed = _valid_lifecycle(ordinary)
        _process_record(run, "ordinary", ordinary, doc, stdout_bound=stdout_bound)
        evidence += [doc["streams"]["ordinary"][key] for key in ("stdout", "stderr")]
        persist()
        if not child_confirmed:
            raise ValueError("ordinary_cleanup")
        if access:
            try:
                doc["measurements"]["ordinary"] = asdict(validate_access_result(ordinary, mode="ordinary"))
            except AccessValidationError:
                raise ValueError("ordinary_access") from None
            persist()
            receipt = listener.verify_control()
            if (receipt.byte_count != 26 or
                    receipt.sha256 != sha256(b"xuxia-loopback-control-v1\n").hexdigest()):
                raise ValueError("control_receipt")
            doc["control_receipt"] = {"byte_count": receipt.byte_count, "sha256": receipt.sha256}
            persist()
        else:
            try:
                validate_hello_result(ordinary)
            except HelloValidationError:
                raise ValueError("ordinary_hello") from None
        try:
            profile.__enter__()
            profile_close_needed = True
        except ProfileError as exc:
            if exc.stage == "profile_create" and exc.code == COLLISION:
                doc["state"] = "collision"
                state = "collision"
                profile_close_needed = False
            else:
                # A failed entry can follow Create S_OK and a failed helper delete.
                profile_close_needed = True
            raise
        doc["state"] = "created"
        persist()
        security = dependencies.security(prepared.sid)
        security.__enter__()
        owner.recheck()
        contained_environment = _environment(run, contained=True)
        if access:
            child_args = ["contained", fixtures[0].path, fixtures[1].path, str(listener.port)]
        child_confirmed = False
        contained = dependencies.run(Path(paths.executable_path), child_args, cwd=Path(paths.directory_path),
            environment=contained_environment, timeout_seconds=15,
            stdout_limit=stdout_bound, stderr_limit=4096, security_context=security)
        child_confirmed = _valid_lifecycle(contained)
        _process_record(run, "contained", contained, doc, stdout_bound=stdout_bound)
        evidence += [doc["streams"]["contained"][key] for key in ("stdout", "stderr")]
        persist()
        if not child_confirmed:
            raise ValueError("contained_cleanup")
        if contained.status == "launch_error":
            error_code = contained.win32_error if type(contained.win32_error) is int else None
            raise ValueError("contained_launch")
        token = contained.token_evidence
        if (token is None or token.package_sid != prepared.sid or
                token.is_appcontainer is not True or
                type(token.capability_count) is not int or token.capability_count != 0):
            raise ValueError("token_evidence")
        doc["token_evidence"] = {"package_sid": token.package_sid,
                                 "is_appcontainer": True, "capability_count": 0}
        persist()
        if access:
            try:
                doc["measurements"]["contained"] = asdict(validate_access_result(
                    contained, mode="contained", expected_sid=prepared.sid))
            except AccessValidationError:
                raise ValueError("contained_access") from None
        else:
            try:
                validate_hello_result(contained)
            except HelloValidationError:
                raise ValueError("contained_hello") from None
        doc["outcome"] = "passed"
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            error_stage = "interrupted"
        elif isinstance(exc, (ProfileError, StageError)):
            error_stage = exc.stage
            error_code = exc.code if isinstance(exc, ProfileError) else None
            if isinstance(exc, StageError) and owner is None:
                owner = exc.owner
        elif isinstance(exc, (ExemptionError, ListenerError)):
            error_stage = exc.stage
            error_code = getattr(exc, "code", None)
            if isinstance(exc, ListenerError) and listener is None:
                listener = exc.owner
        elif isinstance(exc, ValueError) and str(exc) in {
            "reparse_ancestor", "input_bytes", "system_root", "compile_cleanup",
            "compile_result", "compiled_exe", "ordinary_cleanup", "ordinary_hello",
            "contained_cleanup", "contained_launch", "token_evidence", "contained_hello", "localappdata", "stream_type",
            "stdout_bound", "stderr_bound", "journal_size", "fixture_evidence",
            "exemption_evidence", "listener_port", "ordinary_access", "contained_access",
            "control_receipt"}:
            error_stage = str(exc)
        else:
            error_stage = "internal"
        if doc is not None:
            doc["outcome"] = "failed"
            doc["error"] = {"stage": error_stage, "code": error_code}
    if not child_confirmed:
        state = "cleanup_pending"
        if doc is not None:
            doc["state"] = state
            try:
                persist()
            except Exception:
                error_stage = "journal_write"
        result = Outcome(False, state, str(journal_path) if journal_path else None,
                         str(run) if run else None, error_stage, error_code,
                         tuple(evidence), owner, profile if profile_close_needed else None, security,
                         exemption, listener)
        _LIVE_PENDING.append(result)
        return result
    # No child exists or a returned supervisor result confirmed cleanup.
    cleanup_error = None
    for label, action in (("listener_close", lambda: listener.close() if listener else None),
                          ("exemption_close", lambda: exemption.close() if exemption else None),
                          ("security_close", lambda: security.close() if security else None),
                          ("stage_cleanup", lambda: owner.cleanup(child_cleanup_confirmed=True) if owner else None),
                          ("profile_close", lambda: profile.close() if profile_close_needed else None)):
        try:
            report = action()
            if label == "stage_cleanup" and doc is not None and access and report is not None:
                doc["stage_cleanup"] = {"complete": report.complete is True,
                                        "handles_closed": report.handles_closed is True,
                                        "remaining_paths": list(report.remaining_paths),
                                        "uncertain_paths": list(report.uncertain_paths),
                                        "failures": list(report.failures)}
            if label == "stage_cleanup" and report is not None and report.complete is not True:
                raise ValueError("stage_incomplete")
        except Exception:
            cleanup_error = label
            if error_stage is None:
                error_stage = label
            if doc is not None:
                doc["outcome"] = "failed"
            break
    if doc is not None:
        state = ("collision" if cleanup_error is None and state == "collision" else
                 "completed" if cleanup_error is None else "cleanup_pending")
        doc["state"] = state
        doc["error"] = {"stage": error_stage, "code": error_code} if error_stage else None
        try:
            persist()
        except Exception:
            error_stage = "journal_write"
            state = "cleanup_pending"
    ok = bool(doc is not None and doc["outcome"] == "passed" and state == "completed" and error_stage is None)
    outcome = Outcome(ok, state, str(journal_path) if journal_path else None,
                   str(run) if run else None, error_stage, error_code, tuple(evidence),
                   owner if state == "cleanup_pending" else None,
                   profile if state == "cleanup_pending" and profile_close_needed else None,
                   security if state == "cleanup_pending" else None,
                   exemption if state == "cleanup_pending" else None,
                   listener if state == "cleanup_pending" else None)
    if state == "cleanup_pending":
        _LIVE_PENDING.append(outcome)
    return outcome


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv not in ([], ["--access"]):
        print("Unexpected argument; this diagnostic has no options.", file=sys.stderr)
        return 2
    outcome = run_diagnostic(probe_kind="access" if argv else "hello")
    print(json.dumps({"ok": outcome.ok, "state": outcome.state,
                      "journal": outcome.journal, "run": outcome.run,
                      "error_stage": outcome.error_stage, "error_code": outcome.error_code,
                      "retained_evidence": outcome.retained_evidence}, ensure_ascii=True))
    return 0 if outcome.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

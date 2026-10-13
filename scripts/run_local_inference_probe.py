"""Run one bounded, offline, pinned local-model naming diagnostic.

This is an engineering probe, not a product inference provider or a security
sandbox.  It accepts only the reviewed synthetic corpus and pinned resources.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import uuid
import zipfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pymupdf

from scripts.local_model_probe_resources import verify_resource
from scripts.local_probe_process import ProcessResult, run_bounded
from scripts.probe_local_model_native import check_probe_memory, sha256, windows_available_memory
from src.core.smart_naming import SmartNamingError, SmartNamingPolicy
from src.services.local_ai.naming_protocol import (
    MAX_TEXT_BYTES, SMART_PROTOCOL_VERSION, _build_prompt, decode_response,
    local_schema as _product_local_schema,
    text_evidence_spans, text_metadata_choices,
)
from src.services.media.image_preprocessor import ImagePreprocessor
from src.services.media.keyframe_extractor import VideoKeyframeExtractor
from src.services.media.pdf_renderer import PdfRenderer


LOCAL_DIAGNOSTICS = ROOT / "tests/screenshots/qa-current/local-privacy"
CORPUS_DIR = LOCAL_DIAGNOSTICS / "semantic-corpus-v1-reviewed"
CORPUS_MANIFEST = CORPUS_DIR / "manifest.json"
RUNS_DIR = LOCAL_DIAGNOSTICS / "inference-runs"
RESOURCE_MANIFEST = ROOT / "resources/local-models/qwen35-4b-feasibility.json"
RESOURCE_DIR = LOCAL_DIAGNOSTICS / "resources"
RUNTIME_DIR = LOCAL_DIAGNOSTICS / "runtime-b10885"
CORPUS_MANIFEST_SHA256 = "cd820442dffcb12c8c71daf804c8c88fe87e46a0e4760a68a8e175ba99639d8b"
LOCALES = ("zh-CN", "zh-HK", "en-US")
QUALITIES = ("economy", "balanced", "quality")
DIAGNOSTIC_PROTOCOL = SMART_PROTOCOL_VERSION
MAX_VISUAL_BYTES = 16 * 1024 * 1024
MAX_VISUALS = 8


def local_schema(locale: str, *, has_text: bool, has_visuals: bool, text_evidence=None) -> dict:
    """Retain the diagnostic's original three-locale invocation boundary."""
    if locale not in LOCALES:
        raise ValueError("unsupported probe locale")
    return _product_local_schema(locale, has_text=has_text, has_visuals=has_visuals,
                                 text_evidence=text_evidence)


def _load_verified_case(case_id: str) -> tuple[dict, Path]:
    if not isinstance(case_id, str) or case_id not in {f"case_{number:02d}" for number in range(1, 9)}:
        raise ValueError("unknown diagnostic case")
    if sha256(CORPUS_MANIFEST) != CORPUS_MANIFEST_SHA256:
        raise ValueError("corpus manifest hash mismatch")
    manifest = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))
    matches = [item for item in manifest.get("cases", []) if item.get("case_id") == case_id]
    if len(matches) != 1:
        raise ValueError("invalid corpus manifest")
    case = matches[0]
    source = (CORPUS_DIR / case["source_path"]).resolve()
    if (not source.is_relative_to(CORPUS_DIR.resolve()) or source.is_symlink() or not source.is_file()
            or source.stat().st_size != case.get("bytes") or sha256(source) != case.get("sha256")):
        raise ValueError("source hash mismatch")
    return case, source


def _is_link(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def _validate_output(output_dir: Path) -> Path:
    output_dir = Path(output_dir)
    if _is_link(LOCAL_DIAGNOSTICS):
        raise ValueError("unsafe diagnostic root")
    if RUNS_DIR.exists() and (not RUNS_DIR.is_dir() or _is_link(RUNS_DIR)):
        raise ValueError("unsafe diagnostic output root")
    runs = RUNS_DIR.resolve()
    if not output_dir.is_absolute() or output_dir.parent.resolve() != runs:
        raise ValueError("unsafe diagnostic output path")
    if output_dir.exists() or _is_link(output_dir):
        raise FileExistsError("diagnostic output already exists")
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    if _is_link(RUNS_DIR):
        raise ValueError("unsafe diagnostic output root")
    output_dir.mkdir()
    return output_dir


def _cancel_callback(cancellation_event):
    return None if cancellation_event is None else cancellation_event.is_set


def _write_visuals(output_dir: Path, payloads, *, timestamps=()) -> list[dict]:
    payloads = tuple(payloads)
    timestamps = tuple(timestamps)
    if len(payloads) > MAX_VISUALS or (timestamps and len(timestamps) != len(payloads)):
        raise ValueError("prepared visual count exceeded")
    if sum(len(payload.data) for payload in payloads) > MAX_VISUAL_BYTES:
        raise ValueError("prepared visual bytes exceeded")
    results = []
    for index, payload in enumerate(payloads):
        target = output_dir / f"visual_{index:02d}.jpg"
        with target.open("xb") as stream:
            stream.write(payload.data)
        results.append({
            "path": target,
            "bytes": len(payload.data),
            "sha256": hashlib.sha256(payload.data).hexdigest(),
            "source_index": payload.source_index,
            "timestamp_seconds": timestamps[index] if timestamps else None,
            "kind": payload.kind,
        })
    return results


def _prepare_input(case_id: str, output_dir: Path, quality: str = "balanced",
                   cancellation_event=None) -> dict:
    """Verify and prepare exactly one reviewed corpus case without model access."""
    if quality not in QUALITIES:
        raise ValueError("invalid quality")
    case, source = _load_verified_case(case_id)
    output_dir = _validate_output(output_dir)
    kind = case["kind"]
    text = ""
    payloads = ()
    timestamps = ()
    cancelled = _cancel_callback(cancellation_event)
    if kind == "text":
        raw = source.read_bytes()
        if len(raw) > MAX_TEXT_BYTES:
            raise ValueError("source text exceeds diagnostic bound")
        text = raw.decode("utf-8", errors="strict")
    elif kind == "text_pdf":
        with pymupdf.open(source) as document:
            if not document.is_pdf or document.needs_pass or document.page_count != 2:
                raise ValueError("invalid text PDF")
            text = "\n\n".join(document.load_page(index).get_text() for index in (0, 1))
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValueError("extracted text exceeds diagnostic bound")
    elif kind == "image":
        payloads = (ImagePreprocessor().process_file(source, source_index=0,
                                                     cancellation_token=cancelled),)
    elif kind == "image_pdf":
        rendered = PdfRenderer().render_file(source, page_indices=[0, 1],
                                             cancellation_token=cancelled)
        payloads = rendered.payloads
    elif kind == "video":
        extracted = VideoKeyframeExtractor().extract_file(source, quality_mode=quality,
                                                          cancellation_token=cancelled)
        payloads, timestamps = extracted.payloads, extracted.timestamps_seconds
    else:
        raise ValueError("unsupported corpus source kind")
    visuals = _write_visuals(output_dir, payloads, timestamps=timestamps)
    return {
        "case_id": case_id,
        "source_kind": kind,
        "source_extension": source.suffix,
        "source_bytes": case["bytes"],
        "source_sha256": case["sha256"],
        "text": text,
        "visuals": visuals,
        "output_dir": output_dir,
    }


def prepare_input(case_id: str, output_dir: Path, quality: str = "balanced") -> dict:
    return _prepare_input(case_id, output_dir, quality)


def _hash_stream(stream) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            return digest.hexdigest()
        digest.update(chunk)


def _verify_runtime_tree(archive: Path) -> None:
    if not RUNTIME_DIR.is_dir() or RUNTIME_DIR.is_symlink():
        raise ValueError("verified runtime directory is unavailable")
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        expected = {member.filename for member in members}
        actual = {item.name for item in RUNTIME_DIR.iterdir()}
        if expected != actual or any(member.is_dir() for member in members):
            raise ValueError("runtime directory differs from pinned archive")
        for member in members:
            target = RUNTIME_DIR / member.filename
            if target.is_symlink() or not target.is_file():
                raise ValueError("unsafe runtime member")
            with bundle.open(member) as archived:
                expected_hash = _hash_stream(archived)
            if sha256(target) != expected_hash:
                raise ValueError("runtime member hash mismatch")


def _verify_resources() -> dict:
    manifest = json.loads(RESOURCE_MANIFEST.read_text(encoding="utf-8"))
    resources = manifest.get("resources")
    if not isinstance(resources, list) or {item.get("id") for item in resources} != {"runtime-cpu", "model-q4", "vision-f16"}:
        raise ValueError("invalid pinned resource manifest")
    by_id = {item["id"]: item for item in resources}
    paths = {identifier: RESOURCE_DIR / by_id[identifier]["filename"] for identifier in by_id}
    if not all(verify_resource(paths[identifier], by_id[identifier]) for identifier in by_id):
        raise ValueError("pinned resource hash mismatch")
    _verify_runtime_tree(paths["runtime-cpu"])
    completion = RUNTIME_DIR / "llama-completion.exe"
    mtmd = RUNTIME_DIR / "llama-mtmd-cli.exe"
    if not completion.is_file() or completion.is_symlink() or not mtmd.is_file() or mtmd.is_symlink():
        raise ValueError("required pinned executable is unavailable")
    return {"runtime_dir": RUNTIME_DIR, "completion": completion, "mtmd": mtmd,
            "model": paths["model-q4"], "projector": paths["vision-f16"]}




def _new_output_path(case_id: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return RUNS_DIR / f"{stamp}-{case_id}-{uuid.uuid4().hex}"


def _environment(runtime_dir: Path, output_dir: Path) -> dict[str, str]:
    system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
    windows_dir = os.environ.get("WINDIR") or system_root
    return {
        "SystemRoot": system_root,
        "WINDIR": windows_dir,
        "PATH": os.pathsep.join((str(runtime_dir), str(Path(system_root) / "System32"))),
        "TEMP": str(output_dir),
        "TMP": str(output_dir),
    }


def _arguments(resources: dict, prompt_path: Path, schema_path: Path, visuals: list[dict]) -> tuple[Path, list[str]]:
    common = [
        "--offline", "-m", str(resources["model"]), "-f", prompt_path.name,
        "--json-schema-file", schema_path.name, "-n", "1024", "-c", "8192",
        "-t", "4", "-tb", "4", "--device", "none", "--no-op-offload",
        "--no-kv-offload", "--flash-attn", "off", "--no-warmup", "--seed", "1",
        "--temp", "0", "--log-colors", "off", "--verbosity", "1",
    ]
    if not visuals:
        return resources["completion"], common + [
            "--conversation", "--single-turn", "--jinja", "--reasoning", "off",
            "--no-display-prompt", "--simple-io",
        ]
    images = ",".join(item["path"].name for item in visuals)
    return resources["mtmd"], common + [
        "--mmproj", str(resources["projector"]), "--mmproj-device", "none",
        "--no-mmproj-offload", "--image", images, "--image-max-tokens", "1024",
    ]


def _serializable_input(prepared: dict) -> dict:
    return {
        "source_kind": prepared["source_kind"],
        "source_bytes": prepared["source_bytes"],
        "source_sha256": prepared["source_sha256"],
        "text_bytes": len(prepared["text"].encode("utf-8")),
        "visuals": [{key: value for key, value in item.items() if key != "path"}
                    for item in prepared["visuals"]],
    }


def _save_result(path: Path, result: dict) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def run_case(case_id: str, locale: str, *, quality: str = "balanced",
             timeout_seconds: float = 600, cancellation_event=None,
             process_runner=run_bounded, memory_reader=windows_available_memory,
             text_layout: str = "lines", request_observer=None) -> dict:
    """Prepare, run and persist one diagnostic; never repair model output."""
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 900):
        raise ValueError("timeout must be finite, positive and at most 900 seconds")
    if locale not in LOCALES or quality not in QUALITIES:
        raise ValueError("invalid probe argument")
    if text_layout not in ("lines", "contiguous"):
        raise ValueError("invalid text layout")
    if request_observer is not None and not callable(request_observer):
        raise ValueError("invalid request observer")
    check_probe_memory(memory_reader())
    resources = _verify_resources()
    prepared = _prepare_input(case_id, _new_output_path(case_id), quality,
                              cancellation_event=cancellation_event)
    output_dir = prepared["output_dir"]
    has_text, has_visuals = bool(prepared["text"]), bool(prepared["visuals"])
    if text_layout != "lines" and (not has_text or has_visuals):
        raise ValueError("contiguous layout is text-only")
    text_evidence = text_evidence_spans(prepared["text"], text_layout=text_layout) if has_text else None
    metadata_evidence = text_metadata_choices(text_evidence) if has_text else None
    schema = local_schema(locale, has_text=has_text, has_visuals=has_visuals,
                          text_evidence=text_evidence)
    prompt = _build_prompt(locale, prepared["text"], has_text=has_text,
                           has_visuals=has_visuals, text_layout=text_layout,
                           text_evidence=text_evidence)
    prompt_path, schema_path = output_dir / "prompt.txt", output_dir / "schema.json"
    prompt_path.write_text(prompt, encoding="utf-8", newline="\n")
    schema_path.write_text(json.dumps(schema, ensure_ascii=False, separators=(",", ":")),
                           encoding="utf-8", newline="\n")
    text_evidence_path = output_dir / "text-evidence.json"
    metadata_evidence_path = output_dir / "metadata-evidence.json"
    if has_text:
        text_evidence_path.write_text(
            json.dumps(text_evidence, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8", newline="\n")
        metadata_evidence_path.write_text(
            json.dumps(metadata_evidence, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8", newline="\n")
    executable, arguments = _arguments(resources, prompt_path, schema_path, prepared["visuals"])

    base = {
        "diagnostic_protocol": DIAGNOSTIC_PROTOCOL,
        "runner_sha256": sha256(Path(__file__).resolve()),
        "case_id": case_id,
        "locale": locale,
        "quality": quality,
        "text_layout": text_layout,
        "evidence_directory": str(output_dir),
        "input": _serializable_input(prepared),
        "prompt_sha256": sha256(prompt_path),
        "schema_sha256": sha256(schema_path),
        "text_evidence_sha256": sha256(text_evidence_path) if has_text else None,
        "metadata_evidence_sha256": sha256(metadata_evidence_path) if has_text else None,
        "launched": False,
        "status": "launch_error",
        "exit_code": None,
        "cleanup_complete": False,
        "elapsed_seconds": 0.0,
        "parsed_response": None,
        "policy_accepted": False,
        "error": "PROCESS_LAUNCH_ERROR",
        "suggested_name": None,
        "human_model_quality_reviewed": False,
        "outbound_isolation_verified": False,
    }
    try:
        check_probe_memory(memory_reader())
    except (OSError, ValueError, RuntimeError) as error:
        base.update({
            "status": "preflight_failed",
            "error": "MEMORY_BLOCKED" if str(error).startswith("MEMORY_BLOCKED:") else "MEMORY_CHECK_FAILED",
            "error_stage": "prelaunch_memory",
            "cleanup_complete": True,  # No child or process handles were created.
        })
        _save_result(output_dir / "result.json", base)
        return base
    if request_observer is not None:
        try:
            records = (
                {"name": "prompt.txt", "bytes": prompt_path.stat().st_size,
                 "sha256": base["prompt_sha256"]},
                {"name": "schema.json", "bytes": schema_path.stat().st_size,
                 "sha256": base["schema_sha256"]},
                *({"name": item["path"].name, "bytes": item["bytes"],
                   "sha256": item["sha256"]} for item in prepared["visuals"]),
            )
            request_observer(records)
        except Exception:
            base.update(status="preflight_failed", error="REQUEST_OBSERVER_FAILED",
                        error_stage="request_observer", cleanup_complete=True)
            _save_result(output_dir / "result.json", base)
            return base
    try:
        process = process_runner(
            executable, arguments, cwd=output_dir,
            environment=_environment(resources["runtime_dir"], output_dir),
            timeout_seconds=float(timeout_seconds), cancellation_event=cancellation_event,
            stdout_limit=262144, stderr_limit=1048576, cleanup_timeout_seconds=3.0,
        )
        if not isinstance(process, ProcessResult):
            raise TypeError("process runner returned invalid result")
    except Exception:
        _save_result(output_dir / "result.json", base)
        return base

    with (output_dir / "stdout.bin").open("xb") as stream:
        stream.write(process.stdout)
    with (output_dir / "stderr.bin").open("xb") as stream:
        stream.write(process.stderr)
    base.update({
        "launched": process.pid is not None,
        "status": process.status,
        "exit_code": process.exit_code,
        "cleanup_complete": process.cleanup_complete,
        "elapsed_seconds": process.elapsed_seconds,
        "win32_error": process.win32_error,
        "error_stage": process.error_stage,
    })
    if process.status != "completed" or process.exit_code != 0 or not process.cleanup_complete:
        if process.status == "completed" and process.exit_code != 0:
            base["error"] = "PROCESS_NONZERO_EXIT"
        elif not process.cleanup_complete:
            base["error"] = "PROCESS_CLEANUP_INCOMPLETE"
        else:
            base["error"] = "PROCESS_" + process.status.upper()
        _save_result(output_dir / "result.json", base)
        return base
    try:
        parsed = decode_response(process.stdout, locale, has_text=has_text, has_visuals=has_visuals,
                                 text_evidence=text_evidence)
        base["parsed_response"] = parsed
    except ValueError:
        base["error"] = "PROTOCOL_INVALID"
        _save_result(output_dir / "result.json", base)
        return base
    try:
        base["suggested_name"] = SmartNamingPolicy(locale).render(
            parsed, extracted_text=prepared["text"], has_visuals=has_visuals,
            extension=prepared["source_extension"],
        )
        base["policy_accepted"] = True
        base["error"] = None
    except SmartNamingError as error:
        base["error"] = str(error)
    _save_result(output_dir / "result.json", base)
    return base


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, choices=[f"case_{number:02d}" for number in range(1, 9)])
    parser.add_argument("--locale", required=True, choices=LOCALES)
    parser.add_argument("--quality", choices=QUALITIES, default="balanced")
    parser.add_argument("--text-layout", choices=("lines", "contiguous"), default="lines")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args(argv)
    try:
        result = run_case(args.case, args.locale, quality=args.quality,
                          timeout_seconds=args.timeout, text_layout=args.text_layout)
        summary = {key: result[key] for key in (
            "case_id", "status", "exit_code", "cleanup_complete", "policy_accepted",
            "error", "suggested_name", "evidence_directory")}
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if result["policy_accepted"] else 1
    except (OSError, ValueError, RuntimeError):
        print(json.dumps({"case_id": args.case, "policy_accepted": False,
                          "error": "PREFLIGHT_FAILED"}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

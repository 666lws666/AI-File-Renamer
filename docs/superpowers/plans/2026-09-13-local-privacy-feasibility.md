# Local Privacy Feasibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use subagent-driven-development or executing-plans task-by-task. The root owns actual media inspection and permission boundaries.

**Goal:** Prove the pinned Qwen3.5-4B Windows runtime and real naming quality before adding product UI or processing-mode behavior.

**Architecture:** A diagnostic-only resource manifest/downloader validates public byte streams into ignored QA storage. A guarded native runtime probe then loads synthetic fixtures only when memory permits; no product settings are changed. Product integration is a subsequent plan after this gate passes.

**Tech Stack:** Existing Python 3.14 standard library, pinned llama.cpp b10885 CPU archive, Qwen3.5-4B Q4_K_M + F16 visual projector, existing local image/PDF/video fixture tools.

## Global Constraints

- Baseline 488e6fc, isolated branch codex/local-privacy-mode; do not change main, cloud credentials, existing Golden or live configuration.
- Model/runtime downloads use only manifest URLs pinned to exact revision, size and SHA256; no Authorization/cookies/user data.
- Store large resources only below ignored `tests/screenshots/qa-current/local-privacy/`.
- Actual model load requires 5GiB available RAM for this experiment; never close user applications or modify system security/paging.
- Mocks prove downloader boundaries, never model comprehension. No inference PASS without raw model output and human content review.

## Task 1: Verified resource preparation

Files: create `scripts/local_model_probe_resources.py`, `resources/local-models/qwen35-4b-feasibility.json`, `tests/unit/test_local_probe_resources.py`.

Interfaces: `fetch_resource(resource: dict, destination: Path, *, opener=urlopen, cancelled=lambda: False, free_bytes=shutil.disk_usage) -> Path`; `verify_resource(path: Path, resource: dict) -> bool`. A resource contains an exact safe basename, HTTPS URL, byte count and SHA256. Existing verified files are reused; invalid final files are not used or silently deleted. Partial files are kept for restart. Publish a final path only after exact size/hash validation.

- [x] RED tests import the module after asserting its existence; use real temporary bytes and controlled response streams to cover correct hash, corrupt hash, short/oversize body, insufficient disk, cancellation, duplicate cache reuse, unsafe basename, HTTPS-only URL and preserved existing invalid file.
- [x] Run `python -m pytest tests/unit/test_local_probe_resources.py -q`: expected missing implementation FAIL before implementation.
- [x] Implement bounded stream writes to `.part`, safe fixed names, disk reserve, periodic cancellation, trusted HTTPS redirect handling, SHA verification and atomic publish. Do not execute downloaded files in this function. CLI requires `--download` to perform network work and defaults to verification-only.
- [x] Re-run the focused suite until all assertions pass; review no real network usage in tests.
- [x] Run the explicit diagnostic download for the three pinned public resources. Print progress with resource IDs/bytes only; verify all hashes. Inspect the verified archive members before safe extraction (no path traversal, links or unexpected executable names).
- [x] Commit the diagnostic implementation and raw outcome, not model binaries. Implementation checkpoint: `a4f00d9`; final download evidence is in the feasibility report.

## Task 2: Native runtime and real inference gate

Files: create `scripts/probe_local_model_native.py`, `tests/unit/test_local_model_probe.py`, evidence under ignored local-privacy directory; create `docs/reports/2026-09-13-local-privacy-feasibility.md`.

Interfaces: `check_probe_memory(available_bytes: int) -> None` rejects values below `5 * 1024**3`; native subprocess uses an exact verified binary, sanitized environment, bounded output and timeout with tree cleanup. No arguments sourced from content are shell-evaluated.

- [x] RED boundary test: `with pytest.raises(RuntimeError): check_probe_memory(1024**3)`; at 5GiB it passes. Add runtime identity/hash mismatch and deadline negative tests before launching a model.
- [x] Verify runtime `--version` using the trusted CPU archive. Record exact bytes/hashes and license files.
- [x] Check actual free RAM immediately before load. If below the margin, record MEMORY_BLOCKED and do not launch; complete non-inference resource/negative verification, then hand off the concrete resource requirement. Actual inference remains blocked, not passed.
- [ ] When memory permits, use one synthetic text document for initial structured JSON, then image/scan/video frames; record inference duration, exit code, structured result, source fixture IDs, zero cloud calls and manual content judgments. Do not count a model that outputs generic/invented/wrong-language names as semantic PASS.
- [ ] Repeat Chinese/Hong Kong Traditional/English output and template/smart policy checks; verify collision/long-name handling through existing pipeline. Keep model prediction separate from local policy enforcement.
- [ ] Review raw actual results and only then authorize the next process-boundary/resource/product integration plan.

## Task 3: Process isolation design gate

Files: record researched Microsoft per-process sandbox APIs and runtime limitations in the feasibility report; no system firewall changes.

- [x] Compare trusted pinned runtime flags against actual outbound-capable code paths; reject claims based solely on localhost or `--offline`. Research only; no OS sandbox proof yet.
- [ ] Select a no-network-capability process boundary and IPC route that works on Windows Home without user-installed services or security exemptions.
- [ ] If the required boundary cannot be demonstrated, stop downstream local-mode UI integration and report the exact blocker, while preserving smart-naming software checkpoint and verified resources.

Completion of this plan is a prerequisite, not a substitute for the L1–L6 milestones in the design. Each downstream plan is written after its dependency is demonstrated, with exact interfaces and tests rather than pretending unknown runtime behavior is settled.

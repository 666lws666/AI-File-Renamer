# Local inference runner task report — 2026-09-13

## Outcome

Implemented the bounded single-case diagnostic runner and its contract/fault tests in the three assigned files. No real model process was launched by this task. The harness does not claim semantic model quality or outbound OS isolation.

## TDD evidence

- Initial RED: `python -m pytest tests/unit/test_local_inference_probe.py -q` produced 35 errors because `scripts/run_local_inference_probe.py` did not exist.
- First GREEN: the focused file produced `35 passed in 1.33s`.
- Hard-constraint RED: added top-level schema closure, exact public API, prompt/schema hash, source/output fault and second-memory-guard assertions; result was `3 failed, 35 passed in 1.37s` for the three not-yet-implemented behaviors.
- CLI regression RED: direct `python scripts/run_local_inference_probe.py --help` was reproduced as a repository-root import failure; its focused regression test failed once, then passed after the import-path fix.
- Root-review RED: the exact `-f` file-path and pure top-level `oneOf` regressions produced `2 failed in 1.25s`; the runner had incorrectly passed full prompt content where llama expects a prompt-file path. Tests were also moved to a session-generated temporary corpus so ignored QA evidence is not required in a fresh checkout.
- Root real-run RED: case 01 reached `error while handling argument '-f': failed to open file '<Unicode absolute path>\\prompt.txt'`; this was a harness launch failure, not a model-quality result.
- Systematic path-isolation RED/GREEN: a pinned CLI probe with a guaranteed-missing model reproduced failure for the Unicode absolute `-f`, while cwd at the evidence directory plus ASCII `prompt.txt`/`schema.json` passed file handling and stopped at the expected missing-model error. Mock regressions for text cwd/paths, visual relative stills and nonzero exit initially produced `3 failed in 1.54s`; the native diagnostic plus all three then produced `4 passed in 1.40s`.
- Final focused GREEN: `41 passed in 2.75s`.
- Required five-file diagnostic suite: `197 passed in 20.09s` across `test_local_inference_probe.py`, `test_local_model_probe.py`, `test_local_probe_process.py`, `test_local_probe_resources.py`, and `test_local_semantic_corpus.py`.

## Implemented contract

- Named optional roles with modality-constrained evidence, strict false/true `oneOf` branches, and mandatory topic when understood.
- Strict UTF-8, duplicate-key, unknown-key, fence/prose, NaN, truncation and multiple-object rejection. One exact terminal native ` [end of text]` marker may be removed once; arbitrary suffixes remain failures.
- Prompt uses the unchanged policy description once with only the obsolete `understood=false and parts=[]` wire phrase aligned to named roles. It explicitly defines topic/date/entity/context/version, available evidence modalities and untrusted text boundaries; no manifest oracle or source path is loaded into the prompt.
- Verified real preparation for all eight fixed corpus inputs: three UTF-8 texts, both text-PDF layers, image preprocessing, two scanned-PDF pages, and ordered 4/6/8 video frames with timestamps. Prepared vision inputs are new opaque JPEG stills only.
- Entry and immediate-prelaunch 5 GiB checks; pinned archive/model/projector verification and every extracted runtime member checked against the archive; fixed completion/mtmd argument sets with evidence-directory cwd and ASCII relative prompt/schema/visual filenames; minimal five-key environment; bounded process output, timeout, cancellation and cleanup result handling.
- Raw bounded stdout/stderr, prompt/schema plus hashes, source/prepared-input hashes and indices/timestamps, and lifecycle/policy outcome are retained. Process/protocol/policy failure is never repaired or accepted.

## Native versus mocked scope

- Native/local code exercised: a session-generated temporary copy of the real synthetic corpus and SHA256 manifest/source checks; PyMuPDF text extraction/rendering; Pillow image preprocessing; PyAV keyframe extraction; direct CLI help subprocess; read-only verification of the actual pinned archive, GGUF, projector and all extracted runtime files. The latter returned the expected five resource roles.
- Mocked scope: model execution and `run_bounded` results were injected in runner tests. Cancellation, timeout, nonzero exit, output limit and cleanup-incomplete acceptance behavior therefore verifies the runner contract, not a second real native process execution.
- Not established: model semantic quality, visual grounding quality, performance under the full matrix, network denial, or outbound OS isolation. `human_model_quality_reviewed` and `outbound_isolation_verified` remain false in every result.

## Owned files

- `scripts/run_local_inference_probe.py`
- `tests/unit/test_local_inference_probe.py`
- `docs/reports/2026-09-13-local-inference-runner-task-report.md`

## Remaining concerns

- The root-owned real runs already observed that a clean process/JSON result can still fail protocol or policy; this harness intentionally records that negative without changing names or claiming quality. A separate root-owned core-policy defect currently rejects spaced Chinese dates such as `2026 年 8 月`; this task did not modify or work around that validator.
- CPU-only vision inference and image encoding remain expensive; timeout and cleanup bounds are enforced, but the test suite does not predict full-matrix wall time.
- The process job controls lifetime and output bounds, not network access. `--offline` and the minimal environment are behavioral constraints, not proof of outbound isolation.

## Root review correction: post-preparation memory refusal

Independent scoped review found that the second memory check could leave prompt/schema without a result record. Root confirmed this with injected prelaunch low/invalid measurements and a CLI assertion: **3 failed, 40 deselected in 1.52s**. After moving this check behind result construction, the no-child preflight failure is persisted as `MEMORY_BLOCKED` or `MEMORY_CHECK_FAILED`, the CLI includes the evidence directory, and focused tests return **43 passed in 2.40s**. The first entry check still creates no output and launches no process when memory is already low.

The native post-commit attempt was blocked at the *first* guard (subsequent observed available RAM 4,763,938,816 bytes), not proven to have hit the second check. The latter defect is established by source and injected-failure tests, not misreported as a native occurrence. Memory limits were not reduced, and no model was loaded by this correction.

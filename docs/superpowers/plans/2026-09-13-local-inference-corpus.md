# Local Inference Corpus Preparation Plan

> For agentic workers: use subagent-driven-development and test-driven-development. This is a bounded preparation task within the approved real-inference gate, not product integration.

**Goal:** Prepare inspectable, synthetic mixed files with an independent content oracle so actual model quality can later be judged without private files or answer leakage.

**Architecture:** A deterministic source specification and generator create opaque-named TXT, PNG, text PDF, image-only PDF and MP4 files in an ignored QA directory. The manifest records relative paths, checksums and expected facts. Expected facts are reviewer-only and must never be fed to a model as source content. Model execution is not part of this task.

**Tech Stack:** Existing project Python 3.14, Pillow 12.3.0, PyMuPDF 1.28.0 and PyAV 18.0.0. No dependency installation or network.

## Global constraints

- Work only in `D:\文件AI-AGENT\.worktrees\ai-smart-naming`, branch `codex/local-privacy-mode`, baseline `f7ed1737e2c45d6e75f3529ea7d0b06d5e078b37`.
- Do not modify product `src/`, Provider/config/credential code, existing tests, Golden, package inputs or large resource files. No API, real credentials, private files, model loading, push or merge.
- Artifact output is restricted to the caller-supplied new directory or test temporary directory; root's actual capture uses `tests/screenshots/qa-current/local-privacy/semantic-corpus-v1/`.
- Never overwrite a pre-existing destination. Fixed opaque basenames carry no semantic hints. No recursive deletion of caller data. On failure, do not publish a successful manifest.
- No actual model quality result may be marked passed. Keep `actual_inference_run=false` and `human_model_quality_reviewed=false` in generated metadata.
- Keep the 5GiB available-memory guard unchanged. Corpus generation is not a model load and uses bounded images/video only.

## Task 1: Synthetic corpus and real media validation

**Own exactly:** new `scripts/prepare_local_semantic_corpus.py`, new `tests/unit/test_local_semantic_corpus.py`, and task report `docs/reports/2026-09-13-local-corpus-task-report.md`.

**Interfaces:** `prepare_corpus(destination: Path, *, font_path: Path | None = None) -> dict` returns the generated manifest after validating all written media. A default font is resolved below the Windows font directory derived from the OS environment (not a developer installation path); missing usable CJK font fails clearly. CLI defaults to the ignored QA path above and refuses an existing destination. Main agent handles invocation and visual review. No model or product API imports are needed.

**Eight exact cases (opaque case_01 through case_08 basenames):**

1. `case_01.txt`: a Chinese August 2026 campus network maintenance report from fictional 海岚实验室, project 星桥, version v2.1, replacing failed switches in the library and east teaching building. Oracle: distinguish network maintenance and locations; date precision month, never invent a day.
2. `case_02.txt`: Chinese 山岚社区 rain-garden maintenance guidance: clear sediment at inlets, preserve drainage and inspect after heavy rain. Explicitly no date, author, version or legal company name in the source. Oracle must prohibit those invented fields.
3. `case_03.txt`: an English detailed North Pier archive digitisation migration assessment comparing OCR accuracy and retention rules for invoices versus engineering drawings; include multiple paragraphs, known version v3.2, but no date. Oracle requires a concise specific theme rather than copying all paragraphs or a generic report label.
4. `case_04.png`: 1200x900 clear Chinese warehouse fire-evacuation diagram. Draw room outlines, two exits, arrows and an assembly area; visibly label 北区仓库, 消防疏散路线, 出口A, 出口B, 集合点. The visible graphic, not a filename, conveys the purpose; no date/version.
5. `case_05.pdf`: a two-page genuine text-layer English fictional Cedar Research Library scanner evaluation: page 1 covers bound-book scanning, page 2 compares colour calibration and OCR errors. Use page numbers and distinct page headings. No date/version unless explicitly part of this specification (none are).
6. `case_06.pdf`: a two-page image-only Chinese scan, no searchable text. Page 1: 青禾咖啡馆 coffee-machine maintenance confirmation, August 2026, equipment CM-20; page 2: boiler descaling and seal replacement, version v1.1. Render readable CJK raster pages with page numbers, then embed those images; do not add a hidden text layer.
7. `case_07.mp4`: short local synthetic 6-second, 8fps, 640x360 video showing three visually distinct plant-propagation stages (剪枝 / 水培生根 / 移栽) using drawings plus readable Chinese labels. Encode with an available local PyAV software codec, no subprocess/network. Decode and verify ordered frames; future model input is extracted keyframes, never the complete video.
8. `case_08.png`: blank white 800x600 image with no hidden data/labels. Oracle: insufficient content, no invented topic/date/organisation.

**Outputs:** source media; PNG previews for both pages of each PDF and representative video stages; one contact sheet; `manifest.json` with schema_version=1, eight unique case IDs, kind, relative source path, byte count, SHA256, expected/prohibited facts, and explicit unrun model-review flags. Relative output paths must resolve under destination. Do not copy fonts or model files. Keep total generated bytes under 32MiB.

- [x] RED: first write tests requiring the generator file/API, eight IDs/formats, output containment, nonempty valid hashes, missing CJK font failure and refusal to overwrite existing content. Run `python -m pytest tests/unit/test_local_semantic_corpus.py -q` and record expected failures before implementation.
- [x] Implement the minimal fixed corpus generator. Use bounded Pillow images and OS CJK font, PyMuPDF page creation/rendering, and PyAV encode/decode. Write manifest last only after real reopen/validation. Example invariant: `assert not fitz.open(scan_path)[0].get_text().strip()`; validate both scan pages, not just one.
- [x] Extend RED/GREEN tests to verify text PDF extraction includes page-specific facts; both scanned PDF pages have zero text and actual embedded images; rendered previews have expected dimensions; MP4 decodes 48 frames in temporal order with three visibly distinct stages; blank image is genuinely uniform white; total bytes < 32*1024**2. Do not claim those mechanical assertions establish semantic model comprehension.
- [x] Run all new tests and existing `tests/unit/test_local_probe_resources.py tests/unit/test_local_model_probe.py`; report exact raw summaries. Root independently inspects generated images before accepting corpus quality.
- [x] Write the report with RED/GREEN, actual file list and limitations; freeze files without committing. Root performs review and makes an isolated commit after evidence checks.

## Preparation evidence

Task 1 is implemented and accepted after independent review. Root visually inspected the fixed corpus; review then found timeline/stage checks present only in tests. Commit `66020f7` moved them into runtime validation before publication and passed independent re-review. The final corpus suite has 22 tests; the four local diagnostic suites passed 156 tests together. See `docs/reports/2026-09-13-local-corpus-task-report.md` for exact evidence. Actual inference and model-quality review remain unrun.

## Subsequent gate (not completed by this preparation)

Build a bounded native inference runner only against verified installed CLI capabilities, fixed resource identities, explicit local inputs, sanitized environment, output/deadline/cancellation limits and process-tree cleanup. It must refuse model load while available RAM is below the unchanged guard. Actual outputs then pass through the existing smart policy and independent human content review in zh-CN/zh-HK/en-US. The CLI's `--help` advertisement of JSON/image flags is not proof of model compatibility, privacy isolation or quality.

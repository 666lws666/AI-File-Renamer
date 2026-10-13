# Local Inference Corpus Preparation Task Report

Date: 2026-09-13
Branch: `codex/local-privacy-mode`
Baseline HEAD: `f7ed1737e2c45d6e75f3529ea7d0b06d5e078b37`
Scope: synthetic diagnostic corpus preparation only; no product integration

## Result

Implemented the fixed eight-case synthetic corpus generator and its unit tests. The generator writes only to a caller-supplied new directory, refuses any pre-existing destination, validates written media by reopening it, and writes `manifest.json` last. It does not import product/provider code, access credentials, open a network connection, load a model, or change any Golden file.

Generated metadata keeps both review gates explicitly unrun:

- `actual_inference_run=false`
- `human_model_quality_reviewed=false`

Mechanical media assertions do not establish model comprehension or naming quality. Root subsequently completed independent visual inspection and implementation review; the appended evidence below supersedes the implementer's initial file-freeze status. Model-generated naming quality remains unreviewed because inference has not run.

## Owned files

- `scripts/prepare_local_semantic_corpus.py` (new)
- `tests/unit/test_local_semantic_corpus.py` (new)
- `docs/reports/2026-09-13-local-corpus-task-report.md` (new)

No files outside this ownership set were modified by this task. The untracked plan file was supplied by the controller and was not edited.

## TDD evidence

All commands used `D:\文件AI-AGENT\.venv\Scripts\python.exe` from the isolated worktree.

An initial fixture formulation classified the missing script as setup errors (`5 errors in 0.17s`). It was corrected before implementation so the valid RED was a direct, expected assertion failure rather than a collection/setup error.

### Initial API, cases, containment, hash, font and overwrite contract

RED command:

```text
python -m pytest tests/unit/test_local_semantic_corpus.py -q
```

Raw summary:

```text
Fssss                                                                    [100%]
FAILED tests/unit/test_local_semantic_corpus.py::test_generator_script_and_api_exist
1 failed, 4 skipped in 0.15s
```

Expected failure: `scripts/prepare_local_semantic_corpus.py` did not exist.

GREEN raw summary after the minimal generator:

```text
.....                                                                    [100%]
5 passed in 1.63s
```

### Real PDF, raster, video and size assertions

The first extended run exposed one intentionally missing behavior (within-stage video evolution) and one overly layout-sensitive PDF title assertion:

```text
.....F.F.                                                                [100%]
2 failed, 7 passed in 4.34s
```

The PDF test was corrected to normalize extracted whitespace. The resulting valid RED isolated the missing behavior:

```text
.......F.                                                                [100%]
FAILED tests/unit/test_local_semantic_corpus.py::test_video_decodes_exact_ordered_duration_with_motion_inside_each_stage
1 failed, 8 passed in 4.29s
```

Expected failure: each propagation stage repeated a static drawing. The implementation then added continuous pruning, root-growth/bubble and transplant-growth changes while retaining 48 ordered frames at 8 fps and 640x360.

GREEN raw summary:

```text
.........                                                                [100%]
9 passed in 4.36s
```

### Manifest-last failure behavior

RED used a real generated two-page scan and then replaced it with a real invalid one-page PDF before final validation:

```text
.........F                                                               [100%]
FAILED tests/unit/test_local_semantic_corpus.py::test_failed_written_media_validation_never_publishes_manifest
1 failed, 9 passed in 5.10s
```

Expected failure: corrupt media was not yet rejected before manifest publication.

GREEN after central write-then-reopen validation:

```text
..........                                                               [100%]
10 passed in 4.99s
```

### Deterministic source hashes

An independent double-generation check found that PyMuPDF's default random document IDs made only `case_05.pdf` and `case_06.pdf` hashes differ. This was converted into a regression test.

RED raw summary:

```text
..........F                                                              [100%]
FAILED tests/unit/test_local_semantic_corpus.py::test_source_hashes_are_deterministic_across_fresh_destinations
1 failed, 10 passed in 6.45s
```

GREEN after saving both PDFs with `no_new_id=True`:

```text
...........                                                              [100%]
11 passed in 6.42s
```

## Final regression evidence

Exact required command:

```text
python -m pytest tests/unit/test_local_semantic_corpus.py tests/unit/test_local_probe_resources.py tests/unit/test_local_model_probe.py -q
```

Raw summary:

```text
........................................................................ [ 69%]
................................                                         [100%]
104 passed in 6.79s
```

## Actual generated inventory

A fresh generation in a new system temporary directory produced 17 files totaling 676,341 bytes (671,450 bytes before `manifest.json`), below the 32 MiB limit:

```text
case_01.txt
case_02.txt
case_03.txt
case_04.png
case_05.pdf
case_06.pdf
case_07.mp4
case_08.png
contact_sheet.png
manifest.json
previews/case_05_page_1.png
previews/case_05_page_2.png
previews/case_06_page_1.png
previews/case_06_page_2.png
previews/case_07_stage_1.png
previews/case_07_stage_2.png
previews/case_07_stage_3.png
```

The source basenames remain opaque. Expected and prohibited facts exist only in reviewer metadata and are not embedded as model input instructions.

## Mechanical validation performed

- Text files are UTF-8 source documents with the specified synthetic facts and omissions.
- `case_04.png` reopens at 1200x900; `case_08.png` reopens at 800x600 and is uniform RGB white.
- `case_05.pdf` reopens as two pages with a genuine searchable text layer, distinct headings and page-specific facts.
- Both pages of `case_06.pdf` reopen with zero extracted text and at least one embedded raster image per page.
- All four PDF page previews reopen at 600x800.
- `case_07.mp4` is encoded locally through PyAV/libx264, decodes to exactly 48 timestamp-ordered 640x360 frames at 8 fps, preserves the three-stage order, and has measurable visible change within every 16-frame stage.
- Three representative video previews reopen at 640x360.
- The contact sheet reopens at 1200x620.
- All manifest source hashes are SHA-256 over non-empty files and are identical across two fresh generations.
- All manifest relative paths resolve beneath the supplied destination.
- The complete output, including the manifest, remains below 32 MiB.

## PDF workflow note and limitations

The PDF skill's container marker script is unavailable on this native Windows installation. Per the controller's documented fallback, the task used the already-installed PyMuPDF 1.28.0 to author synthetic PDFs, reopen both files, inspect page and image objects, and render every page to PNG. No dependency was installed.

The worker did not publish a fixed QA corpus because the plan assigns that invocation and visual review to the root task. Automated checks confirm structure, dimensions, extraction behavior, decodability, order and bounded size; they do not prove typography, visual semantics, OCR/model understanding, privacy isolation of a future runner, or model-generated naming quality. Those gates remain explicitly unpassed.

## Root visual review and focused correction

The root independently generated the fixed corpus and inspected the contact sheet, both text-PDF pages, both scanned pages, the diagram and all three video previews. Chinese text was readable; PDF pages were upright with the expected separate contents and visible page indices. The three video stages were visibly distinct. The first diagram had its Exit A label partly covered by an arrow; this was a source-fixture defect, not a model error.

The label was moved into the arrow-free area. A real pixel test first failed (`1 failed in 1.41s`), then passed (`1 passed in 1.18s`); the entire corpus file passed 12 tests. The root regenerated into a new directory, inspected the corrected diagram and confirmed both exit labels are unobscured. No prior evidence was overwritten.

Accepted source corpus: `tests/screenshots/qa-current/local-privacy/semantic-corpus-v1-reviewed/`. It contains **17 files / 676,809 bytes**. Manifest SHA256: `CD820442DFFCB12C8C71DAF804C8C88FE87E46A0E4760A68A8E175BA99639D8B`. The earlier `semantic-corpus-v1/` is retained as failed visual evidence and must not be used for the subsequent model-quality experiment.

Fresh root command: `python -m pytest tests/unit/test_local_semantic_corpus.py tests/unit/test_local_probe_resources.py tests/unit/test_local_model_probe.py -q` → **105 passed in 7.56s**, zero skips or warnings. Source/preview structural and visual preparation is accepted; actual inference and human review of model-generated names remain **not run**. No privacy boundary is established by these fixtures.

## Independent review correction

Review of checkpoint `82bb476` confirmed the corpus scope and safety but found that rate/ordered timestamps/stage order were enforced by tests only, not the generator's manifest-publication path. The root verified that distinction and added `_validate_video_frames` to the real decode path before preview/manifest publication. It checks 8fps, 48 correctly sized frames, the exact finite 0-to-5.875-second sequence at 1/8-second intervals, decoded stage colours/order and within-stage motion. This is mechanical source validation, not model comprehension.

RED: six new invalid rate/time/order/count variants failed, with three source-text anchor checks already passing: **6 failed, 3 passed, 12 deselected in 7.45s**. GREEN after implementation: **21 passed in 14.11s**. An additional integration fault confirms that rejecting the decoded video prevents `manifest.json` publication. The text anchors guard the three UTF-8 fixtures against accidental fact drift. This validation-only change does not alter generated media or the accepted corpus hash.

The review oracle contains facts to check, not a mandatory list of filename components. Actual naming may omit secondary facts; it must preserve the specific main subject and avoid invented details. Technical media properties such as fps are not required in a filename. No oracle data may be sent as input to the model.

Independent re-review of `66020f7` approved the corpus implementation with no outstanding findings. A final fail-closed publication test brings the corpus suite to 22 tests. Root ran the combined corpus/process/resources/preflight suites: **156 passed in 17.69s**, zero skips or warnings. The corpus is accepted as synthetic input evidence, not as a model-quality result.

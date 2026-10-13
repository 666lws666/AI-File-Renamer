# Local privacy feasibility — not a feature-complete delivery

## Baseline and scope

The smart-naming checkpoint is `488e6fcaedd9c71edf747bcc78c2fecc4bc4b9ea`. The new work is on isolated branch `codex/local-privacy-mode`, in the same existing worktree. The resource-preparation checkpoint `a4f00d9af3675dbf013a989a9da5a993a0ec43e8` changes no product source, UI, settings, Watch configuration or Golden files. A subsequently reproduced Batch attempt-identity defect is receiving a separate bounded safety correction; it is not local-mode product integration. Main and the public snapshot are untouched; no push/release.

The accepted resource manifest is `resources/local-models/qwen35-4b-feasibility.json`. The resource scripts are diagnostics, not the final user-facing downloader or local engine.

## Evidence already obtained

- Official post-trained Qwen3.5-4B source revision and Apache-2.0 license verified; the selected Unsloth Q4_K_M quantization declares that source as base, not Base or another fine-tune. Quantization conversion has not been independently reproduced.
- Runtime `llama-b10885-bin-win-cpu-x64.zip`: 18,425,079 bytes, published SHA256 matches `b96fd3b2dfa7add41b0d80f93599931d839b54b4b804abc4b295bd4039dc96f1`.
- Verified archive: 51 flat members, 46,749,981 uncompressed bytes. All extracted executable/DLL bytes are rechecked against the pinned archive before version smoke.
- Actual Windows output: `version: 0.4.0-dev (build 10885, commit d7e86430a)` / `built with Clang 20.1.8 for Windows x86_64`.
- This is an upstream prerelease engineering candidate; no model was loaded by `--version`, and no production stability claim is made.
- Model and runtime licenses were fetched from pinned official sources into ignored QA storage; SHA256 respectively `bbedc3fda3305820b977265f01b8619d87570a6739de3a5582c3464840f1e57a` and `94f29bbed6a22c35b992c5c6ebf0e7c92f13b836b90f36f461c9cf2f0f1d010d`. The runtime archive also includes the LLVM OpenMP notice.

## Resource preparation tests

`scripts/local_model_probe_resources.py` defaults to offline verification. Network operation requires `--download`; resources are fixed HTTPS URLs with exact length and SHA256. It preserves invalid existing finals, bounded partials and cancellation prefixes; resumes only with exact Content-Range; verifies before atomic no-overwrite publication. Tests cover disk reserve, oversize/short/corrupt output, timeouts, unsafe names/URLs/redirects, hardlinks and concurrent final-file races.

Real download diagnostics found two environment facts:

1. Direct Python HTTP timed out; native Windows HTTP succeeded. System proxy entries were checked for username/password absence. A diagnostic explicit uncredentialed proxy opener was used only for public model resources, with the same trusted HTTPS redirect handler. No proxy credentials, cookies or user content were sent. The default production-independent script remains direct-only; user-facing proxy support is a future resource-management requirement, not claimed here.
2. Hugging Face now redirects to `us.aws.cdn.hf.co`. This host and `us.gcp.cdn.hf.co` were verified against https://huggingface.co/docs/hub/models-downloading and added as exact redirect-only hosts. Similar malicious suffixes and use as initial source remain rejected. No wildcard or security exception was installed.

Focused tests: **77 resource tests + 16 native-preflight tests = 93 passed**. Resource implementation had a recorded RED before GREEN, plus 2 RED cases for the newly observed official CDN. Native-preflight implementation had 13 RED cases, followed by 2 RED status cases, before all 16 passed.

Complete regression after the final CDN fix: **1965 passed, 1 existing skipped, 3 existing Pydantic warnings**. Screenshot tests, updates disabled: **49 M1 passed + 5 M0 passed, 1 expected M0 update-mode skip**. Current-worktree acceptance: **186/186**. No screenshot test assertions or Golden files were changed by this stage.

## Actual runtime blocker

Host: i5-13420H, 8 cores/12 logical processors, Intel UHD integrated GPU, 16,891,371,520 physical RAM bytes. Free disk is ample. Available physical memory measured between roughly 1.0 and 1.7GiB; pagefile was already using roughly 15GB before model loading.

For this initial 4B Q4 + F16 visual experiment the diagnostic guard requires **5GiB currently available RAM**. This is a conservative experiment safety margin, not a measured product minimum. The actual native preflight returned exit **3**, `MEMORY_BLOCKED`, including a successful runtime version and:

```json
{
  "actual_inference_run": false,
  "semantic_quality_verified": false,
  "outbound_isolation_verified": false
}
```

No other user applications were closed, no pagefile/firewall settings changed and no lower model substituted. Model inference, naming-quality evaluation and end-to-end privacy activation remain unrun. Do not add a misleading ready switch or claim the feature is delivered.

## Integration findings to carry forward

- Batch and Watch currently get separate analysis-service instances. Bootstrap must own one live mode/epoch/dispatch authority injected into both and into connection tests; every retry must recheck at actual dispatch, not only import/admission.
- Current blocking urllib combines connect/upload/read. Define an honest dispatch linearization point; do not promise network bytes were already transmitted merely because a permit existed. Local selection must not wait for a full network timeout before closing new admission.
- Watch handlers currently do not pass cancellation tokens to analysis. Batch task-ID reuse was independently reproduced as a cancellation/completion defect and corrected in `481e2b0` below; the future shared mode/dispatch epoch remains unimplemented.
- Local routing must not read cloud credentials or reuse arbitrary user localhost Providers. Separate bounded local extraction from cloud-upload consent checks.
- Production Batch currently does not use CacheManager. Future cache wiring needs processing source, model artifact hash, runtime identity and smart policy context; do not claim current cache UI is already an enforced local/cloud boundary.
- Workspace/Undo/Watch histories intentionally retain local paths and suggested names. Do not claim zero local traces. Keep sensitive prompts/media out of logs and diagnostics.

## Process isolation research (not yet executed)

`--offline` is not a process-wide network restriction: upstream remote-media paths can still perform HTTP. Modern llama-cli itself has internal server/HTTP behavior. `llama-mtmd-cli` is explicitly a development tool. Production packaging requires a reviewed direct-inference worker and a demonstrated process boundary, not a renamed localhost adapter.

The investigated option is a current-user AppContainer with no network capabilities, minimal runtime/model directory access, inherited anonymous pipes and Job Object lifetime control. Job Objects alone are not network isolation. Do not install loopback exemptions or system firewall changes. AppContainer profile/directory permissions and DLL/IPC compatibility must be tested with fail-closed behavior before claiming protection.

Sources: https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer ; https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-createappcontainerprofile ; https://learn.microsoft.com/en-us/windows/win32/procthread/creating-a-child-process-with-redirected-input-and-output ; https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects ; https://github.com/ggml-org/llama.cpp/blob/master/tools/cli/cli-context.cpp . Research is not an OS isolation test result.

## Nonblocking diagnostic hardening backlog

The diagnostic extractor is used only on the exact pinned archive in our own ignored directory. Before adapting it into a general offline-package importer, reject Windows device basenames and directory reparse ancestry. Also rename its memory-only `READY_FOR_INFERENCE_EXPERIMENT` state to a narrowly scoped memory-ready signal; all quality/privacy flags already remain false. Independent review found no deterministic P0/P1 in the current pinned diagnostic flow.

## Resume

Do not start product integration until real model loading/quality can be evaluated safely. Recheck available RAM after the user closes unneeded applications or restarts; do not close them on the user's behalf. Then verify all downloaded resources, run the mixed synthetic content experiment, prove process outbound denial and proceed through the documented L1–L6 milestones.

## Download completion and offline recheck

All three pinned resources finished downloading and passed a fresh offline size/SHA256 check:

| Resource | Exact bytes | SHA256 |
|---|---:|---|
| CPU runtime ZIP | 18,425,079 | `b96fd3b2dfa7add41b0d80f93599931d839b54b4b804abc4b295bd4039dc96f1` |
| Qwen3.5-4B Q4_K_M GGUF | 2,740,937,888 | `00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4` |
| F16 visual projector | 672,423,616 | `cd88edcf8d031894960bb0c9c5b9b7e1fea6ebee02b9f7ce925a00d12891f864` |

Total: **3,431,786,583 bytes**. Resources remain in ignored `tests/screenshots/qa-current/local-privacy/resources/`; they are not added to Git or the Windows product bundle. Two real short-response interruptions retained resumable partial data; the completed model's whole-file SHA256 verified after recovery. A fresh offline check printed `VERIFIED` for all three files. No private filenames/content or model inference prompts were sent with resource downloads.

The post-download Windows preflight measured **1,631,191,040 available physical-memory bytes**, below the experiment's 5GiB margin, and again reported `MEMORY_BLOCKED`. Its verified native runtime version command succeeded. Model inference, content-quality checks, process outbound-denial tests and local-mode UI integration are **not run / not delivered**.

## Confirmed Batch safety defect (separate from local-mode delivery)

A no-network reproduction used the real Batch controller with a memory-only Future scheduler. After cancelling an old queued job and retrying the same task ID, the old worker read the replacement job's uncancelled token. Its completion saved `old-result.txt` into the retry row and removed the new token; the subsequent `new-result.txt` completion was ignored. This is a deterministic P1 cancellation/result-ownership defect, not evidence of an observed real cloud upload.

Correction commit: **`481e2b0f924d4916b73921dcac95b5d315fe972c`**, limited to `batch_workspace_controller.py` and a new focused regression file. Each attempt now owns a UUID and an Event bound at submission; stale completions are rejected before touching the current task or cancellation mapping. Queued cancelled work does not call the analyzer, including tokenless legacy analyzers. Cancel/ignore/stop/clear invalidate only after successful workspace persistence, and close prevents new submissions. No change to analyzer parameters, QML calls or persisted task schema.

Recorded RED: **10 failed, 6 passed**. GREEN: **16 new tests passed; 31 new/existing Batch tests passed**. A separate reviewer independently replayed both queued-old-work and delayed-old-completion sequences against the corrected code; both preserved the new token and adopted the new result. No deterministic P0/P1 remained within the bounded correction.

One P2 remains: if a future synchronous `tasksChanged` consumer immediately retries during a cancellation notification, the subsequent invalidation should be guarded with the expected attempt. No such production consumer was found. Keep this in the integration backlog rather than expanding the present gate.

## Post-correction regression

All commands used the project Windows Python 3.14 interpreter, isolated test data and fake credentials. No source assertions, pixel tolerances or Golden files were changed to obtain a pass.

- An initial full run explicitly forced `QT_QPA_PLATFORM=windows` into the component suite: **15 failed, 1966 passed, 1 skipped** (114.90s); failures were all Provider-card click/form cases. That suite declares an offscreen component fixture, not a standalone native-screen gate. This unsuccessful run is not hidden or counted as passing.
- Without source/test edits, the entire Provider component file under its declared offscreen backend passed **31/31** (4.24s).
- Full non-screenshot suite, `QT_QPA_PLATFORM=offscreen`: **1981 passed, 1 existing skipped, 3 existing Pydantic warnings** (49.68s).
- M1 visual capture on **native Windows**, scale factor 0.8 to preserve the approved 100% baseline dimensions, `UPDATE_GOLDENS` absent: **49 passed** (38.93s); 82 existing Pillow deprecation warnings. Runtime-warning and semantic-state assertions passed.
- M0 screenshot suite in its established environment, update mode absent: **5 passed, 1 expected update-mode skip** (0.45s); 4 existing Pillow deprecation warnings.
- Current-worktree `acceptance_test.py`: **186/186, 0 failed**.

Offscreen component tests are not substituted for native evidence: the separately executed M1 capture and isolated packaged smoke are the native gates. The product's local-mode inference and outbound-denial gates remain unrun regardless of these software regressions.

## Rebuilt Windows artifact and final handoff

Built from product-source commit **`481e2b0f924d4916b73921dcac95b5d315fe972c`** using `scripts/build_windows.ps1 -SkipClean -PythonPath D:\文件AI-AGENT\.venv\Scripts\python.exe`; build exit 0. A subsequent report-only commit does not change the executable's source. The known optional Qt asset-downloader plugin warning remains; build and runtime gates passed.

- EXE: `D:\文件AI-AGENT\.worktrees\ai-smart-naming\dist\Xuxia\Xuxia.exe`.
- EXE size: **10,963,324 bytes**.
- SHA256: **`B21DF94455723A90E74492647566EC00EE1C75F62EF57084A3687099C33517B9`**.
- Distribution: **3,137 files / 576,125,153 bytes**, including the three-language HTML manual. Large model/projection/runtime experiment files are excluded.
- Fresh packaging tests: **23 passed, 3 existing warnings** (12.49s), including the isolated packaged EXE and full source-asset agreement checks.
- Additional direct EXE smoke with `QT_QPA_PLATFORM=windows`: **exit 0**, status `ok`, `qml_warning_count=0`, ephemeral credentials; image/PDF/video/diagnostic dependencies passed. Report: `tests/screenshots/qa-current/local-privacy/final-exe-smoke-1cb47960522f489ea1fb36add32907d8/report.json`.
- Latest runtime-plus-memory preflight: **2,234,159,104 available bytes**, still `MEMORY_BLOCKED`; verified runtime version remains build 10885/d7e86430a. All actual-inference/semantic/outbound-isolation flags remain false.

Resume in **`D:\文件AI-AGENT\.worktrees\ai-smart-naming`**, branch **`codex/local-privacy-mode`**; do not use a historical main HEAD as this branch's source. The main checkout stays at `4feb71200c08b18f0fe550295b624f9915577ae1`; its existing user shortcut is untouched. No merge, push, release, real cloud API, private test data, real credential access or additional Golden update occurred.

Next required external condition: the user closes unneeded applications or restarts, leaving at least the experiment's **5GiB free-RAM safety margin**. This is not a measured minimum system requirement and does not establish that the machine can never run the model. Do not close applications or change paging/security settings on the user's behalf. Recheck resources offline and native memory, implement the bounded synthetic real-inference harness, inspect actual text/image/scan/video-frame naming outputs, then prove the process privacy boundary before downstream product integration. The prepared resources should be reused, not downloaded again.

Delivery boundary: smart naming, three-language manuals and the Batch safety fix have software/visual/package evidence; real model semantic quality is not claimed. Managed local privacy mode, its UI/download manager/offline importer, shared Batch/Watch cloud lockout, sandbox and offline end-to-end tests remain **not implemented or not verified**, as specified by their pending plan checkboxes. Do not label this partial milestone project-complete.

## Continued preparation and final verification — 2026-09-13

Three diagnostic-only checkpoints preserve product source, QML, main checkout and Golden files:

- `82bb47676c6d97c726aea69d7424cdf26bde41dc`: deterministic mixed synthetic corpus and tests.
- `577679266d4542d83a4946dae8a4bfd51fb01406`: bounded Windows process lifetime/cancellation/output diagnostic and real child-process tests.
- `66020f7e1e8f74e996270bc93afbacf4cac9d3e3`: runtime MP4 timeline/stage validation before corpus publication, after independent review found these checks were previously test-only.

Accepted corpus: `tests/screenshots/qa-current/local-privacy/semantic-corpus-v1-reviewed/`; eight synthetic sources, 17 files, **676,809 bytes**. Manifest SHA256: **`CD820442DFFCB12C8C71DAF804C8C88FE87E46A0E4760A68A8E175BA99639D8B`**. Root inspected every PDF page, the diagram and all three video-stage previews. Chinese text is readable, page directions/indices are correct, and the diagram's obscured Exit A was fixed. The earlier `semantic-corpus-v1/` remains failed visual evidence and must not be used for inference. Reviewer-only expected/prohibited facts must never enter a model prompt as source content.

Existing local media preprocessors were exercised against this corpus, without a model or network:

- Diagram: resized image, 1200x900, 63,370 bytes; blank-image negative sample: 800x600, 3,375 bytes.
- Both PDFs: page indices `[0, 1]`, each 1200x1600. Text-PDF image payloads: 84,435/84,068 bytes; scanned-PDF: 73,671/69,102 bytes.
- Six-second video: economy **4** frames at `[0.75, 2.25, 4.0, 5.25]` (63,156 bytes); balanced **6** at `[0.5, 1.5, 2.5, 4.0, 4.75, 5.5]` (93,864 bytes); quality **8** at `[0.375, 1.25, 1.875, 2.625, 4.0, 4.75, 5.25, 5.75]` (125,369 bytes). Payloads contain local images/rendered pages/video keyframes, not complete PDF/video or source paths.

Independent corpus re-review approved the correction without remaining findings. Process-helper review approved with one P2: a shared cleanup/drain deadline can leave trailing output unread while reporting lifecycle completion. This source-derived case was not independently reproduced; record it rather than claim output completeness. The helper is not yet used by product inference; a Job Object is not outbound/network isolation.

Fresh root verification at `66020f7`, project Windows Python 3.14:

| Gate | Actual result |
|---|---|
| Corpus/process/resources/preflight diagnostic suites | 156 passed in 17.69s; no skips/warnings |
| `pytest tests/ --ignore=tests/screenshots -q` (offscreen component fixture) | 2044 passed, 1 existing skipped, 3 existing Pydantic warnings in 67.21s |
| M1 screenshot suite, native Windows, approved scale, update OFF | 49 passed, 82 existing Pillow warnings in 35.59s |
| M0 screenshot suite, established environment, update OFF | 5 passed, 1 expected update-mode skipped, 4 existing Pillow warnings in 0.45s |
| `acceptance_test.py` | 186/186, zero failed, exit 0 |
| `pytest tests/packaging -q` | 23 passed, 3 existing Pydantic warnings in 7.30s |
| Additional native Windows isolated EXE smoke | Exit 0; status ok; QML warnings 0; ephemeral credentials; image/PDF/video/diagnostics ok |

Fresh native report: `tests/screenshots/qa-current/local-privacy/final-native-smoke-452b8bd608964555862473eee06848df/report.json`. The product artifact was reused, not rebuilt for diagnostic-only changes: **10,963,324 bytes**, SHA256 **`B21DF94455723A90E74492647566EC00EE1C75F62EF57084A3687099C33517B9`**, distribution **3,137 files / 576,125,153 bytes**. Packaging tests verify current product asset agreement. It does not contain a working local privacy mode.

Final offline verification again passed all three resource sizes/hashes. Native version smoke succeeded; final preflight measured **1,047,670,784 available physical-memory bytes**, exiting **3 / MEMORY_BLOCKED**, below the unchanged **5,368,709,120-byte** experimental margin. No model was loaded. Actual-inference, semantic-quality and outbound-isolation flags remain false. No applications were closed or system security/paging settings altered.

Resume after available RAM changes: reuse verified resources and accepted corpus; recheck memory; implement/run the bounded actual-inference harness and review real names in all three languages, then validate outbound denial before product integration. Local-mode UI, managed resource workflow, shared Batch/Watch dispatch protection and offline end-to-end gates remain open. No push, merge, public release, real cloud API/credential access or new Golden update occurred.

## Latest resumed-work handoff — overrides earlier pending-runner status

Current worktree is still `D:\文件AI-AGENT\.worktrees\ai-smart-naming`, branch `codex/local-privacy-mode`. Tested code HEAD: **`a1bd3e66de1b94133c2ef322447d68213bd7081d`**. Subsequent handoff/plan changes are documentation only. Main checkout remains **`4feb71200c08b18f0fe550295b624f9915577ae1`**, branch `feature/xuxia-m0-foundation`, with only the pre-existing untracked user shortcut; do not replace or delete it.

### Completed in this continuation

- Native Qwen model execution was demonstrated twice while RAM was available: text-only 45.24s and one diagram 208.98s. **Both naming results failed their contract/policy**, so this is not semantic-quality acceptance. Exact outputs and limits are in `2026-09-13-local-inference-observations.md`; the first ad-hoc outputs were tool-transcript evidence, not a completed durable matrix.
- `38f482c7b010c7fbdc74198b9ebc30c6df3ec916` adds the fixed eight-case diagnostic runner, pinned-resource/corpus checks, real preparation, strict named-role schema/decoder, raw evidence and bounded process integration. A real CLI invocation found Unicode absolute prompt-file reading failure; controlled no-model tests verified evidence-cwd plus ASCII relative prompt/schema/visual names fixes file reading. No files/resources were moved or redownloaded.
- `7673c28bf56ec9ffd1df11e2ee95a96f51db8ba6` fixes the independently reproduced date-evidence false rejection for `2026 年 8 月`, with 20 precision/grounding/date/range tests. Root RED 8 failed/86 passed; focused integration GREEN 162 passed. Independent review approved.
- `a1bd3e66de1b94133c2ef322447d68213bd7081d` records a post-preparation memory refusal durably, without launching a child. Root RED 3 failed/40 deselected; focused GREEN 43 passed. Independent re-review closed the sole runner finding. Entry low-memory rejection still creates no files/processes.
- AppContainer diagnostic plan is prepared at `docs/superpowers/plans/2026-09-13-appcontainer-feasibility.md`. **It has not been executed:** no profile, ACL, firewall, loopback exemption or other system-security change occurred. L1 still depends on usable actual inference/quality.

### Fresh regression on current code

| Gate | Actual result |
|---|---|
| Complete non-screenshot pytest | **2107 passed, 1 existing skipped, 3 existing Pydantic warnings in 75.99s** |
| M1 dynamic screenshots, native Windows / established scale / UPDATE off | **49 passed, 82 existing Pillow warnings in 39.29s** |
| M0 dynamic screenshots, established environment / UPDATE off | **5 passed, 1 expected update-mode skipped, 4 existing Pillow warnings in 0.43s** |
| Acceptance script | **186/186 passed, zero failed, exit 0**; keyring functions patched to the in-memory test store |
| Packaging tests after rebuild | **23 passed, 3 existing Pydantic warnings in 6.02s** |
| Additional Windows-QPA isolated EXE smoke | **Exit 0; status ok; QML warnings 0; ephemeral credentials; image/PDF/video/diagnostics ok** |

Source dates/limits were not weakened to force a model result. Formal Golden files are unchanged. Deprecation warnings remain maintenance backlog, not suppressed tests. Build also reports the optional Qt asset-downloader plugin and missing tzdata hidden-import warnings; neither caused the tested runtime gates to fail. No unsupported claim about every timezone path is made.

Rebuilt using `scripts/build_windows.ps1 -SkipClean -PythonPath D:\文件AI-AGENT\.venv\Scripts\python.exe`, exit 0, from current committed source. Native report: `tests/screenshots/qa-current/local-privacy/resume-native-smoke-ce55e0e56594498794875f8057fbe212/report.json`.

- EXE: `D:\文件AI-AGENT\.worktrees\ai-smart-naming\dist\Xuxia\Xuxia.exe`
- Size: **10,963,334 bytes**
- SHA256: **`28A456AB66829E558B1995D9C8D1585382A8C4E206266185CB5B5A1F7B66118B`**
- Distribution: **3,137 files / 576,125,163 bytes**

This is the verified smart-naming product baseline with the date correction, **not a release containing working local privacy mode**. It remains in the isolated worktree; the main app/shortcut was not changed. No push/public release/merge occurred.

### Exact next step and blocker

The final post-test memory measurement was **4,947,771,392 available bytes** (about 4.61GiB), below the unchanged **5,368,709,120-byte** experimental guard. Several rechecks remained below it. No model is running, and no applications were closed or paging/security settings changed. This is a temporary available-memory condition, not a published minimum RAM requirement or proof that the hardware can never run the model.

After the user frees memory or restarts, use the existing worktree/venv and pinned resources. Run:

```powershell
& 'D:\文件AI-AGENT\.venv\Scripts\python.exe' scripts/run_local_inference_probe.py --case case_01 --locale zh-CN --quality balanced --timeout 600
```

The runner checks memory twice and all resource hashes; do not bypass those checks. Then run case04 and inspect actual raw output and filename against source content. Continue all eight cases in zh-CN/zh-HK/en-US, including scan pages and video frame variants. Preserve unsuccessful attempts. No real cloud API or private file is permitted.

**Still open:** successful local naming quality; full three-language mixed-media matrix; OS outbound denial and trusted model process; managed download/offline import/recovery; shared Batch/Watch cloud lockout; local-mode UI/manual additions; offline end-to-end and final product integration. Do not redispatch the already-reviewed corpus, process supervisor or single-case runner implementation. Do not mark the whole project complete.

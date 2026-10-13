# Managed model: native contained compatibility and bounded quality check

Source checkpoint: `1e8c1b5859554578e106386815387300ebf7c3e8`.
Run date: 2026-09-30 Asia/Singapore (raw timestamps use 2026-09-29 UTC).
The pinned runtime/model/projector are unchanged from the feasibility manifest.
All inputs were generated synthetic fixtures. No cloud API, credentials, private
files, firewall changes or loopback exemptions were used.

## Result and limits

**Contained runtime compatibility: passed for the exercised cases. Product
readiness and overall naming quality: not passed.** Text, a diagram, two scanned
PDF pages and six video frames were processed by the actual pinned Qwen model in
a fresh owned Windows AppContainer. The parent verified each exact intended SID,
AppContainer token and zero capabilities before allowing the child to run. Each
normal child exited successfully; owned stage/profile cleanup completed. This is
not a replacement for the separate bounded network-block evidence, nor proof that
the unfinished application-wide Batch/Watch privacy gate works.

No raw result was rewritten to claim human review or network isolation. Raw
`outbound_isolation_verified` and `product_ready` remain false. Human inspection
is recorded here separately.

## Real model and human inspection

| Synthetic input | Output language | Child elapsed | Content result |
| --- | --- | ---: | --- |
| Campus-network maintenance text, case01 | zh-CN | 37.33 s | Accepted `2026-08_校园网络间歇中断问题维护_v2.1.txt`; date/version and the concrete maintenance issue are supported. |
| Warehouse evacuation diagram, case04 | zh-CN | 83.84 s | Accepted `北区仓库消防疏散路线示意图.png`; actual source/prepared image inspected, zones/exits/arrows match the explanation. No invented date/version. |
| Two scanned maintenance-record pages, case06 | zh-HK | 152.46 s | **Rejected.** Topic and version were plausible, but model returned year `2026` although the visible evidence says August 2026. Existing precision policy returned `smart.error.ungrounded`; no applicable name. |
| Plant propagation video, case07 | en-US | 82.81 s | Accepted `Plant propagation stages from pruning to transplanting in a pot.mp4`. All six actual prepared frames inspected: cutting, rooting, transplanting in chronological order. |
| Blank white image, case08 | zh-CN | 43.35 s | Correct refusal: `understood=false`, no parts, `smart.error.insufficientContent`, no invented name. |

These times describe this host and these executions, not minimum hardware or a
speed guarantee. Image-process memory was observed at about 5.55 GiB at one point;
that observation is not an exhaustive peak measurement or a product minimum.
The broader earlier multilingual matrix remains PARTIAL; these runs do not
replace it or imply all languages/formats now pass.

The scanned input was legible and complete on both rendered pages; its failure
was model date precision, not hidden/cropped visual evidence. Keep this negative
case. Do not loosen policy or invent a corrected date to make the result pass.
The production review UI must expose unsuccessful naming and allow deliberate
retry/manual work without a silent cloud fallback.

## Payload and cancellation

The owned child bundle contains only pinned runtime members, model/projector,
the generated prompt/schema and prepared JPEGs. Scanned PDF and video sources are
not passed as complete files; the video input uses six bounded frames. Parent
source paths are not included in prompt text. The child necessarily receives its
own managed stage paths for local runtime/model access; that is distinct from
disclosing user source paths or sending anything to a remote service.

A real text-model child was cancelled about two seconds after the process
boundary. Final successful check: status `cancelled`, elapsed **2.198 s**,
`cleanup_complete=true`, exact stage absent, one contained invocation, no name
accepted and no fallback invocation. The first harness run completed its process
assertions but failed saving the same exclusive-create result file twice. Its
raw failure was preserved; the harness was corrected to use separate raw/final
files and rerun successfully. This was not a model/process failure.

## Reproducibility and evidence

Run from the isolated worktree with the project Python:

```powershell
python scripts/run_contained_inference_probe.py --case case_01 --locale zh-CN --timeout 180
python scripts/run_contained_inference_probe.py --case case_04 --locale zh-CN --timeout 300
python scripts/run_contained_inference_probe.py --case case_06 --locale zh-HK --timeout 480
python scripts/run_contained_inference_probe.py --case case_07 --locale en-US --quality balanced --timeout 300
python scripts/run_contained_inference_probe.py --case case_08 --locale zh-CN --timeout 300
```

The CLI exit code covers contained compatibility, not semantic acceptance; inspect
`policy_accepted`, `error` and `suggested_name` separately. Existing resource
hashes and available-memory checks are mandatory before each real launch.

Ignored QA root: `tests/screenshots/qa-current/local-privacy/`.

| Case | Model journal directory | Inference result directory (under `inference-runs/`) |
| --- | --- | --- |
| Text | `model_715352e894ba9d40b33b84a3d5d13031` | `20260929T162409179693Z-case_01-75b9198e9af949398ae554cad0468f78` |
| Image | `model_0ea220e68a99f00b05544ee08e11bb03` | `20260929T162602365919Z-case_04-23b2df9834924c0daa14393630a90a23` |
| Scan | `model_f4f96026f4cd609a3ae485e6bb3b553d` | `20260929T162929180601Z-case_06-a4d66baf83074a6c83e8566abbb14029` |
| Video | `model_603cf39b5347ea6a6dbc301834cc6f09` | `20260929T163337596188Z-case_07-e8cc57213aed418abf547b8419b0c2ac` |
| Blank | `model_226addeda82d84cf2ad6f144b077b255` | `20260929T163948249099Z-case_08-1b584263f3c541a2a4b539c102456340` |
| Cancel | Recorded by `cancel-result.json` | `20260929T164216207493Z-case_01-500f2f99337c416ba90fab7916bc3cd0` |

Cancellation harness: ignored `contained_cancel_check.py` at that QA root. The
initial report-write failure is retained in the preceding case01 run ending
`2b59240edbfd4544a6ea6ffd672aea55`.

## Regression at the source checkpoint

- Isolated non-screenshot suite: **2827 passed, 1 skipped, 3 existing Pydantic
  deprecation warnings**, 61.90 s.
- M1 current-vs-committed comparisons: **49 passed**, 82 existing Pillow warnings,
  30.78 s; update mode absent. On this 125% display the already documented
  process-only `QT_SCALE_FACTOR=0.8` preserves the 100% Golden pixel dimensions.
- M0 under its original offscreen environment: **5 passed, 1 expected update-mode
  skip**, 4 existing Pillow warnings, 0.36 s. No baseline file changed.
- Acceptance script (temporary config/mock credentials): **186/186 passed**.
- Initial unspecialized screenshot invocation genuinely failed 40 cases because
  native images were 1250x875 rather than 1000x700. It also collected 12 ignored QA
  helper tests. The corrected runs above cover both complete committed screenshot
  files, not a filtered set of failing cases; no assertion/tolerance was changed.

## Remaining product gates

Managed download/import/recovery, production process integration, shared
Batch/Watch no-cloud authority, isolated caches, three-language UI/manuals,
disconnected application end-to-end and current packaging remain required.
No main-checkout merge, push, release, formal Golden update or new EXE is claimed.

Nonblocking test backlog from scoped runner review: direct `_members` negative
coverage for prepared payload bounds/projector selection and additional
query-exception/missing-token/prelaunch-cancel cases. Existing native checks do
not eliminate the value of those focused unit negatives.

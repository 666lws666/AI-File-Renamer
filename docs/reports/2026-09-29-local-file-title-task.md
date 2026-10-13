# Diagnostic file-title task correction — 2026-09-29

## Trigger and boundary

The root-owned v6 case05 native run produced a useful zh-CN title. Its zh-HK output ended `頁曲度、焦點一致性、` at the 64-character bound, and en-US ended `finding crd` at the 120-character bound. Both were structurally accepted but rejected by human quality review as incomplete narratives, not usable titles. This v7 change addresses the task definition and one observable dangling-list suffix; it does not repair historical output or claim to detect arbitrary semantic truncation.

The isolated tree started at `bb2badf25ac867cf3e66c2f950a25bf3a212cff7`. Only `scripts/run_local_inference_probe.py`, `tests/unit/test_local_inference_probe.py`, and this report were edited. Unrelated profile-file changes and AppContainer documents were left untouched.

## Change

The three localized topic instructions now explicitly request a short file-title noun phrase rather than a paragraph summary: central object plus theme/purpose, with institution/project only when it distinguishes the content. The selected descriptive language must lead; necessary foreign proper names may follow. The instructions discourage full findings, recommendation sentences, procedure narratives and incidental lists, give soft targets of roughly 12–30 Chinese characters or 6–12 English words (preferably under 90 characters), and ask for a complete title with spare room rather than expanding to the hard bound or emitting a chopped prefix. These are guidance, not new numerical rejection thresholds.

The decoder independently rejects topic values ending in `,，、;；:：`. ASCII `:` was already forbidden anywhere by the unchanged v6 filename regex; its inclusion makes the suffix rule explicit. This check catches only these visible dangling-list endings, not broken English words or every incomplete sentence. No generated value is sanitized, translated, truncated or replaced.

`local-summary-v7` is recorded in results and excluded from prompts. The v6 locale regex, schema bounds, UTF-16 limits, evidence/null/date-version/grounding/refusal/security clauses, source grouping, runtime arguments, resources, metadata extraction, shared policy and raw output retention remain unchanged.

## TDD and verification

- Baseline command `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_inference_probe.py tests/unit/test_smart_naming.py -q --tb=short`: **319 passed in 2.48s**, exit 0.
- RED targeted command on the inference test module with `-k "prompt_defines_short_complete_file_title or decode_refuses_dangling_list or dangling_list_raw_response or public_api_signatures"`: **16 failed, 2 passed, 227 deselected in 1.24s**, exit 1. The old prompt and v6 protocol failed; six newly checked suffixes were still accepted. The two ASCII-colon cases already passed because v6 rejects `:` in topic syntax.
- Focused GREEN, adding `decode_accepts_complete_file_title` to the target selection: **21 passed, 224 deselected in 1.01s**, exit 0. Runner and tests were frozen immediately and root notified for the three-language native rerun.
- Required full-suite first run: **338 passed, 1 failed**. The pre-existing native CLI file-read test received an empty process diagnostic where it expected `failed to load model`; this is unrelated to the edited prompt/decoder paths. The same test in isolation then passed (**1 passed**), and a complete rerun passed (**339 passed in 5.10s**, exit 0). The intermittent cause was not established; no code or test was changed to mask it.
- `git diff --check` exited 0, with only Git line-ending advisories.

Tests preserve the prior important prompt clauses and require the new task instruction in each locale. They assert v7 is absent from prompts, each listed suffix is rejected by direct decoding, the runner retains every raw invalid response byte-for-byte with no suggested name, and complete noun-phrase fixtures remain accepted. The existing grammar, length, evidence, metadata and common-policy tests remain in the full regression.

Frozen SHA-256: runner `0384e9d3ad3233f5d4af6354650f081b150893f86e8ebb9846e3a20bf4ad6bce`; unit test `33310f704e0dd19b74d7d24c6cf8701d872f71889ac29e8c56afe08c912aae09`.

## Limits and handoff

No real model, network, credentials, Git integration, product/QML or Golden path was used or changed by the implementer. Fake-process GREEN proves the prompt/decoder contract, not that the model will write concise, complete titles. Root owns the pinned case05 three-language retry and must judge completeness and supported content separately from `policy_accepted`. If quality still fails, feasibility should be reassessed rather than inferred from structural acceptance.

## Root native verification and content review

The frozen v7 runner was run serially on the same synthetic two-page scanner evaluation PDF, with `--quality balanced --text-layout contiguous --timeout 600`, without cloud calls. Runs retain their unmodified result and raw output under the ignored `inference-runs` directory:

| Locale | Run ID | Elapsed | Suggested name | Content judgment |
| --- | --- | --- | --- | --- |
| zh-CN | 20260928T161555762054Z-case_05-24037d076dc1401597874d08babf3ddd | 30.078s | 装订书扫描与色彩 OCR 评估.pdf | Supported, concise and complete; covers both document sections. |
| zh-HK | 20260928T161629545503Z-case_05-6cde0b39839f4a128c8fec3a41099fc2 | 30.656s | 書脊掃描架與頂部掃描架比較.pdf | Complete wording, but `書脊掃描架` is an imprecise rendering of cradle scanners; do not count this as an unqualified semantic pass. It also omits the colour/OCR section. |
| en-US | 20260928T161703909801Z-case_05-fbb1f30999d942a78c8df779fb099690 | 29.273s | Cedar Research Library scanner evaluation workflow.pdf | Grounded and complete, but less discriminating than the source's bound-book/colour/OCR comparison. Quality limitation remains. |

All three processes exited 0 with cleanup confirmed and structural policy acceptance. None invented a date or version. These facts establish improvement over the dangling/truncated v6 narratives, not three-language product-quality approval. Raw `human_model_quality_reviewed:false` and `outbound_isolation_verified:false` are intentionally not rewritten; this section is the separate content review, and AppContainer outbound enforcement is still unverified.

Root fresh regression: the eight inference/smart-naming/process/security/profile/model/resources/corpus unit modules completed **655 passed in 46.29s**, exit 0. The prior intermittent CLI failure did not recur in this run; its cause remains unestablished. Scoped independent v7 code review reported no findings. This is a diagnostic checkpoint only, not local-mode release approval; broader mixed-media and language verification must precede integration.

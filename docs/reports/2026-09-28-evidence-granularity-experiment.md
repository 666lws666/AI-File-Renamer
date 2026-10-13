# Evidence-granularity diagnostic experiment — 2026-09-28

## Question and control

The reviewed English text-PDF case05 previously produced an English heading verbatim when asked for a zh-CN topic, whereas English text case03 translated. This experiment tests whether line-fragmented extracted text is implicated. It changes only the text evidence bank's grouping through an explicit `--text-layout contiguous` option. The default `lines` grouping and `local-summary-v4` protocol remain unchanged. Source contents, extraction, prompt wording, schema fields, decoder, common naming policy, model arguments and resource checks were not changed.

The root agent's pre-edit default-layout reproduction for case05 used the same source and returned the literal English heading with `T000` and null metadata, leading to `PROTOCOL_INVALID` after 30.1890229 seconds (exit 0; cleanup complete). Its evidence directory is `20260928T154644689325Z-case_05-2b808da6a7774bb9bbc1ae8e91703bf3`; recorded runner/prompt/schema SHA-256 prefixes were `211265`/`67fb125`/`99198` respectively. The root agent owns the post-edit real-model contrast and will append its verified results separately.

## Implementation boundary

`contiguous` slices the exact extracted Python string into consecutive chunks of at most 2,000 characters, preserving whitespace, line endings, order and repeated headings. IDs stay `T000`, `T001`, etc. The existing 32 KiB UTF-8 text bound, 64-span bound and nonblank bank invariant remain. A whitespace-only chunk is rejected instead of silently discarded. Unknown layouts are rejected before memory reads, resource verification, input preparation, output creation or process launch. A nondefault layout is rejected if prepared input has no text or has visuals.

The runner constructs one selected bank, passes it into prompt construction and schema creation, saves it, and uses it for decoder resolution. Prompt construction accepts a prebuilt bank only when it validates and equals the bank deterministically generated from its original text and selected layout. `result.json` records `text_layout` on both completed/failed process paths and prelaunch-memory refusal.

## TDD and verification

- RED 1: 10 targeted failures for missing `text_layout` support in evidence slicing and the runner signature. The failures were expected missing-argument/signature failures.
- RED 2: 7 targeted failures for missing prompt-bank validation, side-effect-free invalid-layout rejection, text-only rejection, one-bank propagation, result metadata and CLI forwarding.
- First complete inference-module run: 129 passed, 1 failed. The failure was in the new test: `Path.read_text()` normalized the fixture's CRLF on Windows, while input preparation reads raw bytes. The test was corrected to decode the original bytes without newline conversion; production code was not changed for this failure.
- GREEN: `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_inference_probe.py tests/unit/test_smart_naming.py -q --tb=short` — **225 passed in 2.56s**, exit 0. Source and tests were frozen after this run.

Tests cover exact original-character reconstruction, 2,000-character multichunk boundaries and order, invalid/blank/oversized input, unchanged default line grouping, validation before side effects, visual/no-text rejection before launch, prompt/schema/saved-bank/decoder agreement, exact decoder substring mapping, successful and failed result metadata including prelaunch refusal, and CLI forwarding. No real model, network or credentials were used in implementer tests.

## Interpretation limits

## Root actual-model contrast

The post-edit contiguous run used the same pinned resources, case05 source hash,
zh-CN locale, balanced quality and runtime arguments. Runner SHA-256:
`c54e699b699f24916e99dace3aeb915d74e7fe6d115cc316e7477ffc655316f8`.
Evidence: `20260928T155143819900Z-case_05-1f6923cbe6c7475394e152044edf0628`.
Process exit0, cleanup complete, 29.1480177 seconds. Metadata choices remained
identical (SHA `0b3cad2de80c4d57fec5f910cfdcbaee4a0ca248dc83605f10c2bc18aed83ba9`).

Raw topic: `Cedar Research Library 扫描仪评估：装订书扫描与色彩/OCR 对比`.
Unlike the unchanged lines baseline, the descriptive portion is Chinese and
captures the main supplied comparisons. Source institution is retained as a
proper name. The common policy correctly rejects the slash with
`smart.error.unsafeName`: there is still NO accepted filename. No sanitization,
translation substitution or evidence rewrite was performed.

This one sample supports evidence granularity affecting the generated summary.
It does not establish causality across files or full language quality. The next
bounded diagnostic addresses observed filename syntax during constrained
generation, retaining the independent decoder and common policy checks.

Independent scoped review: specification PASS; Critical0/Important0. Minor
backlog: invalid nondefault visual/no-text requests may leave prepared output
directories before rejection; no model is launched. This is not a product gate.

Root fresh regression on all eight local diagnostic/policy/process/security/
profile/resource/corpus files: `537 passed in 18.83s`. No skipped cases.

### Interpretation limits remain

This is a one-case, one-variable diagnostic, not a product/default behavior change. A Chinese case05 output would support the grouping hypothesis but not establish general semantic quality; a repeated English heading would reject it for this controlled sample. Contiguous grouping can also alter text metadata candidate availability on other documents because existing parser ambiguity checks operate over a whole fragment and whole-fragment version recognition depends on fragment boundaries. The parser was intentionally not modified or compensated for this experiment. No conclusion about general performance or deployment is warranted before the controlled real-model contrast and review.

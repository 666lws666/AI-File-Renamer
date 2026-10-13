# Local topic filename syntax diagnostic — 2026-09-28

## Scope and observed trigger

The preceding contiguous-text case05 real-model run produced an accurate Chinese description but included `/`: `Cedar Research Library 扫描仪评估：装订书扫描与色彩/OCR 对比`. The unchanged common naming policy rejected it with `smart.error.unsafeName`; no filename was accepted. This change bounds only the diagnostic `topic.value` syntax during constrained generation and validates it again in the decoder. It does not repair that historical output, weaken the common policy, rewrite prompts, or claim the model will choose a good replacement.

## Implementation

`local-summary-v5` uses one anchored, negated-character-class `TOPIC_VALUE_PATTERN` in both text and visual topic schema branches. It excludes ASCII `< > : " / \ | ? * _ .`, U+0000–U+001F, and U+007F. Unicode letters, fullwidth punctuation, proper names, and internal spaces remain eligible. The decoder independently applies the identical regex to `topic.value` before mapping parts to the common policy. Invalid values are rejected, not sanitized, replaced, or truncated. Date/version schemas, metadata candidates, evidence content and ordering, prompt text, model arguments, resource checks, and default `text_layout="lines"` are unchanged. The protocol label is not inserted into prompts.

This is an early syntax bound, not a complete safe-Windows-filename proof. The unchanged common policy still handles reserved device names, other Unicode controls, edge whitespace, and other unsafe cases.

## TDD and verification

- Pinned starting point: branch `codex/local-privacy-mode`, HEAD `329d88feaa1e50188fe30862c93ad74a00911bc0`; pre-edit inference and shared-policy baseline: **225 passed in 2.64s**, exit 0.
- RED: targeted test command `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_inference_probe.py -q --tb=short -k "topic_schema_pattern or topic_pattern_does_not_apply or decode_independently_rejects or public_api_signatures"` gave **49 failed, 1 passed, 130 deselected**, exit 1. Expected causes were missing schema `pattern`, decoder acceptance of unsafe topics, and v4 protocol.
- GREEN focused (including a raw-response retention test): same module with `-k "topic_schema_pattern or topic_pattern_does_not_apply or decode_independently_rejects or public_api_signatures or unsafe_topic_is_protocol_invalid"` gave **51 passed, 130 deselected in 1.40s**, exit 0.
- Required full regression: `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_inference_probe.py tests/unit/test_smart_naming.py -q --tb=short` gave **275 passed in 2.80s**, exit 0. `git diff --check` exited 0 (only line-ending advisory messages).

Tests enumerate every listed forbidden ASCII character plus representative controls, exercise both topic schema branches and decoder bypass of generation, allow zh-CN/zh-HK/English titles with proper-name mixing and fullwidth slash, and check metadata/evidence are unaffected. A synthetic process response containing the observed slash is `PROTOCOL_INVALID`, has no parsed response or suggested name, is not accepted, and remains byte-for-byte in `stdout.bin`.

Source and tests were frozen after GREEN: runner SHA-256 `31ce4efaea740d16f38fd376d7a8a3aacfef30adfe78c0a2f582f2713ea16fc9`; test SHA-256 `ea9b6706ee8bb21b2500197cc9f7cf20f75d5a8cdb632764f0510fb14fc65b98`.

## Limits and handoff

## Root native verification

Independent scoped review found no Critical/Important/Minor issue in the stated
change. Fresh eight-file regression: `587 passed in 51.48s`.

Actual case05, contiguous, balanced, pinned resources and unchanged prompt:

- zh-CN: `20260928T155929164433Z-case_05-a7d8fa0de1bf4cceb01217afceaec3d1`,
  exit0/cleanup complete, 27.0842157s. Model generated
  `Cedar Research Library 扫描仪评估：装订书扫描与色彩 OCR 对比.pdf`.
  Policy accepted; root judged its source institution and comparison topics
  supported. No string replacement or truncation occurred.
- zh-HK: `20260928T160119119164Z-case_05-eacb68607d8e4370a04c1e920b1c829c`.
  Raw topic remained English (`Cedar Research Library Scanner Evaluation -
  Bound-Book Scanning`); decoder correctly rejected it. Language gate FAIL.
- en-US: `20260928T160152036484Z-case_05-28aca42271214960b40464d0ee081235`.
  Raw topic was a paragraph longer than120 characters; decoder correctly rejected
  it. Native generation did not enforce the separate maxLength in this run with
  the unbounded pattern. Do not claim arbitrary JSON Schema conjunction support.

Both rejected runs exited0 with completed cleanup. Raw outputs remain untouched.
Next design must bound repetition in the native topic pattern itself and guide
the descriptive script, preserving independent decoding/common safety checks.
The three-language model-quality gate is NOT passed.

### Original test limitations

Implementer tests used generated corpus and a fake process; no real model, network, credentials, product/QML, or Golden path was exercised or changed. Root owns the same-case actual-model rerun and independent review. The mocked GREEN result proves deterministic schema/decoder behavior, not model compliance or summary quality.

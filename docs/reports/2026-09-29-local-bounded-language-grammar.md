# Bounded descriptive-script topic grammar diagnostic — 2026-09-29

## Trigger and scope

In the root-owned v5 case05 native runs, zh-CN was accepted, zh-HK copied an English title and failed the language gate, and en-US emitted a paragraph beyond 120 characters even though the schema separately declared `maxLength`. Both invalid raw responses were preserved and independently rejected. The three-language gate did not pass. This v6 change tests a narrower generation grammar; it does not alter those runs or claim improved model content.

Only the diagnostic runner, its unit test, and this report were edited. The base was `3c3f10f355ce30df20d3abd335cc42e96339457c` on `codex/local-privacy-mode`.

## Implementation boundary

`local-summary-v6` derives one anchored `topic.value` pattern per requested locale. zh-CN and zh-HK require an initial U+3400–U+9FFF character and then 0–63 repetitions of the existing safe-character negated class; en-US requires initial ASCII A–Z/a–z and then 0–119 repetitions. The class still excludes `< > : " / \ | ? * _ .`, U+0000–U+001F, and U+007F. Both text and visual topic branches use that pattern. Schema `minLength`/`maxLength` remain, but the pattern itself now carries the length bound.

The decoder independently applies the same locale-derived regex. It retains the separate UTF-16-unit limit, coarse language sanity check, and unchanged common naming policy. A non-BMP string can fit the regex code-point bound yet exceed UTF-16 units and must still be rejected. No generated string is prefixed, translated, sanitized, truncated, or otherwise repaired.

This deliberately uses diagnostic “description first; foreign proper names may follow” syntax. An English-leading institution name in a Chinese topic now requires the model to formulate a Chinese descriptive lead. This is neither universal language detection nor a product/template policy. Date/version, metadata candidates, evidence, field order, source grouping, prompt wording, runtime arguments, resource checks, and default `text_layout="lines"` are unchanged. The protocol label appears in results, not model prompts.

## TDD and verification

- Baseline: `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_inference_probe.py tests/unit/test_smart_naming.py -q --tb=short` — **275 passed in 2.31s**, exit 0.
- RED: targeted inference tests with `-k "topic_schema_pattern or decode_independently_rejects_wrong_initial_script or public_api_signatures"` — **57 failed, 3 passed, 165 deselected in 2.21s**, exit 1. The failures reflected the unbounded v5 pattern, missing initial-script restriction, decoder acceptance of wrong-script leads, and v5 protocol. Output was truncated by the command-output budget; the displayed failures and pytest summary identified those causes.
- Focused GREEN: same targeted command after the implementation — **60 passed, 165 deselected in 1.19s**, exit 0.
- Required full regression: the baseline command above — **319 passed in 2.52s**, exit 0. `git diff --check` exited 0, with only Git line-ending advisories.

Tests cover 1, maximum and maximum-plus-one pattern lengths for each locale in both source branches; wrong initial scripts; every previously forbidden ASCII character and representative controls at the first and later positions; valid descriptive-first Chinese/English titles with foreign proper names and fullwidth punctuation; independent decoder rejection when generation is bypassed; existing non-BMP UTF-16 overflow; unaffected metadata/evidence; and preserved raw-response rejection. The old foreign-leading Chinese positive was changed into an explicit rejection with a descriptive-first accepted counterpart, not silently removed.

Source and tests were frozen after GREEN. Runner SHA-256: `b33f822f4015fcf14498b14fafb59c1ef4d2961886c3f924a09f8916b2517ab1`. Test SHA-256: `a053caffa1e24b0dae6eb42fab6e6a4515e4387e5356e5b2ef7ecf49eada9ce5`.

## Limits and root handoff

## Root actual three-language results: quality gate FAIL

All three case05/contiguous/balanced runs completed with exit0 and process cleanup
and were structurally accepted. Root reviewed raw content independently:

- zh-CN: `20260928T160847896134Z-case_05-f479a5b0dc6d43fd9f74a6edcb38abf0`:
  `装订书扫描与色彩 OCR 对比评估.pdf`; accurate compact supported title.
- zh-HK: `20260928T160916226575Z-case_05-70646224dd1f477d9ed9f83ae66449f7`:
  a long explanatory sentence ending `頁曲度、焦點一致性、` at the64-character
  boundary. This is incomplete, not an acceptable filename; quality FAIL.
- en-US: `20260928T160950459271Z-case_05-5529bd3692e549c9a1d3ffa18bdf585c`:
  a narrative sentence ending `finding crd` at the120-character boundary.
  This is incomplete, not an acceptable filename; quality FAIL.

The pattern is now enforced in real generation, but it cannot turn a paragraph
task into a good short-title task. Existing localized contracts call the value
a concise descriptive summary without explicitly framing it as a file-title noun
phrase. Next bounded task will correct that task definition, not keep tightening
character counts or silently repair the model's output. Raw `policy_accepted`
values are retained as structural results; they are NOT human quality approvals.

Independent scoped review found no Critical/Important code defect. A future
coverage improvement is explicit prompt-absence assertion for v6; code inspection
confirmed the protocol constant is used only in result metadata.

Root fresh seven-file regression: `565 passed in 49.83s`. The separately owned
profile test file was intentionally not run concurrently with its independent
prepare-interface edits; this is not a claim of full-product regression.

### Original test limitations

These tests use generated corpus and fake process responses. No real model, network, credentials, product/QML, or Golden path was used or changed by the implementer. The native backend's application of the new regex and the quality of all three case05 summaries are unverified here. Root owns the pinned same-case three-language rerun and independent review; script/length compliance alone will not prove content quality.

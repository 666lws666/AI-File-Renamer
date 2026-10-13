# One-variable local evidence-granularity experiment

## Scope and reason

The English text-PDF case05 repeatedly copies its heading instead of producing a
zh-CN summary, while English text case03 translates. All text is extracted. The
current evidence bank splits every nonblank line; PDF wrapping therefore creates
20 short fragments rather than paragraph-like prose. Causality is not established.
This experiment changes only evidence grouping, not source contents or prompts.

Task baseline: `28ff0b5d6c50bde7192e4566aa30a922320ff2b3` in the existing
`codex/local-privacy-mode` worktree. Root owns actual model runs and judgments.

## Task 1: explicit opt-in diagnostic grouping

Own only `scripts/run_local_inference_probe.py`,
`tests/unit/test_local_inference_probe.py`, and report
`docs/reports/2026-09-28-evidence-granularity-experiment.md`.

- Follow TDD. Add an explicit diagnostic `text_layout` option: `lines` (default,
  unchanged existing behavior), `contiguous` (new). Expose via `--text-layout`.
- For contiguous layout, preserve the entire extracted string exactly including
  whitespace, newlines, order and repeated headings. Slice consecutive chunks of
  at most 2000 Python characters with unchanged T000... IDs, max64 entries and
  MAX_TEXT_BYTES. Do not join/remove/rewrite words, remove headings, infer actual
  paragraph boundaries or read expected corpus answers. A whitespace-only chunk
  may conservatively reject rather than being dropped or inventing evidence.
- Validate unknown layout before resources, filesystem or process side effects.
  Nondefault layout is text-only: reject when there is no extracted text or when
  prepared visuals exist; never accidentally run a visual experiment.
- Build exactly one selected bank and use it consistently for prompt, schema,
  metadata candidate derivation, saved evidence and decoder. Preserve existing
  public call behavior by default. If `_build_prompt` accepts a prebuilt bank,
  validate it and require it matches the original text/layout; no arbitrary
  caller-supplied content or divergent bank between stages.
- Keep diagnostic_protocol `local-summary-v4`; add `text_layout` to result.json
  on successful/failed execution including prelaunch-memory refusal. The actual
  prompt wording, model/runtime arguments, grammar fields, memory/timeout rules,
  original input hashes, source corpus, decoder, common policy and raw evidence
  are unchanged except selected bank/IDs and metadata derived from those IDs.
- Tests: default lines equals prior bank; contiguous reconstructs original text
  byte-for-byte; multichunk exact boundaries/order; invalid/blank/oversized input;
  no default changes; unknown option zero side effects; visuals/no-text rejection
  before process launch; one selected bank appears in prompt/schema/evidence and
  maps decoder evidence to its exact original substring; result records layout;
  CLI forwards it. Do not weaken existing tests or language rejection.
- Run focused inference tests and shared naming policy. Freeze source/tests after
  passing. No real model/network/credentials, no product code/QML, no Golden,
  no Git commit by implementer. Report exact RED/GREEN and limitations.

Root will independently review and run case05 using both layouts with identical
parameters. A Chinese output supports the grouping hypothesis but does not prove
general semantic quality. A repeated English result rejects this hypothesis for
this controlled sample; preserve both and reconsider the approach rather than
stacking unrelated prompt rewrites.

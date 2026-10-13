# Local topic grammar: prevent observed forbidden filename punctuation

## Task 1 (diagnostic only)

Read preceding evidence-granularity report: real contiguous case05 produced an
accurate Chinese description but included `/`, so unchanged common policy
rejected it. Do not repair the generated string or relax that rejection.

Own only `scripts/run_local_inference_probe.py`,
`tests/unit/test_local_inference_probe.py`, and new report
`docs/reports/2026-09-28-local-topic-syntax.md`. Work in the existing isolated
codex/local-privacy-mode tree after root checkpoints the grouping experiment.

- TDD: add one explicit topic-value JSON Schema pattern that disallows the
  common policy's forbidden ASCII filename characters `< > : " / \\ | ? * _`,
  dot, ASCII controls U+0000..U+001F and U+007F. Use a negated character class
  with anchors; no lookahead or unsupported native grammar constructs. Unicode
  letters and fullwidth punctuation, proper names and internal spaces remain.
- Apply the pattern to topic.value for both text and visual source branches.
  Date/version branches, metadata candidates, evidence strings, field order,
  prompt wording, model/runtime arguments and resource checks are unchanged.
- Independently enforce the identical topic regex in decode before mapping to
  common parts; do not trust the constrained backend as validation. Do not
  sanitize, replace or truncate a value. Existing common policy still rejects
  reserved device names, Unicode controls, edge whitespace and all other unsafe
  cases; this grammar is an early bound, not a complete Windows-name proof.
- Advance result protocol to `local-summary-v5`; never put its version label
  into model prompts. Keep text_layout explicit with default lines unchanged.
- Test every forbidden character and representative controls; valid zh-CN,
  zh-HK, English and proper-name mixed titles; text/visual schema branches;
  decoder negative even when bypassing generation; date/version and evidence
  unaffected; raw unsafe response retained and never passed as sanitized name.
  Do not weaken existing tests. Run inference + shared smart policy tests.
- No real model/network/credentials/product/QML/Golden/Git changes by implementer.
  Freeze source/tests after GREEN; report exact RED/GREEN and limits. Root owns
  actual same-case rerun and independent review; no model-quality claim from mocks.

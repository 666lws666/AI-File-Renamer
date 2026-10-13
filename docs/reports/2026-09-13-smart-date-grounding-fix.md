# Evidenced Chinese date whitespace — 2026-09-13

## Finding and narrow correction

The actual pure policy rejected the literal source/evidence `时间：2026 年 8 月` for the correctly normalized month `2026-08`. The Chinese-date regular expression did not admit spaces before 年/月/日. Only those unit boundaries now accept whitespace; no arbitrary prose is removed or joined. NFKC normalization, exact excerpt occurrence, date/range validation and original precision remain enforced.

This is an existing-validator correction, not a model-output repair. No prompt, model response, filename value, extension, role order, output language or schema was changed. The reviewed synthetic corpus itself is unchanged.

## Fresh tests

- RED before implementation: `python -m pytest tests/unit/test_smart_naming.py -q` returned **8 failed, 86 passed in 0.39s**. All eight failures were the new legitimate Chinese spacing cases.
- GREEN: `python -m pytest tests/unit/test_smart_naming.py tests/unit/test_local_inference_probe.py tests/unit/test_smart_workspace.py tests/integration/test_smart_analysis.py -q` returned **162 passed, 3 warnings in 3.81s**.
- The three warnings are the existing Pydantic class-based config deprecations in FileItem, RenameRecord and AppConfig. They were not suppressed or changed in this scope.
- Twenty new cases cover ordinary/fullwidth whitespace, tab/newline extraction, day and same-precision ranges, missing day/month, wrong date, absent source evidence, disjoint prose, invalid dates and invalid ranges.

Tests use synthetic data and do not establish real-model naming quality. The only native CLI check in the diagnostic suite targets an intentionally absent model after reading temporary prompt/schema files; it does not load model weights.

## Ownership

The root performed this TDD micro-fix because the attempt to allocate another implementer, including a follow-up, was rejected by the agent-thread limit. The earlier inference-runner implementer had already frozen its separate files; no concurrent file writer was active. Root will request scoped independent review and retain a separate local commit; no push or Golden changes.

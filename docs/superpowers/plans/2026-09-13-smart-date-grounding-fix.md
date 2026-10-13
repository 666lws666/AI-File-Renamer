# Evidenced date whitespace correction

**Goal:** fix a confirmed conservative-validator false rejection without changing date precision or inventing evidence.

**Authority:** the Product Owner authorized fixes needed for actual local naming. This is a separate, narrow existing-policy correction, not permission to change the local inference runner's policy or prompts.

**Evidence:** root called the actual `SmartNamingPolicy.render` with an explicitly spaced synthetic source and literal evidence `时间：2026 年 8 月`, date value `2026-08`, and an evidenced specific topic. It returned `smart.error.ungrounded` because `_date_evidenced` permits whitespace after 年 but not around all Chinese date units. Later direct source inspection confirmed accepted case01 actually says `时间：2026年8月`; the model had inserted spaces in its quotation. The validator whitespace bug is independently real, but this correction does not make a rewritten quotation pass exact-source occurrence checks or establish model quality.

## Task 1: narrow date evidence matching

Own only `src/core/smart_naming.py`, the existing focused smart naming test file (find its actual path), and a new small task report `docs/reports/2026-09-13-smart-date-grounding-fix.md`. Do not modify any runner, corpus, model, QML, credentials, templates, Golden or unrelated code. Root owns Git. Do not execute models or networks.

- [ ] Locate existing date grounding tests; add RED cases for spaces around Chinese 年/月/日, including NFKC/fullwidth spacing, as they appear in extracted text.
- [ ] Preserve exact-source excerpt checks; changing whitespace support must not allow a different date/year/month or evidence absent from supplied source.
- [ ] Preserve every existing invalid-date, unsupported format, ordered same-precision range and missing-precision rejection. Explicitly test month-only evidence cannot validate a day, year-only cannot validate a month, disjoint numbers cannot be joined across arbitrary prose, and invalid dates remain rejected.
- [ ] Change only date evidence patterns/normalization needed for the observed whitespace. Do not sanitize generated names, append inferred fields, weaken evidence_source handling or bypass policy errors.
- [ ] Run focused tests then the local inference diagnostic tests. Report exact RED/GREEN and freeze; do not stage/commit. Root will independently review before running the model against the corrected policy.

The return value, role order, name-length checks, extension protection and smart-v1 schema remain unchanged. This is whitespace handling already promised by the policy, not a new date parsing language or full natural-language date recognizer.

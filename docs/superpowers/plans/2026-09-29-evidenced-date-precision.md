# Preserve explicit date precision at the shared naming guard

## Observed defect

The real v7 zh-HK scan result at ignored run
`20260928T163324443792Z-case_06-283336a032b24efcaae3965a834b54c4`
contains date value `2026` with evidence
`第一頁文件顯示'維護時間：2026年8月'`. The shared policy accepts the year
substring and generates a year-only filename despite its existing instruction to
preserve evidenced precision. Source images independently show August 2026.
The same loophole exists for text evidence; this is not a reason to modify the
model output, source image, old result, or extraction prompt.

## Task ownership

Only modify `src/core/smart_naming.py`, `tests/unit/test_smart_naming.py`, and add
`docs/reports/2026-09-29-evidenced-date-precision.md`. No naming diagnostic, model,
runtime/staging, QML, template/config/watch, resource or Golden changes. No Git
commit/model/native/API/credential effects by implementer; root owns integration.

## Requirements

- TDD a deterministic regression for the exact response above (synthetic text
  fixture and visual-evidence fixture) through public policy.render(). It must
  reject with the existing `smart.error.ungrounded`, not silently expand/replace
  the date. Leave old raw evidence unchanged.
- A year substring inside an explicit supported month/day atom cannot evidence
  a year-only value. Likewise a month prefix inside an explicit full day cannot
  evidence month-only output. Apply uniformly to accepted numeric separators,
  supported Chinese date syntax, whitespace and NFKC-normalized source digits.
- Preserve genuine standalone year/month/day acceptance and same-precision ordered
  ranges. If the quoted evidence contains a separate exact standalone date at
  the requested precision, that is still usable: do not enforce the most precise
  date anywhere in a paragraph irrespective of which date the value denotes.
- Preserve all existing invalid-calendar, range ordering, no invented day/month,
  literal text occurrence, language, extension/path protection and no mutation
  behavior. Do not infer dates from prose, unrelated numbers or filenames.
- Keep the existing smart-v1 wire shape/render order and policy selection stable;
  this enforces an existing invariant, not a new naming mode or migration. The
  production Batch path renders adapter fields through this guard on every smart
  result; do not change cached tasks, stored defaults, templates or saved names.
- Add negative tests for year<-month, year<-day, month<-day and range endpoints;
  positive tests for exact precision, standalone alternatives and unrelated
  neighboring dates. Do not blanket-reject all dated names or weaken old tests.
- Report the scope honestly: this verifies literal date consistency, not whether
  a model's visual quotation is truthful or whether its title is semantically
  accurate. It will reject the known bad result, not manufacture a better one.

Run focused RED/GREEN, then smart naming and local inference probe test modules
plus existing smart Batch analysis tests as applicable. Report exact commands,
counts, changed files and limitations; freeze for review. If existing tests reveal
a genuine specification conflict, report it rather than silently rewriting them.

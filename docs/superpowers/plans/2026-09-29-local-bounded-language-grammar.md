# Diagnostic v6: bounded descriptive-script topic grammar

Base `3c3f10f355ce30df20d3abd335cc42e96339457c`. Existing worktree only.
Read previous local-topic-syntax report for actual native evidence: zh-CN passed;
zh-HK copied an English title; en-US emitted a paragraph despite separate
maxLength alongside the unbounded regex. All invalid responses were rejected.

## Task 1

Own runner `scripts/run_local_inference_probe.py`, its unit test, and report
`docs/reports/2026-09-29-local-bounded-language-grammar.md`. No other code/files.

- Use TDD. Replace the unbounded topic regex with one locale-derived anchored
  pattern: requested zh-CN/zh-HK starts with a CJK character U+3400..U+9FFF;
  en-US starts with ASCII A-Z/a-z. Remaining characters use the same existing
  forbidden-ASCII negated class. Bound the remaining repetition directly in
  the pattern: {0,63} for Chinese, {0,119} for English. No lookahead. Keep the
  schema min/maxLength too, but do not rely on their conjunction with pattern.
- This explicitly adopts a diagnostic 'description first, foreign proper names
  may follow' style. It is NOT universal language detection or a product/template
  policy change. An English-leading proper institution in a Chinese topic now
  requires model rephrasing; never prefix/translate/rewrite generated strings.
- Use the same locale-derived regex independently in decoder. Preserve existing
  UTF-16 limits (regex counts code points, so non-BMP overflow must still fail),
  language/script sanity and shared policy. No truncation or sanitizer.
- Apply only topic for text/visual. Date/version/evidence/field ordering/source
  grouping/model args/resources/prompt wording remain unchanged. Protocol v6 in
  result only. Default lines unchanged. Preserve all historical raw runs.
- Tests: regex fullmatch at1/max/max+1 for all locales; both source branches;
  Chinese/English initial script violation; valid descriptive prefix plus foreign
  names; original forbidden characters anywhere including first; decoder bypass
  rejection and non-BMP UTF16 bound; metadata/evidence unaffected; existing raw
  preservation. Update previously-positive foreign-leading Chinese title test to
  an explicit rejection and add its natural descriptive-first counterpart, not
  silent deletion. Preserve meaningful old assertions for underlying syntax.
- Run inference + shared-policy suite, freeze source/test, report RED/GREEN.
  No Git/model/network/credentials/product/Golden writes by implementer.

Root will rerun the same text-PDF in all3 languages. Passing script/length does
not prove content quality; root reviews actual outputs against original content.

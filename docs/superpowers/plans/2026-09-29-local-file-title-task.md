# Correct the local diagnostic task definition: file title, not paragraph

Existing v6 native evidence: Chinese title is useful, but Traditional Chinese and
English produce narratives forced to end at the grammar bound. Structural
acceptance is not quality. Root has rejected those outputs; do not alter them.

## Task 1 (diagnostic only)

Own `scripts/run_local_inference_probe.py`, its existing test file, and new report
`docs/reports/2026-09-29-local-file-title-task.md`. Existing isolated tree only.
Other frozen profile changes belong to another task. No Git/model/network.

- TDD; advance result protocol to local-summary-v7, never include it in prompts.
- Rewrite only the localized topic-task instructions (zh-CN/zh-HK/en-US) to
  explicitly say the output is a short file-title noun phrase, not a paragraph
  summary. Describe central object plus theme/purpose; retain institution/project
  only when meaningfully distinguishing content. No full findings, recommendation
  sentences, procedure narratives or incidental lists. Descriptive selected
  language comes first, necessary foreign proper names may follow.
- Prefer concise complete wording with spare room below the hard bound: Chinese
  roughly12-30 characters, English roughly6-12 words and preferably under90
  characters; these are guidance, not new hard rejection thresholds. Never fill
  the budget by elaborating; finish the title without broken words, dangling
  conjunctions or list punctuation. If too much information, summarize central
  content before generating, never output a prefix chopped at the limit.
- Preserve every existing untrusted-data/evidence/null-date-version/grounding/
  refusal/source-date-precision restriction and the final language reminder.
  Preserve v6 schema/regex/role bounds, exact source grouping, runtime/resources,
  metadata extraction, common policy and raw output. No corpus-specific terms,
  example answers, generated title replacement, translation or truncation.
- Add independent decoder refusal for topic ending in ASCII/Chinese dangling
  list punctuation: comma, Chinese comma, ideographic comma, semicolon/Chinese
  semicolon, colon/Chinese colon. This catches the observed dangling-list case;
  it is NOT a claim to detect arbitrary incomplete words/semantic truncation.
- Tests for all3 task contracts and preserved important clauses; v7 absent from
  prompts; each dangling-list suffix direct decoder refusal with full raw
  retention in runner; complete noun-phrase fixtures still accepted, existing
  semantic bounds/forbidden chars/metadata tests retained. Fake tests never prove
  actual model quality. Run inference+sharedpolicy; freeze after GREEN/report.

Root retries case05 three languages without changing model, quality, layout or
sampling. Judge actual completeness/content, not only policy_accepted. If quality
still fails, preserve the result and reassess feasibility rather than declaring
the local model ready or indefinitely piling on length constraints.

# Product local naming protocol

> Execute as one pure-code task after native foundation promotion; independent
> review follows. Real model semantic acceptance is a separate root-owned Gate.

**Goal:** Reuse the actual-model-tested compact smart protocol in the product,
and support existing template naming without inventing missing template fields.
No diagnostic QA path or raw stream logging may enter the product implementation.

## Global constraints

- Naming and processing mode remain independent. No existing template, Watch
  setting, cloud prompt/provider or saved default is changed by this task.
- AI returns structured naming suggestions only: no paths, commands or file I/O.
- Missing facts remain missing; no fake dates, versions, authors or comprehension.
- Output language remains the user's filename language, not UI language.
- No network, model process, credentials, private files, QML, Golden, main checkout
  writes, merge or push. Fixtures and tests are synthetic pure data.
- One implementation of the smart schema/prompt/parser: move tested pure code,
  do not fork diagnostic and production behavior.

## Task 1: Pure smart protocol promotion and nullable template protocol

Allowed source/test files:

- Create `src/services/local_ai/naming_protocol.py`.
- Modify `scripts/run_local_inference_probe.py` only to import/re-export moved
  pure protocol functions/constants; retain all diagnostic orchestration, QA
  paths and raw evidence behavior in the script, not the product module.
- Create `tests/unit/test_local_naming_protocol.py`.
- Existing `tests/unit/test_local_inference_probe.py` and exact protocol tests may
  change import plumbing only if needed. Do not change core smart/template policy.

### Smart protocol

Promote the probe's pure evidence bank, metadata candidates, schema, prompt and
strict decoder (and their helper functions/constants) as a single versioned unit.
Keep `local_schema`, `decode_response`, `text_evidence_spans`,
`text_metadata_choices` and `_build_prompt` compatible for the diagnostic script.
Use public `build_smart_prompt` as a product alias instead of adding a second
prompt implementation. Preserve the exact existing zh-CN/zh-HK/en-US prompt and
schema output for representative fixtures (freeze their pre-move hashes in tests
before relocation). No PyMuPDF, media decoder, Path, process or scripts import is
needed by the pure protocol.

Preserve32KiB UTF-8 text,64 spans,2000 characters/span,16 grounded metadata
candidates,128KiB prompt/schema bounds at the future caller,256KiB response,
role order/date precision and the existing `SmartNamingPolicy` wire result.
Reject duplicate keys, nonfinite JSON, invalid UTF-8, unexpected fields, trailing
content, invented evidence IDs, mismatched modalities/language and oversized
roles. Deep malformed JSON must become a fixed ValueError, not leak a parser
RecursionError; add a genuine negative fixture if current code lacks this case.
Do not relax failed semantic cases or mechanically truncate generated names.

Expose `SUPPORTED_NAMING_LOCALES` covering the existing five filename languages:
zh-CN, zh-HK, en-US, ja-JP, es-ES. Extend only the locale name/prompt and topic
script checks for Japanese (Kana/CJK) and Spanish (Latin including diacritics).
Existing three-locale fixtures must remain identical. Add unit tests for these
two languages, but explicitly report that they have not yet passed real model
semantic acceptance. This task must not claim that mock outputs verify fluency.

### Template protocol

Add pure APIs:

```python
def template_schema(template: Template, locale: str, *, has_text: bool,
                    has_visuals: bool, text_evidence=None) -> dict: ...
def build_template_prompt(template: Template, locale: str, text: str, *,
                          has_text: bool, has_visuals: bool,
                          text_evidence=None) -> str: ...
def decode_template_response(raw: bytes, template: Template, locale: str, *,
                             has_text: bool, has_visuals: bool,
                             text_evidence=None) -> NamingFields: ...
```

Use only enabled fields actually referenced by the immutable template pattern,
in their deterministic template order; allow only the ten NamingFields names.
The model response has explicit understood/language and a field object. Each
requested field may be null even when the template requires it. A populated
field carries bounded value, evidence and evidence_source (text ID or concrete
visual observation); unknown fields, unprovided modalities and invented text IDs
are rejected. `understood=false` is an explicit safe refusal (fixed ValueError
code), not an all-empty success result. No undocumented fallback from template
to smart naming or vice versa.

Preserve trustworthy date/version candidate grounding from the smart protocol:
for text-only dcDate/extVersion a populated value must match a registered exact
candidate, otherwise null. For visual evidence validate date syntax and precision
against its quoted observation using existing pure date-evidence validation;
do not invent missing month/day. Non-date values are bounded (<=180 UTF-16 units),
free from Windows filename/control/path syntax, and not silently sanitized or
truncated. Meaning/translation quality remains for actual-model + user review.

The decoder returns NamingFields, leaving absent/unrequested values None. Existing
TemplateRenderer remains the sole formatter/required-field gate: a title-only
template may succeed without a date; a default date+title template lacking a date
must remain NEEDS_REGENERATION rather than receiving a fabricated date. Output
filename assembly/extensions/Apply/Undo are outside this protocol.

### Tests / report

First freeze representative current smart prompt/schema/result fixtures and add
RED tests for the missing product module/new template APIs. Verify parity after
promotion without weakening existing diagnostic assertions.

Cover five locales, text/visual/mixed evidence, false understanding, null required
metadata, unknown fields/keys/types, invalid language/modality, duplicate JSON,
nonfinite/deep JSON, unsafe/oversized names, response cap, exact evidence IDs,
date precision and a template whose enabled fields include fields not in pattern.
Verify new template output through real existing TemplateRenderer, not a mock.
Source/module inspection must confirm pure product imports and no QA literals.

Run new protocol tests plus all current local-inference/contained-inference/smart
naming and template renderer tests. Report raw RED/GREEN summaries, exact parity
fixtures, changes and unverified real-model languages in
`.superpowers/sdd/local-naming-protocol-report.md`. Commit only allowed source/tests
as an independent commit, no amend. Root will run genuine local inference only
after production service composition; do not execute a model in this task.

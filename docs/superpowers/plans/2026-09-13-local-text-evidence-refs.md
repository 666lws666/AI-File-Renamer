# Local text evidence references

> Execute with subagent-driven-development and TDD. This is a diagnostic protocol correction within the approved autonomous local-mode scope, not a product-policy change.

**Goal:** remove model-rewritten text quotations as a source of false grounding failures, while preserving exact original evidence and strict filename validation.

**Architecture:** the parent constructs bounded opaque references to actual extracted text. For text evidence the model selects a permitted reference, never rewrites the quote. The decoder resolves it to the original fragment before the unchanged SmartNamingPolicy. Visual observations remain their existing free-text, visual-only protocol.

**Tech Stack:** existing Python diagnostic, JSON Schema constrained llama.cpp output, no dependencies or model changes.

## Evidence and options

Actual case01 zh-CN at HEAD02d1e0d produced a correct specific topic/month/version in 40.9792065s, exit0/cleanuptrue. It quoted `时间：2026 年 8 月`, but the actual immutable source is `时间：2026年8月`; literal excerpt matching correctly rejected the changed quote. Do not retroactively accept it. Artifact: `tests/screenshots/qa-current/local-privacy/inference-runs/20260913T081954293639Z-case_01-3aa86cd560cb4db4ba48259a4f868dd0/`.

Options considered: more prompt reminders (not deterministic); removing arbitrary whitespace from all quotations (risks changing word boundaries and weakening the shared validator); parent-owned source references (selected, deterministic original-source resolution). Reference occurrence still does not prove that a generated value is semantically entailed. Root human content review remains mandatory.

## Global constraints

- Existing worktree/branch only; no src/product/QML/Provider/config/Golden changes, model loading by implementer, cloud APIs, credentials, private files, downloads, Git writes or changes to the accepted corpus.
- Preserve optional named roles, required topic, modality constraints, strict duplicate/unknown/prose rejection, raw evidence, model args/lifetime/5GiB guards and all date/language/length/extension policy checks.
- Root owns actual model execution and Git. During the current case04 model run the old script is already imported; implementer may change only the assigned diagnostic files, never raw evidence. Root waits for that model run before any commit or new model invocation.

## Task 1: bounded text-reference protocol

**Own:** `scripts/run_local_inference_probe.py`, `tests/unit/test_local_inference_probe.py`, new `docs/reports/2026-09-13-local-text-evidence-refs.md`. Do not change other files. Refactor only local helpers required for this protocol, not the full runner.

**Interfaces:** add `text_evidence_spans(text: str) -> dict[str, str]`. Add optional keyword `text_evidence=None` to local_schema and decode_response; when has_text=True the bank is required and validated, never silently fall back to free text. Visual-only callers retain their behavior without a bank. Keep run_case's public signature unchanged; it constructs the bank from prepared text for its own invocation. `_build_prompt` may construct/use the same deterministic bank from its supplied text.

- [x] RED: schema text evidence enum is exactly the bank IDs; decoder resolves IDs to unchanged fragments; unknown refs/free rewritten quote/foreign bank evidence rejected; visual-only branch unchanged. Tests must use a generated corpus, not ignored QA evidence.
- [x] Implement the bounded deterministic bank. Reject nonstring/blank text or UTF-8 text over32KiB; split into original nonblank lines, split any line into at most2000-character literal chunks, never drop nonwhitespace content; IDs are T000 onward. Maximum64 chunks, otherwise fail instead of truncating. Every value must be an actual substring of supplied text. Example core:

```python
spans = {}
for line in text.splitlines():
    if not line.strip():
        continue
    for offset in range(0, len(line), 2000):
        if len(spans) >= 64:
            raise ValueError('text evidence span bound exceeded')
        spans[f'T{len(spans):03d}'] = line[offset:offset + 2000]
```

- [x] Validate banks as nonempty mappings with contiguous canonical IDs, at most64 nonempty values of at most2000 characters; copied local values, no arbitrary model lookup/path. Generate segment schema according to evidence_source: text requires `evidence` enum of available IDs; visual requires existing bounded observation string. If both modalities exist, use exclusive per-source object branches so a visual observation is not forced into text IDs. Unknown evidence_source fails.
- [x] Resolve only text `evidence` through the validated invocation bank. Do not change role/value/language/understood; exact common-policy fields remain unchanged. Wrong-bank quotes still fail the actual policy against current extracted_text. Reject free-text quotation on the text path even if it resembles a real excerpt.
- [x] Replace contradictory prompt instruction to quote text with selecting the registered ID. Include the bank with each original fragment under opaque ID inside the untrusted-text delimiter; no source basename/path, case ID or reviewer oracle. Explain that values summarize content while text evidence selects IDs. Preserve visual observation instructions.
- [x] Root's actual case04 review found correct observations but repeated entity and overenumerated captions. Add a generic selection clarification: do not repeat entity in topic when entity is emitted; omit captions, instructions and lists from context unless needed to distinguish the file. Optional roles are not a checklist. No case-specific example/answer or generated-value deletion; test the prompt contract and let root rerun actual vision quality.
- [x] Save `text-evidence.json` (only for text inputs) and its SHA256 in the unique diagnostic result, including post-preparation prelaunch failure. This makes mapping reproducible alongside source/prompt/schema hashes. Do not overwrite earlier evidence.
- [x] Migrate existing fake response fixtures to use actual IDs while keeping assertions about interpreted original evidence. Add RED/GREEN for blank/overbound bank, unknown ref, quote-rewrite, both modalities, bank retention/hash, locale preservation, raw output preservation, and date-space example. Model tests stay fake; no actual model loads.

```python
source = '时间：2026年8月\n校园网络维护报告'
bank = text_evidence_spans(source)
assert bank == {'T000': '时间：2026年8月', 'T001': '校园网络维护报告'}
# A model date segment with evidence=T000 resolves to exactly 时间：2026年8月.
# The value 2026-08 still goes through SmartNamingPolicy; no missing day is added.
```

- [x] Run focused `python -m pytest tests/unit/test_local_inference_probe.py tests/unit/test_smart_naming.py -q`, then the five local diagnostic files. Record exact RED/GREEN, code changes and honest limitations in the report. Freeze the three files without staging/committing; root independently reviews and retries real text inference.

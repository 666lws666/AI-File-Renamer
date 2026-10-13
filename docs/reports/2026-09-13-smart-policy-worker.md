# Smart policy worker report — 2026-09-13

## Scope and implementation

Owned production files: `src/core/smart_naming.py`, `src/core/batch_analysis.py`.
Owned tests: `tests/unit/test_smart_naming.py`, `tests/integration/test_smart_analysis.py`.
No controller, QML, Provider, protocol, config, Watch implementation or template implementation changes. Nothing staged or committed.

- Pure immutable `SmartNamingPolicy(locale, version)`, `SMART_POLICY_VERSION = smart-v1`, and safe `SmartNamingError` identifiers.
- Standard supported schema: `{understood, language, parts:[{role,value,evidence}]}`; no extras; one date/entity/topic/version, at most three distinct context parts.
- Schema description carries policy identity, untrusted-input instruction boundary, specificity/omission/evidence/locale/precision requirements. Existing Provider adapter validator accepts the schema (unit-tested); Provider adapter unchanged.
- Local deterministic role order and underscores, precise ASCII dates/ranges, safe parts/local extension, literal normalized excerpt checking, mandatory non-generic topic, small script sanity checks, 180 UTF-16 stem limit with rejection rather than truncation.
- Smart branch never calls template provider. Mode/version snapshot keywords supported; default remains template; Watch adapter explicitly requests template. Smart requests carry `naming_mode` and `naming_policy_version` metadata. No cache/usage activation.
- Original validation/extraction/prepared-visual/privacy/capability checks reused. Empty content without prepared visuals fails before Provider invocation; cancellation checked after Provider response and before either rendering path.

## TDD execution evidence

Interpreter: `D:/文件AI-AGENT/.venv/Scripts/python.exe`; working directory: `D:/文件AI-AGENT/.worktrees/ai-smart-naming`. Python modules imported from this worktree, not the main tree.

Raw command endings from actual runs:

```text
python -m pytest tests/unit/test_smart_naming.py -q
60 failed in 0.59s
Reason: AssertionError: smart policy is not implemented

python -m pytest tests/integration/test_smart_analysis.py -q --tb=line
9 failed, 1 passed, 3 warnings in 0.51s
Reason: TypeError: BatchAnalysisService.__call__() got an unexpected keyword argument 'naming_mode'
The passing test is existing template/default/Watch behavior.

python -m pytest tests/unit/test_smart_naming.py -q --tb=no
61 failed in 0.17s
Additional RED: date must not invent day from month-only evidence.

python -m pytest tests/unit/test_smart_naming.py tests/integration/test_smart_analysis.py tests/integration/test_batch_analysis_service.py -q --tb=short
77 passed, 3 warnings in 0.95s

python -m pytest tests/unit/test_smart_naming.py tests/integration/test_smart_analysis.py -q --tb=short
2 failed, 78 passed, 3 warnings in 0.77s
Additional RED: fullwidth date digits accepted; invalid output language exposed enum ValueError.

python -m pytest tests/unit/test_smart_naming.py -q --tb=short
68 passed in 0.16s
ASCII date fix independently verified.

python -m pytest tests/unit/test_smart_naming.py tests/integration/test_smart_analysis.py tests/integration/test_batch_analysis_service.py -q --tb=short
86 passed, 3 warnings in 0.52s
Final GREEN after safe locale error mapping: 68 smart unit + 12 smart integration + 6 existing batch integration.

git diff --check -- src/core/smart_naming.py src/core/batch_analysis.py tests/unit/test_smart_naming.py tests/integration/test_smart_analysis.py
Exit 0; only Git LF-to-CRLF advisory for batch_analysis.py.
```

The three warnings are existing class-based Pydantic Config deprecations in FileItem, RenameRecord and AppConfig. Initial terminal output rendered some Chinese paths/text using the shell encoding; tests operated on the actual Unicode strings.

## Explicit limits / review concerns

All model responses are structured in-memory test doubles; no real Provider request, credential or semantic-quality experiment was performed. These tests establish deterministic contract and safety checks, not real-model naming quality.

Literal excerpt occurrence does not establish semantic entailment: a model can quote a real excerpt yet misinterpret/translate it or attach a wrong entity. Visual observations cannot be independently checked by this renderer. The original mixed-text/visual restriction was corrected in the follow-up below. Human review remains required.

Specificity rejection is a small generic-label denylist, not complete subject understanding. Script checking is deliberately a small topic-only mismatch heuristic so proper entity names are not converted; it cannot guarantee all text is in the selected language. Existing Japanese/Spanish locales are accepted in addition to zh-CN/zh-HK/en-US; only the latter three have dedicated output fixtures.

Date evidence checking is conservative: ISO/numeric separators and Chinese numeric dates are recognized, not all natural-language dates or abbreviated ranges. Unsupported/ambiguous date formats should be omitted by the model or fail safely; this can reject otherwise correct candidate responses. No missing date precision is invented.

Body dumping is addressed by explicit model instructions plus structural/safety/length checks; a short body excerpt can still pass. Real-model evaluations are needed to assess concise naming, faithful abstraction and prompt-injection resistance.

Sandbox launcher failed for shell calls and later existing-file patches. Used scoped elevated local test commands and installed `codex.exe --codex-run-as-apply-patch`; no ad-hoc shell file writes or unrelated filesystem changes.

## Follow-up: visual evidence provenance correction

The focused reviewer confirmed that the production image/video extractor always supplies explanatory metadata text, so the original literal-evidence rule wrongly rejected actual visual observations. Root reassigned the same reviewer to implement this bounded fix; this follow-up is not an independent final review.

- Every part now requires `evidence_source=text|visual`. Text evidence must still literally occur in actual extracted text, including when visuals coexist. Visual evidence requires prepared visual payloads; its semantic accuracy remains unverified. Numerical date evidence retains precision checks.
- Smart mode discards the default image/video extractor's EXIF/basename/size explanations as text evidence, before checking content sufficiency or building the Provider request. Custom extractors retain their actual OCR/transcript text contract. Template and Watch paths do not take this branch.
- New tests exercise the real default image/video extraction functions with nonempty metadata. Media preprocessing and Provider responses remain test doubles: these tests establish routing and grounding guards, not image recognition or model quality. They cover visual success, metadata-as-text rejection, absent-frame failure before Provider invocation, mixed text/visual evidence, unavailable visuals, and missing/unknown evidence-source tags.

Raw RED/GREEN results (same interpreter/worktree as above):

```text
python -m pytest tests/unit/test_smart_naming.py tests/integration/test_smart_analysis.py -q --tb=line
64 failed, 27 passed, 3 warnings in 1.55s
RED: original renderer rejects the new evidence_source contract, accepts the missing tag, and does not reject metadata-only video before Provider invocation.

python -m pytest tests/unit/test_smart_naming.py tests/integration/test_smart_analysis.py tests/integration/test_batch_analysis_service.py -q --tb=short
97 passed, 3 warnings in 1.36s
GREEN: 74 smart unit + 17 smart integration + 6 existing batch integration.
```

Only the two policy/analysis implementation files, their two test files, and this report were modified for this follow-up. Nothing staged or committed. Existing three Pydantic deprecation warnings remain.

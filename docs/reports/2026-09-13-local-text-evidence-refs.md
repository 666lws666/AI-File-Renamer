# Local text-evidence reference protocol correction

Date: 2026-09-13

## Scope and root cause

This change is limited to the offline local-inference diagnostic runner and its
unit tests. It does not change SmartNamingPolicy, product providers, QML,
credentials, resources, network behavior, the reviewed corpus, or raw QA
evidence.

The prior schema accepted an arbitrary evidence string and the decoder passed
that string through unchanged. A model could therefore copy a real excerpt
with altered spacing; the unchanged policy would then correctly reject the
rewritten excerpt as ungrounded. The correction constrains model text evidence
to invocation-local opaque IDs and resolves those IDs back to the original
fragments before policy evaluation.

## Protocol changes

- text_evidence_spans(text) rejects non-string, blank, over-32-KiB UTF-8, and
  over-64-span inputs. It keeps original nonblank line content and splits long
  lines into literal chunks of at most 2,000 characters, numbered T000 onward.
- Text banks are copied and validated as nonempty mappings with ordered,
  contiguous canonical IDs, at most 64 entries, and nonblank values of at most
  2,000 characters.
- Text schemas enumerate exactly the current bank IDs. Visual schemas retain a
  bounded observation string. Mixed input uses exclusive per-source object
  branches.
- The decoder accepts only registered IDs for evidence_source=text and restores
  their exact fragments. Values, roles, language, and understood state remain
  model-generated and unchanged.
- Text runs save text-evidence.json and record its SHA-256 in result.json,
  including the retained second-memory-check failure path. Visual-only runs do
  not create that file.
- The prompt replaces the contradictory free-quote instruction with ID
  selection, embeds the bank inside the untrusted-text delimiter, preserves the
  visual-observation instruction, and clarifies that topic should not repeat a
  supplied entity and optional/context fields are not a checklist.

## TDD evidence

The initial collection attempt exposed and corrected a test-only unmatched
parenthesis before accepting RED. The accepted feature-missing RED was:

~~~text
D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_inference_probe.py -q -k "text_evidence_spans or text_schema_evidence_enum or both_modalities_use_exclusive or decode_rejects_unknown_id or date_id_resolves or prompt_has_aligned"
14 failed, 49 deselected in 1.40s
~~~

Failures were the expected missing helper/keyword API, unconstrained prompt,
and absent ID resolution. No model was loaded.

GREEN and regression results:

~~~text
D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_inference_probe.py -q
63 passed in 2.54s

D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_inference_probe.py tests/unit/test_smart_naming.py -q
157 passed in 2.60s

D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_inference_probe.py tests/unit/test_local_model_probe.py tests/unit/test_local_probe_process.py tests/unit/test_local_probe_resources.py tests/unit/test_local_semantic_corpus.py -q
219 passed in 19.76s
~~~

The tests use a generated temporary corpus, migrate text fake responses to IDs,
and retain assertions for original evidence, locale, raw output, the
month-precision date example, bank persistence/hash, and the visual-only path.

## Honest limitations

- No native model was launched for this change. It does not establish a
  semantic-quality pass for any case.
- The generic prompt clarification is contract-tested only; its effect on real
  model naming quality requires a new root-owned native run and human review.
- ID resolution proves that evidence is an exact supplied fragment. Semantic
  entailment and visual observations still require the unchanged policy and
  human review.
- Blank lines and line terminators are intentionally not bank entries; all
  nonwhitespace line content is preserved, as required by the bounded protocol.

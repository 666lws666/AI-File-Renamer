# Local nullable metadata grounding diagnostic report

Date: 2026-09-13

## Scope

This is a bounded correction to the existing offline diagnostic protocol. It
changes only the local inference probe, its unit tests, and this report. It does
not change SmartNamingPolicy, product providers, QML, process supervision,
model/runtime resources or arguments, the reviewed corpus, Golden files,
credentials, network behavior, or prior raw QA evidence.

The correction responds to rejected v2 diagnostic outputs: absent text metadata
was represented by invented placeholders/defaults, visual dates could be emitted
in noncanonical form, and requested output language was not reliably followed.
Those earlier outputs remain recorded failures; this change does not rewrite or
reinterpret them.

## Implemented profile

- The result protocol identifier is now `local-summary-v3`; it is deliberately
  absent from the model prompt so it cannot be mistaken for document metadata.
  Results retain the executing runner SHA-256.
- A successful `understood=true` response has exactly `understood`, `language`,
  `topic`, `date`, and `version`. Topic remains required. Date and version are
  required nullable fields, and null values add no common-policy parts. The
  refusal branch remains exactly `understood` and `language`.
- `text_metadata_choices` conservatively derives bounded date/version candidates
  from the invocation's exact T000-style evidence bank. Text schema branches use
  singleton value/evidence/source enums, and the decoder independently recomputes
  exact membership, preventing wrong-ID pairings and free/default metadata.
- Supported text dates require an explicit Chinese or English date/time label and
  colon, then ISO-numeric or Chinese year/month/day syntax. Same-precision ordered
  ranges normalize to `~`. Calendar-invalid, ambiguous, malformed, incomplete,
  mixed-precision, reverse, or unlabeled values produce no candidate rather than
  being truncated or downgraded. English labels require a word boundary while
  Chinese suffix labels such as `维护时间` remain supported.
- Supported text versions require an explicit version label plus a numeric token
  with optional v/V prefix, or a whole fragment consisting solely of a v/V token.
  Prefix and case are preserved. Equal value/ID pairs are deduplicated; more than
  16 candidates for either role rejects instead of truncating.
- Visual metadata remains nullable. A non-null visual date must full-match the
  numerical ISO/range grammar before reaching unchanged common calendar and
  grounding checks. The local grammar does not normalize model-generated Chinese
  date text or accept placeholder strings.
- The prompt gives an own-language zh-CN, zh-HK, or en-US instruction, requires
  null instead of absent-metadata placeholders/defaults, keeps the original text
  bank separate from allowed metadata choices, and requests a concise central
  object/issue/action across all pages or frames. Decoder language sanity remains
  intentionally coarse: a Chinese topic needs a CJK character and an English
  topic a Latin letter.
- Text runs persist `metadata-evidence.json` and its SHA-256, including retained
  second-memory-check failures. Visual-only runs neither create nor hash that
  file. Raw stdout/stderr retention and protocol/policy failure behavior remain
  unchanged.

## TDD evidence

Initial RED, before production implementation:

~~~text
D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_inference_probe.py -q
41 failed, 62 passed in 4.06s
~~~

The failures covered the missing candidate enumerator, old v2 schema/decoder and
prompt, absent metadata evidence persistence, and old result protocol identity.

Review then identified four same-scope parser boundaries: day zero, English
labels embedded in ordinary words, slash-form malformed dates, and incomplete
ranges. Regression tests demonstrated RED before the correction:

~~~text
D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_inference_probe.py -q -k "text_metadata_choices_rejects or text_metadata_choices_recognizes"
5 failed, 7 passed, 95 deselected in 1.32s
~~~

Runner-only GREEN used fake process outputs and launched no model:

~~~text
D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_inference_probe.py -q
107 passed in 2.63s
~~~

Required focused runner plus unchanged common policy GREEN:

~~~text
D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_inference_probe.py tests/unit/test_smart_naming.py -q
201 passed in 4.75s
~~~

Five local diagnostic files GREEN:

~~~text
D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_inference_probe.py tests/unit/test_local_model_probe.py tests/unit/test_local_probe_process.py tests/unit/test_local_probe_resources.py tests/unit/test_local_semantic_corpus.py -q
281 passed in 20.53s
~~~

Successful fake response fixtures explicitly provide nullable metadata. The raw
JSON helper was not changed to insert fields, so missing-field and malformed
fixture tests still exercise the protocol boundary. Corpus tests use generated
temporary inputs rather than ignored QA evidence.

## Honest limitations

- The implementer ran no native model, network, or credential operation. Unit
  GREEN proves deterministic protocol enforcement, not semantic quality, output
  language quality, visual entailment, or acceptable names for cases 01-08.
- Candidate extraction is intentionally conservative, not a universal date or
  version parser. Unsupported labels/formats become null-only choices even when a
  human could infer metadata.
- The visual date grammar is only a syntactic gate. Common policy and root-owned
  source/visual review still decide calendar validity, grounding, and meaning.
- Coarse CJK/Latin presence is not full language recognition. A topic can pass it
  while remaining poorly translated, generic, repetitive, or inaccurate.
- Root-owned native reruns and human review remain required. No semantic PASS is
  claimed by this report, and previously recorded rejected responses remain
  untouched.

## Task 2: v3 closure and v4 prompt experiment

After Task 1 froze, root ran all eight actual zh-CN cases with v3 runner SHA
`df252133ecf787dab0dad81fe3859d7d9867f0ae5dda85df1b8fadd271db3b46`.
The original evidence remains unchanged. Case02 and case03 stopped inventing
metadata; case05 still copied an English heading and was rejected by the local
language boundary; case06 emitted only a year despite a visible month; case07
became a generic category. These observations are v3 gaps, not v4 quality claims.

The bounded closure made these changes without adding fields, formats, examples,
or output repair:

- Date extraction now rejects an otherwise valid prefix when the remaining token
  continues with unsupported date units, another range endpoint, or an alternate
  year. Thus spaced invalid Chinese dates, three-endpoint ranges, and `or` years
  become null-only candidates rather than shortened values.
- Numeric-only labelled versions no longer accept a prefix before unsupported
  `-` or `_` suffixes. Existing supported dates, ranges, and versions remain
  unchanged.
- The removed/unknown-field test now supplies valid explicit null metadata, so it
  proves the unknown field itself causes rejection.
- Results now identify `local-summary-v4`, still only outside the prompt. Topic
  schema objects order `evidence_source`, `evidence`, then `value`; exact metadata
  candidate objects retain their prior order and contents. Evidence-first topic
  generation is an autoregressive prompting hypothesis, not proof of grounding.
- The full instruction contract is independently written in zh-CN, zh-HK, and
  en-US. Each version preserves refusal, untrusted-input, evidence, nullable
  metadata, concision, central object/action, no defaults, and no path/extension
  constraints. A final post-input reminder repeats the requested topic language
  and requires retaining known date precision without inventing missing detail.
  Video instructions ask for defining central processes/actions rather than only
  a broad category.

Task 2 RED before runner changes:

~~~text
D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_inference_probe.py -q
21 failed, 93 passed in 3.41s
~~~

Task 2 runner GREEN:

~~~text
D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_inference_probe.py -q
114 passed in 2.93s
~~~

Runner plus unchanged shared policy GREEN:

~~~text
D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_inference_probe.py tests/unit/test_smart_naming.py -q
208 passed in 2.98s
~~~

Seven diagnostic/resource/corpus/process/helper files GREEN:

~~~text
D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_inference_probe.py tests/unit/test_local_model_probe.py tests/unit/test_local_probe_process.py tests/unit/test_local_probe_profile.py tests/unit/test_local_probe_resources.py tests/unit/test_local_probe_security.py tests/unit/test_local_semantic_corpus.py -q
375 passed in 20.88s
~~~

The implementer launched no model, network, credential, or Git operation for
Task 2. These deterministic tests do not show that v4 fixes case05 language,
case06 visual precision, case07 specificity, or any other semantic outcome.
Root-owned native reruns and human source/visual review remain required.

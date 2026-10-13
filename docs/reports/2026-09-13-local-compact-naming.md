# Compact local naming diagnostic report

Date: 2026-09-13

## Scope

This change is a diagnostic protocol experiment only. It modifies the local
inference probe and its unit tests. It does not change SmartNamingPolicy,
product providers, QML, model/runtime resources or flags, the generated corpus,
Golden files, credentials, network behavior, or prior raw QA evidence.

The previous local diagnostic allowed entity and up to three context values.
Real case01 and case04 runs at the prior checkpoint showed that generic omission
advice did not prevent repeated entities and long enumerations. Existing text
evidence IDs worked and were retained unchanged.

## Implemented profile

- Added the fixed diagnostic protocol identifier local-summary-v2. Every result
  created after input preparation records diagnostic_protocol and the SHA-256
  of the executing runner as runner_sha256.
- The model-facing true response now contains one required topic and only
  optional date and version roles. The false branch remains exactly understood
  and language. Entity, context, and arbitrary fields are rejected.
- Topic values are bounded to 64 UTF-16 units for zh-CN/zh-HK and 120 for en-US.
  Date is bounded to 21 units and version to 24. Matching conservative JSON
  Schema maxLength values are present, while decoder-side UTF-16 counting
  rejects astral-character overflow without truncating or repairing values.
- The decoder still resolves only current-bank text IDs and preserves repeated
  references as the same exact original fragment. Visual evidence remains a
  bounded specific observation. Allowed roles are adapted into unchanged
  SmartNamingPolicy parts in date-topic-version order.
- Replaced the inherited multi-role prompt with a compact, self-contained
  contract covering the selected language, untrusted inputs, refusal,
  text-ID/visual evidence rules, supported date precision, concise title-size
  guidance, non-enumeration, no invented facts, and no path/extension or prose.
  Prepared text appears only inside its evidence bank.
- Added an integration test proving that a protocol-valid topic value 报告 with
  registered T000 reaches SmartNamingPolicy, returns
  smart.error.genericName, and retains decoded parts, raw bytes, and result.

## TDD evidence

Accepted RED:

~~~text
D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_inference_probe.py -q
24 failed, 49 passed in 3.13s
~~~

The failures were caused by the old five-role schema/decoder, old 180-character
role bound, old prompt, and missing diagnostic/result identity fields.

After the minimal implementation, one stale test still expected the old
smart-v1 prompt label:

~~~text
1 failed, 72 passed in 2.90s
~~~

That intentionally changed expectation was updated to local-summary-v2.

Required focused GREEN:

~~~text
D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_inference_probe.py tests/unit/test_smart_naming.py -q
167 passed in 2.92s
~~~

Five local diagnostic files GREEN:

~~~text
D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_inference_probe.py tests/unit/test_local_model_probe.py tests/unit/test_local_probe_process.py tests/unit/test_local_probe_resources.py tests/unit/test_local_semantic_corpus.py -q
229 passed in 20.60s
~~~

All inference-process tests used fake outputs. Corpus-dependent tests generated
their own temporary corpus and did not depend on ignored QA evidence.

## Honest limitations

- No native model or network operation was run by the implementer. These tests
  do not establish semantic quality for case01, case04, or the language/media
  matrix.
- The smaller response shape prevents entity/context fields at the protocol
  boundary, but the model can still write a poor, repetitive, or inaccurate
  topic. Root-owned native runs and source/visual review remain required.
- SmartNamingPolicy remains unchanged, including its common 180-UTF-16-unit
  final-stem bound and its limited ability to verify visual semantics.
- Previously documented P2 items remain outside scope: conservative rejection
  around whitespace-only evidence chunks/self-consistency and result retention
  for failures before the evidence bank/result base exists.

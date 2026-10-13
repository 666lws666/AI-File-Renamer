# Native model-bundle staging verification

## Scope and result

Verified the new streaming stage on Windows/NTFS using the pinned public CPU
runtime, Qwen3.5-4B Q4_K_M weights and F16 projector. **Stage verification PASS**;
this check neither provisioned an AppContainer profile nor launched a child or
model. It is not a model-compatibility or local-privacy product verdict.

Source commits: `3d9de33`, followed by security fix `f9b6973`.

## Independent review and tests

The initial review found a revalidation bypass: after a reopened member failed
hash verification, a repeated check could trust the retained handle. The fix
permanently invalidates the bundle on failed revalidation while retaining exact
cleanup ownership. The negative regression reproduced the second-check bypass
before the fix, then verified repeated rejection and successful cleanup afterward.
Independent re-review approved this scoped fix and lifecycle behavior.

Root fresh command:

```text
python -m pytest tests/unit/test_local_model_stage.py tests/unit/test_local_probe_stage.py -q
150 passed in 0.29s
```

The native positional-read primitive was separately exercised on the real
2,740,937,888-byte model: reading the last byte returned one byte; reading at EOF
returned zero bytes. This checks the actual large-offset binding, not a fake.

## Actual Windows run

Ignored evidence:
`tests/screenshots/qa-current/local-privacy/model-stage-native-679a15ae997343e99865dcf13a04fbf2/result.json`.

- 53 members: 51 verified runtime files plus weights and projector.
- Total copied bytes: **3,460,111,485**.
- Bounded streaming copy, destination content hashes and protected ACL readback
  passed. Recheck matched exact file/directory identities and sizes.
- Executable/DLL package access: read/execute; model/projector access: read only.
- Original resources and ancestor ACLs were not changed.
- Exact-owned cleanup: complete; all handles closed; no remaining or uncertain
  paths; no cleanup failures. The source resources remain available.
- Profile creation: false. Child launch: false. No network or credentials used.

Raw evidence includes exact identities and ACL facts and remains outside Git.
No formal Golden, product UI, main checkout, executable package, push or release
was changed by this task. The next gate is actual bounded contained inference
with parent-verified token and its own process/semantic/cleanup evidence.

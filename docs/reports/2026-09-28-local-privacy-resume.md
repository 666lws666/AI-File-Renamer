# Local privacy resume: safe checkpoint, real-inference memory blocker

## Repository and completed work

- Main checkout remains `feature/xuxia-m0-foundation` at
  `4feb71200c08b18f0fe550295b624f9915577ae1`; the user's untracked shortcut is retained.
- Work is isolated in `.worktrees/ai-smart-naming`, branch
  `codex/local-privacy-mode`.
- Resumed from `2c39e4832bfd15646c5951f545c3daf8b4711e5b` without replacing its
  pending implementation or evidence.
- `dbd7faf91cd63aa6e0f6108766b6c3ceffc8e458`: checkpoint the reviewed, fake-tested
  owned-profile helper. Native profile provisioning/network denial is NOT proven.
- `0a57d58c537952eb90ac22cc0f2dcee0eae06ed8`: checkpoint nullable, source-grounded
  local metadata and the v4 localized diagnostic, including preserved failures.

## Fresh test evidence

Windows project interpreter: `D:\文件AI-AGENT\.venv\Scripts\python.exe`.

```
python -m pytest tests/unit/test_local_inference_probe.py tests/unit/test_smart_naming.py tests/unit/test_local_probe_process.py tests/unit/test_local_probe_security.py tests/unit/test_local_probe_profile.py tests/unit/test_local_model_probe.py tests/unit/test_local_probe_resources.py tests/unit/test_local_semantic_corpus.py -q
520 passed in 78.43s (0:01:18)
```

`git diff --check` passed. Worktree was clean after the two checkpoints.
These focused results are not a fresh full-product/package/visual regression.
No new actual model inference was launched on this resume.

## Remaining language failure: evidence, not another guessed fix

The preserved v4 case05 text-PDF run contains all 1169 extracted text bytes,
two pages, no image/OCR path, and explicit zh-CN instructions. Raw output still
copies `Cedar Research Library Scanner Evaluation`. The model exits normally;
the diagnostic rejects its topic at `_validate_topic_language`. Its native
terminal marker is handled correctly. The same failure appeared under v3,
whereas the English text case03 produced a Chinese descriptive name.

Independent read-only tracing confirms PyMuPDF page text is joined and then
split into one evidence ID per nonblank line. Case05 therefore contains 20 short
fragments, including a repeated leading heading; case03 has six longer text
fragments. This is a confirmed pipeline difference, NOT a proven cause of the
language failure.

Next bounded experiment, when memory permits: preserve every source character,
ordering, heading and frozen model/runtime/decode setting, changing only how PDF
wrapped body lines are grouped into evidence fragments. Compare raw model output
with the preserved v4 run. Do not insert expected names, translate by string
substitution, weaken the language validator or claim one comparison proves
general model quality. No new protocol implementation has been made here.

The scanned PDF v4 result preserved the correct month and version. The video
result remained broad; record that specificity limitation rather than fabricating
missing distinctions. Three-language acceptance and template-field inference
remain pending, as do native AppContainer enforcement and product integration.

## Blocker and restart condition

Read-only Windows memory checks returned first 293468 KiB available, then
1177012 KiB after the tests (about 1.12 GiB). The existing 5 GiB model preflight
is unchanged. No llama-completion, llama-mtmd-cli or llama-server process was
present at the final check. No user process was ended and no paging/security
setting was changed.

Before actual inference, check memory again and require the existing preflight.
Keep raw failed runs. Do not label local mode ready until real semantic and
outbound-isolation gates pass. No cloud API, credentials, private sample, Golden
update, main merge, push or release was performed.

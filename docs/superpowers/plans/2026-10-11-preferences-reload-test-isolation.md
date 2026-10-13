# Preferences verification reload test isolation

Bounded prerequisite to guarded all-suite validation, not a product feature.

## Confirmed defect

Root Windows full-suite guard records exactly one denied real credential lookup:
`test_qwen_full_workflow_persists_verification` uses FakeCredentialStore for settings
but reloads `load_config()` after permanently overwriting CONFIG_FILE/CONFIG_DIR.
The metadata/verification assertions do not require legacy Credential Manager.

## Scope and requirements

- Only modify `tests/integration/test_preferences_save_flow.py`; root owns this
  plan/Git/review. Do not touch config, credentials, settings, Qt or any product file.
- Change the named test reload to explicit `load_config(config_file,
  load_credentials=False)` and remove assignments to global CONFIG_FILE/CONFIG_DIR.
- Strengthen the same existing test to fail on any real credential function during
  reload, assert blank legacy api_key, exact original config-global identity/value
  preservation, and persisted key-free JSON/active verified Qwen metadata. Keep
  all existing simulated connection, FakeCredentialStore and restart assertions.
- First add the negative assertions/strict deny test instrumentation and run the
  named test against its current reload path. Preserve expected RED for attempted
  credential access or global mutation, before correcting that reload. Do not
  suppress a deny failure merely because production load_config catches errors.
- Run named RED→GREEN, then whole test file once, project Windows interpreter,
  isolated temp user dirs and socket/keyring/core/WinVault/native credential guards
  before imports. Count denied calls explicitly; GREEN must be zero. No API, Key,
  CM, private files, firewall/ACL, Golden, skips/exclusions/xfail, build, Git writes,
  push/merge/release or other source modifications.
- Report exact commands/raw results, zero guard attempts, failure then correction
  evidence to `.superpowers/sdd/preferences-reload-test-isolation-report.md` and
  self-review concerns. No broad suite; root runs it. Leave source unstaged.

## Scoped result

Writer recorded RED one attempted application credential entry despite caught
exception, then GREEN one named case and10 whole-file cases; zero credential/network
guard attempts and complete successful process exits after correction. Three old
Pydantic deprecations remain reported. Fresh read-only scoped review: spec PASS,
quality Approved, no blocking issue. Root owns full guarded Windows regression and
does not equate these focused results with whole-product acceptance.

Root complete Windows non-screenshot regression with final fixture correction:
4202 passed,3 existing skips,4 existing deprecation warnings81.80s. Strict network
and credential guards recorded zero attempts; pytest return0, actual atexit reached
and native process exit0. Normal GC and unchanged backend. Previous failed runs
remain in ignored QA, not reclassified. This is current regression evidence, not
proof of model quality, final Watch/resource/UI completion or packaged READY.

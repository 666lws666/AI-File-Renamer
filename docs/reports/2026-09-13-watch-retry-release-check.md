# Watch retry release check — 2026-09-13

## Scope and implementation

Starting source: `7e1c082`, Windows branch `feature/xuxia-m0-foundation`.

- Cancel and invalidate scheduled observer retries on pause, resource pause,
  stop, removal, and successful explicit resume.
- Give each scheduled retry an identity token. A callback already dispatched
  before cancellation cannot reactivate a stopped watch or consume a later
  retry for the same watch ID.
- Retry only ERROR watches. Persist ACTIVE before publishing that state in
  memory. If persistence fails after observer start, stop the observer and
  preserve ERROR; further attempts remain bounded by the configured limit.
- Remove one obsolete preset test that embedded a third-party product name.
  All preset functionality/integrity tests remain. This is an intentional
  test-count reduction of one, not a skipped release gate.

## Fresh Windows evidence

Python: project `.venv`, Python 3.14.5. No live cloud calls or real credentials.

| Verification | Result |
| --- | --- |
| New integrity regressions before implementation | 6 failed, 11 passed |
| Watch integrity/controller/recovery after implementation | 70 passed |
| Independent read-only review, two Watch unit-test files | 59 passed |
| Provider contracts + connection-test mocks | 118 passed |
| `pytest tests/ --ignore=tests/screenshots -q --tb=short` | 1756 passed, 1 skipped |
| M1 visual comparison, updates disabled | 49 passed |
| M0 screenshot infrastructure, updates disabled | 5 passed, 1 skipped |
| `scripts/build_windows.ps1` | Exit 0 |
| `pytest tests/packaging -q --tb=short`, after rebuild | 23 passed |
| `python acceptance_test.py`, after rebuild | 186/186 passed |
| `git diff --check` | Exit 0 |

The two existing skips are the platform-dependent symlink test and the
update-mode screenshot test. Existing Pydantic/Pillow deprecation warnings
remain. PyInstaller reports optional missing `tzdata`/Qt asset-downloader
components; the packaged application/media/language smoke checks passed.

M1 comparison uses `QT_SCALE_FACTOR=0.8` on this Windows 125% display to match
the existing 100% baseline. M0 is run separately with that variable removed.
`UPDATE_GOLDENS` is removed for both commands. No screenshots, assertions or
comparison tolerances were changed by this fix.

## Windows artifact

- Executable: `dist/Xuxia/Xuxia.exe`
- SHA-256: `A93D9FD5423F1389A62665F98C447D4C08883E86595E482F2287E721FB39296B`
- Executable size: 10,951,418 bytes
- Complete onedir artifact: 3,081 files; 567,791,275 bytes
- The existing local shortcut still targets this artifact.

## Cloud boundary

The 118 contract/probe tests use in-memory transports. They cover successful
structured responses, authentication errors, rate limits/retries, malformed
responses, and the unverified-profile connection gate. Success against an
actual service still depends on endpoint/model availability, correct account
permissions/credentials, network access and compatible responses. No live
connection or real naming-quality claim is made.

## Publication boundary

The current tracked source is neutral. Older local development history is
not a publication artifact. Prepare `codex/github-clean-snapshot` from the
verified current tree with the existing local `origin/master` as its parent,
after checking that parent's reachable history. Preserve the original local
development branch; do not amend/rebase it, push it with `--all`/`--mirror`,
or include local research/configuration/credentials/generated artifacts.

No push, release, history deletion, or remote refresh was performed. The
local remote-tracking reference does not prove that the remote has not
changed since its last refresh; confirm it before a future authorized push.

## Nonblocking backlog

- Add remove/recreate-same-ID retry coverage and exact observer-attempt counts.
- Modernize existing deprecation warnings in a separate maintenance change.
- Keep DPI setup and user-manual screenshots synchronized with future UI work.

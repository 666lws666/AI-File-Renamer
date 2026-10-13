# QML fixture actual-deletion correction

Bounded test-infrastructure correction after a normal-GC full Windows run printed
4193 passed / pytest status0, then exited1; a diagnostic repeat printed the same
summary before native access violation0xC0000005. Those runs are not process PASS.

## Confirmed defect (not an assumed crash root cause)

Root reproduced `QmlTestHandle(TaskCard.qml, controller=MockBatchController())`:
after current cleanup, held native engine/view/root are all still `isValid=True`,
and seven QML `i18n.locale`-of-null warnings arise. Only an explicit DeferredDelete
flush subsequently invalidates the native objects. cleanup drops context holders
before actual destruction, and independently schedules the view-owned engine.

Fix this deterministic lifecycle defect. Whether it resolves the complete-process
AV is a separate root validation; no causal claim solely from the reproduction.

Root review of the first candidate found a second deterministic fixture issue:
the synchronous inline-empty test remained on its creator Python thread, but the
retained QThread wrapper had become native-invalid. Comparing wrapper identity
therefore rejected valid owner cleanup. The final guard must capture stable creator
Python thread identity and, while the actual engine is valid, query fresh native
engine affinity. It must not authorize cleanup by a retained QThread wrapper.
Cover actual foreign-worker rejection before mutations and creator cleanup despite
an altered Python currentThread adapter return; both must preserve real native
disposal and warning capture. Existing failed candidate outputs stay recorded.

## Ownership, scope and constraints

- Base `f9148c5e1009d070bbaeb1c198b408cc33e62bfb`, isolated worktree
  `D:\文件AI-AGENT\.worktrees\ai-smart-naming`, branch codex/local-privacy-mode.
- Only modify `tests/qml/conftest.py`; create
  `tests/qml/test_qml_fixture_lifecycle.py`. Root owns docs, Git and review.
- No product/UI/QML/layout/locale/config/credential/media/Provider code changes.
  No assertions or screenshot tolerances changed, no test exclusions/skips/xfail,
  no global GC disabling, no offscreen/native backend workaround, no Golden update.
- Synthetic mock controls only, isolated temp user directories. Hard block real
  sockets/keyring/WinVault before imports. No API/Key/CM/private inputs/network,
  firewall/ACL settings, build/push/merge/release or broad source audit.
- Preserve caller-owned injected controllers; cleanup is not authority to delete
  them. Keep all QML context holders alive until their UI objects are really gone.

## Exact deliverable and TDD

1. First add failing tests using the actual QmlTestHandle/native Qt objects and
   `shiboken6.isValid`, not a mock deleteLater assertion. Cover both a real hosted
   QQuickView with TaskCard and engine-only component, plus idempotent second
   cleanup. Keep original wrappers to test actual deletion after cleanup returns.
2. Before source change run tests and retain the expected live-native-object/null
   context failures. Tests must safely finish real deletion in a finally fixture
   on the old implementation as well; that safety must run AFTER behavior assertions.
3. Make cleanup explicit and owner-thread-only, idempotent. Close/delete the
   root/view and drain their DeferredDelete events while i18n/design/controller
   references still exist. Dispose owned standalone component/engine after its
   root is gone. A QQuickView owns its engine: do not separately schedule deletion
   of that borrowed engine after the view destroys it. Use actual Qt validity to
   handle already deleted wrappers; don't use broad exception swallowing to hide
   failed disposal. Process required events without dropping contexts first.
4. Retain existing warning collection during cleanup, rather than disconnecting
   or filtering it before teardown. New lifecycle cases must have no teardown
   warnings as well as native root/engine/view invalidation. Break self-capturing
   callback ownership safely when its engine is destroyed/retired; no warning
   suppression. Existing creation, injection, dimensions and click behavior stay.
5. Borrowed injected controller stays valid and usable after cleanup, and two
   consecutive cleanup calls produce no native double-delete or warning. Tests
   retain normal GC. Do not delete/recreate the session QApplication as a workaround.
6. Run the new lifecycle test file RED→GREEN, then full `tests/qml` once with the
   same guard wrapper. Report exact raw summaries/exits; do not run the full global
   suite or manufacture complete-process crash resolution. Root runs that Gate.

## Handoff

Write complete report to `.superpowers/sdd/qml-fixture-lifecycle-report.md` with
files, RED/GREEN outputs and command safety, ownership/disposal order, self-review
and concerns. Do not stage or commit. Return compact status/test summary only.

## Bounded checkpoint evidence

Final native guard revision: writer9 lifecycle cases passed/exit0; QML312 passed,
3 existing Pydantic warnings22.80s/complete exit0. Fresh scoped review spec compliant
and quality Approved with no blocking finding. Root independently ran lifecycle
plus named inline-edit file:20 passed1.40s, zero forbidden access attempts, pytest
return0, atexit reached and native process exit0. This validates the task scope,
not a causal attribution for the earlier global interpreter AV. Global full-suite
validation follows separate legacy Preferences test credential-isolation correction.

# Production managed Watch composition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make default production Watch genuinely usable through the shared managed privacy/analysis/file-operation chain.

**Architecture:** One owned ManagedWatchRuntime uses the existing reviewed ingress, analysis delivery, results and file actions, and borrows the exact Batch analysis service and serial file lane. A bounded shared self-event owner holds original admitted events before genuine operation-result reconciliation. No legacy handler or new AI/file engine.

**Tech Stack:** Python 3.14, PySide6/Qt Quick, watchdog, existing native held-handle file boundary and temporary JSON/JSONL stores.

## Global Constraints

- Use only `D:\\文件AI-AGENT\\.worktrees\\ai-smart-naming` on `codex/local-privacy-mode`; preserve main checkout and user shortcut.
- No push, release, merge, historical rewrite, Golden update, real cloud API/key/Credential Manager/private inputs, firewall/ACL/exemption/security-policy changes.
- Cross-volume automatic moves remain disabled; no os.rename/shutil/copy/delete fallback in the reviewed engine. Preserve original files and recovery evidence.
- All test configs/stores/credentials/transports are isolated/fake; screenshots and raw diagnostics only in `tests/screenshots/qa-current/local-privacy/`.
- One source/test writer; fresh task review and root frozen verification before a source checkpoint. Source PASS is not real model/GUI/package PASS.
- No silent cloud fallback. No invented confidence or unverified readiness. No persisted pending row/intent grants analysis or disk authority.
- Exact shared analyzer/authority/catalog and serial file lane; no duplicate service graphs, no Qt callbacks from watchdog/Timer workers.

## Task 1: Complete the coherent owned production Watch chain

Binding design: `docs/superpowers/specs/2026-10-12-production-managed-watch-design.md`.
Detailed task contract: `.superpowers/sdd/watch-activation-20261012-brief.md`; source-grounded interface inventory: `.superpowers/sdd/watch-activation-map-20261012-report.md`.

**Source ownership:**
Create `src/controllers/managed_watch_runtime.py`, `src/core/watch_self_events.py`.
Modify bounded integration seams only in `src/qml_bootstrap.py`, `src/controllers/managed_watch_results.py`, `src/controllers/managed_watch_file_operations.py`, `src/controllers/watch_controller.py`, `src/controllers/managed_file_operation_lane.py`, `src/services/file_operation_backend.py`, `src/controllers/watch_page_controller.py`, `src/ui_qml/WatchResultsPanel.qml`, three existing locale JSONs.
If actual pre-move observation cannot be provided by backend/lane alone, allow a small optional non-authorizing callback seam in `src/core/rename_executor.py` / `src/core/undo_manager.py`; no native move, Preflight, history codec or safety algorithm rewrite.

**Test ownership:**
Create `tests/integration/test_managed_watch_runtime.py`, `tests/unit/test_watch_self_events.py`.
Bounded additions in existing managed Watch results/file-operation/binding/lifecycle tests, `tests/unit/test_watch_page_controller.py`, `tests/qml/test_watch.py`, `tests/qml/test_qml_bootstrap.py`, `tests/integration/test_managed_processing_runtime.py`, `tests/unit/test_file_operation_backend.py`, `tests/integration/test_managed_file_operation_lane.py`. Existing C1D assertions that default Watch is None must explicitly exercise injection=None or move to the new owned-default contract; do not delete protected assertions.

**Interface requirements:**
- Owned runtime exposes page, controller, delivery, results, actions and receipts; inert constructor, `start()`, `begin_close()`, `poll()`, `workers_idle`.
- Newly-published hook is synchronous, receives the exact result and newly saved ReviewItem, invoked only during genuine publication. Existing delivery authentication is unchanged.
- Managed file Auto Apply API checks a captured `is_authorized() is True` predicate immediately before actual lane commit, after every callback/durable change. Manual apply remains explicit independent authority.
- Page approve/retry/ignore/undo methods return truthful Boolean; retry is a new current admission, not saved-work reconstruction.
- Self-event owner uses typed lane/row receipts, original admitted events and actual successful NativeFileIdentity + SourceFingerprint. Fixed-path-only ignores are forbidden.

- [ ] Step 1: Add failing end-to-end construction and public action tests before implementation.

Concrete assertions after the new real runtime is built with isolated fake AI:
```python
assert runtime.watch_controller is not None
assert runtime.watch_owner.analysis_service is runtime.analysis_service
assert runtime.watch_owner.file_lane is runtime.file_operation_lane
assert observed_start_had_all_consumers is True
assert credentials.real_reads == transport.real_calls == 0
assert page.approveResult(recovery_item_id) is False
```
Use actual existing fakes/helpers rather than inventing non-executable fake APIs. The two counters above belong to the new fixture; no real Credential Manager/network is imported before guards.

- [ ] Step 2: Run RED with the guarded candidate interpreter and preserve actual output. Separate feature absence from a physical negative witness. Drain every real test thread even in RED.

- [ ] Step 3: Build the bounded runtime/results/action/retry integration. Preserve existing public injection semantics, old stores and templates. Implement the private publication hook and final Auto Apply recheck.

Authorization core:
```python
def is_authorized():
    return (not owner.closing
            and delivery.is_publishing_result(result)
            and controller.managed_binding_state(result.event) is WatchBindingState.READY
            and authority.is_current(result.event.admission.work.context)
            and result.event.admission.watch_config.mode is WatchMode.AUTO_APPLY
            and results.item(saved.id) is saved
            and auto_apply_review_reason(saved.managed_metadata) == "")
```
The file-action admission snapshots the original saved row identity before its APPLYING replacement and retains that captured proof; its final predicate must compare the exact admitted transition/current row rather than rejecting its own legitimate state change. No public refresh or persisted result can reconstruct this closure.

- [ ] Step 4: Add true RED self-event receipt tests and implement hold/reconcile for shared Batch/Watch Apply/Undo and compensation candidates before enabling default Watch. Retain original authority/context and bounded held owners.

Test the actual rule:
```python
assert held.admission is original_admission
assert held.admission.work.context is original_context
assert replacement_identity != completed_identity
assert decision_for_replacement == "allow"
assert decision_for_matching_owned_result == "suppress"
assert unrelated_sibling_decision == "allow"
```
Counters must show actual AI calls absent for owned self-events, present for an unrelated current replacement, and absent for released stale context after a local-mode switch. A hash/size/path assertion alone is not native identity evidence.

- [ ] Step 5: Wire default Watch only after common services/catalog, register partial owners immediately, attach QML then start. Add combined cleanup polling and Qt-thread presentation notices/Undo/recovery/coverage labels.

- [ ] Step 6: Run the full named synthetic matrix, resource/delivery/lifecycle and unchanged safety coverage. Include real queued Qt callbacks and real blocked workers; no forced GC or pool abandonment.

- [ ] Step 7: Freeze source; write complete private report with RED/GREEN/raw commands, all changed paths, exact interfaces, actual process/thread cleanup, forbidden attempts and limitations. No Git writes by implementer.

- [ ] Step 8: Root writes complete task diff package; independent fresh task reviewer returns both spec and quality verdicts. Fix actual Critical/Important findings with covering tests; record ordinary deprecations/backlog.

- [ ] Step 9: Root runs frozen integration/native/full non-screenshot/formal screenshot/acceptance Gates with updates off. Old stale packaged artifact and private historical diagnostic failures stay honestly separate until new package work, not weakened.

- [ ] Step 10: After approved scoped review and truthful verification, root commits exact source/test/design/plan files. Do not merge or push. Continue resource/UI/model/package tasks from the new safe checkpoint.

## Exact covering command

```powershell
& '.\\tests\\screenshots\\qa-current\\local-privacy\\qt612-candidate\\venv\\Scripts\\python.exe' '.\\tests\\screenshots\\qa-current\\local-privacy\\qt612-candidate\\run_guarded_pytest.py' tests/integration/test_managed_watch_runtime.py tests/unit/test_watch_self_events.py tests/integration/test_managed_watch_analysis.py tests/integration/test_managed_watch_binding.py tests/integration/test_managed_watch_resource_delivery.py tests/integration/test_managed_watch_results.py tests/integration/test_managed_watch_file_operations.py tests/integration/test_managed_watch_lifecycle.py tests/integration/test_managed_processing_runtime.py tests/unit/test_watch_page_controller.py tests/qml/test_watch.py tests/qml/test_qml_bootstrap.py tests/unit/test_file_operation_backend.py tests/integration/test_managed_file_operation_lane.py -rs
```
Verify exact existing lifecycle/lane test paths before dispatch; actual repository paths, not invented names, govern. Missing path is not permission to omit coverage silently.

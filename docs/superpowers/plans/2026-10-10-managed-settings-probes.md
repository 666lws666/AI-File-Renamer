# Managed Settings credential policy and asynchronous fixed probes

This is C1C following coordinator and managed Batch publication. The runtime
composition will inject these explicit contracts in C1D. Keep existing explicitly
injected synchronous connection-test fixtures compatible. No new HTTP stack or
connection error-classification redesign.

## Scope

- `src/controllers/settings_controller.py`
- `src/controllers/managed_connection_runner.py` (new bounded runner)
- `src/ui_qml/ProviderForm.qml` (candidate lifecycle invalidation hook only)
- `tests/unit/test_managed_connection_runner.py` (new)
- `tests/unit/test_settings_processing_policy.py` (new)
- Existing focused Settings/Provider tests as necessary, with actual behavioral
  assertions; no static assertions masquerading as an interaction test

Root owns Git/review; one writer. No bootstrap, Watch, Batch, Provider transport,
connection_test.py, transaction engine, preparation/model/resources, other QML,
layout or Golden changes. No actual API/key/Credential Manager/private input,
system settings, push or release. Tests use fake services and temporary stores.

## Runtime input publication hook

Add an explicit private successful-commit callback and optional precommit input
preparer to SettingsController. The preparer builds/validates an immutable candidate
analysis catalog before the transaction; failure leaves file, credentials and live
config unchanged. On transaction success, install the prepared catalog/invalidate
processing work BEFORE draft/profile/save success public signals or the injected
external event publisher. The production callback is an owner-thread, prevalidated
bounded operation, not disk/model/network work.

Buffer transaction publisher notifications until this ordering has been fulfilled
in managed mode; legacy injection keeps its existing semantics. Failed/rolled-back
transactions do not publish a candidate catalog. Do not change SettingsSaveTransaction
or pretend a post-durable unexpected callback exception undid disk writes; classify
such a runtime publication failure truthfully and keep processing admission closed.
Expose the fixed failure to the composition rather than hiding it as a save success.

A failed transaction with nonempty `rollback_errors` is not known-restored state.
In managed mode, invoke the injected runtime-admission failure hook before any
public failure/event notification, so concurrent Batch/Watch cannot continue with
an uncertain credential/config combination. An ordinary failure with complete
compensation does not require inventing a new published catalog. Keep transaction
implementation and legacy behavior unchanged; test both outcomes with fake stores.

## Credential read policy

Add explicit injected `credential_read_allowed` (default legacy-true) and a managed
probe runner. The production policy reads current coordinator open/mode state.
Gate actual passive reads in preset/custom view-model generation, validation,
setActiveProvider, stage-empty-key lookup and `_candidate_credential` fallback.
When LOCAL/closing: passive credential state is unavailable, not false unconfigured;
metadata-only Save retains structural checks but skips cloud-key existence checks;
new/edited candidates without an explicitly usable verification remain unverified.
Don't recover a stored key merely to render a settings row or save local metadata.

Explicit user key set/delete operations may still use the existing compensated
transaction; fake tests cover them. Test admission in LOCAL/closing must refuse
BEFORE any credential fallback, adapter creation or runner submit. Don't let a
typed/staged key circumvent the processing mode gate.

## Managed connection runner and completion

Production tests no longer block Qt. Use a bounded owned executor with at most
one running request and one latest pending replacement. New tests cancel the
previous request context/Event; never grow an unbounded submit queue. Runner uses
an explicit fixed-probe service signature taking profile/key/processing_dispatch,
not inspection/TypeError fallback to an unguarded service.

On Qt freeze immutable profile, credential source/value (private repr-disabled
memory only), known-versus-candidate purpose, settings session epoch, draft/candidate
epoch, request ID and authentic CloudProbeContext. Capture purpose permission before
credential reads. Profile fingerprint and captured model must match the actual
adapter profile. No active cloud engine binding is changed for a candidate test.

Worker executes only the fixed service and returns a frozen completion via queued
Signal. Final Qt completion requires exact owned request, session/epoch, current
candidate/profile/key fingerprint and authority currentness. Remove terminal
ownership BEFORE public/reentrant signals. A stale success cannot verify a profile;
a stale error cannot remove a newly staged key or replace a newer visible state.
Exceptions become fixed ConnectionResult failure; no raw secret/path diagnostics.
Only accepted success stores the existing verification fingerprint/known-profile
draft update. Pending/running ownership remains truthful after cancellation.

Add `invalidateConnectionCandidate()` Slot: candidate epoch advances and the current
candidate request is cancelled. ProviderForm calls it on edit, open new/existing,
close and reopen lifecycle; preserve layout, visible labels and existing save/test
bindings. Do not rely only on a local QML flag that resets when reopened. Session
Cancel/open, staged key mutation, removal, Save and new test similarly supersede
affected requests. The known-provider and full-candidate APIs both follow fencing.

Expose finite `begin_close`/idle or drain state for C1D; do not delete a callback
QObject while the active runner can emit. A network request already committed may
finish; cancellation prevents retries and result publication, not an unsend claim.

## Required tests

- Saved LOCAL passive preset/custom views, metadata save, active selection,
  candidate add/edit and all tests: credential get/set/delete/migration/adapter
  counters zero except explicitly requested fake credential edits.
- Valid fake cloud probe with no active engine binding succeeds, uses authentic
  fixed purpose; runtime/local choice occurs before credential read or final opener
  and blocks it. Cloud mode change does not make old completion current again.
- Worker is actually off Qt; owner remains responsive to mode choice/Cancel;
  completion accepted only on Qt. One blocked running + latest pending replacement
  proves boundedness; intermediate superseded requests never execute.
- Old success after candidate edit/close/reopen same ID cannot mark/display success.
  Old failure after new key staging cannot remove it. Cancel/new session/save/removal
  and reversed completion order are covered with real queued signal delivery.
- ProviderForm lifecycle hook behavior is exercised, not just string-grepped.
- Successful settings commit invalidates/installs before public signal/event
  callbacks can start work; failed validation/transaction never publish inputs.
- Indeterminate rollback closes shared runtime admission before failure observers;
  fully compensated failure preserves the old catalog without reporting success.
- Bounded close retains runner/bridge while blocked and later reaches actual idle;
  no skip/xfail, real network or credentials in fixtures.

Use TDD and run named new/focused existing Settings, transaction and Provider QML
tests. Report raw RED/GREEN/results/files/concerns; root independently reviews and
checkpoints before C1D production composition. Interface feedback follows the
existing desktop design: loading/success/error must belong to the current candidate,
not a stale request. This small wiring hook does not authorize a visual redesign.

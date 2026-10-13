# Managed Watch execution resource integration

Approved autonomous integration scope; dependency54d42123f3ac4c8a5724d134bdbf68850b321062. Pending admission and exact guard receipts already pass scoped native gates. Production Watch is not activated by this task.

## Chosen ownership and alternatives

Keep pending/execution receipts on the same authentic ingress owner. Delivery consumes exact event identity, not caller-owned watch-id counter adjustments. A second resource queue duplicates authenticity/retirement; releasing at model return loses actual Qt acknowledgement/emission/publication tails. Chosen: genuine stable-size acquire before submission, primitive-only release at the already-reviewed actual retirement boundary.

An ingress resource observation is a real in-flight operation, outside ingress lock. An explicit owner flag prevents close/retirement from losing it while clock/contributors reenter. Receipt assignment precedes stale checks; cleanup never releases another event or drops ownership on false primitive release.

## Permission and visible denial

Optional exact resource_guard preserves the old standalone delivery path without a guard. Guarded construction requires a callable on_resource_blocked(event, fixed_reason); do not silently hold work without an observable reason. Pass the same guard to ingress; do not register its counts twice. This observer receives genuine stable work, not an outcome, and grants no observer resume.

Transient reasons global_pending_limit/watch_pending_limit/global_concurrency_limit/watch_concurrency_limit/manually_paused/failure_backoff/cooldown/resource_unavailable hold the same sealed queued owner without recapture or body submission. Coalesce unchanged reason per owner. Genuine stable size global_size_limit/watch_size_limit is terminal fixed failure, never content understanding. Lost/invalid ownership fails closed rather than retrying endlessly. Raw admitted failure preserves fixed pending-resource reasons/queue_full on ordinary exact failure delivery.

After guard observation, refresh current binding and final trusted start readiness, then check only sealed owner/authority/ingress facts. A True readiness answer is not a lease. If readiness became HELD, release only execution and retain pending/queued work. If stale/closed/cancelled, retire exact unsubmitted work after actual resource/public callback tail. Local or resource failures never fall back to cloud.

## Completion and boundaries

Execution receipt remains counted during worker, completed Future, before/after emission, queued acknowledgement and reentrant public consumer tails. Release execution only when acked, not in callback/admitting, bridge_done and genuine Future.done (or no submitted Future); then retire ingress pending. Submission failure has the same genuine queued acknowledgement ownership. Close must not remove an owner while resource acquisition or blocked observer is executing.

No failure-count reset/increment is added here: durable pipeline will own exactly-once operation accounting. No ResourcePaused recovery/observer resume, persistence, Apply/Undo, file lane/self-event/runtime/production/UI/provider/model/config/security change. Prior unexplained Qt GC crash remains open. Root exact frozen review, sequential native covers/full/screens/acceptance; no official Golden update, network/real credential, main write/merge/push.

## Acceptance

Real guard + synthetic catalog + actual Qt queue/Future/Threads: limit1 across delivery owners, at-cap owned execution, transient hold/recovery without recapture, actual stable oversize no inference, raw resource notice no I/O/worker, all real tails held, close/cancel/stale/reentrant clock/binding/readiness/blocked observer, submission failure, forged/duplicate events, exact cleanup. Bound waits and join every worker. Guard primitive-only unit proof is not actual Future proof.

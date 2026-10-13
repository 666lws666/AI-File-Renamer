# Managed Watch Pending Resource Admission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. One source writer; root alone Git/review/final Gates.

**Goal:** Connect exact pending resource receipts to authentic pre-capture ingress ownership and bounded watch-level denial.
**Architecture:** Extend the existing ingress owner only; reuse WatchResourceGuard and WatchAdmissionFailure. Pending admission is not execution permission.
**Tech Stack:** Python3.14.5, isolated Qt6.12.0 native guarded test runner, synthetic existing catalog/authority fixtures.

## Global Constraints

- Source dependency6b3dbbc86fd7a46ce59c6fcbe5de167cf2384f95; codex/local-privacy-mode in the linked ai-smart-naming checkout, not main. Actual plan checkpoint supplied at dispatch.
- Exact design docs/superpowers/specs/2026-10-11-managed-watch-resource-admission-design.md binds this task.
- ONLY modify src/controllers/managed_watch_ingress.py; ONLY create tests/unit/test_managed_watch_resource_admission.py. Existing tests and guard are covering READ-ONLY.
- No delivery/controller/runtime/QML/schema/config/default/Provider/model/file-lane/log/Golden/main mutation or execution; no Git/network/key/CM/firewall by implementer.
- Optional resource_guard=None retains existing ingress behavior; when supplied it must be exact WatchResourceGuard, not bool/custom shim. No producer count double-registration.
- reserve_pending outside ingress lock; canonical release_pending is primitive-only and may be used in locked pruning. Never drop an owner/token when release returnsFalse.
- Actual capture/post/consumer tails, exact event identity/authority/cancellation and bounded input behavior remain mandatory.
- At most one resource notice per watch-id/incarnation; separate finite MAX_RESOURCE_NOTICES=1000; normal MAX_OWNED=1000 unchanged. No paths/work/fingerprint added to a denial.
- No execution permit, production activation or whole-product/native-stability claim from this admission task. Prior Qt crash remains open.

## Task1: Exact pending receipt transfer and resource notice ownership

Files above form one reviewed task. Consumes guard reserve_pending(watch_id,size_bytes)->(ResourceDecision,token|None) and release_pending(token)->bool. Produces optional ingress constructor keyword resource_guard and bounded authentic resource failure on the existing capture/post_failure protocol.

### Step1 — genuine tests first

- [x] Write named tests before source edits. Reuse the real synthetic lane fixture from tests.unit.test_managed_watch_admission, not a fake guard. Example complete witnesses:

~~~python
from threading import Event, Thread
from src.controllers.managed_watch_ingress import ManagedWatchIngress
from src.core.watch_resource_guard import WatchResourceGuard, WatchLimits
from src.core.watch_work import WatchAdmissionFailure
from tests.unit.test_managed_watch_admission import lane, capture

def make_owned(lane, guard, post=lambda event: None):
    service, authority, source, watch = lane
    return ManagedWatchIngress(service, authority, capture_guard=source.guard,
        post_event=post, resource_guard=guard)

def test_reservation_precedes_actual_catalog_capture(lane, monkeypatch):
    guard = WatchResourceGuard(global_limits=WatchLimits(max_pending=1), cooldown_seconds=0)
    ingress = make_owned(lane, guard)
    original = lane[0].capture_work
    calls = []
    def checked(*args, **kwargs):
        assert guard.pending_count("watch") == 1
        assert guard.active_analyses("watch") == 0
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(lane[0], "capture_work", checked)
    first = capture(ingress, lane)
    try:
        denied = capture(ingress, lane, "overflow")
        assert type(denied) is WatchAdmissionFailure
        assert denied.reason == "global_pending_limit"
        assert not hasattr(denied, "work")
        assert calls == [1]
        assert guard.pending_count("watch") == 1
        assert capture(ingress, lane, "coalesced") is None
        assert ingress.retire(first)
        replacement = capture(ingress, lane, "replacement")
        assert replacement is not None and not isinstance(replacement, WatchAdmissionFailure)
        assert calls == [1, 1]
    finally:
        ingress.begin_close()
        assert ingress.workers_idle
        assert guard.global_pending_count() == 0

def test_clock_callback_can_query_ingress_from_actual_thread(lane):
    workers, errors = [], []
    armed = [False]
    ingress = None
    def clock():
        if armed[0]:
            done = Event()
            def query():
                try:
                    assert ingress.owned_count == 1
                except BaseException as error:
                    errors.append(error)
                finally:
                    done.set()
            worker = Thread(target=query)
            workers.append(worker)
            worker.start()
            assert done.wait(0.5), "ingress lock held during guard callback"
        return 0
    guard = WatchResourceGuard(clock=clock)
    ingress = make_owned(lane, guard)
    armed[0] = True
    try:
        event = capture(ingress, lane)
        assert event is not None and not errors
    finally:
        armed[0] = False
        ingress.begin_close()
        for worker in workers:
            worker.join(3)
        assert not any(worker.is_alive() for worker in workers)
        assert ingress.workers_idle and guard.global_pending_count() == 0
~~~

Add actual finite-thread capture/clock/post-tail close witnesses; limit1 two admitting threads; notice cap1 with two distinct synthetic watch configs; stale/forged/repeated retirement; unavailable-callback fixed denial; internal MAX_OWNED overflow with separate notice; no stat/content/key/adapter call; success after pending notice; false primitive release retains owner until genuine execution receipt is released. Guard receipt-only unit tests must not be called worker/Future proof.

### Step2 — native RED

- [x] Run the new file before source edits. Missing constructor keyword is feature-absence RED, not a claimed concurrency regression. Use cleanup-safe finite threaded callbacks, always joined after failure.

~~~powershell
& '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\venv\Scripts\python.exe' -B '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\run_guarded_pytest.py' tests/unit/test_managed_watch_resource_admission.py; exit $LASTEXITCODE
~~~

### Step3 — implement owner metadata and bounded admission

- [x] Add imports WatchResourceGuard plus the five fixed admission reason constants: R_GLOBAL_PENDING,R_WATCH_PENDING,R_GLOBAL_SIZE,R_WATCH_SIZE,R_RESOURCE_UNAVAILABLE. Add these exact private owner fields:

~~~python
    pending_token: object = None
    resource_notice: bool = False
~~~

Add MAX_RESOURCE_NOTICES=1000. Constructor exact keyword resource_guard=None; reject a non-None non-exact guard before creating any owner. Complete constructor:

~~~python
    def __init__(self, service, authority, *, capture_guard, post_event,
                 resource_guard=None):
        if resource_guard is not None and type(resource_guard) is not WatchResourceGuard:
            raise ValueError("invalid_watch_resource_guard")
        self._service = service
        self._authority = authority
        self._capture_guard = capture_guard
        self._post_event = post_event
        self._resource_guard = resource_guard
        self._resource_notices = {}
        self._open = True
        self._owned = {}
        self._issued = {}
        self._lock = Lock()
~~~

Complete helper starting implementation (genuine negatives may require strengthening):

~~~python
    def _normal_count_locked(self):
        return sum(not owner.resource_notice for owner in self._owned.values())

    def _mark_resource_notice_locked(self, key, owner):
        notice_key = (owner.watch_id, owner.incarnation)
        if (notice_key in self._resource_notices
                or len(self._resource_notices) >= self.MAX_RESOURCE_NOTICES):
            owner.retired = True
            owner.cancel.set()
            return False
        owner.resource_notice = True
        self._resource_notices[notice_key] = key
        return True

    def _prune_locked(self, key, owner):
        if not (owner.retired and not owner.capturing and not owner.posting):
            return
        if owner.pending_token is not None:
            if not self._resource_guard.release_pending(owner.pending_token):
                return
            owner.pending_token = None
        self._owned.pop(key, None)
        notice_key = (owner.watch_id, owner.incarnation)
        if self._resource_notices.get(notice_key) is key:
            self._resource_notices.pop(notice_key, None)
        if owner.event is not None:
            self._issued.pop(id(owner.event), None)
~~~

The guard's canonical primitive release has no clock/contributor/custom token callbacks. No I/O/user callback is permitted in these helpers. Count/idle may retry primitive pruning of already retired owners; still-live capture/post owners remain counted. Preserve _find_locked rejection of retired events, exact issued identity and all currentness/transfer methods.

Complete count query with bounded retirement retry; workers_idle remains owned_count==0:

~~~python
    @property
    def owned_count(self):
        with self._lock:
            for key, owner in tuple(self._owned.items()):
                self._prune_locked(key, owner)
            return len(self._owned)
~~~

Replace capture with this complete starting body:

~~~python
    def capture(self, config, incarnation, source_path, event_id):
        if not valid_admission_fields(config, incarnation, source_path, event_id):
            return None
        key, cancel = object(), Event()
        owner = _Owned(cancel, config.id, incarnation)
        notice_reason = ""
        with self._lock:
            if not self._open:
                return None
            full = self._normal_count_locked() >= self.MAX_OWNED
            if full and self._resource_guard is None:
                return None
            self._owned[key] = owner
            if full:
                if not self._mark_resource_notice_locked(key, owner):
                    owner.capturing = False
                    self._prune_locked(key, owner)
                    return None
                notice_reason = "queue_full"
        event = None
        try:
            if self._resource_guard is not None and not notice_reason:
                decision, receipt = self._resource_guard.reserve_pending(config.id, 0)
                with self._lock:
                    owner.pending_token = receipt
                    if not self._open or owner.retired:
                        owner.retired = True
                        cancel.set()
                        return None
                    if not decision.allowed:
                        if not self._mark_resource_notice_locked(key, owner):
                            return None
                        allowed_reasons = {
                            R_GLOBAL_PENDING, R_WATCH_PENDING, R_GLOBAL_SIZE,
                            R_WATCH_SIZE, R_RESOURCE_UNAVAILABLE,
                        }
                        notice_reason = decision.reason if decision.reason in allowed_reasons else R_RESOURCE_UNAVAILABLE
            with self._capture_guard():
                snapshot = self._authority.snapshot()
                if notice_reason:
                    event = WatchAdmissionFailure(snapshot, config.id, config,
                        incarnation, event_id, notice_reason)
                else:
                    try:
                        work = self._service.capture_work(source_path, event_id,
                            task_attempt_id=uuid4().hex, task_cancel_event=cancel,
                            template_id=config.template_id, output_language="",
                            naming_mode="template", defer_execution_deadline=True)
                    except (LocalProcessingUnavailable, CloudDispatchBlocked,
                            ProcessingSuperseded, BatchAnalysisError,
                            SmartNamingError, ValueError, TypeError) as error:
                        reason = "invalid_settings"
                        if isinstance(error, LocalProcessingUnavailable):
                            reason = "local_unavailable"
                        elif isinstance(error, CloudDispatchBlocked):
                            reason = "cloud_unavailable"
                        elif isinstance(error, ProcessingSuperseded):
                            reason = "superseded"
                        event = WatchAdmissionFailure(snapshot, config.id,
                            config, incarnation, event_id, reason)
                    else:
                        event = WatchAdmission(work, config.id, config,
                            incarnation, event_id, cancel)
            with self._lock:
                if not self._open or owner.retired:
                    owner.retired = True
                    cancel.set()
                    return None
                owner.event = event
                self._issued[id(event)] = (key, owner)
                return event
        finally:
            with self._lock:
                owner.capturing = False
                if event is None:
                    owner.retired = True
                    cancel.set()
                self._prune_locked(key, owner)
~~~

Admission size0 is unknown metadata only. Denial does not call capture_work, stat, extraction, credentials or inference. Normal/admitted-setting failures retain their pending receipt until actual retirement. Resource notices never have one. Keep coalescing separate from normal admission so a pending notice cannot prevent a newly permitted file from being captured.

### Step4 — GREEN and cover

- [x] Run focused new tests, then exact unchanged covers:

~~~powershell
& '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\venv\Scripts\python.exe' -B '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\run_guarded_pytest.py' tests/unit/test_managed_watch_resource_admission.py tests/unit/test_managed_watch_admission.py tests/unit/test_watch_resource_ownership.py tests/unit/test_watch_resource_guard.py tests/integration/test_managed_watch_lifecycle.py; exit $LASTEXITCODE
~~~

Every genuine thread joined, actual native0/forbidden0/MainThread-only. No old assertion/fixture change, no Qt/full/screens/model/API by implementer. Native helper default setup-refresh errors are environment launch failures, not test results; use the exact scoped elevated runner when required.

### Step5 — freeze, review, checkpoint

- [x] Write private .superpowers/sdd/managed-watch-resource-admission-report.md with every original RED/GREEN/native output, scoped hashes and limits; freeze two files. Root independent scoped review, then frozen sequential full/screens/acceptance and exact local checkpoint. Root alone docs/ledger/staging/commit; no push/merge/Golden or main changes.

## Explicit next task

This pending-only component is not yet injected into ManagedWatchAnalysisDelivery. Its execution/resource-notice mapping must be integrated and reviewed before production use. The next delivery task must acquire an exact execution receipt using genuine stable size, recheck live readiness after fallible resource observations, retain Future/emission/public-callback tails, release exact execution then pending, and hold resource-denied genuine work without recapture. A trusted True is not a permit. Durable Review/AutoApply/file lane/self-events/recovery/runtime/resources/UI/model/manual/package remain unfinished; whole-project PASS is forbidden here.

## Actual scoped completion evidence

Root independent task review: Spec compliant / Quality Approved, no Critical/Important issue; only unchanged warning backlog. Frozen native cover253passed; sequential full4865passed/3existing skips; screenshots66passed/1designed skip UPDATE absent; guarded acceptance186/186. Each native0/forbidden0/MainThread-only. Two source/test hashes matched before staging; main/shortcut/official Golden unchanged. No execution/production/runtime-stability/model/package claim. Full original QA: tests/screenshots/qa-current/local-privacy/2026-10-11-managed-watch-resource-admission-root-verification.md plus returned-output JSON. Local checkpoint only, no push.

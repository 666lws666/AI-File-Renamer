# Managed Watch Qt Analysis Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this single bounded task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute authentic, stable Watch admissions through the existing managed analysis service off the Qt thread, and deliver exact current outcomes on the Qt owner with truthful finite shutdown.

**Architecture:** This is a standalone adapter between the reviewed ManagedWatchIngress and the same BatchAnalysisService used by Batch. It owns the ingress, a bounded two-worker executor, and private queued Qt completions. Production Watch activation, review persistence/file actions and resource-guard scheduling are separate integration tasks; this adapter does not create another AI engine or call the legacy Watch analyzer.

**Tech Stack:** Windows Python 3.14.5, pinned PySide6 6.12.0, Qt queued signals/timer, standard Future/Event/Lock, existing frozen domain values.

## Global Constraints

- Work only in the existing isolated codex/local-privacy-mode checkout. Root alone owns Git. No main checkout edits, push, merge, release, history rewrite or formal Golden update.
- No real cloud API, key, Credential Manager, private input, firewall/ACL changes or global collection. Use the root-provided guarded candidate interpreter for native tests.
- Only create src/controllers/managed_watch_analysis.py and tests/integration/test_managed_watch_analysis.py. Do not alter ingress, authority, Batch, WatchController, resource guard, UI, bootstrap or canonical media/model services in this task.
- Preserve exact admitted work/context/event identity. Never recapture current catalog/settings in a worker, call legacy analyze, manufacture confidence, execute Apply/Undo or turn a persisted record into an authority permit.
- Bound all ingress/captured/running/queued-publication owners to at most 1000. At most two runner submissions may be live. Count a Future until its actual emission tail and Qt consumption/public callback have finished, not merely Future.done.
- No source reads/stat on Qt. Worker checks the admitted source fingerprint immediately before and after run_prepared; non-regular source/missing/changed source produces a bounded reason, never exception text or a path in diagnostics.
- A synchronous on_result callback is part of the Qt ownership boundary. This component does not account for external queued/asynchronous work started by that callback; the eventual review/file-action facade must explicitly own it.
- Bindings/current mode must be rechecked on Qt after fallible/reentrant callbacks. Stale/cancelled/closed work must not publish a suggestion.
- Ownership and cancel state stay alive through actual worker exit and queued acknowledgement. Ingress.retire must not prematurely set the work cancel event while a runner still owns it.
- workers_idle must include queued ingress deliveries, submissions, emission tails and active public callbacks. Closing is nonblocking; draining has a finite supplied monotonic deadline, normal GC and real Qt event delivery.
- This task is not production Watch/model/UI/privacy or whole-product PASS.

## Approved design and bounded choices

The user already approved shared managed authority and autonomous implementation. Reusing the synchronous legacy ReviewFirst/AutoApply analyzer would invent confidence and execute on observer callbacks; a separate inference engine would split privacy authority. The selected adapter keeps one managed service and one private Qt delivery owner.

A Qt-owned timer polls completed emission tails; workers never emit after marking their tail finished. Constructor creates connections before admission is possible. A later production facade supplies is_binding_current(event) using the exact current watch incarnation/binding revision and supplies on_result(result) for durable review/AutoApply decisions. Resource-guard tickets and accepted file-operation ownership are not approximated in this adapter.

### Task 1: Bounded authentic Watch analysis owner

**Files:**
- Create: src/controllers/managed_watch_analysis.py
- Create: tests/integration/test_managed_watch_analysis.py

**Interfaces:**

Consumes BatchAnalysisService.run_prepared(work, cancellation_token=...), ProcessingAuthority.is_current(context), ManagedWatchIngress.capture/post_stable/post_failure/is_current/retire/begin_close/owned_count/workers_idle, StableWatchEvent, WatchAdmissionFailure, metadata_from_outcome and existing SourceFingerprint(size_bytes, mtime_ns).

Produces ManagedWatchAnalysisDelivery(service, authority, *, capture_guard, is_binding_current, on_result, max_workers=2, pending_limit=1000); its ingress property for observer construction; workers_idle, owned_count, publication_failed, begin_close(), drain(deadline), and poll(). on_result receives frozen ManagedWatchAnalysisResult(event, outcome, metadata, failure) only on Qt. outcome/metadata are None on failure. failure is a bounded reason.

- [x] **Step 1: Write genuine failing integration tests**

Use a real ProcessingAuthority/AnalysisCatalogSource/managed BatchAnalysisService construction as in tests/unit/test_managed_watch_admission.py, with synthetic AppConfig/Template and forbidden credential/adapter/extraction fakes. Replace only the fixture service's run_prepared with a deterministic local fake to record thread, block/release, return AnalysisOutcome or raise a synthetic secret-bearing error. Use real QCoreApplication and actual QueuedConnection delivery; no fake signal/counter/GC suppression.

The first new test imports the new module and captures a real synthetic regular file through owner.ingress, computes its fingerprint off Qt in the test, posts it, pumps Qt until the callback, and asserts:
```python
assert seen[0].event.admission is admission
assert seen[0].outcome.context is admission.work.context
assert seen[0].metadata.confidence is None
assert seen[0].failure == ""
assert runner_threads and runner_threads[0] != threading.get_ident()
assert callback_threads == [threading.get_ident()]
assert owner.drain(time.monotonic() + 2.0)
```

Additional required test contracts (actual asserts and synchronization, not registration-only cases):
1. cloned/forged stable delivery does not run or publish; duplicate real delivery runs once.
2. unavailable admitted failure uses exact snapshot and bounded reason, no run_prepared or I/O.
3. stale generation before Qt intake and while blocked in runner suppresses publication and eventually retires actual ownership.
4. binding removed/replaced before intake and while runner blocks suppresses result; reentrant binding predicate changing authority cannot return a current result.
5. source replacement between stable capture/start and source mutation during runner returns source_changed, no suggestion; reject symlink/nonregular/missing source safely.
6. protected extension/name and incorrect outcome.context/type/metadata are rejected as invalid_outcome.
7. synthetic exception text/path never appears in the returned failure or emitted diagnostics.
8. pending_limit exact capacity is enforced before capture; queued Qt ingress tails count; max_workers bound is retained while emit is blocked and after Future.done.
9. submission failure returns one bounded current failure, owns queued acknowledgement, drains.
10. start close while worker blocked: no suggestion, workers_idle stays False until actual release/emission/Qt consumption; finite deadline returns False, later actual drain True.
11. close with queued ingress/failure and unstarted queued work: no inference/fallback, all exact owners retire after real Qt delivery.
12. synchronous callback pumps nested Qt events/queries workers_idle: still owned inside callback; callback exception latches publication_failed, closes admission and does not leak source exception text.
13. two simultaneous real workers plus queued work honor max_workers; complete callback/Qt dispatch is required before capacity is reused.
14. wrong Python/Qt thread cannot call owner lifecycle/introspection/slot methods; original owner remains usable afterward.
15. same tested file is a synthetic fixture, no network or credential access, and finally closes/drains every constructed owner with bounded synchronization.

Every test that constructs an owner must close/drain in finally, including tests expecting failure. Do not abandon a worker or suppress assertion exceptions. Use Events with explicit finite waits and an eventual Qt pump helper:
```python
def pump_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    assert predicate()
```

- [x] **Step 2: Run RED with the guarded native candidate interpreter**

Root supplies this exact Windows command (UPDATE absent, isolation/socket/native CM guard installed by runner):
```powershell
& 'D:\文件AI-AGENT\.worktrees\ai-smart-naming\tests\screenshots\qa-current\local-privacy\qt612-candidate\venv\Scripts\python.exe' -B 'D:\文件AI-AGENT\.worktrees\ai-smart-naming\tests\screenshots\qa-current\local-privacy\qt612-candidate\run_guarded_pytest.py' tests/integration/test_managed_watch_analysis.py
```
Expected: genuine missing-module/API failure, actual nonzero exit. Executor launch failure is BLOCKED, not a RED product result.

- [x] **Step 3: Implement the adapter**

Use the following complete starting implementation. Strengthen it when a named regression proves an issue; stay in the exact two-path scope and report any required interface/scope change before editing a third path.

```python
"""Bounded Watch analysis owner; no production activation or file operations."""
from __future__ import annotations
from concurrent.futures import CancelledError, ThreadPoolExecutor
from dataclasses import dataclass, field
import math
import os
import stat
import threading
import time
from PySide6.QtCore import QObject, Signal, Slot, Qt, QTimer, QCoreApplication
from src.controllers.managed_watch_ingress import ManagedWatchIngress
from src.core.batch_analysis import BatchAnalysisService, BatchAnalysisError
from src.core.processing_analysis import AnalysisOutcome, CloudAnalysisCoverage
from src.core.processing_authority import (
    ProcessingMode, ProcessingSuperseded, LocalProcessingUnavailable, CloudDispatchBlocked,
)
from src.core.watch_work import StableWatchEvent, WatchAdmissionFailure
from src.core.managed_watch_metadata import metadata_from_outcome
from src.core.rename_plan import SourceFingerprint
from src.core.filename_validator import validate_filename
from src.services.local_ai.preparation_protocol import PreparationCoverage


@dataclass(frozen=True)
class ManagedWatchAnalysisResult:
    event: object = field(repr=False)
    outcome: AnalysisOutcome | None = field(default=None, repr=False)
    metadata: object = None
    failure: str = ""


@dataclass(eq=False)
class _Owner:
    event: StableWatchEvent
    future: object = None
    bridge_done: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    issued: object = None
    acked: bool = False
    in_callback: bool = False


@dataclass(frozen=True)
class _Completion:
    owner: _Owner = field(repr=False)
    outcome: object = field(default=None, repr=False)
    failure: str = ""


class ManagedWatchAnalysisDelivery(QObject):
    _incoming = Signal(object)
    _completed = Signal(object)

    def __init__(self, service, authority, *, capture_guard, is_binding_current,
                 on_result, max_workers=2, pending_limit=1000):
        super().__init__()
        if (not isinstance(service, BatchAnalysisService) or not service._managed
                or service._authority is not authority
                or not callable(capture_guard) or not callable(is_binding_current)
                or not callable(on_result) or type(max_workers) is not int
                or not 1 <= max_workers <= 2 or type(pending_limit) is not int
                or not 1 <= pending_limit <= 1000):
            raise ValueError("invalid_managed_watch_owner")
        self._ident = threading.get_ident()
        self._service, self._authority = service, authority
        self._binding, self._consume = is_binding_current, on_result
        self._max_workers = max_workers
        self._closed = self._publication_failed = self._pumping = False
        self._callbacks = 0
        self._queued, self._owners = [], {}
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._incoming.connect(self._accept_event, Qt.QueuedConnection)
        self._completed.connect(self._accept_completion, Qt.QueuedConnection)
        self.ingress = ManagedWatchIngress(service, authority, capture_guard=capture_guard,
                                           post_event=self._incoming.emit)
        self.ingress.MAX_OWNED = pending_limit
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self.poll)
        self._timer.start()

    def _require_owner(self):
        if threading.get_ident() != self._ident or not self.thread().isCurrentThread():
            raise RuntimeError("watch_owner_thread_required")

    def _current(self, event):
        if self._closed or not self.ingress.is_current(event):
            return False
        try:
            bound = self._binding(event) is True
        except Exception:
            bound = False
        return bound and not self._closed and self.ingress.is_current(event)

    @Slot(object)
    def _accept_event(self, event):
        self._require_owner()
        if not self.ingress.is_current(event):
            self.ingress.retire(event)
            return
        if not self._current(event):
            self.ingress.retire(event)
            return
        if type(event) is WatchAdmissionFailure:
            safe = event.reason if event.reason in {
                "invalid_settings", "local_unavailable", "cloud_unavailable", "superseded"
            } else "analysis_failed"
            self._deliver(ManagedWatchAnalysisResult(event, failure=safe))
            self.ingress.retire(event)
            return
        if type(event) is not StableWatchEvent:
            self.ingress.retire(event)
            return
        if id(event) in self._owners:
            return
        owner = _Owner(event)
        self._owners[id(event)] = owner
        self._queued.append(owner)
        self.poll()

    @staticmethod
    def _fingerprint(path):
        value = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(value.st_mode):
            raise ValueError("source_changed")
        return SourceFingerprint(value.st_size, value.st_mtime_ns)

    @classmethod
    def _run(cls, service, owner):
        event, work = owner.event, owner.event.admission.work
        try:
            if cls._fingerprint(work.source_path) != event.fingerprint:
                return _Completion(owner, failure="source_changed")
            outcome = service.run_prepared(work)
            if cls._fingerprint(work.source_path) != event.fingerprint:
                return _Completion(owner, failure="source_changed")
            return _Completion(owner, outcome=outcome)
        except (ProcessingSuperseded, CancelledError):
            return _Completion(owner, failure="superseded")
        except LocalProcessingUnavailable:
            return _Completion(owner, failure="local_unavailable")
        except CloudDispatchBlocked:
            return _Completion(owner, failure="cloud_unavailable")
        except (OSError, ValueError):
            return _Completion(owner, failure="source_changed")
        except Exception as error:
            reason = "analysis_failed"
            if isinstance(error, BatchAnalysisError):
                if str(error) == "Local analysis timed out": reason = "timeout"
                elif str(error) == "Local analysis queue is full": reason = "queue_full"
            return _Completion(owner, failure=reason)

    def _emit(self, owner, future):
        try:
            try:
                completion = future.result()
            except BaseException:
                completion = _Completion(owner, failure="analysis_failed")
            with owner.lock:
                owner.issued = completion
            self._completed.emit(completion)
        finally:
            # No worker Qt call after this final synchronized tail fact.
            owner.bridge_done.set()

    def _prune(self):
        for key, owner in tuple(self._owners.items()):
            if (owner.acked and not owner.in_callback and owner.bridge_done.is_set()
                    and (owner.future is None or owner.future.done())):
                self.ingress.retire(owner.event)
                self._owners.pop(key, None)

    @Slot()
    def poll(self):
        self._require_owner()
        if self._pumping:
            return
        self._pumping = True
        try:
            self._prune()
            if self._closed:
                if not self._owners and self.ingress.workers_idle and not self._callbacks:
                    self._timer.stop()
                return
            running = sum(owner.future is not None or owner.issued is not None
                          for owner in self._owners.values())
            while self._queued and running < self._max_workers:
                owner = self._queued.pop(0)
                if not self._current(owner.event):
                    self.ingress.retire(owner.event)
                    self._owners.pop(id(owner.event), None)
                    continue
                try:
                    owner.future = self._pool.submit(self._run, self._service, owner)
                except Exception:
                    completion = _Completion(owner, failure="analysis_failed")
                    with owner.lock: owner.issued = completion
                    owner.bridge_done.set()
                    self._completed.emit(completion)
                else:
                    owner.future.add_done_callback(lambda done, owned=owner: self._emit(owned, done))
                running += 1
        finally:
            self._pumping = False

    def _deliver(self, result):
        self._callbacks += 1
        try:
            if self._current(result.event):
                self._consume(result)
        except Exception:
            self._publication_failed = True
            self.begin_close()
        finally:
            self._callbacks -= 1

    @Slot(object)
    def _accept_completion(self, completion):
        self._require_owner()
        if type(completion) is not _Completion:
            return
        owner = completion.owner
        if self._owners.get(id(owner.event)) is not owner or owner.acked or owner.in_callback:
            return
        with owner.lock:
            if owner.issued is not completion:
                return
        owner.in_callback = True
        try:
            if not self._current(owner.event):
                return
            work, outcome = owner.event.admission.work, completion.outcome
            metadata, failure = None, completion.failure
            if type(failure) is not str or failure not in {
                "", "source_changed", "superseded", "local_unavailable",
                "cloud_unavailable", "analysis_failed", "timeout", "queue_full"
            } or (outcome is None and not failure) or (outcome is not None and failure):
                outcome, failure = None, "invalid_outcome"
            if outcome is not None:
                try:
                    expected = PreparationCoverage if work.context.mode is ProcessingMode.LOCAL else CloudAnalysisCoverage
                    if (type(outcome) is not AnalysisOutcome or outcome.context is not work.context
                            or type(outcome.coverage) is not expected
                            or type(outcome.suggested_name) is not str):
                        raise ValueError("invalid_outcome")
                    parts = outcome.suggested_name.split("/")
                    if (not parts or any(not validate_filename(p).is_valid for p in parts[:-1])
                            or not validate_filename(parts[-1], owner.event.protected_extension).is_valid):
                        raise ValueError("invalid_outcome")
                    metadata = metadata_from_outcome(outcome, work.settings.quality_mode)
                except Exception:
                    outcome, metadata, failure = None, None, "invalid_outcome"
            self._deliver(ManagedWatchAnalysisResult(owner.event, outcome, metadata, failure))
        finally:
            owner.acked = True
            owner.in_callback = False
            self.poll()

    @property
    def owned_count(self):
        self._require_owner()
        self._prune()
        return self.ingress.owned_count

    @property
    def workers_idle(self):
        self._require_owner()
        self._prune()
        return not self._owners and self.ingress.workers_idle and not self._callbacks

    @property
    def publication_failed(self):
        self._require_owner()
        return self._publication_failed

    def begin_close(self):
        self._require_owner()
        if self._closed:
            return
        self._closed = True
        self.ingress.begin_close()
        for owner in self._queued:
            self.ingress.retire(owner.event)
            self._owners.pop(id(owner.event), None)
        self._queued.clear()
        self._pool.shutdown(wait=False, cancel_futures=True)
        self.poll()

    def drain(self, deadline):
        self._require_owner()
        if (type(deadline) not in (int, float) or not math.isfinite(deadline)
                or deadline - time.monotonic() > 30):
            raise ValueError("invalid_watch_drain_deadline")
        while time.monotonic() < deadline:
            self.poll()
            if self.workers_idle:
                return True
            QCoreApplication.processEvents()
            time.sleep(0.005)
        return self.workers_idle
```

- [x] **Step 4: Run GREEN and covering regressions**

Run the guarded native command above for these exact existing paths as well as the new integration file:
```text
tests/integration/test_managed_watch_analysis.py
tests/unit/test_managed_watch_admission.py
tests/integration/test_managed_watch_lifecycle.py
tests/unit/test_managed_watch_metadata.py
tests/unit/test_managed_watch_persistence.py
tests/unit/test_processing_analysis.py
```
Expected: all pass, real native 0, forbidden accesses 0, no owned worker/timer remains at exit. Record raw summary and failures; do not invent counts or substitute collection/static tests.

- [x] **Step 5: Root independent scoped review, full verification and exact checkpoint**

Writer reports full scoped diff/tests in .superpowers/sdd/managed-watch-analysis-report.md and freezes the two files. Root generates an exact diff package, dispatches an independent task-scoped spec/quality review, reruns native scoped/all regressions, and commits only the reviewed two files plus this plan if applicable. No production activation or branch finish/merge.

## Cross-task integration boundary

Production binding callback, resource-guard pre-existing-pending semantics, persisted review publication, AutoApply/file-operation lane, exact self-event suppression, WatchPage callbacks, bootstrap composition and final native/model privacy acceptance remain explicit next tasks. The adapter result and descriptive metadata are not disk authority. Future Apply must preflight the stable fingerprint again; the two-field SourceFingerprint is the existing reviewed metadata contract, not a cryptographic snapshot or proof against a deliberate same-size/mtime rewrite.

## Executed bounded verification — 2026-10-11

The code block above is the historical starting proposal, not a substitute for the reviewed final source. Genuine negative tests and review corrected duplicate intake, failure-callback ownership, and the initial binding predicate's reentrant owner-install boundary. The original RED results remain recorded; none was relabeled passing. Final spec and quality review approved the corrected two-file task.

Independent root verification used Python 3.14.5 and isolated official Qt 6.12.0, normal garbage collection, synthetic inputs, isolated user-data directories, prohibited socket/native credential calls, and actual native process exit. Results on the frozen correction:

- Covering six targets: 257 passed, 3 existing Pydantic warnings (2.86s).
- Complete non-screenshot suite: 4576 passed, 3 existing skips, 4 existing warnings (100.10s).
- Existing screenshot suite, update mode absent: 66 passed, 1 designed update-mode skip, 86 existing Pillow warnings (50.68s). No Golden changed.
- Acceptance: 186/186.
- Existing isolated Qt candidate artifact: 27 packaging/smoke checks passed, 3 existing Pydantic warnings (6.71s). This artifact was not rebuilt from this task and is not a final local-privacy release.

Every run returned pytest/acceptance 0 and actual native exit 0, with zero forbidden-access attempts and only MainThread at exit. The shared project venv and main checkout were not modified. This establishes standalone Watch analysis delivery only; production Watch/resource scheduling, durable result publication, Apply/Undo composition, resource UI, real model semantics and the final Windows distribution remain separate unfinished Gates.

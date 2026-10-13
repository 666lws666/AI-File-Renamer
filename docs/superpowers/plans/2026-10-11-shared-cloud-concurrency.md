# Shared Managed Cloud Analysis Concurrency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Root owns Git and final native verification; one fresh source writer, then independent task review. Steps use checkbox syntax.

**Goal:** Bound simultaneous managed cloud analysis across Batch and Watch sharing the same BatchAnalysisService by the captured user setting, while retaining cancellation, finite waiting and actual in-flight ownership.

**Architecture:** Add one small synchronous lane per shared service, not another executor or a process-global singleton. The lane owns opaque exact-identity tokens until the real service call returns through its finally block. It uses immutable captured max_concurrent_requests and the minimum limit among existing token holders and a candidate, so raising a new limit cannot weaken an older live limit and lowering a new limit cannot interrupt already-sent work. This bounds real managed cloud analysis, not Qt completion/publication tails or Watch pending/recovery policy; those remain independently owned.

**Tech Stack:** Python3.14.5, standard-library Condition, existing managed authority/catalog/service, real Qt Batch and Watch adapters, isolated official PySide6 6.12.0.

## Global Constraints

- Source predecessor dae5a548c883fe90ab9a8bdfe89f9a06e0123e26, codex/local-privacy-mode linked checkout only; root provides actual plan checkpoint before dispatch.
- One writer owns exactly the seven source/test paths in Task1. No Git, main checkout, model launch/download, network, real API/Key/Credential Manager, firewall/ACL/global collection, Golden/UI/config-default/Provider adapter/file-lane/store/ResourceGuard/runtime modification.
- Captured settings stay immutable. Add a defaulted field to the end of AnalysisSettings for direct-constructor compatibility; do not serialize new work or silently alter user config/templates/watch rules.
- Only managed CLOUD run_prepared uses this lane. Preserve managed LOCAL's reviewed lane, deadline start, waiter cap, no-cloud fallback and all admission/publication authenticity. Deliberate legacy analysis is not production fallback and is outside this lane.
- Every acquisition/release/cancellation path must reflect actual work, not fabricated counters, cleared ownership or early retirement of a sent request. A mode switch cannot retract a sent request.
- No cancellation callback, user callback, authority query, source I/O or clock callback may run while the lane Condition lock is held.
- Max concurrency uses exact int1..20, matching current AppConfig. Production waiting cap64, bounded and separate from pipeline pending capacity. Queue wait ceiling600 seconds; this is a safety ceiling, not a speed promise or request-network timeout.
- Raising the captured limit does not outrun lower-limit work still alive. Lowering does not kill in-flight work; it prevents additional starts until below the candidate/living minimum.
- Existing Future/emission/publication ownership remains unchanged. This lane releases after the actual service body, not after public Qt callbacks; it is NOT the future Watch ResourceGuard execution permit.
- Synthetic adapters may model attempted dispatch and blocked sends, but no actual network/model-quality/production Watch approval may be claimed.

## Task1: Shared cloud lane, captured setting and fixed failure mapping

### Files and responsibilities

Create src/core/analysis_concurrency.py: pure bounded Condition lane and fixed exceptions.
Modify src/core/processing_analysis.py: append/validate captured concurrency field only.
Modify src/core/batch_analysis.py: instantiate shared lane and own it through CLOUD service execution.
Modify src/controllers/batch_workspace_controller.py: map the two fixed cloud queue failures to existing translated timeout/queueFull IDs.
Modify src/controllers/managed_watch_analysis.py: same fixed cloud queue failure mapping.
Create tests/unit/test_analysis_concurrency.py: real token/Condition/cancellation/settings negatives.
Create tests/integration/test_shared_cloud_concurrency.py: real shared service, Batch/Watch/Futures/Qt and synthetic adapter calls.

No other source/test path, not even existing fixture files, is owned by the writer.

### Interfaces

Consumes AnalysisSettings.capture(config), AppConfig.max_concurrent_requests, authenticated AnalysisWork, ProcessingAuthority/ProcessingSuperseded, actual BatchAnalysisService.run_prepared, existing Qt Batch and managed Watch delivery.
Produces CloudAnalysisLane(max_waiters=64, clock=None), acquire(limit, *, cancelled, deadline) -> opaque object; release(token) -> bool; active_count/waiting_count synchronized diagnostics; CloudLaneQueueFull / CloudLaneQueueTimeout fixed exceptions.
The lane is per shared service. Multiple unrelated service instances are not a claimed process-wide quota. QML runtime already constructs a shared service; this task does not activate Watch.

- [x] **Step1: Write named genuine failing tests before implementation**

Start with actual unit test code below, then extend with the exact matrix following it:

~~~python
import time
from threading import Event, Thread
import pytest
from src.core.analysis_concurrency import (
    CloudAnalysisLane, CloudLaneQueueFull, CloudLaneQueueTimeout,
)
from src.core.processing_authority import ProcessingSuperseded
from src.core.processing_analysis import AnalysisSettings
from src.models.app_config import AppConfig

def test_exact_token_release_cannot_release_another_job():
    lane = CloudAnalysisLane()
    token = lane.acquire(1, cancelled=lambda: False, deadline=time.monotonic()+2)
    assert lane.active_count == 1
    assert lane.release(object()) is False
    assert lane.active_count == 1
    assert lane.release(token) is True
    assert lane.release(token) is False
    assert lane.active_count == 0

def test_captured_concurrency_remains_immutable():
    config = AppConfig(max_concurrent_requests=2)
    captured = AnalysisSettings.capture(config)
    config.max_concurrent_requests = 20
    assert captured.max_concurrent_requests == 2
    assert AnalysisSettings.capture(config).max_concurrent_requests == 20

@pytest.mark.parametrize('bad', [True, False, 0, 21, 1.0, '2', None])
def test_invalid_limit_has_zero_ownership(bad):
    lane = CloudAnalysisLane()
    with pytest.raises(ValueError, match='invalid_cloud_lane_acquisition'):
        lane.acquire(bad, cancelled=lambda: False, deadline=time.monotonic()+2)
    assert lane.active_count == lane.waiting_count == 0
~~~

Named exact additional unit checks: second acquisition atlimit1 actually waits on another joined Thread; existing token remains active while waiting; cancellation and callback exception/non-exact-False terminate only the waiter with ProcessingSuperseded; deadline timeout retires waiter but not another token; cap1waiter rejects second waiter as CloudLaneQueueFull without decrementing the first; callbacks may query active_count or release another token without deadlock because callbacks are outside the lock; peak genuine holders<=limit; limit2to1 waits for both real older holders to leave; limit1to20 waits while older limit1holder remains; release from another real thread wakes waiters; every test finite-joins real threads/finally releases exact tokens. No sleeps as sole assertion or unbounded stress loops.

For integration, build a self-contained fixture with real shared catalog/authority/service and synthetic files, using the existing reviewed patterns in tests/integration/test_managed_batch_publication.py:104-178 only as an interface reference (do not modify/import its autouse test fixture). Required production service construction is:

~~~python
template = Template(id='one', name='Synthetic', pattern='{dcTitle}',
    fields=(TemplateField('dcTitle', 'Title'),))
profile = ProviderProfile(id='active', model='synthetic',
    base_url='https://example.invalid/v1',
    needs_connection_verification=False,
    capabilities=ProviderCapabilities(text=True, json_schema=True))
config = AppConfig(default_template_id='one',
    active_provider_id='active', provider_profiles=[profile.to_safe_dict()],
    max_concurrent_requests=1)
source = AnalysisCatalogSource(build_analysis_catalog(config, [template]))
authority = ProcessingAuthority(initial_mode=ProcessingMode.CLOUD)
authority.bind_cloud_engine(cloud_engine_fingerprint(profile))

def extract(path, max_chars):
    return path.read_text(encoding='utf-8'), {
        'sections_processed': 1, 'sections_total': 1,
    }

def adapter(profile, credential, *, processing_dispatch, retry_executor):
    def invoke(request, *, cancellation_token):
        receipt = authority.commit_cloud_attempt(
            processing_dispatch.context, 'synthetic-send')
        try:
            hooks.invoke(request, cancellation_token)
        finally:
            authority.finish_attempt(receipt)
        return RetryExecutionResult(True,
            ProviderResponse(fields={'dcTitle': 'Synthetic report'}),
            (), None, None)
    return SimpleNamespace(invoke=invoke)

service = BatchAnalysisService(
    profile_provider=lambda: source.get().active_profile,
    credential_provider=lambda profile: 'synthetic-only',
    config_provider=lambda: source.get().settings,
    template_provider=lambda ident: source.get().template(ident),
    capture_guard=source.guard, processing_authority=authority,
    local_inference_service=object(), local_preparation_service=object(),
    managed_adapter_factory=adapter, content_extractor=extract)
~~~

All named types above are existing exported types except hooks, a SimpleNamespace holding the test's bounded invoke callback. Import them explicitly in this new file. Never replace run_prepared or the lane with a mock for the shared-routing Gate.

Construct BatchWorkspaceController with a real temp workspace/history and max_workers>1; configure real template and install service before import. Construct ManagedWatchAnalysisDelivery with that exact same service/authority, source.guard and synthetic current binding, consumer before authentic ingress capture/post_stable. Use separate synthetic text bodies for Batch/Watch and actual stat SourceFingerprint. Both use ordinary actual worker/Qt delivery. Pending Watch admission may be synthetic; no observer/product Watch Gate is claimed.

Required named integration checks:
1. Batch+Watch real adapter calls share peak1 with configured1 even with distinct pools. Waiting work performs no extraction/credential/factory/send before acquisition. Release first actual adapter and verify both original work objects eventually publish once, actual lane counts0 and owners drained.
2. Configured2 permits exactly2 genuine blocked adapter bodies; a third waits. No assertion based only on the construction argument.
3. Queued Watch incarnation/task cancellation or Batch cancel prevents its extraction/send; no recapture. A mode switch to LOCAL cancels all waiting CLOUD jobs without new send; already-entered synthetic send remains recorded/in-flight until released, then rejected at publication as stale.
4. A current extractor/adapter/render failure releases its exact token and allows another current job; raw error payload never appears in task/result messages. BaseException from synthetic body also releases token and actual workers are finally drained.
5. Capture limit2 then catalog change to1 does not mutate old settings. A new same-authority work with limit1 waits for existing2 actual owners; a later raised limit cannot weaken an older live1 owner.
6. CloudLaneQueueFull maps to existing batch.error.queueFull / Watch queue_full; CloudLaneQueueTimeout to existing batch.error.timeout / Watch timeout. Use injected short monotonic deadlines or a bounded clock seam, not a real600second wait. Map tests may inject fixed lane exceptions but do not substitute for tests1-5.
7. LOCAL executes without entering cloud lane and no legacy/cloud fallback; captured values/types/authority tampering still fail closed. Every Qt target and real Thread/Future must finally close/drain/join at finite deadlines; actual emission/publication tails remain owned.

- [x] **Step2: Run genuine RED natively**

Cwd linked checkout. Exact isolated candidate interpreter/guard; do not use shared oldQt or network:

~~~powershell
& '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\venv\Scripts\python.exe' -B '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\run_guarded_pytest.py' tests/unit/test_analysis_concurrency.py tests/integration/test_shared_cloud_concurrency.py
~~~

Record initial missing-module collection failure, and also genuine captured-setting/shared-service behavior failure before changing those existing source paths. An import error alone does not establish absence of cross-pool enforcement. If tests require the new helper to collect, add a tests-only optional import/pytest helper separation, not a production stub.

- [x] **Step3: Implement the bounded lane**

Complete starting code follows; strengthen only after genuine negatives, not by weakening predicates/counters:

~~~python
"""Shared managed CLOUD analysis capacity; no threads, I/O or Qt."""
import math
from threading import Condition, Lock
import time
from src.core.processing_authority import ProcessingSuperseded

CLOUD_QUEUE_TIMEOUT_SECONDS = 600.0

class CloudLaneQueueFull(RuntimeError):
    pass

class CloudLaneQueueTimeout(RuntimeError):
    pass

class CloudAnalysisLane:
    def __init__(self, *, max_waiters=64, clock=None):
        if (type(max_waiters) is not int or not 1 <= max_waiters <= 1000
                or (clock is not None and not callable(clock))):
            raise ValueError('invalid_cloud_lane_configuration')
        self._condition = Condition(Lock())
        self._clock = clock or time.monotonic
        self._max_waiters = max_waiters
        self._tokens = {}
        self._waiting = 0

    def acquire(self, limit, *, cancelled, deadline):
        if (type(limit) is not int or not 1 <= limit <= 20
                or not callable(cancelled)
                or type(deadline) not in (int, float)
                or not math.isfinite(deadline)):
            raise ValueError('invalid_cloud_lane_acquisition')
        registered = False
        try:
            while True:
                try:
                    if cancelled() is not False:
                        raise ProcessingSuperseded()
                except BaseException:
                    raise ProcessingSuperseded() from None
                now = self._clock()
                if (type(now) not in (int, float) or not math.isfinite(now)):
                    raise ValueError('invalid_cloud_lane_clock')
                if now >= deadline:
                    raise CloudLaneQueueTimeout('cloud_queue_timeout')
                with self._condition:
                    ceiling = min((limit, *self._tokens.values()))
                    if len(self._tokens) < ceiling:
                        token = object()
                        self._tokens[token] = limit
                        return token
                    if not registered:
                        if self._waiting >= self._max_waiters:
                            raise CloudLaneQueueFull('cloud_queue_full')
                        self._waiting += 1
                        registered = True
                    self._condition.wait(min(.05, deadline-now))
        finally:
            if registered:
                with self._condition:
                    self._waiting -= 1
                    self._condition.notify_all()

    def release(self, token):
        if type(token) is not object:
            return False
        with self._condition:
            if token not in self._tokens:
                return False
            del self._tokens[token]
            self._condition.notify_all()
            return True

    @property
    def active_count(self):
        with self._condition:
            return len(self._tokens)

    @property
    def waiting_count(self):
        with self._condition:
            return self._waiting
~~~

No source path/work/request/credential stored in lane. The fixed deadline can be shortened by a test-owned module constant/clock seam, never by editing production authority or suppressing deadline checks.

- [x] **Step4: Capture settings and integrate actual ownership**

Append max_concurrent_requests: int = 4 after the existing AnalysisSettings fields. Add 'max_concurrent_requests': (1, 20) to capture's exact-int bounds. Do not change AppConfig, serialization, existing field order/defaults or other captured values.

In batch_analysis.py import the four lane symbols; instantiate self._cloud_lane = CloudAnalysisLane() beside the existing local lane. Replace run_prepared with the full body below; existing authenticity/checkpoint/error/local behavior retained:

~~~python
def run_prepared(self, work: AnalysisWork, *, cancellation_token=None) -> AnalysisOutcome:
    self._assert_work(work, current=False)
    work._seal.claim_execution()
    deadline = None if work._seal.deferred else work._seal.execution_deadline()
    self._authority.assert_current(work.context)
    latched = False

    def cancelled():
        nonlocal latched
        if latched or not self._authority.is_current(work.context):
            latched = True
            return True
        try:
            latched = bool(cancellation_token and cancellation_token())
        except BaseException:
            latched = True
        latched = latched or not self._authority.is_current(work.context)
        return latched

    def checkpoint():
        if cancelled():
            raise ProcessingSuperseded()
        if deadline is not None and time.monotonic() >= deadline:
            raise BatchAnalysisError('Local analysis timed out')

    lane_acquired = False
    cloud_token = None
    try:
        if work._seal.deferred:
            self._acquire_local_lane(cancelled)
            lane_acquired = True
            deadline = work._seal.execution_deadline()
        elif work.context.mode is ProcessingMode.CLOUD:
            try:
                cloud_token = self._cloud_lane.acquire(
                    work.settings.max_concurrent_requests,
                    cancelled=cancelled,
                    deadline=time.monotonic()+CLOUD_QUEUE_TIMEOUT_SECONDS)
            except CloudLaneQueueFull:
                raise BatchAnalysisError('Cloud analysis queue is full') from None
            except CloudLaneQueueTimeout:
                raise BatchAnalysisError('Cloud analysis queue timed out') from None
        checkpoint()
        source = Path(work.source_path)
        self._validate_local_file(source, work.settings)
        checkpoint()
        if work.context.mode is ProcessingMode.LOCAL:
            outcome = self._run_local(work, source, cancelled, checkpoint, deadline)
        else:
            outcome = self._run_cloud(work, source, cancelled, checkpoint)
        checkpoint()
        return outcome
    except Exception as error:
        checkpoint()
        if isinstance(error, (BatchAnalysisError, SmartNamingError, ProcessingSuperseded)):
            raise
        raise BatchAnalysisError(
            'Local analysis failed' if work.context.mode is ProcessingMode.LOCAL
            else 'Cloud analysis failed') from None
    finally:
        if cloud_token is not None:
            self._cloud_lane.release(cloud_token)
        if lane_acquired:
            self._local_lane.release()
~~~

In BatchWorkspaceController._managed_failure, fixed timeout string set becomes {'Local analysis timed out', 'Cloud analysis queue timed out'}; queue-full set becomes {'Local analysis queue is full', 'Cloud analysis queue is full'}. Keep exception type checks and all other mapping unchanged. In ManagedWatchAnalysisDelivery._run, use the same fixed sets for existing timeout/queue_full reasons. No raw string fallback, new visible message or translation change.

- [x] **Step5: Covering GREEN, independent review and root native Gates**

~~~powershell
& '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\venv\Scripts\python.exe' -B '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\run_guarded_pytest.py' tests/unit/test_analysis_concurrency.py tests/integration/test_shared_cloud_concurrency.py tests/unit/test_processing_analysis.py tests/integration/test_managed_batch_publication.py tests/integration/test_managed_watch_analysis.py tests/integration/test_managed_watch_binding.py tests/integration/test_local_analysis_routing.py tests/integration/test_managed_processing_runtime.py tests/integration/test_batch_analysis_service.py
~~~

Writer report exact RED/GREEN summaries/native exits/forbidden attempts/actual atexit threads and all seven file hashes to .superpowers/sdd/shared-cloud-concurrency-report.md, then freeze all owned paths. Root creates complete diff incl new files, independent review and frozen full/screenshot/acceptance native checks before exact checkpoint. No writer Git. Root's intended commit is fix: share managed cloud analysis concurrency.

## Checkpoint evidence — 2026-10-11

Scoped shared-cloud implementation and its corrected finite Qt-publication predicates received independent spec/quality approval. Original missing-module collection and defective fixture runs were not behavioral RED; the corrected real RED held two adapter bodies at a required limit of one. No real cloud call or model semantic quality is claimed.

Root final frozen coverage: 418 passed, 3 existing warnings; full non-screenshot sequential run: 4705 passed, 3 existing skips, 4 existing warnings; screenshots: 66 passed, 1 designed update-mode skip, 86 existing warnings; acceptance: 186/186. Every completed passing process returned native0, forbidden-access0 and actual atexit MainThread-only. UPDATE_GOLDENS was disabled and the official screenshot tree unchanged. Exact source hashes match both scoped reviews.

The full Gate first exposed an unchanged Watch test that resumed after joining only the observer, not its real retirement worker. A separate tests-only correction waits for actual observer ownership to drain and adds a held-thread-tail regression; it was independently approved and will be separately checkpointed.

A subsequent parallel full/screenshot run crashed during QML garbage collection (native access violation), without a passing summary or normal exit. The same unchanged tree's sequential full run above passed. That failed run remains recorded; its root cause is NOT established by a successful rerun and remains a final-runtime delivery investigation. This checkpoint approves the scoped concurrency work, not production Watch activation, native-runtime stability, packaging or whole-project completion.

## Explicit remaining product boundary

This establishes shared managed service execution capacity only. WatchResourceGuard genuine owned-pending eligibility/recovery, real analysis permit release at Qt publication tail, durable Review/AutoApply/file operations/self-events, production bootstrap/close, local resource/UI/download/model/manual/package still require their own integration. No production Watch/current packaged release/model-semantic/whole-project completion claim.

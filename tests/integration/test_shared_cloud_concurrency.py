"""Shared real managed service across independent Batch/Watch pools.

All sends are synthetic; this is not a production Watch or network Gate.
"""
from dataclasses import replace
from pathlib import Path
from threading import Event, Lock, Thread, get_ident
from types import SimpleNamespace
import copy
import json
import os
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QThread
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

import src.core.batch_analysis as analysis
from src.controllers.batch_workspace_controller import BatchWorkspaceController
from src.controllers.managed_watch_analysis import ManagedWatchAnalysisDelivery
from src.core.analysis_catalog import AnalysisCatalogSource, build_analysis_catalog
from src.core.batch_analysis import BatchAnalysisService, BatchAnalysisError
from src.core.naming_fields import NamingFields
from src.core.processing_analysis import AnalysisSettings, cloud_engine_fingerprint
from src.core.processing_authority import ProcessingAuthority, ProcessingMode, ProcessingSuperseded, LocalReadiness
from src.core.provider_profile import ProviderProfile
from src.core.provider_protocol import ProviderCapabilities, ProviderResponse
from src.core.rename_plan import SourceFingerprint
from src.core.template_model import Template, TemplateField
from src.core.watch_config import WatchConfig
from src.models.app_config import AppConfig
from src.services.local_ai.inference_request import LocalInferenceResult
from src.services.local_ai.preparation_protocol import LocalPreparationResult, PreparationCoverage
from src.services.retry_policy import RetryExecutionResult


def pump(app, predicate, timeout=3):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.003)
    assert predicate(), 'finite Qt/worker state deadline'


@pytest.fixture(scope='module')
def app():
    value = QApplication.instance() or QApplication([])
    assert isinstance(value, QApplication)
    return value


@pytest.fixture
def env(tmp_path, app):
    """Own every real Qt target, Future and bounded synthetic adapter release."""
    template = Template(id='one', name='Synthetic', pattern='{dcTitle}',
        fields=(TemplateField('dcTitle', 'Title'),))
    profile = ProviderProfile(id='active', model='synthetic',
        base_url='https://example.invalid/v1', needs_connection_verification=False,
        capabilities=ProviderCapabilities(text=True, json_schema=True))
    config = AppConfig(default_template_id='one', active_provider_id='active',
        provider_profiles=[profile.to_safe_dict()], max_concurrent_requests=1)
    source = AnalysisCatalogSource(build_analysis_catalog(config, [template]))
    authority = ProcessingAuthority(initial_mode=ProcessingMode.CLOUD)
    authority.bind_cloud_engine(cloud_engine_fingerprint(profile))
    calls, captures, results, watches, releases, direct_threads = [], [], [], [], [], []
    lock = Lock()
    state = SimpleNamespace(active=0, peak=0, entered=0)
    hooks = SimpleNamespace(invoke=lambda request, cancellation: None,
        extract=lambda path: None, render=lambda: None)
    def extract(path, max_chars):
        calls.append(('extract', path.name, get_ident()))
        hooks.extract(path)
        return path.read_text(encoding='utf-8'), {'sections_processed': 1, 'sections_total': 1}
    def credential(profile):
        calls.append(('credential', profile.id, get_ident()))
        return 'synthetic-only'
    def adapter(profile, credential, *, processing_dispatch, retry_executor):
        calls.append(('factory', profile.id, get_ident()))
        def invoke(request, *, cancellation_token):
            receipt = authority.commit_cloud_attempt(processing_dispatch.context, 'synthetic-send')
            with lock:
                state.active += 1
                state.entered += 1
                state.peak = max(state.peak, state.active)
            calls.append(('send', request.task_id, get_ident()))
            try:
                hooks.invoke(request, cancellation_token)
            finally:
                with lock:
                    state.active -= 1
                authority.finish_attempt(receipt)
            return RetryExecutionResult(True,
                ProviderResponse(fields={'dcTitle': 'Synthetic report'}), (), None, None)
        return SimpleNamespace(invoke=invoke)
    service = BatchAnalysisService(profile_provider=lambda: source.get().active_profile,
        credential_provider=credential, config_provider=lambda: source.get().settings,
        template_provider=lambda ident: source.get().template(ident),
        capture_guard=source.guard, processing_authority=authority,
        local_inference_service=object(), local_preparation_service=object(),
        managed_adapter_factory=adapter, content_extractor=extract)
    original_capture = service.capture_work
    def capture(*args, **kwargs):
        work = original_capture(*args, **kwargs)
        captures.append(work)
        return work
    service.capture_work = capture
    controller = BatchWorkspaceController(background=True, max_workers=3,
        workspace_path=tmp_path/'workspace.json', history_path=tmp_path/'history.json')
    controller.configure_templates([dict(id='one', name='Synthetic', outputLanguage='en')], 'one')
    controller.set_managed_analyzer(service, authority)
    bound = [True]
    def watch():
        owner = ManagedWatchAnalysisDelivery(service, authority, capture_guard=source.guard,
            is_binding_current=lambda event: bound[0], on_result=results.append, max_workers=2)
        watches.append(owner)
        return owner
    def path(name):
        value = tmp_path/name
        value.write_text('Distinct synthetic body: '+name, encoding='utf-8')
        return value
    def batch(name='batch.txt'):
        value = path(name)
        controller.add_files([str(value)])
        return controller.task_ids[-1]
    def post(owner, name='watch.txt'):
        value = path(name)
        rule = WatchConfig(id='watch', source_dir=str(tmp_path), template_id='one')
        admission = owner.ingress.capture(rule, 'incarnation', str(value), name)
        assert admission is not None and hasattr(admission, 'work')
        fingerprints = []
        def stat():
            info = os.stat(value, follow_symlinks=False)
            fingerprints.append(SourceFingerprint(info.st_size, info.st_mtime_ns))
        reader = Thread(target=stat)
        reader.start(); reader.join(2)
        assert not reader.is_alive() and len(fingerprints) == 1
        assert owner.ingress.post_stable(admission, fingerprints[0])
        return admission
    def block():
        release = Event(); releases.append(release)
        def invoke(request, cancellation):
            assert release.wait(5), 'bounded synthetic adapter release'
        hooks.invoke = invoke
        return release
    def direct(name, work=None):
        work = work or service.capture_work(str(path(name)), name,
            task_attempt_id=name, task_cancel_event=Event())
        done = SimpleNamespace(work=work, outcome=None, error=None)
        def run():
            try:
                done.outcome = service.run_prepared(work)
            except BaseException as error:
                done.error = error
        thread = Thread(target=run); done.thread = thread
        direct_threads.append(thread); thread.start()
        return done
    value = SimpleNamespace(service=service, authority=authority, config=config, source=source,
        template=template, app=app, controller=controller, calls=calls, captures=captures,
        results=results, watches=watches, watch=watch, batch=batch, post=post, block=block,
        state=state, hooks=hooks, bound=bound, path=path, direct=direct)
    yield value
    for release in releases:
        release.set()
    batch_pool = controller._pool
    controller.close()
    for owner in watches:
        owner.begin_close()
    for thread in direct_threads:
        thread.join(4)
        assert not thread.is_alive(), 'real service thread leaked'
    pump(app, lambda: controller.workers_idle and all(owner.workers_idle for owner in watches), 5)
    for owner in watches:
        assert owner.drain(time.monotonic()+2) and owner.owned_count == 0
        assert not owner._timer.isActive()
        for thread in owner._pool._threads:
            thread.join(2); assert not thread.is_alive()
    for thread in batch_pool._threads:
        thread.join(2); assert not thread.is_alive()
    app.processEvents()
    for target in [controller, *watches]:
        assert QThread.currentThread() == target.thread()
        target.deleteLater()
        QCoreApplication.sendPostedEvents(target, QEvent.Type.DeferredDelete)
        assert not isValid(target), 'Qt target leaked'


def lane(env):
    return getattr(env.service, '_cloud_lane', None)


def waiter_or_extra_send(env, expected):
    # Before implementation an actual second synthetic send is the RED witness,
    # not a missing-module or missing-private-attribute error.
    pump(env.app, lambda: env.state.entered > expected or
        (lane(env) is not None and lane(env).waiting_count > 0))


def test_captured_concurrency_existing_setting_is_frozen():
    config = AppConfig(max_concurrent_requests=2)
    settings = AnalysisSettings.capture(config)
    config.max_concurrent_requests = 20
    assert getattr(settings, 'max_concurrent_requests', None) == 2


def test_batch_watch_real_adapter_share_peak_one_and_preserve_original_publication(env):
    release = env.block()
    tid = env.batch()
    pump(env.app, lambda: env.state.entered == 1)
    owner = env.watch()
    admission = env.post(owner)
    waiter_or_extra_send(env, 1)
    assert env.state.peak == 1, 'distinct real pools exceeded captured limit1'
    assert [item[0] for item in env.calls] == ['extract', 'credential', 'factory', 'send']
    assert lane(env).active_count == lane(env).waiting_count == 1
    assert admission.work is env.captures[1]
    assert env.controller._analysis_work[tid] is env.captures[0]
    release.set()
    pump(env.app, lambda: env.controller.task_snapshot(tid)['status'] == 'review_pending'
        and owner.workers_idle)
    assert len(env.results) == 1 and env.results[0].event.admission is admission
    assert env.results[0].outcome.context is admission.work.context
    assert len(env.captures) == 2 and env.state.entered == 2 and env.state.peak == 1
    assert lane(env).active_count == lane(env).waiting_count == 0
    assert env.controller.workers_idle and owner.owned_count == 0


def test_configured_two_permits_two_real_bodies_and_third_waits(env):
    env.config.max_concurrent_requests = 2
    env.source.install(build_analysis_catalog(env.config, [env.template]))
    release = env.block()
    env.batch('batch-a.txt'); env.batch('batch-b.txt')
    pump(env.app, lambda: env.state.entered == 2)
    owner = env.watch(); env.post(owner)
    waiter_or_extra_send(env, 2)
    assert env.state.active == env.state.peak == 2
    assert lane(env).active_count == 2 and lane(env).waiting_count == 1
    assert sum(call[0] == 'extract' for call in env.calls) == 2
    release.set()
    pump(env.app, lambda: env.controller.workers_idle and owner.workers_idle)
    assert env.state.entered == 3 and env.state.peak == 2 and len(env.results) == 1
    assert lane(env).active_count == lane(env).waiting_count == 0


@pytest.mark.parametrize('cancel', ['watch_task', 'watch_binding', 'batch', 'mode'])
def test_waiting_cancellation_prevents_extraction_send_without_recapture(env, cancel):
    release = env.block()
    first = env.batch('first.txt')
    pump(env.app, lambda: env.state.entered == 1)
    owner = env.watch()
    if cancel == 'batch':
        second = env.batch('queued.txt')
    else:
        admission = env.post(owner)
    waiter_or_extra_send(env, 1)
    assert env.state.entered == 1 and lane(env).waiting_count == 1
    if cancel == 'mode':
        env.batch('another-queued.txt')
        pump(env.app, lambda: lane(env).waiting_count == 2)
    captures = len(env.captures)
    if cancel == 'watch_task':
        admission.cancel_event.set()
    elif cancel == 'watch_binding':
        env.bound[0] = False
        owner.begin_close()
    elif cancel == 'batch':
        env.controller.cancelTask(second)
    else:
        env.authority.select_local()
    pump(env.app, lambda: lane(env).waiting_count == 0)
    assert lane(env).active_count == env.state.active == 1
    assert env.authority.snapshot().committed_attempts == 1
    assert len(env.calls) == 4 and env.state.entered == 1
    assert len(env.captures) == captures
    release.set()
    pump(env.app, lambda: env.controller.workers_idle and owner.workers_idle)
    if cancel == 'mode':
        pump(env.app, lambda: all(env.controller.task_snapshot(tid)['status'] == 'cancelled'
            for tid in env.controller.task_ids))
        assert env.controller.task_snapshot(first)['status'] == 'cancelled'
        assert not env.results
    assert lane(env).active_count == 0 and env.state.entered == 1
    assert env.authority.snapshot().committed_attempts == 0


@pytest.mark.parametrize('stage', ['extract', 'adapter', 'render', 'base_exception'])
def test_actual_failure_releases_token_allows_next_job_and_hides_payload(env, monkeypatch, stage):
    marker = 'PRIVATE_ERROR synthetic-only private-path'
    entered, release = Event(), Event()
    def fail(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        if stage == 'base_exception':
            raise KeyboardInterrupt(marker)
        raise RuntimeError(marker)
    if stage == 'extract':
        env.hooks.extract = fail
    elif stage in {'adapter', 'base_exception'}:
        env.hooks.invoke = fail
    else:
        original = env.service._render_managed
        monkeypatch.setattr(env.service, '_render_managed', fail)
    owner = env.watch(); env.post(owner, 'failing.txt')
    pump(env.app, entered.is_set)
    env.batch('next.txt')
    waiter_or_extra_send(env, env.state.entered)
    assert lane(env).waiting_count == 1 and lane(env).active_count == 1
    if stage == 'extract':
        env.hooks.extract = lambda path: None
    elif stage in {'adapter', 'base_exception'}:
        env.hooks.invoke = lambda request, cancellation: None
    else:
        monkeypatch.setattr(env.service, '_render_managed', original)
    release.set()
    pump(env.app, lambda: owner.workers_idle and env.controller.workers_idle
        and len(env.results) == 1
        and env.controller.task_snapshot(env.controller.task_ids[-1])['status'] == 'review_pending')
    assert len(env.results) == 1 and env.results[0].failure == 'analysis_failed'
    assert marker not in repr(env.results[0])
    snapshot = env.controller.task_snapshot(env.controller.task_ids[-1])
    assert snapshot['status'] == 'review_pending' and marker not in json.dumps(snapshot)
    assert lane(env).active_count == lane(env).waiting_count == 0


def test_catalog_lowering_and_raising_do_not_mutate_or_outrun_live_owners(env):
    env.config.max_concurrent_requests = 2
    env.source.install(build_analysis_catalog(env.config, [env.template]))
    release = env.block()
    old = [env.direct('old-a.txt'), env.direct('old-b.txt')]
    pump(env.app, lambda: env.state.active == 2)
    env.config.max_concurrent_requests = 1
    env.source.install(build_analysis_catalog(env.config, [env.template]))
    low = env.direct('low.txt')
    pump(env.app, lambda: lane(env).waiting_count == 1)
    assert all(job.work.settings.max_concurrent_requests == 2 for job in old)
    assert low.work.settings.max_concurrent_requests == 1 and env.state.entered == 2
    # The low-limit body has its own real blocking release.
    entered_low, release_low = Event(), Event()
    def low_body(request, cancellation):
        entered_low.set(); assert release_low.wait(3)
    env.hooks.invoke = low_body
    release.set()
    try:
        pump(env.app, entered_low.is_set)
        assert lane(env).active_count == 1
        env.config.max_concurrent_requests = 20
        env.source.install(build_analysis_catalog(env.config, [env.template]))
        high = env.direct('high.txt')
        pump(env.app, lambda: lane(env).waiting_count == 1)
        assert high.work.settings.max_concurrent_requests == 20
        assert env.state.entered == 3 and env.state.active == 1
        env.hooks.invoke = lambda request, cancellation: None
        release_low.set()
        pump(env.app, lambda: not high.thread.is_alive())
        assert all(job.error is None for job in [*old, low, high])
        assert env.state.peak == 2 and env.state.entered == 4
        assert lane(env).active_count == lane(env).waiting_count == 0
    finally:
        release_low.set()


@pytest.mark.parametrize('kind, key, reason', [('full', 'queueFull', 'queue_full'),
    ('timeout', 'timeout', 'timeout')])
def test_fixed_cloud_queue_failure_maps_on_actual_qt_workers(env, monkeypatch, kind, key, reason):
    from src.core.analysis_concurrency import CloudLaneQueueFull, CloudLaneQueueTimeout
    error = CloudLaneQueueFull if kind == 'full' else CloudLaneQueueTimeout
    def rejected(*args, **kwargs):
        raise error('PRIVATE_ERROR ignored')
    monkeypatch.setattr(lane(env), 'acquire', rejected)
    tid = env.batch()
    owner = env.watch(); env.post(owner)
    pump(env.app, lambda: env.controller.workers_idle and owner.workers_idle
        and len(env.results) == 1
        and env.controller.task_snapshot(tid)['errorMessage'] == 'batch.error.'+key
        and env.controller.task_snapshot(tid)['status'] == 'failed')
    assert env.controller.task_snapshot(tid)['errorMessage'] == 'batch.error.'+key
    assert env.results[0].failure == reason and not env.calls
    assert 'PRIVATE_ERROR' not in json.dumps(env.controller.task_snapshot(tid))


def test_real_short_cloud_queue_timeout_prevents_waiter_io(env, monkeypatch):
    release = env.block(); env.batch('held.txt')
    pump(env.app, lambda: env.state.active == 1)
    monkeypatch.setattr(analysis, 'CLOUD_QUEUE_TIMEOUT_SECONDS', .1)
    owner = env.watch(); env.post(owner)
    pump(env.app, lambda: bool(env.results))
    assert env.results[0].failure == 'timeout' and env.state.entered == 1
    assert len(env.calls) == 4 and lane(env).active_count == 1
    release.set()


def test_local_execution_never_enters_cloud_or_legacy(env, monkeypatch):
    env.authority.select_local()
    env.authority.set_local_state(env.authority.snapshot().generation, LocalReadiness.READY,
        engine_fingerprint='a'*64)
    local_calls = []
    def forbidden(*args, **kwargs):
        pytest.fail('cloud/legacy fallback in LOCAL')
    monkeypatch.setattr(lane(env), 'acquire', forbidden)
    monkeypatch.setattr(env.service, 'analyze', forbidden)
    monkeypatch.setattr(env.service, 'run_work', forbidden, raising=False)
    def prepare(path, **kwargs):
        local_calls.append('prepare')
        return LocalPreparationResult('synthetic', (), PreparationCoverage('text', sections_processed=1),
            (), kwargs['quality_mode'])
    def infer(request, **kwargs):
        local_calls.append('infer')
        return LocalInferenceResult(True, NamingFields(dcTitle='Local synthetic'), None, 'b'*64, .1)
    env.service._local_preparation = SimpleNamespace(prepare=prepare)
    env.service._local_inference = SimpleNamespace(infer=infer)
    tid = env.batch()
    pump(env.app, lambda: env.controller.workers_idle
        and env.controller.task_snapshot(tid)['status'] == 'review_pending')
    assert env.controller.task_snapshot(tid)['status'] == 'review_pending'
    assert local_calls == ['prepare', 'infer'] and not env.calls
    assert lane(env).active_count == lane(env).waiting_count == 0


@pytest.mark.parametrize('tamper', ['copy', 'foreign_authority', 'bad_limit', 'bad_type'])
def test_tampered_work_fails_closed_before_cloud_io(env, tamper):
    work = env.service.capture_work(str(env.path('tampered.txt')), 'tampered',
        task_attempt_id='attempt', task_cancel_event=Event())
    if tamper == 'copy':
        work = copy.copy(work)
    elif tamper == 'foreign_authority':
        env.service._authority = ProcessingAuthority(initial_mode=ProcessingMode.CLOUD)
    else:
        object.__setattr__(work, 'settings', replace(work.settings,
            max_concurrent_requests=21 if tamper == 'bad_limit' else True))
    with pytest.raises((ProcessingSuperseded, BatchAnalysisError)):
        env.service.run_prepared(work)
    assert not env.calls
    assert lane(env).active_count == lane(env).waiting_count == 0

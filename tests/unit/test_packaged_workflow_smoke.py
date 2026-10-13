"""Source logic/media checks only, never frozen/model acceptance."""
import importlib
import importlib.util
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


def module(name='packaged_workflow_smoke'):
    qualified = 'src.services.local_ai.' + name
    assert importlib.util.find_spec(qualified) is not None, 'fixed workflow diagnostic missing'
    return importlib.import_module(qualified)


def test_cli_exposes_only_fixed_workflow_choices():
    from src.main_qml import _parser
    actions = {action.dest: action for action in _parser()._actions}
    assert 'local_smoke_workflow' in actions, 'workflow option missing'
    assert tuple(actions['local_smoke_workflow'].choices) == ('file-workflows', 'scan-pdf', 'video')


@pytest.mark.parametrize('omitted', ['--smoke-test', '--local-smoke-resources', '--data-dir', '--report'])
def test_workflow_requires_all_explicit_arguments_before_actions(monkeypatch, omitted):
    from src import main_qml
    argv = ['--smoke-test', '--local-smoke-resources', 'public', '--data-dir', 'data', '--report', 'report',
            '--local-smoke-workflow', 'video']
    index = argv.index(omitted)
    del argv[index:index + (1 if omitted == '--smoke-test' else 2)]
    monkeypatch.setattr(main_qml, '_application', lambda: pytest.fail('application created'))
    monkeypatch.setattr(main_qml, 'run_application', lambda: pytest.fail('normal startup'))
    with pytest.raises(SystemExit): main_qml.main(argv)


@pytest.mark.parametrize('workflow', ['file-workflows', 'scan-pdf', 'video'])
def test_cli_dispatches_explicit_workflow_only(monkeypatch, tmp_path, workflow):
    from src import main_qml
    from src.services.local_ai import packaged_smoke
    diagnostic = module()
    captured = {}
    monkeypatch.setattr(diagnostic, 'run_local_workflow_smoke', lambda **kw: captured.update(kw) or 9)
    monkeypatch.setattr(packaged_smoke, 'run_local_smoke', lambda **kw: pytest.fail('old smoke entered'))
    assert main_qml.main(['--smoke-test', '--local-smoke-resources', str(tmp_path/'public'),
        '--data-dir', str(tmp_path/'data'), '--report', str(tmp_path/'report'),
        '--local-smoke-workflow', workflow]) == 9
    assert captured == dict(resources_dir=tmp_path/'public', data_dir=tmp_path/'data',
                            report_path=tmp_path/'report', workflow=workflow)


def test_invalid_workflow_refused_before_root_creation(tmp_path):
    with pytest.raises(ValueError):
        module().run_local_workflow_smoke(resources_dir=tmp_path/'public', data_dir=tmp_path/'data',
                                         report_path=tmp_path/'report', workflow='arbitrary')
    assert not (tmp_path/'data').exists()


def test_builder_creates_fixed_empty_watch_config_before_real_builder(tmp_path, monkeypatch):
    diagnostic = module()
    from src.core.template_store import TemplateStore
    from src.core.watch_config import WatchConfigStore, WatchMode
    data = tmp_path/'fresh'; data.mkdir()
    sentinel = object()
    def builder(**kwargs):
        assert kwargs['credential_store'] is sentinel
        configs = WatchConfigStore(data/'watch_folders.json').list_all()
        assert {c.mode for c in configs} == {WatchMode.REVIEW_FIRST, WatchMode.AUTO_APPLY}
        for c in configs:
            assert list(Path(c.source_dir).iterdir()) == []
            template = TemplateStore(data/'templates.json').get(c.template_id)
            assert template.pattern == '{dcTitle}'
            assert template.output_language.value == 'zh-HK'
        return sentinel
    monkeypatch.setattr(diagnostic, 'build_qml_runtime', builder)
    assert diagnostic._workflow_runtime_builder(config_file=data/'settings.json', credential_store=sentinel) is sentinel


def test_scan_pdf_is_two_image_only_pages_with_bounded_rendered_payloads(tmp_path):
    import pymupdf
    from src.services.media.pdf_renderer import PdfRenderer
    media = module('synthetic_smoke_media')
    source = media.create_scan_pdf(tmp_path)
    assert source.name == 'synthetic-coffee-maintenance.pdf'
    with pymupdf.open(source) as document:
        assert len(document) == 2
        assert all(not page.get_text().strip() and page.get_images() for page in document)
    rendered = PdfRenderer().render_bytes(source.read_bytes(), provenance='synthetic-scan', page_indices=(0, 1))
    assert rendered.rendered_page_indices == (0, 1)
    assert len(rendered.payloads) == 2
    assert all(p.kind == 'rendered_scan_page' and p.width > 0 and p.height > 0 and
               p.byte_size == len(p.data) for p in rendered.payloads)
    with pytest.raises(FileExistsError): media.create_scan_pdf(tmp_path)


def test_video_has_three_visibly_distinct_stages_and_real_bounded_keyframes(tmp_path):
    import av
    from src.services.media.keyframe_extractor import VideoKeyframeExtractor
    media = module('synthetic_smoke_media')
    source = media.create_video(tmp_path)
    assert source.name == 'synthetic-plant-propagation.mp4'
    with av.open(source) as container:
        frames = [frame.to_image() for frame in container.decode(video=0)]
    assert len(frames) == 72
    assert len({frames[i].tobytes() for i in (0, 24, 48)}) == 3
    extracted = VideoKeyframeExtractor().extract_bytes(source.read_bytes(), provenance='synthetic-video', quality_mode='balanced')
    assert 3 <= len(extracted.payloads) <= 6
    assert len(extracted.timestamps_seconds) == len(extracted.payloads)
    assert all(p.kind == 'video_keyframe' and p.byte_size == len(p.data) for p in extracted.payloads)
    with pytest.raises(FileExistsError): media.create_video(tmp_path)


def test_request_observer_forwards_exact_request_and_returns_exact_outcome(tmp_path):
    from src.services.local_ai.inference_request import LocalNamingRequest, LocalInferenceResult
    from src.services.media.image_preprocessor import ImagePreprocessor
    from PIL import Image
    import io
    data = io.BytesIO(); Image.new('RGB', (64, 64), 'green').save(data, format='PNG')
    payload = ImagePreprocessor().process_bytes(data.getvalue(), source_index=0, provenance='fixed')
    request = LocalNamingRequest('', (payload,), 'zh-HK', 'smart')
    outcome = LocalInferenceResult(False, None, 'INVALID_RESPONSE', None, .1)
    calls = []
    service = SimpleNamespace(infer=lambda *args, **kw: calls.append((args, kw)) or outcome)
    observer = module()._RequestObserver(tmp_path/'fixed.pdf', b'%PDF-fixed', 'scan-pdf')
    observer.attach(service)
    token = object()
    assert service.infer(request, cancelled=token) is outcome
    assert calls == [((request,), {'cancelled': token})]
    facts = observer.records[0]
    assert facts['visual_count'] == 1 and facts['text_bytes'] == 0
    assert facts['visuals'][0]['source_index'] == 0
    assert facts['response_success'] is False and facts['response_error'] == 'INVALID_RESPONSE'
    assert str(tmp_path) not in json.dumps(facts) and '%PDF-fixed' not in json.dumps(facts)


@pytest.mark.parametrize('bad', ['path', 'container', 'not_ready', 'exception'])
def test_request_observer_fails_closed_without_replacing_outputs(tmp_path, bad):
    from src.services.local_ai.inference_request import LocalNamingRequest, LocalInferenceResult
    observer = module()._RequestObserver(tmp_path/'fixed.mp4', b'full-container', 'video')
    request = LocalNamingRequest(str(tmp_path/'fixed.mp4') if bad == 'path' else
                                 'full-container' if bad == 'container' else 'synthetic', (), 'zh-HK', 'smart')
    error = RuntimeError('private details')
    def original(*args, **kw):
        if bad == 'exception': raise error
        return LocalInferenceResult(False, None, 'NOT_READY', None, 0)
    service = SimpleNamespace(infer=original); observer.attach(service)
    if bad in ('path', 'container'):
        with pytest.raises(RuntimeError): service.infer(request)
    elif bad == 'exception':
        with pytest.raises(RuntimeError) as caught: service.infer(request)
        assert caught.value is error
    else:
        assert service.infer(request).error == 'NOT_READY'
        with pytest.raises(RuntimeError): observer.require_success()
    assert 'private details' not in json.dumps(observer.records)


class FakeBatch:
    """Stateful file-controller boundary: real filesystem, no inference."""
    def __init__(self, source, failure='', corrupt=False):
        self.source, self.failure, self.corrupt = source, failure, corrupt
        self.row = dict(status='review_pending', suggestedName='雨水花園維護指南.txt', validationError='',
                        appliedPath='', fileOperationPending=False)
        self.task_ids = ('fixed',)
    def task_snapshot(self, task): return dict(self.row)
    def applyTask(self, task):
        if self.failure == 'admission':
            self.row['errorMessage'] = 'fileops.error.admissionSaveFailed'; return
        if self.failure:
            self.row['status'] = self.failure; return
        target = self.source.with_name(self.row['suggestedName'])
        self.source.rename(target); self.row.update(status='applied', appliedPath=str(target))
    def undoTask(self, task):
        Path(self.row['appliedPath']).rename(self.source)
        if self.corrupt: self.source.write_bytes(b'corrupted')
        self.row.update(status='undone', appliedPath='')


@pytest.mark.parametrize('failure,corrupt', [('failed', False), ('', True), ('', False)])
def test_batch_apply_undo_checks_observed_states_and_restored_hash(tmp_path, failure, corrupt):
    diagnostic = module()
    source = tmp_path/'synthetic-rain-garden.txt'; source.write_bytes(b'fixed synthetic')
    batch = FakeBatch(source, failure, corrupt)
    if failure or corrupt:
        with pytest.raises(RuntimeError): diagnostic._batch_apply_undo(batch, 'fixed', source, time.monotonic()+1)
    else:
        facts = diagnostic._batch_apply_undo(batch, 'fixed', source, time.monotonic()+1)
        assert facts['applied_state'] == 'applied' and facts['undo_state'] == 'undone'
        assert facts['restored_sha256'] == facts['original_sha256']
        assert source.read_bytes() == b'fixed synthetic'


def test_batch_admission_failure_is_rejected_without_waiting_for_status_change(tmp_path):
    from src.main_qml import _application
    _application()  # This negative case actually spins the Qt wait loop.
    source = tmp_path/'synthetic-rain-garden.txt'; source.write_bytes(b'fixed')
    with pytest.raises(RuntimeError):
        module()._batch_apply_undo(FakeBatch(source, 'admission'), 'fixed', source, time.monotonic()+.1)
    assert source.read_bytes() == b'fixed'


@pytest.mark.parametrize('field', ['fileOperationRecoveryRequired', 'fileOperation', 'errorMessage'])
def test_batch_applied_state_with_unresolved_ownership_is_not_a_pass(tmp_path, field):
    source = tmp_path/'synthetic-rain-garden.txt'; source.write_bytes(b'fixed')
    batch = FakeBatch(source)
    original = batch.applyTask
    def apply(task):
        original(task)
        batch.row['fileOperationPending'] = True
        batch.row[field] = True if field == 'fileOperationRecoveryRequired' else 'unresolved'
    batch.applyTask = apply
    with pytest.raises(RuntimeError): module()._batch_apply_undo(batch, 'fixed', source, time.monotonic()+1)
    assert Path(batch.row['appliedPath']).read_bytes() == b'fixed'


def test_wrapper_reuses_guard_runner_and_configures_only_file_workflow(tmp_path, monkeypatch):
    diagnostic = module()
    captured = []
    monkeypatch.setattr(diagnostic, 'run_local_smoke', lambda **kw: captured.append(kw) or 7)
    for workflow in ('file-workflows', 'scan-pdf', 'video'):
        assert diagnostic.run_local_workflow_smoke(resources_dir=tmp_path/'public', data_dir=tmp_path/'data',
                  report_path=tmp_path/'report', workflow=workflow) == 7
    assert captured[0]['runtime_builder'] is diagnostic._workflow_runtime_builder
    assert all(kw['cleanup_timeout'] == 45 and 0 < kw['timeout'] <= 1800 for kw in captured)


@pytest.mark.parametrize('forbidden', ['', 'cloud', 'credentials'])
def test_workflow_wrapper_preserves_real_guard_counts_cleanup_and_failure_report(tmp_path, monkeypatch, forbidden):
    diagnostic = module()
    runtime = SimpleNamespace(warnings=[], cleanup=lambda **kw: True)
    captured = {}
    def builder(**kw):
        captured.update(kw)
        assert kw['config_file'].parent.is_dir()
        return runtime
    def exercise(*args):
        if forbidden == 'cloud': captured['managed_adapter_factory']()
        if forbidden == 'credentials': captured['credential_store'].get('fixed', 'fixed')
        return {'workflow':'scan-pdf', 'semantic_quality':'not_judged'}
    monkeypatch.setattr(diagnostic, 'build_qml_runtime', builder)
    monkeypatch.setattr(diagnostic, '_exercise_media', exercise)
    (tmp_path/'public').mkdir()
    assert diagnostic.run_local_workflow_smoke(resources_dir=tmp_path/'public', data_dir=tmp_path/'data',
        report_path=tmp_path/'report.json', workflow='scan-pdf') == (2 if forbidden else 0)
    payload = json.loads((tmp_path/'report.json').read_text(encoding='utf-8'))
    assert payload['status'] == ('failed' if forbidden else 'ok')
    assert payload['strict_shutdown'] is True
    assert payload['forbidden_attempts'] == {'network':0, 'credentials':int(forbidden=='credentials'),
                                             'cloud':int(forbidden=='cloud')}
    assert payload['semantic_quality'] == 'not_judged'


@pytest.mark.parametrize('mode,phase,ready', [('cloud', 'READY', 'ready'), ('local', 'NOT_READY', 'not_ready')])
def test_media_preparation_rejects_nonlocal_or_not_ready(tmp_path, mode, phase, ready):
    from src.core.processing_authority import ProcessingMode, LocalReadiness
    from src.services.local_ai.production_resources import PRODUCT_CATALOG_ID
    public = tmp_path/'public'; public.mkdir()
    snapshot = SimpleNamespace(persistence_status=SimpleNamespace(value='saved'), mode=ProcessingMode(mode),
        local_readiness=LocalReadiness(ready), engine_fingerprint='a'*64)
    runtime = SimpleNamespace(production_resources=SimpleNamespace(catalog=SimpleNamespace(identity=PRODUCT_CATALOG_ID, resources=())),
        root=SimpleNamespace(show=lambda: None), assert_zero_warnings=lambda: None,
        processing_coordinator=SimpleNamespace(selectLocal=lambda: True, snapshot=snapshot),
        local_resources_controller=SimpleNamespace(importAndEnable=lambda value: True, busy=False, phase=phase))
    with pytest.raises(RuntimeError): module()._prepare_local(runtime, public, tmp_path/'data', time.monotonic()+1)


@pytest.mark.parametrize('workflow', ['anything', 'video'])
def test_workflow_cli_invalid_or_version_conflict_cannot_create_application(monkeypatch, workflow):
    from src import main_qml
    monkeypatch.setattr(main_qml, '_application', lambda: pytest.fail('application created'))
    with pytest.raises(SystemExit): main_qml.main(['--version', '--smoke-test', '--local-smoke-resources', 'public',
                         '--data-dir', 'data', '--report', 'report', '--local-smoke-workflow', workflow])


def test_request_failure_snapshot_is_bounded_exclusive_and_content_free(tmp_path):
    from src.services.local_ai.inference_request import LocalNamingRequest, LocalInferenceResult
    observer = module()._RequestObserver(tmp_path/'fixed.pdf', b'%PDF-fixed', 'scan-pdf')
    service = SimpleNamespace(infer=lambda request: LocalInferenceResult(False, None, 'NOT_READY', None, 0))
    observer.attach(service)
    service.infer(LocalNamingRequest('synthetic coffee', (), 'zh-HK', 'smart'))
    assert hasattr(observer, 'write_snapshot'), 'fresh fixed failure facts missing'
    observer.write_snapshot(tmp_path)
    output = tmp_path/'synthetic-request-facts.json'
    facts = json.loads(output.read_text(encoding='utf-8'))
    assert facts['requests'][0]['response_error'] == 'NOT_READY'
    assert facts['semantic_quality'] == 'not_judged'
    assert all(value not in output.read_text(encoding='utf-8') for value in ('synthetic coffee', str(tmp_path), '%PDF-fixed'))
    before = output.read_bytes()
    with pytest.raises(FileExistsError): observer.write_snapshot(tmp_path)
    assert output.read_bytes() == before


@pytest.mark.parametrize('state,success', [('review_pending', True), ('failed', False), ('review_pending', False)])
def test_media_orchestration_uses_actual_returned_states_and_outcome(tmp_path, monkeypatch, state, success):
    from src.services.local_ai.inference_request import LocalNamingRequest, LocalInferenceResult
    from src.services.media.pdf_renderer import PdfRenderer
    diagnostic = module()
    monkeypatch.setattr(diagnostic, '_prepare_local', lambda *args: None)
    service = SimpleNamespace(infer=lambda request: LocalInferenceResult(success, None,
                                  None if success else 'NOT_READY', None, 0))
    class Batch:
        task_ids = ()
        def setNamingMode(self, mode): assert mode == 'smart'
        def setNamingLanguage(self, language): assert language == 'zh-HK'
        def add_files(self, paths):
            self.task_ids = ('fixed',)
            prepared = PdfRenderer().render_bytes(Path(paths[0]).read_bytes(), provenance='fixed', page_indices=(0,1))
            service.infer(LocalNamingRequest('', prepared.payloads, 'zh-HK', 'smart'))
        def task_snapshot(self, task):
            return dict(status=state, suggestedName='咖啡機維護指南.pdf', validationError='',
                        analysisCoverageType='local', analysisCoverage={'content_kind':'scanned_pdf'})
    original = service.infer
    runtime = SimpleNamespace(batch_controller=Batch(), local_inference_service=service, assert_zero_warnings=lambda: None)
    if state == 'review_pending' and success:
        result = diagnostic._exercise_media(runtime, tmp_path/'public', tmp_path, time.monotonic()+5, 'scan-pdf')
        assert result['cases'][0]['request']['visual_count'] == 2
        assert result['semantic_quality'] == 'not_judged'
    else:
        with pytest.raises(RuntimeError): diagnostic._exercise_media(runtime, tmp_path/'public', tmp_path, time.monotonic()+5, 'scan-pdf')
    assert service.infer is original
    assert (tmp_path/'synthetic-coffee-maintenance.pdf').is_file()
    assert (tmp_path/'synthetic-request-facts.json').is_file()


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('failure', ['', 'failed', 'hash', 'duplicate', 'recovery'])
def test_watch_checks_actual_result_native_paths_hashes_and_duplicate_window(tmp_path, monkeypatch, auto, failure):
    from dataclasses import replace
    from src.core.watch_review_queue import ReviewItem, ReviewItemState
    from src.services.local_ai.packaged_smoke import SYNTHETIC_TEXT
    diagnostic = module()
    mode = 'auto_apply' if auto else 'review_first'
    folder = tmp_path/mode; folder.mkdir()
    items = []
    def results():
        source = folder/'synthetic-rain-garden.txt'
        if not items and source.exists():
            state = ReviewItemState.FAILED if failure == 'failed' else ReviewItemState.AWAITING_APPROVAL
            item = ReviewItem('fixed', mode, str(source), source.stat().st_size, source.stat().st_mtime_ns,
                              '.txt', source.name, state, suggested_name='雨水花園維護指南.txt')
            items.append(item)
            if auto and not failure == 'failed': apply('fixed')
        return tuple(items)
    def apply(identifier):
        source = folder/'synthetic-rain-garden.txt'; target = folder/'雨水花園維護指南.txt'
        source.rename(target)
        items[0] = replace(items[0], state=ReviewItemState.APPLIED, applied_path=str(target),
                           recovery_required=failure == 'recovery')
        return True
    def undo(identifier):
        Path(items[0].applied_path).rename(folder/'synthetic-rain-garden.txt')
        if failure == 'hash': (folder/'synthetic-rain-garden.txt').write_bytes(b'bad')
        items[0] = replace(items[0], state=ReviewItemState.UNDONE)
        return True
    observed = []
    def observation(deadline, seconds):
        observed.append(seconds)
        if failure == 'duplicate': items.append(replace(items[0], id='duplicate'))
    monkeypatch.setattr(diagnostic, '_observe_window', observation)
    runtime = SimpleNamespace(watch_owner=SimpleNamespace(file_actions=SimpleNamespace(workers_idle=True),
        results=SimpleNamespace(items=results,
        item=lambda identifier: items[0])), watch_controller=SimpleNamespace(approveResult=apply, undoResult=undo))
    if failure:
        with pytest.raises(RuntimeError): diagnostic._watch_case(runtime, tmp_path, mode, time.monotonic()+15)
    else:
        facts = diagnostic._watch_case(runtime, tmp_path, mode, time.monotonic()+15)
        assert facts['restored_sha256'] == facts['original_sha256']
        assert facts['result_count'] == 1 and observed == [6.0]
        assert (folder/'synthetic-rain-garden.txt').read_text(encoding='utf-8') == SYNTHETIC_TEXT


def install_completion_queue(monkeypatch, diagnostic, events):
    """Deliver distinct completion callbacks only while the product waits.

    Tests inspect product predicates/ordering, not elapsed scheduler time or
    real Qt/native acceptance. Filesystem renames below are actual temp I/O.
    """
    def wait(predicate, deadline):
        while not predicate():
            assert events, 'No completion queued while waiting for a terminal boundary'
            events.pop(0)()
    monkeypatch.setattr(diagnostic, '_wait', wait)


@pytest.mark.parametrize('delayed', ['apply', 'undo'])
def test_batch_terminal_progress_waits_for_queued_live_owner_release(tmp_path, monkeypatch, delayed):
    diagnostic = module()
    source = tmp_path/'synthetic-rain-garden.txt'; source.write_bytes(b'fixed synthetic')
    events, ordering = [], []
    batch = FakeBatch(source)
    original_apply, original_undo = batch.applyTask, batch.undoTask
    def completion(operation):
        ordering.append(operation+'_completion')
        batch.row['fileOperationPending'] = False
    def apply(task):
        ordering.append('apply_requested')
        original_apply(task)
        ordering.append('apply_progress_terminal')
        if delayed == 'apply':
            batch.row['fileOperationPending'] = True
            events.append(lambda: completion('apply'))
    def undo(task):
        ordering.append('undo_requested')
        assert batch.row['fileOperationPending'] is False, 'Undo requested before Apply owner release'
        original_undo(task)
        ordering.append('undo_progress_terminal')
        if delayed == 'undo':
            batch.row['fileOperationPending'] = True
            events.append(lambda: completion('undo'))
    batch.applyTask, batch.undoTask = apply, undo
    install_completion_queue(monkeypatch, diagnostic, events)
    result = diagnostic._batch_apply_undo(batch, 'fixed', source, time.monotonic()+1)
    assert batch.row['fileOperationPending'] is False, 'Returned before Undo owner release'
    assert events == [] and ordering.count('undo_requested') == 1
    if delayed == 'apply': assert ordering.index('apply_completion') < ordering.index('undo_requested')
    assert result['restored_sha256'] == result['original_sha256']
    assert result['apply_owner_released'] and result['undo_owner_released']
    assert source.read_bytes() == b'fixed synthetic'


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('delayed', ['apply', 'undo'])
def test_watch_terminal_progress_waits_for_queued_file_actions_idle(tmp_path, monkeypatch, auto, delayed):
    from dataclasses import replace
    from src.core.watch_review_queue import ReviewItem, ReviewItemState as State
    diagnostic = module()
    mode = 'auto_apply' if auto else 'review_first'
    folder = tmp_path/mode; folder.mkdir()
    source, target = folder/'synthetic-rain-garden.txt', folder/'雨水花園維護指南.txt'
    events, ordering, items = [], [], []
    file_actions = SimpleNamespace(workers_idle=True)
    def completion(operation):
        ordering.append(operation+'_completion')
        file_actions.workers_idle = True
    def apply(identifier):
        ordering.append('apply_requested')
        source.rename(target)
        items[0] = replace(items[0], state=State.APPLIED, applied_path=str(target))
        ordering.append('apply_progress_terminal')
        if delayed == 'apply':
            file_actions.workers_idle = False
            events.append(lambda: completion('apply'))
        return True
    def rows():
        if not items and source.exists():
            items.append(ReviewItem('fixed', mode, str(source), source.stat().st_size,
                source.stat().st_mtime_ns, '.txt', source.name, State.AWAITING_APPROVAL,
                suggested_name=target.name))
            if auto: apply('fixed')
        return tuple(items)
    def undo(identifier):
        ordering.append('undo_requested')
        assert file_actions.workers_idle, 'Undo requested before Watch Apply owner release'
        target.rename(source)
        items[0] = replace(items[0], state=State.UNDONE, applied_path='')
        ordering.append('undo_progress_terminal')
        if delayed == 'undo':
            file_actions.workers_idle = False
            events.append(lambda: completion('undo'))
        return True
    runtime = SimpleNamespace(watch_owner=SimpleNamespace(file_actions=file_actions,
        results=SimpleNamespace(items=rows, item=lambda identifier: items[0])),
        watch_controller=SimpleNamespace(approveResult=apply, undoResult=undo))
    install_completion_queue(monkeypatch, diagnostic, events)
    observed = []
    def observation(deadline, seconds):
        assert file_actions.workers_idle, 'Duplicate observation began before Watch Undo owner release'
        observed.append(seconds)
    monkeypatch.setattr(diagnostic, '_observe_window', observation)
    result = diagnostic._watch_case(runtime, tmp_path, mode, time.monotonic()+1)
    assert events == [] and file_actions.workers_idle and observed == [6.0]
    assert ordering.count('undo_requested') == 1
    if delayed == 'apply': assert ordering.index('apply_completion') < ordering.index('undo_requested')
    assert result['restored_sha256'] == result['original_sha256']
    assert result['apply_owner_idle'] and result['undo_owner_idle']

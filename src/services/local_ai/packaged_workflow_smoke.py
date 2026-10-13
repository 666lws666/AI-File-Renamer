"""Fixed synthetic workflow diagnostics, never startup or semantic acceptance.

The existing smoke runner exclusively owns isolation, guards and cleanup.
Observers forward the actual inference request/result; no replacement outputs.
"""
from __future__ import annotations

from functools import wraps
from hashlib import sha256
import json
from pathlib import Path
import threading
import time

from src.qml_bootstrap import build_qml_runtime
from .packaged_smoke import (run_local_smoke, _exercise, _wait, SYNTHETIC_NAME,
                             SYNTHETIC_TEXT, _DependencyObserver)
from .production_resources import PRODUCT_CATALOG_ID


WORKFLOWS = ('file-workflows', 'scan-pdf', 'video')
_WATCH_MODES = ('review_first', 'auto_apply')
_TEMPLATE_ID = 'synthetic-title-hk'


def _workflow_runtime_builder(**kwargs):
    """Only called after the runner proves and creates a fresh data root."""
    from src.core.template_store import TemplateStore
    from src.core.template_model import Template, TemplateField, OutputLanguage
    from src.core.watch_config import WatchConfig, WatchConfigStore, WatchMode
    root = Path(kwargs['config_file']).parent
    TemplateStore(root/'templates.json').create(Template(id=_TEMPLATE_ID,
        name='Synthetic title only', pattern='{dcTitle}',
        fields=(TemplateField('dcTitle', 'Title', id='synthetic-title-field'),),
        output_language=OutputLanguage.ZH_HK))
    store = WatchConfigStore(root/'watch_folders.json')
    for mode in _WATCH_MODES:
        folder = root/mode; folder.mkdir()
        store.add(WatchConfig(mode, str(folder), template_id=_TEMPLATE_ID, mode=WatchMode(mode)))
    return build_qml_runtime(**kwargs)


def _digest(source):
    return sha256(source.read_bytes()).hexdigest()


def _require(condition, code):
    if not condition: raise RuntimeError(code)


def _valid_name(name, extension, *, smart=True):
    from src.core.naming_orthography import normalize_managed_name
    from src.core.filename_validator import validate_filename
    return (type(name) is str and bool(name) and '/' not in name and '\\' not in name
            and validate_filename(name, extension).is_valid
            and normalize_managed_name(name, 'zh-HK', extension, smart=smart) == name)


def _batch_apply_undo(batch, task_id, source, deadline):
    def wait_operation(expected, waiting, code):
        def completed():
            current = batch.task_snapshot(task_id)
            _require(not current.get('fileOperationRecoveryRequired')
                     and not current.get('errorMessage'), code)
            if current['status'] != expected:
                _require(current['status'] in waiting, code)
                return False
            _require(not current.get('fileOperation'), code)
            # Progress publishes the terminal row before the queued completion
            # retires this task's live owner. Only the latter permits Undo.
            return current['fileOperationPending'] is False
        _wait(completed, min(deadline, time.monotonic()+45))
        return batch.task_snapshot(task_id)

    original = _digest(source)
    row = batch.task_snapshot(task_id)
    _require(row['status'] == 'review_pending' and not row.get('validationError')
             and _valid_name(row['suggestedName'], source.suffix), 'WORKFLOW_BATCH_SUGGESTION_INVALID')
    target = source.with_name(row['suggestedName'])
    _require(target != source and not target.exists(), 'WORKFLOW_BATCH_TARGET_INVALID')
    batch.applyTask(task_id)
    applied = wait_operation('applied', ('review_pending', 'applying'), 'WORKFLOW_BATCH_APPLY_FAILED')
    _require(applied['status'] == 'applied' and Path(applied.get('appliedPath', '')) == target
             and not applied.get('fileOperationRecoveryRequired') and not applied.get('fileOperation')
             and not applied.get('errorMessage')
             and target.is_file() and not source.exists() and _digest(target) == original,
             'WORKFLOW_BATCH_APPLY_FAILED')
    batch.undoTask(task_id)
    undone = wait_operation('undone', ('applied', 'undoing'), 'WORKFLOW_BATCH_UNDO_FAILED')
    _require(undone['status'] == 'undone' and source.is_file() and not target.exists()
             and not undone.get('fileOperationRecoveryRequired') and not undone.get('fileOperation')
             and not undone.get('errorMessage')
             and _digest(source) == original, 'WORKFLOW_BATCH_UNDO_FAILED')
    return dict(case='batch_smart_hk', language='zh-HK', naming_mode='smart',
        generated_filename=applied['suggestedName'], applied_state=applied['status'],
        undo_state=undone['status'], original_sha256=original, applied_sha256=original,
        restored_sha256=_digest(source), apply_owner_released=applied['fileOperationPending'] is False,
        undo_owner_released=undone['fileOperationPending'] is False)


def _observe_window(deadline, seconds):
    _require(time.monotonic()+seconds <= deadline, 'WORKFLOW_OBSERVATION_BUDGET')
    end = time.monotonic()+seconds
    _wait(lambda: time.monotonic() >= end, deadline)


def _watch_case(runtime, data_dir, mode, deadline):
    from src.core.watch_review_queue import ReviewItemState as State
    source = data_dir/mode/SYNTHETIC_NAME
    with source.open('x', encoding='utf-8') as handle: handle.write(SYNTHETIC_TEXT)
    original = _digest(source)
    queue = runtime.watch_owner.results
    file_actions = runtime.watch_owner.file_actions

    def wait_operation(identifier, expected, waiting, code):
        def completed():
            current = queue.item(identifier)
            _require(not current.recovery_required and not current.error_category, code)
            if current.state is not expected:
                _require(current.state in waiting, code)
                return False
            _require(current.file_operation is None, code)
            # A clean progress-published row can still have a live operation
            # owner/publication/lane tail; use the existing actual idle boundary.
            return file_actions.workers_idle is True
        _wait(completed, min(deadline, time.monotonic()+45))
        return queue.item(identifier)

    def rows(): return tuple(row for row in queue.items() if row.watch_id == mode)
    _wait(lambda: bool(rows()) and any(row.state not in (State.PENDING, State.ANALYZING, State.APPLYING)
                                     for row in rows()), deadline)
    _require(len(rows()) == 1, 'WORKFLOW_WATCH_DUPLICATE')
    row = rows()[0]
    _require(not row.recovery_required and not row.error_category and row.file_operation is None,
             'WORKFLOW_WATCH_RECOVERY_REQUIRED')
    _require(_valid_name(row.suggested_name, '.txt', smart=False), 'WORKFLOW_WATCH_NAME_INVALID')
    target = source.with_name(row.suggested_name)
    _require(target != source, 'WORKFLOW_WATCH_TARGET_INVALID')
    if mode == 'review_first':
        _require(row.state is State.AWAITING_APPROVAL and source.is_file() and not target.exists()
                 and _digest(source) == original, 'WORKFLOW_WATCH_REVIEW_FAILED')
        _require(runtime.watch_controller.approveResult(row.id) is True, 'WORKFLOW_WATCH_APPROVE_REFUSED')
    applied = wait_operation(row.id, State.APPLIED, (State.AWAITING_APPROVAL, State.APPLYING),
                             'WORKFLOW_WATCH_APPLY_FAILED')
    applied_owner_idle = file_actions.workers_idle is True
    _require(applied.state is State.APPLIED and Path(applied.applied_path) == target
             and not applied.recovery_required and not applied.error_category and applied.file_operation is None
             and target.is_file() and not source.exists() and _digest(target) == original,
             'WORKFLOW_WATCH_APPLY_FAILED')
    _require(runtime.watch_controller.undoResult(row.id) is True, 'WORKFLOW_WATCH_UNDO_REFUSED')
    undone = wait_operation(row.id, State.UNDONE, (State.APPLIED, State.APPLYING),
                            'WORKFLOW_WATCH_UNDO_FAILED')
    undone_owner_idle = file_actions.workers_idle is True
    _require(undone.state is State.UNDONE and source.is_file()
             and not undone.recovery_required and not undone.error_category
             and undone.file_operation is None
             and not target.exists() and _digest(source) == original, 'WORKFLOW_WATCH_UNDO_FAILED')
    _observe_window(deadline, 6.0)
    _require(len(rows()) == 1 and queue.item(row.id).state is State.UNDONE
             and source.is_file() and _digest(source) == original and not target.exists(),
             'WORKFLOW_WATCH_SELF_TRIGGERED')
    return dict(case='watch_'+mode+'_template_hk', language='zh-HK', naming_mode='template',
        generated_filename=row.suggested_name, applied_state=applied.state.value, undo_state='undone',
        original_sha256=original, applied_sha256=original, restored_sha256=_digest(source),
        result_count=len(rows()), duplicate_observation_seconds=6.0,
        apply_owner_idle=applied_owner_idle, undo_owner_idle=undone_owner_idle)


def _exercise_files(runtime, resources_dir, data_dir, deadline):
    watch_before = (data_dir/'watch_folders.json').read_bytes()
    template_before = (data_dir/'templates.json').read_bytes()
    summary = _exercise(runtime, resources_dir, data_dir, deadline)
    batch = runtime.batch_controller
    _require(len(batch.task_ids) == 1, 'WORKFLOW_BATCH_COUNT_INVALID')
    cases = [_batch_apply_undo(batch, batch.task_ids[0], data_dir/SYNTHETIC_NAME, deadline)]
    owner = runtime.watch_owner
    _require(all(state.observer.is_alive() for state in owner.controller._watches.values())
             and len(owner.controller._watches) == 2, 'WORKFLOW_WATCH_OBSERVER_NOT_READY')
    for mode in _WATCH_MODES: cases.append(_watch_case(runtime, data_dir, mode, deadline))
    _require((data_dir/'watch_folders.json').read_bytes() == watch_before
             and (data_dir/'templates.json').read_bytes() == template_before,
             'WORKFLOW_CONFIG_CHANGED')
    runtime.assert_zero_warnings()
    # The original local-text smoke deliberately never applies. Do not carry
    # that assertion into this explicit native-file diagnostic.
    summary['assertions'].pop('apply_not_executed', None)
    summary.update(workflow='file-workflows', cases=cases, config_bytes_unchanged=True,
                   semantic_quality='not_judged')
    return summary


def _prepare_local(runtime, resources_dir, data_dir, deadline):
    from src.core.processing_authority import ProcessingMode, LocalReadiness
    _require(runtime.production_resources.catalog.identity == PRODUCT_CATALOG_ID,
             'LOCAL_SMOKE_CATALOG_MISMATCH')
    _require(resources_dir.is_dir() and not resources_dir.is_relative_to(data_dir)
             and not data_dir.is_relative_to(resources_dir), 'LOCAL_SMOKE_SOURCE_INVALID')
    _require(all((resources_dir/item.filename).is_file()
                 for item in runtime.production_resources.catalog.resources), 'LOCAL_SMOKE_SOURCE_MISSING')
    runtime.root.show(); runtime.assert_zero_warnings()
    coordinator, resources = runtime.processing_coordinator, runtime.local_resources_controller
    _require(coordinator.selectLocal(), 'LOCAL_SMOKE_LOCAL_REFUSED')
    _wait(lambda: coordinator.snapshot.persistence_status.value == 'saved', deadline)
    _require(resources.importAndEnable(str(resources_dir)), 'LOCAL_SMOKE_IMPORT_REFUSED')
    _wait(lambda: not resources.busy, deadline)
    snapshot = coordinator.snapshot
    _require(resources.phase == 'READY' and snapshot.mode is ProcessingMode.LOCAL
             and snapshot.local_readiness is LocalReadiness.READY and bool(snapshot.engine_fingerprint),
             'LOCAL_SMOKE_NOT_READY')


class _RequestObserver:
    """Content-free facts at the actual per-instance LocalNamingRequest boundary."""
    def __init__(self, source, container, case):
        self.source, self.container, self.case = source, container, case
        self.records = []
        self._lock = threading.Lock()

    def attach(self, service):
        from .inference_request import LocalNamingRequest, LocalInferenceResult, prepare_request
        original = service.infer
        @wraps(original)
        def observed(request, *args, **kwargs):
            _require(type(request) is LocalNamingRequest and len(self.records) < 8,
                     'WORKFLOW_REQUEST_INVALID')
            prepared = prepare_request(request)
            paths = {str(self.source).encode('utf-8'), self.source.as_posix().encode('utf-8')}
            _require(not any(path.decode('utf-8') in request.text for path in paths),
                     'WORKFLOW_SOURCE_ENTERED_REQUEST')
            _require(all(not any(path in member.data for path in paths)
                         and self.container not in member.data for member in prepared.members),
                     'WORKFLOW_SOURCE_ENTERED_REQUEST')
            _require(all(not any(path.decode('utf-8') in p.provenance for path in paths)
                         for p in request.visuals), 'WORKFLOW_SOURCE_ENTERED_REQUEST')
            facts = dict(case=self.case, language=request.locale, naming_mode=request.naming_mode,
                text_bytes=len(request.text.encode('utf-8')), text_present=bool(request.text.strip()),
                visual_count=len(request.visuals), source_path_absent=True, full_container_absent=True,
                visuals=[dict(kind=p.kind, mime_type=p.mime_type, source_index=p.source_index,
                              width=p.width, height=p.height, byte_size=p.byte_size) for p in request.visuals])
            with self._lock: self.records.append(facts)
            try:
                outcome = original(request, *args, **kwargs)
            except BaseException:
                with self._lock: facts.update(response_success=False, response_error='INFERENCE_RAISED')
                raise
            _require(type(outcome) is LocalInferenceResult, 'WORKFLOW_RESPONSE_INVALID')
            with self._lock:
                facts.update(response_success=outcome.success is True,
                             response_error=outcome.error if outcome.error in _DependencyObserver._SERVICE_ERRORS else None)
            return outcome
        service.infer = observed
        self.service, self.original, self.observed = service, original, observed

    def detach(self):
        if self.service.infer is self.observed: self.service.infer = self.original

    def require_success(self):
        _require(len(self.records) == 1 and self.records[0].get('response_success') is True,
                 'WORKFLOW_INFERENCE_FAILED')

    def write_snapshot(self, data_dir):
        """Fresh fixed-case facts only, including failures; never report adoption.

        This exclusive file is inside the runner's already-proved fresh root.
        On timeout it is a snapshot, not a claim that the live worker stopped.
        """
        with self._lock:
            encoded = json.dumps(dict(workflow=self.case, requests=self.records,
                                      semantic_quality='not_judged'), ensure_ascii=False).encode('utf-8')
        with (data_dir/'synthetic-request-facts.json').open('xb') as handle:
            _require(handle.write(encoded) == len(encoded), 'WORKFLOW_FACTS_WRITE_FAILED')


def _exercise_media(runtime, resources_dir, data_dir, deadline, workflow):
    from .synthetic_smoke_media import create_scan_pdf, create_video
    _prepare_local(runtime, resources_dir, data_dir, deadline)
    source = (create_scan_pdf if workflow == 'scan-pdf' else create_video)(data_dir)
    original = _digest(source)
    observer = _RequestObserver(source, source.read_bytes(), workflow)
    observer.attach(runtime.local_inference_service)
    batch = runtime.batch_controller
    try:
        batch.setNamingMode('smart'); batch.setNamingLanguage('zh-HK')
        before = set(batch.task_ids); batch.add_files([str(source)])
        added = set(batch.task_ids)-before
        _require(len(added) == 1, 'WORKFLOW_MEDIA_BATCH_REFUSED')
        task = added.pop()
        _wait(lambda: batch.task_snapshot(task)['status'] not in ('pending', 'analyzing'), deadline)
        row = batch.task_snapshot(task)
        _require(row['status'] == 'review_pending' and not row.get('validationError')
                 and _valid_name(row['suggestedName'], source.suffix), 'WORKFLOW_MEDIA_SUGGESTION_INVALID')
        observer.require_success()
        facts = observer.records[0]
        expected = 'rendered_scan_page' if workflow == 'scan-pdf' else 'video_keyframe'
        _require(not facts['text_present'] and facts['visual_count'] > 0
                 and all(p['kind'] == expected for p in facts['visuals']), 'WORKFLOW_MEDIA_PAYLOAD_INVALID')
        if workflow == 'scan-pdf':
            _require(facts['visual_count'] == 2 and [p['source_index'] for p in facts['visuals']] == [0, 1],
                     'WORKFLOW_PDF_PAGES_INVALID')
        else:
            _require(3 <= facts['visual_count'] <= 8, 'WORKFLOW_VIDEO_FRAMES_INVALID')
        _require(row.get('analysisCoverageType') == 'local' and source.is_file()
                 and _digest(source) == original, 'WORKFLOW_MEDIA_SOURCE_CHANGED')
        runtime.assert_zero_warnings()
        return dict(workflow=workflow, cases=[dict(case=workflow, language='zh-HK', naming_mode='smart',
            generated_filename=row['suggestedName'], terminal_state=row['status'],
            coverage=row.get('analysisCoverage'), request=facts, original_sha256=original,
            source_unchanged=True)], semantic_quality='not_judged')
    finally:
        # Restore the entry method; any in-flight call retains its observer and
        # original delegate. The runner still owns that service and cleanup.
        observer.detach()
        observer.write_snapshot(data_dir)


def run_local_workflow_smoke(*, resources_dir: Path, data_dir: Path, report_path: Path, workflow: str) -> int:
    if type(workflow) is not str or workflow not in WORKFLOWS:
        raise ValueError('LOCAL_SMOKE_WORKFLOW_INVALID')
    if workflow == 'file-workflows':
        builder, exercise = _workflow_runtime_builder, _exercise_files
    else:
        builder = build_qml_runtime
        def exercise(runtime, resources, data, deadline):
            return _exercise_media(runtime, resources, data, deadline, workflow)
    return run_local_smoke(resources_dir=resources_dir, data_dir=data_dir, report_path=report_path,
        runtime_builder=builder, exercise=exercise, timeout=1800.0 if workflow == 'file-workflows' else 1200.0,
        cleanup_timeout=45.0)

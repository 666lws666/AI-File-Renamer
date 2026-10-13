"""Explicit offline artifact diagnostic, borrowing the actual production graph.

Never a startup engine, downloader, Apply action or semantic acceptance gate.
"""
from __future__ import annotations

from functools import wraps
import math
import json
import os
from pathlib import Path
import re
import socket
import sys
import threading
import time

from src.main_qml import SmokeCredentialStore, _application
from src.models.app_config import AppConfig
from src.qml_bootstrap import RuntimeConstructionPending, build_qml_runtime
from .production_resources import PRODUCT_CATALOG_ID, load_production_resources


_RETAINED = []
_RETAINED_PATH_OWNERS = []
SYNTHETIC_NAME = 'synthetic-rain-garden.txt'
SYNTHETIC_TEXT = (
    '雨水花园维护指南\n'
    '本指南介绍一座虚构社区雨水花园的日常维护。雨水花园收集屋顶和步道的雨水，'
    '通过植物和土壤过滤径流。维护人员清理入水口的落叶与垃圾，检查排水沟是否堵塞，'
    '观察积水能否消退，移除杂草并补充覆盖物。干旱时适量浇水，避免过度施肥。'
    '记录植物健康状况和清理工作。本文不涉及真实地点、人员或日期。\n'
)


def retained_runtimes():
    """Owners retained after unproven close; never kill or delete them."""
    return tuple(_RETAINED)


class _ExceptionObserver:
    """Bounded metadata only, solely for the explicit synthetic artifact probe.

    Existing traces are saved, never invoked as callbacks. No exception text,
    arguments, frame locals or filenames are inspected. Unproved cleanup keeps
    this observer with the same retained runtime/path owners as the guard.
    """
    _MODULES = frozenset(('src.services.local_ai.inference_service',
                         'src.services.local_ai.native.stage',
                         'src.services.local_ai.native.model_stage'))
    _IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z_0-9]{0,79}', re.ASCII)
    _STAGES = frozenset(('path_input', 'sid_input', 'bytes_input', 'digest_input',
        'object_info', 'object_identity', 'object_path', 'object_security',
        'object_size', 'object_read', 'object_hash', 'object_open', 'handle_close',
        'removal_query', 'removal_unconfirmed', 'evidence_unavailable',
        'stage_not_ready', 'ownership_uncertain', 'object_disposition',
        'fixtures_input', 'stage_entropy', 'native_bindings', 'volume_query',
        'volume_unsupported', 'current_user', 'directory_create', 'file_write',
        'file_short_write', 'file_flush', 'members_input', 'member_input',
        'member_name', 'member_bounds', 'source_input', 'member_rights',
        'bundle_bounds', 'entrypoint_input', 'source_identity', 'file_short_read',
        'file_extra_bytes', 'cancelled', 'cancel_input', 'source_short_read',
        'source_extra_bytes', 'source_hash', 'source_info', 'source_path',
        'source_open', 'source_read'))

    def __init__(self):
        from .native.stage import StageError
        self.records = []
        self._stage_error = StageError
        self._lock = threading.Lock()
        self._active = False

    def _trace(self, frame, event, arg):
        module = frame.f_globals.get('__name__')
        if type(module) is not str or module not in self._MODULES:
            return None
        if event != 'exception':
            return self._trace
        with self._lock:
            if len(self.records) >= 64:
                return self._trace
            error = arg[1]
            function = frame.f_code.co_name
            name = type.__dict__['__name__'].__get__(type(error))
            if not self._IDENTIFIER.fullmatch(function) or not self._IDENTIFIER.fullmatch(name):
                return self._trace
            record = {'module': module, 'function': function, 'line': frame.f_lineno,
                      'exception_type': name}
            # Read the built-in dictionary descriptor, bypassing user properties
            # and __getattribute__. The native OSError member is also C-owned.
            attributes = BaseException.__dict__['__dict__'].__get__(error)
            safe_attributes = {key: value for key, value in dict.items(attributes)
                               if type(key) is str and key in ('winerror', 'stage')}
            winerror = safe_attributes.get('winerror')
            mro = type.__dict__['__mro__'].__get__(type(error))
            native_winerror = OSError.__dict__.get('winerror')
            if winerror is None and native_winerror is not None and any(base is OSError for base in mro):
                winerror = native_winerror.__get__(error)
            if type(winerror) is int and 0 <= winerror <= 65535:
                record['winerror'] = winerror
            if type(error) is self._stage_error:
                stage = safe_attributes.get('stage')
                if type(stage) is str and stage in self._STAGES:
                    record['stage'] = stage
            self.records.append(record)
        return self._trace

    def __enter__(self):
        self._previous_sys = sys.gettrace()
        self._previous_thread = threading.gettrace()
        self._active = True
        try:
            threading.settrace(self._trace)
            sys.settrace(self._trace)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *args):
        if self._active:
            sys.settrace(self._previous_sys)
            threading.settrace(self._previous_thread)
            self._active = False


class _DependencyObserver:
    """Observe five original per-instance delegates without altering their work.

    Real default service construction remains inert. Only explicit synthetic
    local smoke supplies this factory; no attestation/context or owner wrapper.
    """
    _DEPENDENCIES = ('stage_model_bundle', 'measure_host_capacity',
                     'require_host_capacity', 'build_launch', 'run_bounded')
    _HOST_CODES = frozenset(('HOST_UNSUPPORTED', 'HOST_INPUT_INVALID',
                            'HOST_MEASUREMENT_FAILED', 'LOCAL_MEMORY_LOW', 'LOCAL_DISK_LOW'))
    _SERVICE_ERRORS = _HOST_CODES | frozenset(('STAGE_VERIFICATION_FAILED', 'INVALID_DEADLINE',
        'BUSY', 'CLOSED', 'CANCELLED', 'STALE_CONTEXT', 'CALLBACK_FAILED', 'TIMEOUT',
        'UNSUPPORTED_RUNTIME', 'RECOVERY_REQUIRED', 'RESOURCE_VERIFICATION_FAILED',
        'STAGE_BOUNDS', 'PROFILE_FAILED', 'EXEMPTION_FAILED', 'CONTAINMENT_FAILED',
        'ENGINE_FAILED', 'CLEANUP_PENDING', 'TOKEN_VERIFICATION_FAILED', 'INVALID_RESPONSE',
        'RESOURCE_MISSING', 'INVALID_INFERENCE_RESOURCES', 'INVALID_RUNTIME_INVENTORY',
        'RESOURCE_FAILED', 'STAGE_FAILED', 'LOCAL_INFERENCE_FAILED', 'NOT_READY',
        'INVALID_REQUEST', 'INSUFFICIENT_CONTENT'))
    _PROCESS_STATUS = frozenset(('completed', 'cancelled', 'timeout', 'output_limit',
                                 'launch_error', 'cleanup_incomplete'))

    def __init__(self):
        from .native.stage import StageError
        from .host_capacity import HostCapacityError
        self._stage_error = StageError
        self._host_error = HostCapacityError
        self._lock = threading.Lock()
        self.records = []
        self.events = []
        self.service = None

    def _event(self, dependency, phase, result=None):
        with self._lock:
            if len(self.events) >= 32:
                return
            record = {'dependency': dependency, 'phase': phase}
            if dependency == 'run_bounded' and phase == 'returned':
                # Lazy operation-only imports preserve inert service creation.
                from .native.process import ProcessResult
                from .native.security import TokenEvidence
                if type(result) is ProcessResult:
                    if type(result.status) is str and result.status in self._PROCESS_STATUS:
                        record['status'] = result.status
                    if type(result.exit_code) is int and -(1 << 31) <= result.exit_code < (1 << 32):
                        record['exit_code'] = result.exit_code
                    if type(result.cleanup_complete) is bool:
                        record['cleanup_complete'] = result.cleanup_complete
                    token = result.token_evidence
                    if token is None:
                        record['token_evidence_present'] = False
                    elif type(token) is TokenEvidence:
                        record['token_evidence_present'] = True
                        if type(token.is_appcontainer) is bool:
                            record['is_appcontainer'] = token.is_appcontainer
                        if type(token.capability_count) is int and 0 <= token.capability_count <= 65535:
                            record['capability_count'] = token.capability_count
            self.events.append(record)

    def _observe(self, dependency, error):
        with self._lock:
            if len(self.records) >= 32:
                return
            name = type.__dict__['__name__'].__get__(type(error))
            if not _ExceptionObserver._IDENTIFIER.fullmatch(name):
                return
            record = {'dependency': dependency, 'exception_type': name}
            attributes = BaseException.__dict__['__dict__'].__get__(error)
            safe_attributes = {key: value for key, value in dict.items(attributes)
                               if type(key) is str and key in ('winerror', 'stage', 'code')}
            winerror = safe_attributes.get('winerror')
            mro = type.__dict__['__mro__'].__get__(type(error))
            native_winerror = OSError.__dict__.get('winerror')
            if winerror is None and native_winerror is not None and any(base is OSError for base in mro):
                winerror = native_winerror.__get__(error)
            if type(winerror) is int and 0 <= winerror <= 65535:
                record['winerror'] = winerror
            if type(error) is self._stage_error:
                stage = safe_attributes.get('stage')
                if type(stage) is str and stage in _ExceptionObserver._STAGES:
                    record['stage'] = stage
            if type(error) is self._host_error:
                code = safe_attributes.get('code')
                if type(code) is str and code in self._HOST_CODES:
                    record['code'] = code
            self.records.append(record)

    def wrap(self, dependency, original):
        if type(dependency) is not str or dependency not in self._DEPENDENCIES:
            raise ValueError('LOCAL_SMOKE_DEPENDENCY_INVALID')
        @wraps(original)
        def observed(*args, **kwargs):
            self._event(dependency, 'entered')
            try:
                result = original(*args, **kwargs)
            except BaseException as error:
                self._observe(dependency, error)
                self._event(dependency, 'raised')
                raise
            self._event(dependency, 'returned', result)
            return result
        return observed

    def service_factory(self, config):
        from .inference_service import LocalInferenceService
        service = LocalInferenceService(config)
        for name in self._DEPENDENCIES:
            setattr(service._deps, name, self.wrap(name, getattr(service._deps, name)))
        self.service = service
        return service

    def service_error(self):
        from .inference_service import LocalInferenceService, LocalServiceSnapshot
        if type(self.service) is not LocalInferenceService:
            return None
        snapshot = LocalInferenceService.snapshot(self.service)
        if (type(snapshot) is LocalServiceSnapshot and type(snapshot.error) is str
                and snapshot.error in self._SERVICE_ERRORS):
            return snapshot.error
        return None


class _SmokeIsolation:
    """Read-only preflight, held Windows parents, and fresh relative output.

    No public-source guards, path resolution/adoption or pathname report writer.
    Existing directory capabilities keep the same physical graph through writes.
    """
    def __init__(self, resources, data, report):
        from .resource_store import PreparedParentDirectories, _local_path
        from src.core import safe_file_move as native
        self.owner = None
        self.report_pin = None
        self.guard = None
        self.resources, self.data, self.report = map(_local_path, (resources, data, report))
        if (self.data.is_relative_to(self.resources) or self.resources.is_relative_to(self.data)
                or self.report.is_relative_to(self.resources) or self.report.is_relative_to(self.data)
                or self.data.parent == self.data or self.report.parent == self.report):
            raise ValueError('LOCAL_SMOKE_ISOLATION_INVALID')
        self.owner = PreparedParentDirectories()  # rejects unsupported platforms
        try:
            self.owner.pin_chain(self.resources)
            source = native._info(self.owner.directories[self.resources])
            source_id = (source.volume, source.index)
            for destination in (self.data.parent, self.report.parent):
                self.owner.pin_chain(destination)
                for ancestor in (*destination.parents, destination):
                    info = native._info(self.owner.directories[ancestor])
                    if (info.volume, info.index) == source_id:
                        raise ValueError('LOCAL_SMOKE_ISOLATION_INVALID')
            # Refuse an existing report before any mutation. Even an unsafe
            # existing leaf is never adopted or overwritten.
            try:
                handle = self.owner.child(self.owner.directories[self.report.parent], self.report.name)
            except FileNotFoundError:
                pass
            else:
                raise ValueError('LOCAL_SMOKE_REPORT_OCCUPIED')
            self.owner.assert_safe()
        except BaseException:
            self.close()
            raise

    def create_data(self):
        # Existing data is not adopted, even if empty. Probe without mutation so
        # the ordinary isolated failure report can still use its proven parent.
        try:
            self.owner.child(self.owner.directories[self.data.parent], self.data.name, directory=True)
        except FileNotFoundError:
            pass
        else:
            raise ValueError('LOCAL_SMOKE_DATA_OCCUPIED')
        self.owner.assert_safe()
        self.owner.guard(self.data.parent)  # already proved outside public source
        handle = self.owner.child(self.owner.directories[self.data.parent], self.data.name,
                                  directory=True, create=True)
        self.owner.directories[self.data] = handle
        self.owner.check_directory(handle)
        self.owner.guard(self.data)
        self.owner.assert_safe()

    def write_report(self, payload):
        from src.core import safe_file_move as native
        self.owner.assert_safe()
        self.owner.guard(self.report.parent)  # never public source
        self.report_pin = self.owner.file(self.report, writable=True, create=True)
        # Transfer the known completed fresh-file handle back to the same
        # checked close owner, rather than relying on unchecked pin.close().
        self.owner.handles.append(native._OwnedHandle(self.report_pin.handle))
        self.owner.assert_safe()
        encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')
        with self.report_pin.stream('wb') as stream:
            if stream.write(encoded) != len(encoded): raise OSError('LOCAL_SMOKE_REPORT_WRITE_FAILED')
            stream.flush()
            os.fsync(stream.fileno())
        self.owner.assert_safe()

    def close(self):
        if self.owner is None: return True
        try:
            closed = self.owner.close() is True
        except BaseException:
            closed = False
        if not closed and self not in _RETAINED_PATH_OWNERS:
            _RETAINED_PATH_OWNERS.append(self)
        if closed and self.report_pin is not None:
            self.report_pin.handle = None  # original handle was provably closed
        return closed


class _ForbiddenCredentials(SmokeCredentialStore):
    def __init__(self, guard):
        super().__init__()
        self.guard = guard

    def get(self, *args, **kwargs): return self.guard.forbid('credentials')
    def set(self, *args, **kwargs): return self.guard.forbid('credentials')
    def delete(self, *args, **kwargs): return self.guard.forbid('credentials')


class ForbiddenAccessGuard:
    """Process-local Python network/credential fences, with exact counters.

    Native model isolation remains the production service's responsibility;
    these counters are not system-wide traffic evidence.
    """
    def __init__(self):
        self.counts = {'network': 0, 'credentials': 0, 'cloud': 0}
        self.credential_store = _ForbiddenCredentials(self)
        self._restore = []

    def forbid(self, category):
        self.counts[category] += 1
        raise RuntimeError('LOCAL_SMOKE_FORBIDDEN_ACCESS')

    def cloud_factory(self, *args, **kwargs): return self.forbid('cloud')

    def __enter__(self):
        import keyring
        import keyring.core
        from keyring.backends import Windows
        targets = [(socket.socket, ('connect', 'connect_ex', 'send', 'sendall', 'sendto', 'sendmsg', 'sendfile'), 'network'),
                   (socket, ('getaddrinfo', 'gethostbyname', 'gethostbyname_ex', 'gethostbyaddr',
                             'getnameinfo', 'create_connection'), 'network'),
                   (keyring, ('get_password', 'set_password', 'delete_password', 'get_credential'), 'credentials'),
                   (keyring.core, ('get_password', 'set_password', 'delete_password', 'get_credential'), 'credentials'),
                   (Windows.WinVaultKeyring, ('get_password', 'set_password', 'delete_password',
                     'get_credential', '_read_credential', '_resolve_credential', '_set_password', '_delete_password'), 'credentials'),
                   (Windows.win32cred, ('CredRead', 'CredWrite', 'CredDelete', 'CredEnumerate'), 'credentials')]
        try:
            for owner, names, category in targets:
                for name in names:
                    if hasattr(owner, name):
                        self._restore.append((owner, name, getattr(owner, name)))
                        def forbidden(*args, _category=category, **kwargs):
                            return self.forbid(_category)
                        setattr(owner, name, forbidden)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *args):
        for owner, name, original in reversed(self._restore):
            setattr(owner, name, original)
        self._restore.clear()


def _wait(predicate, deadline):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QEventLoop, QTimer
    while not predicate():
        if time.monotonic() >= deadline: raise TimeoutError('LOCAL_SMOKE_TIMEOUT')
        QApplication.processEvents()
        loop = QEventLoop()
        QTimer.singleShot(10, loop.quit)
        loop.exec()


def _exercise(runtime, resources_dir, data_dir, deadline):
    """All hashes/import/self-check stay on the existing resource worker."""
    from src.core.processing_authority import ProcessingMode, LocalReadiness
    from src.core.naming_orthography import normalize_managed_name
    product = runtime.production_resources
    if product.catalog.identity != PRODUCT_CATALOG_ID:
        raise ValueError('LOCAL_SMOKE_CATALOG_MISMATCH')
    if not resources_dir.is_dir() or resources_dir.is_relative_to(data_dir) or data_dir.is_relative_to(resources_dir):
        raise ValueError('LOCAL_SMOKE_SOURCE_INVALID')
    # Fixed public names only: the accepted manager verifies handles/size/hash,
    # never executes a source executable or reads a user-provided manifest.
    for item in product.catalog.resources:
        if not (resources_dir / item.filename).is_file():
            raise ValueError('LOCAL_SMOKE_SOURCE_MISSING')
    runtime.root.show()
    runtime.assert_zero_warnings()
    coordinator = runtime.processing_coordinator
    resources = runtime.local_resources_controller
    if not coordinator.selectLocal(): raise RuntimeError('LOCAL_SMOKE_LOCAL_REFUSED')
    _wait(lambda: coordinator.snapshot.persistence_status.value == 'saved', deadline)
    if not resources.importAndEnable(str(resources_dir)):
        raise RuntimeError('LOCAL_SMOKE_IMPORT_REFUSED')
    _wait(lambda: not resources.busy, deadline)
    snapshot = coordinator.snapshot
    if (resources.phase != 'READY' or snapshot.mode is not ProcessingMode.LOCAL
            or snapshot.local_readiness is not LocalReadiness.READY or not snapshot.engine_fingerprint):
        raise RuntimeError('LOCAL_SMOKE_NOT_READY')
    # Exercise the real packaged OpenCC resource chain, not a handwritten map.
    orthography = normalize_managed_name('雨水花园维护指南.txt', 'zh-HK', '.txt', smart=True)
    if orthography != '雨水花園維護指南.txt':
        raise RuntimeError('LOCAL_SMOKE_ORTHOGRAPHY_FAILED')
    source = data_dir / SYNTHETIC_NAME
    with source.open('x', encoding='utf-8') as handle:
        handle.write(SYNTHETIC_TEXT)
    batch = runtime.batch_controller
    batch.setNamingMode('smart')
    batch.setNamingLanguage('zh-HK')
    before = set(batch.task_ids)
    batch.add_files([str(source)])
    added = set(batch.task_ids) - before
    if len(added) != 1: raise RuntimeError('LOCAL_SMOKE_BATCH_REFUSED')
    task_id = added.pop()
    _wait(lambda: batch.task_snapshot(task_id)['status'] not in ('pending', 'analyzing'), deadline)
    row = batch.task_snapshot(task_id)
    suggestion = row['suggestedName']
    if (row['status'] != 'review_pending' or not suggestion or row.get('validationError')
            or normalize_managed_name(suggestion, 'zh-HK', '.txt', smart=True) != suggestion):
        raise RuntimeError('LOCAL_SMOKE_SUGGESTION_INVALID')
    unchanged = source.read_text(encoding='utf-8') == SYNTHETIC_TEXT
    if not unchanged: raise RuntimeError('LOCAL_SMOKE_SOURCE_CHANGED')
    runtime.assert_zero_warnings()
    return {'phase': resources.phase, 'resource_state': resources.resourceState,
            'suggestion': suggestion, 'coverage': row.get('analysisCoverage'),
            'coverage_type': row.get('analysisCoverageType'),
            'assertions': {'genuine_ready': True, 'review_pending': True,
                           'hk_orthography_resources': True, 'source_unchanged': unchanged,
                           'apply_not_executed': True, 'captured_locale': 'zh-HK'}}


def run_local_smoke(*, resources_dir: Path, data_dir: Path, report_path: Path,
                    runtime_builder=build_qml_runtime, exercise=_exercise,
                    timeout=1200.0, cleanup_timeout=45.0) -> int:
    """Finite source/artifact probe; injected tests are not a frozen gate."""
    for budget in (timeout, cleanup_timeout):
        if type(budget) not in (int, float) or not math.isfinite(budget) or budget <= 0:
            raise ValueError('LOCAL_SMOKE_DEADLINE_INVALID')
    # All path/physical isolation proofs precede Qt, data creation, runtime
    # construction and even a failure report. Parent ownership remains held.
    isolation = _SmokeIsolation(resources_dir, data_dir, report_path)
    resources_dir, data_dir, report_path = isolation.resources, isolation.data, isolation.report
    runtime = None
    guard = ForbiddenAccessGuard()
    observer = _ExceptionObserver()
    dependency_observer = _DependencyObserver()
    payload = {'status': 'failed', 'diagnostic': 'explicit-local-artifact-smoke',
               'catalog_id': PRODUCT_CATALOG_ID, 'semantic_quality': 'not_judged',
               'strict_shutdown': False, 'qml_warning_count': 0}
    paths_closed = False
    try:
        guard.__enter__()
        observer.__enter__()
        _application()
        isolation.create_data()
        product = load_production_resources(user_data_root=data_dir / 'local-ai')
        runtime = runtime_builder(live_config=AppConfig(language='zh_HK'),
            config_file=data_dir / 'settings.json', credential_store=guard.credential_store,
            usage_recorder=None, production_resources=product, trusted_local_anchor=data_dir.parent,
            local_inference_factory=dependency_observer.service_factory,
            managed_adapter_factory=guard.cloud_factory, connection_test_service=guard.cloud_factory)
        payload.update(exercise(runtime, resources_dir, data_dir, time.monotonic() + timeout))
        payload['status'] = 'ok'
    except BaseException as error:
        if isinstance(error, RuntimeConstructionPending): runtime = error.runtime
        if not isinstance(error, Exception): raise
        payload['error_type'] = type(error).__name__  # no messages/paths/keys
    finally:
        # Canonical shutdown may clear the failure when it publishes CLOSED.
        # Capture only the fixed snapshot code before that unchanged cleanup.
        payload['local_service_error'] = dependency_observer.service_error()
        if runtime is not None:
            payload['qml_warning_count'] = len(runtime.warnings)
            controller = getattr(runtime, 'local_resources_controller', None)
            if controller is not None:
                phases = {'NOT_READY', 'VERIFYING', 'TRANSFERRING', 'PREPARING', 'READY', 'AVAILABLE',
                          'FAILED', 'CANCELLED', 'PAUSED', 'CLEANUP_PENDING', 'RECOVERY_REQUIRED'}
                payload['phase'] = controller.phase if controller.phase in phases else 'NOT_READY'
                states = {'missing', 'partial', 'available', 'downloading', 'importing', 'error', 'paused', 'cancelled'}
                payload['resource_state'] = controller.resourceState if controller.resourceState in states else 'missing'
                from .resource_operation_runner import safe_error
                payload['resource_error'] = safe_error(controller.errorCode) if controller.errorCode else None
            deadline = time.monotonic() + cleanup_timeout
            try:
                _wait(lambda: runtime.cleanup(deadline=min(deadline, time.monotonic() + .02)) is True, deadline)
                payload['strict_shutdown'] = True
            except BaseException:
                payload['status'] = 'failed'
                runtime._packaged_smoke_guard = guard
                runtime._packaged_smoke_observer = observer
                _RETAINED.append(runtime)
        else:
            payload['strict_shutdown'] = True  # no runtime ownership was created
        payload['forbidden_attempts'] = dict(guard.counts)
        payload['exception_observations'] = list(observer.records)
        payload['dependency_observations'] = list(dependency_observer.records)
        payload['dependency_events'] = list(dependency_observer.events)
        if any(guard.counts.values()) or payload['qml_warning_count']:
            payload['status'] = 'failed'
        payload['report_publication'] = 'fresh-relative-file-held-parent'
        payload['report_parent_close'] = 'not_certified_by_this_report'
        try:
            isolation.write_report(payload)
        except Exception:
            payload['status'] = 'failed'  # no alternate path / overwrite retry
        finally:
            paths_closed = isolation.close()
            if paths_closed and payload['strict_shutdown']:
                guard.__exit__(None, None, None)
                observer.__exit__(None, None, None)
            else:
                isolation.guard = guard
                isolation.observer = observer
    return 0 if payload['status'] == 'ok' and payload['strict_shutdown'] and paths_closed else 2

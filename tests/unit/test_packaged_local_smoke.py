"""Injected source diagnostics only; actual frozen/model evidence belongs to root."""
import json
import socket
import sys
import threading
from types import SimpleNamespace

import pytest


_OBSERVED_DEPENDENCIES = ('stage_model_bundle', 'measure_host_capacity',
                          'require_host_capacity', 'build_launch', 'run_bounded')


@pytest.mark.parametrize('dependency', _OBSERVED_DEPENDENCIES)
@pytest.mark.parametrize('outcome', ['return', 'exception', 'interruption'])
def test_dependency_observer_forwards_once_and_preserves_result_or_exception_identity(dependency, outcome):
    from src.services.local_ai import packaged_smoke
    observer_type = getattr(packaged_smoke, '_DependencyObserver', None)
    assert observer_type is not None, 'faithful synthetic dependency observer missing'
    observer = observer_type()
    argument, keyword, result = object(), object(), object()
    error = RuntimeError('private path secret output') if outcome == 'exception' else KeyboardInterrupt('private')
    calls = []
    def original(*args, **kwargs):
        calls.append((args, kwargs))
        if outcome != 'return': raise error
        return result
    wrapped = observer.wrap(dependency, original)
    if outcome == 'return':
        assert wrapped(argument, context=keyword) is result
        assert observer.records == []
    else:
        with pytest.raises(type(error)) as captured: wrapped(argument, context=keyword)
        assert captured.value is error
        assert observer.records == [{'dependency': dependency, 'exception_type': type(error).__name__}]
    assert len(calls) == 1
    assert calls[0][0][0] is argument
    assert calls[0][1]['context'] is keyword


def test_dependency_observer_keeps_only_bounded_trusted_content_free_metadata():
    import pywintypes
    from src.services.local_ai import packaged_smoke
    from src.services.local_ai.native.stage import StageError
    from src.services.local_ai.host_capacity import HostCapacityError
    observer_type = getattr(packaged_smoke, '_DependencyObserver', None)
    assert observer_type is not None, 'faithful synthetic dependency observer missing'
    class SpoofStageError(StageError): pass
    class SpoofCapacityError(HostCapacityError): pass
    class CallbackError(Exception):
        @property
        def winerror(self): pytest.fail('arbitrary winerror property invoked')
        @property
        def stage(self): pytest.fail('arbitrary stage property invoked')
        @property
        def code(self): pytest.fail('arbitrary code property invoked')
    errors = [StageError('object_open'), StageError('private'), SpoofStageError('object_open'),
              HostCapacityError('LOCAL_MEMORY_LOW'), HostCapacityError('private'),
              SpoofCapacityError('LOCAL_DISK_LOW'), CallbackError('private'),
              pywintypes.error(5, 'private native function', 'secret content')]
    for number in (-1, 65536, True, 'secret'):
        error = RuntimeError('private')
        error.winerror = number
        errors.append(error)
    observer = observer_type()
    for error in errors:
        def original(*args, **kwargs): raise error
        with pytest.raises(type(error)):
            observer.wrap('stage_model_bundle', original)()
    assert observer.records[0]['stage'] == 'object_open'
    assert observer.records[3]['code'] == 'LOCAL_MEMORY_LOW'
    assert observer.records[7]['winerror'] == 5
    assert all('stage' not in row for row in observer.records[1:])
    assert all('code' not in row for index, row in enumerate(observer.records) if index != 3)
    assert all('winerror' not in row for index, row in enumerate(observer.records) if index != 7)
    for _ in range(80):
        with pytest.raises(RuntimeError):
            observer.wrap('run_bounded', lambda: (_ for _ in ()).throw(RuntimeError('private')))()
    assert len(observer.records) == 32
    assert all(value not in json.dumps(observer.records) for value in ('private', 'secret', 'content'))
    with pytest.raises(ValueError): observer.wrap('private_dependency', lambda: None)


def test_diagnostic_factory_constructs_real_inert_service_with_every_original_production_dependency(tmp_path, monkeypatch):
    from src.services.local_ai import packaged_smoke, inference_service
    from src.services.local_ai.production_resources import load_production_resources
    observer_type = getattr(packaged_smoke, '_DependencyObserver', None)
    assert observer_type is not None, 'faithful synthetic dependency observer missing'
    product = load_production_resources(user_data_root=tmp_path / 'local-ai')
    config = inference_service.LocalInferenceConfig(product.resource_root, product.runtime_root,
                                                   product.state_root, product.catalog)
    originals, constructor_calls = [], []
    original_dependencies = inference_service._production_dependencies
    original_init = inference_service.LocalInferenceService.__init__
    def capture_dependencies():
        dependencies = original_dependencies()
        originals.append(dict(vars(dependencies)))
        return dependencies
    def capture_init(service, *args, **kwargs):
        constructor_calls.append((args, kwargs))
        original_init(service, *args, **kwargs)
    monkeypatch.setattr(inference_service, '_production_dependencies', capture_dependencies)
    monkeypatch.setattr(inference_service.LocalInferenceService, '__init__', capture_init)
    observer = observer_type()
    service = observer.service_factory(config)
    assert constructor_calls == [((config,), {})], 'real constructor must receive no dependency replacement'
    assert len(originals) == 1
    assert type(service) is inference_service.LocalInferenceService
    assert service._config is config
    assert service.snapshot().phase == 'NOT_READY'
    assert not service._operation.locked()
    assert not service._shutdown.is_set()
    assert service._owner is None and service._journal is None and service._journal_context is None
    assert observer.records == []
    for name, original in originals[0].items():
        if name in _OBSERVED_DEPENDENCIES:
            assert getattr(service._deps, name).__wrapped__ is original
        else:
            assert getattr(service._deps, name) is original


@pytest.mark.parametrize('fail', [False, True])
def test_explicit_local_smoke_passes_factory_and_publishes_actual_capacity_exception(tmp_path, fail):
    from src.services.local_ai.packaged_smoke import run_local_smoke
    from src.services.local_ai.inference_service import LocalInferenceConfig, LocalInferenceService
    from src.services.local_ai.host_capacity import HostCapacity
    (tmp_path / 'public').mkdir()
    report = tmp_path / 'report.json'
    captured = {}
    runtime = SimpleNamespace(warnings=[], cleanup=lambda **kwargs: True)
    def builder(**kwargs):
        assert 'local_inference_factory' in kwargs, 'explicit synthetic diagnostic lacks original-dependency factory'
        product = kwargs['production_resources']
        config = LocalInferenceConfig(product.resource_root, product.runtime_root, product.state_root, product.catalog)
        captured['service'] = kwargs['local_inference_factory'](config)
        assert type(captured['service']) is LocalInferenceService
        return runtime
    def exercise(*args):
        memory = (1 if fail else 6) * 1024**3
        captured['service']._deps.require_host_capacity(HostCapacity(memory, memory, 1024**3), staging_bytes=0)
        return {}
    result = run_local_smoke(resources_dir=tmp_path / 'public', data_dir=tmp_path / 'data',
                            report_path=report, runtime_builder=builder, exercise=exercise)
    payload = json.loads(report.read_text(encoding='utf-8'))
    assert result == (2 if fail else 0)
    assert payload['dependency_observations'] == ([{'dependency': 'require_host_capacity',
        'exception_type': 'HostCapacityError', 'code': 'LOCAL_MEMORY_LOW'}] if fail else [])
    assert 'dependency_events' in payload, 'synthetic report lacks dependency phase events'
    assert payload['dependency_events'] == [{'dependency': 'require_host_capacity', 'phase': 'entered'},
        {'dependency': 'require_host_capacity', 'phase': 'raised' if fail else 'returned'}]
    assert payload['local_service_error'] is None
    assert payload['strict_shutdown'] is True
    assert payload['forbidden_attempts'] == {'network': 0, 'credentials': 0, 'cloud': 0}


def test_normal_and_fast_smoke_never_construct_diagnostic_dependency_observer(tmp_path, monkeypatch):
    from src import main_qml
    from src.services.local_ai import packaged_smoke
    observer_type = getattr(packaged_smoke, '_DependencyObserver', None)
    assert observer_type is not None, 'faithful synthetic dependency observer missing'
    monkeypatch.setattr(packaged_smoke, '_DependencyObserver', lambda: pytest.fail('diagnostic factory outside explicit local smoke'))
    monkeypatch.setattr(main_qml, 'run_application', lambda **kwargs: 3)
    monkeypatch.setattr(main_qml, 'run_smoke_test', lambda **kwargs: 4)
    assert main_qml.main([]) == 3
    assert main_qml.main(['--smoke-test', '--data-dir', str(tmp_path / 'fast'),
                          '--report', str(tmp_path / 'fast.json')]) == 4


@pytest.mark.parametrize('dependency', _OBSERVED_DEPENDENCIES)
def test_dependency_observer_has_bounded_fixed_enter_return_and_raise_events(dependency):
    from src.services.local_ai.packaged_smoke import _DependencyObserver
    observer = _DependencyObserver()
    assert hasattr(observer, 'events'), 'dependency phase observation missing'
    result = object()
    assert observer.wrap(dependency, lambda: result)() is result
    with pytest.raises(RuntimeError):
        observer.wrap(dependency, lambda: (_ for _ in ()).throw(RuntimeError('private')))()
    assert observer.events == [{'dependency': dependency, 'phase': phase}
                               for phase in ('entered', 'returned', 'entered', 'raised')]
    for _ in range(80): observer.wrap(dependency, lambda: result)()
    assert len(observer.events) == 32
    assert 'private' not in json.dumps(observer.events)


def test_dependency_return_observes_only_exact_trusted_process_and_token_metadata():
    from src.services.local_ai.packaged_smoke import _DependencyObserver
    from src.services.local_ai.native.process import ProcessResult
    from src.services.local_ai.native.security import TokenEvidence
    observer = _DependencyObserver()
    assert hasattr(observer, 'events'), 'dependency phase observation missing'
    result = ProcessResult('completed', 0xC0000005, b'private prompt/model output', b'secret path',
                           1234, True, 1.25, token_evidence=TokenEvidence('private SID', True, 0))
    assert observer.wrap('run_bounded', lambda: result)() is result
    assert observer.events[-1] == {'dependency': 'run_bounded', 'phase': 'returned',
        'status': 'completed', 'exit_code': 0xC0000005, 'cleanup_complete': True,
        'token_evidence_present': True, 'is_appcontainer': True, 'capability_count': 0}
    assert all(value not in json.dumps(observer.events) for value in ('private', 'secret', '1234', '1.25'))
    # Other delegates never inspect returned objects, even this exact dataclass.
    assert observer.wrap('build_launch', lambda: result)() is result
    assert observer.events[-1] == {'dependency': 'build_launch', 'phase': 'returned'}


@pytest.mark.parametrize('case', ['spoof_process', 'spoof_token', 'invalid_fields', 'absent_token'])
def test_dependency_return_rejects_properties_subclasses_and_unsafe_values(case):
    from src.services.local_ai.packaged_smoke import _DependencyObserver
    from src.services.local_ai.native.process import ProcessResult
    from src.services.local_ai.native.security import TokenEvidence
    observer = _DependencyObserver()
    assert hasattr(observer, 'events'), 'dependency phase observation missing'
    class SpoofProcessResult(ProcessResult):
        @property
        def status(self): pytest.fail('untrusted process result property read')
    class SpoofTokenEvidence(TokenEvidence):
        @property
        def is_appcontainer(self): pytest.fail('untrusted token property read')
    if case == 'spoof_process':
        result = object.__new__(SpoofProcessResult)
        expected = {}
    elif case == 'spoof_token':
        result = ProcessResult('completed', 1, b'private', b'secret', None, False, 0,
                               token_evidence=object.__new__(SpoofTokenEvidence))
        expected = {'status': 'completed', 'exit_code': 1, 'cleanup_complete': False}
    elif case == 'invalid_fields':
        result = ProcessResult('private status', True, b'private', b'secret', None, 'private', 0,
                               token_evidence=TokenEvidence('private SID', 'secret', True))
        expected = {'token_evidence_present': True}
    else:
        result = ProcessResult('launch_error', -2147483648, b'private', b'secret', None, True, 0)
        expected = {'status': 'launch_error', 'exit_code': -2147483648,
                    'cleanup_complete': True, 'token_evidence_present': False}
    assert observer.wrap('run_bounded', lambda: result)() is result
    assert observer.events[-1] == {'dependency': 'run_bounded', 'phase': 'returned', **expected}
    assert 'private' not in json.dumps(observer.events)
    assert 'secret' not in json.dumps(observer.events)


def test_diagnostic_service_error_uses_exact_service_snapshot_and_fixed_allowlist(tmp_path):
    from src.services.local_ai.packaged_smoke import _DependencyObserver
    from src.services.local_ai.inference_service import LocalInferenceConfig
    from src.services.local_ai.production_resources import load_production_resources
    observer = _DependencyObserver()
    assert hasattr(observer, 'service_error'), 'safe local service error projection missing'
    assert observer.service_error() is None
    product = load_production_resources(user_data_root=tmp_path / 'local-ai')
    service = observer.service_factory(LocalInferenceConfig(product.resource_root, product.runtime_root,
                                                           product.state_root, product.catalog))
    service._publish('NOT_READY', 'ENGINE_FAILED')
    # Never invoke an arbitrary instance-supplied snapshot callback.
    service.snapshot = lambda: pytest.fail('arbitrary snapshot callback invoked')
    assert observer.service_error() == 'ENGINE_FAILED'
    service._error = 'private api_key=secret'
    assert observer.service_error() is None
    class SpoofService:
        @property
        def snapshot(self): pytest.fail('untrusted snapshot property read')
    observer.service = SpoofService()
    assert observer.service_error() is None


def test_synthetic_report_captures_service_error_before_shutdown_clears_snapshot(tmp_path):
    from src.services.local_ai.packaged_smoke import run_local_smoke
    from src.services.local_ai.inference_service import LocalInferenceConfig
    (tmp_path / 'public').mkdir()
    report = tmp_path / 'report.json'
    captured = {}
    def cleanup(**kwargs):
        captured['service']._publish('CLOSED')
        return True
    runtime = SimpleNamespace(warnings=[], cleanup=cleanup)
    def builder(**kwargs):
        product = kwargs['production_resources']
        captured['service'] = kwargs['local_inference_factory'](LocalInferenceConfig(
            product.resource_root, product.runtime_root, product.state_root, product.catalog))
        captured['service']._publish('NOT_READY', 'LOCAL_INFERENCE_FAILED')
        return runtime
    def exercise(*args): raise RuntimeError('private error')
    assert run_local_smoke(resources_dir=tmp_path / 'public', data_dir=tmp_path / 'data',
                          report_path=report, runtime_builder=builder, exercise=exercise) == 2
    payload = json.loads(report.read_text(encoding='utf-8'))
    assert captured['service'].snapshot().error is None
    assert payload['local_service_error'] == 'LOCAL_INFERENCE_FAILED'
    assert payload['strict_shutdown'] is True
    assert 'private' not in report.read_text(encoding='utf-8')


def _observed_raise(module, error):
    namespace = {'__name__': module, 'error': error}
    exec(compile('def probe():\n    raise error\n', 'private-fixture-path', 'exec'), namespace)
    return namespace['probe']


@pytest.mark.parametrize('module', [
    'src.services.local_ai.inference_service',
    'src.services.local_ai.native.stage',
    'src.services.local_ai.native.model_stage',
])
def test_exception_observer_records_only_bounded_safe_metadata(module):
    from src.services.local_ai import packaged_smoke
    observer_type = getattr(packaged_smoke, '_ExceptionObserver', None)
    assert observer_type is not None, 'bounded synthetic exception observer missing'
    error = RuntimeError('private-path api_key=secret synthetic document model output')
    error.winerror = 5
    with observer_type() as observer:
        for _ in range(80):
            with pytest.raises(RuntimeError): _observed_raise(module, error)()
    assert len(observer.records) == 64
    assert observer.records[0] == {'module': module, 'function': 'probe', 'line': 2,
                                   'exception_type': 'RuntimeError', 'winerror': 5}
    encoded = json.dumps(observer.records)
    assert all(value not in encoded for value in ('private', 'secret', 'document', 'model output'))


@pytest.mark.parametrize('module', ['untrusted.src.services.local_ai.native.stage',
                                  'src.services.local_ai.native.stage.spoof', 'untrusted'])
def test_exception_observer_rejects_nonexact_module_names(module):
    from src.services.local_ai import packaged_smoke
    observer_type = getattr(packaged_smoke, '_ExceptionObserver', None)
    assert observer_type is not None, 'bounded synthetic exception observer missing'
    with observer_type() as observer:
        with pytest.raises(RuntimeError): _observed_raise(module, RuntimeError('private'))()
    assert observer.records == []


def test_exception_observer_accepts_only_fixed_trusted_stage_and_plain_numeric_winerror():
    from src.services.local_ai import packaged_smoke
    from src.services.local_ai.native.stage import StageError
    observer_type = getattr(packaged_smoke, '_ExceptionObserver', None)
    assert observer_type is not None, 'bounded synthetic exception observer missing'
    class SpoofStageError(StageError): pass
    class CallbackError(Exception):
        @property
        def winerror(self): pytest.fail('observer called arbitrary property')
    errors = [StageError('object_open'), StageError('private_path'),
              SpoofStageError('object_open'), CallbackError('private')]
    for winerror in (-1, 65536, True, 'private'):
        error = RuntimeError('private')
        error.winerror = winerror
        errors.append(error)
    with observer_type() as observer:
        for error in errors:
            with pytest.raises(Exception):
                _observed_raise('src.services.local_ai.native.stage', error)()
    assert observer.records[0]['stage'] == 'object_open'
    assert all('stage' not in row for row in observer.records[1:])
    assert all('winerror' not in row for row in observer.records)
    assert 'private' not in json.dumps(observer.records)


def test_exception_observer_reads_actual_windows_error_without_native_calls():
    import pywintypes
    from src.services.local_ai.packaged_smoke import _ExceptionObserver
    error = pywintypes.error(5, 'private native function', 'secret private path')
    with _ExceptionObserver() as observer:
        with pytest.raises(pywintypes.error):
            _observed_raise('src.services.local_ai.native.stage', error)()
    assert observer.records == [{'module': 'src.services.local_ai.native.stage',
        'function': 'probe', 'line': 2, 'exception_type': 'error', 'winerror': 5}]


@pytest.mark.parametrize('fail', [False, True])
def test_exception_observer_restores_previous_sys_and_thread_traces(fail):
    from src.services.local_ai import packaged_smoke
    observer_type = getattr(packaged_smoke, '_ExceptionObserver', None)
    assert observer_type is not None, 'bounded synthetic exception observer missing'
    original_sys, original_thread = sys.gettrace(), threading.gettrace()
    def previous_sys(frame, event, arg): return previous_sys
    def previous_thread(frame, event, arg): return previous_thread
    sys.settrace(previous_sys)
    threading.settrace(previous_thread)
    try:
        try:
            with observer_type() as observer:
                def worker():
                    with pytest.raises(RuntimeError):
                        _observed_raise('src.services.local_ai.inference_service', RuntimeError('private'))()
                thread = threading.Thread(target=worker)
                thread.start()
                thread.join()
                if fail: raise RuntimeError('private')
        except RuntimeError:
            assert fail
        assert sys.gettrace() is previous_sys
        assert threading.gettrace() is previous_thread
        assert len(observer.records) == 1
    finally:
        sys.settrace(original_sys)
        threading.settrace(original_thread)


@pytest.mark.parametrize('fail', [False, True])
def test_synthetic_report_includes_observer_without_changing_failure_or_guards(tmp_path, fail):
    from src.services.local_ai.packaged_smoke import run_local_smoke
    runtime = SimpleNamespace(warnings=[], cleanup=lambda **kwargs: True)
    (tmp_path / 'public').mkdir()
    report = tmp_path / 'report.json'
    previous_sys, previous_thread = sys.gettrace(), threading.gettrace()
    def exercise(*args):
        probe = _observed_raise('src.services.local_ai.native.model_stage', RuntimeError('private secret'))
        if fail: probe()
        with pytest.raises(RuntimeError): probe()
        return {}
    result = run_local_smoke(resources_dir=tmp_path / 'public', data_dir=tmp_path / 'data',
                            report_path=report, runtime_builder=lambda **kwargs: runtime, exercise=exercise)
    payload = json.loads(report.read_text(encoding='utf-8'))
    assert 'exception_observations' in payload, 'synthetic diagnostic report lacks observer record'
    assert len(payload['exception_observations']) == 1
    assert result == (2 if fail else 0)
    assert payload['status'] == ('failed' if fail else 'ok')
    assert payload['strict_shutdown'] is True
    assert payload['forbidden_attempts'] == {'network': 0, 'credentials': 0, 'cloud': 0}
    assert sys.gettrace() is previous_sys
    assert threading.gettrace() is previous_thread
    assert 'private' not in report.read_text(encoding='utf-8')


@pytest.mark.parametrize('argv', [
    ['--local-smoke-resources', 'public'],
    ['--smoke-test', '--local-smoke-resources', 'public'],
    ['--version', '--local-smoke-resources', 'public'],
    ['--smoke-test', '--data-dir', 'data', '--local-smoke-resources', 'public'],
])
def test_local_argument_requires_explicit_smoke_data_and_report(argv, monkeypatch):
    from src import main_qml
    monkeypatch.setattr(main_qml, 'run_application', lambda: pytest.fail('normal startup entered'))
    with pytest.raises(SystemExit):
        main_qml.main(argv)


def test_explicit_local_argument_dispatches_only_diagnostic(tmp_path, monkeypatch):
    from src import main_qml
    from src.services.local_ai import packaged_smoke
    captured = {}
    monkeypatch.setattr(packaged_smoke, 'run_local_smoke', lambda **kwargs: captured.update(kwargs) or 7)
    monkeypatch.setattr(main_qml, 'run_smoke_test', lambda **kwargs: pytest.fail('fast smoke entered'))
    assert main_qml.main(['--smoke-test', '--data-dir', str(tmp_path / 'data'), '--report', str(tmp_path / 'report'),
                          '--local-smoke-resources', str(tmp_path / 'public')]) == 7
    assert captured['resources_dir'] == tmp_path / 'public'


def test_process_guards_block_restore_and_count():
    from src.services.local_ai.packaged_smoke import ForbiddenAccessGuard
    old = socket.getaddrinfo
    guard = ForbiddenAccessGuard()
    with guard:
        with pytest.raises(RuntimeError): socket.getaddrinfo('example.invalid', 443)
        with pytest.raises(RuntimeError): guard.cloud_factory()
        with pytest.raises(RuntimeError): guard.credential_store.get('x', 'y')
    assert socket.getaddrinfo is old
    assert guard.counts == {'network': 1, 'credentials': 1, 'cloud': 1}


def test_guard_blocks_socket_send_even_for_preexisting_socket():
    from src.services.local_ai.packaged_smoke import ForbiddenAccessGuard
    guard = ForbiddenAccessGuard()
    with socket.socket() as sock:
        with guard:
            with pytest.raises(RuntimeError): sock.send(b'synthetic')
            with pytest.raises(RuntimeError): sock.sendall(b'synthetic')
    assert guard.counts['network'] == 2


def test_failure_report_cleanup_retains_owner_without_private_error(tmp_path):
    from src.services.local_ai.packaged_smoke import run_local_smoke, retained_runtimes
    runtime = SimpleNamespace(warnings=[], cleanup=lambda **kwargs: False)
    previous_sys, previous_thread = sys.gettrace(), threading.gettrace()
    def builder(**kwargs): return runtime
    def exercise(*args, **kwargs): raise RuntimeError('private-path api_key=secret')
    report = tmp_path / 'report.json'
    (tmp_path / 'public').mkdir()
    assert run_local_smoke(resources_dir=tmp_path / 'public', data_dir=tmp_path / 'data', report_path=report,
                           runtime_builder=builder, exercise=exercise, timeout=.05, cleanup_timeout=.02) != 0
    payload = json.loads(report.read_text(encoding='utf-8'))
    assert payload['strict_shutdown'] is False
    assert payload['status'] == 'failed'
    assert runtime in retained_runtimes()
    assert sys.gettrace() == runtime._packaged_smoke_observer._trace
    assert threading.gettrace() == runtime._packaged_smoke_observer._trace
    assert 'secret' not in report.read_text(encoding='utf-8')
    # This injected fake has no worker/native owner. Undo only its retained guard
    # so subsequent source tests keep the outer pytest guard intact.
    runtime._packaged_smoke_guard.__exit__(None, None, None)
    runtime._packaged_smoke_observer.__exit__(None, None, None)
    assert sys.gettrace() is previous_sys
    assert threading.gettrace() is previous_thread


def test_nonempty_injected_result_never_claims_semantic_pass(tmp_path):
    from src.services.local_ai.packaged_smoke import run_local_smoke
    runtime = SimpleNamespace(warnings=[], cleanup=lambda **kwargs: True)
    report = tmp_path / 'report.json'
    (tmp_path / 'public').mkdir()
    def exercise(*args, **kwargs): return {'suggestion': '雨水花園維護指南.txt', 'coverage': 'text', 'assertions': {'review_pending': True}}
    assert run_local_smoke(resources_dir=tmp_path / 'public', data_dir=tmp_path / 'data', report_path=report,
                           runtime_builder=lambda **kwargs: runtime, exercise=exercise) == 0
    payload = json.loads(report.read_text(encoding='utf-8'))
    assert payload['semantic_quality'] == 'not_judged'
    assert payload['strict_shutdown'] is True
    assert payload['forbidden_attempts'] == {'network': 0, 'credentials': 0, 'cloud': 0}


def test_real_exercise_captures_hk_language_without_apply(tmp_path):
    import time
    from src.services.local_ai.packaged_smoke import _exercise
    from src.services.local_ai.production_resources import load_production_resources
    from src.core.processing_authority import ProcessingMode, LocalReadiness
    data = tmp_path / 'data'
    public = tmp_path / 'public'
    data.mkdir()
    public.mkdir()
    product = load_production_resources(user_data_root=data / 'local-ai')
    for item in product.catalog.resources: (public / item.filename).touch()
    class Batch:
        def setNamingMode(self, value): assert value == 'smart'
        def setNamingLanguage(self, value): self.language = value
        @property
        def task_ids(self): return ('synthetic',) if hasattr(self, 'path') else ()
        def add_files(self, paths):
            assert self.language == 'zh-HK'
            self.path = paths[0]
        def task_snapshot(self, task_id):
            return {'status': 'review_pending', 'suggestedName': '雨水花園維護指南.txt',
                    'validationError': '', 'analysisCoverage': {}, 'analysisCoverageType': 'local'}
        def applyTask(self, *args): pytest.fail('Apply forbidden')
    snapshot = SimpleNamespace(mode=ProcessingMode.LOCAL, local_readiness=LocalReadiness.READY,
                               engine_fingerprint='a' * 64, persistence_status=SimpleNamespace(value='saved'))
    runtime = SimpleNamespace(production_resources=product, root=SimpleNamespace(show=lambda: None),
        assert_zero_warnings=lambda: None, processing_coordinator=SimpleNamespace(selectLocal=lambda: True, snapshot=snapshot),
        local_resources_controller=SimpleNamespace(importAndEnable=lambda source: True, busy=False, phase='READY', resourceState='available'),
        batch_controller=Batch())
    result = _exercise(runtime, public, data, time.monotonic() + 1)
    assert result['assertions']['captured_locale'] == 'zh-HK'
    assert result['assertions']['source_unchanged'] is True


def test_reused_data_refused_before_runtime_constructor(tmp_path):
    from src.services.local_ai.packaged_smoke import run_local_smoke
    data = tmp_path / 'existing'
    data.mkdir()
    (tmp_path / 'public').mkdir()
    report = tmp_path / 'report.json'
    assert run_local_smoke(resources_dir=tmp_path / 'public', data_dir=data, report_path=report,
                           runtime_builder=lambda **kwargs: pytest.fail('runtime constructed')) == 2
    assert json.loads(report.read_text(encoding='utf-8'))['strict_shutdown'] is True


def test_report_cannot_mutate_public_source_folder(tmp_path):
    from src.services.local_ai.packaged_smoke import run_local_smoke
    public = tmp_path / 'public'
    public.mkdir()
    report = public / 'report.json'
    with pytest.raises(ValueError):
        run_local_smoke(resources_dir=public, data_dir=tmp_path / 'data', report_path=report,
                        runtime_builder=lambda **kwargs: pytest.fail('runtime constructed'))
    assert not report.exists()


def _inventory(directory):
    return {str(p.relative_to(directory)): p.read_bytes() if p.is_file() else None
            for p in directory.rglob('*')}


@pytest.mark.parametrize('case', ['descendant_data', 'report_traversal', 'occupied_report'])
def test_preflight_no_write_no_builder_for_unproved_paths(tmp_path, case):
    from src.services.local_ai.packaged_smoke import run_local_smoke
    public = tmp_path / 'public'
    public.mkdir()
    (public / 'original.txt').write_bytes(b'harmless public fixture')
    nested = public / 'existing'
    nested.mkdir()
    output = tmp_path / 'output'
    output.mkdir()
    data, report = tmp_path / 'data', output / 'report.json'
    if case == 'descendant_data': data = nested / 'fresh-data'
    if case == 'report_traversal': report = output / '..' / 'public' / 'report.json'
    if case == 'occupied_report': report.write_bytes(b'preserve report original')
    before = _inventory(public)
    called = []
    with pytest.raises((ValueError, RuntimeError)):
        run_local_smoke(resources_dir=public, data_dir=data, report_path=report,
                        runtime_builder=lambda **kwargs: called.append(True) or SimpleNamespace(
                            warnings=[], cleanup=lambda **kwargs: True),
                        exercise=lambda *args: {})
    assert called == []
    assert _inventory(public) == before
    assert not data.exists()
    if case == 'occupied_report': assert report.read_bytes() == b'preserve report original'
    else: assert not report.exists()


@pytest.mark.parametrize('role', ['data', 'report', 'source'])
def test_real_windows_junction_parent_refused_without_source_mutation(tmp_path, role):
    import os
    import subprocess
    from src.services.local_ai.packaged_smoke import run_local_smoke
    assert os.name == 'nt', 'Windows physical-isolation gate requires Windows'
    public = tmp_path / 'public'
    public.mkdir()
    (public / 'original.txt').write_bytes(b'harmless public fixture')
    alias = tmp_path / 'alias'
    result = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(alias), str(public)],
                            capture_output=True, check=False)
    assert result.returncode == 0, 'Could not create owned Windows junction fixture'
    data = (alias if role == 'data' else tmp_path) / 'fresh-data'
    report = (alias if role == 'report' else tmp_path) / 'report.json'
    before = _inventory(public)
    called = []
    with pytest.raises((ValueError, RuntimeError)):
        run_local_smoke(resources_dir=alias if role == 'source' else public, data_dir=data, report_path=report,
                        runtime_builder=lambda **kwargs: called.append(True) or SimpleNamespace(
                            warnings=[], cleanup=lambda **kwargs: True),
                        exercise=lambda *args: {})
    assert called == []
    assert _inventory(public) == before
    assert not data.exists()
    assert not report.exists()


def test_report_parent_remains_held_and_fresh_relative_until_publication(tmp_path, monkeypatch):
    from src.services.local_ai import packaged_smoke
    public = tmp_path / 'public'
    output = tmp_path / 'output'
    public.mkdir()
    output.mkdir()
    (public / 'original.txt').write_bytes(b'harmless fixture')
    original = _inventory(public)
    owners = []
    real_isolation = packaged_smoke._SmokeIsolation
    def capture(*args):
        owner = real_isolation(*args)
        owners.append(owner)
        return owner
    monkeypatch.setattr(packaged_smoke, '_SmokeIsolation', capture)
    def exercise(*args):
        with pytest.raises(OSError): output.rename(tmp_path / 'redirected')
        assert not (output / 'report.json').exists()
        return {'suggestion': '雨水花園維護指南.txt'}
    assert packaged_smoke.run_local_smoke(resources_dir=public, data_dir=tmp_path / 'data',
        report_path=output / 'report.json', runtime_builder=lambda **kwargs: SimpleNamespace(
            warnings=[], cleanup=lambda **kwargs: True), exercise=exercise) == 0
    assert _inventory(public) == original
    assert owners[0].owner.idle is True
    assert all(record.state == 'closed' for record in owners[0].owner.handles)
    payload = json.loads((output / 'report.json').read_text(encoding='utf-8'))
    assert payload['report_publication'] == 'fresh-relative-file-held-parent'
    assert payload['report_parent_close'] == 'not_certified_by_this_report'


def test_late_report_collision_never_overwrites_or_falls_back(tmp_path):
    from src.services.local_ai.packaged_smoke import run_local_smoke
    public = tmp_path / 'public'
    public.mkdir()
    original = _inventory(public)
    report = tmp_path / 'report.json'
    def exercise(*args):
        report.write_bytes(b'other writer original')
        return {'suggestion': '雨水花園維護指南.txt'}
    assert run_local_smoke(resources_dir=public, data_dir=tmp_path / 'data', report_path=report,
        runtime_builder=lambda **kwargs: SimpleNamespace(warnings=[], cleanup=lambda **kwargs: True),
        exercise=exercise) == 2
    assert report.read_bytes() == b'other writer original'
    assert _inventory(public) == original
    assert set(tmp_path.glob('*.json')) == {report}


def test_unsupported_physical_platform_refused_before_any_write(tmp_path, monkeypatch):
    from src.services.local_ai.packaged_smoke import run_local_smoke
    from src.core import safe_file_move
    monkeypatch.setattr(safe_file_move, '_NATIVE_AVAILABLE', False)
    public = tmp_path / 'public'
    public.mkdir()
    original = _inventory(public)
    data, report = tmp_path / 'data', tmp_path / 'report.json'
    with pytest.raises(RuntimeError):
        run_local_smoke(resources_dir=public, data_dir=data, report_path=report,
                        runtime_builder=lambda **kwargs: pytest.fail('runtime constructed'))
    assert _inventory(public) == original
    assert not data.exists()
    assert not report.exists()


def test_uncertain_parent_close_returns_nonzero_and_retains_guard_owner(tmp_path, monkeypatch):
    from src.services.local_ai import packaged_smoke
    public = tmp_path / 'public'
    public.mkdir()
    previous_sys, previous_thread = sys.gettrace(), threading.gettrace()
    owners, real_closes = [], []
    real_isolation = packaged_smoke._SmokeIsolation
    def capture(*args):
        isolation = real_isolation(*args)
        owners.append(isolation)
        real_closes.append(isolation.owner.close)
        isolation.owner.close = lambda: False
        return isolation
    monkeypatch.setattr(packaged_smoke, '_SmokeIsolation', capture)
    result = packaged_smoke.run_local_smoke(resources_dir=public, data_dir=tmp_path / 'data',
        report_path=tmp_path / 'report.json', runtime_builder=lambda **kwargs: SimpleNamespace(
            warnings=[], cleanup=lambda **kwargs: True), exercise=lambda *args: {})
    assert result == 2
    assert owners[0] in packaged_smoke._RETAINED_PATH_OWNERS
    assert owners[0].guard is not None
    assert sys.gettrace() == owners[0].observer._trace
    assert threading.gettrace() == owners[0].observer._trace
    # No native close ambiguity was induced: this is the explicit false-return
    # seam over an owned harmless fixture. Restore and prove genuine cleanup.
    owners[0].owner.close = real_closes[0]
    assert owners[0].close() is True
    owners[0].guard.__exit__(None, None, None)
    owners[0].observer.__exit__(None, None, None)
    assert sys.gettrace() is previous_sys
    assert threading.gettrace() is previous_thread


def test_interrupted_runtime_cleanup_still_closes_path_owner_and_retains_guard(tmp_path, monkeypatch):
    from src.services.local_ai import packaged_smoke
    class DiagnosticStop(BaseException): pass
    public = tmp_path / 'public'
    public.mkdir()
    owners = []
    real_isolation = packaged_smoke._SmokeIsolation
    def capture(*args):
        owner = real_isolation(*args)
        owners.append(owner)
        return owner
    monkeypatch.setattr(packaged_smoke, '_SmokeIsolation', capture)
    def interrupted(**kwargs): raise DiagnosticStop()
    runtime = SimpleNamespace(warnings=[], cleanup=interrupted)
    assert packaged_smoke.run_local_smoke(resources_dir=public, data_dir=tmp_path / 'data',
        report_path=tmp_path / 'report.json', runtime_builder=lambda **kwargs: runtime,
        exercise=lambda *args: {}) == 2
    assert owners[0].owner.idle is True
    assert runtime in packaged_smoke.retained_runtimes()
    payload = json.loads((tmp_path / 'report.json').read_text(encoding='utf-8'))
    assert payload['strict_shutdown'] is False
    assert payload['status'] == 'failed'
    runtime._packaged_smoke_guard.__exit__(None, None, None)
    runtime._packaged_smoke_observer.__exit__(None, None, None)

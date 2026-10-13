"""Filename language travels in real requests, independently of UI locale."""
from dataclasses import replace
import json
import pytest
from src.core.template_model import OutputLanguage
from src.core.batch_analysis import BatchAnalysisService
from src.controllers.batch_workspace_controller import BatchWorkspaceController
from src.models.app_config import AppConfig
from tests.integration.test_batch_analysis_service import _profile, _template, _Adapter


@pytest.mark.parametrize('output,ui,expected', [('en', 'zh_CN', 'en-US'), ('zh', 'en_US', 'zh-CN'), ('zh-HK', 'en_US', 'zh-HK'), ('ja','zh_HK','ja-JP')])
def test_template_language_not_interface_language_reaches_provider(tmp_path, output, ui, expected):
    source = tmp_path / 'source.txt'
    source.write_text('safe content', encoding='utf-8')
    template = replace(_template(), output_language=OutputLanguage(output))
    adapter = _Adapter()
    service = BatchAnalysisService(profile_provider=_profile,
        credential_provider=lambda _: 'fake', adapter_factory=lambda *_: adapter,
        config_provider=lambda: AppConfig(language=ui), template_provider=lambda _: template,
        content_extractor=lambda *_: ('safe extracted content', {}))
    service(str(source), 'test')
    assert adapter.requests[0].locale == expected
    assert template.output_language.value == output


def test_explicit_override_does_not_modify_template(tmp_path):
    source = tmp_path / 'source.txt'
    source.write_text('safe content', encoding='utf-8')
    template = _template()
    adapter = _Adapter()
    service = BatchAnalysisService(profile_provider=_profile,
        credential_provider=lambda _: 'fake', adapter_factory=lambda *_: adapter,
        config_provider=lambda: AppConfig(language='en_US'), template_provider=lambda _: template,
        content_extractor=lambda *_: ('safe extracted content', {}))
    service(str(source), 'test', output_language='zh-HK')
    assert adapter.requests[0].locale == 'zh-HK'
    assert template.output_language is OutputLanguage.ZH
    with pytest.raises(ValueError):
        service(str(source), 'invalid', output_language='not-a-locale')
    assert len(adapter.requests) == 1


def test_pending_imports_and_retries_keep_per_task_language(tmp_path):
    ctrl = BatchWorkspaceController(workspace_path=tmp_path/'workspace.json', background=False)
    try:
        ctrl.configure_templates([{'id':'one','name':'One','outputLanguage':'en'}, {'id':'two','name':'Two','outputLanguage':'ja'}])
        ctrl.setNamingLanguage('zh-HK')
        first = tmp_path/'first.txt'; first.write_text('one')
        ctrl.add_files([str(first)])
        ctrl.setSelectedTemplate('two')
        ctrl.setNamingLanguage('')
        second = tmp_path/'second.txt'; second.write_text('two')
        ctrl.add_files([str(second)])
        calls = []
        def analyze(path, task_id, *, template_id=None, output_language=None, cancellation_token=None):
            calls.append((task_id, template_id, output_language))
            return 'suggestion.txt'
        ctrl.set_analyzer(analyze)
        assert [row[1:] for row in calls] == [('one','zh-HK'), ('two','ja')]
        ctrl.setNamingLanguage('en')
        ctrl.retryTask(calls[0][0])
        assert calls[-1][1:] == ('one','zh-HK')
        with pytest.raises(ValueError):
            ctrl.setNamingLanguage('invalid')
        assert first.read_text() == 'one' and second.read_text() == 'two'
    finally:
        ctrl.close()


def test_legacy_task_choices_are_persisted_before_first_analysis_and_survive_retry(tmp_path):
    workspace = tmp_path / 'workspace.json'
    source = tmp_path / 'legacy.txt'
    source.write_text('legacy', encoding='utf-8')
    workspace.write_text(json.dumps({
        'schema_version': 1,
        'target_directory': '',
        'selected_template_id': '',
        'tasks': [{
            'taskId': 'legacy', 'originalName': str(source), 'suggestedName': '',
            'extension': '.txt', 'status': 'pending', 'selected': False,
            'sizeBytes': source.stat().st_size, 'modifiedNs': source.stat().st_mtime_ns,
        }],
    }), encoding='utf-8')
    calls = []

    def analyze(path, task_id, *, template_id=None, output_language=None):
        persisted = json.loads(workspace.read_text(encoding='utf-8'))['tasks'][0]
        calls.append((template_id, output_language,
                      persisted.get('templateId'), persisted.get('outputLanguage')))
        return 'suggestion.txt'

    ctrl = BatchWorkspaceController(workspace_path=workspace, background=False)
    ctrl.configure_templates([
        {'id': 'one', 'name': 'One', 'outputLanguage': 'en'},
        {'id': 'two', 'name': 'Two', 'outputLanguage': 'ja'},
    ], 'one')
    ctrl.set_analyzer(analyze)
    assert calls == [('one', 'en', 'one', 'en')]
    ctrl.close()

    restarted = BatchWorkspaceController(workspace_path=workspace, background=False)
    try:
        restarted.configure_templates([
            {'id': 'one', 'name': 'One', 'outputLanguage': 'en'},
            {'id': 'two', 'name': 'Two', 'outputLanguage': 'ja'},
        ], 'one')
        restarted.setSelectedTemplate('two')
        restarted.setNamingLanguage('zh-HK')
        restarted.set_analyzer(analyze)
        restarted.retryTask('legacy')
        assert calls[-1] == ('one', 'en', 'one', 'en')
    finally:
        restarted.close()

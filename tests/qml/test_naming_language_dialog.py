from pathlib import Path
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tests.qml.conftest import make_handle
from tests.qml.test_beginner_ui_polish import evaluate, find, QML
from src.controllers.batch_workspace_controller import BatchWorkspaceController


def click(handle, item):
    point = item.mapToScene(QPoint(int(item.width()/2), int(item.height()/2)))
    QTest.mouseClick(handle._host_view, Qt.LeftButton, Qt.NoModifier, point.toPoint())
    QApplication.processEvents()


def test_import_language_prompt_cancel_and_confirm(tmp_path):
    source = tmp_path/'local.txt'; source.write_text('untouched')
    ctrl = BatchWorkspaceController(background=False)
    ctrl.configure_templates([{'id':'general','name':'通用命名','outputLanguage':'en'}])
    handle = make_handle(QML/'BatchPage.qml', ctrl=ctrl)
    try:
        handle.root.requestImport('files', [source.as_uri()])
        QTest.qWait(100)
        dialog = find(handle, 'namingLanguageDialog')
        assert dialog.property('visible')
        assert ctrl.totalCount == 0
        assert '英文' in find(handle, 'namingLanguageChoice').property('currentText')
        click(handle, find(handle, 'namingLanguageCancel'))
        assert ctrl.totalCount == 0 and ctrl.namingLanguage == ''
        assert not dialog.property('visible')
        handle.root.requestImport('files', [source.as_uri()])
        QTest.qWait(50)
        combo = find(handle, 'namingLanguageChoice')
        evaluate(handle, combo, 'currentIndex = indexOfValue("zh-HK"); activated(currentIndex)')
        assert ctrl.namingLanguage == ''  # draft only until confirm
        click(handle, find(handle, 'namingLanguageConfirm'))
        assert ctrl.totalCount == 1 and ctrl.namingLanguage == 'zh-HK'
        assert ctrl.task_snapshot(ctrl.task_ids[0])['outputLanguage'] == 'zh-HK'
        assert source.read_text() == 'untouched'
        handle.assert_zero_warnings()
    finally:
        handle.cleanup(); ctrl.close()


def test_escape_and_outside_click_do_not_import(tmp_path):
    source = tmp_path/'local.txt'; source.write_text('safe')
    ctrl = BatchWorkspaceController(background=False)
    handle = make_handle(QML/'BatchPage.qml', ctrl=ctrl)
    try:
        handle.root.requestImport('drop', [source.as_uri()])
        QTest.qWait(100)
        QTest.keyClick(handle._host_view, Qt.Key_Escape)
        QApplication.processEvents()
        assert ctrl.totalCount == 0
        assert not find(handle, 'namingLanguageDialog').property('visible')
        assert handle.root.property('pendingImportPaths').toVariant() == []
        handle.assert_zero_warnings()
    finally:
        handle.cleanup(); ctrl.close()


def test_saved_template_language_updates_follow_template_in_runtime(tmp_path):
    from tests.qml.test_language_switching import _build_runtime
    rt = _build_runtime(tmp_path)
    try:
        templates = rt.template_controller
        batch = rt.batch_controller
        selected = batch.selectedTemplateId
        templates.beginEditTemplate(selected)
        templates.setDraftOption('outputLanguage', 'zh-HK')
        assert templates.saveDraft()
        QApplication.processEvents()
        option = next(row for row in batch.templateOptions if row['id'] == selected)
        assert option['outputLanguage'] == 'zh-HK'
        calls = []
        def fake_analyzer(path, task_id, *, output_language='', template_id=''):
            calls.append(output_language)
            return 'safe.txt'
        batch.set_analyzer(fake_analyzer)
        source = tmp_path/'synthetic.txt'; source.write_text('safe')
        batch.add_files([str(source)])
        for _ in range(50):
            if calls: break
            QTest.qWait(10)
        assert calls == ['zh-HK']
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()

from tests.unit.test_template_presets import controller


def test_hk_builtin_labels_and_user_text_preserved(tmp_path):
    ctrl = controller(tmp_path/'templates.json')
    before = (tmp_path/'templates.json').read_bytes()
    ctrl.setLocale('zh-HK')
    rows = ctrl.templates
    assert rows[0]['name'] == '通用命名（預設）'
    assert rows[1]['name'] == '簡潔標題'
    assert '檔案' in rows[1]['description']
    assert (tmp_path/'templates.json').read_bytes() == before
    ctrl.beginCreateTemplate()
    ctrl.setDraftName('我的简体名字 KEEP')
    assert ctrl.saveDraft()
    custom_id = ctrl.templates[-1]['id']
    ctrl.setLocale('en-US')
    ctrl.setLocale('zh-HK')
    assert next(r for r in ctrl.templates if r['id'] == custom_id)['name'] == '我的简体名字 KEEP'


def test_ui_locale_does_not_change_builtin_example_filename(tmp_path):
    ctrl = controller(tmp_path/'templates.json')
    examples = {row['id']: row['example'] for row in ctrl.templates}
    ctrl.setLocale('zh-HK')
    assert {row['id']: row['example'] for row in ctrl.templates} == examples

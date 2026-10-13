"""Scenario presets are additive, editable, atomic and safe across upgrades."""
import json
from dataclasses import replace

import pytest

from src.controllers.template_page_controller import TemplatePageController
from src.core.template_model import Template, OrgMode
from src.core.template_store import TemplateStore, TemplateIntegrityError
from src.core.vocabulary import VocabularyStore


def controller(path):
    return TemplatePageController(template_store=TemplateStore(path),
        vocabulary_store=VocabularyStore(), locale="zh")


def test_new_user_gets_nine_useful_named_templates(tmp_path):
    ctrl = controller(tmp_path / "templates.json")
    assert ctrl.templateCount == 9
    assert [row["name"] for row in ctrl.templates] == [
        "通用命名（默认）", "简洁标题", "票据报销", "合同往来", "项目资料",
        "学习资料", "论文文献", "照片与视频", "版本文档",
    ]
    assert all(row["description"] and row["example"] for row in ctrl.templates)
    assert len({row["pattern"] for row in ctrl.templates}) == 9


def test_legacy_upgrade_preserves_ids_order_and_custom_content(tmp_path):
    path = tmp_path / "templates.json"
    store = TemplateStore(path)
    old = store.create(Template(id="my-current-default", name="我的规则", version=7))
    user = store.create(Template(id="custom", name="工作文件"))
    ctrl = controller(path)
    assert ctrl.templates[0]["id"] == old.id
    assert ctrl.get_template_for_analysis(old.id) == old
    assert ctrl.get_template_for_analysis(user.id) == user
    assert ctrl.templateCount == 10
    first = path.read_bytes()
    assert controller(path).templateCount == 10
    assert path.read_bytes() == first


def test_deleted_and_edited_presets_are_not_reinstalled(tmp_path):
    path = tmp_path / "templates.json"
    ctrl = controller(path)
    deleted = ctrl.templates[1]["id"]
    edited = ctrl.templates[2]["id"]
    assert ctrl.deleteTemplate(deleted)
    ctrl.beginEditTemplate(edited)
    ctrl.setDraftName("我的报销规则")
    assert ctrl.saveDraft()
    reloaded = controller(path)
    assert reloaded.templateCount == 8
    assert deleted not in {row["id"] for row in reloaded.templates}
    assert reloaded.get_template_for_analysis(edited).name == "我的报销规则"


def test_install_transaction_failure_preserves_file_memory_and_ledger(tmp_path, monkeypatch):
    from src.core.template_presets import SCENARIO_PRESETS
    path = tmp_path / "templates.json"
    store = TemplateStore(path)
    old = store.create(Template(name="existing"))
    before = path.read_bytes()
    def fail_replace(*_args):
        raise OSError("disk full")
    with monkeypatch.context() as ctx:
        ctx.setattr("src.core.template_store.os.replace", fail_replace)
        with pytest.raises(OSError, match="disk full"):
            store.install_presets(tuple(p.template() for p in SCENARIO_PRESETS))
    assert store.list_all() == [old]
    assert path.read_bytes() == before
    store.install_presets(tuple(p.template() for p in SCENARIO_PRESETS))
    assert len(store.list_all()) == 9


@pytest.mark.parametrize("schema", [2, True, "1"])
def test_invalid_or_future_envelope_fails_without_rewriting(tmp_path, schema):
    path = tmp_path / "templates.json"
    path.write_text(json.dumps({"schema_version": schema, "templates": [], "installed_presets": []}))
    original = path.read_bytes()
    with pytest.raises(TemplateIntegrityError):
        TemplateStore(path)
    assert path.read_bytes() == original


def test_catalog_examples_render_with_current_engine_and_missing_values_block():
    from src.core.template_presets import SCENARIO_PRESETS
    from src.core.template_renderer import TemplateRenderer
    from src.core.naming_fields import NamingFields
    assert len(SCENARIO_PRESETS) == 8
    for preset in SCENARIO_PRESETS:
        template = preset.template()
        assert template.org_mode == OrgMode.FLAT
        result = TemplateRenderer.render(template, preset.sample_fields(template), preset.extension)
        assert result.can_apply and result.rendered_name == preset.expected_example
        assert not TemplateRenderer.render(template, NamingFields(), preset.extension).can_apply


def test_colliding_user_template_is_preserved_and_not_relabelled(tmp_path):
    from src.core.template_presets import SCENARIO_PRESETS
    path = tmp_path / 'templates.json'
    preset = SCENARIO_PRESETS[1]
    custom = replace(preset.template(), pattern='{dcTitle}')
    TemplateStore(path).create(custom)
    ctrl = controller(path)
    assert ctrl.get_template_for_analysis(custom.id) == custom
    assert ctrl.templates[0]['name'] == custom.name
    assert ctrl.templateCount == 8


def test_edited_preset_example_uses_current_fields_and_separator(tmp_path):
    from src.core.template_presets import SCENARIO_PRESETS
    from src.core.template_model import Separator
    path = tmp_path / 'templates.json'
    controller(path)
    preset = SCENARIO_PRESETS[1]
    TemplateStore(path).update(preset.id, pattern='{dcTitle}_{dcType}', separator=Separator.HYPHEN)
    ctrl = controller(path)
    row = next(row for row in ctrl.templates if row['id'] == preset.id)
    assert row['example'] == '办公用品-发票.pdf'
    assert row['description'].startswith('按当前字段规则')


def test_all_presets_flow_to_batch_without_changing_saved_choice(tmp_path):
    from src.controllers.batch_workspace_controller import BatchWorkspaceController
    ctrl = controller(tmp_path / 'templates.json')
    batch = BatchWorkspaceController(workspace_path=tmp_path / 'workspace.json', background=False)
    batch.configure_templates(ctrl.templates, ctrl.templates[0]['id'])
    assert len(batch.templateOptions) == 9
    chosen = ctrl.templates[-1]['id']
    batch.setSelectedTemplate(chosen)
    restarted = BatchWorkspaceController(workspace_path=tmp_path / 'workspace.json', background=False)
    restarted.configure_templates(controller(tmp_path / 'templates.json').templates, ctrl.templates[0]['id'])
    assert restarted.selectedTemplateId == chosen

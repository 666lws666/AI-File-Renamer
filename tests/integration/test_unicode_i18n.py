"""M8 Unicode filesystem and complete bilingual/pseudo-locale validation."""

import json
import re
from pathlib import Path

from src.controllers.batch_workspace_controller import BatchWorkspaceController
from src.utils.i18n.service import I18n


def test_unicode_filenames_apply_and_undo(tmp_path):
    names = (
        "中文资料.txt", "日本語の資料.txt", "한국어자료.txt",
        "เอกสารภาษาไทย.txt", "Tài-liệu-tiếng-Việt.txt", "📁-résumé.txt",
    )
    sources = []
    for name in names:
        source = tmp_path / name
        source.write_text(name, encoding="utf-8")
        sources.append(source)

    def analyzer(path, _task_id):
        source = Path(path)
        return f"整理-{source.stem}{source.suffix}"

    controller = BatchWorkspaceController(
        workspace_path=tmp_path / "workspace.json",
        history_path=tmp_path / "history.jsonl",
        analyzer=analyzer,
        background=False,
    )
    controller.add_files([str(path) for path in sources])
    for task_id in controller.task_ids:
        controller.applyTask(task_id)
    assert all(controller.task_snapshot(task_id)["status"] == "applied" for task_id in controller.task_ids)
    assert all((tmp_path / f"整理-{path.name}").exists() for path in sources)

    for task_id in reversed(controller.task_ids):
        controller.undoTask(task_id)
    assert all(path.exists() for path in sources)
    assert all(controller.task_snapshot(task_id)["status"] == "undone" for task_id in controller.task_ids)


def test_zh_cn_and_en_us_have_identical_complete_keysets():
    locale_dir = Path(__file__).parents[2] / "src" / "utils" / "i18n" / "locales"
    zh = json.loads((locale_dir / "zh_CN.json").read_text(encoding="utf-8"))
    en = json.loads((locale_dir / "en_US.json").read_text(encoding="utf-8"))
    assert set(zh) == set(en)
    assert all(str(value).strip() for value in zh.values())
    assert all(str(value).strip() for value in en.values())


def test_pseudo_locale_expands_text_and_preserves_placeholders():
    i18n = I18n()
    english = i18n.tr("batch.progress.completed", "en-US")
    pseudo = i18n.tr("batch.progress.completed", "en-XA")
    assert pseudo.startswith("[") and pseudo.endswith(" ~~~]")
    assert len(pseudo) > len(english) * 1.25
    assert set(re.findall(r"\{[^}]+\}", pseudo)) == set(re.findall(r"\{[^}]+\}", english))

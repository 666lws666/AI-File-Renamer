"""M8 official-entry and Windows packaging contract tests.

The Product Owner approved the QML cutover and retirement of the previous Qt
Widgets product slice. These tests keep QML as the only official entry and run
the executable smoke test separately after PyInstaller creates the onedir
artifact.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
PACKAGED_EXE = ROOT / "dist" / "Xuxia" / "Xuxia.exe"


class _FakeRoot:
    def __init__(self) -> None:
        self.shown = False

    def show(self) -> None:
        self.shown = True


class _FakeRuntime:
    def __init__(self, warnings: list[str] | None = None) -> None:
        self.root = _FakeRoot()
        self.warnings = list(warnings or [])
        self.cleaned = False

    def assert_zero_warnings(self) -> None:
        if self.warnings:
            raise AssertionError("QML warnings present")

    def cleanup(self, deadline=None) -> bool:
        self.cleaned = True
        return True


def test_candidate_smoke_uses_isolated_data_and_no_real_credentials(tmp_path):
    from src import main_qml

    captured: dict[str, object] = {}
    runtime = _FakeRuntime()

    def builder(**kwargs):
        captured.update(kwargs)
        return runtime

    report = tmp_path / "smoke.json"
    exit_code = main_qml.run_smoke_test(
        data_dir=tmp_path / "user-data",
        report_path=report,
        runtime_builder=builder,
    )

    assert exit_code == 0
    assert runtime.root.shown is True
    assert runtime.cleaned is True
    assert captured["config_file"] == tmp_path / "user-data" / "settings.json"
    assert captured["live_config"].api_key == ""
    assert isinstance(captured["credential_store"], main_qml.SmokeCredentialStore)
    assert captured["usage_recorder"] is None
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["qml_warning_count"] == 0
    assert payload["brand"] == "Xuxia"
    assert payload["media"] == {
        "image_preprocess": "ok",
        "pdf_render": "ok",
        "video_keyframes": "ok",
        "diagnostics_export": "ok",
        "windows_credential_backend": "import-ok",
    }


def test_candidate_smoke_fails_closed_on_qml_warning(tmp_path):
    from src import main_qml

    runtime = _FakeRuntime(["synthetic warning"])
    report = tmp_path / "smoke.json"

    exit_code = main_qml.run_smoke_test(
        data_dir=tmp_path / "user-data",
        report_path=report,
        runtime_builder=lambda **_: runtime,
    )

    assert exit_code != 0
    assert runtime.cleaned is True
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert "synthetic warning" not in report.read_text(encoding="utf-8")


def test_candidate_startup_failure_is_sanitized_in_user_data(monkeypatch, tmp_path):
    from src import main_qml

    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))

    def fail_runtime():
        raise RuntimeError("D:/文件AI-AGENT secret api_key=sk-test-secret")

    assert main_qml.run_application(runtime_builder=fail_runtime) == 1
    report = local_app_data / "Xuxia" / "logs" / "startup-failure.json"
    payload = json.loads(report.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["status"] == "failed"
    assert payload["error_type"] == "RuntimeError"
    assert "D:/文件AI-AGENT" not in serialized
    assert "sk-test-secret" not in serialized


def test_candidate_user_data_dir_is_not_install_dir(monkeypatch, tmp_path):
    from src.main_qml import user_data_dir

    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    assert user_data_dir() == local_app_data / "Xuxia"
    assert ROOT not in user_data_dir().parents


def test_runtime_storage_defaults_to_os_user_data(monkeypatch, tmp_path):
    from src.config import default_config_dir

    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    assert default_config_dir() == local_app_data / "Xuxia" / "config"


def test_packaging_spec_contains_runtime_assets_and_official_entry():
    spec = (ROOT / "packaging" / "xuxia.spec").read_text(encoding="utf-8")

    required = (
        "src/main.py",
        "src/ui_qml",
        "qmldir",
        "src/utils/i18n/locales",
        "vocabulary_presets_general.json",
        "nav_batch.svg",
        "nav_watch.svg",
        "nav_templates.svg",
        "nav_status.svg",
        "nav_preferences.svg",
        "apply_selected.svg",
        "stop_tasks.svg",
        "clear_workspace.svg",
        "PySide6",
        "pymupdf",
        "PIL",
        "av",
        "keyring.backends",
        "Xuxia",
    )
    for value in required:
        assert value in spec
    assert "src/main_qml.py" not in spec
    assert "settings.json" not in spec
    assert "qa-current" not in spec


def test_packaging_spec_includes_offline_user_manual_and_asset_tree():
    spec = (ROOT / "packaging" / "xuxia.spec").read_text(encoding="utf-8")
    assert '序匣用户手册.html' in spec
    assert 'user-guide-assets' in spec
    assert 'GUIDE_ASSET_ROOT' in spec
    assert 'rglob("*")' in spec


def test_packaging_analysis_explicitly_includes_native_datetime_dependency(monkeypatch):
    """Evaluate the real spec without invoking build hooks or constructors."""
    spec_path = ROOT / "packaging" / "xuxia.spec"
    hooks = ModuleType("PyInstaller.utils.hooks")
    hooks.collect_submodules = lambda name: [f"{name}._contract_sentinel"]
    hooks.collect_data_files = lambda name: []
    hooks.copy_metadata = lambda name: []
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks)
    captured = {}

    def analysis(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])

    namespace = {
        "SPEC": str(spec_path),
        "Analysis": analysis,
        "PYZ": lambda *args, **kwargs: None,
        "EXE": lambda *args, **kwargs: None,
        "COLLECT": lambda *args, **kwargs: None,
    }
    exec(compile(spec_path.read_text(encoding="utf-8"), str(spec_path), "exec"), namespace)

    assert "win32timezone" in captured["hiddenimports"], (
        "GetFileInformationByHandle constructs native datetimes and dynamically "
        "imports win32timezone; Analysis must explicitly bundle it"
    )


def test_built_pyz_contains_native_datetime_dependency():
    from PyInstaller.archive.readers import CArchiveReader

    assert PACKAGED_EXE.is_file(), "Build the release EXE before checking its PYZ"
    archive = CArchiveReader(str(PACKAGED_EXE))
    pyz_names = [name for name, entry in archive.toc.items() if entry[-1] == "z"]
    assert pyz_names, "Release EXE must contain a readable embedded PYZ archive"
    modules = {
        name
        for pyz_name in pyz_names
        for name in archive.open_embedded_archive(pyz_name).toc
    }
    assert "win32timezone" in modules, (
        "Built release PYZ lacks win32timezone, required by native FILETIME "
        "conversion in GetFileInformationByHandle"
    )


def test_packaged_offline_manual_matches_every_source_asset():
    packaged_root = PACKAGED_EXE.parent
    source_manual = ROOT / "序匣用户手册.html"
    packaged_manual = packaged_root / "序匣用户手册.html"
    source_assets = ROOT / "user-guide-assets"
    packaged_assets = packaged_root / "user-guide-assets"
    assert packaged_manual.is_file()
    assert packaged_manual.read_bytes() == source_manual.read_bytes()
    expected = {
        path.relative_to(source_assets).as_posix()
        for path in source_assets.rglob("*") if path.is_file()
    }
    packaged_names = {
        path.relative_to(packaged_assets).as_posix()
        for path in packaged_assets.rglob("*") if path.is_file()
    }
    source_names = {
        path.relative_to(source_assets).as_posix()
        for path in source_assets.rglob("*") if path.is_file()
    }
    assert source_names == expected
    assert {"guide.css", "manifest.json", "manual-zh-HK.html", "manual-en-US.html"} <= expected
    assert packaged_names == expected
    for name in expected:
        source = source_assets / name
        packaged = packaged_assets / name
        assert hashlib.sha256(packaged.read_bytes()).digest() == hashlib.sha256(source.read_bytes()).digest()


def test_build_script_targets_candidate_spec_not_official_entry():
    script = (ROOT / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")
    assert "packaging\\xuxia.spec" in script
    assert "src\\main.py" not in script
    assert "UPDATE_GOLDENS" not in script
    assert "[string]$PythonPath" in script
    assert 'Get-ChildItem -LiteralPath $projectRoot -Filter "*.html" -File' in script
    assert "user-guide-assets" in script
    assert "Copy-Item" in script


def test_candidate_packaging_sources_contain_no_developer_absolute_path():
    files = (
        ROOT / "src" / "main_qml.py",
        ROOT / "packaging" / "xuxia.spec",
        ROOT / "scripts" / "build_windows.ps1",
        ROOT / "src" / "config.py",
        ROOT / "src" / "utils" / "logger.py",
    )
    forbidden = ("D:/文件AI-AGENT", "D:\\文件AI-AGENT")
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert all(value not in text for value in forbidden), path


def test_build_dependency_supports_python_314():
    requirement = (ROOT / "requirements-build.txt").read_text(encoding="utf-8")
    assert "PyInstaller==6.21.0" in requirement


def test_retired_monetary_features_are_absent_from_release_source():
    retired = (
        ROOT / "src" / "core" / "budget.py",
        ROOT / "src" / "core" / "cost_estimator.py",
        ROOT / "src" / "resources" / "provider_pricing.json",
    )
    assert all(not path.exists() for path in retired)

    product_spec = (ROOT / "docs" / "PRODUCT_SPEC.md").read_text(encoding="utf-8")
    detailed_design = (ROOT / "docs" / "XUXIA_DETAILED_DESIGN.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "docs" / "ACCEPTANCE_MATRIX.md").read_text(encoding="utf-8")
    assert "本批预计费用" not in product_spec
    assert "## 18. 费用、预算与用量" not in detailed_design
    assert "批次费用预估" not in acceptance


def test_official_python_entry_delegates_to_qml():
    from src import main, main_qml

    assert main.main is main_qml.main


def test_official_launchers_are_location_independent():
    launcher = ROOT / "run.bat"
    text = launcher.read_text(encoding="utf-8")
    assert "D:\\文件AI-AGENT" not in text
    assert "D:/文件AI-AGENT" not in text
    assert "%~dp0" in text
    assert "-m src.main" in text


def test_retired_widgets_product_slice_is_absent():
    retired = (
        ROOT / "AI-文件夹整理程序.bat",
        ROOT / "AI-文件夹整理程序.vbs",
        ROOT / "legacy",
        ROOT / "src" / "main_legacy.py",
        ROOT / "src" / "app.py",
        ROOT / "src" / "ui",
    )
    assert all(not path.exists() for path in retired)


def test_release_artifact_exists_for_packaging_gate():
    assert PACKAGED_EXE.is_file(), (
        "Release packaging gate is fail-closed: build dist/Xuxia/Xuxia.exe first"
    )


def test_built_executable_smoke_isolated_full_runtime(tmp_path):
    report = tmp_path / "report.json"
    data_dir = tmp_path / "data"
    install_before = {
        path.relative_to(PACKAGED_EXE.parent)
        for path in PACKAGED_EXE.parent.rglob("*")
        if path.is_file()
    }

    completed = subprocess.run(
        [
            str(PACKAGED_EXE),
            "--smoke-test",
            "--data-dir",
            str(data_dir),
            "--report",
            str(report),
        ],
        cwd=tmp_path,
        check=False,
        timeout=60,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )

    assert completed.returncode == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload == {
        "status": "ok",
        "brand": "Xuxia",
        "version": "1.0.0",
        "qml_warning_count": 0,
        "credential_backend": "ephemeral",
        "media": {
            "image_preprocess": "ok",
            "pdf_render": "ok",
            "video_keyframes": "ok",
            "diagnostics_export": "ok",
            "windows_credential_backend": "import-ok",
        },
    }
    install_after = {
        path.relative_to(PACKAGED_EXE.parent)
        for path in PACKAGED_EXE.parent.rglob("*")
        if path.is_file()
    }
    assert install_after == install_before
    catalog = json.loads((data_dir / "templates.json").read_text(encoding="utf-8"))
    assert isinstance(catalog, dict), "EXE must include the versioned preset installer"
    assert catalog["schema_version"] == 1
    assert len(catalog["templates"]) == 9
    assert len(catalog["installed_presets"]) == 8
    assert catalog["templates"][0]["name"] == "General Naming (Default)"
    assert {row["id"] for row in catalog["templates"]} >= {
        "builtin.simple-title.v1", "builtin.receipts.v1", "builtin.contracts.v1",
        "builtin.projects.v1", "builtin.study.v1", "builtin.papers.v1",
        "builtin.media.v1", "builtin.versions.v1",
    }


def test_built_executable_has_xuxia_windows_version_resource():
    import pefile

    pe = pefile.PE(str(PACKAGED_EXE), fast_load=False)
    tables = [
        table
        for group in pe.FileInfo
        for entry in group
        for table in getattr(entry, "StringTable", [])
    ]
    strings = {
        key.decode("utf-8", errors="replace"): value.decode("utf-8", errors="replace")
        for table in tables
        for key, value in table.entries.items()
    }
    assert strings["ProductName"] == "序匣 Xuxia"
    assert strings["ProductVersion"] == "1.0.0"
    assert strings["OriginalFilename"] == "Xuxia.exe"


def test_built_tree_contains_no_user_state_or_developer_path():
    forbidden_names = {
        "settings.json",
        "batch_workspace.json",
        "rename_history.jsonl",
        "watch_folders.json",
        "usage.json",
    }
    names = {path.name for path in PACKAGED_EXE.parent.rglob("*") if path.is_file()}
    assert not (names & forbidden_names)

    forbidden_bytes = (
        "D:/文件AI-AGENT".encode("utf-8"),
        "D:\\文件AI-AGENT".encode("utf-8"),
        "D:/文件AI-AGENT".encode("utf-16le"),
        "D:\\文件AI-AGENT".encode("utf-16le"),
    )
    for path in PACKAGED_EXE.parent.rglob("*"):
        if not path.is_file():
            continue
        previous = b""
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                candidate = previous + chunk
                assert not any(value in candidate for value in forbidden_bytes), path
                previous = candidate[-128:]

# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata


PROJECT_ROOT = Path(SPEC).resolve().parents[1]
QML_ROOT = PROJECT_ROOT / "src" / "ui_qml"
LOCALE_ROOT = PROJECT_ROOT / "src" / "utils" / "i18n" / "locales"
GUIDE_ASSET_ROOT = PROJECT_ROOT / "user-guide-assets"

NAV_ICON_NAMES = (
    "nav_batch.svg",
    "nav_watch.svg",
    "nav_templates.svg",
    "nav_status.svg",
    "nav_preferences.svg",
    "watch_folder.svg",
    "apply_selected.svg",
    "stop_tasks.svg",
    "clear_workspace.svg",
    "chevron_down.svg",
)

datas = [
    (str(path), str(Path("src/ui_qml") / path.relative_to(QML_ROOT).parent))
    for path in QML_ROOT.rglob("*.qml")
]
datas += [(str(QML_ROOT / "qmldir"), "src/ui_qml")]
datas += [
    (str(QML_ROOT / "icons" / name), "src/ui_qml/icons")
    for name in NAV_ICON_NAMES
]
datas += [
    (str(path), "src/utils/i18n/locales")
    for path in LOCALE_ROOT.glob("*.json")
]
datas += [
    (
        str(PROJECT_ROOT / "src/core/data/vocabulary_presets_general.json"),
        "src/core/data",
    )
]
datas += [(str(PROJECT_ROOT / "序匣用户手册.html"), ".")]
datas += [(str(PROJECT_ROOT / "resources/local-models/qwen35-4b-managed-v1.json"),
           "resources/local-models")]
datas += [(str(PROJECT_ROOT / "resources/local-models/runtime/llama-b10885-bin-win-cpu-x64.zip"),
           "resources/local-models/runtime")]
datas += [(str(PROJECT_ROOT / "resources/local-models/licenses" / name),
           "resources/local-models/licenses") for name in (
               "Qwen3.5-4B-LICENSE.txt", "llama.cpp-LICENSE.txt", "SOURCES.md", "OpenCC-SOURCES.md")]
# The pinned pure-Python wheel owns its original configs, dictionaries and
# Apache license. Preserve them and metadata rather than retyping/vendoring.
datas += collect_data_files("opencc")
datas += copy_metadata("opencc-python-reimplemented")
datas += [
    (str(path), str(Path("user-guide-assets") / path.relative_to(GUIDE_ASSET_ROOT).parent))
    for path in GUIDE_ASSET_ROOT.rglob("*")
    if path.is_file()
]

hiddenimports = (
    collect_submodules("keyring.backends")
    + collect_submodules("PIL")
    + [
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickControls2",
        "pymupdf",
        "PIL",
        "av",
        "watchdog.observers.winapi",
        # Native FILETIME-to-datetime conversion dynamically imports this module.
        "win32timezone",
        "src.services.media.image_preprocessor",
        "src.services.media.pdf_renderer",
        "src.services.media.keyframe_extractor",
    ]
)

a = Analysis(
    [str(PROJECT_ROOT / "src/main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Xuxia",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(PROJECT_ROOT / "packaging" / "version_info.txt"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Xuxia",
)

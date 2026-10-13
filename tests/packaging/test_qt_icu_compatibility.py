"""Guard against an unrelated tool's ICU DLL poisoning the Windows package."""
import os
from pathlib import Path

import pefile
import pytest


ROOT = Path(__file__).resolve().parents[2]


def _packaged_qt_core_path(internal):
    candidates = [
        internal / "Qt6Core.dll",
        internal / "PySide6/Qt6Core.dll",
    ]
    existing = [path for path in candidates if path.is_file()]
    assert len(existing) == 1, (
        f"Expected exactly one packaged Qt6Core.dll in {internal}, found {existing!r}"
    )
    return existing[0]


@pytest.mark.parametrize("relative_path", ["Qt6Core.dll", "PySide6/Qt6Core.dll"])
def test_qt_core_path_resolver_supports_both_layouts(tmp_path, relative_path):
    qt_path = tmp_path / relative_path
    qt_path.parent.mkdir(parents=True, exist_ok=True)
    qt_path.write_bytes(b"synthetic Qt core")

    assert _packaged_qt_core_path(tmp_path) == qt_path


def test_qt_core_path_resolver_rejects_missing_core(tmp_path):
    with pytest.raises(AssertionError):
        _packaged_qt_core_path(tmp_path)


def test_qt_core_path_resolver_rejects_ambiguous_layouts(tmp_path):
    (tmp_path / "Qt6Core.dll").write_bytes(b"top-level Qt core")
    nested_qt_path = tmp_path / "PySide6/Qt6Core.dll"
    nested_qt_path.parent.mkdir()
    nested_qt_path.write_bytes(b"nested Qt core")

    with pytest.raises(AssertionError):
        _packaged_qt_core_path(tmp_path)


def test_packaged_icu_provides_the_symbols_required_by_qt():
    internal = ROOT / "dist/Xuxia/_internal"
    qt_path = _packaged_qt_core_path(internal)
    assert qt_path.is_file(), "Build the Windows package before running its Gate"
    with pefile.PE(str(qt_path), fast_load=True) as qt:
        qt.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
        required = {symbol.name for entry in qt.DIRECTORY_ENTRY_IMPORT
                    if entry.dll.lower() == b"icuuc.dll"
                    for symbol in entry.imports if symbol.name}
    assert required, "Expected Qt's Windows ICU dependency to be checked"
    library = internal / "icuuc.dll"
    if not library.exists():
        library = Path(os.environ['SystemRoot']) / "System32/icuuc.dll"
    with pefile.PE(str(library), fast_load=True) as icu:
        icu.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
        available = {symbol.name for symbol in icu.DIRECTORY_ENTRY_EXPORT.symbols}
    assert required <= available, f"Incompatible ICU DLL: {library}; missing {sorted(required - available)!r}"

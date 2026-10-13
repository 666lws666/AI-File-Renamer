"""Every locally referenced QML SVG must survive packaging byte-for-byte."""
import ast
from pathlib import Path
import re

ROOT = Path(__file__).parents[2]
QML = ROOT / 'src/ui_qml'


def referenced_icons():
    return {name for qml in QML.glob('*.qml')
            for name in re.findall(r'["\']icons/([^"\']+\.svg)["\']', qml.read_text(encoding='utf-8'))}


def test_spec_includes_every_referenced_local_icon():
    tree = ast.parse((ROOT / 'packaging/xuxia.spec').read_text(encoding='utf-8'))
    declared = next(ast.literal_eval(node.value) for node in tree.body
                    if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'NAV_ICON_NAMES' for t in node.targets))
    assert referenced_icons() - set(declared) == set()


def test_built_local_icons_match_source():
    bundle = ROOT / 'dist/Xuxia/_internal/src/ui_qml/icons'
    for name in referenced_icons():
        packaged = bundle / name
        assert packaged.is_file(), f'Bundled QML icon missing: {name}'
        assert packaged.read_bytes() == (QML / 'icons' / name).read_bytes()

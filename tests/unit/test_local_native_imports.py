"""Product-native ownership and legacy diagnostic import compatibility."""

import ast
import importlib
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "src" / "services" / "local_ai" / "native"
MODULES = (
    ("security", "local_probe_security", "AppContainerSecurity"),
    ("profile", "local_probe_profile", "OwnedAppContainerProfile"),
    ("process", "local_probe_process", "ProcessResult"),
    ("exemptions", "local_probe_exemptions", "OwnedLoopbackExemptionQuery"),
    ("stage", "local_probe_stage", "OwnedProbe"),
    ("model_stage", "local_model_stage", "OwnedModelBundle"),
)


@pytest.mark.parametrize("product,diagnostic,public_type", MODULES)
def test_diagnostic_import_is_the_product_module(product, diagnostic, public_type):
    product_name = f"src.services.local_ai.native.{product}"
    diagnostic_name = f"scripts.{diagnostic}"
    implementation = importlib.import_module(product_name)
    legacy = importlib.import_module(diagnostic_name)
    assert legacy is implementation
    assert sys.modules[diagnostic_name] is sys.modules[product_name]
    assert getattr(legacy, public_type) is getattr(implementation, public_type)


def test_native_package_import_is_side_effect_free():
    code = (
        "import sys; "
        "import src.services.local_ai.native; "
        "assert not any(name.startswith('scripts.') for name in sys.modules); "
        "assert not any(name.startswith('tests.') for name in sys.modules); "
        "assert not any(name.startswith('src.services.local_ai.native.') "
        "for name in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_diagnostic_first_import_uses_one_product_module():
    pairs = tuple((product, diagnostic) for product, diagnostic, _ in MODULES)
    code = f"""
import importlib
import sys
for product, diagnostic in {pairs!r}:
    old = 'scripts.' + diagnostic
    new = 'src.services.local_ai.native.' + product
    assert importlib.import_module(old) is importlib.import_module(new)
    assert sys.modules[old] is sys.modules[new]
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("product,diagnostic,public_type", MODULES)
def test_product_imports_do_not_depend_on_diagnostic_or_application_modules(
    product, diagnostic, public_type
):
    source = (NATIVE / f"{product}.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    prohibited = ("scripts", "tests", "qa")
    assert not [name for name in imported if name.startswith(prohibited)]
    assert all(
        name.startswith("src.services.local_ai.native.")
        for name in imported if name.startswith("src.")
    )

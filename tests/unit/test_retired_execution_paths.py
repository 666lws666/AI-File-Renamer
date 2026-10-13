"""Retirement architecture gates; these do not prove model quality or file safety."""
import ast
import importlib
import importlib.util
import json
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RETIRED = (
    "src/core/ai_engine.py", "src/core/rename_engine.py",
    "src/core/template_engine.py", "src/core/folder_watcher.py",
    "src/core/organization_engine.py", "src/models/template.py",
    "src/models/watch_config.py", "src/providers/base.py",
    "src/providers/deepseek.py", "src/providers/openai.py", "src/providers/claude.py",
)
RETIRED_MODULES = {name[:-3].replace("/", ".") for name in RETIRED}


def test_retired_execution_modules_are_absent():
    assert not [name for name in RETIRED if (ROOT / name).exists()]


def _python_paths():
    for directory in ("src", "scripts", "tests"):
        yield from (ROOT / directory).rglob("*.py")
    yield ROOT / "acceptance_test.py"


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    package = ".".join(path.relative_to(ROOT).parts[:-1])
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (item.name for item in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = importlib.util.resolve_name("." * node.level + module, package)
            yield module
            yield from (module + "." + item.name for item in node.names)


def test_no_retired_module_import_consumers():
    references = [(str(path.relative_to(ROOT)), name)
                  for path in _python_paths() for name in _imports(path)
                  if name in RETIRED_MODULES]
    assert references == []


def test_current_public_imports_do_not_load_retired_chain():
    models = importlib.import_module("src.models")
    assert {"FileItem", "RenameRecord", "AppConfig"} <= set(models.__all__)
    assert not {"NamingTemplate", "TemplateField", "WatchConfig", "WatchMode"} & set(models.__all__)
    factory = importlib.import_module("src.providers.factory")
    assert factory.LEGACY_PROVIDER_IDS == frozenset({"openai", "claude"})
    assert factory.is_legacy_provider(" OPENAI ")
    assert factory.is_legacy_provider("CLAUDE")
    assert not factory.is_legacy_provider(None)
    assert not factory.is_legacy_provider("deepseek")
    assert not hasattr(factory, "create_provider")
    importlib.import_module("src.providers.presets")


def test_history_is_persistence_only_not_a_file_move_api():
    from src.core.rename_history import RenameHistory
    assert not hasattr(RenameHistory, "undo_batch")
    assert not hasattr(RenameHistory, "_rewrite_with_undone")
    tree = ast.parse((ROOT / "src/core/rename_history.py").read_text(encoding="utf-8"))
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"rename", "renames", "move"}]


def test_retired_provider_sdks_are_not_required_or_imported():
    retired_sdks = {"openai", "anthropic", "httpx"}
    declarations = {line.split(">=")[0].split("==")[0].strip().casefold()
                    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.lstrip().startswith("#")}
    assert retired_sdks.isdisjoint(declarations)
    assert not [(str(path.relative_to(ROOT)), name) for path in _python_paths()
                for name in _imports(path) if name.split(".")[0] in retired_sdks]


@pytest.mark.parametrize("function_name", ["test_template_engine", "test_rename_engine",
    "test_providers", "test_organization", "test_watcher", "test_e2e", "test_integration"])
def test_migrated_acceptance_exercises_current_functionality(function_name, tmp_path):
    """Run actual acceptance checks without its top-level GUI/config side effects.

    Fake transport/observer replace only external boundaries. File movement is
    the production native engine; synthetic fields make no model-quality claim.
    """
    path = ROOT / "acceptance_test.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                   and node.name.startswith("test_")]
    assertions = []

    def assert_check(name, condition, detail=""):
        assertions.append(name)
        assert condition, f"{name}: {detail}"

    namespace = {"Path": Path, "tempfile": tempfile, "json": json,
                 "PROJECT_ROOT": ROOT, "_SAFE_CONFIG_DIR": tmp_path, "check": assert_check}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(path), "exec"), namespace)
    namespace[function_name]()
    assert assertions, "Acceptance function must execute behavioral assertions"

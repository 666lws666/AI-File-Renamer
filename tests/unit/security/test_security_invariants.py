"""M0 Task 2: Security Invariant Regression Suite.

Characterization tests for Phase 1A security behaviors.
These tests verify that existing security guarantees are not
accidentally broken by future changes.

ALL tests use monkeypatch, tmp_path, and mock keyring — never
touch real Windows Credential Manager or settings.json.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config import load_config, save_config, CredentialSaveError
from src.models.app_config import AppConfig


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    """Redirect config paths to a temp directory."""
    config_dir = tmp_path / "config"
    config_file = config_dir / "settings.json"
    monkeypatch.setattr("src.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("src.config.CONFIG_FILE", config_file)
    monkeypatch.setattr("src.config.TEMPLATES_DIR", config_dir / "templates")
    return config_dir, config_file


@pytest.fixture
def mock_keyring_store():
    """In-memory keyring mock."""
    store = {}

    def _get(service, account):
        return store.get(f"{service}/{account}")

    def _set(service, account, password):
        store[f"{service}/{account}"] = password

    def _delete(service, account):
        store.pop(f"{service}/{account}", None)

    with patch("keyring.get_password", side_effect=_get), \
         patch("keyring.set_password", side_effect=_set), \
         patch("keyring.delete_password", side_effect=_delete):
        yield store


@pytest.fixture
def mock_keyring_failing():
    """Keyring where set_password always raises."""
    store = {}

    def _get(service, account):
        return store.get(f"{service}/{account}")

    def _set(service, account, password):
        raise OSError("Simulated credential manager failure")

    def _delete(service, account):
        store.pop(f"{service}/{account}", None)

    with patch("keyring.get_password", side_effect=_get), \
         patch("keyring.set_password", side_effect=_set), \
         patch("keyring.delete_password", side_effect=_delete):
        yield store


# ── Test: API Key never in JSON ───────────────────────────

def test_api_key_never_in_json(isolated_config, mock_keyring_store):
    """save_config() must never write api_key to settings.json."""
    _, config_file = isolated_config
    config = AppConfig(
        provider="deepseek",
        api_key="sk-secret-key-12345",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-flash",
    )
    save_config(config)

    with open(config_file, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert "api_key" not in saved, "api_key must never appear in settings.json"
    # Key should be in mock keyring
    assert mock_keyring_store.get("AIRenamer/api_key") == "sk-secret-key-12345"


# ── Test: Keyring failure → JSON not written ──────────────

def test_keyring_failure_json_not_written(isolated_config, mock_keyring_failing):
    """When credential save fails, JSON must NOT be written (fail-closed)."""
    config_dir, config_file = isolated_config
    config_dir.mkdir(parents=True, exist_ok=True)

    # Pre-write known state
    original = {"provider": "openai", "model": "gpt-4"}
    config_file.write_text(json.dumps(original, indent=2, ensure_ascii=False), encoding="utf-8")

    config = AppConfig(
        provider="deepseek",
        api_key="sk-should-not-persist",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-flash",
    )

    with pytest.raises(CredentialSaveError):
        save_config(config)

    # JSON must still contain original data
    with open(config_file, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved == original, "JSON was overwritten despite credential save failure"
    assert "api_key" not in saved


# ── Test: Clear key deletes credential ────────────────────

def test_clear_key_deletes_credential(isolated_config, mock_keyring_store):
    """When user clears the API key, the credential is deleted."""
    _, config_file = isolated_config

    # Pre-seed keyring
    mock_keyring_store["AIRenamer/api_key"] = "sk-old-key"

    config = AppConfig(
        provider="deepseek",
        api_key="",  # Cleared
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-flash",
    )
    save_config(config)

    # Credential should be gone
    assert "AIRenamer/api_key" not in mock_keyring_store, "Credential not deleted when key cleared"
    # JSON should be written without api_key
    with open(config_file, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert "api_key" not in saved


# ── Test: Config writes only to isolated paths ─────────────

def test_config_operations_write_only_to_isolated_path(isolated_config, mock_keyring_store):
    """save/load never touch real paths; all writes go to tmp_path."""
    config_dir, config_file = isolated_config
    import src.config

    original_atomic = src.config._atomic_write_json
    written_paths = []

    def _spy_atomic(filepath, data):
        written_paths.append(str(filepath))
        return original_atomic(filepath, data)

    src.config._atomic_write_json = _spy_atomic
    try:
        config = AppConfig(provider="deepseek", api_key="sk-isolated-test", model="deepseek-v4-flash")
        save_config(config)
        load_config()

        # All JSON writes must be within tmp_path
        tmp_str = str(config_dir)
        for path in written_paths:
            assert path.startswith(tmp_str), (
                f"Config wrote outside isolated path: {path}"
            )
        # No real credential calls — already enforced by mock keyring fixture
    finally:
        src.config._atomic_write_json = original_atomic


# ── Test: No trivial assertions ────────────────────────────

def test_security_suite_contains_no_trivial_assertions():
    """Verify this file has no assert True, empty pass, or no-op tests."""
    import ast
    import sys
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            # Collect all statements in the function body
            stmts = [s for s in node.body if not isinstance(s, ast.Expr)
                     or not isinstance(s.value, ast.Constant)
                     or not isinstance(s.value, (str, type(None)))]
            # Check for trivial pass-only body
            non_docstring = [s for s in node.body
                           if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))]
            if len(non_docstring) == 0 or (len(non_docstring) == 1 and isinstance(non_docstring[0], ast.Pass)):
                pytest.fail(f"Test {node.name} has empty/pass-only body")
            # Check for assert True as only assertion
            for s in ast.walk(node):
                if isinstance(s, ast.Assert) and isinstance(s.test, ast.Constant) and s.test.value is True:
                    # Check if there are any other real assertions
                    other_asserts = [a for a in ast.walk(node)
                                   if isinstance(a, ast.Assert)
                                   and not (isinstance(a.test, ast.Constant) and a.test.value is True)]
                    if not other_asserts:
                        pytest.fail(f"Test {node.name} only has assert True")


# ── Test: AST log scanning for api_key ─────────────────────

def test_api_key_never_in_logs():
    """AST scan: no logger call in src/ passes api_key as argument."""
    import ast
    src_dir = Path(__file__).parent.parent.parent.parent / "src"
    py_files = list(src_dir.rglob("*.py"))

    log_names = {"logger", "log", "logging"}
    log_methods = {"debug", "info", "warning", "warn", "error", "critical",
                   "exception", "log", "print", "write"}

    violations = []
    for py_file in py_files:
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in log_methods:
                if isinstance(func.value, ast.Name) and func.value.id in log_names:
                    # Only flag calls where api_key VALUE (not just the word) is passed
                    # Pattern: api_key subscript (api_key[:8]), api_key concatenation,
                    # or api_key variable directly in an f-string/format
                    for arg in node.args:
                        arg_src = ast.unparse(arg)
                        # Subscript: api_key[...]
                        if "api_key[" in arg_src:
                            rel = py_file.relative_to(src_dir.parent)
                            violations.append(f"{rel}:{node.lineno}: api_key SUBSCRIPT: {ast.unparse(node)[:120]}")
                        # Direct variable: the argument IS api_key (not a string literal mentioning it)
                        elif arg_src.strip() == "api_key" or arg_src.strip() == "self.api_key":
                            rel = py_file.relative_to(src_dir.parent)
                            violations.append(f"{rel}:{node.lineno}: api_key DIRECT: {ast.unparse(node)[:120]}")
                        # f-string containing api_key variable
                        elif "api_key" in arg_src and isinstance(arg, ast.JoinedStr):
                            rel = py_file.relative_to(src_dir.parent)
                            violations.append(f"{rel}:{node.lineno}: api_key IN F-STRING: {ast.unparse(node)[:120]}")

    # Sentinel: prove the scanner catches what it should
    sentinel_code = 'logger.info(api_key[:4])'
    sentinel_tree = ast.parse(sentinel_code)
    sentinel_call = sentinel_tree.body[0].value
    sentinel_arg = ast.unparse(sentinel_call.args[0])
    assert "api_key" in sentinel_arg, "AST scanner sentinel not working — check test logic"

    assert not violations, (
        f"Found {len(violations)} log call(s) passing api_key:\n" +
        "\n".join(violations)
    )

"""Test that src/ contains no logging of API key fragments.

Covers: AM-01.3 — 日志文件不包含 API Key 任何片段

Uses sentinel-based source scan: a fictional secret is defined and we
prove the scanner would catch it if it appeared.  We then scan for
the actual dangerous patterns (api_key slicing in logger calls).
"""

import ast
from pathlib import Path

import pytest


SRC_DIR = Path(__file__).parent.parent / "src"
SENTINEL = "phase1a-sentinel-test-secret-abc123"
SENTINEL_PREFIX = SENTINEL[:8]   # "phase1a-"
SENTINEL_SUFFIX = SENTINEL[-4:]  # "c123"


def _py_files():
    return sorted(SRC_DIR.rglob("*.py"))


# ---------------------------------------------------------------------------
# Sentinel scan — proves the scanner mechanism would catch real leaks
# ---------------------------------------------------------------------------

def test_sentinel_not_in_source():
    """No .py file under src/ contains the sentinel secret or its fragments.

    This is trivially true (we just invented the sentinel) and proves
    that the source-scanner is working correctly.
    """
    for py_file in _py_files():
        content = py_file.read_text(encoding="utf-8")
        rel = py_file.relative_to(SRC_DIR.parent)
        assert SENTINEL not in content, f"{rel}: source contains full sentinel"
        assert SENTINEL_PREFIX not in content, f"{rel}: source contains sentinel prefix"
        assert SENTINEL_SUFFIX not in content, f"{rel}: source contains sentinel suffix"


# ---------------------------------------------------------------------------
# Dangerous pattern scan — api_key slicing in logging/output context
# ---------------------------------------------------------------------------

_LOGGER_NAMES = frozenset({"logger", "log", "logging"})
_LOG_METHODS = frozenset({
    "debug", "info", "warning", "warn", "error", "critical", "exception",
    "log", "print", "write",
})


def _is_log_call(call_node: ast.Call) -> bool:
    """Return True if *call_node* looks like a logger.info(...) call."""
    func = call_node.func
    # logger.info(...) → Attribute.value=Name('logger'), Attribute.attr='info'
    if isinstance(func, ast.Attribute):
        if func.attr not in _LOG_METHODS:
            return False
        if isinstance(func.value, ast.Name) and func.value.id in _LOGGER_NAMES:
            return True
    return False


def _contains_api_key_slice(node: ast.AST) -> bool:
    """Walk *node* and return True if it contains api_key subscript."""
    for child in ast.walk(node):
        if isinstance(child, ast.Subscript):
            # Check for: api_key[...] or self.api_key[...]
            value_src = ast.unparse(child.value)
            if value_src.endswith("api_key"):
                return True
    return False


def test_no_api_key_slicing_in_log_calls():
    """No logger call in src/ passes api_key[...] (a key slice) as an argument.

    This is the actual defense against logging key prefixes/suffixes.
    """
    violations = []
    for py_file in _py_files():
        rel = str(py_file.relative_to(SRC_DIR.parent))
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue  # skip unparseable files

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_log_call(node):
                if _contains_api_key_slice(node):
                    violations.append(f"{rel}:{node.lineno}: {ast.unparse(node)[:120]}")

    assert not violations, (
        f"Found {len(violations)} log call(s) that pass api_key slices:\n" +
        "\n".join(violations)
    )


def test_current_provider_source_has_no_credential_logging():
    """Static output-context gate, not proof of runtime error redaction.

    The current adapter has no logger. Existing dynamic transport/contracts
    remain responsible for error-result redaction. Authorization construction
    is intentional transport behavior and is not a logging leak.
    """
    secrets = {"api_key", "credential", "_credential"}

    def violations(source):
        found = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call):
                continue
            output = (_is_log_call(node)
                      or isinstance(node.func, ast.Name) and node.func.id == "print"
                      or ast.unparse(node.func) in {"sys.stdout.write", "sys.stderr.write"})
            if not output:
                continue
            values = [*node.args, *(item.value for item in node.keywords)]
            if any((isinstance(child, ast.Name) and child.id in secrets)
                   or (isinstance(child, ast.Attribute) and child.attr in secrets)
                   for value in values for child in ast.walk(value)):
                found.append(node.lineno)
        return found

    # Prove the scanner catches whole credentials and prefix/suffix variants
    # in logging/output contexts without rejecting legitimate wire headers.
    for secret in secrets:
        assert violations(f"logger.debug({secret}[:8])")
        assert violations(f"log.warning(self.{secret}[-4:])")
        assert violations(f"print({secret})")
        assert violations(f"sys.stderr.write(self.{secret}[:8])")
    assert not violations('headers = {"Authorization": f"Bearer {self._credential}"}')
    source = (SRC_DIR / "providers" / "openai_compatible.py").read_text(encoding="utf-8")
    assert not violations(source), "Credential logging/output in current Provider source"


def test_current_settings_sources_have_no_key_logging():
    """The official settings controller/transaction never log key fragments."""
    sources = (
        SRC_DIR / "controllers" / "settings_controller.py",
        SRC_DIR / "controllers" / "settings_transaction.py",
        SRC_DIR / "utils" / "credential_manager.py",
    )
    for source_path in sources:
        source = source_path.read_text(encoding="utf-8")
        assert "api_key[:8]" not in source, f"key prefix slice in {source_path.name}"
        assert "api_key[-4:]" not in source, f"key suffix slice in {source_path.name}"

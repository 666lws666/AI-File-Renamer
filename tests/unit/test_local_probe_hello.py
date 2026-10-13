"""Exact, data-only validation of the native hello protocol result."""

from dataclasses import replace
from importlib import import_module
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.local_probe_process import ProcessResult


CANONICAL_LINE = b'{"protocol":"xuxia-appcontainer-hello","version":1}\r\n'


def validator():
    try:
        module = import_module("scripts.local_probe_hello")
        return module.validate_hello_result, module.HelloValidationError
    except (ModuleNotFoundError, AttributeError) as exc:
        pytest.fail(f"hello validator unavailable: {exc}")


@pytest.fixture
def completed_result():
    return ProcessResult("completed", 0, CANONICAL_LINE, b"", None, True, 0.01)


def test_accepts_exact_completed_hello_result(completed_result):
    validate, _ = validator()
    assert validate(completed_result) is None


def test_import_does_not_initialize_process_bindings_in_fresh_interpreter():
    project_root = Path(__file__).resolve().parents[2]
    code = (
        "import importlib, sys; "
        "assert 'scripts.local_probe_process' not in sys.modules; "
        "importlib.import_module('scripts.local_probe_hello'); "
        "assert 'scripts.local_probe_process' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=project_root, capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"status": "timeout"}, "timeout"),
        ({"status": "launch_error"}, "launch-error"),
        ({"status": "output_limit"}, "partial-output"),
        ({"status": "cleanup_incomplete"}, "cleanup-status"),
        ({"status": "cancelled"}, "cancelled"),
        ({"exit_code": 1}, "nonzero-exit"),
        ({"exit_code": None}, "missing-exit"),
        ({"exit_code": False}, "boolean-zero"),
        ({"cleanup_complete": False}, "incomplete-cleanup"),
        ({"cleanup_complete": 1}, "nonboolean-cleanup"),
        ({"stdout": CANONICAL_LINE[:-1]}, "partial-line"),
        ({"stdout": CANONICAL_LINE + b"extra\r\n"}, "extra-line"),
        ({"stdout": CANONICAL_LINE + b"\r\n"}, "trailing-line"),
        ({"stdout": b"\xef\xbb\xbf" + CANONICAL_LINE}, "bom"),
        ({"stdout": b'{"version":1,"protocol":"xuxia-appcontainer-hello"}\r\n'}, "alternate-json"),
        ({"stdout": b'{"protocol":"xuxia-appcontainer-hello","version":2}\r\n'}, "wrong-version"),
        ({"stdout": CANONICAL_LINE[:-2] + b"\n"}, "noncanonical-newline"),
        ({"stdout": bytearray(CANONICAL_LINE)}, "nonbytes-stdout"),
        ({"stderr": b"diagnostic"}, "diagnostic-stderr"),
        ({"stderr": bytearray()}, "nonbytes-stderr"),
    ],
)
def test_rejects_noncanonical_process_evidence(completed_result, changes, reason):
    validate, error_type = validator()
    with pytest.raises(error_type):
        validate(replace(completed_result, **changes))

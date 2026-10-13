"""Focused regression tests for the native M1 verification entry point."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import capture_m1_native as native
from tests.screenshots.m1_cases import NATIVE_CASES


def _fake_result(case):
    data = f"png:{case.case_id}".encode("utf-8")
    return data, {
        "case_id": case.case_id,
        "filename": f"{case.filename}.png",
        "sha256": native.hashlib.sha256(data).hexdigest(),
        "warnings": [],
        "setup_executed": True,
        "post_executed": True,
        "assert_executed": True,
        "assertion_count": 1,
        "assert_passed": True,
        "cjk_passed": True,
    }


def test_run_verify_consumes_native_case_registry(tmp_path):
    seen = []

    def fake_capture(case):
        seen.append(case.case_id)
        return _fake_result(case)

    results = native.run_verify(
        output_dir=tmp_path,
        cases=NATIVE_CASES,
        capture_fn=fake_capture,
    )

    assert seen == [case.case_id for case in NATIVE_CASES]
    assert [result["case_id"] for result in results] == seen
    assert {
        path.name for path in tmp_path.glob("*.png")
    } == {
        f"{case.filename}.png" for case in NATIVE_CASES
    }


def test_run_verify_rejects_duplicate_image_hashes(tmp_path):
    def duplicate_capture(case):
        data = b"same-png"
        _, result = _fake_result(case)
        result["sha256"] = native.hashlib.sha256(data).hexdigest()
        return data, result

    with pytest.raises(AssertionError, match="duplicate SHA"):
        native.run_verify(
            output_dir=tmp_path,
            cases=NATIVE_CASES,
            capture_fn=duplicate_capture,
        )

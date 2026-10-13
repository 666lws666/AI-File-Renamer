"""Capture and verify the three canonical M1 scenes on the Windows QPA."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Iterable


for key in list(os.environ):
    if key.startswith("QT_QPA_PLATFORM"):
        del os.environ[key]

from PySide6.QtCore import QBuffer, QRect, Qt, QUrl
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontInfo,
    QGuiApplication,
    QImage,
    QPainter,
)
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest


PROJECT = Path(__file__).resolve().parent.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

SRC = PROJECT / "src"
QML_DIR = SRC / "ui_qml"
DEFAULT_OUTPUT = PROJECT / "tests" / "screenshots" / "qa-current" / "m1"


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value


def _cjk_probe(app: QGuiApplication) -> dict[str, Any]:
    chars = "序匣批量重命名待确认应用失败取消忽略"
    font = QFont(app.font())
    font.setPointSize(18)
    glyph_hashes: list[str] = []
    non_background_counts: list[int] = []

    for char in chars:
        image = QImage(48, 48, QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        painter.setFont(font)
        painter.setPen(QColor("black"))
        painter.drawText(
            QRect(0, 0, image.width(), image.height()),
            Qt.AlignmentFlag.AlignCenter,
            char,
        )
        painter.end()
        data = image.bits().tobytes()
        glyph_hashes.append(hashlib.sha256(data).hexdigest())
        non_background_counts.append(
            sum(
                image.pixelColor(x, y) != QColor("white")
                for y in range(image.height())
                for x in range(image.width())
            )
        )

    unique_glyphs = len(set(glyph_hashes))
    all_rendered = all(count > 0 for count in non_background_counts)
    return {
        "characters": chars,
        "total_characters": len(chars),
        "unique_pixel_hashes": unique_glyphs,
        "all_have_non_background_pixels": all_rendered,
        "passed": all_rendered and unique_glyphs >= 10,
    }


def _serialize_assertions(recorder: Any) -> list[dict[str, Any]]:
    return [
        {
            "name": record.name,
            "actual": _json_safe(record.actual),
            "expected": _json_safe(record.expected),
            "passed": bool(record.passed),
        }
        for record in getattr(recorder, "records", [])
    ]


def capture_case(case: Any) -> tuple[bytes, dict[str, Any]]:
    """Capture one complete VisualCase and return PNG bytes and evidence."""
    from src.controllers.mock_batch_controller import MockBatchController
    from src.utils.i18n.service import I18n

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    platform = QGuiApplication.platformName().lower()
    if platform != "windows":
        raise RuntimeError(f"Expected Windows QPA, got {platform!r}")

    app.setFont(QFont("Microsoft YaHei UI", 10))
    i18n = I18n()
    i18n.set_locale(case.locale)
    controller = MockBatchController()

    view = QQuickView()
    engine = view.engine()
    engine.addImportPath(str(SRC))
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    qml_warnings: list[str] = []

    def collect_warnings(errors):
        qml_warnings.extend(error.toString() for error in errors)

    engine.warnings.connect(collect_warnings)

    setup_executed = False
    post_executed = False
    assert_executed = False
    assert_passed = False
    assertion_records: list[dict[str, Any]] = []
    state_snapshot: dict[str, Any] = {}

    try:
        case.setup_fn(controller, i18n)
        setup_executed = True

        view.rootContext().setContextProperty("i18n", i18n)
        view.rootContext().setContextProperty(
            "batchController",
            controller,
        )
        view.setSource(
            QUrl.fromLocalFile(
                str(QML_DIR / "ScreenshotShell.qml")
            )
        )
        if view.status() != QQuickView.Status.Ready:
            errors = [error.toString() for error in view.errors()]
            qml_warnings.extend(errors)
            raise RuntimeError(
                f"{case.case_id}: QML load failed: {errors}"
            )

        root = view.rootObject()
        if root is None:
            raise RuntimeError(f"{case.case_id}: root object is null")

        case.post_fn(root, controller, i18n)
        post_executed = True

        view.resize(case.width, case.height)
        view.show()
        if not QTest.qWaitForWindowExposed(view, 5000):
            raise RuntimeError(
                f"{case.case_id}: native window was not exposed"
            )
        view.requestUpdate()
        QTest.qWait(100)
        app.processEvents()

        assert_executed = True
        recorder = case.assert_fn(root, controller, i18n)
        assertion_records = _serialize_assertions(recorder)
        if not assertion_records:
            raise AssertionError(
                f"{case.case_id}: assert_fn made zero assertions"
            )
        assert_passed = all(
            record["passed"] for record in assertion_records
        )
        if not assert_passed:
            raise AssertionError(
                f"{case.case_id}: state assertions failed"
            )
        state_snapshot = {
            record["name"]: record["actual"]
            for record in assertion_records
        }

        view.requestUpdate()
        QTest.qWait(50)
        app.processEvents()
        image = view.grabWindow()
        if image.isNull():
            raise RuntimeError(
                f"{case.case_id}: grabWindow returned a null image"
            )

        buffer = QBuffer()
        buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise RuntimeError(
                f"{case.case_id}: PNG encoding failed"
            )
        data = bytes(buffer.data())
        cjk = _cjk_probe(app)
        font_info = QFontInfo(app.font())
        result = {
            "case_id": case.case_id,
            "filename": f"{case.filename}.png",
            "registry_source": (
                "tests.screenshots.m1_cases.NATIVE_CASES"
            ),
            "setup_fn": getattr(
                case.setup_fn,
                "__name__",
                type(case.setup_fn).__name__,
            ),
            "post_fn": getattr(
                case.post_fn,
                "__name__",
                type(case.post_fn).__name__,
            ),
            "assert_fn": getattr(
                case.assert_fn,
                "__name__",
                type(case.assert_fn).__name__,
            ),
            "setup_executed": setup_executed,
            "post_executed": post_executed,
            "assert_executed": assert_executed,
            "assert_passed": assert_passed,
            "assertion_count": len(assertion_records),
            "assertions": assertion_records,
            "state_snapshot": state_snapshot,
            "warnings": qml_warnings,
            "platform": platform,
            "width": image.width(),
            "height": image.height(),
            "device_pixel_ratio": (
                app.primaryScreen().devicePixelRatio()
            ),
            "font_requested": "Microsoft YaHei UI",
            "font_actual": font_info.family(),
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "cjk": cjk,
            "cjk_passed": bool(cjk["passed"]),
        }
        return data, result
    finally:
        try:
            engine.warnings.disconnect(collect_warnings)
        except (RuntimeError, TypeError):
            pass
        view.close()
        view.deleteLater()
        app.processEvents()


def run_verify(
    output_dir: Path = DEFAULT_OUTPUT,
    cases: Iterable[Any] | None = None,
    capture_fn: Callable[
        [Any],
        tuple[bytes, dict[str, Any]],
    ] = capture_case,
) -> list[dict[str, Any]]:
    """Capture NATIVE_CASES and fail closed on invalid evidence."""
    if cases is None:
        from tests.screenshots.m1_cases import NATIVE_CASES

        cases = NATIVE_CASES

    case_list = list(cases)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    for case in case_list:
        data, result = capture_fn(case)
        expected_filename = f"{case.filename}.png"
        if result.get("case_id") != case.case_id:
            raise AssertionError(
                f"{case.case_id}: capture returned the wrong case_id"
            )
        if result.get("filename") != expected_filename:
            raise AssertionError(
                f"{case.case_id}: capture returned filename "
                f"{result.get('filename')!r}, expected "
                f"{expected_filename!r}"
            )
        (output_dir / expected_filename).write_bytes(data)
        results.append(result)

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    hashes: dict[str, list[str]] = {}
    for result in results:
        hashes.setdefault(result["sha256"], []).append(
            result["case_id"]
        )
    duplicates = {
        sha: case_ids
        for sha, case_ids in hashes.items()
        if len(case_ids) > 1
    }
    if duplicates:
        raise AssertionError(
            f"duplicate SHA across native cases: {duplicates}"
        )

    failures: list[str] = []
    for result in results:
        case_id = result["case_id"]
        if result.get("warnings"):
            failures.append(f"{case_id}: QML warnings")
        if not result.get("setup_executed"):
            failures.append(f"{case_id}: setup_fn not executed")
        if not result.get("post_executed"):
            failures.append(f"{case_id}: post_fn not executed")
        if not result.get("assert_executed"):
            failures.append(f"{case_id}: assert_fn not executed")
        if not result.get("assert_passed"):
            failures.append(f"{case_id}: state assertions failed")
        if result.get("assertion_count", 0) <= 0:
            failures.append(f"{case_id}: zero state assertions")
        if not result.get("cjk_passed"):
            failures.append(f"{case_id}: CJK glyph probe failed")

    if failures:
        raise AssertionError(
            "native evidence validation failed: "
            + "; ".join(failures)
        )
    return results


def _find_case(case_id: str) -> Any | None:
    from tests.screenshots.m1_cases import (
        CANONICAL_CASES,
        NATIVE_CASES,
    )

    return next(
        (
            case
            for case in [*CANONICAL_CASES, *NATIVE_CASES]
            if case.case_id == case_id
        ),
        None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case")
    parser.add_argument("--output")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Capture and verify canonical native scenes",
    )
    args = parser.parse_args(argv)
    output_dir = (
        Path(args.output) if args.output else DEFAULT_OUTPUT
    )

    try:
        if args.verify:
            results = run_verify(output_dir=output_dir)
            for result in results:
                print(
                    f"[{result['case_id']}] "
                    f"platform={result['platform']} "
                    f"sha256={result['sha256']} "
                    f"warnings={len(result['warnings'])} "
                    f"assertions={result['assertion_count']} "
                    f"cjk_pass={result['cjk_passed']}"
                )
            print(
                f"Verify: PASS ({len(results)} distinct native cases)"
            )
            return 0

        if args.case:
            case = _find_case(args.case)
            if case is None:
                print(
                    f"Unknown case: {args.case}",
                    file=sys.stderr,
                )
                return 1
            data, result = capture_case(case)
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{case.filename}.png"
            output_path.write_bytes(data)
            print(json.dumps(result, ensure_ascii=False))
            return 0

        parser.print_help()
        return 0
    except Exception as exc:
        print(f"Verify: FAIL — {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

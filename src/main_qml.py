"""Official QML application runtime for the Xuxia Windows desktop app.

``src.main`` delegates here after the Product Owner-approved M8 cutover. The
retired Qt Widgets product slice has been removed so this is the sole supported
application runtime.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from src.models.app_config import AppConfig
from src.qml_bootstrap import QmlRuntime, RuntimeConstructionPending, build_qml_runtime


APP_NAME = "序匣"
APP_BRAND = "Xuxia"
APP_ORGANIZATION = "Xuxia"
APP_VERSION = "1.0.0"


class SmokeCredentialStore:
    """Ephemeral credential adapter used only by packaged smoke tests."""

    def __init__(self) -> None:
        self._values: dict[tuple[str, str], str] = {}

    def get(self, service: str, account: str) -> str | None:
        return self._values.get((service, account))

    def set(self, service: str, account: str, secret: str) -> bool:
        self._values[(service, account)] = secret
        return True

    def delete(self, service: str, account: str) -> bool:
        self._values.pop((service, account), None)
        return True


def user_data_dir() -> Path:
    """Return the per-user data root, never the installation directory."""

    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / APP_BRAND
    return Path.home() / "AppData" / "Local" / APP_BRAND


def _configure_application(app: QApplication) -> None:
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setOrganizationName(APP_ORGANIZATION)
    QCoreApplication.setApplicationVersion(APP_VERSION)
    app.setQuitOnLastWindowClosed(False)


def configure_render_environment() -> None:
    """Select the conservative Windows scenegraph loop before Qt app creation.

    QSG_RENDER_LOOP is process-local; an explicit user/developer choice wins.
    This selects rendering only, not model or resource worker execution.
    """
    if sys.platform == "win32":
        os.environ.setdefault("QSG_RENDER_LOOP", "basic")


def _application() -> QApplication:
    configure_render_environment()
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    _configure_application(app)
    return app


def _drain_runtime(runtime) -> None:
    """Keep all owners and Qt dispatch alive between finite cleanup attempts."""
    while runtime.cleanup(deadline=time.monotonic() + .02) is not True:
        loop = QEventLoop()
        QTimer.singleShot(25, loop.quit)
        loop.exec()


def _write_report(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _safe_smoke_detail(error: Exception, data_dir: Path) -> str:
    """Return bounded diagnostics with paths and credential-like text removed."""

    detail = str(error).replace(str(data_dir), "<data-dir>")
    detail = re.sub(
        r"file:///[^\r\n]*?/(?=(?:_internal/)?src/)",
        "file:///<bundle>/",
        detail,
    )
    detail = detail.replace(str(Path.cwd()), "<working-dir>")
    bundle_root = getattr(sys, "_MEIPASS", "")
    if bundle_root:
        detail = detail.replace(str(bundle_root), "<bundle-dir>")
    detail = re.sub(r"(?i)\b[A-Z]:[\\/][^\s\r\n]+", "<local-path>", detail)
    detail = re.sub(
        r"(?i)(api[_-]?key|authorization|bearer|credential)(\s*[:=]\s*)\S+",
        r"\1\2<redacted>",
        detail,
    )
    return detail[:1000]


def _verify_media_dependencies(data_dir: Path) -> dict[str, str]:
    """Exercise packaged image/PDF/video/diagnostics dependencies locally."""

    import av
    import pymupdf
    from keyring.backends.Windows import WinVaultKeyring
    from PIL import Image

    from src.core.diagnostics import DiagnosticsExporter
    from src.services.media.image_preprocessor import ImagePreprocessor
    from src.services.media.keyframe_extractor import VideoKeyframeExtractor
    from src.services.media.pdf_renderer import PdfRenderer

    image = Image.new("RGB", (320, 180), (48, 112, 196))
    image_bytes = io.BytesIO()
    image.save(image_bytes, format="PNG")
    prepared = ImagePreprocessor().process_bytes(
        image_bytes.getvalue(), source_index=0, provenance="packaged-smoke-image"
    )
    if not prepared.data or prepared.width <= 0 or prepared.height <= 0:
        raise RuntimeError("Packaged image preprocessing returned no payload")

    document = pymupdf.open()
    page = document.new_page(width=320, height=180)
    page.insert_text((24, 60), "Xuxia packaged PDF smoke")
    pdf_bytes = document.tobytes()
    document.close()
    rendered = PdfRenderer().render_bytes(
        pdf_bytes, provenance="packaged-smoke-pdf", page_indices=(0,)
    )
    if len(rendered.payloads) != 1 or rendered.rendered_page_indices != (0,):
        raise RuntimeError("Packaged PDF rendering returned an invalid result")

    video_bytes = io.BytesIO()
    container = av.open(video_bytes, mode="w", format="mp4")
    stream = container.add_stream("mpeg4", rate=12)
    stream.width = 160
    stream.height = 96
    stream.pix_fmt = "yuv420p"
    for index in range(48):
        frame_image = Image.new(
            "RGB",
            (160, 96),
            ((index * 17) % 256, (index * 37) % 256, (index * 67) % 256),
        )
        frame = av.VideoFrame.from_image(frame_image)
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    keyframes = VideoKeyframeExtractor().extract_bytes(
        video_bytes.getvalue(),
        provenance="packaged-smoke-video",
        quality_mode="economy",
    )
    if len(keyframes.payloads) != 4 or len(keyframes.timestamps_seconds) != 4:
        raise RuntimeError("Packaged video keyframe extraction returned an invalid result")

    credential_backend = WinVaultKeyring()
    if credential_backend.__class__.__name__ != "WinVaultKeyring":
        raise RuntimeError("Packaged Windows credential backend is unavailable")

    diagnostics_path = data_dir / "packaged-smoke-diagnostics.zip"
    exporter = DiagnosticsExporter(app_version=APP_VERSION)
    preview = exporter.preview(components=[], settings={}, logs=[])
    exporter.export(diagnostics_path, preview)
    if not diagnostics_path.is_file() or diagnostics_path.stat().st_size <= 0:
        raise RuntimeError("Packaged diagnostics export did not create an archive")
    diagnostics_path.unlink()

    return {
        "image_preprocess": "ok",
        "pdf_render": "ok",
        "video_keyframes": "ok",
        "diagnostics_export": "ok",
        "windows_credential_backend": "import-ok",
    }


def run_smoke_test(
    *,
    data_dir: Path,
    report_path: Path | None = None,
    runtime_builder: Callable[..., QmlRuntime] = build_qml_runtime,
) -> int:
    """Load the real QML tree using isolated local-only dependencies.

    No network transport or system credential backend is constructed. A QML
    warning is a hard failure. Reports intentionally include no exception
    messages, paths, credentials, or local file contents.
    """

    runtime: QmlRuntime | None = None
    store = SmokeCredentialStore()
    try:
        _application()
        data_dir.mkdir(parents=True, exist_ok=True)
        runtime = runtime_builder(
            live_config=AppConfig(),
            config_file=data_dir / "settings.json",
            credential_store=store,
            usage_recorder=None,
        )
        runtime.root.show()
        QApplication.instance().processEvents()
        runtime.assert_zero_warnings()
        media = _verify_media_dependencies(data_dir)
        _drain_runtime(runtime)
        _write_report(
            report_path,
            {
                "status": "ok",
                "brand": APP_BRAND,
                "version": APP_VERSION,
                "qml_warning_count": len(runtime.warnings),
                "credential_backend": "ephemeral",
                "media": media,
            },
        )
        return 0
    except Exception as error:
        if isinstance(error, RuntimeConstructionPending):
            runtime = error.runtime
            _drain_runtime(runtime)
        _write_report(
            report_path,
            {
                "status": "failed",
                "brand": APP_BRAND,
                "version": APP_VERSION,
                "error_type": type(error).__name__,
                "error_detail": _safe_smoke_detail(error, data_dir),
            },
        )
        return 2
    finally:
        if runtime is not None:
            _drain_runtime(runtime)


def _write_startup_failure(error: Exception) -> None:
    target = user_data_dir() / "logs" / "startup-failure.json"
    _write_report(
        target,
        {
            "status": "failed",
            "brand": APP_BRAND,
            "version": APP_VERSION,
            "error_type": type(error).__name__,
            "error_detail": _safe_smoke_detail(error, user_data_dir()),
        },
    )


def run_application(
    *, runtime_builder: Callable[[], QmlRuntime] = build_qml_runtime
) -> int:
    """Run the candidate UI and fail closed with a sanitized local report."""

    runtime: QmlRuntime | None = None
    try:
        app = _application()
        runtime = runtime_builder()
        runtime.manage_window_close(quit_application=True)
        runtime.root.show()
        runtime.assert_zero_warnings()
        result = app.exec()
        # Even an external app.quit must not turn wait=False into proven exit.
        _drain_runtime(runtime)
        return result
    except Exception as error:
        if isinstance(error, RuntimeConstructionPending):
            runtime = error.runtime
            _drain_runtime(runtime)
        try:
            _write_startup_failure(error)
        except Exception:
            pass
        return 1
    finally:
        if runtime is not None:
            _drain_runtime(runtime)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=APP_BRAND)
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--local-smoke-resources", type=Path)
    parser.add_argument("--local-smoke-workflow", choices=("file-workflows", "scan-pdf", "video"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.local_smoke_workflow is not None:
        if (not args.smoke_test or args.local_smoke_resources is None
                or args.data_dir is None or args.report is None or args.version):
            raise SystemExit("--local-smoke-workflow requires --smoke-test, --local-smoke-resources, explicit --data-dir and --report")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from src.services.local_ai.packaged_workflow_smoke import run_local_workflow_smoke
        return run_local_workflow_smoke(resources_dir=args.local_smoke_resources,
            data_dir=args.data_dir, report_path=args.report, workflow=args.local_smoke_workflow)
    if args.local_smoke_resources is not None:
        if not args.smoke_test or args.data_dir is None or args.report is None or args.version:
            raise SystemExit("--local-smoke-resources requires --smoke-test, explicit --data-dir and --report")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from src.services.local_ai.packaged_smoke import run_local_smoke
        return run_local_smoke(resources_dir=args.local_smoke_resources,
                               data_dir=args.data_dir, report_path=args.report)
    if args.version:
        print(f"{APP_NAME} {APP_VERSION}")
        return 0
    if args.smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        isolated = args.data_dir or (user_data_dir() / "smoke-test")
        return run_smoke_test(data_dir=isolated, report_path=args.report)
    if args.data_dir is not None or args.report is not None:
        raise SystemExit("--data-dir and --report require --smoke-test")

    return run_application()


if __name__ == "__main__":
    raise SystemExit(main())

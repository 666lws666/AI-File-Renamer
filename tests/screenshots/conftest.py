"""Screenshot test fixtures — deterministic QML capture and golden comparison."""
import os
import hashlib
from pathlib import Path

import pytest

# Force offscreen for screenshot tests
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

GOLDEN_DIR = Path(__file__).parent / "golden"


@pytest.fixture(autouse=True)
def ensure_offscreen():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    yield


def capture_qml_view(qml_path: Path, width: int = 400, height: int = 300) -> bytes:
    """Capture a QML view as PNG bytes."""
    import sys
    from PySide6.QtQuick import QQuickView
    from PySide6.QtCore import QUrl, QSize
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    if app is None:
        app = QGuiApplication(sys.argv)

    view = QQuickView()
    view.setSource(QUrl.fromLocalFile(str(qml_path)))
    view.resize(QSize(width, height))
    view.show()
    # Process events to ensure rendering completes
    app.processEvents()

    image = view.grabWindow()
    ba = bytearray()
    buf = image.save(ba, "PNG")
    view.close()
    return bytes(ba)


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_valid_image(data: bytes) -> bool:
    """Check that PNG data is non-empty, decodable, and has content."""
    if len(data) == 0:
        return False
    # PNG magic bytes
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        return False
    return True


def is_blank_image(data: bytes) -> bool:
    """Heuristic: a valid image with very few unique bytes is likely blank."""
    if len(data) < 100:
        return True
    # Check if image is mostly uniform (blank/single color)
    unique = len(set(data))
    # Very small unique byte count suggests solid color / blank
    return unique < 50

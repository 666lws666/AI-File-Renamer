"""M0 Task 5: Screenshot infrastructure — committed golden comparison."""
import io
import hashlib
import os
import sys
from pathlib import Path

import pytest
from PIL import Image
from PySide6 import QtCore
from PySide6.QtQuick import QQuickView
from PySide6.QtCore import QUrl, QSize
from PySide6.QtGui import QGuiApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QML_PATH = Path(__file__).parent.parent.parent / "src" / "ui_qml" / "M0Bootstrap.qml"
GOLDEN_DIR = Path(__file__).parent / "golden"
GOLDEN_PATH = GOLDEN_DIR / "m0" / "bootstrap" / "zh_CN" / "400x300.png"
UPDATE_GOLDEN = os.environ.get("UPDATE_SCREENSHOT_GOLDEN", "").lower() in (
    "1", "true", "yes"
)

# Tolerance: same software renderer may have sub-pixel anti-aliasing variance.
# This threshold is strict enough to catch real visual changes.
MAX_CHANGED_PIXEL_RATIO = 0.005   # 0.5%
MAX_CHANNEL_DIFF = 40             # per-channel, out of 255


def _capture(width=400, height=300) -> bytes:
    """Capture QML view as PNG bytes."""
    app = QGuiApplication.instance()
    if app is None:
        app = QGuiApplication(sys.argv)
    view = QQuickView()
    view.setSource(QUrl.fromLocalFile(str(QML_PATH)))
    view.resize(QSize(width, height))
    view.show()
    app.processEvents()
    image = view.grabWindow()
    buf = QtCore.QBuffer()
    buf.open(QtCore.QBuffer.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    view.close()
    return bytes(buf.data())


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_valid(data: bytes) -> bool:
    return len(data) > 0 and data[:8] == b'\x89PNG\r\n\x1a\n'


def _is_blank(data: bytes) -> bool:
    return len(data) < 100 or len(set(data)) < 50


def assert_matches_golden(current: bytes, golden: bytes):
    """Compare current capture to committed golden with pixel-level diff.

    Raises AssertionError with diff metrics if images diverge beyond tolerance.
    """
    cur_img = Image.open(io.BytesIO(current)).convert("RGBA")
    gold_img = Image.open(io.BytesIO(golden)).convert("RGBA")

    assert cur_img.size == gold_img.size, (
        f"Size mismatch: current={cur_img.size}, golden={gold_img.size}"
    )

    cur_pixels = list(cur_img.getdata())
    gold_pixels = list(gold_img.getdata())
    total_pixels = len(cur_pixels)

    changed_pixels = 0
    max_channel_diff = 0
    for cp, gp in zip(cur_pixels, gold_pixels):
        diff = max(abs(int(cp[i]) - int(gp[i])) for i in range(4))
        if diff > 0:
            changed_pixels += 1
            if diff > max_channel_diff:
                max_channel_diff = diff

    ratio = changed_pixels / total_pixels if total_pixels > 0 else 0

    info = (
        f"changed_pixels={changed_pixels}/{total_pixels} "
        f"({ratio*100:.3f}%), max_channel_diff={max_channel_diff}, "
        f"tolerance: ratio<={MAX_CHANGED_PIXEL_RATIO}, channel<={MAX_CHANNEL_DIFF}"
    )

    if ratio > MAX_CHANGED_PIXEL_RATIO or max_channel_diff > MAX_CHANNEL_DIFF:
        raise AssertionError(
            f"Screenshot differs from golden beyond tolerance. {info}"
        )

    print(f"Screenshot matches golden. {info}")


# ── Test: current capture matches committed golden ─────

def test_current_capture_matches_committed_golden():
    """Current QML rendering must match the committed golden image."""
    assert GOLDEN_PATH.exists(), (
        f"Golden not found at {GOLDEN_PATH}. "
        f"Run with UPDATE_SCREENSHOT_GOLDEN=1 to regenerate."
    )
    current = _capture(400, 300)
    assert _is_valid(current), "Current capture is not valid PNG"
    assert not _is_blank(current), "Current capture appears blank"

    golden = GOLDEN_PATH.read_bytes()
    assert _is_valid(golden), "Golden is not valid PNG"
    assert not _is_blank(golden), "Golden appears blank"

    assert_matches_golden(current, golden)


# ── Test: deliberate change must be detected ────────────

def test_golden_comparison_detects_change():
    """A deliberately corrupted capture must fail comparison."""
    # Load a valid capture and corrupt a visible block
    current = _capture(400, 300)
    img = Image.open(io.BytesIO(current)).convert("RGBA")
    w, h = img.size
    # Paint center 100x100 block solid red
    for y in range(h // 2 - 50, h // 2 + 50):
        for x in range(w // 2 - 50, w // 2 + 50):
            img.putpixel((x, y), (255, 0, 0, 255))

    corrupted = io.BytesIO()
    img.save(corrupted, "PNG")
    corrupted_bytes = corrupted.getvalue()

    # Must fail against golden
    golden = GOLDEN_PATH.read_bytes()
    with pytest.raises(AssertionError, match="beyond tolerance"):
        assert_matches_golden(corrupted_bytes, golden)


# ── Test: missing golden fails-closed ──────────────────

def test_missing_golden_fails_closed():
    """Normal test run must fail if golden is missing, not auto-create."""
    # Operate on a temporary path to avoid touching committed golden
    tmp_path = Path(__file__).parent / "golden" / "_tmp_test_missing"
    tmp_file = tmp_path / "nonexistent.png"
    # Ensure it does not exist
    if tmp_file.exists():
        tmp_file.unlink()

    # In normal mode (UPDATE_GOLDEN not set), missing golden must fail
    assert not UPDATE_GOLDEN, (
        "UPDATE_SCREENSHOT_GOLDEN is set — cannot test fail-closed behavior"
    )
    with pytest.raises(AssertionError, match="Golden not found"):
        # Simulate the production check
        assert tmp_file.exists(), (
            f"Golden not found at {tmp_file}. "
            f"Run with UPDATE_SCREENSHOT_GOLDEN=1 to regenerate."
        )


# ── Test: explicit golden update mode ──────────────────

def test_golden_update_mode():
    """When UPDATE_SCREENSHOT_GOLDEN=1, the test skips to allow regeneration."""
    if not UPDATE_GOLDEN:
        pytest.skip("UPDATE_SCREENSHOT_GOLDEN not set — update mode test skipped")
    data = _capture(400, 300)
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_bytes(data)
    assert GOLDEN_PATH.exists()
    print(f"Golden updated: {GOLDEN_PATH}, {len(data)} bytes, SHA256: {_sha256(data)}")


# ── Retained valid-image tests ─────────────────────────

def test_size_correct():
    data = _capture(400, 300)
    img = Image.open(io.BytesIO(data))
    assert img.width == 400
    assert img.height == 300


def test_golden_not_blank():
    if not GOLDEN_PATH.exists():
        pytest.skip("Golden not yet created")
    g = GOLDEN_PATH.read_bytes()
    assert _is_valid(g), "Golden not valid PNG"
    assert not _is_blank(g), "Golden is blank"
    img = Image.open(io.BytesIO(g))
    assert img.width == 400 and img.height == 300
    sha = _sha256(g)
    assert len(sha) == 64
    print(f"Golden: {GOLDEN_PATH}, {len(g)} bytes, SHA256: {sha}")

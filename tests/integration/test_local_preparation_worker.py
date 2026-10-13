"""Real source-mode workers and owned synthetic native children, never models."""
import ctypes
import io
from pathlib import Path
import sys
import threading
import time

import pytest

from src.services.local_ai.preparation_protocol import LocalPreparationLimits, PreparationError
from src.services.local_ai.preparation_service import BoundedLocalPreparationService


def prepare(path, **limits):
    service = BoundedLocalPreparationService()
    try:
        return service.prepare(path, limits=LocalPreparationLimits(**limits), quality_mode="economy", deadline=time.monotonic()+30, cancelled=lambda: False)
    finally:
        assert service.close(time.monotonic()+3)


def test_real_worker_unicode_text_and_precise_utf8_limit(tmp_path):
    path = tmp_path / "中文无关文件名.txt"
    path.write_text("真实内容" * 10, encoding="utf-8")
    result = prepare(path, max_text_utf8_bytes=13)
    assert result.text == "真实内容"
    assert result.coverage.text_limit_reason == "utf8_limit"
    assert "text_utf8_limit" in result.warning_codes
    assert path.name not in repr(result)


def test_real_worker_unicode_image_has_visual_not_filename_text(tmp_path):
    from PIL import Image
    path = tmp_path / "不相关名字图片.png"
    Image.new("RGB", (120, 80), "gold").save(path)
    result = prepare(path)
    assert result.text == ""
    assert result.coverage.content_kind == "image" and result.coverage.text_source == "none"
    assert len(result.visuals) == 1 and result.visuals[0].width == 120


@pytest.mark.parametrize("scan", [False, True])
def test_real_worker_pdf_text_and_scan_bounded_pages(tmp_path, scan):
    import pymupdf
    from PIL import Image
    path = tmp_path / "扫描文件.pdf"
    image = io.BytesIO()
    Image.new("RGB", (100, 70), "green").save(image, format="PNG")
    with pymupdf.open() as pdf:
        for i in range(3):
            page = pdf.new_page(width=240, height=160)
            if scan:
                page.insert_image(page.rect, stream=image.getvalue())
            else:
                page.insert_text((20, 30), f"Genuine document content page {i+1}")
        pdf.save(path)
    result = prepare(path, max_pdf_pages=1)
    assert result.coverage.pdf_total_pages == 3
    assert result.coverage.text_page_indices == (0,)
    assert result.coverage.rendered_page_indices == (0,)
    assert len(result.visuals) == 1 and "pdf_page_limit" in result.warning_codes
    if scan:
        assert not result.text and result.coverage.content_kind == "scanned_pdf"
    else:
        assert "Genuine document content page 1" in result.text and "page 2" not in result.text


def test_real_worker_distinct_ordered_video(tmp_path):
    import av
    from PIL import Image
    path = tmp_path / "视频顺序.mp4"
    with av.open(str(path), "w") as output:
        stream = output.add_stream("mpeg4", rate=10)
        stream.width, stream.height, stream.pix_fmt = 96, 64, "yuv420p"
        for n in range(80):
            color = (40 + (n//10)*25, 190-(n//10)*15, 40+(n//10)*20)
            frame = av.VideoFrame.from_image(Image.new("RGB", (96, 64), color))
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)
    result = prepare(path)
    assert len(result.visuals) == 4
    assert len({v.content_digest for v in result.visuals}) == 4
    assert tuple(sorted(result.coverage.video_timestamps_seconds)) == result.coverage.video_timestamps_seconds
    assert result.text == "" and result.effective_quality == "economy"
    assert "video_sampled" in result.warning_codes


@pytest.mark.parametrize("mode,cancel", [("hang", False), ("descendant", True), ("overflow", False)])
def test_real_uncooperative_child_and_descendants_are_finitely_reaped(tmp_path, mode, cancel):
    from src.services.local_ai.native.process import run_bounded
    captured = []
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "local_preparation_worker_fixture.py"
    def runner(executable, arguments, **kwargs):
        kwargs["timeout_seconds"] = .5
        kwargs["stdout_limit"] = 1024
        result = run_bounded(executable, ("-I", str(fixture), mode), **kwargs)
        captured.append(result)
        return result
    service = BoundedLocalPreparationService(_runner=runner)
    event = threading.Event()
    timer = threading.Timer(.25, event.set) if cancel else None
    if timer:
        timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(PreparationError):
            service.prepare(tmp_path / "fake.txt", limits=LocalPreparationLimits(), quality_mode="balanced", deadline=started+5, cancelled=event.is_set)
    finally:
        if timer:
            timer.cancel()
            timer.join()
        assert service.close(time.monotonic()+3)
    assert time.monotonic()-started < 5
    result = captured[0]
    assert result.cleanup_complete and result.pending_owner is None
    assert result.status == ("cancelled" if cancel else "output_limit" if mode == "overflow" else "timeout")
    if mode == "descendant":
        pid = int(result.stdout.strip())
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x100000, False, pid)
        if handle:
            try:
                kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
                # Job active-count zero can precede descendant handle signaling
                # by a scheduler turn; assert finite termination, not a 0ms race.
                assert kernel.WaitForSingleObject(handle, 3000) == 0
            finally:
                kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                kernel.CloseHandle(handle)


def test_real_worker_rejects_empty_sheet_labels_as_content(tmp_path):
    import openpyxl
    path = tmp_path / "empty.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.title = "Invented semantic title"
    workbook.save(path)
    workbook.close()
    result = prepare(path)
    assert result.text == "" and "no_text_content" in result.warning_codes


def test_early_main_dispatch_does_not_import_qt(tmp_path):
    from src.services.local_ai.native.process import run_bounded
    from src.services.local_ai.preparation_protocol import PreparationRequest, encode_request, decode_result
    from src.services.local_ai.preparation_service import _environment
    root = Path(__file__).resolve().parents[2]
    path = tmp_path / "dispatch.txt"
    path.write_text("dispatch content", encoding="utf-8")
    bootstrap = "import sys,runpy;sys.path.insert(0,sys.argv[1]);sys.modules['src.main_qml']=None;sys.argv=['main','--local-preparation-worker-v1',sys.argv[2]];runpy.run_module('src.main',run_name='__main__')"
    request = encode_request(PreparationRequest(str(path), LocalPreparationLimits(), "balanced"))
    result = run_bounded(Path(sys.executable), ("-I", "-c", bootstrap, str(root), request), cwd=root, environment=_environment(), timeout_seconds=10)
    assert result.cleanup_complete and result.exit_code == 0
    assert decode_result(result.stdout).text == "dispatch content"


def test_real_whitespace_source_is_empty_not_false_content(tmp_path):
    path = tmp_path / "blank.txt"
    path.write_text(" \n\t", encoding="utf-8")
    result = prepare(path)
    assert result.text == "" and result.coverage.text_source == "none"


def test_worker_rejects_remote_drive_without_reading(tmp_path, monkeypatch):
    from src.services.local_ai import preparation_worker as worker
    class Function:
        def __call__(self, *args):
            return 4
    class Kernel:
        GetDriveTypeW = Function()
    monkeypatch.setattr(worker.ctypes, "WinDLL", lambda *a, **k: Kernel())
    monkeypatch.setattr(Path, "lstat", lambda *a: pytest.fail("remote file read"))
    with pytest.raises(PreparationError):
        worker._local_source(str(tmp_path / "remote.txt"), 1000)

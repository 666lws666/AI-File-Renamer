"""Explicit additional-resource denial at the actual PyAV open boundary."""
import io
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import pytest
from src.services.media import keyframe_extractor as subject
from src.services.media.image_preprocessor import MediaProcessingError


def test_actual_open_uses_file_object_and_both_nested_io_guards(monkeypatch, tmp_path):
    calls = []
    def opener(source, **kwargs):
        calls.append((source, kwargs))
        raise OSError("synthetic-private-url")
    monkeypatch.setattr(subject.av, "open", opener)
    source = tmp_path / "synthetic.mp4"
    source.write_bytes(b"synthetic")
    with pytest.raises(MediaProcessingError) as caught:
        subject.VideoKeyframeExtractor().extract_file(source, quality_mode="economy")
    assert len(calls) == 1
    stream, options = calls[0]
    assert not isinstance(stream, (str, bytes))
    assert stream.closed
    assert options["options"] == {"protocol_whitelist": ""}
    assert callable(options["io_open"])
    with pytest.raises(OSError, match="^nested_video_io_denied$"):
        options["io_open"]("file:///synthetic-private-url", 0, {"secret": "synthetic-private-url"})
    assert "synthetic-private-url" not in str(caught.value)


def test_nested_rejection_never_retries_permissively(monkeypatch):
    calls = []
    def opener(source, **kwargs):
        calls.append(kwargs)
        kwargs["io_open"]("https://synthetic-private-url", 0, {})
    monkeypatch.setattr(subject.av, "open", opener)
    with pytest.raises(MediaProcessingError) as caught:
        subject.VideoKeyframeExtractor().extract_bytes(b"synthetic", provenance="synthetic", quality_mode="economy")
    assert len(calls) == 1
    assert caught.value.code == "invalid_video"
    assert "synthetic-private-url" not in str(caught.value)


def test_real_hls_guards_block_loopback_library_positive_control(caplog, capsys):
    """Forced HLS is a library diagnostic, not a product auto-detect leak claim."""
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(404)
            self.end_headers()
        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 0.1
    stopped = threading.Event()
    def serve():
        while not stopped.is_set():
            server.handle_request()
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    marker = "synthetic-private-marker.ts"
    data = ("#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:1\n"
            "#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:1,\n"
            f"http://127.0.0.1:{server.server_port}/{marker}\n#EXT-X-ENDLIST\n").encode()
    try:
        # Positive control: deliberate unguarded *library* call with fixed timeout.
        with pytest.raises(subject.av.FFmpegError):
            subject.av.open(io.BytesIO(data), mode="r", format="hls",
                            options={"rw_timeout": "500000"})
        assert requests == ["/" + marker]
        caplog.clear()
        capsys.readouterr()
        with pytest.raises(OSError, match="^nested_video_io_denied$"):
            subject.av.open(io.BytesIO(data), mode="r", format="hls",
                            options={"protocol_whitelist": "", "rw_timeout": "500000"},
                            io_open=subject._deny_nested_io)
        assert requests == ["/" + marker]
        with pytest.raises(MediaProcessingError) as caught:
            subject.VideoKeyframeExtractor().extract_bytes(
                data, provenance="synthetic-playlist", quality_mode="economy")
        assert requests == ["/" + marker]
        assert marker not in str(caught.value)
        captured = capsys.readouterr()
        assert marker not in captured.out + captured.err + caplog.text
    finally:
        stopped.set()
        thread.join(timeout=2)
        server.server_close()
    assert not thread.is_alive()


def test_secondary_file_callback_never_opens_or_returns_content(tmp_path, monkeypatch):
    source = tmp_path / "synthetic-private-marker.ts"
    source.write_bytes(b"synthetic-secret-content")
    def forbidden(*args, **kwargs):
        pytest.fail("The rejecting callback must never open a secondary file")
    monkeypatch.setattr("builtins.open", forbidden)
    with pytest.raises(OSError) as caught:
        subject._deny_nested_io(source.as_uri(), 0, {"secret": "synthetic-secret-content"})
    assert str(caught.value) == "nested_video_io_denied"

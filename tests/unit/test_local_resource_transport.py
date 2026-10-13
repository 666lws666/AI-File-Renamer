"""Direct production transport tests with in-memory HTTP responses."""

import hashlib
import io
import traceback
from urllib.error import URLError

import pytest

from scripts import local_model_probe_resources as probe
from src.services.local_ai import resource_transport as transport


URL = "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/" + "a" * 40 + "/fixture.gguf"


class Response(io.BytesIO):
    status = 200
    headers = {}

    def geturl(self):
        return URL


def resource(body):
    return {"id": "model-q4", "filename": "fixture.gguf", "url": URL,
            "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


def plenty(_):
    return 1024 ** 4


def test_script_and_production_share_implementation():
    for name in ("ResourceError", "ResourceCancelled", "validate_resource",
                 "verify_resource", "fetch_resource", "TrustedRedirectHandler", "urlopen"):
        assert getattr(probe, name) is getattr(transport, name)


def test_production_fetch_publishes_and_reuses(tmp_path):
    body = b"verified public bytes"
    item = resource(body)
    target = transport.fetch_resource(item, tmp_path, opener=lambda *a, **k: Response(body), free_bytes=plenty)
    assert target.read_bytes() == body
    assert transport.verify_resource(target, item)
    assert transport.fetch_resource(item, tmp_path, opener=lambda *a, **k: pytest.fail("network")) == target


def test_production_cancellation_and_resume(tmp_path):
    body = b"x" * (transport.CHUNK_BYTES + 7)
    item = resource(body)
    calls = []

    class CancellingResponse(Response):
        def read(self, size=-1):
            calls.append(True)
            return super().read(size)

    with pytest.raises(transport.ResourceCancelled):
        transport.fetch_resource(item, tmp_path, opener=lambda *a, **k: CancellingResponse(body),
                                 cancelled=lambda: len(calls) >= 2, free_bytes=plenty)
    part = tmp_path / "fixture.gguf.part"
    offset = part.stat().st_size
    assert 0 < offset < len(body)
    requests = []

    def resume(request, *, timeout):
        requests.append(request)
        response = Response(body[offset:])
        response.status = 206
        response.headers = {"Content-Range": f"bytes {offset}-{len(body)-1}/{len(body)}"}
        return response

    assert transport.fetch_resource(item, tmp_path, opener=resume, free_bytes=plenty).read_bytes() == body
    assert requests[0].get_header("Range") == f"bytes={offset}-"
    assert not part.exists()


def test_production_bad_hash_and_transport_error_are_safe(tmp_path):
    body = b"verified public bytes"
    item = resource(body)
    with pytest.raises(transport.ResourceError, match="SHA256"):
        transport.fetch_resource(item, tmp_path, opener=lambda *a, **k: Response(b"x" * len(body)), free_bytes=plenty)
    assert not (tmp_path / item["filename"]).exists()
    assert (tmp_path / "fixture.gguf.part").exists()
    (tmp_path / "fixture.gguf.part").unlink()

    def fail(*args, **kwargs):
        raise URLError("https://cas-bridge.xethub.hf.co/file?signature=TOPSECRET")

    with pytest.raises(transport.ResourceError) as caught:
        transport.fetch_resource(item, tmp_path, opener=fail, free_bytes=plenty)
    assert "TOPSECRET" not in "".join(traceback.format_exception(caught.value))


def test_legacy_ignored_range_still_restarts_download(tmp_path):
    body = b"complete replacement response"
    item = resource(body)
    part = tmp_path / (item["filename"] + ".part")
    part.write_bytes(body[:4])
    requests = []

    def ignored_range(request, **kwargs):
        requests.append(request)
        return Response(body)

    final = transport.fetch_resource(item, tmp_path, opener=ignored_range, free_bytes=plenty)
    assert requests[0].get_header("Range") == "bytes=4-"
    assert final.read_bytes() == body
    assert not part.exists()

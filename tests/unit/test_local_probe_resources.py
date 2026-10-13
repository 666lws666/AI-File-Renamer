"""Offline boundaries for the diagnostic-only public resource fetcher."""

import hashlib
import importlib.util
import io
import json
import traceback
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "local_model_probe_resources.py"
URL = "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/" + "a" * 40 + "/fixture.gguf"


def test_resource_implementation_exists():
    assert SCRIPT.is_file(), "Task 1 resource fetch implementation is missing"


@pytest.fixture
def probe():
    assert SCRIPT.is_file(), "Task 1 resource fetch implementation is missing"
    spec = importlib.util.spec_from_file_location("local_probe_resources_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resource(body=b"verified public bytes"):
    return {"id": "test-model", "filename": "fixture.gguf", "url": URL,
            "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


class Response(io.BytesIO):
    def __init__(self, body, *, status=200, headers=None, url=URL, on_read=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}
        self.url = url
        self.on_read = on_read
        self.read_sizes = []

    def geturl(self):
        return self.url

    def read(self, size=-1):
        self.read_sizes.append(size)
        if self.on_read:
            self.on_read()
        return super().read(size)


def endpoint(response, requests=None):
    def open_stream(request, *, timeout):
        assert isinstance(request, Request)
        assert request.full_url == URL
        assert 0 < timeout <= 60
        assert not any(key.lower() in {"authorization", "cookie", "proxy-authorization"}
                       for key in dict(request.header_items()))
        if requests is not None:
            requests.append(request)
        return response
    return open_stream


def no_network(*args, **kwargs):
    pytest.fail("this operation must not open a network connection")


def plenty(_path):
    return 1024 ** 4


def test_verified_stream_is_published_then_reused_without_network(probe, tmp_path):
    body = b"a" * (2 * probe.CHUNK_BYTES + 17)
    spec = resource(body)
    response = Response(body)
    result = probe.fetch_resource(spec, tmp_path, opener=endpoint(response), free_bytes=plenty)
    assert result == tmp_path / spec["filename"]
    assert result.read_bytes() == body
    assert probe.verify_resource(result, spec)
    assert not result.with_name(result.name + ".part").exists()
    assert response.closed
    assert all(0 < size <= probe.CHUNK_BYTES for size in response.read_sizes)
    assert probe.fetch_resource(spec, tmp_path, opener=no_network, free_bytes=plenty) == result


def test_verification_rejects_missing_size_and_hash_corruption(probe, tmp_path):
    spec = resource()
    target = tmp_path / spec["filename"]
    assert not probe.verify_resource(target, spec)
    target.write_bytes(b"short")
    assert not probe.verify_resource(target, spec)
    target.write_bytes(b"x" * spec["bytes"])
    assert not probe.verify_resource(target, spec)


def test_invalid_existing_final_is_preserved_without_network(probe, tmp_path):
    spec = resource()
    target = tmp_path / spec["filename"]
    target.write_bytes(b"existing user evidence")
    with pytest.raises(probe.ResourceError, match="existing"):
        probe.fetch_resource(spec, tmp_path, opener=no_network, free_bytes=plenty)
    assert target.read_bytes() == b"existing user evidence"


@pytest.mark.parametrize("body", [b"short", b"x" * 21, b"verified public bytesX"])
def test_bad_body_never_publishes_and_preserves_partial(probe, tmp_path, body):
    spec = resource()
    with pytest.raises(probe.ResourceError):
        probe.fetch_resource(spec, tmp_path, opener=endpoint(Response(body)), free_bytes=plenty)
    assert not (tmp_path / spec["filename"]).exists()
    part = tmp_path / (spec["filename"] + ".part")
    assert part.exists()
    assert part.stat().st_size <= spec["bytes"]


@pytest.mark.parametrize("filename", ["../escape", "a/b", "a\\b", "C:escape", "/escape",
                                     ".", "..", "NUL.gguf", "con", "name.", "a\n.gguf"])
def test_unsafe_basename_rejected_before_network(probe, tmp_path, filename):
    spec = dict(resource(), filename=filename)
    with pytest.raises(probe.ResourceError, match="filename"):
        probe.fetch_resource(spec, tmp_path, opener=no_network, free_bytes=plenty)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("url", ["http://huggingface.co/model", "file:///tmp/model",
                                "https://evil.example/model", "https://huggingface.co.evil.example/model",
                                "https://user:secret@huggingface.co/model", URL + "?token=secret",
                                URL + "#fragment", "https://huggingface.co:444/model",
                                "https://huggingface.co/\nmodel"])
def test_untrusted_source_is_rejected_without_network_or_secret_output(probe, tmp_path, url):
    with pytest.raises(probe.ResourceError) as caught:
        probe.fetch_resource(dict(resource(), url=url), tmp_path, opener=no_network, free_bytes=plenty)
    assert "secret" not in str(caught.value)
    assert url not in str(caught.value)


@pytest.mark.parametrize("field,value", [("sha256", "z" * 64), ("sha256", "a" * 63),
                                        ("bytes", 0), ("bytes", -1), ("bytes", True),
                                        ("bytes", 1.5), ("id", "unsafe\nid")])
def test_invalid_manifest_fields_fail_before_network(probe, tmp_path, field, value):
    with pytest.raises(probe.ResourceError):
        probe.fetch_resource(dict(resource(), **{field: value}), tmp_path,
                             opener=no_network, free_bytes=plenty)


def test_insufficient_space_includes_reserve_and_never_opens_network(probe, tmp_path):
    spec = resource()
    with pytest.raises(probe.ResourceError, match="space"):
        probe.fetch_resource(spec, tmp_path, opener=no_network,
                             free_bytes=lambda _: spec["bytes"] + probe.DISK_RESERVE_BYTES - 1)
    assert not (tmp_path / (spec["filename"] + ".part")).exists()


def test_cancellation_before_fetch_leaves_no_download(probe, tmp_path):
    with pytest.raises(probe.ResourceCancelled):
        probe.fetch_resource(resource(), tmp_path, opener=no_network, cancelled=lambda: True)
    assert list(tmp_path.iterdir()) == []


def test_cancellation_keeps_partial_for_correct_range_resume(probe, tmp_path):
    body = b"x" * (2 * probe.CHUNK_BYTES + 9)
    spec = resource(body)
    reads = []
    first = Response(body, on_read=lambda: reads.append(True))
    with pytest.raises(probe.ResourceCancelled):
        probe.fetch_resource(spec, tmp_path, opener=endpoint(first), free_bytes=plenty,
                             cancelled=lambda: len(reads) >= 2)
    part = tmp_path / (spec["filename"] + ".part")
    offset = part.stat().st_size
    assert 0 < offset < len(body)
    assert first.closed
    requests = []
    resumed = Response(body[offset:], status=206,
                       headers={"Content-Range": f"bytes {offset}-{len(body)-1}/{len(body)}"})
    result = probe.fetch_resource(spec, tmp_path, opener=endpoint(resumed, requests), free_bytes=plenty)
    assert requests[0].get_header("Range") == f"bytes={offset}-"
    assert result.read_bytes() == body
    assert not part.exists()


def test_server_ignoring_range_restarts_without_appending(probe, tmp_path):
    body = b"verified public bytes"
    spec = resource(body)
    (tmp_path / (spec["filename"] + ".part")).write_bytes(b"wrong-prefix")
    result = probe.fetch_resource(spec, tmp_path, opener=endpoint(Response(body)), free_bytes=plenty)
    assert result.read_bytes() == body


@pytest.mark.parametrize("content_range", [None, "bytes 0-20/21", "bytes 4-20/22",
                                        "bytes 4-19/21", "bytes 4-20/*", "nonsense"])
def test_invalid_resume_range_preserves_existing_partial(probe, tmp_path, content_range):
    spec = resource()
    part = tmp_path / (spec["filename"] + ".part")
    part.write_bytes(b"veri")
    headers = {} if content_range is None else {"Content-Range": content_range}
    with pytest.raises(probe.ResourceError, match="range"):
        probe.fetch_resource(spec, tmp_path, opener=endpoint(Response(b"bad", status=206, headers=headers)),
                             free_bytes=plenty)
    assert part.read_bytes() == b"veri"
    assert not (tmp_path / spec["filename"]).exists()


def test_complete_valid_partial_publishes_without_network(probe, tmp_path):
    body = b"verified public bytes"
    spec = resource(body)
    part = tmp_path / (spec["filename"] + ".part")
    part.write_bytes(body)
    result = probe.fetch_resource(spec, tmp_path, opener=no_network, free_bytes=plenty)
    assert result.read_bytes() == body
    assert not part.exists()


@pytest.mark.parametrize("body", [b"x" * 21, b"x" * 22])
def test_invalid_complete_or_oversize_partial_is_preserved(probe, tmp_path, body):
    spec = resource()
    part = tmp_path / (spec["filename"] + ".part")
    part.write_bytes(body)
    with pytest.raises(probe.ResourceError):
        probe.fetch_resource(spec, tmp_path, opener=no_network, free_bytes=plenty)
    assert part.read_bytes() == body


@pytest.mark.parametrize("url", ["http://release-assets.githubusercontent.com/file",
                                "https://attacker.example/file?token=secret",
                                "https://huggingface.co.attacker.example/file",
                                "https://user:secret@cas-bridge.xethub.hf.co/file"])
def test_redirect_handler_rejects_unsafe_target_before_following(probe, url):
    handler = probe.TrustedRedirectHandler()
    with pytest.raises(probe.ResourceError) as caught:
        handler.redirect_request(Request(URL), None, 302, "found", {}, url)
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize("url", ["https://release-assets.githubusercontent.com/file?sig=secret",
                                "https://cas-bridge.xethub.hf.co/file?sig=secret",
                                "https://cdn-lfs.huggingface.co/file",
                                "https://cdn-lfs-us-1.hf.co/file"])
def test_redirect_handler_accepts_only_public_provider_https(probe, url):
    redirect = probe.TrustedRedirectHandler().redirect_request(Request(URL), None, 302, "found", {}, url)
    assert redirect.full_url == url
    assert redirect.get_header("Authorization") is None
    assert redirect.get_header("Cookie") is None


@pytest.mark.parametrize("host", ["us.aws.cdn.hf.co", "us.gcp.cdn.hf.co"])
def test_official_hf_cloud_cdn_redirect_is_accepted(probe, host):
    url = f"https://{host}/fixture.gguf?signature=public-cdn-signature"
    redirect = probe.TrustedRedirectHandler().redirect_request(Request(URL), None, 302, "found", {}, url)
    assert redirect.full_url == url


@pytest.mark.parametrize("host", ["us.aws.cdn.hf.co", "us.gcp.cdn.hf.co"])
def test_official_hf_cloud_cdn_is_not_a_source_host(probe, tmp_path, host):
    with pytest.raises(probe.ResourceError):
        probe.fetch_resource(dict(resource(), url=f"https://{host}/fixture.gguf"),
                             tmp_path, opener=no_network, free_bytes=plenty)


@pytest.mark.parametrize("host", ["us.aws.cdn.hf.co", "us.gcp.cdn.hf.co"])
@pytest.mark.parametrize("pattern", ["{host}.evil.example", "child.{host}", "evil-{host}"])
def test_similar_hf_cloud_cdn_redirect_is_rejected(probe, host, pattern):
    url = "https://" + pattern.format(host=host) + "/fixture.gguf"
    with pytest.raises(probe.ResourceError):
        probe.TrustedRedirectHandler().redirect_request(Request(URL), None, 302, "found", {}, url)


def test_untrusted_final_response_url_rejected_without_writing(probe, tmp_path):
    response = Response(b"verified public bytes", url="https://attacker.example/file?token=secret")
    with pytest.raises(probe.ResourceError):
        probe.fetch_resource(resource(), tmp_path, opener=endpoint(response), free_bytes=plenty)
    assert list(tmp_path.iterdir()) == []
    assert response.closed


def test_transport_error_is_sanitized_without_signed_url_exception_chain(probe, tmp_path):
    def failed_opener(request, *, timeout):
        raise URLError("https://cas-bridge.xethub.hf.co/file?signature=TOPSECRET")
    with pytest.raises(probe.ResourceError) as caught:
        probe.fetch_resource(resource(), tmp_path, opener=failed_opener, free_bytes=plenty)
    assert "TOPSECRET" not in "".join(traceback.format_exception(caught.value))


def test_read_timeout_preserves_downloaded_prefix_and_closes_stream(probe, tmp_path):
    spec = resource(b"x" * (probe.CHUNK_BYTES + 9))
    reads = []

    def timeout_after_first_chunk():
        reads.append(True)
        if len(reads) > 1:
            raise TimeoutError("signed URL contains TOPSECRET")

    response = Response(b"x" * spec["bytes"], on_read=timeout_after_first_chunk)
    with pytest.raises(probe.ResourceError) as caught:
        probe.fetch_resource(spec, tmp_path, opener=endpoint(response), free_bytes=plenty)
    assert "TOPSECRET" not in "".join(traceback.format_exception(caught.value))
    assert response.closed
    assert not (tmp_path / spec["filename"]).exists()
    assert (tmp_path / (spec["filename"] + ".part")).read_bytes() == b"x" * probe.CHUNK_BYTES


def test_disk_reserve_is_checked_again_before_stream_writes(probe, tmp_path):
    checks = []

    def decreasing_space(_path):
        checks.append(True)
        return 1024 ** 4 if len(checks) == 1 else probe.DISK_RESERVE_BYTES

    with pytest.raises(probe.ResourceError, match="space"):
        probe.fetch_resource(resource(), tmp_path, opener=endpoint(Response(b"verified public bytes")),
                             free_bytes=decreasing_space)
    assert not (tmp_path / "fixture.gguf").exists()
    assert (tmp_path / "fixture.gguf.part").read_bytes() == b""


def test_partial_hardlink_is_not_followed_or_truncated(probe, tmp_path):
    original = tmp_path / "original"
    original.write_bytes(b"user bytes")
    (tmp_path / "fixture.gguf.part").hardlink_to(original)
    with pytest.raises(probe.ResourceError, match="unsafe partial"):
        probe.fetch_resource(resource(), tmp_path, opener=no_network, free_bytes=plenty)
    assert original.read_bytes() == b"user bytes"


def test_final_created_during_fetch_is_not_overwritten(probe, tmp_path):
    final = tmp_path / "fixture.gguf"

    def create_concurrent_final():
        if not final.exists():
            final.write_bytes(b"concurrent user bytes")

    response = Response(b"verified public bytes", on_read=create_concurrent_final)
    with pytest.raises(probe.ResourceError, match="existing final"):
        probe.fetch_resource(resource(), tmp_path, opener=endpoint(response), free_bytes=plenty)
    assert final.read_bytes() == b"concurrent user bytes"
    assert (tmp_path / "fixture.gguf.part").read_bytes() == b"verified public bytes"


@pytest.mark.parametrize("headers", [{"Content-Length": "1"}, {"Content-Length": "nonsense"},
                                     {"Content-Encoding": "gzip"}, {"Content-Range": "bytes 0-20/21"}])
def test_bad_response_metadata_never_creates_partial(probe, tmp_path, headers):
    with pytest.raises(probe.ResourceError):
        probe.fetch_resource(resource(), tmp_path, opener=endpoint(Response(b"verified public bytes", headers=headers)),
                             free_bytes=plenty)
    assert list(tmp_path.iterdir()) == []


def test_cli_defaults_to_offline_verification(probe, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(probe, "DEFAULT_DESTINATION", tmp_path)
    monkeypatch.setattr(probe, "fetch_resource", no_network)
    assert probe.main(["--only", "runtime-cpu"]) == 1
    output = capsys.readouterr().out
    assert "runtime-cpu" in output and "NOT_VERIFIED" in output
    assert "https://" not in output


def test_real_manifest_is_fixed_and_validates_without_network(probe):
    manifest = json.loads((ROOT / "resources/local-models/qwen35-4b-feasibility.json").read_text(encoding="utf-8"))
    assert {item["id"] for item in manifest["resources"]} == {"runtime-cpu", "model-q4", "vision-f16"}
    for item in manifest["resources"]:
        probe.validate_resource(item)

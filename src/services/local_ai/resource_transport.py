"""Pinned public-resource transport for an exclusively owned destination.

The caller must separately own and exclusively lock the destination directory.
This low-level transport is not an arbitrary-folder download API.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


CHUNK_BYTES = 1024 * 1024
DISK_RESERVE_BYTES = 64 * 1024 * 1024
SOCKET_TIMEOUT_SECONDS = 30
SOURCE_HOSTS = {"github.com", "huggingface.co"}
REDIRECT_HOSTS = SOURCE_HOSTS | {
    "release-assets.githubusercontent.com", "objects.githubusercontent.com",
    "cdn-lfs.huggingface.co", "cdn-lfs.hf.co", "cdn-lfs-us-1.hf.co",
    "cdn-lfs-eu-1.hf.co", "cas-bridge.xethub.hf.co",
    "us.aws.cdn.hf.co", "us.gcp.cdn.hf.co",
}
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    prefix + str(number) for prefix in ("COM", "LPT") for number in range(1, 10)
}


class ResourceError(RuntimeError):
    """Safe diagnostic message containing no remote URL or response text."""

    def __init__(self, *args, code="TRANSFER_FAILED"):
        super().__init__(*args)
        self.code = code


class ResourceCancelled(ResourceError):
    """Cancellation preserves any partial download."""


def _validate_url(url, *, source=False):
    if not isinstance(url, str) or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise ResourceError("unsafe resource URL")
    try:
        parsed = urlsplit(url)
        safe = (parsed.scheme == "https" and parsed.hostname in (SOURCE_HOSTS if source else REDIRECT_HOSTS)
                and parsed.port in (None, 443) and parsed.username is None and parsed.password is None
                and not parsed.fragment and (not source or not parsed.query))
    except ValueError:
        raise ResourceError("unsafe resource URL") from None
    if not safe:
        raise ResourceError("unsafe resource URL")


def validate_resource(resource):
    """Validate metadata before filesystem writes or network use."""
    if not isinstance(resource, dict):
        raise ResourceError("invalid resource metadata")
    filename = resource.get("filename")
    if (not isinstance(filename, str) or not SAFE_NAME.fullmatch(filename)
            or filename.endswith(".") or filename.split(".")[0].upper() in RESERVED_NAMES):
        raise ResourceError("unsafe resource filename")
    identifier = resource.get("id")
    if not isinstance(identifier, str) or not SAFE_NAME.fullmatch(identifier):
        raise ResourceError("invalid resource identifier")
    size = resource.get("bytes")
    if type(size) is not int or size <= 0:
        raise ResourceError("invalid resource byte count")
    digest = resource.get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ResourceError("invalid resource SHA256")
    _validate_url(resource.get("url"), source=True)


class TrustedRedirectHandler(HTTPRedirectHandler):
    """Reject unsafe locations before urllib can send a follow-up request."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_url(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            for header in ("Authorization", "Cookie", "Proxy-Authorization"):
                redirected.remove_header(header)
        return redirected


def urlopen(request, *, timeout=SOCKET_TIMEOUT_SECONDS):
    """Isolated opener: no ambient proxy credentials, auth or cookie handlers."""
    _validate_url(request.full_url, source=True)
    return build_opener(ProxyHandler({}), TrustedRedirectHandler()).open(request, timeout=timeout)


def _cancel(cancelled):
    if cancelled():
        raise ResourceCancelled("resource preparation cancelled; partial retained")


def _plain_file(path):
    return (path.is_file() and not path.is_symlink() and not path.is_junction()
            and path.stat().st_nlink == 1)


def _digest(path, cancelled, *, owned_store=None):
    digest = hashlib.sha256()
    source = owned_store.open_file(path.name) if owned_store else path.open("rb")
    with source as stream:
        while True:
            _cancel(cancelled)
            chunk = stream.read(CHUNK_BYTES)
            _cancel(cancelled)
            if not chunk:
                return digest
            digest.update(chunk)


def verify_resource(path: Path, resource: dict) -> bool:
    validate_resource(resource)
    try:
        path = Path(path)
        return (_plain_file(path) and path.stat().st_size == resource["bytes"]
                and _digest(path, lambda: False).hexdigest() == resource["sha256"])
    except OSError:
        return False


def _space(destination, required, free_bytes):
    usage = free_bytes(destination)
    available = usage.free if hasattr(usage, "free") else usage
    if available < required + DISK_RESERVE_BYTES:
        raise ResourceError("insufficient disk space including safety reserve", code="INSUFFICIENT_SPACE")


def _publish(part, final):
    # A same-volume hard-link publishes atomically without overwriting a file
    # created since the initial cache check (unlike POSIX rename/replace).
    try:
        os.link(part, final)
    except FileExistsError:
        raise ResourceError("existing final appeared during preparation; partial retained") from None
    part.unlink()
    return final


def _response_mode(response, offset, total):
    _validate_url(response.geturl())
    headers = response.headers
    if headers.get("Content-Encoding", "identity").lower() != "identity":
        raise ResourceError("unexpected content encoding")
    status = response.status
    if status == 206:
        value = headers.get("Content-Range", "")
        expected = f"bytes {offset}-{total - 1}/{total}"
        if not offset or value != expected:
            raise ResourceError("invalid resume content range")
        remaining = total - offset
    elif status == 200:
        if headers.get("Content-Range") is not None:
            raise ResourceError("unexpected response content range")
        remaining = total
        offset = 0
    else:
        raise ResourceError("unexpected resource HTTP status")
    length = headers.get("Content-Length")
    if length is not None and (not re.fullmatch(r"[0-9]+", length) or int(length) != remaining):
        raise ResourceError("unexpected response byte count")
    return offset


def fetch_resource(resource: dict, destination: Path, *, opener=urlopen,
                   cancelled=lambda: False, free_bytes=shutil.disk_usage,
                   progress=None, owned_store=None) -> Path:
    """Verify/reuse or fetch to destination/filename; retain partials on failure.

    The destination must already be exclusively owned and locked by the caller.
    Injected openers are for controlled offline tests. The default opener enforces
    the redirect policy before every request. All streams have bounded reads and
    socket timeouts; cancellation is checked before and after each read.
    ``owned_store`` supplies pinned file operations while its caller holds its
    lease; without it, the original exclusively-owned-directory contract applies.
    """
    validate_resource(resource)
    _cancel(cancelled)
    destination = Path(destination)
    final = destination / resource["filename"]
    part = destination / (resource["filename"] + ".part")
    total = resource["bytes"]

    def exists(path):
        return owned_store.exists(path.name) if owned_store else path.exists() or path.is_symlink()

    def size(path):
        return owned_store.size(path.name) if owned_store else path.stat().st_size

    def publish():
        return owned_store.publish(part.name, final.name) if owned_store else _publish(part, final)

    try:
        if exists(final):
            if ((owned_store is not None or _plain_file(final)) and size(final) == total
                    and _digest(final, cancelled, owned_store=owned_store).hexdigest() == resource["sha256"]):
                return final
            raise ResourceError("existing final resource failed verification; preserved")
        if owned_store is None:
            destination.mkdir(parents=True, exist_ok=True)
        offset = 0
        digest = hashlib.sha256()
        if exists(part):
            if owned_store is None and not _plain_file(part):
                raise ResourceError("unsafe partial file; preserved")
            offset = size(part)
            if offset > total:
                raise ResourceError("oversize partial file; preserved")
            digest = _digest(part, cancelled, owned_store=owned_store)
            if offset == total:
                if digest.hexdigest() != resource["sha256"]:
                    raise ResourceError("partial SHA256 mismatch; preserved")
                _cancel(cancelled)
                return publish()
        _space(destination, total - offset, free_bytes)
        _cancel(cancelled)
        headers = {"Accept-Encoding": "identity", "User-Agent": "Xuxia-Local-Resource-Probe/1"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = Request(resource["url"], headers=headers)
        with opener(request, timeout=SOCKET_TIMEOUT_SECONDS) as response:
            start = _response_mode(response, offset, total)
            if start != offset:
                if owned_store is not None:
                    raise ResourceError("resource resume not honored; explicit restart required; partial retained")
                _space(destination, total, free_bytes)
                digest = hashlib.sha256()
            offset = start
            _cancel(cancelled)
            output = (owned_store.open_file(part.name, "ab" if start else "wb")
                      if owned_store else part.open("ab" if start else "wb"))
            with output as stream:
                while True:
                    _cancel(cancelled)
                    chunk = response.read(min(CHUNK_BYTES, total - offset + 1))
                    _cancel(cancelled)
                    if not chunk:
                        break
                    if not isinstance(chunk, bytes) or len(chunk) > total - offset:
                        raise ResourceError("resource exceeded pinned byte count; partial retained")
                    _space(destination, total - offset, free_bytes)
                    if owned_store is not None:
                        owned_store.assert_safe()
                    stream.write(chunk)
                    digest.update(chunk)
                    offset += len(chunk)
                    if progress is not None:
                        progress(resource["id"], offset, total)
                stream.flush()
                os.fsync(stream.fileno())
        if offset != total:
            raise ResourceError("resource shorter than pinned byte count; partial retained")
        if digest.hexdigest() != resource["sha256"]:
            raise ResourceError("resource SHA256 mismatch; partial retained")
        _cancel(cancelled)
        return publish()
    except ResourceError:
        raise
    except (OSError, ValueError):
        # urllib errors can embed signed CDN URLs. Never surface their text or
        # chained traceback. Existing final and partial bytes remain untouched.
        raise ResourceError("resource transport or filesystem failure; partial retained") from None

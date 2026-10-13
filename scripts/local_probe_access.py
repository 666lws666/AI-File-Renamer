
"""Strict validation of one fixed access-probe child record; no native imports."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.local_probe_process import ProcessResult


_TOP = frozenset(("protocol", "version", "mode", "file_allowed", "file_denied", "loopback", "external"))
_FILE = frozenset(("attempted", "opened", "open_error", "read_attempted", "read_error", "content_ok", "close_ok"))
_SOCKET = frozenset(("attempted", "socket_created", "socket_error", "connect_error", "poll_error", "timed_out", "send_error", "sent_bytes", "close_ok"))


class AccessValidationError(ValueError):
    """Only a fixed code is exposed; raw child bytes are never included."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class FileEvidence:
    attempted: bool
    opened: bool
    open_error: int | None
    read_attempted: bool
    read_error: int | None
    content_ok: bool
    close_ok: bool


@dataclass(frozen=True)
class SocketEvidence:
    attempted: bool
    socket_created: bool
    socket_error: int | None
    connect_error: int | None
    poll_error: int | None
    timed_out: bool
    send_error: int | None
    sent_bytes: int
    close_ok: bool


@dataclass(frozen=True)
class AccessEvidence:
    protocol: str
    version: int
    mode: str
    file_allowed: FileEvidence
    file_denied: FileEvidence
    loopback: SocketEvidence
    external: SocketEvidence
    package_sid: str | None


def _fail(code: str):
    raise AccessValidationError(code)


def _pairs(items):
    obj = {}
    for key, value in items:
        if key in obj:
            _fail("json_duplicate")
        obj[key] = value
    return obj


def _exact_object(value, keys, code):
    if type(value) is not dict or value.keys() != keys:
        _fail(code)


def _error(value, code):
    if value is not None and (type(value) is not int or value < 0 or value > 0xFFFFFFFF):
        _fail(code)


def _file(value):
    _exact_object(value, _FILE, "file_schema")
    for name in ("attempted", "opened", "read_attempted", "content_ok", "close_ok"):
        if type(value[name]) is not bool:
            _fail("file_type")
    for name in ("open_error", "read_error"):
        _error(value[name], "file_type")
    return FileEvidence(**value)


def _socket(value):
    _exact_object(value, _SOCKET, "socket_schema")
    for name in ("attempted", "socket_created", "timed_out", "close_ok"):
        if type(value[name]) is not bool:
            _fail("socket_type")
    for name in ("socket_error", "connect_error", "poll_error", "send_error"):
        _error(value[name], "socket_type")
    if type(value["sent_bytes"]) is not int or not 0 <= value["sent_bytes"] <= 26:
        _fail("socket_type")
    return SocketEvidence(**value)


def _read_file_ok(file):
    return (file.attempted is True and file.opened is True and file.open_error is None
            and file.read_attempted is True and file.read_error is None
            and file.content_ok is True and file.close_ok is True)


def _denied_file_ok(file):
    return (file.attempted is True and file.opened is False and file.open_error == 5
            and file.read_attempted is False and file.read_error is None
            and file.content_ok is False and file.close_ok is True)


def _connected_socket_ok(socket):
    return (socket.attempted is True and socket.socket_created is True
            and socket.socket_error is None and socket.connect_error == 0
            and socket.poll_error is None and socket.timed_out is False
            and socket.send_error == 0 and socket.sent_bytes == 26 and socket.close_ok is True)


def _denied_socket_ok(socket):
    return (socket.attempted is True and socket.socket_created is True
            and socket.socket_error is None and socket.connect_error == 10013
            and socket.poll_error is None and socket.timed_out is False
            and socket.send_error is None and socket.sent_bytes == 0 and socket.close_ok is True)


def _unattempted_socket_ok(socket):
    return (socket.attempted is False and socket.socket_created is False
            and socket.socket_error is None and socket.connect_error is None
            and socket.poll_error is None and socket.timed_out is False
            and socket.send_error is None and socket.sent_bytes == 0 and socket.close_ok is True)


def validate_access_result(result: ProcessResult, *, mode: str,
                           expected_sid: str | None = None) -> AccessEvidence:
    """Require exact completed facts; does not prove parent nonce receipt or isolation."""
    if type(mode) is not str or mode not in ("ordinary", "contained"):
        _fail("mode")
    if result.status != "completed" or type(result.exit_code) is not int or result.exit_code != 0:
        _fail("process")
    if result.cleanup_complete is not True:
        _fail("cleanup")
    if type(result.stderr) is not bytes or result.stderr:
        _fail("stderr")
    raw = result.stdout
    if type(raw) is not bytes or not 2 <= len(raw) <= 4096 or not raw.endswith(b"\r\n"):
        _fail("stdout")
    try:
        source = raw[:-2].decode("ascii")
        data = json.loads(source, object_pairs_hook=_pairs)
    except AccessValidationError:
        raise
    except (UnicodeError, ValueError, TypeError, RecursionError):
        _fail("json")
    _exact_object(data, _TOP, "schema")
    if (type(data["protocol"]) is not str or data["protocol"] != "xuxia-appcontainer-access"
            or type(data["version"]) is not int or data["version"] != 1
            or type(data["mode"]) is not str or data["mode"] != mode):
        _fail("header")
    if json.dumps(data, ensure_ascii=True, separators=(",", ":")) != source:
        _fail("json_canonical")
    evidence = AccessEvidence(data["protocol"], data["version"], mode,
                              _file(data["file_allowed"]), _file(data["file_denied"]),
                              _socket(data["loopback"]), _socket(data["external"]), None)
    if not _read_file_ok(evidence.file_allowed):
        _fail("allowed_file")
    if mode == "ordinary":
        if not _read_file_ok(evidence.file_denied):
            _fail("denied_control")
        if not _connected_socket_ok(evidence.loopback):
            _fail("loopback_control")
        if not _unattempted_socket_ok(evidence.external):
            _fail("external_control")
        return evidence
    if type(expected_sid) is not str or not expected_sid:
        _fail("expected_sid")
    token = result.token_evidence
    if (token is None or getattr(token, "package_sid", None) != expected_sid
            or getattr(token, "is_appcontainer", None) is not True
            or type(getattr(token, "capability_count", None)) is not int
            or token.capability_count != 0):
        _fail("token")
    if not _denied_file_ok(evidence.file_denied):
        _fail("denied_file")
    if not _denied_socket_ok(evidence.loopback):
        _fail("loopback_denial")
    if not _denied_socket_ok(evidence.external):
        _fail("external_denial")
    return AccessEvidence(evidence.protocol, evidence.version, mode,
                          evidence.file_allowed, evidence.file_denied,
                          evidence.loopback, evidence.external, expected_sid)

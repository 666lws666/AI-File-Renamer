"""Pure protocol tests: synthetic child evidence is not an OS measurement."""
import json
from types import SimpleNamespace

import pytest

from scripts.local_probe_access import AccessValidationError, validate_access_result


SID = "S-1-15-2-1-2-3-4-5-6-7"


def record(mode):
    allowed = dict(attempted=True, opened=True, open_error=None,
                   read_attempted=True, read_error=None, content_ok=True, close_ok=True)
    denied = (allowed.copy() if mode == "ordinary" else
              dict(attempted=True, opened=False, open_error=5,
                   read_attempted=False, read_error=None, content_ok=False, close_ok=True))
    loopback = dict(attempted=True, socket_created=True, socket_error=None,
                    connect_error=0 if mode == "ordinary" else 10013,
                    poll_error=None, timed_out=False, send_error=None if mode == "contained" else 0,
                    sent_bytes=0 if mode == "contained" else 26, close_ok=True)
    external = (dict(attempted=False, socket_created=False, socket_error=None,
                     connect_error=None, poll_error=None, timed_out=False,
                     send_error=None, sent_bytes=0, close_ok=True)
                if mode == "ordinary" else
                dict(attempted=True, socket_created=True, socket_error=None,
                     connect_error=10013, poll_error=None, timed_out=False,
                     send_error=None, sent_bytes=0, close_ok=True))
    return dict(protocol="xuxia-appcontainer-access", version=1, mode=mode,
                file_allowed=allowed, file_denied=denied,
                loopback=loopback, external=external)


def result(data, *, token=None, **changes):
    base = dict(status="completed", exit_code=0,
                stdout=json.dumps(data, separators=(",", ":")).encode("ascii") + b"\r\n",
                stderr=b"", cleanup_complete=True, token_evidence=token)
    base.update(changes)
    return SimpleNamespace(**base)


def good(mode):
    token = (SimpleNamespace(package_sid=SID, is_appcontainer=True, capability_count=0)
             if mode == "contained" else None)
    return result(record(mode), token=token)


@pytest.mark.parametrize("mode", ["ordinary", "contained"])
def test_accepts_complete_measurement(mode):
    evidence = validate_access_result(good(mode), mode=mode,
                                      expected_sid=SID if mode == "contained" else None)
    assert evidence.mode == mode
    assert evidence.file_allowed.content_ok is True
    assert evidence.loopback.connect_error == (0 if mode == "ordinary" else 10013)
    with pytest.raises(Exception):
        evidence.mode = "changed"


@pytest.mark.parametrize("path,value", [
    ("file_allowed.opened", False), ("file_allowed.content_ok", False),
    ("file_allowed.read_attempted", False), ("file_allowed.close_ok", False),
    ("file_denied.opened", True), ("file_denied.open_error", 2),
    ("file_denied.open_error", 32), ("file_denied.read_attempted", True),
    ("file_denied.content_ok", True), ("loopback.socket_created", False),
    ("loopback.socket_error", 10013), ("loopback.poll_error", 10013),
    ("loopback.connect_error", 0), ("loopback.connect_error", 10060),
    ("loopback.connect_error", 10061), ("loopback.connect_error", 10051),
    ("loopback.connect_error", True), ("loopback.timed_out", True),
    ("loopback.send_error", 0), ("loopback.sent_bytes", 1),
    ("loopback.close_ok", False), ("external.attempted", False),
    ("external.connect_error", 10061), ("external.sent_bytes", 1),
])
def test_rejects_contained_alternatives(path, value):
    data = record("contained")
    group, field = path.split(".")
    data[group][field] = value
    with pytest.raises(AccessValidationError):
        validate_access_result(result(data, token=good("contained").token_evidence),
                               mode="contained", expected_sid=SID)


@pytest.mark.parametrize("path,value", [
    ("file_allowed.open_error", 5), ("file_denied.read_error", 5),
    ("loopback.connect_error", 10013), ("loopback.sent_bytes", 25),
    ("loopback.send_error", 10013), ("loopback.timed_out", True),
    ("external.attempted", True), ("external.socket_created", True),
])
def test_rejects_ordinary_alternatives(path, value):
    data = record("ordinary")
    group, field = path.split(".")
    data[group][field] = value
    with pytest.raises(AccessValidationError):
        validate_access_result(result(data), mode="ordinary")


@pytest.mark.parametrize("raw", [
    b'{}\r\n', b'{"protocol":1,"protocol":2}\r\n', b'{}\n',
    b'\xef\xbb\xbf{}\r\n', b'{}\r\nextra', b'{}\r\n{}\r\n',
    b' ' * 4097,
])
def test_rejects_malformed_wire(raw):
    with pytest.raises(AccessValidationError):
        validate_access_result(good("ordinary").__class__(**{**vars(good("ordinary")), "stdout": raw}), mode="ordinary")


def test_rejects_deeply_nested_json_with_fixed_error(monkeypatch):
    raw = b"[" * 1500 + b"]" * 1500 + b"\r\n"
    candidate = good("ordinary")
    candidate.stdout = raw
    def depth_limited_decoder(*args, **kwargs):
        raise RecursionError("decoder nesting limit")
    monkeypatch.setattr("scripts.local_probe_access.json.loads", depth_limited_decoder)
    with pytest.raises(AccessValidationError) as caught:
        validate_access_result(candidate, mode="ordinary")
    assert caught.value.code == "json"


@pytest.mark.parametrize("change", [
    dict(status="timeout"), dict(exit_code=1), dict(exit_code=False),
    dict(stderr=b"x"), dict(cleanup_complete=False),
])
def test_rejects_process_failure(change):
    with pytest.raises(AccessValidationError):
        validate_access_result(result(record("ordinary"), **change), mode="ordinary")


@pytest.mark.parametrize("token,sid", [
    (None, SID), (SimpleNamespace(package_sid="wrong", is_appcontainer=True, capability_count=0), SID),
    (SimpleNamespace(package_sid=SID, is_appcontainer=False, capability_count=0), SID),
    (SimpleNamespace(package_sid=SID, is_appcontainer=True, capability_count=1), SID),
    (SimpleNamespace(package_sid=SID, is_appcontainer=True, capability_count=False), SID),
    (SimpleNamespace(package_sid=SID, is_appcontainer=True, capability_count=0), None),
])
def test_rejects_missing_or_wrong_token(token, sid):
    with pytest.raises(AccessValidationError):
        validate_access_result(result(record("contained"), token=token), mode="contained", expected_sid=sid)


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(extra=1), lambda d: d.pop("external"),
    lambda d: d["loopback"].update(extra=1),
    lambda d: d["file_allowed"].pop("close_ok"),
    lambda d: d.update(version=True), lambda d: d.update(mode="contained"),
])
def test_rejects_schema_mutations(mutation):
    data = record("ordinary")
    mutation(data)
    with pytest.raises(AccessValidationError):
        validate_access_result(result(data), mode="ordinary")

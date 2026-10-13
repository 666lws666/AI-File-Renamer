"""Owned staging tests; native effects are replaced at the OS boundary."""
from dataclasses import replace
from hashlib import sha256
from importlib import import_module
import ntpath

import pytest


SID = "S-1-15-2-1-2-3-4-5-6-7"
USER = "S-1-5-21-11-22-33-1001"
PARENT = r"C:\qa"
DATA = b"MZ trusted fixed hello bytes"
DIGEST = sha256(DATA).hexdigest()


def module():
    try:
        return import_module("scripts.local_probe_stage")
    except ModuleNotFoundError:
        pytest.fail("owned staging helper is not implemented")


class FakeNative:
    """Small in-memory disk with handle lifetime and delete-on-close semantics."""
    def __init__(self, m):
        self.m = m
        self.objects = {}
        self.handles = {}
        self.calls = []
        self.next_id = 10
        self.next_handle = 1
        self.fail = {}
        self.hooks = {}
        self.fs = "NTFS"
        self.short_write = False
        self._add("C:\\", True)
        self._add(PARENT, True)

    def _add(self, path, directory, security=None):
        self.next_id += 1
        obj = {"path": path, "directory": directory, "security": security,
               "data": b"", "id": self.next_id, "links": 1,
               "reparse": False, "pending": False}
        self.objects[path] = obj
        return obj

    def _call(self, name, *args):
        self.calls.append((name, *args))
        if name in self.hooks:
            self.hooks[name](self, *args)
        if self.fail.get(name, 0):
            self.fail[name] -= 1
            raise OSError(5, "sensitive arbitrary exception must not escape")

    def current_user(self):
        self._call("current_user")
        return USER

    def volume(self, path):
        self._call("volume", path)
        return self.fs, 123, 3

    def mkdir(self, path, security):
        self._call("mkdir", path, security)
        if path in self.objects:
            raise FileExistsError()
        self._add(path, True, security)

    def open(self, path, access, share, creation, flags, security=None):
        self._call("open", path, access, share, creation, flags, security)
        if creation == self.m.CREATE_NEW:
            if path in self.objects:
                raise FileExistsError()
            self._add(path, False, security)
        if path not in self.objects:
            raise FileNotFoundError()
        obj = self.objects[path]
        # Windows sharing checks apply in both directions.
        for other, old_access, old_share in self.handles.values():
            if other is obj:
                for rights, flag in [(self.m.GENERIC_READ, 1),
                                     (self.m.GENERIC_WRITE, 2), (self.m.DELETE, 4)]:
                    if (access & rights and not old_share & flag
                            or old_access & rights and not share & flag):
                        raise OSError(32, "sharing violation")
        handle = self.next_handle
        self.next_handle += 1
        self.handles[handle] = (obj, access, share)
        return handle

    def info(self, handle):
        self._call("info", handle)
        obj = self.handles[handle][0]
        return self.m.ObjectInfo(123, obj["id"], len(obj["data"]), obj["links"],
                                obj["directory"], obj["reparse"], True)

    def security(self, handle):
        self._call("security", handle)
        return self.handles[handle][0]["security"]

    def final_path(self, handle):
        self._call("final_path", handle)
        return self.handles[handle][0]["path"]

    def write(self, handle, data):
        self._call("write", handle)
        count = len(data) - 1 if self.short_write else len(data)
        self.handles[handle][0]["data"] = data[:count]
        return count

    def flush(self, handle):
        self._call("flush", handle)

    def read(self, handle, size):
        self._call("read", handle)
        return self.handles[handle][0]["data"][:size]

    def dispose(self, handle):
        self._call("dispose", handle)
        obj = self.handles[handle][0]
        assert self.handles[handle][1] & self.m.DELETE
        if obj["directory"] and any(ntpath.dirname(p) == obj["path"]
                                    for p in self.objects):
            raise OSError(145, "directory not empty")
        obj["pending"] = True

    def close(self, handle):
        self._call("close", handle)
        obj = self.handles.pop(handle)[0]
        if obj["pending"] and not any(v[0] is obj for v in self.handles.values()):
            if self.objects.get(obj["path"]) is obj:
                del self.objects[obj["path"]]

    def absent(self, path):
        self._call("absent", path)
        return path not in self.objects


def setup():
    m = module()
    return m, FakeNative(m)


def stage(m, native, **kwargs):
    return m.stage_probe(kwargs.get("parent", PARENT), kwargs.get("sid", SID),
                         kwargs.get("data", DATA), kwargs.get("digest", DIGEST),
                         _native=native, **({"include_fixtures": kwargs["include_fixtures"]}
                                            if "include_fixtures" in kwargs else {}))


def test_fixture_stage_exact_evidence_security_and_no_residual_handles():
    m, n = setup()
    owner = stage(m, n, include_fixtures=True)
    fixtures = owner.evidence.fixtures
    assert tuple(f.filename for f in fixtures) == ("allowed.txt", "denied.txt")
    for evidence, payload, package_ace in zip(fixtures,
            (b"xuxia-allowed-fixture-v1\r\n", b"xuxia-denied-fixture-v1\r\n"),
            (True, False)):
        obj = n.objects[evidence.path]
        assert obj["data"] == payload
        assert evidence.identity == (123, obj["id"])
        assert evidence.sha256 == sha256(payload).hexdigest()
        assert evidence.size == len(payload) and evidence.file_links == 1
        assert evidence.security == m.SecurityFacts(USER, True, True, (
            (0, 0, m.FILE_ALL_ACCESS, USER),
            (0, 0, m.FILE_ALL_ACCESS, "S-1-5-18"),
        ) + (((0, 0, 0x120089, SID),) if package_ace else ()))
        assert all(h[0] is not obj for h in n.handles.values())
    assert len([h for h in n.handles.values() if not h[0]["directory"]]) == 1
    assert owner.cleanup(child_cleanup_confirmed=True).complete


def test_fixture_recheck_reopens_verifies_and_closes():
    m, n = setup()
    owner = stage(m, n, include_fixtures=True)
    before = len(n.calls)
    owner.recheck()
    calls = n.calls[before:]
    for evidence in owner.evidence.fixtures:
        assert any(c[0] == "open" and c[1] == evidence.path and c[4] == m.OPEN_EXISTING
                   for c in calls)
        assert all(h[0]["path"] != evidence.path for h in n.handles.values())


@pytest.mark.parametrize("bad", [None, 0, 1, "yes"])
def test_fixture_flag_rejects_nonbool_before_native(bad):
    m, n = setup()
    with pytest.raises(m.StageError) as caught:
        stage(m, n, include_fixtures=bad)
    assert caught.value.owner is None and n.calls == []


def test_false_fixture_flag_keeps_hello_stage_unchanged():
    m, n = setup()
    owner = stage(m, n, include_fixtures=False)
    assert owner.evidence.fixtures == ()
    assert len([c for c in n.calls if c[0] == "write"]) == 1
    assert owner.cleanup(child_cleanup_confirmed=True).complete


def test_omitted_fixture_flag_keeps_hello_stage_unchanged():
    m, n = setup()
    owner = stage(m, n)
    assert owner.evidence.fixtures == ()
    assert set(n.objects) == {"C:\\", PARENT, owner.evidence.directory_path,
                              owner.evidence.executable_path}
    assert owner.cleanup(child_cleanup_confirmed=True).complete


@pytest.mark.parametrize("name", ["allowed.txt", "denied.txt"])
def test_fixture_creation_collision_is_uncertain_and_no_parent_delete(name):
    m, n = setup()
    def collision(native, path, access, share, creation, flags, security):
        if path.endswith(name) and creation == m.CREATE_NEW:
            native._add(path, False, security)
    n.hooks["open"] = collision
    with pytest.raises(m.StageError) as caught:
        stage(m, n, include_fixtures=True)
    owner = caught.value.owner
    report = owner.cleanup(child_cleanup_confirmed=True)
    assert not report.complete and any(p.endswith(name) for p in report.uncertain_paths)
    assert n.objects[owner._directory.path]
    assert owner.close_only().handles_closed


@pytest.mark.parametrize("name", ["allowed.txt", "denied.txt"])
@pytest.mark.parametrize("kind", ["short_write", "flush", "acl", "hash", "read", "close"])
def test_fixture_partial_failure_reports_owned_path(name, kind):
    m, n = setup()
    def inject(native, *args):
        if kind == "short_write" and args[0] in native.handles and native.handles[args[0]][0]["path"].endswith(name):
            native.short_write = True
        if kind in ("flush", "read", "close") and args[0] in native.handles and native.handles[args[0]][0]["path"].endswith(name):
            native.fail[kind] = 1
        if kind in ("acl", "hash") and args[0] in native.handles and native.handles[args[0]][0]["path"].endswith(name):
            obj = native.handles[args[0]][0]
            if kind == "acl": obj["security"] = None
            else: obj["data"] = b"X" * len(obj["data"])
    n.hooks["write" if kind == "short_write" else kind if kind in ("flush", "read", "close") else "flush"] = inject
    with pytest.raises(m.StageError) as caught:
        stage(m, n, include_fixtures=True)
    owner = caught.value.owner
    report = owner._report()
    assert any(p.endswith(name) for p in report.remaining_paths)
    assert owner._directory.path in report.remaining_paths
    assert not report.complete


def test_fixture_cleanup_gate_failure_retry_and_unexpected_child():
    m, n = setup()
    owner = stage(m, n, include_fixtures=True)
    assert not owner.cleanup(child_cleanup_confirmed=False).complete
    assert not any(c[0] == "dispose" for c in n.calls)
    extra = owner.evidence.directory_path + "\\extra.txt"
    n._add(extra, False)
    report = owner.cleanup(child_cleanup_confirmed=True)
    assert not report.complete and owner.evidence.directory_path in report.remaining_paths
    assert extra in n.objects
    del n.objects[extra]
    assert owner.cleanup(child_cleanup_confirmed=True).complete


@pytest.mark.parametrize("name", ["allowed.txt", "denied.txt"])
@pytest.mark.parametrize("kind", ["hash", "links", "reparse", "identity", "acl"])
def test_fixture_recheck_rejects_changed_object_and_releases_temp_handle(name, kind):
    m, n = setup()
    owner = stage(m, n, include_fixtures=True)
    fixture = next(f for f in owner.evidence.fixtures if f.filename == name)
    obj = n.objects[fixture.path]
    if kind == "hash": obj["data"] = b"X" * fixture.size
    if kind == "links": obj["links"] = 2
    if kind == "reparse": obj["reparse"] = True
    if kind == "identity": obj["id"] += 1
    if kind == "acl": obj["security"] = replace(obj["security"], protected=False)
    with pytest.raises(m.StageError): owner.recheck()
    assert all(h[0] is not obj for h in n.handles.values())


@pytest.mark.parametrize("name", ["allowed.txt", "denied.txt"])
def test_fixture_recheck_failed_close_retains_handle(name):
    m, n = setup()
    owner = stage(m, n, include_fixtures=True)
    path = next(f.path for f in owner.evidence.fixtures if f.filename == name)
    def fail_close(native, handle):
        if native.handles[handle][0]["path"] == path:
            native.fail["close"] = 1
            del native.hooks["close"]
    n.hooks["close"] = fail_close
    with pytest.raises(m.StageError): owner.recheck()
    assert any(h[0]["path"] == path for h in n.handles.values())
    assert owner.close_only().handles_closed


@pytest.mark.parametrize("name", ["allowed.txt", "denied.txt"])
def test_fixture_delete_open_failure_preserves_identity_and_retries(name):
    m, n = setup()
    owner = stage(m, n, include_fixtures=True)
    fixture = next(f for f in owner.evidence.fixtures if f.filename == name)
    def fail_once(native, path, access, share, creation, flags, security):
        if path == fixture.path and access & m.DELETE:
            del native.hooks["open"]
            raise OSError(32, "sharing")
    n.hooks["open"] = fail_once
    report = owner.cleanup(child_cleanup_confirmed=True)
    assert not report.complete and fixture.path in report.remaining_paths
    assert fixture.path not in report.uncertain_paths
    assert (123, n.objects[fixture.path]["id"]) == fixture.identity
    assert owner.evidence.directory_path in n.objects
    assert owner.cleanup(child_cleanup_confirmed=True).complete


@pytest.mark.parametrize("name", ["allowed.txt", "denied.txt"])
def test_fixture_replacement_before_delete_is_never_adopted(name):
    m, n = setup()
    owner = stage(m, n, include_fixtures=True)
    fixture = next(f for f in owner.evidence.fixtures if f.filename == name)
    def swap(native, path, access, share, creation, flags, security):
        if path == fixture.path and access & m.DELETE:
            native._add(path, False, fixture.security)
    n.hooks["open"] = swap
    result = owner.cleanup(child_cleanup_confirmed=True)
    assert not result.complete and fixture.path in result.uncertain_paths
    assert fixture.path in n.objects and owner.evidence.directory_path in n.objects
    assert not n.objects[fixture.path]["pending"]


@pytest.mark.parametrize("name", ["allowed.txt", "denied.txt"])
def test_fixture_close_failure_after_disposition_retries_only_close(name):
    m, n = setup()
    owner = stage(m, n, include_fixtures=True)
    path = next(f.path for f in owner.evidence.fixtures if f.filename == name)
    def close_failure(native, handle):
        if native.handles[handle][0]["path"] == path and native.handles[handle][0]["pending"]:
            native.fail["close"] = 1
            del native.hooks["close"]
    n.hooks["close"] = close_failure
    first = owner.cleanup(child_cleanup_confirmed=True)
    assert not first.complete and path in first.remaining_paths
    assert any(h[0]["path"] == path and h[0]["pending"] for h in n.handles.values())
    assert owner.cleanup(child_cleanup_confirmed=True).complete


def test_fixture_descriptors_serialize_to_exact_protected_dacls():
    m = module()
    pytest.importorskip("win32security")
    native = m._Native()
    for allowed in (True, False):
        facts = m._fixture_security(USER, SID, allowed=allowed)
        attrs = native._attributes(facts)
        assert not attrs.bInheritHandle
        assert native._security_facts(attrs.SECURITY_DESCRIPTOR) == facts


@pytest.mark.parametrize("kwargs", [
    {"parent": "relative"}, {"parent": r"\\server\share"},
    {"parent": r"C:\qa\..\else"}, {"parent": r"C:\qa\."},
    {"parent": r"C:\qa\stream:x"}, {"parent": r"C:\qa "},
    {"parent": r"C:\qa\NUL"}, {"parent": r"\\?\C:\qa"},
    {"parent": "C:\\qa\x00"}, {"parent": "C:\\"},
    {"sid": SID + "-8"}, {"sid": SID.replace("-7", "-4294967296")},
    {"sid": SID.replace("-7", "-07")}, {"sid": None},
    {"data": b""}, {"data": bytearray(DATA)}, {"data": b"x" * (4 * 1024 * 1024 + 1)},
    {"digest": "0" * 64}, {"digest": DIGEST.upper()}, {"digest": None},
])
def test_invalid_input_precedes_all_native_calls(kwargs):
    m, n = setup()
    with pytest.raises(m.StageError) as caught:
        stage(m, n, **kwargs)
    assert n.calls == []
    assert caught.value.owner is None


def test_success_pins_readonly_image_and_exact_private_security():
    m, n = setup()
    owner = stage(m, n)
    evidence = owner.recheck()
    assert evidence == owner.evidence
    assert evidence.sha256 == DIGEST and evidence.size == len(DATA)
    assert evidence.file_links == 1
    assert evidence.directory_path.startswith(PARENT + "\\stage_")
    assert len(ntpath.basename(evidence.directory_path)) == 38
    assert evidence.executable_path.endswith("\\hello.exe")
    assert evidence.security == m.SecurityFacts(USER, True, True, (
        (0, 0, m.FILE_ALL_ACCESS, USER),
        (0, 0, m.FILE_ALL_ACCESS, "S-1-5-18"),
        (0, 0, m.FILE_READ_EXECUTE, SID)))
    with pytest.raises(Exception):
        evidence.size = 1
    file_handles = [v for v in n.handles.values() if not v[0]["directory"]]
    assert len(file_handles) == 1
    assert file_handles[0][1] == m.GENERIC_READ
    assert file_handles[0][2] == m.FILE_SHARE_READ
    opens = [c for c in n.calls if c[0] == "open"]
    assert all(c[5] & m.OPEN_REPARSE_POINT for c in opens)
    assert all(not c[3] & m.FILE_SHARE_DELETE for c in opens)
    create = next(c for c in opens if c[4] == m.CREATE_NEW)
    assert create[2] == m.GENERIC_READ | m.GENERIC_WRITE
    assert create[6] == evidence.security
    assert len([c for c in n.calls if c[0] == "mkdir"]) == 1


@pytest.mark.parametrize("value", [False, 0, 1, None, "yes"])
def test_cleanup_requires_literal_true(value):
    m, n = setup()
    owner = stage(m, n)
    before = dict(n.handles)
    result = owner.cleanup(child_cleanup_confirmed=value)
    assert not result.complete and result.pending
    assert n.handles == before
    assert not any(c[0] == "dispose" for c in n.calls)


def test_success_cleanup_is_exact_retryable_idempotent():
    m, n = setup()
    owner = stage(m, n)
    evidence = owner.evidence
    result = owner.cleanup(child_cleanup_confirmed=True)
    assert result.complete and not result.pending
    assert n.handles == {}
    assert set(n.objects) == {"C:\\", PARENT}
    assert owner.cleanup(child_cleanup_confirmed=True) == result
    assert evidence.executable_path not in n.objects


@pytest.mark.parametrize("operation", ["dispose", "close"])
def test_cleanup_failure_retains_owner_and_retry(operation):
    m, n = setup()
    owner = stage(m, n)
    n.fail[operation] = 1
    first = owner.cleanup(child_cleanup_confirmed=True)
    assert not first.complete and first.failures
    assert "sensitive" not in repr(first)
    assert owner.cleanup(child_cleanup_confirmed=True).complete
    assert n.handles == {}


@pytest.mark.parametrize("kind", ["hash", "links", "reparse", "identity", "acl", "null", "inherited", "extra"])
def test_prelaunch_recheck_rejects_changed_object(kind):
    m, n = setup()
    owner = stage(m, n)
    obj = n.objects[owner.evidence.executable_path]
    if kind == "hash": obj["data"] = b"X" * len(DATA)
    if kind == "links": obj["links"] = 2
    if kind == "reparse": obj["reparse"] = True
    if kind == "identity": obj["id"] += 1
    if kind == "acl": obj["security"] = replace(obj["security"], protected=False)
    if kind == "null": obj["security"] = replace(obj["security"], dacl_present=False)
    if kind == "inherited":
        a = obj["security"].aces
        obj["security"] = replace(obj["security"], aces=((0, 16, a[0][2], a[0][3]),) + a[1:])
    if kind == "extra":
        obj["security"] = replace(obj["security"], aces=obj["security"].aces + ((0, 0, m.FILE_ALL_ACCESS, "S-1-1-0"),))
    with pytest.raises(m.StageError): owner.recheck()
    assert n.handles


@pytest.mark.parametrize("kind", ["filesystem", "ancestor_reparse"])
def test_unsupported_ancestor_never_creates(kind):
    m, n = setup()
    if kind == "filesystem": n.fs = "ReFS"
    else: n.objects[PARENT]["reparse"] = True
    with pytest.raises(m.StageError) as caught: stage(m, n)
    assert not any(c[0] == "mkdir" for c in n.calls)
    assert caught.value.owner.close_only().handles_closed


@pytest.mark.parametrize("kind", ["short_write", "flush", "read", "bad_hash", "bad_links"])
def test_partial_file_creation_retains_live_owner(kind):
    m, n = setup()
    if kind == "short_write": n.short_write = True
    elif kind in ("flush", "read"): n.fail[kind] = 1
    else:
        def mutate(native, handle):
            obj = native.handles[handle][0]
            if kind == "bad_hash": obj["data"] = b"X" * len(DATA)
            else: obj["links"] = 2
        n.hooks["flush"] = mutate
    with pytest.raises(m.StageError) as caught: stage(m, n)
    owner = caught.value.owner
    assert owner is not None and n.handles
    assert "sensitive" not in str(caught.value)
    if kind == "bad_links":
        assert not owner.cleanup(child_cleanup_confirmed=True).complete
    else:
        assert owner.cleanup(child_cleanup_confirmed=True).complete


@pytest.mark.parametrize("kind", ["collision", "open_failure", "bad_acl", "reparse"])
def test_directory_acquisition_uncertainty_never_grants_delete(kind):
    m, n = setup()
    if kind == "collision":
        def collision(native, path, security): native._add(path, True, security)
        n.hooks["mkdir"] = collision
    else:
        def interfere(native, path, access, share, creation, flags, security):
            if "stage_" not in path: return
            if kind == "open_failure": raise OSError(5, "no")
            if kind == "bad_acl": native.objects[path]["security"] = None
            if kind == "reparse": native.objects[path]["reparse"] = True
        n.hooks["open"] = interfere
    with pytest.raises(m.StageError) as caught: stage(m, n)
    owner = caught.value.owner
    result = owner.cleanup(child_cleanup_confirmed=True)
    assert not result.complete
    assert result.uncertain_paths
    assert not any(c[0] == "dispose" for c in n.calls)
    assert owner.close_only().handles_closed
    assert len(n.objects) == 3


def test_exe_collision_never_adopts_or_deletes_file_or_nonempty_directory():
    m, n = setup()
    def collision(native, path, access, share, creation, flags, security):
        if creation == m.CREATE_NEW: native._add(path, False, security)
    n.hooks["open"] = collision
    with pytest.raises(m.StageError) as caught: stage(m, n)
    result = caught.value.owner.cleanup(child_cleanup_confirmed=True)
    assert not result.complete and result.uncertain_paths
    assert len(n.objects) == 4


def test_reopen_replacement_never_deleted_and_close_only_reports_leftovers():
    m, n = setup()
    owner = stage(m, n)
    path = owner.evidence.executable_path
    def swap(native, p, access, share, creation, flags, security):
        if p == path and access & m.DELETE:
            native._add(p, False, owner.evidence.security)
    n.hooks["open"] = swap
    result = owner.cleanup(child_cleanup_confirmed=True)
    assert not result.complete and result.uncertain_paths
    assert not any(c[0] == "dispose" for c in n.calls)
    close = owner.close_only()
    assert close.handles_closed and close.pending and not close.complete
    assert n.handles == {} and path in n.objects


def test_directory_replacement_during_cleanup_never_deleted():
    m, n = setup()
    owner = stage(m, n)
    path = owner.evidence.directory_path
    def swap(native, p, access, share, creation, flags, security):
        if p == path and access & m.DELETE:
            native._add(p, True, owner.evidence.security)
    n.hooks["open"] = swap
    result = owner.cleanup(child_cleanup_confirmed=True)
    assert not result.complete and path in result.uncertain_paths
    assert path in n.objects


def test_unexpected_child_prevents_directory_disposition_without_recursive_delete():
    m, n = setup()
    owner = stage(m, n)
    extra = owner.evidence.directory_path + "\\unexpected.txt"
    n._add(extra, False)
    result = owner.cleanup(child_cleanup_confirmed=True)
    assert not result.complete and result.failures
    assert extra in n.objects
    del n.objects[extra]  # External cleanup; the helper must never do this.
    assert owner.cleanup(child_cleanup_confirmed=True).complete


def test_pywin32_descriptor_roundtrip_is_pure_and_exact():
    m = module()
    pytest.importorskip("win32security")
    native = m._Native()
    facts = m._expected_security(USER, SID)
    attrs = native._attributes(facts)
    assert not attrs.bInheritHandle
    assert native._security_facts(attrs.SECURITY_DESCRIPTOR) == facts


def test_delete_pending_external_reader_does_not_claim_removal():
    m, n = setup()
    owner = stage(m, n)
    path = owner.evidence.executable_path
    other = n.open(path, m.GENERIC_READ, m.FILE_SHARE_READ | m.FILE_SHARE_DELETE,
                   m.OPEN_EXISTING, m.OPEN_REPARSE_POINT)
    result = owner.cleanup(child_cleanup_confirmed=True)
    assert not result.complete and path in result.remaining_paths
    n.close(other)
    assert owner.cleanup(child_cleanup_confirmed=True).complete


def test_close_failure_after_successful_disposition_retries_only_close():
    m, n = setup()
    owner = stage(m, n)
    def close_failure(native, handle):
        if native.handles[handle][0]["pending"]:
            native.fail["close"] = 1
            del native.hooks["close"]
    n.hooks["close"] = close_failure
    assert not owner.cleanup(child_cleanup_confirmed=True).complete
    assert any(v[0]["pending"] for v in n.handles.values())
    assert owner.cleanup(child_cleanup_confirmed=True).complete


def test_import_is_lazy_in_fresh_interpreter():
    from pathlib import Path
    import subprocess
    import sys
    result = subprocess.run([sys.executable, "-c",
        "import scripts.local_probe_stage, sys; "
        "assert 'win32file' not in sys.modules; "
        "assert 'win32security' not in sys.modules"],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("kind", ["open_failure", "replacement", "acl", "hash"])
def test_writer_to_read_pin_gap_never_adopts_uncertain_image(kind):
    m, n = setup()
    def interfere(native, path, access, share, creation, flags, security):
        if not path.endswith("hello.exe") or creation != m.OPEN_EXISTING:
            return
        if kind == "open_failure": raise OSError(5, "failed")
        if kind == "replacement": native._add(path, False, native.objects[path]["security"])
        if kind == "acl": native.objects[path]["security"] = None
        if kind == "hash": native.objects[path]["data"] = b"X" * len(DATA)
    n.hooks["open"] = interfere
    with pytest.raises(m.StageError) as caught: stage(m, n)
    result = caught.value.owner.cleanup(child_cleanup_confirmed=True)
    assert not result.complete and result.uncertain_paths
    assert not any(c[0] == "dispose" for c in n.calls)


def test_native_adapter_detaches_pyhandle_and_uses_raw_close_for_retry():
    from types import SimpleNamespace
    m = module()
    native = object.__new__(m._Native)
    class Handle:
        detached = False
        def Detach(self):
            self.detached = True
            return 101
    handle = Handle()
    closed = []
    native.file = SimpleNamespace(CreateFile=lambda *args: handle,
                                  CloseHandle=lambda raw: closed.append(raw))
    raw = native.open(r"C:\qa\hello.exe", m.GENERIC_READ, 1, 3, m.OPEN_REPARSE_POINT)
    assert type(raw) is int and raw == 101 and handle.detached
    native.close(raw)
    assert closed == [101]


def test_native_volume_normalizes_pywin32_signed_serial():
    from types import SimpleNamespace
    m = module()
    native = object.__new__(m._Native)
    native.api = SimpleNamespace(GetVolumeInformation=lambda root: ("", -1, 255, 8, "NTFS"))
    native.file = SimpleNamespace(GetDriveType=lambda root: 3)
    assert native.volume(PARENT) == ("NTFS", 0xFFFFFFFF, 3)


@pytest.mark.parametrize("target", ["file", "directory"])
def test_cleanup_transient_delete_open_failure_retains_identity_for_retry(target):
    m, n = setup()
    owner = stage(m, n)
    evidence = owner.evidence
    path = evidence.executable_path if target == "file" else evidence.directory_path
    expected = evidence.executable_id if target == "file" else evidence.directory_id
    def fail_once(native, p, access, share, creation, flags, security):
        if p == path and access & m.DELETE:
            del native.hooks["open"]
            raise OSError(32, "transient sharing failure")
    n.hooks["open"] = fail_once
    result = owner.cleanup(child_cleanup_confirmed=True)
    assert not result.complete and path in result.remaining_paths
    assert result.uncertain_paths == ()
    assert (123, n.objects[path]["id"]) == expected
    assert not any(v[0]["path"] == path for v in n.handles.values())
    assert owner.cleanup(child_cleanup_confirmed=True).complete
    assert n.handles == {} and set(n.objects) == {"C:\\", PARENT}


def test_rng_failure_precedes_resource_acquisition(monkeypatch):
    m, n = setup()
    def fail_rng(_count):
        raise OSError("sensitive entropy failure")
    monkeypatch.setattr(m.secrets, "token_hex", fail_rng)
    with pytest.raises(m.StageError) as caught:
        stage(m, n)
    assert caught.value.owner is None
    assert str(caught.value) == "stage_entropy"
    assert n.calls == [] and n.handles == {}
    assert set(n.objects) == {"C:\\", PARENT}


@pytest.mark.parametrize("error", [2, 3, 5, 32, 0])
def test_native_absence_uses_checked_wrapper_not_unchecked_minus_one(error):
    from types import SimpleNamespace
    m = module()
    native = object.__new__(m._Native)
    class NativeError(Exception):
        def __init__(self, winerror):
            self.winerror = winerror
    calls = []
    def unchecked(path):
        calls.append("unchecked")
        return -1  # Actual win32file behavior observed by the root native smoke.
    def checked(path):
        calls.append("checked")
        raise NativeError(error)  # win32api checks INVALID_FILE_ATTRIBUTES.
    native.file = SimpleNamespace(GetFileAttributes=unchecked)
    native.api = SimpleNamespace(GetFileAttributes=checked, GetLastError=lambda: error)
    native.types = SimpleNamespace(error=NativeError)
    if error in (2, 3):
        assert native.absent(r"C:\qa\hello.exe") is True
    else:
        with pytest.raises(NativeError) as caught:
            native.absent(r"C:\qa\hello.exe")
        assert caught.value.winerror == error
    assert calls == ["checked"]


@pytest.mark.parametrize("attributes", [-1, 0xFFFFFFFF, None, False, "missing"])
def test_native_absence_never_accepts_arbitrary_invalid_attribute_sentinel(attributes):
    from types import SimpleNamespace
    m = module()
    native = object.__new__(m._Native)
    native.file = SimpleNamespace(GetFileAttributes=lambda p: attributes)
    native.api = SimpleNamespace(GetFileAttributes=lambda p: attributes, GetLastError=lambda: 2)
    native.types = SimpleNamespace(error=OSError)
    with pytest.raises(ValueError):
        native.absent(r"C:\qa\hello.exe")


@pytest.mark.parametrize("attributes", [0, 0x10, 0x80])
def test_native_existing_attributes_are_not_absence_despite_stale_error(attributes):
    from types import SimpleNamespace
    m = module()
    native = object.__new__(m._Native)
    calls = []
    def checked(path):
        calls.append(path)
        return attributes
    native.file = SimpleNamespace(GetFileAttributes=lambda p: attributes)
    native.api = SimpleNamespace(GetFileAttributes=checked, GetLastError=lambda: 2)
    native.types = SimpleNamespace(error=OSError)
    assert native.absent(r"C:\qa\hello.exe") is False
    assert calls == [r"C:\qa\hello.exe"]

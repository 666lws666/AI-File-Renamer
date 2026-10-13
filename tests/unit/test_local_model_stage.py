"""Model bundle staging contract tests, without launching a model."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from scripts import local_model_stage as model
from scripts import local_probe_stage as probe
from tests.unit.test_local_probe_stage import FakeNative, PARENT, SID, USER


class ModelNative(FakeNative):
    def __init__(self):
        super().__init__(probe)
        self.max_read = 0
        self.max_write = 0

    def source(self, path, data, *, links=1, reparse=False):
        path = str(path)
        parts = Path(path).parts
        for i in range(1, len(parts)):
            parent = str(Path(*parts[:i]))
            if parent not in self.objects:
                self._add(parent, True)
        obj = self._add(path, False)
        obj.update(data=data, links=links, reparse=reparse)
        return obj

    def read_at(self, handle, offset, size):
        self._call("read_at", handle, offset, size)
        self.max_read = max(self.max_read, size)
        return self.handles[handle][0]["data"][offset:offset + size]

    def write(self, handle, data):
        self.max_write = max(self.max_write, len(data))
        self._call("write", handle)
        count = len(data) - 1 if self.short_write else len(data)
        obj = self.handles[handle][0]
        obj["data"] += data[:count]
        return count


def member(name="runner.exe", data=b"MZ executable", *, executable=True, size=None, digest=None):
    path = Path(r"C:\source") / name
    return model.StageMember(name, path, len(data) if size is None else size,
                             sha256(data).hexdigest() if digest is None else digest,
                             executable), data


def make_stage(*pairs, cancelled=lambda: False):
    n = ModelNative()
    for spec, payload in pairs:
        n.source(spec.source, payload)
    owner = model.stage_model_bundle(PARENT, SID, tuple(s for s, _ in pairs),
                                     "runner.exe", cancelled=cancelled, _native=n)
    return owner, n


@pytest.mark.parametrize("name", ["../runner.exe", "bad:name.exe", "CON.exe", "runner.exe ",
                                  "é.exe", "sub\\runner.exe", ".", "bad/runner.exe"])
def test_invalid_member_name_rejected_before_io(name):
    spec, _ = member(name)
    n = ModelNative()
    with pytest.raises(probe.StageError) as caught:
        model.stage_model_bundle(PARENT, SID, (spec,), name, _native=n)
    assert caught.value.owner is None and not n.calls


def test_case_insensitive_duplicate_and_bounds_rejected_before_io():
    spec, _ = member()
    n = ModelNative()
    for members in ((), (spec, replace(spec, name="RUNNER.EXE")),
                    (replace(spec, size=0),), (replace(spec, size=4 * 1024**3 + 1),),
                    tuple(replace(spec, name=f"n{i}.exe") for i in range(81))):
        with pytest.raises(probe.StageError) as caught:
            model.stage_model_bundle(PARENT, SID, members, "runner.exe", _native=n)
        assert caught.value.owner is None and not n.calls


def test_streams_verifies_and_pins_all_members_with_distinct_rights():
    exe = member(data=b"MZ" * (1024 * 1024))
    data = member("weights.gguf", b"W" * (1024 * 1024 + 9), executable=False)
    owner, n = make_stage(exe, data)
    assert n.max_read <= 1024 * 1024 and n.max_write <= 1024 * 1024
    assert len(owner.evidence.members) == 2
    assert owner.evidence.members[0].security.aces[-1][2] == probe.FILE_READ_EXECUTE
    assert owner.evidence.members[1].security.aces[-1][2] == probe.FILE_GENERIC_READ
    assert all(n.handles[o.handle][1] == probe.GENERIC_READ for o, _ in owner._members)
    assert owner.recheck() == owner.evidence
    assert not owner.cleanup(child_cleanup_confirmed=False).complete
    assert owner.cleanup(child_cleanup_confirmed=True).complete


@pytest.mark.parametrize("change", ["links", "reparse", "size", "hash"])
def test_source_rejected_with_live_owner_if_acquired(change):
    spec, payload = member()
    n = ModelNative()
    obj = n.source(spec.source, payload)
    if change == "links": obj["links"] = 2
    if change == "reparse": obj["reparse"] = True
    if change == "size": obj["data"] += b"x"
    if change == "hash": obj["data"] = b"X" * len(payload)
    with pytest.raises(probe.StageError) as caught:
        model.stage_model_bundle(PARENT, SID, (spec,), spec.name, _native=n)
    assert caught.value.owner is not None


def test_cancellation_between_chunks_retains_owner():
    spec = member(data=b"x" * (1024 * 1024 + 1))
    n = ModelNative()
    n.source(spec[0].source, spec[1])
    def cancelled():
        return any(c[0] == "write" for c in n.calls)
    with pytest.raises(probe.StageError) as caught:
        model.stage_model_bundle(PARENT, SID, (spec[0],), spec[0].name,
                                 cancelled=cancelled, _native=n)
    assert caught.value.owner is not None
    assert not caught.value.owner.cleanup(child_cleanup_confirmed=False).complete


def test_recheck_tamper_and_cleanup_refuses_replacement():
    owner, n = make_stage(member())
    obj = n.objects[owner.executable_path]
    obj["security"] = replace(obj["security"], protected=False)
    with pytest.raises(probe.StageError): owner.recheck()
    obj["security"] = owner.evidence.members[0].security
    obj["id"] += 1
    report = owner.cleanup(child_cleanup_confirmed=True)
    assert not report.complete and owner.executable_path in n.objects


def test_source_ancestor_reparse_rejected_without_acl_mutation():
    spec, payload = member()
    n = ModelNative()
    source = n.source(spec.source, payload)
    source["security"] = object()
    before = source["security"]
    n.objects[r"C:\source"]["reparse"] = True
    with pytest.raises(probe.StageError) as caught:
        model.stage_model_bundle(PARENT, SID, (spec,), spec.name, _native=n)
    assert caught.value.owner is not None
    assert source["security"] is before
    assert not any(c[0] == "dispose" for c in n.calls)


def test_source_handles_exclude_write_and_delete_sharing():
    owner, n = make_stage(member())
    source_opens = [c for c in n.calls if c[0] == "open" and c[1].startswith(r"C:\source")]
    assert source_opens and all(c[3] == probe.FILE_SHARE_READ for c in source_opens)
    assert owner.cleanup(child_cleanup_confirmed=True).complete


@pytest.mark.parametrize("operation", ["write", "flush", "reopen"])
def test_partial_failure_retains_exact_owner(operation):
    spec, payload = member()
    n = ModelNative()
    n.source(spec.source, payload)
    if operation in ("write", "flush"):
        n.fail[operation] = 1
    else:
        def fail_reopen(native, path, access, share, creation, flags, security):
            if "\\stage_" in path and path.endswith("runner.exe") and creation == probe.OPEN_EXISTING:
                native.fail["open"] = 1
        n.hooks["open"] = fail_reopen
    with pytest.raises(probe.StageError) as caught:
        model.stage_model_bundle(PARENT, SID, (spec,), spec.name, _native=n)
    owner = caught.value.owner
    assert owner is not None and owner.executable_path in owner._report().remaining_paths
    assert owner.directory_path in owner._report().remaining_paths


@pytest.mark.parametrize("change", ["size", "links", "reparse", "identity", "acl"])
def test_recheck_rejects_metadata_tamper(change):
    owner, n = make_stage(member())
    obj = n.objects[owner.executable_path]
    if change == "size": obj["data"] += b"x"
    if change == "links": obj["links"] = 2
    if change == "reparse": obj["reparse"] = True
    if change == "identity": obj["id"] += 1
    if change == "acl": obj["security"] = replace(obj["security"], protected=False)
    with pytest.raises(probe.StageError):
        owner.recheck()


def test_source_alternate_stream_rejected_before_native():
    spec, _ = member()
    spec = replace(spec, source=Path(r"C:\source\runner.exe:stream"))
    n = ModelNative()
    with pytest.raises(probe.StageError) as caught:
        model.stage_model_bundle(PARENT, SID, (spec,), spec.name, _native=n)
    assert caught.value.owner is None and n.calls == []


def test_recheck_rehashes_member_after_pin_release():
    owner, n = make_stage(member())
    obj = owner._file
    owner._close(obj)
    n.objects[obj.path]["data"] = b"X" * owner.evidence.members[0].size
    with pytest.raises(probe.StageError) as caught:
        owner.recheck()
    assert caught.value.stage == "object_hash"
    with pytest.raises(probe.StageError):
        owner.recheck()
    assert owner.cleanup(child_cleanup_confirmed=True).complete


def test_dll_gets_execute_rights_even_without_entrypoint_flag():
    owner, n = make_stage(member(), member("llama.dll", b"DLL", executable=False))
    assert owner.evidence.members[1].security.aces[-1][2] == probe.FILE_READ_EXECUTE
    assert owner.cleanup(child_cleanup_confirmed=True).complete


def test_data_member_cannot_request_execute_rights():
    exe, _ = member()
    data, _ = member("weights.gguf", b"GGUF", executable=True)
    n = ModelNative()
    with pytest.raises(probe.StageError) as caught:
        model.stage_model_bundle(PARENT, SID, (exe, data), exe.name, _native=n)
    assert caught.value.owner is None and n.calls == []

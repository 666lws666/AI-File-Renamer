"""Private in-memory request staging at the fake native boundary."""
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256

import pytest

from scripts import local_model_stage as model
from scripts import local_probe_stage as probe
from tests.unit.test_local_model_stage import ModelNative, member
from tests.unit.test_local_probe_stage import PARENT, SID


SECRET = b"private prompt contents"


def bytes_member(name="prompt.txt", data=SECRET):
    return model.StageBytesMember(name, data)


def stage_private(*private, cancelled=lambda: False, native=None):
    exe, payload = member()
    n = native or ModelNative()
    n.source(exe.source, payload)
    owner = model.stage_model_bundle(PARENT, SID, (exe, *private), exe.name,
                                     cancelled=cancelled, _native=n)
    return owner, n


def test_mixed_bundle_stages_bytes_without_source_and_keeps_file_evidence():
    owner, n = stage_private(bytes_member(), bytes_member("schema.json", b"{}"),
                             bytes_member("visual_00.png", b"PNG"))
    assert len(owner.evidence.members) == 4
    file_evidence = owner.evidence.members[0]
    assert file_evidence.source_path == r"C:\source\runner.exe"
    assert file_evidence.source_identity is not None
    for evidence, payload in zip(owner.evidence.members[1:], (SECRET, b"{}", b"PNG")):
        assert evidence.source_path is None and evidence.source_identity is None
        assert evidence.size == len(payload)
        assert evidence.sha256 == sha256(payload).hexdigest()
        assert evidence.security.aces[-1][2] == probe.FILE_GENERIC_READ
        assert n.objects[evidence.path]["data"] == payload
    assert set(n.objects) == {"C:\\", PARENT, r"C:\source", r"C:\source\runner.exe",
                              owner.directory_path, *(e.path for e in owner.evidence.members)}
    assert owner.recheck() == owner.evidence
    assert owner.cleanup(child_cleanup_confirmed=True).complete


@pytest.mark.parametrize("name", ["visual_08.png", "visual_0.png", "visual_00.gif",
                                   "visual_00.PNG", "visual_00.png.exe", "other.txt",
                                   "../prompt.txt", "PROMPT.TXT"])
def test_unsafe_private_names_rejected_before_native(name):
    n = ModelNative()
    exe, _ = member()
    with pytest.raises(probe.StageError) as error:
        model.stage_model_bundle(PARENT, SID, (exe, bytes_member(name)), exe.name, _native=n)
    assert error.value.owner is None and n.calls == []


@pytest.mark.parametrize("name,data", [
    ("prompt.txt", b""), ("prompt.txt", b"x" * (128 * 1024 + 1)),
    ("schema.json", b"x" * (128 * 1024 + 1)),
    ("visual_00.webp", b"x" * (16 * 1024 * 1024 + 1)),
    ("prompt.txt", bytearray(b"x")),
], ids=["empty-prompt", "oversized-prompt", "oversized-schema", "oversized-visual", "mutable-data"])
def test_private_data_bounds_and_type_rejected_before_native(name, data):
    n = ModelNative()
    exe, _ = member()
    with pytest.raises(probe.StageError) as error:
        model.stage_model_bundle(PARENT, SID, (exe, bytes_member(name, data)), exe.name, _native=n)
    assert error.value.owner is None and n.calls == []


def test_duplicate_visual_index_and_aggregate_bound_rejected_before_native():
    exe, _ = member()
    cases = (
        (bytes_member("visual_00.jpg", b"x"), bytes_member("visual_00.webp", b"y")),
        tuple(bytes_member(f"visual_{i:02}.png", b"x" * (2 * 1024 * 1024 + 1))
              for i in range(8)),
    )
    for private in cases:
        n = ModelNative()
        with pytest.raises(probe.StageError) as error:
            model.stage_model_bundle(PARENT, SID, (exe, *private), exe.name, _native=n)
        assert error.value.owner is None and n.calls == []


def test_private_member_cannot_be_entrypoint_or_executable():
    n = ModelNative()
    with pytest.raises(probe.StageError):
        model.stage_model_bundle(PARENT, SID, (bytes_member(),), "prompt.txt", _native=n)
    assert n.calls == []
    with pytest.raises((TypeError, FrozenInstanceError)):
        model.StageBytesMember("prompt.txt", SECRET, executable=True)


@pytest.mark.parametrize("name", ["prompt.txt", "schema.json", "visual_00.jpg",
                                   "visual_01.png", "visual_07.webp"])
def test_every_private_member_kind_is_read_only(name):
    owner, _ = stage_private(bytes_member(name, b"x"))
    assert owner.evidence.members[1].security.aces[-1][2] == probe.FILE_GENERIC_READ
    assert owner.cleanup(child_cleanup_confirmed=True).complete


def test_exact_acl_exists_before_first_private_write_and_writes_are_bounded():
    n = ModelNative()
    payload = b"x" * (1024 * 1024 + 9)
    def check_write(native, handle):
        obj = native.handles[handle][0]
        if obj["path"].endswith("visual_00.png"):
            assert obj["security"].protected
            assert obj["security"].aces[-1][2] == probe.FILE_GENERIC_READ
            assert any(c[0] == "security" and c[1] == handle for c in native.calls)
            assert obj["data"] == b"" or len(obj["data"]) == 1024 * 1024
    n.hooks["write"] = check_write
    owner, n = stage_private(bytes_member("visual_00.png", payload), native=n)
    assert n.max_write <= 1024 * 1024
    assert owner.cleanup(child_cleanup_confirmed=True).complete


def test_cancellation_between_private_chunks_preserves_cleanup_owner():
    n = ModelNative()
    exe, payload = member()
    n.source(exe.source, payload)
    def cancelled():
        return any(c[0] == "write" and n.handles[c[1]][0]["path"].endswith("visual_00.png")
                   for c in n.calls if c[1] in n.handles)
    with pytest.raises(probe.StageError) as error:
        model.stage_model_bundle(PARENT, SID,
            (exe, bytes_member("visual_00.png", b"x" * (1024 * 1024 + 1))),
            exe.name, cancelled=cancelled, _native=n)
    assert error.value.stage == "cancelled" and error.value.owner is not None
    assert error.value.owner.cleanup(child_cleanup_confirmed=True).complete


@pytest.mark.parametrize("failure", ["write", "hash", "security"])
def test_private_failure_retains_exact_cleanup_owner(failure):
    n = ModelNative()
    if failure == "write":
        def corrupt(native, handle):
            if native.handles[handle][0]["path"].endswith("prompt.txt"):
                native.short_write = True
        n.hooks["write"] = corrupt
    elif failure == "hash":
        def corrupt(native, handle):
            obj = native.handles[handle][0]
            if obj["path"].endswith("prompt.txt"):
                obj["data"] = b"X" * len(obj["data"])
        n.hooks["flush"] = corrupt
    else:
        def corrupt(native, handle):
            obj = native.handles[handle][0]
            if obj["path"].endswith("prompt.txt"):
                obj["security"] = replace(obj["security"], protected=False)
        n.hooks["flush"] = corrupt
    exe, payload = member()
    n.source(exe.source, payload)
    with pytest.raises(probe.StageError) as error:
        model.stage_model_bundle(PARENT, SID, (exe, bytes_member()), exe.name, _native=n)
    assert error.value.owner is not None
    if failure == "security":
        private_obj = error.value.owner._members[1][0]
        report = error.value.owner.cleanup(child_cleanup_confirmed=True)
        assert not report.complete and private_obj.path in report.uncertain_paths
        assert private_obj.path in n.objects
    else:
        assert error.value.owner.cleanup(child_cleanup_confirmed=True).complete


def test_private_bytes_and_digest_never_enter_reprs_or_errors():
    private = bytes_member()
    assert SECRET.decode() not in repr(private)
    with pytest.raises(FrozenInstanceError):
        private.data = b"changed"
    owner, n = stage_private(private)
    assert SECRET.decode() not in repr(owner.evidence)
    assert sha256(SECRET).hexdigest() not in repr(owner.evidence)
    assert sha256(SECRET).hexdigest() not in repr(owner._members)
    evidence = owner.evidence.members[1]
    n.objects[evidence.path]["data"] = b"X" * evidence.size
    owner._close(owner._members[1][0])
    with pytest.raises(probe.StageError) as error:
        owner.recheck()
    assert SECRET.decode() not in str(error.value)
    assert sha256(SECRET).hexdigest() not in str(error.value)
    assert owner.cleanup(child_cleanup_confirmed=True).complete

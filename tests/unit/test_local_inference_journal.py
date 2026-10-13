"""Content-free crash journal tests; only tiny synthetic state roots are used."""

import importlib
import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.services.local_ai.resource_store import MARKER, ResourceStore, StoreBusy


MODULE = "src.services.local_ai.inference_journal"
NAMESPACE = "xuxia-local-inference-journal-v1"
BASENAME = "inference-run.json"
RUN = "b" * 32
OTHER = "c" * 32
CATALOG = "a" * 64
PROFILE = "xuxia_local_" + RUN
SID = "S-1-15-2-0-1-2-3-4-5-4294967295"
STAGE = "stage_" + OTHER
SECRET = "PRIVATE-content-C:/private/secret.txt-prompt-model-result"


def api():
    assert importlib.util.find_spec(MODULE) is not None, "inference journal is not implemented"
    return importlib.import_module(MODULE)


def begin(journal):
    return journal.begin(catalog_id=CATALOG, profile_name=PROFILE, package_sid=SID)


def payload(**updates):
    result = dict(schema_version=1, revision=0, run_id=None, phase="clean",
                  catalog_id=None, profile_name=None, package_sid=None,
                  stage_name=None, stage_identity=None)
    result.update(updates)
    return result


def active_payload(**updates):
    result = payload(revision=1, run_id=RUN, phase="active", catalog_id=CATALOG,
                     profile_name=PROFILE, package_sid=SID)
    result.update(updates)
    return result


def seed(root, raw):
    with ResourceStore(root, NAMESPACE).lease(create=True) as store:
        with store.open_file(BASENAME, "wb") as stream:
            stream.write(raw)


def test_new_clean_reopens_and_constructor_is_io_free(tmp_path):
    module = api()
    root = tmp_path / "state"
    journal = module.LocalInferenceJournal(root)
    assert not root.exists()
    with journal.lease() as leased:
        assert leased is journal
        assert journal.record == module.InferenceRunRecord(0, None, "clean", None, None, None, None, None)
        with pytest.raises(FrozenInstanceError):
            journal.record.revision = 1
    assert json.loads((root / BASENAME).read_bytes()) == payload()
    marker = json.loads((root / MARKER).read_bytes())
    assert marker["catalog_id"] == NAMESPACE
    with module.LocalInferenceJournal(root).lease(create=False) as reopened:
        assert reopened.record.revision == 0


def test_missing_create_false_does_not_create(tmp_path):
    module = api()
    root = tmp_path / "missing"
    with pytest.raises(module.InferenceRecoveryRequired, match="^RECOVERY_REQUIRED$"):
        with module.LocalInferenceJournal(root).lease(create=False):
            pytest.fail("missing journal admitted")
    assert not root.exists()


def test_active_reopen_refused_and_exclusion(tmp_path):
    module = api()
    root = tmp_path / "state"
    journal = module.LocalInferenceJournal(root)
    with journal.lease():
        begin(journal)
        for contender in (journal, module.LocalInferenceJournal(root)):
            with pytest.raises(StoreBusy):
                with contender.lease():
                    pytest.fail("concurrent lease admitted")
    before = (root / BASENAME).read_bytes()
    with pytest.raises(module.InferenceRecoveryRequired, match="^RECOVERY_REQUIRED$"):
        with module.LocalInferenceJournal(root).lease():
            pytest.fail("active journal admitted")
    assert (root / BASENAME).read_bytes() == before


def test_revision_progression_idempotence_and_metadata_retention(tmp_path):
    module = api()
    root = tmp_path / "state"
    with module.LocalInferenceJournal(root).lease() as journal:
        first = begin(journal)
        assert (first.revision, first.run_id, first.phase) == (1, RUN, "active")
        staged = journal.attach_stage(RUN, name=STAGE, identity=(0, 1))
        assert staged.revision == 2
        assert journal.attach_stage(RUN, name=STAGE, identity=(0, 1)) is staged
        clean = journal.complete(RUN)
        assert (clean.revision, clean.phase, clean.stage_identity) == (3, "clean", (0, 1))
        assert journal.complete(RUN) is clean
    with module.LocalInferenceJournal(root).lease() as journal:
        assert journal.record == clean
        assert journal.complete(RUN) is journal.record
        assert begin(journal).revision == 4


@pytest.mark.parametrize("operation", ["begin", "attach", "complete", "record"])
def test_outside_lease_rejected(tmp_path, operation):
    module = api()
    journal = module.LocalInferenceJournal(tmp_path / "state")
    actions = dict(begin=lambda: begin(journal), attach=lambda: journal.attach_stage(RUN, name=STAGE, identity=(1, 2)),
                   complete=lambda: journal.complete(RUN), record=lambda: journal.record)
    with pytest.raises(module.InferenceJournalError):
        actions[operation]()


def test_incompatible_phases_stale_ids_and_conflicts_do_not_write(tmp_path):
    module = api()
    with module.LocalInferenceJournal(tmp_path / "state").lease() as journal:
        with pytest.raises(module.InferenceJournalError):
            journal.complete(RUN)
        with pytest.raises(module.InferenceJournalError):
            journal.attach_stage(RUN, name=STAGE, identity=(1, 2))
        first = begin(journal)
        for action in (lambda: begin(journal), lambda: journal.complete(OTHER),
                       lambda: journal.attach_stage(OTHER, name=STAGE, identity=(1, 2))):
            with pytest.raises(module.InferenceJournalError):
                action()
            assert journal.record is first
        staged = journal.attach_stage(RUN, name=STAGE, identity=(1, 2))
        with pytest.raises(module.InferenceJournalError):
            journal.attach_stage(RUN, name=STAGE, identity=(1, 3))
        assert journal.record is staged
        journal.complete(RUN)
        with pytest.raises(module.InferenceJournalError):
            journal.complete(OTHER)


@pytest.mark.parametrize("kind", ["file", "directory"])
@pytest.mark.parametrize("phase", ["entry", "begin", "complete", "missing"])
def test_unexpected_children_are_untouched(tmp_path, kind, phase):
    module = api()
    root = tmp_path / "state"
    journal = module.LocalInferenceJournal(root)
    def residue():
        child = root / STAGE
        if kind == "directory":
            child.mkdir()
            (child / "private").write_bytes(SECRET.encode())
        else:
            child.write_bytes(SECRET.encode())
        return child
    if phase in ("entry", "missing"):
        with ResourceStore(root, NAMESPACE).lease(create=True):
            pass
        if phase == "entry":
            with journal.lease():
                pass
        child = residue()
        with pytest.raises(module.InferenceRecoveryRequired):
            with journal.lease():
                pytest.fail("residue admitted")
    else:
        with journal.lease():
            if phase == "complete":
                begin(journal)
            previous = journal.record
            child = residue()
            with pytest.raises(module.InferenceRecoveryRequired):
                begin(journal) if phase == "begin" else journal.complete(RUN)
            assert journal.record is previous
    assert child.exists()
    assert (child / "private" if kind == "directory" else child).read_bytes() == SECRET.encode()


INVALID_RECORDS = [
    b"", b"{", b" " * 4097, b"[" * 1800 + b"]" * 1800, b"\xff",
    b'{"revision":0,"revision":1}', b'{"revision":NaN}', b'{"revision":Infinity}',
    json.dumps(payload(schema_version=True)).encode(), json.dumps(payload(schema_version=2)).encode(),
    json.dumps(payload(extra=SECRET)).encode(), json.dumps(payload(revision=True)).encode(),
    json.dumps(payload(revision=-1)).encode(), json.dumps(payload(revision=2**63)).encode(),
    json.dumps(payload(revision=1.0)).encode(), json.dumps(payload(phase=SECRET)).encode(),
    json.dumps(payload(run_id=RUN)).encode(), json.dumps(payload(revision=1)).encode(),
    json.dumps(active_payload(run_id=OTHER)).encode(), json.dumps(active_payload(profile_name=PROFILE.upper())).encode(),
    json.dumps(active_payload(catalog_id=SECRET)).encode(), json.dumps(active_payload(package_sid="S-1-15-2-01-1-2-3-4-5-6")).encode(),
    json.dumps(active_payload(package_sid="S-1-15-2-0-1-2-3-4-5-4294967296")).encode(),
    json.dumps(active_payload(stage_name=STAGE)).encode(), json.dumps(active_payload(stage_identity=[1, 2])).encode(),
    json.dumps(active_payload(stage_name="../" + STAGE, stage_identity=[1, 2])).encode(),
    *[json.dumps(active_payload(stage_name=STAGE, stage_identity=value)).encode()
      for value in ([True, 1], [1, False], [1, 0], [-1, 1], [2**32, 1], [1, 2**64], [1, 2, 3], "1,2")],
]


@pytest.mark.parametrize("raw", INVALID_RECORDS)
def test_invalid_disk_records_fail_closed_without_reset(tmp_path, raw):
    module = api()
    root = tmp_path / "state"
    seed(root, raw)
    with pytest.raises(module.InferenceRecoveryRequired, match="^RECOVERY_REQUIRED$") as caught:
        with module.LocalInferenceJournal(root).lease():
            pytest.fail("invalid record admitted")
    assert (root / BASENAME).read_bytes() == raw
    assert SECRET not in str(caught.value) + repr(caught.value)


@pytest.mark.parametrize("field,value", [("catalog_id", SECRET), ("profile_name", SECRET),
    ("profile_name", "xuxia_local_" + "B" * 32), ("package_sid", SECRET),
    ("package_sid", "S-1-15-2-1-2-3-4-5-6"), ("catalog_id", True)])
def test_begin_rejects_private_or_invalid_input_without_persistence(tmp_path, field, value):
    module = api()
    root = tmp_path / "state"
    with module.LocalInferenceJournal(root).lease() as journal:
        kwargs = dict(catalog_id=CATALOG, profile_name=PROFILE, package_sid=SID)
        kwargs[field] = value
        with pytest.raises(module.InferenceJournalError) as caught:
            journal.begin(**kwargs)
        assert journal.record.revision == 0
        assert SECRET not in repr(journal) + repr(journal.record) + repr(caught.value)
    assert SECRET.encode() not in (root / BASENAME).read_bytes()


@pytest.mark.parametrize("name,identity", [(SECRET, (1, 2)), ("../" + STAGE, (1, 2)),
    (STAGE + "/x", (1, 2)), (STAGE, [1, 2]), (STAGE, (True, 2)), (STAGE, (1, 0)),
    (STAGE, (1, 2**64)), (STAGE, (2**32, 1)), (STAGE, (1,)), (None, None)])
def test_false_stage_metadata_rejected(tmp_path, name, identity):
    module = api()
    with module.LocalInferenceJournal(tmp_path / "state").lease() as journal:
        first = begin(journal)
        with pytest.raises(module.InferenceJournalError) as caught:
            journal.attach_stage(RUN, name=name, identity=identity)
        assert journal.record is first
        assert SECRET not in repr(caught.value)


def test_revision_overflow_rejected_before_write(tmp_path):
    module = api()
    root = tmp_path / "state"
    original = json.dumps(active_payload(revision=2**63 - 1, phase="clean")).encode()
    seed(root, original)
    with module.LocalInferenceJournal(root).lease() as journal:
        with pytest.raises(module.InferenceJournalError):
            begin(journal)
        assert journal.record.revision == 2**63 - 1
    assert (root / BASENAME).read_bytes() == original


class FaultStream:
    def __init__(self, stream, failure, events):
        self.stream, self.failure, self.events = stream, failure, events
    def __getattr__(self, name):
        return getattr(self.stream, name)
    def seek(self, *args):
        self.events.append("seek")
        return self.stream.seek(*args)
    def write(self, data):
        self.events.append("write")
        if self.failure == "write":
            raise OSError(SECRET)
        if self.failure == "short":
            return self.stream.write(data[:len(data) // 2])
        return self.stream.write(data)
    def truncate(self, size):
        self.events.append("truncate")
        if self.failure == "truncate":
            raise OSError(SECRET)
        return self.stream.truncate(size)
    def flush(self):
        self.events.append("flush")
        if self.failure == "flush":
            raise OSError(SECRET)
        return self.stream.flush()


@pytest.mark.parametrize("failure", ["write", "short", "truncate", "flush", "fsync"])
@pytest.mark.parametrize("operation", ["begin", "attach", "complete"])
def test_failed_write_latches_preserves_memory_and_restart_fails_closed(tmp_path, monkeypatch, failure, operation):
    module = api()
    root = tmp_path / "state"
    events = []
    with module.LocalInferenceJournal(root).lease() as journal:
        if operation != "begin":
            begin(journal)
        before = journal.record
        original_stream = journal._stream
        journal._stream = FaultStream(original_stream, failure, events)
        real_fsync = module.os.fsync
        def fsync(fd):
            events.append("fsync")
            if failure == "fsync":
                raise OSError(SECRET)
            return real_fsync(fd)
        monkeypatch.setattr(module.os, "fsync", fsync)
        action = dict(begin=lambda: begin(journal), attach=lambda: journal.attach_stage(RUN, name=STAGE, identity=(1, 2)),
                      complete=lambda: journal.complete(RUN))[operation]
        with pytest.raises(module.InferenceJournalError, match="^JOURNAL_WRITE_FAILED$") as caught:
            action()
        assert journal.record is before
        assert SECRET not in str(caught.value) + repr(caught.value)
        for again in (lambda: begin(journal), lambda: journal.attach_stage(RUN, name=STAGE, identity=(1, 2)),
                      lambda: journal.complete(RUN)):
            with pytest.raises(module.InferenceJournalError, match="^JOURNAL_WRITE_FAILED$"):
                again()
        assert events[0:2] == ["seek", "write"]
        journal._stream = original_stream
        monkeypatch.setattr(module.os, "fsync", real_fsync)
    raw = (root / BASENAME).read_bytes()
    try:
        disk = json.loads(raw)
    except ValueError:
        disk = None
    # Failed writes need not roll back. Only an actually valid clean disk may reopen.
    if disk is not None and disk.get("phase") == "clean":
        with module.LocalInferenceJournal(root).lease() as reopened:
            assert reopened.record.phase == "clean"
    else:
        with pytest.raises(module.InferenceRecoveryRequired):
            with module.LocalInferenceJournal(root).lease():
                pytest.fail("malformed/active disk admitted")


def test_writes_use_one_pin_and_ordered_durable_stream(tmp_path, monkeypatch):
    module = api()
    events = []
    pins = []
    real_pin = ResourceStore.pin
    def pin(store, name, **kwargs):
        pins.append((name, kwargs))
        return real_pin(store, name, **kwargs)
    monkeypatch.setattr(ResourceStore, "pin", pin)
    with module.LocalInferenceJournal(tmp_path / "state").lease() as journal:
        original = journal._stream
        journal._stream = FaultStream(original, None, events)
        real_fsync = module.os.fsync
        def fsync(fd):
            events.append("fsync")
            return real_fsync(fd)
        monkeypatch.setattr(module.os, "fsync", fsync)
        begin(journal)
        journal.complete(RUN)
        assert events.count("write") == 2
        assert events[-10:] == ["seek", "write", "truncate", "flush", "fsync"] * 2
        journal._stream = original
    assert original.closed
    assert pins == [(BASENAME, {"writable": True, "create": True})]


def test_no_native_process_profile_or_cleanup_api_used(tmp_path, monkeypatch):
    module = api()
    import subprocess
    def forbidden(*args, **kwargs):
        raise AssertionError("native ownership API must not be called")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(Path, "unlink", forbidden)
    monkeypatch.setattr(Path, "rmdir", forbidden)
    monkeypatch.setattr(module, "create_profile", forbidden, raising=False)
    monkeypatch.setattr(module, "delete_profile", forbidden, raising=False)
    with module.LocalInferenceJournal(tmp_path / "state").lease() as journal:
        begin(journal)
        journal.attach_stage(RUN, name=STAGE, identity=(2**32 - 1, 2**64 - 1))
        journal.complete(RUN)


def test_cross_process_journal_lease_exclusion(tmp_path):
    module = api()
    root = tmp_path / "state"
    code = """import sys
from pathlib import Path
from src.services.local_ai.inference_journal import LocalInferenceJournal
from src.services.local_ai.resource_store import StoreBusy
try:
    with LocalInferenceJournal(Path(sys.argv[1])).lease(create=False):
        print('ACQUIRED', flush=True)
except StoreBusy:
    print('BUSY', flush=True)
"""
    with module.LocalInferenceJournal(root).lease():
        result = subprocess.run([sys.executable, "-c", code, str(root)],
                                capture_output=True, text=True, check=True)
        assert result.stdout.strip() == "BUSY"
        assert not result.stderr
    result = subprocess.run([sys.executable, "-c", code, str(root)],
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "ACQUIRED"
    assert not result.stderr


def test_pin_blocks_replacement_and_all_handles_release_on_body_error(tmp_path):
    module = api()
    root = tmp_path / "state"
    with pytest.raises(RuntimeError, match="caller stopped"):
        with module.LocalInferenceJournal(root).lease() as journal:
            stream = journal._stream
            with pytest.raises(OSError):
                (root / BASENAME).rename(root / "renamed")
            raise RuntimeError("caller stopped")
    assert stream.closed
    with module.LocalInferenceJournal(root).lease():
        pass
    (root / BASENAME).rename(root / "renamed")
    assert (root / "renamed").exists()


@pytest.mark.parametrize("raw", [
    json.dumps(payload()).replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1').encode(),
    json.dumps(payload()).replace('"revision": 0', '"revision": NaN').encode(),
    json.dumps(payload()).replace('"revision": 0', '"revision": -Infinity').encode(),
    b"null", b"[]", json.dumps({k: v for k, v in payload().items() if k != "stage_name"}).encode(),
    json.dumps(active_payload(revision=0)).encode(),
])
def test_strict_json_validation_and_failed_entry_releases_pins(tmp_path, raw):
    module = api()
    root = tmp_path / "state"
    seed(root, raw)
    journal = module.LocalInferenceJournal(root)
    for _ in range(2):
        with pytest.raises(module.InferenceRecoveryRequired):
            with journal.lease():
                pytest.fail("invalid record admitted")
    # A fresh canonical store lease proves failed entry did not retain handles.
    with ResourceStore(root, NAMESPACE).lease() as store:
        with store.open_file(BASENAME, "r+b") as stream:
            assert stream.read() == raw


@pytest.mark.parametrize("failure", ["write", "short", "truncate", "flush", "fsync"])
def test_initialization_write_failure_never_admitted(tmp_path, monkeypatch, failure):
    module = api()
    from src.services.local_ai import resource_store
    root = tmp_path / "state"
    with ResourceStore(root, NAMESPACE).lease(create=True):
        pass
    real_stream = resource_store._PinnedFile.stream
    real_fsync = module.os.fsync
    held = []
    def stream(pin, mode="rb"):
        result = real_stream(pin, mode)
        if mode == "r+b":
            held.append(result)
            return FaultStream(result, failure, [])
        return result
    def fsync(fd):
        if failure == "fsync":
            raise OSError(SECRET)
        return real_fsync(fd)
    with monkeypatch.context() as patch:
        patch.setattr(resource_store._PinnedFile, "stream", stream)
        patch.setattr(module.os, "fsync", fsync)
        with pytest.raises(module.InferenceJournalError, match="^JOURNAL_WRITE_FAILED$"):
            with module.LocalInferenceJournal(root).lease():
                pytest.fail("failed initial write admitted")
    assert held and all(item.closed for item in held)
    if failure in ("write", "short"):
        with pytest.raises(module.InferenceRecoveryRequired):
            with module.LocalInferenceJournal(root).lease():
                pytest.fail("empty/truncated initial write admitted")
    else:
        with module.LocalInferenceJournal(root).lease() as journal:
            assert journal.record.revision == 0


def test_active_revision_overflow_refuses_attach_and_complete(tmp_path):
    module = api()
    root = tmp_path / "state"
    seed(root, json.dumps(active_payload(phase="clean", revision=2**63 - 2)).encode())
    with module.LocalInferenceJournal(root).lease() as journal:
        record = begin(journal)
        assert record.revision == 2**63 - 1
        for action in (lambda: journal.attach_stage(RUN, name=STAGE, identity=(1, 2)),
                       lambda: journal.complete(RUN)):
            with pytest.raises(module.InferenceJournalError, match="^JOURNAL_REVISION_OVERFLOW$"):
                action()
            assert journal.record is record


def test_direct_record_and_errors_never_repr_unvalidated_content(tmp_path):
    module = api()
    with pytest.raises(module.InferenceJournalError) as caught:
        module.InferenceRunRecord(1, SECRET, "active", CATALOG, PROFILE, SID, None, None)
    assert SECRET not in repr(caught.value)
    assert SECRET not in repr(module.InferenceJournalError(SECRET))
    assert SECRET not in repr(module.LocalInferenceJournal(tmp_path / SECRET.replace("/", "_")))


def test_marker_only_requires_create_permission(tmp_path):
    module = api()
    root = tmp_path / "state"
    with ResourceStore(root, NAMESPACE).lease(create=True):
        pass
    with pytest.raises(module.InferenceRecoveryRequired):
        with module.LocalInferenceJournal(root).lease(create=False):
            pytest.fail("missing file admitted without create")
    assert {child.name for child in root.iterdir()} == {MARKER}
    with module.LocalInferenceJournal(root).lease() as journal:
        assert journal.record.revision == 0


@pytest.mark.parametrize("kind", ["foreign_namespace", "journal_directory", "journal_hardlink"])
def test_unsafe_store_or_journal_is_untouched(tmp_path, kind):
    module = api()
    root = tmp_path / "state"
    namespace = CATALOG if kind == "foreign_namespace" else NAMESPACE
    with ResourceStore(root, namespace).lease(create=True):
        pass
    original = tmp_path / "synthetic-original"
    if kind == "journal_directory":
        (root / BASENAME).mkdir()
    if kind == "journal_hardlink":
        original.write_bytes(json.dumps(payload()).encode())
        os.link(original, root / BASENAME)
    with pytest.raises(module.InferenceRecoveryRequired):
        with module.LocalInferenceJournal(root).lease():
            pytest.fail("unsafe journal admitted")
    assert json.loads((root / MARKER).read_bytes())["catalog_id"] == namespace
    if kind == "journal_directory":
        assert (root / BASENAME).is_dir()
    if kind == "journal_hardlink":
        assert json.loads(original.read_bytes()) == payload()


def test_bounded_read_and_exact_truncation_of_padded_record(tmp_path):
    module = api()
    root = tmp_path / "state"
    seed(root, json.dumps(payload()).encode().ljust(4096))
    with module.LocalInferenceJournal(root).lease() as journal:
        begin(journal)
        journal.complete(RUN)
    raw = (root / BASENAME).read_bytes()
    assert len(raw) < 4096
    assert raw == json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":")).encode()
    assert json.loads(raw)["revision"] == 2
def test_recovery_inspection_missing_is_readonly(tmp_path):
    import src.services.local_ai.inference_journal as module
    journal = module.LocalInferenceJournal(tmp_path / "absent")
    assert hasattr(journal, "inspect_recovery_state"), "readonly recovery inspection missing"
    assert journal.inspect_recovery_state() is module.InferenceRecoveryState.MISSING
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("kind", ["clean", "malformed", "unknown", "unowned", "busy"])
def test_recovery_inspection_preserves_bytes_and_times(tmp_path, kind):
    import src.services.local_ai.inference_journal as module
    root = tmp_path / "state"
    journal = module.LocalInferenceJournal(root)
    assert hasattr(journal, "inspect_recovery_state"), "readonly recovery inspection missing"
    with journal.lease():
        pass
    if kind == "malformed":
        (root / "inference-run.json").write_bytes(b"bad")
    elif kind == "unknown":
        (root / "unknown").write_bytes(b"keep")
    elif kind == "unowned":
        (root / MARKER).write_bytes(b"bad")
    def fingerprint():
        return {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in root.iterdir()}
    before = fingerprint()
    if kind == "busy":
        with journal.lease():
            assert module.LocalInferenceJournal(root).inspect_recovery_state() is module.InferenceRecoveryState.BUSY
    else:
        expected = module.InferenceRecoveryState.CLEAN if kind == "clean" else module.InferenceRecoveryState.RECOVERY_REQUIRED
        assert journal.inspect_recovery_state() is expected
    assert fingerprint() == before


@pytest.mark.parametrize("kind", ["dirty", "empty", "marker_only", "clean"])
def test_recovery_observation_never_writes_or_initializes(tmp_path, monkeypatch, kind):
    module = api()
    root = tmp_path / "state"
    journal = module.LocalInferenceJournal(root)
    if kind == "empty":
        root.mkdir()
    elif kind == "marker_only":
        with ResourceStore(root, NAMESPACE).lease(create=True):
            pass
    else:
        with journal.lease():
            if kind == "dirty":
                begin(journal)
    before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in root.iterdir()}
    root_time = root.stat().st_mtime_ns
    def forbidden(*args, **kwargs):
        pytest.fail("readonly observation attempted mutation")
    original = ResourceStore.pin
    def readonly(store, name, *, writable=False, create=False):
        assert not writable and not create
        return original(store, name, writable=writable, create=create)
    monkeypatch.setattr(ResourceStore, "pin", readonly)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(module.os, "fsync", forbidden)
    expected = module.InferenceRecoveryState.CLEAN if kind == "clean" else module.InferenceRecoveryState.RECOVERY_REQUIRED
    assert journal.inspect_recovery_state() is expected
    assert before == {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in root.iterdir()}
    assert root.stat().st_mtime_ns == root_time

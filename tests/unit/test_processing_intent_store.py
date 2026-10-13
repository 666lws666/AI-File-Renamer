"""Strict intent persistence and deterministic writer lifecycle tests."""
from dataclasses import FrozenInstanceError
import importlib.util
import json
import os
from pathlib import Path
from threading import Event, Lock
import time

import pytest

from src.core.processing_authority import (
    ChoiceIntent, LocalReadiness, PersistenceStatus, ProcessingAuthority,
    ProcessingMode,
)


def api():
    assert importlib.util.find_spec("src.core.processing_intent_store") is not None
    from src.core import processing_intent_store
    return processing_intent_store


def intent(revision=1, mode=ProcessingMode.LOCAL):
    return ChoiceIntent("test-session", revision, mode)


def test_missing_only_defaults_cloud_and_record_is_frozen(tmp_path):
    record = api().ProcessingIntentStore(tmp_path / "missing" / "intent.json").load()
    assert (record.mode, record.revision, record.startup_error) == (ProcessingMode.CLOUD, 0, False)
    with pytest.raises(FrozenInstanceError):
        record.revision = 2
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize("payload", [
    b"", b"{", b"[]", b"null", b"\xff", b" " * 4097,
    b'{"schema_version":1,"revision":1,"mode":"local","mode":"cloud"}',
    b'{"schema_version":1,"revision":NaN,"mode":"cloud"}',
    b'{"schema_version":1,"revision":Infinity,"mode":"cloud"}',
] + [json.dumps(value).encode() for value in [
    {"schema_version": 2, "revision": 1, "mode": "cloud"},
    {"schema_version": True, "revision": 1, "mode": "cloud"},
    {"schema_version": 1.0, "revision": 1, "mode": "cloud"},
    {"schema_version": 1, "revision": True, "mode": "cloud"},
    {"schema_version": 1, "revision": 0, "mode": "cloud"},
    {"schema_version": 1, "revision": -1, "mode": "cloud"},
    {"schema_version": 1, "revision": 2**63, "mode": "cloud"},
    {"schema_version": 1, "revision": 1.0, "mode": "cloud"},
    {"schema_version": 1, "revision": "1", "mode": "cloud"},
    {"schema_version": 1, "revision": 1, "mode": "CLOUD"},
    {"schema_version": 1, "revision": 1, "mode": None},
    {"schema_version": 1, "revision": 1},
    {"schema_version": 1, "revision": 1, "mode": "cloud", "provider": "secret"},
]])
def test_invalid_records_fail_closed_without_rewrite(tmp_path, payload):
    path = tmp_path / "intent.json"
    path.write_bytes(payload)
    record = api().ProcessingIntentStore(path).load()
    assert record.startup_error and record.mode is ProcessingMode.LOCAL
    assert record.revision == 0
    assert path.read_bytes() == payload


@pytest.mark.parametrize("mode", list(ProcessingMode))
def test_save_exact_schema_and_restore_unready(tmp_path, mode):
    path = tmp_path / "nested" / "intent.json"
    store = api().ProcessingIntentStore(path)
    store.save(intent(7, mode))
    assert json.loads(path.read_bytes()) == {"schema_version": 1, "revision": 7, "mode": mode.value}
    record = store.load()
    authority = ProcessingAuthority(initial_mode=record.mode, initial_revision=record.revision,
                                    startup_error=record.startup_error)
    assert authority.snapshot().mode is mode
    assert authority.snapshot().local_readiness is LocalReadiness.NOT_READY
    assert not record.startup_error
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("bad", [intent(True), intent(0), intent(2**63), intent(1, "local"), object()])
def test_save_prevalidates_before_filesystem_changes(tmp_path, bad):
    path = tmp_path / "absent" / "intent.json"
    with pytest.raises(api().ProcessingIntentError, match="^PROCESSING_PERSISTENCE_ERROR$"):
        api().ProcessingIntentStore(path).save(bad)
    assert not path.parent.exists()


def test_nonregular_target_and_parent_fail_closed(tmp_path):
    path = tmp_path / "directory"
    path.mkdir()
    assert api().ProcessingIntentStore(path).load().startup_error
    with pytest.raises(api().ProcessingIntentError):
        api().ProcessingIntentStore(path).save(intent())
    parent = tmp_path / "file"
    parent.write_bytes(b"keep")
    assert api().ProcessingIntentStore(parent / "intent.json").load().startup_error
    assert parent.read_bytes() == b"keep"


def test_unreadable_is_not_legacy_missing(tmp_path, monkeypatch):
    path = tmp_path / "intent.json"
    path.write_bytes(b"keep")
    monkeypatch.setattr(api(), "_read_record", lambda path: (_ for _ in ()).throw(PermissionError("private")))
    assert api().ProcessingIntentStore(path).load().startup_error
    assert path.read_bytes() == b"keep"


@pytest.mark.parametrize("failure", ["mkdir", "fdopen", "write", "short_write", "flush", "fsync", "replace"])
def test_real_file_failures_preserve_previous_bytes(tmp_path, monkeypatch, failure):
    module = api()
    path = tmp_path / "intent.json"
    store = module.ProcessingIntentStore(path)
    store.save(intent(1))
    previous = path.read_bytes()
    def fail(*args, **kwargs):
        raise OSError("private path/provider detail")
    with monkeypatch.context() as patch:
        if failure == "mkdir":
            patch.setattr(Path, "mkdir", fail)
        elif failure == "fdopen":
            patch.setattr(module.os, "fdopen", fail)
        elif failure in ("write", "short_write", "flush"):
            original = os.fdopen
            class BrokenFile:
                def __init__(self, fd, *args, **kwargs):
                    self.file = original(fd, *args, **kwargs)
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    self.file.close()
                def write(self, data):
                    if failure == "short_write":
                        return self.file.write(data[:3])
                    if failure == "write":
                        self.file.write(data[:3])
                        fail()
                    return self.file.write(data)
                def flush(self):
                    if failure == "flush":
                        fail()
                    self.file.flush()
                def fileno(self):
                    return self.file.fileno()
            patch.setattr(module.os, "fdopen", BrokenFile)
        elif failure == "replace":
            patch.setattr(module, "_atomic_replace", fail)
        else:
            patch.setattr(module.os, failure, fail)
        with pytest.raises(module.ProcessingIntentError, match="^PROCESSING_PERSISTENCE_ERROR$"):
            store.save(intent(2, ProcessingMode.CLOUD))
    assert path.read_bytes() == previous
    assert store.load().revision == 1
    assert list(tmp_path.iterdir()) == [path]


class ObservedAuthority(ProcessingAuthority):
    def __init__(self):
        super().__init__(initial_mode=ProcessingMode.LOCAL)
        self.completions = []
        self.completed = Event()
        self.writer = None

    def complete_choice(self, choice, *, persisted):
        if self.writer is not None:
            assert self.writer._condition.acquire(blocking=False)
            self.writer._condition.release()
        result = super().complete_choice(choice, persisted=persisted)
        self.completions.append((choice, persisted))
        self.completed.set()
        return result


class BlockingStore:
    def __init__(self, real=None, fail_first=False):
        self.started = Event()
        self.release = Event()
        self.revisions = []
        self.real = real
        self.fail_first = fail_first
        self.saving = Lock()

    def save(self, choice):
        assert self.saving.acquire(blocking=False)
        try:
            self.revisions.append(choice.revision)
            if len(self.revisions) == 1:
                self.started.set()
                assert self.release.wait(5)
                if self.fail_first:
                    raise OSError("private detail")
            if self.real is not None:
                self.real.save(choice)
        finally:
            self.saving.release()


@pytest.mark.parametrize("fail_first", [False, True])
def test_delayed_cloud_then_local_is_ordered_and_never_reopens(tmp_path, fail_first):
    module = api()
    authority = ObservedAuthority()
    real = module.ProcessingIntentStore(tmp_path / "intent.json")
    store = BlockingStore(real, fail_first)
    writer = module.ProcessingIntentWriter(store, authority)
    authority.writer = writer
    assert authority.snapshot().revision == 0
    cloud = authority.request_cloud_choice()
    assert writer.submit(cloud)
    assert store.started.wait(2)
    local = authority.select_local().intent
    assert writer.submit(local)
    assert authority.snapshot().mode is ProcessingMode.LOCAL
    store.release.set()
    assert writer.close()
    assert writer.close()
    assert store.revisions == [1, 2]
    assert authority.completions == [(cloud, not fail_first), (local, True)]
    assert authority.snapshot().mode is ProcessingMode.LOCAL
    assert real.load().revision == 2 and real.load().mode is ProcessingMode.LOCAL


@pytest.mark.parametrize("mode", list(ProcessingMode))
def test_failed_current_choice_can_retry_same_intent_without_generation_change(mode):
    module = api()
    authority = ObservedAuthority()
    store = BlockingStore(fail_first=True)
    store.release.set()
    writer = module.ProcessingIntentWriter(store, authority)
    authority.writer = writer
    choice = authority.request_cloud_choice() if mode is ProcessingMode.CLOUD else authority.select_local().intent
    generation = authority.snapshot().generation
    assert writer.submit(choice)
    assert authority.completed.wait(2)
    assert authority.snapshot().mode is ProcessingMode.LOCAL
    assert authority.snapshot().persistence_status is PersistenceStatus.ERROR
    assert authority.snapshot().generation == generation
    authority.completed.clear()
    assert writer.submit(choice)
    assert authority.completed.wait(2)
    assert writer.close()
    assert store.revisions == [choice.revision, choice.revision]
    assert authority.completions == [(choice, False), (choice, True)]
    assert authority.snapshot().persistence_status is PersistenceStatus.SAVED


def test_old_retry_and_out_of_order_choices_do_not_overwrite(tmp_path):
    module = api()
    authority = ObservedAuthority()
    store = module.ProcessingIntentStore(tmp_path / "intent.json")
    writer = module.ProcessingIntentWriter(store, authority)
    authority.writer = writer
    old = authority.request_cloud_choice()
    new = authority.select_local().intent
    assert writer.submit(new)
    assert not writer.submit(old)
    assert writer.close()
    assert store.load().revision == new.revision
    assert len(authority.completions) == 2


def test_bounded_close_retains_pending_notifications():
    module = api()
    authority = ObservedAuthority()
    store = BlockingStore()
    writer = module.ProcessingIntentWriter(store, authority)
    authority.writer = writer
    cloud = authority.request_cloud_choice()
    writer.submit(cloud)
    assert store.started.wait(2)
    local = authority.select_local().intent
    writer.submit(local)
    started = time.monotonic()
    assert writer.close() is False
    assert time.monotonic() - started < 1.5
    assert writer._thread.daemon
    store.release.set()
    assert writer.close()
    assert len(authority.completions) == 2
    assert authority.snapshot().mode is ProcessingMode.LOCAL
    assert not writer.submit(local)
    assert len(authority.completions) == 3


def test_disappearing_record_after_validation_is_closed_not_legacy(tmp_path, monkeypatch):
    module = api()
    path = tmp_path / "intent.json"
    module.ProcessingIntentStore(path).save(intent())
    def disappear(*args, **kwargs):
        path.unlink()
        raise FileNotFoundError("raced disappearance")
    monkeypatch.setattr(module, "_open_read", disappear)
    assert module.ProcessingIntentStore(path).load().startup_error


def test_replaced_temporary_is_neither_published_nor_deleted(tmp_path, monkeypatch):
    module = api()
    path = tmp_path / "intent.json"
    store = module.ProcessingIntentStore(path)
    store.save(intent())
    previous = path.read_bytes()
    original_check = module._check_parents
    foreign = b"belongs to a different operation"
    substituted = []
    def substitute(identities):
        original_check(identities)
        candidates = list(tmp_path.glob(".processing-intent-*.tmp"))
        if candidates and not substituted:
            temporary = candidates[0]
            displaced = tmp_path / "displaced-owned-file"
            try:
                temporary.rename(displaced)
            except PermissionError:
                # An OS handle lock is also valid substitution protection.
                raise OSError("substitution blocked")
            temporary.write_bytes(foreign)
            substituted.append(temporary)
    monkeypatch.setattr(module, "_check_parents", substitute)
    with pytest.raises(module.ProcessingIntentError):
        store.save(intent(2, ProcessingMode.CLOUD))
    assert path.read_bytes() == previous
    for temporary in substituted:
        assert temporary.read_bytes() == foreign


def test_replaced_parent_is_not_followed_or_cleaned(tmp_path, monkeypatch):
    module = api()
    parent = tmp_path / "settings"
    path = parent / "intent.json"
    store = module.ProcessingIntentStore(path)
    store.save(intent())
    previous = path.read_bytes()
    original_check = module._check_parents
    displaced = tmp_path / "displaced-parent"
    switched = []
    def substitute(identities):
        candidates = list(parent.glob(".processing-intent-*.tmp"))
        if candidates and not switched:
            try:
                parent.rename(displaced)
            except PermissionError:
                raise OSError("substitution blocked")
            parent.mkdir()
            (parent / candidates[0].name).write_bytes(b"foreign temporary")
            path.write_bytes(b"foreign target")
            switched.append(True)
        original_check(identities)
    monkeypatch.setattr(module, "_check_parents", substitute)
    with pytest.raises(module.ProcessingIntentError):
        store.save(intent(2, ProcessingMode.CLOUD))
    if switched:
        assert (displaced / "intent.json").read_bytes() == previous
        assert path.read_bytes() == b"foreign target"
        assert next(parent.glob(".processing-intent-*.tmp")).read_bytes() == b"foreign temporary"
    else:
        assert path.read_bytes() == previous


@pytest.mark.skipif(os.name != "nt", reason="Windows junction/reparse regression")
def test_windows_junction_parent_is_rejected(tmp_path):
    import subprocess
    module = api()
    external = tmp_path / "external"
    external.mkdir()
    outside = external / "intent.json"
    outside.write_bytes(b"untouched outside data")
    junction = tmp_path / "junction"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(external)],
                            capture_output=True, timeout=5)
    assert result.returncode == 0
    try:
        store = module.ProcessingIntentStore(junction / "intent.json")
        assert store.load().startup_error
        with pytest.raises(module.ProcessingIntentError):
            store.save(intent())
        assert outside.read_bytes() == b"untouched outside data"
        assert list(external.iterdir()) == [outside]
    finally:
        junction.rmdir()  # Remove the exact junction, never recurse into its target.


def test_failed_older_revision_cannot_retry_after_newer_choice(tmp_path):
    module = api()
    authority = ObservedAuthority()
    real = module.ProcessingIntentStore(tmp_path / "intent.json")
    store = BlockingStore(real, fail_first=True)
    store.release.set()
    writer = module.ProcessingIntentWriter(store, authority)
    authority.writer = writer
    old = authority.request_cloud_choice()
    writer.submit(old)
    assert authority.completed.wait(2)
    new = authority.select_local().intent
    assert writer.submit(new)
    assert not writer.submit(old)
    assert writer.close()
    assert store.revisions == [old.revision, new.revision]
    assert real.load().revision == new.revision


def test_successful_duplicate_and_foreign_session_never_write_again():
    module = api()
    authority = ObservedAuthority()
    store = BlockingStore()
    store.release.set()
    writer = module.ProcessingIntentWriter(store, authority)
    authority.writer = writer
    choice = authority.select_local().intent
    assert writer.submit(choice)
    assert authority.completed.wait(2)
    assert not writer.submit(choice)
    assert not writer.submit(ChoiceIntent("foreign", choice.revision, choice.mode))
    assert writer.close()
    assert store.revisions == [choice.revision]
    assert len(authority.completions) == 3


def test_forged_choice_is_not_persisted_even_with_matching_public_fields(tmp_path):
    module = api()
    authority = ObservedAuthority()
    path = tmp_path / "intent.json"
    writer = module.ProcessingIntentWriter(module.ProcessingIntentStore(path), authority)
    authority.writer = writer
    choice = authority.request_cloud_choice()
    forged = ChoiceIntent(choice.session_id, choice.revision, choice.mode)
    assert not writer.submit(forged)
    assert writer.close()
    assert not path.exists()
    assert authority.snapshot().mode is ProcessingMode.LOCAL


def test_superseded_queued_choice_is_skipped_before_io(tmp_path):
    module = api()
    authority = ObservedAuthority()
    store = BlockingStore(module.ProcessingIntentStore(tmp_path / "intent.json"))
    writer = module.ProcessingIntentWriter(store, authority)
    authority.writer = writer
    first = authority.request_cloud_choice()
    writer.submit(first)
    assert store.started.wait(2)
    second = authority.select_local().intent
    writer.submit(second)
    latest = authority.request_cloud_choice()
    writer.submit(latest)
    store.release.set()
    assert writer.close()
    assert store.revisions == [first.revision, latest.revision]
    assert authority.completions == [(first, True), (second, False), (latest, True)]


@pytest.mark.skipif(os.name != "nt", reason="Windows handle pinning")
@pytest.mark.parametrize("substitution", ["parent", "temporary"])
def test_windows_final_publish_window_is_pinned(tmp_path, monkeypatch, substitution):
    module = api()
    assert hasattr(module, "_atomic_replace")
    parent = tmp_path / "settings"
    path = parent / "intent.json"
    store = module.ProcessingIntentStore(path)
    store.save(intent())
    previous = path.read_bytes()
    attempted = []
    def attack(candidate, temporary, destination):
        attempted.append(True)
        if substitution == "parent":
            with pytest.raises(PermissionError):
                parent.rename(tmp_path / "moved-parent")
        else:
            with pytest.raises(PermissionError):
                temporary.rename(parent / "moved-temporary")
        # Injection deliberately fails publication, so previous durable bytes survive.
        raise OSError("publish failure")
    monkeypatch.setattr(module, "_atomic_replace", attack)
    with pytest.raises(module.ProcessingIntentError):
        store.save(intent(2, ProcessingMode.CLOUD))
    assert attempted
    assert path.read_bytes() == previous
    assert list(parent.iterdir()) == [path]


def test_target_symlink_never_reads_or_rewrites_referent(tmp_path):
    module = api()
    outside = tmp_path / "outside.json"
    outside.write_bytes(b'{"schema_version":1,"revision":7,"mode":"cloud"}')
    path = tmp_path / "intent.json"
    try:
        path.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"file symlink unavailable: {error.winerror if hasattr(error, 'winerror') else error.errno}")
    store = module.ProcessingIntentStore(path)
    assert store.load().startup_error
    with pytest.raises(module.ProcessingIntentError):
        store.save(intent())
    assert outside.read_bytes() == b'{"schema_version":1,"revision":7,"mode":"cloud"}'
    assert path.is_symlink()


def test_exact_maximum_size_and_revision_are_accepted(tmp_path):
    module = api()
    path = tmp_path / "intent.json"
    payload = json.dumps({"schema_version": 1, "revision": 2**63 - 1, "mode": "local"}).encode()
    path.write_bytes(payload + b" " * (4096 - len(payload)))
    record = module.ProcessingIntentStore(path).load()
    assert not record.startup_error and record.revision == 2**63 - 1


@pytest.mark.parametrize("fail", [False, True])
def test_external_completion_replaces_worker_and_rejection_completion(fail):
    authority = ObservedAuthority()
    store = BlockingStore(fail_first=fail)
    store.release.set()
    notifications = []
    def completed(choice, persisted):
        assert writer._condition.acquire(blocking=False)
        writer._condition.release()
        notifications.append((choice, persisted))
    writer = api().ProcessingIntentWriter(store, authority, completion_callback=completed)
    choice = authority.request_cloud_choice()
    assert writer.submit(choice)
    assert writer.close()
    assert notifications == [(choice, not fail)]
    assert authority.completions == []
    assert authority.snapshot().persistence_status is PersistenceStatus.PENDING
    assert not writer.submit(choice)
    assert notifications == [(choice, not fail), (choice, False)]
    assert authority.completions == []
    authority.complete_choice(choice, persisted=not fail)
    assert authority.snapshot().persistence_status is (
        PersistenceStatus.ERROR if fail else PersistenceStatus.SAVED)


@pytest.mark.parametrize("timeout", [-1, 0.251, float("inf"), float("nan"), None, True, "0",
                                    pytest.param(10**1000, id="oversized-integer")])
def test_close_rejects_invalid_budget_before_closing(timeout):
    authority = ObservedAuthority()
    writer = api().ProcessingIntentWriter(BlockingStore(), authority)
    try:
        with pytest.raises(ValueError):
            writer.close(timeout=timeout)
        assert not writer._closed
    finally:
        writer.close()


def test_close_zero_budget_retains_pending_callback():
    authority = ObservedAuthority()
    store = BlockingStore()
    notifications = []
    writer = api().ProcessingIntentWriter(
        store, authority, completion_callback=lambda *args: notifications.append(args))
    assert writer.submit(authority.request_cloud_choice())
    assert store.started.wait(2)
    try:
        assert not writer.close(timeout=0)
        assert notifications == []
    finally:
        store.release.set()
        assert writer.close()
    assert len(notifications) == 1

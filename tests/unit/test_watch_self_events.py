"""Pure bounded receipts and real native observation; no analyzer authority."""
import importlib
import threading
from dataclasses import replace

from src.core.rename_plan import NativeFileIdentity, RenamePlan, SourceFingerprint
from src.services.file_operation_backend import FileOperationRequest, FileOperationOutcome


def api():
    return importlib.import_module("src.core.watch_self_events")


def request(tmp_path, operation="op"):
    return FileOperationRequest(operation, "apply", "batch", (RenamePlan("row",
        str(tmp_path / "source.txt"), SourceFingerprint(4, 1), "result.txt",
        str(tmp_path), ".txt", "batch"),))


def test_receipt_pre_worker_collision_family_identity_and_content(tmp_path):
    module = api()
    values = {}
    owner = module.WatchSelfEvents(observe=lambda path: values.get(path))
    req = request(tmp_path)
    token = owner.reserve(req)
    assert token is not None
    source, target = req.plans[0].source_path, str(tmp_path / "result_999.txt")
    assert owner.decision(target) == "hold"
    assert owner.decision(str(tmp_path / "result_1000.txt")) == "allow"
    assert owner.decision(str(tmp_path / "result_01.txt")) == "allow"
    assert owner.decision(str(tmp_path / "unrelated.txt")) == "allow"
    observation = module.FileObservation(NativeFileIdentity(1, 2, 3), SourceFingerprint(4, 1), "a" * 64)
    values[source] = observation
    owner.before_move(token, "row", source, target)
    result = FileOperationOutcome("row", "batch", True, new_path=target,
        source_fingerprint=observation.fingerprint, source_identity=observation.identity)
    owner.after_move(token, "row", source, target, result)
    owner.settle(token, "row", result)
    values[target] = observation
    assert owner.decision(target) == "suppress"
    values[target] = replace(observation, identity=NativeFileIdentity(1, 22, 3))
    assert owner.decision(target) == "allow"
    values[target] = replace(observation, digest="b" * 64)
    assert owner.decision(target) == "allow"
    owner.acknowledge(token)
    owner.begin_close()
    assert owner.workers_idle


def test_receipt_capacity_cancel_late_policy_and_unknown_recovery(tmp_path):
    module = api()
    now = [0.0]
    owner = module.WatchSelfEvents(capacity=1, late_seconds=30, clock=lambda: now[0], observe=lambda _: None)
    req = request(tmp_path)
    token = owner.reserve(req)
    assert owner.reserve(request(tmp_path, "other")) is None
    assert owner.cancel(token)
    token = owner.reserve(req)
    result = FileOperationOutcome("row", "batch", False, recovery_required=True,
        owned_residue_paths=(str(tmp_path / "residue.txt"),))
    owner.settle(token, "row", result)
    now[0] = 31
    assert owner.decision(str(tmp_path / "residue.txt")) == "hold"
    assert owner.reserve(request(tmp_path, "other")) is None
    owner.acknowledge(token)
    owner.begin_close()
    assert owner.workers_idle


def test_pre_content_digest_from_different_native_identity_never_suppresses(tmp_path):
    module = api()
    req = request(tmp_path)
    source, target = req.plans[0].source_path, req.plans[0].target_path
    before = module.FileObservation(NativeFileIdentity(1, 2, 3), SourceFingerprint(4, 1), "a" * 64)
    after = replace(before, identity=NativeFileIdentity(1, 22, 33))
    values = {source: before, target: after}
    owner = module.WatchSelfEvents(observe=lambda path: values.get(path))
    receipt = owner.reserve(req)
    owner.before_move(receipt, "row", source, target)
    result = FileOperationOutcome("row", "batch", True, new_path=target,
        source_fingerprint=after.fingerprint, source_identity=after.identity)
    owner.after_move(receipt, "row", source, target, result)
    owner.settle(receipt, "row", result)
    assert owner.decision(target) == "hold"
    owner.acknowledge(receipt); owner.begin_close()
    assert owner.workers_idle


def test_pre_post_same_volume_file_id_with_tunneled_creation_keeps_actual_post_identity(tmp_path):
    module = api()
    req = request(tmp_path)
    source, target = req.plans[0].source_path, req.plans[0].target_path
    before = module.FileObservation(NativeFileIdentity(1, 2, 3), SourceFingerprint(4, 1), "a" * 64)
    after = replace(before, identity=NativeFileIdentity(1, 2, 99))
    values = {source: before, target: after}
    owner = module.WatchSelfEvents(observe=lambda path: values.get(path))
    receipt = owner.reserve(req)
    owner.before_move(receipt, "row", source, target)
    result = FileOperationOutcome("row", "batch", True, new_path=target,
        source_fingerprint=after.fingerprint, source_identity=after.identity)
    owner.after_move(receipt, "row", source, target, result)
    owner.settle(receipt, "row", result)
    assert owner.decision(target) == "suppress"
    values[target] = before
    assert owner.decision(target) == "allow"  # Future matching remains strict actual POST identity.
    owner.acknowledge(receipt); owner.begin_close()
    assert owner.workers_idle


def test_actual_native_observation_rejects_same_size_mtime_replacement(tmp_path):
    module = api()
    path = tmp_path / "original.txt"
    path.write_bytes(b"aaaa")
    found = []
    thread = threading.Thread(target=lambda: found.append(module.observe_file(str(path))))
    thread.start(); thread.join(3)
    assert not thread.is_alive()
    first = found[0]
    assert first is not None
    old = tmp_path / "retained.txt"
    path.rename(old)
    path.write_bytes(b"bbbb")
    import os
    os.utime(path, ns=(first.fingerprint.mtime_ns, first.fingerprint.mtime_ns))
    thread = threading.Thread(target=lambda: found.append(module.observe_file(str(path))))
    thread.start(); thread.join(3)
    assert not thread.is_alive()
    second = found[1]
    assert second is not None
    assert second.fingerprint == first.fingerprint
    assert second.identity != first.identity and second.digest != first.digest


def read_worker(reader, path, **options):
    found, errors = [], []
    def run():
        try: found.append(reader.read_file(str(path), **options))
        except Exception as error: errors.append(error)
    thread = threading.Thread(target=run)
    thread.start(); thread.join(5)
    assert not thread.is_alive() and not errors
    return found[0]


def test_readonly_owner_same_id_changed_content_budget_cancel_and_deadline(tmp_path):
    import os, time
    reader = api().NativeWatchObservation()
    source = tmp_path / "source.txt"
    source.write_bytes(b"aaaa")
    first = read_worker(reader, source)
    assert first is not None
    source.write_bytes(b"bbbb")
    os.utime(source, ns=(first.fingerprint.mtime_ns, first.fingerprint.mtime_ns))
    second = read_worker(reader, source)
    assert second.identity == first.identity and second.fingerprint == first.fingerprint
    assert second.digest != first.digest
    assert read_worker(reader, source, max_bytes=3) is None
    cancelled = threading.Event(); cancelled.set()
    assert read_worker(reader, source, cancel_event=cancelled) is None
    assert read_worker(reader, source, deadline=time.monotonic() - 1) is None
    reader.begin_close()
    assert reader.workers_idle


def test_readonly_owner_reparse_before_leaf_never_reads_outside(tmp_path, monkeypatch):
    from src.core import safe_file_move as native
    module = api()
    selected = tmp_path / "selected"; selected.mkdir()
    source = selected / "inside.txt"; source.write_bytes(b"synthetic inside")
    outside = tmp_path / "outside.txt"; outside.write_bytes(b"OUTSIDE SENTINEL")
    info, calls = native._info, []
    def reparse(handle):
        value = info(handle)
        calls.append(value)
        if len(calls) == 2:
            return replace(value, attributes=value.attributes | native._REPARSE)
        return value
    monkeypatch.setattr(native, "_info", reparse)
    reader = module.NativeWatchObservation()
    assert read_worker(reader, source) is None
    assert len(calls) == 2  # Rejection during ancestor traversal, never leaf read.
    assert outside.read_bytes() == b"OUTSIDE SENTINEL"
    reader.begin_close(); assert reader.workers_idle


def test_actual_windows_parent_junction_refused_before_outside_sentinel_read(tmp_path, monkeypatch):
    import subprocess
    from src.core import safe_file_move as native
    outside = tmp_path / "outside"; outside.mkdir()
    sentinel = outside / "sentinel.txt"; sentinel.write_bytes(b"OUTSIDE SENTINEL")
    link = tmp_path / "selected"
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "New-Item",
        "-ItemType", "Junction", "-Path", str(link), "-Target", str(outside)], check=True, capture_output=True)
    calls = []
    read = native._kernel.ReadFile
    def trace(*args): calls.append(args[0]); return read(*args)
    monkeypatch.setattr(native._kernel, "ReadFile", trace)
    reader = api().NativeWatchObservation()
    assert read_worker(reader, link / "sentinel.txt") is None
    assert calls == [] and sentinel.read_bytes() == b"OUTSIDE SENTINEL"
    reader.begin_close(); assert reader.workers_idle


def test_readonly_pending_request_retains_independent_owner_not_move_state(tmp_path, monkeypatch):
    from src.core import safe_file_move as native
    module = api()
    source = tmp_path / "source.txt"; source.write_bytes(b"synthetic")
    marker = (native._OWNER.active, native._OWNER.quarantine)
    from types import SimpleNamespace
    class PendingRequest:
        def __init__(self, *args):
            self.state = "allocated"
            self.block = SimpleNamespace(status=-1, information=0)
        def capture(self, owner): return None
    # Inject the whole submitted-resource adapter: no actual native pending
    # request, heap allocation or open handle is abandoned by this negative.
    monkeypatch.setattr(native, "_CreateRequest", PendingRequest)
    monkeypatch.setattr(module._ReadOperation, "root", lambda *args: 42)
    monkeypatch.setattr(native, "_info", lambda _: SimpleNamespace(attributes=native._DIRECTORY))
    monkeypatch.setattr(native, "_nt_create", lambda *args: 0x103)
    monkeypatch.setattr(native, "_wait", lambda *args: 0x102)
    reader = module.NativeWatchObservation()
    assert read_worker(reader, source) is None
    reader.begin_close()
    assert not reader.workers_idle
    assert reader.quarantined_count == 1
    assert (native._OWNER.active, native._OWNER.quarantine) == marker


def test_held_ancestor_cannot_be_replaced_before_relative_leaf_read(tmp_path, monkeypatch):
    from src.core import safe_file_move as native
    selected = tmp_path / "selected"; selected.mkdir()
    source = selected / "inside.txt"; source.write_bytes(b"inside")
    outside = tmp_path / "outside"; outside.mkdir()
    (outside / "inside.txt").write_bytes(b"OUTSIDE SENTINEL")
    attempts, call = [], native._nt_create
    def race(request, *args):
        if request.name == "inside.txt":
            try:
                selected.rename(tmp_path / "retired")
            except OSError:
                attempts.append("held")
            else:
                attempts.append("replaced")
        return call(request, *args)
    monkeypatch.setattr(native, "_nt_create", race)
    reader = api().NativeWatchObservation()
    observed = read_worker(reader, source)
    assert attempts == ["held"]
    import hashlib
    assert observed.digest == hashlib.sha256(b"inside").hexdigest()
    assert (outside / "inside.txt").read_bytes() == b"OUTSIDE SENTINEL"
    reader.begin_close(); assert reader.workers_idle


def test_leaf_reparse_refused_before_read(tmp_path, monkeypatch):
    from src.core import safe_file_move as native
    source = tmp_path / "inside.txt"; source.write_bytes(b"leaf sentinel")
    info = native._info
    def reparse(handle):
        value = info(handle)
        if not value.attributes & native._DIRECTORY:
            return replace(value, attributes=value.attributes | native._REPARSE)
        return value
    monkeypatch.setattr(native, "_info", reparse)
    reads = []
    def forbidden(*args): reads.append(args); raise AssertionError("reparse read")
    monkeypatch.setattr(native._kernel, "ReadFile", forbidden)
    reader = api().NativeWatchObservation()
    assert read_worker(reader, source) is None and not reads
    reader.begin_close(); assert reader.workers_idle

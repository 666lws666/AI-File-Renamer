"""Resource preparation is not model/process/privacy activation."""

import hashlib
import importlib
import io
import os
import threading
from dataclasses import FrozenInstanceError, replace
from urllib.error import URLError

import pytest

from src.services.local_ai.resource_catalog import ResourceCatalog, ResourceSpec
from src.services.local_ai.resource_transport import CHUNK_BYTES, DISK_RESERVE_BYTES, ResourceError


def api():
    name = "src.services.local_ai.resource_manager"
    assert importlib.util.find_spec(name) is not None, "resource manager is not implemented"
    return importlib.import_module(name)


@pytest.fixture
def bodies():
    return {"runtime-cpu": b"runtime", "model-q4": b"model" * 19, "vision-f16": b"vision" * 7}


@pytest.fixture
def tiny_catalog(bodies):
    specs = tuple(ResourceSpec(key, key + (".zip" if key == "runtime-cpu" else ".gguf"),
                               "https://github.com/fixtures/" + key, len(body), hashlib.sha256(body).hexdigest())
                  for key, body in bodies.items())
    return ResourceCatalog("test", "a" * 40, "test", "b" * 40, "b1", "Apache-2.0", "MIT", "test", specs, "c" * 64)


def forbidden(*args, **kwargs):
    pytest.fail("network forbidden")


def plenty(_):
    return 1024 ** 4


class Response(io.BytesIO):
    def __init__(self, body, url, *, status=200, headers=None):
        super().__init__(body)
        self.url, self.status, self.headers = url, status, headers or {}

    def geturl(self):
        return self.url


class Opener:
    def __init__(self, bodies):
        self.bodies, self.calls = bodies, []

    def __call__(self, request, *, timeout):
        self.calls.append(request)
        body = self.bodies[request.full_url.rsplit("/", 1)[1]]
        offset = int(request.get_header("Range", "bytes=0-")[6:-1])
        headers = {"Content-Range": f"bytes {offset}-{len(body)-1}/{len(body)}"} if offset else {}
        return Response(body[offset:], request.full_url, status=206 if offset else 200, headers=headers)


def manager(tmp_path, tiny_catalog, **kwargs):
    return api().ResourceManager(tmp_path / "cache", tiny_catalog, free_bytes=kwargs.pop("free_bytes", plenty), **kwargs)


@pytest.mark.parametrize("consent", [False, None, 1, "yes"])
def test_no_consent_has_zero_side_effects(tmp_path, tiny_catalog, consent):
    instance = manager(tmp_path, tiny_catalog, opener=forbidden)
    with pytest.raises(ResourceError):
        instance.download(consent=consent)
    assert not (tmp_path / "cache").exists()


def test_constructor_snapshot_and_missing_inspect_are_pure(tmp_path, tiny_catalog):
    instance = manager(tmp_path, tiny_catalog, opener=forbidden)
    observation = instance.snapshot()
    assert observation.state is api().ResourceState.MISSING
    with pytest.raises(FrozenInstanceError):
        observation.received_bytes = 1
    assert instance.inspect().state is api().ResourceState.MISSING
    assert not (tmp_path / "cache").exists()


def test_all_three_download_verified_and_fresh_rehash(tmp_path, tiny_catalog, bodies):
    opener = Opener(bodies)
    instance = manager(tmp_path, tiny_catalog, opener=opener)
    seen = []
    result = instance.download(consent=True, progress=lambda *args: seen.append(args))
    assert result.state is api().ResourceState.AVAILABLE
    assert result.verified_ids == tuple(bodies)
    assert result.received_bytes == result.total_bytes == sum(map(len, bodies.values()))
    assert all(len(values) == 3 and values[0] in bodies for values in seen)
    assert [request.full_url for request in opener.calls] == [item.url for item in tiny_catalog.resources]
    for request in opener.calls:
        assert set(key.lower() for key in request.headers) == {"accept-encoding", "user-agent"}
    fresh = manager(tmp_path, tiny_catalog, opener=forbidden)
    assert fresh.snapshot().state is api().ResourceState.MISSING
    assert fresh.inspect().state is api().ResourceState.AVAILABLE
    first = tmp_path / "cache" / tiny_catalog.resources[0].filename
    first.write_bytes(b"corrupt")
    assert fresh.inspect().state is api().ResourceState.ERROR
    assert first.read_bytes() == b"corrupt"


@pytest.mark.parametrize("pause", [False, True])
def test_cancel_pause_preserves_partial_and_range_resumes(tmp_path, tiny_catalog, bodies, pause):
    body = b"x" * (CHUNK_BYTES + 17)
    bodies["runtime-cpu"] = body
    tiny_catalog = replace(tiny_catalog, resources=(replace(tiny_catalog.resources[0], bytes=len(body), sha256=hashlib.sha256(body).hexdigest()), *tiny_catalog.resources[1:]))
    opener = Opener(bodies)
    instance = manager(tmp_path, tiny_catalog, opener=opener)
    observed = []
    result = instance.download(consent=True, cancelled=lambda: bool(observed), paused=lambda: pause and bool(observed), progress=lambda *args: observed.append(args))
    assert result.state is (api().ResourceState.PAUSED if pause else api().ResourceState.CANCELLED)
    assert result.received_bytes == CHUNK_BYTES
    part = tmp_path / "cache" / (tiny_catalog.resources[0].filename + ".part")
    assert part.stat().st_size == CHUNK_BYTES
    fresh = manager(tmp_path, tiny_catalog, opener=opener)
    assert fresh.inspect().state is api().ResourceState.PARTIAL
    assert fresh.download(consent=True).state is api().ResourceState.AVAILABLE
    assert opener.calls[1].get_header("Range") == f"bytes={CHUNK_BYTES}-"


def test_last_resource_failure_never_available_and_retry(tmp_path, tiny_catalog, bodies):
    bad = dict(bodies, **{"vision-f16": b"bad"})
    instance = manager(tmp_path, tiny_catalog, opener=Opener(bad))
    state = instance.download(consent=True)
    assert state.state is api().ResourceState.ERROR
    assert state.verified_ids == ("runtime-cpu", "model-q4")
    assert state.received_bytes < state.total_bytes
    fresh = manager(tmp_path, tiny_catalog, opener=Opener(bodies))
    assert fresh.inspect().state is api().ResourceState.PARTIAL
    fresh.restart_partial("vision-f16")
    assert fresh.download(consent=True).state is api().ResourceState.AVAILABLE


def test_opener_exception_is_sanitized(tmp_path, tiny_catalog):
    def fail(*args, **kwargs):
        raise URLError("https://private.example/?signature=SECRET C:/private/file")
    state = manager(tmp_path, tiny_catalog, opener=fail).download(consent=True)
    assert state.state is api().ResourceState.ERROR
    assert state.error_code == "TRANSFER_FAILED"
    assert "SECRET" not in repr(state) and "private" not in repr(state)


def test_shortage_before_transfer(tmp_path, tiny_catalog):
    state = manager(tmp_path, tiny_catalog, opener=forbidden, free_bytes=lambda _: DISK_RESERVE_BYTES).download(consent=True)
    assert state.state is api().ResourceState.ERROR
    assert state.error_code == "INSUFFICIENT_SPACE"


def test_same_instance_call_is_busy(tmp_path, tiny_catalog, bodies):
    instance = manager(tmp_path, tiny_catalog, opener=Opener(bodies))
    def progress(*args):
        with pytest.raises(ResourceError, match="BUSY"):
            instance.inspect()
        assert instance.snapshot().state is api().ResourceState.DOWNLOADING
    assert instance.download(consent=True, progress=progress).state is api().ResourceState.AVAILABLE


def write_source(tmp_path, catalog, bodies):
    source = tmp_path / "source"
    source.mkdir()
    for item in catalog.resources:
        (source / item.filename).write_bytes(bodies[item.id])
    (source / "manifest.json").write_text('{"url":"https://untrusted.example"}')
    return source


def test_offline_import_ignores_manifest_and_preserves_source(tmp_path, tiny_catalog, bodies):
    source = write_source(tmp_path, tiny_catalog, bodies)
    before = {path.name: path.read_bytes() for path in source.iterdir()}
    state = manager(tmp_path, tiny_catalog, opener=forbidden).import_offline(source)
    assert state.state is api().ResourceState.AVAILABLE
    assert before == {path.name: path.read_bytes() for path in source.iterdir()}
    assert not (tmp_path / "cache" / "manifest.json").exists()


def test_import_bad_hash_preserved_and_explicit_restart(tmp_path, tiny_catalog, bodies):
    source = write_source(tmp_path, tiny_catalog, dict(bodies, **{"runtime-cpu": b"invalid"}))
    instance = manager(tmp_path, tiny_catalog, opener=forbidden)
    assert instance.import_offline(source).state is api().ResourceState.ERROR
    part = tmp_path / "cache" / (tiny_catalog.resources[0].filename + ".part")
    original = part.read_bytes()
    instance.restart_partial("runtime-cpu")
    rejected = list(part.parent.glob(part.name + ".rejected-*"))
    assert len(rejected) == 1 and rejected[0].read_bytes() == original
    assert not part.exists()
    (source / tiny_catalog.resources[0].filename).write_bytes(bodies["runtime-cpu"])
    assert instance.import_offline(source).state is api().ResourceState.AVAILABLE


def test_unknown_restart_has_no_side_effects(tmp_path, tiny_catalog):
    with pytest.raises(ResourceError):
        manager(tmp_path, tiny_catalog).restart_partial("../../unknown")
    assert not (tmp_path / "cache").exists()


def test_hardlinked_final_or_partial_rejected_without_changes(tmp_path, tiny_catalog, bodies):
    instance = manager(tmp_path, tiny_catalog, opener=Opener(bodies))
    instance.download(consent=True, cancelled=lambda: True)
    root = tmp_path / "cache"
    # Cancel can happen before ownership creation: explicitly establish a store.
    store = importlib.import_module("src.services.local_ai.resource_store")
    with store.ResourceStore(root, tiny_catalog.identity).lease(create=True):
        pass
    outside = tmp_path / "outside"
    outside.write_bytes(b"keep")
    os.link(outside, root / (tiny_catalog.resources[0].filename + ".part"))
    with pytest.raises(ResourceError):
        instance.download(consent=True)
    assert outside.read_bytes() == b"keep"


def test_source_hardlink_rejected(tmp_path, tiny_catalog, bodies):
    source = write_source(tmp_path, tiny_catalog, bodies)
    os.link(source / tiny_catalog.resources[0].filename, tmp_path / "linked")
    with pytest.raises(ResourceError):
        manager(tmp_path, tiny_catalog, opener=forbidden).import_offline(source)


def large_catalog(catalog, bodies):
    bodies = dict(bodies)
    body = b"z" * (CHUNK_BYTES * 2 + 11)
    bodies["runtime-cpu"] = body
    return replace(catalog, resources=(replace(catalog.resources[0], bytes=len(body), sha256=hashlib.sha256(body).hexdigest()), *catalog.resources[1:])), bodies


def test_disk_shortage_during_transfer_accounts_for_remaining_bytes(tmp_path, tiny_catalog, bodies):
    catalog, bodies = large_catalog(tiny_catalog, bodies)
    seen = []
    def free(_):
        return DISK_RESERVE_BYTES + CHUNK_BYTES if seen else 1024 ** 4
    state = manager(tmp_path, catalog, opener=Opener(bodies), free_bytes=free).download(consent=True, progress=lambda *args: seen.append(args))
    assert state.state is api().ResourceState.ERROR
    assert state.error_code == "INSUFFICIENT_SPACE"
    assert len(seen) == 1
    assert (tmp_path / "cache" / (catalog.resources[0].filename + ".part")).stat().st_size == CHUNK_BYTES


def test_import_cancel_bounded_and_resume_preserves_sources(tmp_path, tiny_catalog, bodies, monkeypatch):
    catalog, bodies = large_catalog(tiny_catalog, bodies)
    source = write_source(tmp_path, catalog, bodies)
    before = {path.name: path.read_bytes() for path in source.iterdir()}
    instance = manager(tmp_path, catalog, opener=forbidden)
    observed = []
    state = instance.import_offline(source, cancelled=lambda: bool(observed), progress=lambda *args: observed.append(args))
    assert state.state is api().ResourceState.CANCELLED
    assert state.received_bytes == CHUNK_BYTES
    assert instance.import_offline(source).state is api().ResourceState.AVAILABLE
    assert before == {path.name: path.read_bytes() for path in source.iterdir()}


@pytest.mark.parametrize("kind", ["bad_range", "short", "long", "hash"])
def test_transfer_validation_cannot_publish(tmp_path, tiny_catalog, bodies, kind):
    catalog, bodies = large_catalog(tiny_catalog, bodies)
    seen = []
    first = manager(tmp_path, catalog, opener=Opener(bodies))
    first.download(consent=True, cancelled=lambda: bool(seen), progress=lambda *args: seen.append(args))
    spec = catalog.resources[0]
    body = bodies[spec.id][CHUNK_BYTES:]
    def bad(request, **kwargs):
        headers = {"Content-Range": f"bytes {CHUNK_BYTES}-{spec.bytes-1}/{spec.bytes}"}
        if kind == "bad_range":
            headers["Content-Range"] = "bytes 0-1/2"
        payload = body[:-1] if kind == "short" else body + b"!" if kind == "long" else b"w" * len(body) if kind == "hash" else body
        return Response(payload, request.full_url, status=206, headers=headers)
    state = manager(tmp_path, catalog, opener=bad).download(consent=True)
    assert state.state is api().ResourceState.ERROR
    assert not (tmp_path / "cache" / spec.filename).exists()
    assert (tmp_path / "cache" / (spec.filename + ".part")).exists()


def test_corrupt_final_is_never_overwritten_by_download_or_import(tmp_path, tiny_catalog, bodies):
    instance = manager(tmp_path, tiny_catalog, opener=Opener(bodies))
    assert instance.download(consent=True).state is api().ResourceState.AVAILABLE
    path = tmp_path / "cache" / tiny_catalog.resources[1].filename
    path.write_bytes(b"do not replace")
    source = write_source(tmp_path, tiny_catalog, bodies)
    fresh = manager(tmp_path, tiny_catalog, opener=forbidden)
    assert fresh.download(consent=True).state is api().ResourceState.ERROR
    assert fresh.import_offline(source).state is api().ResourceState.ERROR
    assert path.read_bytes() == b"do not replace"


def test_inspection_cancellation_during_hash(tmp_path, tiny_catalog, bodies):
    catalog, bodies = large_catalog(tiny_catalog, bodies)
    instance = manager(tmp_path, catalog, opener=Opener(bodies))
    instance.download(consent=True)
    calls = []
    def cancelled():
        calls.append(True)
        return len(calls) > 8
    assert instance.inspect(cancelled=cancelled).state is api().ResourceState.CANCELLED


def test_restart_missing_store_reports_missing(tmp_path, tiny_catalog):
    instance = manager(tmp_path, tiny_catalog)
    instance.restart_partial("model-q4")
    assert instance.snapshot().state is api().ResourceState.MISSING
    assert not (tmp_path / "cache").exists()


def test_incomplete_catalog_cannot_report_available(tmp_path, tiny_catalog):
    with pytest.raises(ResourceError):
        manager(tmp_path, replace(tiny_catalog, resources=()), opener=forbidden).download(consent=True)
    assert not (tmp_path / "cache").exists()


def test_space_reserve_includes_later_resources_during_write(tmp_path, tiny_catalog, bodies):
    catalog, bodies = large_catalog(tiny_catalog, bodies)
    observed = []
    # Enough for current resource's remainder, not the rest of the catalog.
    def free(_):
        return DISK_RESERVE_BYTES + catalog.resources[0].bytes - CHUNK_BYTES if observed else 1024 ** 4
    state = manager(tmp_path, catalog, opener=Opener(bodies), free_bytes=free).download(consent=True, progress=lambda *args: observed.append(args))
    assert state.state is api().ResourceState.ERROR
    assert len(observed) == 1
    assert (tmp_path / "cache" / (catalog.resources[0].filename + ".part")).stat().st_size == CHUNK_BYTES


def test_hardlink_added_mid_transfer_fails_closed_or_is_os_blocked(tmp_path, tiny_catalog, bodies):
    catalog, bodies = large_catalog(tiny_catalog, bodies)
    attack = []
    outside = tmp_path / "outside"
    part = tmp_path / "cache" / (catalog.resources[0].filename + ".part")
    def progress(*args):
        if attack:
            return
        try:
            os.link(part, outside)
        except OSError:
            attack.append("blocked")
        else:
            attack.append("linked")
    instance = manager(tmp_path, catalog, opener=Opener(bodies))
    try:
        state = instance.download(consent=True, progress=progress)
    except ResourceError:
        assert attack == ["linked"]
        assert outside.stat().st_size == CHUNK_BYTES
    else:
        assert attack == ["blocked"]
        assert state.state is api().ResourceState.AVAILABLE


def test_rejected_partial_names_are_unique_and_preserved(tmp_path, tiny_catalog, bodies):
    instance = manager(tmp_path, tiny_catalog)
    store_type = importlib.import_module("src.services.local_ai.resource_store").ResourceStore
    root = tmp_path / "cache"
    name = tiny_catalog.resources[0].filename + ".part"
    with store_type(root, tiny_catalog.identity).lease(create=True):
        pass
    for value in (b"first bad", b"second bad"):
        (root / name).write_bytes(value)
        instance.restart_partial("runtime-cpu")
    assert sorted(path.read_bytes() for path in root.glob(name + ".rejected-*")) == [b"first bad", b"second bad"]


def test_snapshot_progress_never_decreases_within_attempt(tmp_path, tiny_catalog, bodies):
    catalog, bodies = large_catalog(tiny_catalog, bodies)
    instance = manager(tmp_path, catalog, opener=Opener(bodies))
    values = []
    state = instance.download(consent=True, progress=lambda *args: values.append(instance.snapshot().received_bytes))
    assert state.state is api().ResourceState.AVAILABLE
    assert values == sorted(values)
    assert values[-1] == catalog.total_bytes


def test_bounded_offline_reads(tmp_path, tiny_catalog, bodies, monkeypatch):
    catalog, bodies = large_catalog(tiny_catalog, bodies)
    source = write_source(tmp_path, catalog, bodies)
    instance = manager(tmp_path, catalog, opener=forbidden)
    store_module = importlib.import_module("src.services.local_ai.resource_store")
    original = store_module._PinnedFile.stream
    sizes = []
    class Reader:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def read(self, size=-1):
            assert 0 < size <= CHUNK_BYTES
            sizes.append(size)
            return self.stream.read(size)
    def wrapped(pin, mode="rb"):
        stream = original(pin, mode)
        return Reader(stream) if mode == "rb" else stream
    monkeypatch.setattr(store_module._PinnedFile, "stream", wrapped)
    assert instance.import_offline(source).state is api().ResourceState.AVAILABLE
    assert len(sizes) >= 9


def test_import_write_error_is_a_safe_failure_snapshot(tmp_path, tiny_catalog, bodies, monkeypatch):
    source = write_source(tmp_path, tiny_catalog, bodies)
    instance = manager(tmp_path, tiny_catalog, opener=forbidden)
    store_module = importlib.import_module("src.services.local_ai.resource_store")
    original = store_module.ResourceStore.open_file
    class FailingWrite:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def write(self, chunk):
            raise OSError("SECRET path")
    def output(store, name, mode="rb"):
        stream = original(store, name, mode)
        return FailingWrite(stream) if mode != "rb" else stream
    monkeypatch.setattr(store_module.ResourceStore, "open_file", output)
    state = instance.import_offline(source)
    assert state.state is api().ResourceState.ERROR
    assert state.error_code == "PREPARATION_FAILED"
    assert "SECRET" not in repr(state)


def test_missing_source_has_specific_safe_code(tmp_path, tiny_catalog):
    state = manager(tmp_path, tiny_catalog, opener=forbidden).import_offline(tmp_path / "absent")
    assert state.state is api().ResourceState.ERROR
    assert state.error_code == "SOURCE_MISSING"


def test_concurrent_thread_gets_busy_while_snapshot_remains_readable(tmp_path, tiny_catalog, bodies):
    entered, release = threading.Event(), threading.Event()
    base = Opener(bodies)
    def opener(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return base(*args, **kwargs)
    instance = manager(tmp_path, tiny_catalog, opener=opener)
    results = []
    worker = threading.Thread(target=lambda: results.append(instance.download(consent=True)))
    worker.start()
    try:
        assert entered.wait(5)
        assert instance.snapshot().state is api().ResourceState.DOWNLOADING
        with pytest.raises(ResourceError, match="BUSY"):
            instance.import_offline(tmp_path / "absent")
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert results[0].state is api().ResourceState.AVAILABLE


@pytest.mark.parametrize("failure", ["read_error", "cancel_on_read"])
def test_ignored_range_preserves_owned_partial_before_read_or_truncate(
        tmp_path, tiny_catalog, bodies, monkeypatch, failure):
    store_module = importlib.import_module("src.services.local_ai.resource_store")
    root = tmp_path / "cache"
    item = tiny_catalog.resources[0]
    original_bytes = bodies[item.id][:3]
    part = root / (item.filename + ".part")
    with store_module.ResourceStore(root, tiny_catalog.identity).lease(create=True) as store:
        with store.open_file(part.name, "wb") as stream:
            stream.write(original_bytes)

    reads, modes, requests = [], [], []
    original_open = store_module.ResourceStore.open_file

    def observe_open(store, name, mode="rb"):
        modes.append(mode)
        return original_open(store, name, mode)

    class IgnoredRange(Response):
        def read(self, size=-1):
            reads.append(size)
            if failure == "read_error":
                raise OSError("SECRET remote response")
            return super().read(size)

    def ignored_range(request, **kwargs):
        requests.append(request)
        return IgnoredRange(bodies[item.id], request.full_url, status=200)

    monkeypatch.setattr(store_module.ResourceStore, "open_file", observe_open)
    instance = manager(tmp_path, tiny_catalog, opener=ignored_range)
    state = instance.download(consent=True, cancelled=lambda: failure == "cancel_on_read" and bool(reads))
    assert part.read_bytes() == original_bytes
    assert "wb" not in modes and "ab" not in modes
    assert reads == []
    assert requests[0].get_header("Range") == "bytes=3-"
    assert not (root / item.filename).exists()
    assert state.state is api().ResourceState.ERROR
    assert state.error_code == "TRANSFER_FAILED"

    instance.restart_partial(item.id)
    rejected = list(root.glob(part.name + ".rejected-*"))
    assert len(rejected) == 1 and rejected[0].read_bytes() == original_bytes
    fresh_opener = Opener(bodies)
    result = manager(tmp_path, tiny_catalog, opener=fresh_opener).download(consent=True)
    assert result.state is api().ResourceState.AVAILABLE
    assert fresh_opener.calls[0].get_header("Range") is None


def test_runtime_seed_is_partial_idempotent_and_selection_budget(tmp_path, tiny_catalog, bodies):
    source = write_source(tmp_path, tiny_catalog, bodies)
    item = tiny_catalog.resources[0]
    instance = manager(tmp_path, tiny_catalog, opener=forbidden,
                       free_bytes=lambda _: DISK_RESERVE_BYTES + item.bytes)
    assert hasattr(instance, "import_bundled_runtime"), "runtime seeding missing"
    state = instance.import_bundled_runtime(source / item.filename)
    assert state.state is api().ResourceState.PARTIAL
    assert state.verified_ids == (item.id,)
    final = tmp_path / "cache" / item.filename
    identity = final.stat().st_ino
    assert instance.import_bundled_runtime(source / item.filename).state is api().ResourceState.PARTIAL
    assert final.stat().st_ino == identity
    assert not (final.parent / tiny_catalog.resources[1].filename).exists()
    assert manager(tmp_path, tiny_catalog, opener=forbidden).import_offline(source).state is api().ResourceState.AVAILABLE


@pytest.mark.parametrize("kind", ["missing", "basename", "hash", "size"])
def test_bad_runtime_seed_never_network_or_available(tmp_path, tiny_catalog, bodies, kind):
    source = write_source(tmp_path, tiny_catalog, bodies)
    item = tiny_catalog.resources[0]
    path = source / item.filename
    if kind == "missing":
        path.unlink()
    elif kind == "basename":
        path = source / "wrong.zip"
        path.write_bytes(bodies[item.id])
    else:
        path.write_bytes(b"X" * (item.bytes + (kind == "size")))
    instance = manager(tmp_path, tiny_catalog, opener=forbidden)
    assert hasattr(instance, "import_bundled_runtime"), "runtime seeding missing"
    result = instance.import_bundled_runtime(path)
    assert result.state is api().ResourceState.ERROR
    assert not (tmp_path / "cache" / item.filename).exists()


def test_partial_observation_is_exact_and_not_verified(tmp_path, tiny_catalog):
    from src.services.local_ai.resource_store import ResourceStore
    item = tiny_catalog.resources[0]
    root = tmp_path / "cache"
    with ResourceStore(root, tiny_catalog.identity).lease(create=True) as store:
        with store.open_file(item.filename + ".part", "wb") as stream:
            stream.write(b"abc")
    state = manager(tmp_path, tiny_catalog).inspect()
    assert hasattr(state, "acquired_bytes"), "separate byte observations missing"
    assert state.acquired_bytes == 3
    assert state.verified_bytes == state.received_bytes == 0
    assert state.remaining_bytes == tiny_catalog.total_bytes - 3
    (root / (item.filename + ".part")).write_bytes(b"X" * (item.bytes + 1))
    assert manager(tmp_path, tiny_catalog).inspect().state is api().ResourceState.ERROR


def test_exact_repair_quarantines_corruption_with_fresh_writable_pins(tmp_path, tiny_catalog, bodies):
    source = write_source(tmp_path, tiny_catalog, bodies)
    instance = manager(tmp_path, tiny_catalog, opener=forbidden)
    instance.import_offline(source)
    item = tiny_catalog.resources[0]
    final = tmp_path / "cache" / item.filename
    final.write_bytes(b"broken")
    unrelated = final.parent / "unrelated"
    unrelated.write_bytes(b"keep")
    assert hasattr(instance, "repair_resource"), "exact repair missing"
    before = {p.name: p.read_bytes() for p in final.parent.iterdir()}
    with pytest.raises(ResourceError):
        instance.repair_resource("../unknown")
    assert before == {p.name: p.read_bytes() for p in final.parent.iterdir()}
    state = instance.repair_resource(item.id)
    assert state.state is api().ResourceState.PARTIAL
    assert not final.exists()
    assert [p.read_bytes() for p in final.parent.glob(item.filename + ".rejected-*")] == [b"broken"]
    assert unrelated.read_bytes() == b"keep"
    assert (source / item.filename).read_bytes() == bodies[item.id]


def test_runtime_seed_cancel_resumes_and_counts_acquired(tmp_path, tiny_catalog, bodies):
    catalog, bodies = large_catalog(tiny_catalog, bodies)
    source = write_source(tmp_path, catalog, bodies)
    instance = manager(tmp_path, catalog, opener=forbidden)
    seen = []
    path = source / catalog.resources[0].filename
    state = instance.import_bundled_runtime(path, cancelled=lambda: bool(seen), progress=lambda *args: seen.append(args))
    assert state.state is api().ResourceState.CANCELLED
    assert state.acquired_bytes == state.received_bytes == CHUNK_BYTES
    assert state.verified_bytes == 0
    assert instance.inspect().acquired_bytes == CHUNK_BYTES
    state = instance.import_bundled_runtime(path)
    assert state.state is api().ResourceState.PARTIAL
    assert state.acquired_bytes == state.verified_bytes == catalog.resources[0].bytes


@pytest.mark.parametrize("failure", ["fsync", "publish", "hash"])
def test_runtime_seed_failure_retains_evidence_no_available(tmp_path, tiny_catalog, bodies, monkeypatch, failure):
    from src.services.local_ai.resource_store import ResourceStore
    source = write_source(tmp_path, tiny_catalog, bodies)
    instance = manager(tmp_path, tiny_catalog, opener=forbidden)
    with ResourceStore(tmp_path / "cache", tiny_catalog.identity).lease(create=True):
        pass
    def fail(*args, **kwargs):
        raise OSError("synthetic failure")
    if failure == "fsync":
        monkeypatch.setattr(api().os, "fsync", fail)
    elif failure == "publish":
        monkeypatch.setattr(ResourceStore, "publish", fail)
    else:
        monkeypatch.setattr(instance, "_hash", fail)
    state = instance.import_bundled_runtime(source / tiny_catalog.resources[0].filename)
    assert state.state is api().ResourceState.ERROR
    root = tmp_path / "cache"
    assert any(p.name.startswith(tiny_catalog.resources[0].filename) for p in root.iterdir())
    assert (source / tiny_catalog.resources[0].filename).read_bytes() == bodies["runtime-cpu"]


def test_stale_part_alongside_final_is_rejected(tmp_path, tiny_catalog, bodies):
    source = write_source(tmp_path, tiny_catalog, bodies)
    instance = manager(tmp_path, tiny_catalog, opener=forbidden)
    instance.import_offline(source)
    (tmp_path / "cache" / (tiny_catalog.resources[0].filename + ".part")).write_bytes(b"old")
    assert instance.inspect().state is api().ResourceState.ERROR


def test_runtime_seed_busy_and_source_hardlink_are_no_network(tmp_path, tiny_catalog, bodies):
    from src.services.local_ai.resource_store import ResourceStore, StoreBusy
    source = write_source(tmp_path, tiny_catalog, bodies)
    path = source / tiny_catalog.resources[0].filename
    instance = manager(tmp_path, tiny_catalog, opener=forbidden)
    with ResourceStore(tmp_path / "cache", tiny_catalog.identity).lease(create=True):
        with pytest.raises(StoreBusy):
            instance.import_bundled_runtime(path)
    os.link(path, tmp_path / "hardlink")
    with pytest.raises(ResourceError):
        instance.import_bundled_runtime(path)
    assert path.read_bytes() == bodies["runtime-cpu"]


def test_invalid_seed_cannot_mutate_active_operation_snapshot(tmp_path, tiny_catalog, bodies):
    from src.services.local_ai.resource_store import StoreBusy
    instance = manager(tmp_path, tiny_catalog, opener=Opener(bodies))
    def progress(*args):
        before = instance.snapshot()
        with pytest.raises(StoreBusy):
            instance.import_bundled_runtime(tmp_path / "wrong.zip")
        assert instance.snapshot() == before
    assert instance.download(consent=True, progress=progress).state is api().ResourceState.AVAILABLE


def test_restart_partial_refreshes_cancelled_seed_observation(tmp_path, tiny_catalog, bodies):
    catalog, bodies = large_catalog(tiny_catalog, bodies)
    source = write_source(tmp_path, catalog, bodies)
    instance = manager(tmp_path, catalog, opener=forbidden)
    seen = []
    item = catalog.resources[0]
    result = instance.import_bundled_runtime(source / item.filename,
        cancelled=lambda: bool(seen), progress=lambda *args: seen.append(args))
    assert result.state is api().ResourceState.CANCELLED
    assert result.acquired_bytes == CHUNK_BYTES
    assert instance.restart_partial(item.id) is None
    observed = instance.snapshot()
    assert observed.acquired_bytes == observed.verified_bytes == observed.received_bytes == 0
    assert observed.remaining_bytes == catalog.total_bytes
    assert observed.state is api().ResourceState.MISSING
    assert observed == instance.inspect()
    part = tmp_path / "cache" / (item.filename + ".part")
    assert not part.exists()
    assert [path.read_bytes() for path in part.parent.glob(part.name + ".rejected-*")] == [bodies[item.id][:CHUNK_BYTES]]


def test_restart_partial_rebuilds_surviving_final_and_other_part(tmp_path, tiny_catalog, bodies):
    from src.services.local_ai.resource_store import ResourceStore
    root = tmp_path / "cache"
    final, other, selected = tiny_catalog.resources
    with ResourceStore(root, tiny_catalog.identity).lease(create=True) as store:
        for name, payload in ((final.filename, bodies[final.id]),
                              (other.filename + ".part", bodies[other.id][:3]),
                              (selected.filename + ".part", bodies[selected.id][:2])):
            with store.open_file(name, "wb") as stream:
                stream.write(payload)
    instance = manager(tmp_path, tiny_catalog, opener=forbidden)
    assert instance.inspect().acquired_bytes == final.bytes + 5
    instance.restart_partial(selected.id)
    observed = instance.snapshot()
    assert observed.state is api().ResourceState.PARTIAL
    assert observed.verified_ids == (final.id,)
    assert observed.verified_bytes == observed.received_bytes == final.bytes
    assert observed.acquired_bytes == final.bytes + 3
    assert observed.remaining_bytes == tiny_catalog.total_bytes - final.bytes - 3
    assert observed == instance.inspect()
    assert (root / final.filename).read_bytes() == bodies[final.id]
    assert (root / (other.filename + ".part")).read_bytes() == bodies[other.id][:3]
    assert not (root / (selected.filename + ".part")).exists()


def test_restart_absent_part_preserves_all_verified_finals(tmp_path, tiny_catalog, bodies):
    source = write_source(tmp_path, tiny_catalog, bodies)
    instance = manager(tmp_path, tiny_catalog, opener=forbidden)
    assert instance.import_offline(source).state is api().ResourceState.AVAILABLE
    instance.restart_partial("runtime-cpu")
    observed = instance.snapshot()
    assert observed.state is api().ResourceState.AVAILABLE
    assert observed.verified_ids == tuple(bodies)
    assert observed.verified_bytes == observed.acquired_bytes == tiny_catalog.total_bytes
    assert observed.remaining_bytes == 0
    assert observed == instance.inspect()

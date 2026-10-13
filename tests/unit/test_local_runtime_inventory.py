"""The runtime inventory never executes or trusts extracted members."""

import hashlib
import io
import stat
import struct
import zipfile
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from src.services.local_ai.resource_catalog import ResourceCatalog, ResourceSpec
from src.services.local_ai.resource_store import ResourceStore, StoreBusy
from src.services.local_ai.resource_transport import ResourceCancelled, ResourceError


def api():
    from src.services.local_ai import runtime_inventory
    return runtime_inventory


def archive(members=None, *, compression=zipfile.ZIP_DEFLATED):
    members = members or {"llama-completion.exe": b"completion", "llama-mtmd-cli.exe": b"mtmd",
                          "LICENSE-LLVM-OpenMP": b"license"}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=compression) as output:
        for name, content in members.items() if isinstance(members, dict) else members:
            output.writestr(name, content)
    return stream.getvalue()


def fixture(tmp_path, data=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    data = archive() if data is None else data
    spec = ResourceSpec("runtime-cpu", "runtime.zip", "https://github.com/fixtures/runtime.zip",
                        len(data), hashlib.sha256(data).hexdigest())
    catalog = ResourceCatalog("test", "a" * 40, "test", "b" * 40, "b1",
                              "Apache-2.0", "MIT", "test", (spec,), "c" * 64)
    source = tmp_path / "source"
    with ResourceStore(source, catalog.identity).lease(create=True) as store:
        with store.open_file(spec.filename, "wb") as output:
            output.write(data)
    return source, tmp_path / "runtime", catalog


def run(source, target, catalog, **kwargs):
    return api().prepare_runtime_inventory(source, target, catalog, free_bytes=lambda _: 2**40, **kwargs)


def watch_store_reads(monkeypatch, predicate):
    original = ResourceStore.open_file
    state = {"reads": 0}
    class Watched:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return self.stream.__exit__(*args)
        def __getattr__(self, name):
            return getattr(self.stream, name)
        def read(self, size=-1):
            result = self.stream.read(size)
            if result:
                state["reads"] += 1
            return result
    def open_file(self, name, mode="rb"):
        stream = original(self, name, mode)
        return Watched(stream) if predicate(self, name, mode) else stream
    monkeypatch.setattr(ResourceStore, "open_file", open_file)
    return state


def test_valid_archive_inventory_is_immutable_and_fresh_call_rehashes(tmp_path):
    source, target, catalog = fixture(tmp_path)
    first = run(source, target, catalog)
    assert first.catalog_id == catalog.identity
    assert first.runtime_release == "b1"
    assert first.root == target.absolute()
    assert [member.name for member in first.members] == sorted(member.name for member in first.members)
    assert {member.name for member in first.members} == {"llama-completion.exe", "llama-mtmd-cli.exe", "LICENSE-LLVM-OpenMP"}
    for member in first.members:
        assert member.path.read_bytes() == (b"license" if member.name.startswith("LICENSE") else
                                             b"completion" if member.name == "llama-completion.exe" else b"mtmd")
        assert member.sha256 == hashlib.sha256(member.path.read_bytes()).hexdigest()
        assert member.size == len(member.path.read_bytes())
        assert member.executable == member.name.lower().endswith((".exe", ".dll"))
    with pytest.raises(FrozenInstanceError):
        first.catalog_id = "other"
    assert run(source, target, catalog) == first
    (target / "LICENSE-LLVM-OpenMP").write_bytes(b"tampered")
    with pytest.raises(ResourceError):
        run(source, target, catalog)
    assert (target / "LICENSE-LLVM-OpenMP").read_bytes() == b"tampered"


def test_archive_hash_and_size_fail_before_runtime_creation(tmp_path):
    source, target, catalog = fixture(tmp_path)
    bad = ResourceSpec("runtime-cpu", "runtime.zip", "x", 1, "0" * 64)
    from dataclasses import replace
    for spec in (replace(bad, bytes=catalog.resources[0].bytes), replace(bad, sha256=catalog.resources[0].sha256)):
        with pytest.raises(ResourceError):
            run(source, target, replace(catalog, resources=(spec,)))
        assert not target.exists()


@pytest.mark.parametrize("name", ["../evil", "dir/file", "dir\\file", "/abs", "C:ads", "CON.txt",
                                  "file:stream", "trailing.", "trailing ", "é.txt", ".xuxia-local-resources.json",
                                  "x" * 256])
def test_unsafe_names_fail_before_target_creation(tmp_path, name):
    source, target, catalog = fixture(tmp_path, archive([("llama-completion.exe", b"a"),
                                                         ("llama-mtmd-cli.exe", b"b"), (name, b"x")]))
    with pytest.raises(ResourceError):
        run(source, target, catalog)
    assert not target.exists()


@pytest.mark.parametrize("members", [
    [("llama-completion.exe", b"a"), ("llama-mtmd-cli.exe", b"b"), ("LLAMA-COMPLETION.EXE", b"c")],
    [("llama-completion.exe", b"a")],
    [("llama-completion.exe", b"a"), ("llama-mtmd-cli.exe", b"b")] + [(f"x{i}", b"x") for i in range(67)],
    [("llama-completion.exe", b"a"), ("llama-mtmd-cli.exe", b"b"), ("other.part", b"x"), ("other", b"y")],
])
def test_invalid_directory_fails_before_target_creation(tmp_path, members):
    source, target, catalog = fixture(tmp_path, archive(members))
    with pytest.raises(ResourceError):
        run(source, target, catalog)
    assert not target.exists()


def test_cancel_and_resume_valid_prefix_and_reject_changed_prefix(tmp_path):
    payload = b"x" * (2**20 + 37)
    source, target, catalog = fixture(tmp_path, archive({"llama-completion.exe": payload,
                                                         "llama-mtmd-cli.exe": b"b"}, compression=zipfile.ZIP_STORED))
    def cancel():
        part = target / "llama-completion.exe.part"
        return part.exists() and part.stat().st_size > 0
    with pytest.raises(ResourceCancelled):
        run(source, target, catalog, cancelled=cancel)
    part = target / "llama-completion.exe.part"
    if part.exists():
        original = part.read_bytes()
        assert original
        result = run(source, target, catalog)
        assert len(result.members) == 2
        assert not part.exists()
    else:
        pytest.fail("expected a retained partial")

    source2, target2, catalog2 = fixture(tmp_path / "second", archive({"llama-completion.exe": payload,
                                                                         "llama-mtmd-cli.exe": b"b"}, compression=zipfile.ZIP_STORED))
    with ResourceStore(target2, catalog2.identity + ":runtime:" + catalog2.runtime_release).lease(create=True) as store:
        with store.open_file("llama-completion.exe.part", "wb") as output:
            output.write(b"wrong")
    with pytest.raises(ResourceError):
        run(source2, target2, catalog2)
    assert (target2 / "llama-completion.exe.part").read_bytes() == b"wrong"


def test_unowned_root_and_overlapping_roots_are_rejected(tmp_path):
    source, target, catalog = fixture(tmp_path)
    target.mkdir()
    (target / "foreign").write_bytes(b"keep")
    with pytest.raises(ResourceError):
        run(source, target, catalog)
    assert (target / "foreign").read_bytes() == b"keep"
    with pytest.raises(ResourceError):
        run(source, source / "nested", catalog)
    with pytest.raises(ResourceError):
        run(source, source, catalog)


def test_invalid_timeout_and_busy_source_fail_without_target(tmp_path):
    source, target, catalog = fixture(tmp_path)
    for timeout in (0, -1, True, float("inf"), float("nan")):
        with pytest.raises(ResourceError):
            run(source, target, catalog, timeout_seconds=timeout)
        assert not target.exists()
    with ResourceStore(source, catalog.identity).lease() as store:
        with pytest.raises(StoreBusy):
            run(source, target, catalog)


def test_huge_integer_timeout_is_fixed_input_error(tmp_path):
    source, target, catalog = fixture(tmp_path)
    with pytest.raises(ResourceError) as raised:
        run(source, target, catalog, timeout_seconds=10**1000)
    assert str(raised.value) == "INVALID_RUNTIME_INPUT"
    assert not target.exists()


def test_catalog_without_runtime_is_fixed_error_before_target_creation(tmp_path):
    from dataclasses import replace
    source, target, catalog = fixture(tmp_path)
    with pytest.raises(ResourceError) as raised:
        run(source, target, replace(catalog, resources=()))
    assert str(raised.value) == "INVALID_RUNTIME_INPUT"
    assert not target.exists()


def test_cross_volume_commonpath_failure_does_not_reject_distinct_roots(tmp_path, monkeypatch):
    source, target, catalog = fixture(tmp_path)
    module = api()
    def different_volumes(_):
        raise ValueError("different drives")
    monkeypatch.setattr(module.os.path, "commonpath", different_volumes)
    assert len(run(source, target, catalog).members) == 3


def test_rejects_symlink_encryption_unsupported_compression_and_expanded_limit(tmp_path):
    base = archive()
    def changed(field_offset, value, width=2):
        data = bytearray(base)
        central = data.index(b"PK\x01\x02")
        data[central + field_offset:central + field_offset + width] = value.to_bytes(width, "little")
        return bytes(data)
    bad_archives = [changed(8, 1), changed(10, 12), changed(24, 64 * 1024 * 1024 + 1, 4)]
    link = zipfile.ZipInfo("link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as output:
        output.writestr("llama-completion.exe", b"a")
        output.writestr("llama-mtmd-cli.exe", b"b")
        output.writestr(link, b"target")
    bad_archives.append(stream.getvalue())
    for index, data in enumerate(bad_archives):
        source, target, catalog = fixture(tmp_path / str(index), data)
        with pytest.raises(ResourceError):
            run(source, target, catalog)
        assert not target.exists()


def test_corrupt_crc_fails_before_runtime_creation(tmp_path):
    data = bytearray(archive(compression=zipfile.ZIP_STORED))
    data[data.index(b"completion")] ^= 1
    source, target, catalog = fixture(tmp_path, bytes(data))
    with pytest.raises(ResourceError):
        run(source, target, catalog)
    assert not target.exists()


def test_malformed_deflate_is_fixed_error_before_runtime_creation(tmp_path):
    data = bytearray(archive(compression=zipfile.ZIP_DEFLATED))
    local = data.index(b"PK\x03\x04")
    name_bytes, extra_bytes = struct.unpack_from("<HH", data, local + 26)
    data[local + 30 + name_bytes + extra_bytes] = 0x06  # Reserved DEFLATE block type.
    source, target, catalog = fixture(tmp_path, bytes(data))
    original = (source / "runtime.zip").read_bytes()
    with pytest.raises(ResourceError) as raised:
        run(source, target, catalog)
    assert str(raised.value) == "RUNTIME_PREPARATION_FAILED"
    assert not target.exists()
    assert (source / "runtime.zip").read_bytes() == original


def test_disk_shortage_preflight_and_midcopy_preserve_source(tmp_path):
    body = b"x" * (2**20 + 9)
    source, target, catalog = fixture(tmp_path, archive({"llama-completion.exe": body,
                                                         "llama-mtmd-cli.exe": b"b"}, compression=zipfile.ZIP_STORED))
    source_bytes = (source / "runtime.zip").read_bytes()
    with pytest.raises(ResourceError) as raised:
        api().prepare_runtime_inventory(source, target, catalog, free_bytes=lambda _: 0)
    assert raised.value.code == "INSUFFICIENT_SPACE"
    assert not (target / "llama-completion.exe.part").exists()
    def capacity(_):
        part = target / "llama-completion.exe.part"
        return 0 if part.exists() and part.stat().st_size else 2**40
    with pytest.raises(ResourceError) as raised:
        api().prepare_runtime_inventory(source, target, catalog, free_bytes=capacity)
    assert raised.value.code == "INSUFFICIENT_SPACE"
    assert (target / "llama-completion.exe.part").stat().st_size > 0
    assert (source / "runtime.zip").read_bytes() == source_bytes
    assert len(run(source, target, catalog).members) == 2


def test_cancel_before_acquisition_does_not_create_target(tmp_path):
    source, target, catalog = fixture(tmp_path)
    with pytest.raises(ResourceCancelled):
        run(source, target, catalog, cancelled=lambda: True)
    assert not target.exists()


def test_cancel_during_pinned_archive_hash_leaves_target_absent(tmp_path, monkeypatch):
    source, target, catalog = fixture(tmp_path)
    original = (source / "runtime.zip").read_bytes()
    state = watch_store_reads(monkeypatch, lambda store, name, mode:
                              store.root == source.absolute() and name == "runtime.zip")
    with pytest.raises(ResourceCancelled):
        run(source, target, catalog, cancelled=lambda: state["reads"] > 0)
    assert state["reads"] > 0
    assert not target.exists()
    assert (source / "runtime.zip").read_bytes() == original


def test_deadline_during_pinned_archive_hash_leaves_target_absent(tmp_path, monkeypatch):
    source, target, catalog = fixture(tmp_path)
    state = watch_store_reads(monkeypatch, lambda store, name, mode:
                              store.root == source.absolute() and name == "runtime.zip")
    monkeypatch.setattr(api(), "time", SimpleNamespace(monotonic=lambda: 2.0 if state["reads"] else 0.0))
    with pytest.raises(ResourceError) as raised:
        run(source, target, catalog, timeout_seconds=1.0)
    assert raised.value.code == "RUNTIME_TIMEOUT"
    assert state["reads"] > 0
    assert not target.exists()


def test_deadline_during_extraction_preserves_part_and_resumes(tmp_path, monkeypatch):
    source, target, catalog = fixture(tmp_path, archive({"llama-completion.exe": b"x" * (2**20 + 7),
                                                         "llama-mtmd-cli.exe": b"b"},
                                                        compression=zipfile.ZIP_STORED))
    part = target / "llama-completion.exe.part"
    def clock():
        return 2.0 if part.exists() and part.stat().st_size > 0 else 0.0
    with monkeypatch.context() as scoped:
        scoped.setattr(api(), "time", SimpleNamespace(monotonic=clock))
        with pytest.raises(ResourceError) as raised:
            run(source, target, catalog, timeout_seconds=1.0)
    assert raised.value.code == "RUNTIME_TIMEOUT"
    assert part.stat().st_size > 0
    assert len(run(source, target, catalog).members) == 2


def test_deadline_during_final_recheck_preserves_valid_finals(tmp_path, monkeypatch):
    source, target, catalog = fixture(tmp_path, archive({"llama-completion.exe": b"a",
                                                         "llama-mtmd-cli.exe": b"b"}))
    state = watch_store_reads(monkeypatch, lambda store, name, mode:
                              store.root == target.absolute() and name.endswith(".exe")
                              and (target / "llama-completion.exe").exists()
                              and (target / "llama-mtmd-cli.exe").exists())
    with monkeypatch.context() as scoped:
        scoped.setattr(api(), "time", SimpleNamespace(monotonic=lambda: 2.0 if state["reads"] else 0.0))
        with pytest.raises(ResourceError) as raised:
            run(source, target, catalog, timeout_seconds=1.0)
    assert raised.value.code == "RUNTIME_TIMEOUT"
    assert state["reads"] > 0
    assert (target / "llama-completion.exe").read_bytes() == b"a"
    assert (target / "llama-mtmd-cli.exe").read_bytes() == b"b"
    assert len(run(source, target, catalog).members) == 2


def test_published_member_survives_later_failure_and_reopens(tmp_path):
    members = [("llama-completion.exe", b"ok"), ("llama-mtmd-cli.exe", b"next")]
    source, target, catalog = fixture(tmp_path, archive(members))
    def capacity(_):
        return 0 if (target / "llama-completion.exe").exists() else 2**40
    with pytest.raises(ResourceError):
        api().prepare_runtime_inventory(source, target, catalog, free_bytes=capacity)
    assert (target / "llama-completion.exe").read_bytes() == b"ok"
    assert len(run(source, target, catalog).members) == 2


def test_zip_directory_reads_from_pinned_stream_are_bounded(tmp_path, monkeypatch):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as output:
        for name in ["llama-completion.exe", "llama-mtmd-cli.exe"] + [f"notice-{i}" for i in range(18)]:
            info = zipfile.ZipInfo(name)
            info.comment = b"c" * 65535
            output.writestr(info, b"x")
    source, target, catalog = fixture(tmp_path, stream.getvalue())
    original = ResourceStore.open_file
    class Limited:
        def __init__(self, underlying):
            self.underlying = underlying
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.underlying.close()
        def read(self, size=-1):
            assert 0 <= size <= 2**20
            return self.underlying.read(size)
        def seek(self, *args):
            return self.underlying.seek(*args)
        def tell(self):
            return self.underlying.tell()
    def limited(self, name, mode="rb"):
        result = original(self, name, mode)
        return Limited(result) if self.root == source.absolute() and name == "runtime.zip" else result
    monkeypatch.setattr(ResourceStore, "open_file", limited)
    assert len(run(source, target, catalog).members) == 20

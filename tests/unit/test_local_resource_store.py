"""Owned-store tests use temporary directories only; no security-policy changes."""

import importlib
import ctypes
import json
import os
import struct
import subprocess
import sys

import pytest

from src.services.local_ai.resource_transport import ResourceError


def store_type():
    name = "src.services.local_ai.resource_store"
    assert importlib.util.find_spec(name) is not None, "owned store is not implemented"
    return importlib.import_module(name).ResourceStore


def test_missing_inspection_does_not_create(tmp_path):
    root = tmp_path / "cache"
    with store_type()(root, "a" * 64).lease(create=False) as lease:
        assert lease is None
    assert not root.exists()


def test_empty_root_gets_exact_marker_and_reopens(tmp_path):
    root = tmp_path / "cache"
    with store_type()(root, "a" * 64).lease(create=True):
        pass
    marker = json.loads((root / ".xuxia-local-resources.json").read_text())
    assert set(marker) == {"schema", "catalog_id", "store_id"}
    assert type(marker["schema"]) is int and marker["schema"] == 1
    assert marker["catalog_id"] == "a" * 64
    assert len(marker["store_id"]) == 32
    with store_type()(root, "a" * 64).lease(create=False):
        pass


@pytest.mark.parametrize("kind", ["unmarked", "invalid", "foreign", "bool_schema", "extra", "file"])
def test_unowned_roots_are_untouched(tmp_path, kind):
    root = tmp_path / "cache"
    if kind == "file":
        root.write_bytes(b"private")
    else:
        root.mkdir()
        if kind == "unmarked":
            (root / "private.txt").write_bytes(b"private")
        else:
            marker = {"schema": 1, "catalog_id": "a" * 64, "store_id": "b" * 32}
            if kind == "foreign":
                marker["catalog_id"] = "c" * 64
            if kind == "bool_schema":
                marker["schema"] = True
            if kind == "extra":
                marker["other"] = "unexpected"
            (root / ".xuxia-local-resources.json").write_text("bad" if kind == "invalid" else json.dumps(marker))
    before = {p.name: p.read_bytes() for p in root.iterdir()} if root.is_dir() else root.read_bytes()
    with pytest.raises(ResourceError):
        with store_type()(root, "a" * 64).lease(create=True):
            pytest.fail("unowned root accepted")
    after = {p.name: p.read_bytes() for p in root.iterdir()} if root.is_dir() else root.read_bytes()
    assert before == after


def test_same_process_and_cross_process_lease_release(tmp_path):
    root = tmp_path / "cache"
    cls = store_type()
    code = """import sys
from pathlib import Path
from src.services.local_ai.resource_store import ResourceStore, StoreBusy
try:
    with ResourceStore(Path(sys.argv[1]), 'a'*64).lease(create=False):
        print('ACQUIRED', flush=True)
except StoreBusy:
    print('BUSY', flush=True)
"""
    with cls(root, "a" * 64).lease(create=True):
        with pytest.raises(ResourceError, match="BUSY"):
            with cls(root, "a" * 64).lease(create=False):
                pass
        result = subprocess.run([sys.executable, "-c", code, str(root)], capture_output=True, text=True, check=True)
        assert result.stdout.strip() == "BUSY"
    result = subprocess.run([sys.executable, "-c", code, str(root)], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "ACQUIRED"


def test_process_exit_releases_lease(tmp_path):
    root = tmp_path / "cache"
    cls = store_type()
    code = """import os, sys
from pathlib import Path
from src.services.local_ai.resource_store import ResourceStore
with ResourceStore(Path(sys.argv[1]), 'a'*64).lease(create=True):
    os._exit(0)
"""
    subprocess.run([sys.executable, "-c", code, str(root)], check=True)
    with cls(root, "a" * 64).lease(create=False):
        pass


@pytest.mark.skipif(os.name != "nt", reason="Windows native pinning")
def test_parent_directory_cannot_be_renamed_during_lease(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    with store_type()(parent / "cache", "a" * 64).lease(create=True):
        with pytest.raises(OSError):
            parent.rename(tmp_path / "renamed")
    parent.rename(tmp_path / "renamed")


def test_hardlinked_file_is_rejected(tmp_path):
    root = tmp_path / "cache"
    cls = store_type()
    with cls(root, "a" * 64).lease(create=True):
        pass
    outside = tmp_path / "original"
    outside.write_bytes(b"keep")
    os.link(outside, root / "item.part")
    with cls(root, "a" * 64).lease(create=False) as store:
        with pytest.raises(ResourceError):
            store.open_file("item.part", "ab")
    assert outside.read_bytes() == b"keep"


@pytest.mark.skipif(os.name != "nt", reason="Windows junction")
def test_junction_ancestor_is_rejected(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    link = tmp_path / "junction"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(original)], capture_output=True, check=True)
    try:
        with pytest.raises(ResourceError):
            with store_type()(link / "cache", "a" * 64).lease(create=True):
                pass
        assert list(original.iterdir()) == []
    finally:
        link.rmdir()


def test_publication_never_overwrites_existing_final(tmp_path):
    with store_type()(tmp_path / "cache", "a" * 64).lease(create=True) as store:
        with store.open_file("item.part", "wb") as stream:
            stream.write(b"new")
        (store.root / "item").write_bytes(b"existing")
        with pytest.raises(ResourceError):
            store.publish("item.part", "item")
    assert (tmp_path / "cache" / "item").read_bytes() == b"existing"
    assert (tmp_path / "cache" / "item.part").read_bytes() == b"new"


def test_file_appearing_after_absence_check_is_never_adopted(tmp_path):
    with store_type()(tmp_path / "cache", "a" * 64).lease(create=True) as store:
        assert not store.exists("item.part")
        (store.root / "item.part").write_bytes(b"intruder")
        with pytest.raises(ResourceError):
            with store.open_file("item.part", "wb") as stream:
                stream.write(b"replacement")
    assert (tmp_path / "cache" / "item.part").read_bytes() == b"intruder"


def test_body_missing_file_error_does_not_reenter_context(tmp_path):
    with pytest.raises(ResourceError, match="STORE_IO_FAILED"):
        with store_type()(tmp_path / "cache", "a" * 64).lease(create=True):
            raise FileNotFoundError("private path")


def test_symlink_file_is_rejected_if_supported(tmp_path):
    target = tmp_path / "target"
    target.write_bytes(b"untouched")
    root = tmp_path / "cache"
    with store_type()(root, "a" * 64).lease(create=True):
        pass
    try:
        (root / "item.part").symlink_to(target)
    except OSError:
        pytest.skip("symlink privilege is unavailable; no policy changes requested")
    with store_type()(root, "a" * 64).lease(create=False) as store:
        with pytest.raises(ResourceError):
            store.open_file("item.part", "wb")
    assert target.read_bytes() == b"untouched"


def test_publication_supports_unicode_root(tmp_path):
    root = tmp_path / "resources-\U0001f512\U0001f512"
    with store_type()(root, "a" * 64).lease(create=True) as store:
        with store.open_file("item.part", "wb") as stream:
            stream.write(b"verified")
        store.publish("item.part", "item")
    assert (root / "item").read_bytes() == b"verified"


@pytest.mark.parametrize("count", [8, 9])
def test_parent_creation_bound_is_union_and_preflight(tmp_path, count):
    module = importlib.import_module("src.services.local_ai.resource_store")
    assert hasattr(module, "_prepare_directory_parents"), "relative parent capability missing"
    parents = tuple(tmp_path / str(index) for index in range(count))
    if count == 9:
        with pytest.raises(ResourceError):
            with module._prepare_directory_parents(trusted_anchor=tmp_path, parents=parents):
                pass
        assert list(tmp_path.iterdir()) == []
    else:
        with module._prepare_directory_parents(trusted_anchor=tmp_path, parents=parents) as owner:
            owner.assert_safe()
            assert all(path.is_dir() for path in parents)
        assert len(list(tmp_path.iterdir())) == 8


def test_readonly_store_observation_excludes_writer(tmp_path):
    cls = store_type()
    root = tmp_path / "cache"
    with cls(root, "a" * 64).lease(create=True):
        pass
    store = cls(root, "a" * 64)
    assert hasattr(store, "observe"), "readonly marker observation missing"
    before = (root / ".xuxia-local-resources.json").stat().st_mtime_ns
    with store.observe() as observed:
        assert observed is not None
        with pytest.raises(ResourceError, match="BUSY"):
            with cls(root, "a" * 64).lease():
                pass
    assert (root / ".xuxia-local-resources.json").stat().st_mtime_ns == before


def _try_reparse(directory, target):
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.DeviceIoControl.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    sub = ("\\??\\" + str(target)).encode("utf-16-le")
    display = str(target).encode("utf-16-le")
    body = struct.pack("<HHHH", 0, len(sub), len(sub) + 2, len(display)) + sub + b"\0\0" + display + b"\0\0"
    data = struct.pack("<IHH", 0xA0000003, len(body), 0) + body
    handle = kernel.CreateFileW(str(directory), 0x100, 7, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        return False, ctypes.get_last_error()
    try:
        returned = wintypes.DWORD()
        buffer = ctypes.create_string_buffer(data)
        success = kernel.DeviceIoControl(handle, 0x900A4, buffer, len(data), None, 0, ctypes.byref(returned), None)
        return bool(success), ctypes.get_last_error() if not success else 0
    finally:
        assert kernel.CloseHandle(handle)


def test_empty_directory_pin_excludes_rename(tmp_path):
    module = importlib.import_module("src.services.local_ai.resource_store")
    target = tmp_path / "empty"
    target.mkdir()
    with module.pinned_directory(target):
        with pytest.raises(OSError):
            target.rename(tmp_path / "moved")


def test_empty_parent_guard_blocks_actual_reparse(tmp_path, capsys):
    module = importlib.import_module("src.services.local_ai.resource_store")
    assert hasattr(module, "_prepare_directory_parents"), "relative parent capability missing"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_bytes(b"outside")
    parent = tmp_path / "new"
    with module._prepare_directory_parents(trusted_anchor=tmp_path, parents=(parent,)) as owner:
        result = _try_reparse(parent, outside)
        with capsys.disabled():
            print("RESOURCE_PARENT_REPARSE_ACTUAL=" + repr(result))
        assert not result[0]
        owner.assert_safe()
    assert (outside / "keep").read_bytes() == b"outside"
    assert {path.name for path in outside.iterdir()} == {"keep"}


@pytest.mark.parametrize("failure", ["pending", "free", "close", "guard_pending"])
def test_uncertainty_exposes_retained_owner_without_false_idle(tmp_path, failure):
    # Isolate deliberately unrecoverable native ownership until OS process exit.
    code = r'''
import sys
from pathlib import Path
from src.services.local_ai import resource_store as module
assert hasattr(module, "StoreOwnershipUncertain"), "opaque retained-owner contract missing"
base = Path(sys.argv[1])
failure = sys.argv[2]
real_create = module._native._nt_create
real_free = module._native._heap_free
real_close = module._native._close
def create(request, *args):
    if failure == "pending":
        return 0x103
    return real_create(request, *args)
def free(pointer):
    if failure == "free":
        raise OSError("injected ambiguous free")
    return real_free(pointer)
def close(handle):
    if failure == "close":
        raise OSError("injected ambiguous close")
    return real_close(handle)
module._native._nt_create = create
module._native._heap_free = free
module._native._close = close
held = None
try:
    with module._prepare_directory_parents(trusted_anchor=base, parents=(base / "new",)) as owner:
        assert owner.retained and not owner.idle
        if failure == "guard_pending":
            guard = owner.guards[base / "new"][0]
            held = module._PinnedFile(base / "new" / guard, directory=False)
except module.StoreOwnershipUncertain as error:
    owner = error.retained_owner
    assert owner.retained and not owner.idle and owner.uncertain
    assert owner.close() is False
    assert str(error) == "NATIVE_OWNERSHIP_UNCERTAIN"
    assert str(base) not in repr(error)
    try:
        error.retained_owner = None
    except AttributeError:
        pass
    else:
        raise AssertionError("owner reference is mutable")
    print("RETAINED_NOT_IDLE=" + failure, flush=True)
else:
    raise AssertionError("uncertain native lifecycle reported success")
'''
    # The guard-pending scenario requires an attribute-only handle, because an
    # ordinary readable file pin correctly refuses sharing with the guard.
    if failure == "guard_pending":
        code = code.replace('held = module._PinnedFile(base / "new" / guard, directory=False)',
            'held = module._kernel.CreateFileW(str(base / "new" / guard), 0x80, 7, None, 3, 0x00200000, None)\n            assert held != module.ctypes.c_void_p(-1).value')
    result = subprocess.run([sys.executable, "-B", "-c", code, str(tmp_path), failure], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RETAINED_NOT_IDLE=" + failure in result.stdout


def test_cancelled_and_invalid_parent_preflight_never_mutate(tmp_path):
    module = importlib.import_module("src.services.local_ai.resource_store")
    from src.services.local_ai.resource_transport import ResourceCancelled
    with pytest.raises(ResourceCancelled):
        with module._prepare_directory_parents(trusted_anchor=tmp_path, parents=(tmp_path / "new",), cancelled=lambda: True):
            pass
    for anchor, parent in ((tmp_path / "missing", tmp_path / "missing/new"),
                           ("relative", tmp_path / "new"),
                           ("\\\\server\\share", tmp_path / "new"),
                           (tmp_path, tmp_path.parent / "outside")):
        with pytest.raises(ResourceError):
            with module._prepare_directory_parents(trusted_anchor=anchor, parents=(parent,)):
                pass
    assert list(tmp_path.iterdir()) == []


def test_source_after_directory_check_substitution_cannot_read_outside(tmp_path, monkeypatch):
    module = importlib.import_module("src.services.local_ai.resource_store")
    source, outside = tmp_path / "source", tmp_path / "outside"
    source.mkdir()
    outside.mkdir()
    (outside / "runtime.zip").write_bytes(b"outside must not be read")
    original = module.PreparedParentDirectories.assert_safe
    attacked = []
    def checked(owner):
        original(owner)
        if source in owner.directories and not attacked:
            attacked.append(_try_reparse(source, outside))
    monkeypatch.setattr(module.PreparedParentDirectories, "assert_safe", checked)
    with pytest.raises(ResourceError):
        with module.source_files(source, ["runtime.zip"]) as files:
            pytest.fail("outside source handle was exposed")
    assert attacked and attacked[0][0], "fixture must actually convert unguarded empty directory"
    assert (outside / "runtime.zip").read_bytes() == b"outside must not be read"
    source.rmdir()  # Exact fixture junction only, never recurse into its target.


def test_first_empty_created_parent_substitution_never_mutates_outside(tmp_path, monkeypatch, capsys):
    module = importlib.import_module("src.services.local_ai.resource_store")
    parent = tmp_path / "new"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_bytes(b"untouched")
    original = module.PreparedParentDirectories.guard
    observed = []
    def attack(owner, path):
        if path == parent and not observed:
            observed.append(_try_reparse(parent, outside))
        return original(owner, path)
    monkeypatch.setattr(module.PreparedParentDirectories, "guard", attack)
    with pytest.raises(ResourceError):
        with module._prepare_directory_parents(trusted_anchor=tmp_path, parents=(parent / "child",)):
            pytest.fail("substituted first-empty parent accepted")
    assert observed == [(True, 0)], "the post-create race must occur physically"
    with capsys.disabled():
        print("RESOURCE_FIRST_EMPTY_SUBSTITUTED_OUTSIDE_UNCHANGED=" + repr(observed))
    assert {path.name: path.read_bytes() for path in outside.iterdir()} == {"keep": b"untouched"}
    parent.rmdir()
    assert not list(tmp_path.glob(".xuxia-resource-init-*"))


def test_existing_junction_parent_is_rejected_without_creation(tmp_path):
    module = importlib.import_module("src.services.local_ai.resource_store")
    original = tmp_path / "outside"
    original.mkdir()
    link = tmp_path / "link"
    link.mkdir()
    assert _try_reparse(link, original)[0]
    try:
        with pytest.raises(ResourceError):
            with module._prepare_directory_parents(trusted_anchor=tmp_path, parents=(link / "new",)):
                pass
        assert list(original.iterdir()) == []
    finally:
        link.rmdir()


def test_native_create_failure_unwinds_held_parent_handles(tmp_path, monkeypatch):
    module = importlib.import_module("src.services.local_ai.resource_store")
    anchor = tmp_path / "anchor"
    anchor.mkdir()
    original = module._native._nt_create
    def denied(request, access, share, disposition, options):
        if request.name == "new" and disposition == 2:
            return ctypes.c_int32(0xC0000022).value
        return original(request, access, share, disposition, options)
    monkeypatch.setattr(module._native, "_nt_create", denied)
    with pytest.raises(ResourceError):
        with module._prepare_directory_parents(trusted_anchor=anchor, parents=(anchor / "new",)):
            pass
    assert list(anchor.iterdir()) == []
    anchor.rename(tmp_path / "released")


def test_unavailable_native_capability_fails_before_mutation(tmp_path, monkeypatch):
    module = importlib.import_module("src.services.local_ai.resource_store")
    monkeypatch.setattr(module._native, "_NATIVE_AVAILABLE", False)
    with pytest.raises(ResourceError, match="UNSUPPORTED_STORE_PLATFORM"):
        with module._prepare_directory_parents(trusted_anchor=tmp_path, parents=(tmp_path / "new",)):
            pass
    assert list(tmp_path.iterdir()) == []

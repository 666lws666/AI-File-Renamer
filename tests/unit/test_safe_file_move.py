"""Actual Windows held-object movement, plus controlled native boundary faults.

No simulated EXDEV, critical skips, real user files, or path-based product cleanup.
"""
from dataclasses import FrozenInstanceError
import ctypes
import gc
import json
import os
from pathlib import Path
import subprocess
import struct
import tempfile
import time
import sys

import pytest

from src.core import safe_file_move as move
from src.core.rename_plan import SourceFingerprint


def _publish_ready_json(ready_text, graph):
    """Publish only a fully written/closed owned sibling as the readiness signal."""
    ready = Path(ready_text)
    publishing = ready.with_name(ready.name + '.publishing')
    publishing.write_text(json.dumps(graph), encoding='utf-8')
    publishing.replace(ready)


def test_ready_json_is_invisible_until_complete_closed_publication(tmp_path, monkeypatch):
    ready = tmp_path / 'ready.json'
    publishing = ready.with_name(ready.name + '.publishing')
    graph, observations = {'case': 'owned-ready', 'paths': ['synthetic']}, []
    write = Path.write_text
    def observed(path, *args, **kwargs):
        answer = write(path, *args, **kwargs)  # Real complete write and close.
        observations.append((path, ready.exists()))
        return answer
    monkeypatch.setattr(Path, 'write_text', observed)
    _publish_ready_json(ready, graph)
    assert observations == [(publishing, False)]
    assert json.loads(ready.read_text(encoding='utf-8')) == graph and not publishing.exists()


@pytest.mark.parametrize('prior', [False, True])
def test_ready_json_partial_write_preserves_final_and_owned_partial(tmp_path, monkeypatch, prior):
    ready = tmp_path / 'ready.json'
    publishing = ready.with_name(ready.name + '.publishing')
    original = b'{"prior":true}'
    if prior: ready.write_bytes(original)
    def partial(path, *args, **kwargs):
        with path.open('w', encoding='utf-8') as stream: stream.write('{"partial":')
        raise OSError('controlled partial readiness write')
    monkeypatch.setattr(Path, 'write_text', partial)
    with pytest.raises(OSError, match='controlled partial readiness write'):
        _publish_ready_json(ready, {'new': True})
    assert ready.read_bytes() == original if prior else not ready.exists()
    assert publishing.read_bytes() == b'{"partial":'  # Retain the owned failure evidence.


@pytest.mark.parametrize('prior', [False, True])
def test_ready_json_replace_failure_preserves_final_and_complete_sibling(tmp_path, monkeypatch, prior):
    ready = tmp_path / 'ready.json'
    publishing = ready.with_name(ready.name + '.publishing')
    original, graph, attempts = b'{"prior":true}', {'new': True}, []
    if prior: ready.write_bytes(original)
    def refused(path, target):
        attempts.append((path, target, json.loads(path.read_text(encoding='utf-8'))))
        raise OSError('controlled readiness replace failure')
    monkeypatch.setattr(Path, 'replace', refused)
    with pytest.raises(OSError, match='controlled readiness replace failure'):
        _publish_ready_json(ready, graph)
    assert attempts == [(publishing, ready, graph)]
    assert ready.read_bytes() == original if prior else not ready.exists()
    assert json.loads(publishing.read_text(encoding='utf-8')) == graph


def fingerprint(path):
    info = path.stat()
    return SourceFingerprint(info.st_size, info.st_mtime_ns)


def invoke(src, dst, roots=None, approved=None, **kwargs):
    return move.safe_move(str(src), str(dst), expected_fingerprint=approved or fingerprint(src),
                          allowed_roots=roots or (str(src.parent), str(dst.parent))
                          if src.parent != dst.parent else roots or (str(src.parent),), **kwargs)


def ordinary(result, code):
    assert not result.success and not result.recovery_required
    assert result.error_code == code and result.new_path == ""
    assert result.owned_residue_paths == ()


def recovery(result):
    assert not result.success and result.recovery_required
    assert result.error_code == "SAFE_MOVE_RECOVERY_REQUIRED"
    assert result.new_path == ""
    assert len(result.owned_residue_paths) <= 4


def success(result, dst, approved):
    assert result.success and not result.recovery_required
    assert result.new_path == str(dst) and result.error_code == ""
    assert result.source_fingerprint == approved and result.owned_residue_paths == ()
    assert fingerprint(dst) == approved


@pytest.fixture
def pair(tmp_path):
    src, dst = tmp_path / "source.txt", tmp_path / "提案-🌱.txt"
    src.write_bytes(b"SYNTHETIC_APPROVED")
    return src, dst


@pytest.fixture
def second_volume(tmp_path):
    qa = Path(__file__).resolve().parents[1] / "screenshots" / "qa-current" / "local-privacy"
    qa = qa.resolve(strict=True)
    temporary = tempfile.TemporaryDirectory(prefix="native-safe-file-move-", dir=qa)
    target = Path(temporary.name).resolve(strict=True)
    assert target.parent == qa and target.name.startswith("native-safe-file-move-")
    assert tmp_path.stat().st_dev != target.stat().st_dev, "Actual second volume required"
    try:
        yield target
    finally:
        # Validate the exact resolved synthetic target again before recursive cleanup.
        assert Path(temporary.name).resolve(strict=True) == target and target.parent == qa
        temporary.cleanup()
        assert not target.exists(), "Native handles must permit actual fixture cleanup"


def test_same_volume_exact_move(pair, monkeypatch):
    src, dst = pair
    approved, identity = fingerprint(src), src.stat().st_ino
    native_errors = []
    original = move._rename
    def observed_rename(*args):
        try:
            return original(*args)
        except OSError as error:
            native_errors.append(getattr(error, "winerror", error.errno))
            raise
    monkeypatch.setattr(move, "_rename", observed_rename)
    result = invoke(src, dst)
    assert native_errors == [], native_errors
    success(result, dst, approved)
    assert not src.exists() and dst.read_bytes() == b"SYNTHETIC_APPROVED"
    assert dst.stat().st_ino == identity
    with pytest.raises(FrozenInstanceError):
        result.success = False


def test_native_win32_vs_nt_same_held_objects_diagnostic(pair):
    """Single-variable compatibility comparison, not a mocked publication PASS."""
    src, dst = pair
    approved = fingerprint(src)
    parent = move._open(str(src.parent), directory=True)
    handle = move._open(str(src))
    class StatusUnion(ctypes.Union):
        _fields_ = [("status", ctypes.c_int32), ("pointer", ctypes.c_void_p)]
    class StatusBlock(ctypes.Structure):
        _anonymous_ = ("value",)
        _fields_ = [("value", StatusUnion), ("information", ctypes.c_size_t)]
    encoded = dst.name.encode("utf-16-le")
    buffer = ctypes.create_string_buffer(ctypes.sizeof(move._RenameHeader) + len(encoded))
    header = move._RenameHeader.from_buffer(buffer)
    header.flags = 0; header.root = parent; header.length = len(encoded)
    ctypes.memmove(ctypes.addressof(buffer) + move._RenameHeader.name.offset, encoded, len(encoded))
    block = StatusBlock(); block.status = ctypes.c_int32(0xC0000000).value
    native = ctypes.WinDLL("ntdll")
    native.NtSetInformationFile.argtypes = [ctypes.c_void_p, ctypes.POINTER(StatusBlock),
                                           ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int]
    native.NtSetInformationFile.restype = ctypes.c_int32
    observations = []
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetFileInformationByHandle.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                 ctypes.c_void_p, ctypes.c_ulong]
    kernel.SetFileInformationByHandle.restype = ctypes.c_int
    try:
        accepted = kernel.SetFileInformationByHandle(handle, 3, buffer, len(buffer))
        observations.append(("Win32", bool(accepted), ctypes.get_last_error() if not accepted else 0))
        assert not accepted and observations[-1][2] == 87, observations
        status = native.NtSetInformationFile(handle, ctypes.byref(block), buffer, len(buffer), 10)
        observations.append(("Nt", status, block.status, block.information))
        assert status == 0 and block.status == 0, observations
        assert move._info(handle).fingerprint == approved
    finally:
        move._close(handle); move._close(parent)
    assert not src.exists() and dst.read_bytes() == b"SYNTHETIC_APPROVED", observations


def _r1_child(case, src_text, dst_text, ready_text, exit_text):
    """Controlled boundary faults; kernel locks and process release are real."""
    import atexit
    import socket
    import threading
    forbidden = []
    def deny(*args, **kwargs):
        forbidden.append(True)
        raise AssertionError("Forbidden external access")
    for name in ("connect", "connect_ex", "sendto"):
        setattr(socket.socket, name, deny)
    for name in ("getaddrinfo", "create_connection"):
        setattr(socket, name, deny)
    import keyring, keyring.core
    from keyring.backends import Windows
    from keyring.backends.fail import Keyring
    keyring.set_keyring(Keyring())
    for owner in (keyring, keyring.core, Windows.WinVaultKeyring):
        for name in ("get_password", "set_password", "delete_password", "get_credential",
                     "_read_credential", "_resolve_credential", "_set_password", "_delete_password"):
            if hasattr(owner, name):
                setattr(owner, name, deny)
    for name in ("CredRead", "CredWrite", "CredDelete", "CredEnumerate"):
        if hasattr(Windows.win32cred, name):
            setattr(Windows.win32cred, name, deny)
    def exit_evidence():
        print("R1_CHILD_FORBIDDEN=" + str(len(forbidden)), flush=True)
        print("R1_CHILD_ATEXIT=" + repr([(t.name, t.is_alive()) for t in threading.enumerate()]), flush=True)
    atexit.register(exit_evidence)
    src, dst = Path(src_text), Path(dst_text)
    events, waits, submitted, frees, admission_witness = [], [], [], [], []
    real_nt, real_close = move._nt_set, move._close
    real_free = getattr(move, "_heap_free", None)
    def nt(handle, block, buffer):
        submitted.append((ctypes.addressof(block), ctypes.addressof(buffer), len(buffer)))
        if hasattr(move, "_OWNER"):
            assert move._OWNER.active.requests[-1].block is block
            assert ctypes.addressof(buffer) % ctypes.alignment(move._RenameHeader) == 0
            admission_witness.append(True)
        gc.collect()  # No GC suppression; the native backing allocation must survive.
        if case == "submission-after-effect":
            real_nt(handle, block, buffer)
            raise OSError(5, "controlled exception after submission")
        if case == "submission-keyboardinterrupt":
            raise KeyboardInterrupt()
        if case == "submission-systemexit-after-effect":
            real_nt(handle, block, buffer)
            raise SystemExit(12)
        if case.startswith("pending-"):
            if case == "pending-terminal-success":
                block.status = 0
            elif case == "pending-terminal-collision":
                block.status = ctypes.c_int32(0xC0000035).value
            elif case == "pending-iosb-pending":
                block.status = 0x103
            elif case == "pending-iosb-unknown":
                block.status = 1
            return 0x103
        if case == "informational":
            return 1
        if case == "success-iosb-mismatch":
            return 0
        return real_nt(handle, block, buffer)
    if not case.startswith("close-"):
        move._nt_set = nt
    def wait(handle, milliseconds):
        waits.append(milliseconds)
        return {"pending-timeout": 0x102, "pending-failed": 0xffffffff,
                "pending-abandoned": 0x80}.get(case, 0)
    # Patch the private boundary when present; baseline's actual wrapper otherwise.
    if hasattr(move, "_wait"):
        move._wait = wait
    else:
        move._kernel.WaitForSingleObject = wait
    def close(handle):
        events.append("close")
        if case.startswith("close-"):
            if case == "close-after-effect":
                real_close(handle)
            raise OSError(6, "controlled close ambiguity")
        return real_close(handle)
    move._close = close
    if real_free is not None:
        def free(pointer):
            request = move._OWNER.active.requests[-1]
            if request.kind != "rename":
                return real_free(pointer)
            frees.append(pointer)
            if case.startswith("free-"):
                events.append("free")
                if case == "free-after-effect":
                    real_free(pointer)
                raise OSError(5, "controlled free ambiguity")
            return real_free(pointer)
        move._heap_free = free
    result = invoke(src, dst)
    recovery(result)
    if case.startswith("pending-"):
        assert waits == [250], waits
    if case.startswith("close-"):
        assert events == ["close"], events
        assert len(frees) == 1
    elif case.startswith("free-"):
        assert events == ["free"], events
        assert len(frees) == 1
    else:
        assert events == [] and frees == [], (events, frees)
    owner = move._OWNER
    transaction = owner.quarantine
    assert transaction is not None and owner.active is None
    assert transaction.source_fingerprint == result.source_fingerprint
    assert transaction.owned_residue_paths == result.owned_residue_paths
    assert transaction.source == str(src) and transaction.destination == str(dst)
    assert transaction.handles and any(record.state != "closed" for record in transaction.handles)
    rename_requests = [request for request in transaction.requests if request.kind == "rename"]
    assert len(rename_requests) == 1
    assert all(request.state == "freed" for request in transaction.requests if request.kind == "create")
    if case.startswith("close-"):
        assert sum(record.state == "close-uncertain" for record in transaction.handles) == 1
        assert sum(record.state == "open" for record in transaction.handles) == len(transaction.handles) - 1
    elif case.startswith("free-"):
        assert rename_requests[0].state == "free-uncertain"
        assert all(record.state == "open" for record in transaction.handles)
    if submitted and not case.startswith("free-"):
        assert admission_witness == [True]  # Outside the caught native callback.
        request = rename_requests[0]
        assert request.pointer and request.state == "uncertain"
        assert submitted[0][1] % ctypes.alignment(move._RenameHeader) == 0
        if case.startswith("pending-"):
            assert request.wait_result == {"pending-timeout": 0x102, "pending-failed": 0xffffffff,
                                           "pending-abandoned": 0x80}.get(case, 0)
            assert request.completion == request.block.status
        assert (ctypes.addressof(request.block), ctypes.addressof(request.buffer), len(request.buffer)) == submitted[0]
        # Non-owning ctypes views may be recreated after collection, while native memory stays.
        gc.collect()
        assert move._StatusBlock.from_address(request.pointer).status == request.block.status
    original_paths = result.owned_residue_paths
    calls = []
    move._open = lambda *args, **kwargs: calls.append(args)
    later = move.safe_move(str(src.with_name("later.txt")), str(dst.with_name("later.txt")),
                           expected_fingerprint=SourceFingerprint(1, 1),
                           allowed_roots=(str(src.parent), str(dst.parent)))
    recovery(later)
    assert later.owned_residue_paths == () and later.source_fingerprint is None and calls == []
    assert original_paths and len(original_paths) <= 4
    ordinary(move.safe_move("bad", "bad", expected_fingerprint=SourceFingerprint(1, 1),
                            allowed_roots=(str(src.parent),)), "SAFE_MOVE_INVALID_INPUT")
    _publish_ready_json(ready_text, {"case": case, "events": events, "waits": waits,
                                    "residue": original_paths})
    deadline = time.monotonic() + 15
    while not Path(exit_text).exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert Path(exit_text).exists(), "Parent did not release child normally"


@pytest.mark.parametrize("case", [
    "pending-timeout", "pending-failed", "pending-abandoned", "pending-iosb-sentinel",
    "pending-iosb-pending", "pending-iosb-unknown", "pending-terminal-success",
    "pending-terminal-collision", "informational", "success-iosb-mismatch",
    "submission-after-effect", "close-before-effect", "close-after-effect",
    "submission-keyboardinterrupt", "submission-systemexit-after-effect",
    "free-before-effect", "free-after-effect",
])
def test_r1_process_quarantine_and_normal_exit_release(tmp_path, case, capsys):
    owned = tmp_path / "r1-owned"; owned.mkdir()
    target_parent = tmp_path / "r1-target"; target_parent.mkdir()
    src, dst = owned / "source.txt", target_parent / "target.txt"
    src.write_bytes(b"SYNTHETIC_APPROVED")
    collision = case.startswith("close-")
    if collision:
        dst.write_bytes(b"OCCUPIED")
    ready, exit_marker = tmp_path / "ready.json", tmp_path / "normal-exit"
    code = "import runpy,sys; runpy.run_path(sys.argv[1])['_r1_child'](*sys.argv[2:])"
    child = subprocess.Popen([sys.executable, "-B", "-c", code, str(Path(__file__).resolve()),
                              case, str(src), str(dst), str(ready), str(exit_marker)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    witness = None
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "Child failed before ownership/lock witness"
        evidence = json.loads(ready.read_text(encoding="utf-8"))
        assert evidence["case"] == case
        renamed = case in ("submission-after-effect", "submission-systemexit-after-effect",
                           "free-before-effect", "free-after-effect")
        locked_path = dst if renamed else src
        if renamed:
            assert not src.exists() and dst.exists()
        try:
            probe = move._open(str(locked_path))
        except OSError as error:
            witness = error.winerror
        else:
            move._close(probe)  # Only the parent's own probe, never a child handle.
        assert witness == 32, (case, witness)
        locked_ancestor = target_parent if renamed else owned
        with pytest.raises(OSError):
            os.rename(locked_ancestor, locked_ancestor.with_name("moved-while-child-live"))
        if renamed:
            # The source parent now has only its retained guard and stays pinned.
            with pytest.raises(OSError):
                os.rename(owned, owned.with_name("empty-source-escaped"))
    finally:
        exit_marker.write_text("normal exit", encoding="ascii")
        stdout, stderr = child.communicate(timeout=30)
        with capsys.disabled():
            print(f"R1_CHILD_PROOF same_volume=True case={case} native_exit={child.returncode} lock={witness} stdout={stdout!r} stderr={stderr!r}")
    assert child.returncode == 0, (stdout, stderr)
    assert "R1_CHILD_FORBIDDEN=0" in stdout and "R1_CHILD_ATEXIT=[('MainThread', False)]" in stdout
    if collision:
        assert src.read_bytes() == b"SYNTHETIC_APPROVED"
        assert dst.read_bytes() == b"OCCUPIED"
    elif case in ("submission-after-effect", "submission-systemexit-after-effect",
                  "free-before-effect", "free-after-effect"):
        assert dst.read_bytes() == b"SYNTHETIC_APPROVED"
        assert not src.exists()
    else:
        assert src.read_bytes() == b"SYNTHETIC_APPROVED"
        assert not dst.exists()
    moved = owned.with_name("moved-after-child-exit")
    os.rename(owned, moved); os.rename(moved, owned)
    assert list(target_parent.glob(".xuxia-move-*")) == []
    if src.exists():
        src.unlink()
    if dst.exists():
        dst.unlink()
    owned.rmdir(); target_parent.rmdir()
    assert not owned.exists() and not target_parent.exists()


def test_unavailable_nt_entry_fails_closed_without_io(pair, monkeypatch):
    calls = []
    monkeypatch.setattr(move, "_NATIVE_AVAILABLE", False)
    monkeypatch.setattr(move, "_open", lambda *args, **kw: calls.append(args))
    ordinary(invoke(*pair), "SAFE_MOVE_UNSUPPORTED_PLATFORM")
    assert calls == [] and pair[0].exists() and not pair[1].exists()


@pytest.mark.parametrize("bad", ["C:/root/a.txt/", "C:/root/a.txt\\", "C:/root/a\x85b", "C:/root/CON .txt"])
@pytest.mark.parametrize("field", ["source", "destination"])
def test_rejected_path_aliases_do_not_open_handles(monkeypatch, field, bad):
    calls = []
    monkeypatch.setattr(move, "_open", lambda *args, **kw: calls.append(args))
    args = dict(source="C:/root/s.txt", destination="C:/root/d.txt", allowed_roots=("C:/root",),
                expected_fingerprint=SourceFingerprint(1, 1))
    args[field] = bad
    ordinary(move.safe_move(**args), "SAFE_MOVE_INVALID_INPUT")
    assert calls == []


def test_exact_subclasses_rejected_without_io(monkeypatch):
    class Text(str):
        pass
    class Roots(tuple):
        pass
    class Fingerprint(SourceFingerprint):
        pass
    calls = []
    monkeypatch.setattr(move, "_open", lambda *args, **kw: calls.append(args))
    base = dict(source="C:/root/s.txt", destination="C:/root/d.txt", allowed_roots=("C:/root",),
                expected_fingerprint=SourceFingerprint(1, 1))
    for field, value in [("source", Text(base["source"])), ("destination", Text(base["destination"])),
                         ("allowed_roots", Roots(base["allowed_roots"])),
                         ("expected_fingerprint", Fingerprint(1, 1))]:
        args = {**base, field: value}
        ordinary(move.safe_move(**args), "SAFE_MOVE_INVALID_INPUT")
    assert calls == []


def test_unselected_missing_root_is_not_created(pair):
    src, dst = pair
    unused = src.parent / "unused-absent"
    approved = fingerprint(src)
    success(invoke(src, dst, roots=(str(src.parent), str(unused))), dst, approved)
    assert not unused.exists()


def test_utf16_basename_boundary_and_root_separator_normalization(pair):
    src, _ = pair
    dst = src.parent / ("🌱" * 125 + "a.txt")  # Exactly 255 UTF-16 units.
    approved = fingerprint(src)
    success(invoke(src, dst, roots=(str(src.parent) + "\\",)), dst, approved)
    assert dst.read_bytes() == b"SYNTHETIC_APPROVED"


def test_occupied_target_is_preserved(pair):
    src, dst = pair
    dst.write_bytes(b"OCCUPIED")
    approved = fingerprint(src)
    result = invoke(src, dst)
    ordinary(result, "SAFE_MOVE_TARGET_OCCUPIED")
    assert result.source_fingerprint == approved
    assert src.read_bytes() == b"SYNTHETIC_APPROVED" and dst.read_bytes() == b"OCCUPIED"


@pytest.mark.parametrize("data", [b"", b"SYNTHETIC_APPROVED", bytes(range(256)) * 5000],
                         ids=["zero-byte", "ordinary", "over-one-MiB"])
@pytest.mark.parametrize("occupied", [False, True])
def test_r2_cross_volume_refusal_has_no_file_mutation(pair, second_volume, monkeypatch, data, occupied):
    src, _ = pair; src.write_bytes(data)
    dst = second_volume / "blocked.txt"
    if occupied:
        dst.write_bytes(b"OCCUPIED")
    approved, identity = fingerprint(src), src.stat().st_ino
    actions, real_open, real_create = [], move._open, move._nt_create
    def open_only_existing(path, **kwargs):
        if not kwargs.get("directory") and str(path).casefold() != str(src).casefold():
            actions.append(("target-file-open", path))
            raise OSError("Forbidden cross-volume target open")
        return real_open(path, **kwargs)
    def forbidden(*args, **kwargs):
        actions.append("forbidden-mutation")
        raise OSError("Forbidden cross-volume action")
    def create_only_admitted(request, access, share, disposition, options):
        if disposition != 1 or not options & 1 and request.name != src.name:
            actions.append(("unauthorized-relative-action", request.name, disposition))
            raise OSError("Forbidden cross-volume relative creation/open")
        return real_create(request, access, share, disposition, options)
    monkeypatch.setattr(move, "_open", open_only_existing)
    monkeypatch.setattr(move, "_nt_create", create_only_admitted)
    monkeypatch.setattr(move, "_rename", forbidden)
    monkeypatch.setattr(move._Transaction, "guard", forbidden)
    for name in ("ReadFile", "WriteFile", "SetFileTime", "FlushFileBuffers",
                 "SetFileInformationByHandle", "CopyFileW", "MoveFileExW", "DeleteFileW", "CreateDirectoryW"):
        monkeypatch.setattr(move._kernel, name, forbidden)
    result = invoke(src, dst, approved=approved)
    ordinary(result, "SAFE_MOVE_CROSS_VOLUME_BLOCKED")
    assert result.source_fingerprint == approved and actions == []
    assert fingerprint(src) == approved and src.stat().st_ino == identity and src.read_bytes() == data
    assert dst.read_bytes() == b"OCCUPIED" if occupied else not dst.exists()
    assert list(second_volume.glob(".xuxia-move-*")) == []


@pytest.mark.parametrize("create", [False, True])
def test_r2_cross_volume_blocked_before_missing_descendant_creation(pair, second_volume, monkeypatch, create):
    src, _ = pair; dst = second_volume / "absent" / "nested" / "target.txt"
    approved, actions = fingerprint(src), []
    def forbidden(*args, **kwargs):
        actions.append(True)
        raise OSError("Cross-volume mutation forbidden")
    monkeypatch.setattr(move._Transaction, "guard", forbidden)
    monkeypatch.setattr(move, "_rename", forbidden)
    result = invoke(src, dst, roots=(str(src.parent), str(second_volume)), approved=approved,
                    create_parents=create)
    ordinary(result, "SAFE_MOVE_CROSS_VOLUME_BLOCKED")
    assert result.source_fingerprint == approved and actions == []
    assert src.read_bytes() == b"SYNTHETIC_APPROVED" and fingerprint(src) == approved
    assert not (second_volume / "absent").exists() and list(second_volume.iterdir()) == []


def test_r2_actual_preserved_time_late_ads_keeps_original_and_stream(pair, second_volume, monkeypatch, capsys):
    src, _ = pair; dst = second_volume / "absent" / "target.txt"
    approved, identity = fingerprint(src), src.stat().st_ino
    source_handles, root_handles, witnesses = [], [], []
    opened, queried = move._Transaction.open_child, move._info
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p,
                                  ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong,
                                ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p]
    kernel.WriteFile.restype = ctypes.c_int
    from ctypes import wintypes
    kernel.SetFileTime.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.FILETIME),
                                   ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME)]
    kernel.SetFileTime.restype = ctypes.c_int
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]; kernel.CloseHandle.restype = ctypes.c_int
    payload = b"SYNTHETIC_LATE_STREAM_MUST_SURVIVE"
    def open_file(transaction, parent, name, **kwargs):
        handle = opened(transaction, parent, name, **kwargs)
        if name == src.name:
            source_handles.append(handle)
        if name == second_volume.name:
            root_handles.append(handle)
        return handle
    def info(handle):
        value = queried(handle)
        if handle in root_handles and not witnesses:
            original = queried(source_handles[0])  # Real admitted held source.
            stream = kernel.CreateFileW(move._native_path(str(src) + ":late-evidence"),
                                        0x40000000, 7, None, 1, 0x00200000, None)
            if stream == ctypes.c_void_p(-1).value:
                witnesses.append(("open-failed", ctypes.get_last_error()))
                return value
            try:
                buffer = ctypes.create_string_buffer(payload, len(payload)); count = ctypes.c_ulong()
                if not kernel.WriteFile(stream, buffer, len(payload), ctypes.byref(count), None):
                    raise OSError("Owned ADS write failed")
                if count.value != len(payload):
                    raise OSError("Owned ADS short write")
                times = [wintypes.FILETIME(t & 0xffffffff, t >> 32)
                         for t in (original.creation, original.access, original.write)]
                if not kernel.SetFileTime(stream, *(ctypes.byref(t) for t in times)):
                    raise OSError("Owned ADS time restore failed")
            finally:
                if not kernel.CloseHandle(stream):
                    raise OSError("Owned ADS close failed")
            after = queried(source_handles[0])
            witnesses.append(("written-restored", after.fingerprint, original.volume, value.volume))
        return value
    monkeypatch.setattr(move._Transaction, "open_child", open_file); monkeypatch.setattr(move, "_info", info)
    result = invoke(src, dst, roots=(str(src.parent), str(second_volume)), approved=approved)
    with capsys.disabled():
        print(f"R2_LATE_ADS result={result!r} witnesses={witnesses!r} source_exists={src.exists()}")
    ordinary(result, "SAFE_MOVE_CROSS_VOLUME_BLOCKED")
    assert len(witnesses) == 1 and witnesses[0][0] == "written-restored"
    assert witnesses[0][1] == approved and witnesses[0][2] != witnesses[0][3]
    assert result.source_fingerprint == approved and fingerprint(src) == approved
    assert src.stat().st_ino == identity and src.read_bytes() == b"SYNTHETIC_APPROVED"
    assert Path(str(src) + ":late-evidence").read_bytes() == payload
    assert not dst.exists() and not dst.parent.exists() and list(second_volume.iterdir()) == []


def test_r2_empty_pinned_target_cannot_escape_approved_root(tmp_path, monkeypatch, capsys):
    """Initially empty root is guarded at publication; low-level empty proof is separate."""
    source_root, target_root = tmp_path / "source-root", tmp_path / "target-root"
    source_root.mkdir(); target_root.mkdir()
    escaped_root = tmp_path / "outside-approved-roots"
    reparse_target = tmp_path / "owned-reparse-outside"; reparse_target.mkdir()
    src, dst = source_root / "source.txt", target_root / "target.txt"
    src.write_bytes(b"APPROVED_ONLY_INSIDE_ROOT")
    approved, witnesses, rename = fingerprint(src), [], move._rename
    guarded = []
    def attempted(handle, parent, name):
        guards = list(target_root.glob(".xuxia-move-*"))
        guarded.append(([p.stat().st_size for p in guards],
                        _r3_owned_junction(target_root, reparse_target, 0x100)))
        try:
            os.rename(target_root, escaped_root)
        except OSError as error:
            witnesses.append(("denied", error.winerror))
        else:
            witnesses.append(("escaped", 0))
        return rename(handle, parent, name)
    monkeypatch.setattr(move, "_rename", attempted)
    result = invoke(src, dst, roots=(str(source_root), str(target_root)), approved=approved)
    escaped_file = escaped_root / dst.name
    observed = (result, witnesses, src.exists(), dst.exists(), escaped_file.exists(),
                escaped_file.read_bytes() if escaped_file.exists() else None)
    with capsys.disabled():
        print(f"R2_EMPTY_PARENT_ESCAPE actual={observed!r}")
    assert witnesses == [("denied", 32)], observed
    assert guarded == [([0], {"opened": True, "set": False, "winerror": 145, "closed": True})]
    success(result, dst, approved)
    assert not escaped_root.exists() and not src.exists() and dst.read_bytes() == b"APPROVED_ONLY_INSIDE_ROOT"
    assert list(reparse_target.iterdir()) == [] and not target_root.is_junction()
    assert list(target_root.glob(".xuxia-move-*")) == []


def test_r2_native_attribute_vs_list_directory_sharing_comparison(tmp_path, capsys):
    observed = []
    for access in (0x80, 0x81):
        owned = tmp_path / f"directory-{access:x}"; owned.mkdir()
        escaped = owned.with_name(owned.name + "-renamed")
        handle = move._kernel.CreateFileW(move._native_path(str(owned)), access, 3,
                                          None, 3, 0x02200000, None)
        assert handle != ctypes.c_void_p(-1).value, ctypes.get_last_error()
        try:
            try:
                os.rename(owned, escaped)
            except OSError as error:
                observed.append((access, "denied", error.winerror))
            else:
                observed.append((access, "renamed", 0))
        finally:
            move._close(handle)  # Test owns this normal, unambiguous diagnostic handle.
        if escaped.exists():
            os.rename(escaped, owned)
        assert owned.exists(); owned.rmdir()
    with capsys.disabled():
        print(f"R2_NATIVE_DIRECTORY_ACCESS_COMPARISON actual={observed!r}")
    assert observed == [(0x80, "renamed", 0), (0x81, "denied", 32)], observed


def _r3_kernel():
    """Independent ordinary native bindings; no privilege/configuration changes."""
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
                                      wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.DeviceIoControl.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _r3_owned_junction(directory, target, access=0x40000000):
    """Try a real writable open/conversion; return close evidence to outer tests."""
    kernel = _r3_kernel()
    substitute = ("\\??\\" + str(target)).encode("utf-16-le")
    display = str(target).encode("utf-16-le")
    body = struct.pack("<HHHH", 0, len(substitute), len(substitute) + 2, len(display))
    body += substitute + b"\0\0" + display + b"\0\0"
    data = struct.pack("<IHH", 0xA0000003, len(body), 0) + body
    handle = kernel.CreateFileW(move._native_path(str(directory)), access,
                                7, None, 3, 0x02200000, None)
    evidence = {"opened": False, "set": False, "winerror": 0, "closed": None}
    if handle == ctypes.c_void_p(-1).value:
        evidence["winerror"] = ctypes.get_last_error()
        return evidence
    evidence["opened"] = True
    try:
        returned = ctypes.c_ulong()
        buffer = ctypes.create_string_buffer(data)
        accepted = kernel.DeviceIoControl(handle, 0x900A4, buffer, len(data), None, 0,
                                          ctypes.byref(returned), None)
        evidence["set"] = bool(accepted)
        evidence["winerror"] = 0 if accepted else ctypes.get_last_error()
    finally:
        evidence["closed"] = bool(kernel.CloseHandle(handle))
    return evidence


def _r4_relative_guard_premise_child(parent_text, outside_text, report_text):
    """Owned-fixture premise only: never submits a source rename or source delete.

    All NtCreateFile pointers live in one process-heap allocation; ambiguous
    outcomes deliberately leave it and handles for actual process termination.
    """
    import atexit
    import threading
    from ctypes import wintypes
    atexit.register(lambda: print("R4_PREMISE_ATEXIT=" + repr(
        [(t.name, t.is_alive()) for t in threading.enumerate()]), flush=True))
    parent, outside = Path(parent_text), Path(outside_text)
    assert parent.parent == outside.parent and parent != outside
    assert parent.is_dir() and outside.is_dir()
    assert not list(parent.iterdir()) and not list(outside.iterdir())
    class Unicode(ctypes.Structure):
        _fields_ = [("length", wintypes.USHORT), ("maximum", wintypes.USHORT),
                    ("buffer", ctypes.c_void_p)]
    class Attributes(ctypes.Structure):
        _fields_ = [("length", wintypes.ULONG), ("root", wintypes.HANDLE),
                    ("name", ctypes.c_void_p), ("attributes", wintypes.ULONG),
                    ("security", ctypes.c_void_p), ("quality", ctypes.c_void_p)]
    native = ctypes.WinDLL("ntdll")
    native.NtCreateFile.argtypes = [ctypes.c_void_p, wintypes.ULONG, ctypes.c_void_p,
                                  ctypes.c_void_p, ctypes.c_void_p, wintypes.ULONG,
                                  wintypes.ULONG, wintypes.ULONG, wintypes.ULONG,
                                  ctypes.c_void_p, wintypes.ULONG]
    native.NtCreateFile.restype = ctypes.c_int32
    kernel = _r3_kernel()
    held = kernel.CreateFileW(move._native_path(str(parent)), 0x100081, 3,
                              None, 3, 0x02200000, None)
    assert held != ctypes.c_void_p(-1).value, ctypes.get_last_error()
    converted = _r3_owned_junction(parent, outside, 0x100)
    observed = {"conversion": converted, "status": None, "close": None,
                "outside_live": [], "outside_after": [], "quarantined": False}
    if converted["set"]:
        pointer = move._heap_alloc(2048)
        slot = ctypes.c_void_p.from_address(pointer)
        block = move._StatusBlock.from_address(pointer + 32)
        attrs = Attributes.from_address(pointer + 64)
        name = Unicode.from_address(pointer + 128)
        encoded = ".xuxia-move-owned-premise.tmp".encode("utf-16-le")
        ctypes.memmove(pointer + 256, encoded, len(encoded))
        name.length = len(encoded); name.maximum = len(encoded) + 2
        name.buffer = pointer + 256
        attrs.length = ctypes.sizeof(Attributes); attrs.root = held
        attrs.name = pointer + 128; attrs.attributes = 0x1040  # DONT_REPARSE | CASE_INSENSITIVE
        block.status = ctypes.c_int32(0xC0000000).value
        # READ_DATA | READ_ATTRIBUTES | DELETE | SYNCHRONIZE; CREATE only,
        # NON_DIRECTORY | SYNC_NONALERT | OPEN_REPARSE_POINT | DELETE_ON_CLOSE.
        status = native.NtCreateFile(pointer, 0x110081, pointer + 64, pointer + 32,
                                     None, 0x80, 0, 2, 0x201060, None, 0)
        observed.update(status=status, iosb=block.status, information=block.information,
                        output_handle=bool(slot.value),
                        outside_live=[p.name for p in outside.iterdir()])
        definite_success = status == 0 and block.status == 0 and block.information == 2 and bool(slot.value)
        definite_failure = status < 0 and not slot.value
        if definite_success:
            output_handle = slot.value  # Register before the request allocation is freed.
            move._heap_free(pointer)
            observed["close"] = bool(kernel.CloseHandle(output_handle))
            if not observed["close"]:
                observed["quarantined"] = True
        elif definite_failure:
            move._heap_free(pointer)
        else:
            observed["quarantined"] = True
    if not observed["quarantined"]:
        observed["parent_close"] = bool(kernel.CloseHandle(held))
    observed["outside_after"] = [p.name for p in outside.iterdir()]
    Path(report_text).write_text(json.dumps(observed), encoding="utf-8")
    print("R4_RELATIVE_GUARD_PREMISE=" + json.dumps(observed), flush=True)


def test_r4_first_relative_guard_cannot_redirect_converted_held_parent(tmp_path, capsys):
    """Architecture stop gate: an escaped guard is a failure even if close removes it."""
    parent, outside = tmp_path / "premise-parent", tmp_path / "premise-outside"
    parent.mkdir(); outside.mkdir()
    src = tmp_path / "untouched-source.txt"; src.write_bytes(b"R4_SOURCE_MUST_NOT_MOVE")
    approved, report = fingerprint(src), tmp_path / "premise-report.json"
    code = "import runpy,sys; runpy.run_path(sys.argv[1])['_r4_relative_guard_premise_child'](*sys.argv[2:])"
    child = subprocess.run([sys.executable, "-B", "-c", code, str(Path(__file__).resolve()),
                            str(parent), str(outside), str(report)],
                           capture_output=True, text=True, timeout=30)
    try:
        with capsys.disabled():
            print(f"R4_PREMISE_CHILD native_exit={child.returncode} stdout={child.stdout!r} stderr={child.stderr!r}")
        assert child.returncode == 0, (child.stdout, child.stderr)
        observed = json.loads(report.read_text(encoding="utf-8"))
        assert observed["conversion"] == {"opened": True, "set": True, "winerror": 0, "closed": True}
        assert observed["status"] == ctypes.c_int32(0xC0000280).value and not observed["output_handle"]
        assert observed["outside_live"] == [] and observed["outside_after"] == [], observed
        assert not observed["quarantined"] and observed["parent_close"] is True, observed
        assert "R4_PREMISE_ATEXIT=[('MainThread', False)]" in child.stdout
        assert src.read_bytes() == b"R4_SOURCE_MUST_NOT_MOVE" and fingerprint(src) == approved
    finally:
        if parent.is_junction():
            os.rmdir(parent)  # Exact synthetic link after actual child termination.
    assert not parent.exists() and outside.is_dir()


def test_r4_relative_admission_uses_absolute_drive_anchor_only(pair, monkeypatch):
    src, dst = pair; opened, real_open = [], move._open
    def observe(path, **kwargs):
        opened.append(str(path))
        return real_open(path, **kwargs)
    monkeypatch.setattr(move, "_open", observe)
    approved = fingerprint(src)
    result = invoke(src, dst)
    success(result, dst, approved)
    assert opened and all(len(path) == 3 and path[1:] == ":\\" for path in opened), opened


def test_r4_before_guard_conversion_preserves_source_without_escape(tmp_path, monkeypatch, capsys):
    source_root, target_root, outside = (tmp_path / name for name in ("source-root", "target-root", "outside"))
    for path in (source_root, target_root, outside):
        path.mkdir()
    src, dst = source_root / "source.txt", target_root / "child" / "target.txt"
    src.write_bytes(b"R4_APPROVED_SOURCE")
    approved, attempts = fingerprint(src), []
    assert callable(getattr(move._Transaction, "guard", None)), "Held-relative guard admission missing"
    real = move._Transaction.guard
    def before_guard(transaction, parent, path, **kwargs):
        if str(path).casefold() == str(target_root).casefold() and not attempts:
            attempts.append(_r3_owned_junction(target_root, outside, 0x100))
        return real(transaction, parent, path, **kwargs)
    monkeypatch.setattr(move._Transaction, "guard", before_guard)
    try:
        result = invoke(src, dst, roots=(str(source_root), str(target_root)), approved=approved)
        with capsys.disabled():
            print(f"R4_BEFORE_GUARD result={result!r} conversion={attempts!r} outside={list(outside.iterdir())!r}")
        assert attempts == [{"opened": True, "set": True, "winerror": 0, "closed": True}]
        assert not result.success and not result.recovery_required
        assert src.read_bytes() == b"R4_APPROVED_SOURCE" and fingerprint(src) == approved
        assert list(outside.iterdir()) == [] and not dst.exists()
        assert list(source_root.glob(".xuxia-move-*")) == []
    finally:
        if target_root.is_junction():
            os.rmdir(target_root)


def test_r4_source_parent_guard_survives_real_rename_and_normal_cleanup(tmp_path, monkeypatch, capsys):
    source_root, target_root, outside = (tmp_path / name for name in ("source-root", "target-root", "outside"))
    for path in (source_root, target_root, outside):
        path.mkdir()
    src, dst = source_root / "source.txt", target_root / "target.txt"
    src.write_bytes(b"R4_APPROVED_SOURCE")
    approved, witnesses, real = fingerprint(src), [], move._rename
    rename_denials = []
    def after_rename(*args):
        real(*args)
        try:
            os.rename(source_root, source_root.with_name("escaped-source-parent"))
        except OSError as error:
            rename_denials.append(error.winerror)
        else:
            rename_denials.append("UNSAFE_SUCCESS")
        guards = list(source_root.glob(".xuxia-move-*"))
        witnesses.append((len(guards), [p.stat().st_size for p in guards],
                          _r3_owned_junction(source_root, outside, 0x100)))
    monkeypatch.setattr(move, "_rename", after_rename)
    try:
        result = invoke(src, dst, approved=approved)
        with capsys.disabled():
            print(f"R4_SOURCE_PARENT_AFTER_RENAME result={result!r} witnesses={witnesses!r}")
        assert len(witnesses) == 1 and witnesses[0][0:2] == (1, [0]), witnesses
        assert rename_denials == [32] and not source_root.with_name("escaped-source-parent").exists()
        assert witnesses[0][2]["opened"] and not witnesses[0][2]["set"] and witnesses[0][2]["closed"]
        success(result, dst, approved)
        assert dst.read_bytes() == b"R4_APPROVED_SOURCE" and not src.exists()
        assert list(outside.iterdir()) == [] and not source_root.is_junction()
        assert list(source_root.iterdir()) == []
        assert list(target_root.glob(".xuxia-move-*")) == []
    finally:
        if source_root.is_junction():
            os.rmdir(source_root)


def test_r4_guard_cannot_be_removed_or_replaced_while_held(pair, monkeypatch):
    src, dst = pair; approved, witnesses, real = fingerprint(src), [], move._rename
    kernel = _r3_kernel()
    def native_write_open(guard):
        handle = kernel.CreateFileW(move._native_path(str(guard)), 0x40000000, 7,
                                    None, 3, 0x00200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise move._NativeError(ctypes.get_last_error())
        # Only this unexpected test-owned probe is closed; never rescue product handles.
        if not kernel.CloseHandle(handle):
            raise OSError("Test probe close failed")
    def probe(*args):
        guards = list(src.parent.glob(".xuxia-move-*"))
        witnesses.append(("guards", len(guards)))
        for guard in guards:
            for operation in (guard.unlink, lambda: native_write_open(guard),
                              lambda: os.rename(guard, guard.with_name("guard-stolen"))):
                try:
                    operation()
                except OSError as error:
                    witnesses.append(("denied", error.winerror))
                else:
                    witnesses.append(("unsafe", 0))
        return real(*args)
    monkeypatch.setattr(move, "_rename", probe)
    result = invoke(src, dst, approved=approved)
    assert witnesses == [("guards", 1), ("denied", 32), ("denied", 32), ("denied", 32)]
    success(result, dst, approved)
    assert list(src.parent.glob(".xuxia-move-*")) == []


def test_r4_guard_collision_refuses_without_retry_or_preexisting_deletion(pair, monkeypatch):
    src, dst = pair; approved = fingerprint(src)
    assert hasattr(move, "secrets"), "Create-only randomized owned guards missing"
    calls = []
    def token(amount):
        calls.append(amount)
        return "a" * 32
    monkeypatch.setattr(move.secrets, "token_hex", token)
    occupied = src.parent / (".xuxia-move-" + "a" * 32 + ".tmp")
    occupied.write_bytes(b"PREEXISTING_DO_NOT_DELETE")
    result = invoke(src, dst, approved=approved)
    assert not result.success and not result.recovery_required and len(calls) == 1
    assert occupied.read_bytes() == b"PREEXISTING_DO_NOT_DELETE"
    assert src.read_bytes() == b"SYNTHETIC_APPROVED" and fingerprint(src) == approved and not dst.exists()


def test_r4_non_ntfs_refuses_before_guards_or_descendants(pair, monkeypatch):
    src, _ = pair; dst = src.parent / "absent" / "target.txt"
    assert callable(getattr(move, "_filesystem", None)), "Held filesystem admission missing"
    monkeypatch.setattr(move, "_filesystem", lambda handle: "UNPROVEN_FS")
    ordinary(invoke(src, dst, roots=(str(src.parent),)), "SAFE_MOVE_UNSUPPORTED_METADATA")
    assert src.read_bytes() == b"SYNTHETIC_APPROVED" and not dst.parent.exists()
    assert list(src.parent.glob(".xuxia-move-*")) == []


@pytest.mark.parametrize("parent", ["C:\\", "C:\\" + "\\".join(["p" * 240] * 16 + ["q" * 210])],
                         ids=["bare-drive", "overlong-generated-guard"])
def test_r4_guard_parent_and_generated_path_bounds_before_submission(monkeypatch, parent):
    transaction, calls = move._Transaction(), []
    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise move._Unsupported()
    monkeypatch.setattr(transaction, "open_child", forbidden)
    assert len(parent) <= 4096
    with pytest.raises((ValueError, move._Unsupported)):
        transaction.guard(123, parent)
    assert calls == [] and transaction.guards == {}


@pytest.mark.parametrize("nested", [False, True])
def test_r4_retained_source_guard_reused_for_overlapping_target(pair, monkeypatch, nested):
    src, dst = pair
    if nested:
        dst = src.parent / "one" / "two" / "target.txt"
    observed, real = [], move._rename
    def publication(*args):
        guards = list(src.parent.rglob(".xuxia-move-*"))
        observed.append([(str(p.parent), p.stat().st_size) for p in guards])
        return real(*args)
    monkeypatch.setattr(move, "_rename", publication)
    approved = fingerprint(src)
    result = invoke(src, dst, roots=(str(src.parent),), approved=approved)
    assert len(observed) == 1 and (str(src.parent), 0) in observed[0]
    assert len(observed[0]) == (2 if nested else 1)
    success(result, dst, approved)
    assert list(src.parent.rglob(".xuxia-move-*")) == []


def _r4_uncertainty_child(case, src_text, dst_text, ready_text, exit_text):
    """Controlled create faults + physical lock/process-release witnesses."""
    import atexit
    import socket
    import threading
    forbidden = []
    def deny(*args, **kwargs):
        forbidden.append(True)
        raise AssertionError("Forbidden external access")
    for name in ("connect", "connect_ex", "sendto"):
        setattr(socket.socket, name, deny)
    for name in ("getaddrinfo", "create_connection"):
        setattr(socket, name, deny)
    import keyring, keyring.core
    from keyring.backends import Windows
    from keyring.backends.fail import Keyring
    keyring.set_keyring(Keyring())
    for owner in (keyring, keyring.core, Windows.WinVaultKeyring):
        for name in ("get_password", "set_password", "delete_password", "get_credential",
                     "_read_credential", "_resolve_credential", "_set_password", "_delete_password"):
            if hasattr(owner, name):
                setattr(owner, name, deny)
    for name in ("CredRead", "CredWrite", "CredDelete", "CredEnumerate"):
        if hasattr(Windows.win32cred, name):
            setattr(Windows.win32cred, name, deny)
    def exiting():
        print("R4_CHILD_FORBIDDEN=" + str(len(forbidden)), flush=True)
        print("R4_CHILD_ATEXIT=" + repr([(t.name, t.is_alive()) for t in threading.enumerate()]), flush=True)
    atexit.register(exiting)
    src, dst = Path(src_text), Path(dst_text)
    assert callable(getattr(move, "_nt_create", None)), "Bounded relative creation missing"
    real, real_free, real_close = move._nt_create, move._heap_free, move._close
    submitted, frees, closes, waits, external = [], [], [], [], []
    def native(request, access, share, disposition, options):
        # Admit the source first; uncertainty targets only the new source guard.
        if not request.name.startswith(".xuxia-move-") or submitted:
            return real(request, access, share, disposition, options)
        submitted.append(request)
        assert request in move._OWNER.active.requests
        if case in ("close-before", "close-after", "external-attribute-handle"):
            status = real(request, access, share, disposition, options)
            if case == "external-attribute-handle":
                kernel = _r3_kernel()
                path = src.parent / request.name
                handle = kernel.CreateFileW(move._native_path(str(path)), 0x80, 7, None, 3, 0x00200000, None)
                external.append((handle, str(path)))  # Intentionally held to actual child exit.
            return status
        if case.startswith("pending"):
            if case == "pending-handle":
                real(request, access, share, disposition, options)
            return 0x103
        if case == "informational":
            return 1
        status = real(request, access, share, disposition, options)
        if case == "iosb-mismatch":
            request.block.status = 1
        elif case == "information-mismatch":
            request.block.information = 1
        elif case == "missing-output":
            # Do not lose a real handle: this case is a no-effect success fiction.
            raise AssertionError("Case must use no-effect branch")
        elif case == "negative-with-handle":
            return ctypes.c_int32(0xC0000022).value
        elif case == "submission-after":
            raise OSError("controlled post-create exception")
        return status
    def submit(request, *args):
        if case == "missing-output" and request.name.startswith(".xuxia-move-") and not submitted:
            submitted.append(request); request.block.status = 0; request.block.information = 2
            return 0
        return native(request, *args)
    def free(pointer):
        if submitted and pointer == submitted[0].pointer:
            frees.append(pointer)
            if case.startswith("free-"):
                if case == "free-after":
                    real_free(pointer)
                raise OSError("controlled create free ambiguity")
        return real_free(pointer)
    def close(handle):
        if submitted:
            closes.append(handle)
            if case.startswith("close-"):
                if case == "close-after":
                    real_close(handle)
                raise OSError("controlled guard close ambiguity")
        return real_close(handle)
    move._nt_create, move._heap_free, move._close = submit, free, close
    move._wait = lambda handle, milliseconds: waits.append(milliseconds) or 0x102
    result = invoke(src, dst)
    recovery(result)
    transaction = move._OWNER.quarantine
    assert transaction and transaction.owned_residue_paths == result.owned_residue_paths
    assert len(result.owned_residue_paths) <= 4
    assert len(submitted) == 1
    if case.startswith("close-") or case == "external-attribute-handle":
        assert transaction.published and not src.exists() and dst.exists()
    else:
        assert not transaction.publication_attempted and src.exists() and not dst.exists()
    request = submitted[0]
    assert request in transaction.requests and request.pointer and request.amount <= 2048
    assert request.name.startswith(".xuxia-move-")
    if case.startswith("pending"):
        assert waits == [250]
    if case.startswith("close-"):
        assert len(closes) == 1 and request.state == "freed"
    elif case == "external-attribute-handle":
        assert external and external[0][0] not in (None, ctypes.c_void_p(-1).value)
        assert Path(external[0][1]).exists()
        assert external[0][1] in result.owned_residue_paths
    elif case.startswith("free-"):
        assert len(frees) == 1 and closes == [] and request.state == "free-uncertain"
        assert request.returned_handle in [record.value for record in transaction.handles]
    else:
        assert frees == [] and closes == [] and request.state == "uncertain"
        gc.collect()
        # Every native pointer falls inside the single still-owned allocation.
        for view in (request.output, request.block, request.attributes, request.unicode):
            assert request.pointer <= ctypes.addressof(view) < request.pointer + request.amount
        assert request.pointer <= request.unicode.buffer < request.pointer + request.amount
        if case not in ("pending-no-handle", "informational", "missing-output"):
            assert request.returned_handle in [record.value for record in transaction.handles]
    calls = []
    move._nt_create = lambda *args: calls.append(args)
    move._open = lambda *args, **kwargs: calls.append(args)
    later = invoke(src.with_name("later.txt"), dst.with_name("later.txt"), approved=SourceFingerprint(1, 1))
    recovery(later)
    assert later.owned_residue_paths == () and calls == []
    _publish_ready_json(ready_text, {"case": case, "residue": result.owned_residue_paths,
                                    "published": not src.exists()})
    deadline = time.monotonic() + 15
    while not Path(exit_text).exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert Path(exit_text).exists()


@pytest.mark.parametrize("case", ["pending-no-handle", "pending-handle", "informational",
    "iosb-mismatch", "information-mismatch", "missing-output", "negative-with-handle",
    "submission-after", "free-before", "free-after", "close-before", "close-after",
    "external-attribute-handle"])
def test_r4_relative_create_uncertainty_owns_resources_until_process_exit(tmp_path, case, capsys):
    source_root, target_root = tmp_path / "source-root", tmp_path / "target-root"
    source_root.mkdir(); target_root.mkdir()
    src, dst = source_root / "source.txt", target_root / "target.txt"
    src.write_bytes(b"R4_APPROVED_SOURCE")
    ready, release = tmp_path / "ready.json", tmp_path / "exit"
    code = "import runpy,sys; runpy.run_path(sys.argv[1])['_r4_uncertainty_child'](*sys.argv[2:])"
    child = subprocess.Popen([sys.executable, "-B", "-c", code, str(Path(__file__).resolve()),
                              case, str(src), str(dst), str(ready), str(release)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    witness = None
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "Child did not establish quarantine witness"
        observed = json.loads(ready.read_text(encoding="utf-8"))
        locked = dst if observed["published"] else src
        try:
            handle = move._open(str(locked))
        except OSError as error:
            witness = error.winerror
        else:
            move._close(handle)
        assert witness == 32
        with pytest.raises(OSError):
            os.rename(source_root, source_root.with_name("escaped-source"))
    finally:
        release.write_text("normal", encoding="ascii")
        stdout, stderr = child.communicate(timeout=30)
        with capsys.disabled():
            print(f"R4_CHILD_PROOF case={case} native_exit={child.returncode} lock={witness} stdout={stdout!r} stderr={stderr!r}")
    assert child.returncode == 0, (stdout, stderr)
    assert "R4_CHILD_FORBIDDEN=0" in stdout and "R4_CHILD_ATEXIT=[('MainThread', False)]" in stdout
    existing = dst if dst.exists() else src
    assert existing.read_bytes() == b"R4_APPROVED_SOURCE"
    assert list(source_root.glob(".xuxia-move-*")) == []
    assert list(target_root.glob(".xuxia-move-*")) == []
    existing.unlink(); source_root.rmdir(); target_root.rmdir()
    assert not source_root.exists() and not target_root.exists()


@pytest.mark.parametrize("access", [0, 0x80, 0x100, 0x40000000],
                         ids=["zero-access", "read-attributes", "write-attributes", "generic-write"])
def test_r3_unheld_junction_construction_physically_traverses_and_cleans(tmp_path, capsys, access):
    link, outside = tmp_path / "control-link", tmp_path / "control-target"
    link.mkdir(); outside.mkdir()
    try:
        observed = _r3_owned_junction(link, outside, access)
        with capsys.disabled():
            print(f"R3_UNHELD_CONTROL access={access:#x} actual={observed!r}")
        if access in (0x100, 0x40000000):
            assert observed == {"opened": True, "set": True, "winerror": 0, "closed": True}
            assert link.is_junction()
            (link / "marker.txt").write_bytes(b"OWNED_JUNCTION_CONTROL")
            assert (outside / "marker.txt").read_bytes() == b"OWNED_JUNCTION_CONTROL"
        else:
            assert observed == {"opened": True, "set": False, "winerror": 5, "closed": True}
            assert not link.is_junction() and list(outside.iterdir()) == []
    finally:
        if link.is_junction():
            os.rmdir(link)  # Exact owned link only: never traverse/delete its target.
    assert not link.is_junction() and outside.is_dir()
    if access in (0x100, 0x40000000):
        assert not link.exists()
        assert (outside / "marker.txt").read_bytes() == b"OWNED_JUNCTION_CONTROL"
    else:
        link.rmdir(); assert not link.exists()


@pytest.mark.parametrize("access", [0, 0x80, 0x100, 0x40000000],
                         ids=["zero-access", "read-attributes", "write-attributes", "generic-write"])
def test_r3_postcheck_target_junction_attempt_denied_before_descendant_creation(tmp_path, monkeypatch, capsys, access):
    source_root, target_root = tmp_path / "source-root", tmp_path / "target-root"
    outside = tmp_path / "outside-approved-roots"
    source_root.mkdir(); target_root.mkdir(); outside.mkdir()
    src, dst = source_root / "source.txt", target_root / "child" / "target.txt"
    src.write_bytes(b"APPROVED_REPARSE_BOUNDARY")
    approved, identity = fingerprint(src), src.stat().st_ino
    create_child, attempts = move._Transaction.open_child, []
    def attempted(transaction, parent, name, **kwargs):
        if kwargs.get("directory") and kwargs.get("create"):
            attempts.append(_r3_owned_junction(target_root, outside, access))
        return create_child(transaction, parent, name, **kwargs)
    monkeypatch.setattr(move._Transaction, "open_child", attempted)
    try:
        result = invoke(src, dst, roots=(str(source_root), str(target_root)), approved=approved)
        escaped = outside / "child" / "target.txt"
        witness = (result, attempts, src.exists(), target_root.is_junction(), escaped.exists(),
                   escaped.read_bytes() if escaped.exists() else None)
        with capsys.disabled():
            print(f"R3_POSTCHECK_REPARSE access={access:#x} actual={witness!r}")
        if access in (0x100, 0x40000000):
            assert len(attempts) == 1 and attempts[0]["opened"] and not attempts[0]["set"]
            assert attempts[0]["closed"] and attempts[0]["winerror"] != 0, witness
        else:
            assert attempts == [{"opened": True, "set": False, "winerror": 5, "closed": True}], witness
        success(result, dst, approved)
        assert dst.stat().st_ino == identity and dst.read_bytes() == b"APPROVED_REPARSE_BOUNDARY"
        assert not src.exists() and not target_root.is_junction()
        assert not (outside / "child").exists() and list(outside.iterdir()) == []
    finally:
        if target_root.is_junction():
            os.rmdir(target_root)  # Preserve failed escaped bytes; remove only owned link.
    assert not target_root.is_junction() and outside.is_dir()


def test_r3_preexisting_writable_target_ancestor_cannot_convert_guarded_parent(tmp_path, monkeypatch, capsys):
    source_root, target_root = tmp_path / "source-root", tmp_path / "target-root"
    source_root.mkdir(); target_root.mkdir()
    src, dst = source_root / "source.txt", target_root / "child" / "target.txt"
    src.write_bytes(b"APPROVED_WRITABLE_ANCESTOR")
    approved, identity = fingerprint(src), src.stat().st_ino
    outside = tmp_path / "outside"; outside.mkdir()
    kernel = _r3_kernel()
    writer = kernel.CreateFileW(move._native_path(str(target_root)), 0x40000000,
                                7, None, 3, 0x02200000, None)
    assert writer != ctypes.c_void_p(-1).value, ctypes.get_last_error()
    attempts, create_child = [], move._Transaction.open_child
    def attempted(transaction, parent, name, **kwargs):
        if kwargs.get("directory") and kwargs.get("create"):
            substitute = ("\\??\\" + str(outside)).encode("utf-16-le")
            display = str(outside).encode("utf-16-le")
            body = struct.pack("<HHHH", 0, len(substitute), len(substitute) + 2, len(display))
            body += substitute + b"\0\0" + display + b"\0\0"
            data = struct.pack("<IHH", 0xA0000003, len(body), 0) + body
            buffer, returned = ctypes.create_string_buffer(data), ctypes.c_ulong()
            accepted = kernel.DeviceIoControl(writer, 0x900A4, buffer, len(data), None, 0,
                                              ctypes.byref(returned), None)
            attempts.append((bool(accepted), 0 if accepted else ctypes.get_last_error(),
                             len(list(target_root.glob(".xuxia-move-*")))))
        return create_child(transaction, parent, name, **kwargs)
    monkeypatch.setattr(move._Transaction, "open_child", attempted)
    try:
        result = invoke(src, dst, roots=(str(source_root), str(target_root)), approved=approved)
        with capsys.disabled():
            print(f"R3_PREEXISTING_WRITER_GUARDED actual={result!r} attempts={attempts!r}")
        assert attempts == [(False, 145, 1)]
        success(result, dst, approved)
        assert dst.stat().st_ino == identity and dst.read_bytes() == b"APPROVED_WRITABLE_ANCESTOR"
        assert not src.exists() and not target_root.is_junction() and list(outside.iterdir()) == []
        assert list(source_root.glob(".xuxia-move-*")) == []
        assert list(target_root.rglob(".xuxia-move-*")) == []
    finally:
        assert kernel.CloseHandle(writer), ctypes.get_last_error()


@pytest.mark.parametrize("field,value", [
    ("source", None), ("source", Path("C:/source")), ("source", ""),
    ("destination", 1), ("destination", "C:relative.txt"),
    ("allowed_roots", []), ("allowed_roots", ()), ("allowed_roots", ("",)),
    ("allowed_roots", (1,)), ("allowed_roots", tuple(f"C:/r{i}" for i in range(2001))),
    ("allowed_roots", ("C:/ROOT", "c:/root")),
    ("expected_fingerprint", None), ("expected_fingerprint", (1, 1)),
    ("expected_fingerprint", SourceFingerprint(True, 1)),
    ("expected_fingerprint", SourceFingerprint(1, False)),
    ("expected_fingerprint", SourceFingerprint(-1, 1)),
    ("expected_fingerprint", SourceFingerprint(1, -1)),
    ("expected_fingerprint", SourceFingerprint(1.0, 1)),
    ("create_parents", 1), ("create_parents", None),
])
def test_exact_input_graph_zero_io(monkeypatch, field, value):
    calls = []
    monkeypatch.setattr(move, "_open", lambda *a, **kw: calls.append(a))
    monkeypatch.setattr(move, "_nt_create", lambda *a: calls.append(a))
    args = dict(source="C:/approved/source.txt", destination="C:/approved/dest.txt",
                allowed_roots=("C:/approved",), expected_fingerprint=SourceFingerprint(1, 1),
                create_parents=True)
    args[field] = value
    ordinary(move.safe_move(**args), "SAFE_MOVE_INVALID_INPUT")
    assert calls == []


@pytest.mark.parametrize("bad", [
    "relative.txt", "C:source.txt", "\\\\server\\share\\source.txt",
    "\\\\?\\C:\\source.txt", "\\\\.\\C:\\source.txt", "C:/approved/../source.txt",
    "C:/approved/./source.txt", "C:/approved/source.txt:stream", "C:/approved/a. ",
    "C:/approved/a.", "C:/approved/a ", "C:/approved/NUL.txt", "C:/approved/COM1",
    "C:/approved/LPT9.txt", "C:/approved/CON/file.txt", "C:/approved/a\x00b",
    "C:/approved/a\nb", "C:/approved/a?b", "C:/approved/" + "a" * 4097,
    "C:/approved/" + "🌱" * 128 + ".txt", "C:/approved/COM¹.txt",
])
@pytest.mark.parametrize("field", ["source", "destination", "root"])
def test_malformed_paths_zero_io(monkeypatch, bad, field):
    calls = []
    monkeypatch.setattr(move, "_open", lambda *a, **kw: calls.append(a))
    args = dict(source="C:/approved/source.txt", destination="C:/approved/dest.txt",
                allowed_roots=("C:/approved",), expected_fingerprint=SourceFingerprint(1, 1))
    args["allowed_roots" if field == "root" else field] = (bad,) if field == "root" else bad
    ordinary(move.safe_move(**args), "SAFE_MOVE_INVALID_INPUT")
    assert calls == []


def test_equal_paths_and_sibling_prefix_escape_zero_io(monkeypatch):
    calls = []
    monkeypatch.setattr(move, "_open", lambda *a, **kw: calls.append(a))
    for src, dst in [("C:/root/s.txt", "c:/ROOT/s.txt"),
                     ("C:/root/s.txt", "C:/root-other/d.txt")]:
        ordinary(move.safe_move(src, dst, expected_fingerprint=SourceFingerprint(1, 1),
                                allowed_roots=("C:/root",)), "SAFE_MOVE_INVALID_INPUT")
    assert calls == []


def test_unsupported_platform_is_closed(pair, monkeypatch):
    monkeypatch.setattr(move, "_WINDOWS", False)
    ordinary(invoke(*pair), "SAFE_MOVE_UNSUPPORTED_PLATFORM")
    assert pair[0].exists() and not pair[1].exists()


@pytest.mark.parametrize("cross", [False, True])
def test_changed_source_before_target_directories(tmp_path, second_volume, cross):
    src = tmp_path / "source.txt"; src.write_bytes(b"APPROVED")
    approved = fingerprint(src); src.write_bytes(b"CHANGED_SOURCE")
    root = second_volume if cross else tmp_path
    dst = root / "absent" / "descendant" / "target.txt"
    ordinary(invoke(src, dst, roots=(str(tmp_path), str(root)) if cross else (str(root),),
                    approved=approved), "SAFE_MOVE_SOURCE_CHANGED")
    assert not dst.parent.parent.exists() and src.read_bytes() == b"CHANGED_SOURCE"


def test_absent_authorizing_root_not_created(pair):
    src, _ = pair
    root = src.parent / "absent-root"; dst = root / "target.txt"
    ordinary(invoke(src, dst, roots=(str(src.parent), str(root))), "SAFE_MOVE_INVALID_ROOT")
    assert not root.exists() and src.exists()


@pytest.mark.parametrize("create", [False, True])
def test_validated_descendant_creation(pair, create):
    src, _ = pair
    dst = src.parent / "child" / "nested" / "target.txt"
    approved = fingerprint(src)
    result = invoke(src, dst, roots=(str(src.parent),), create_parents=create)
    if create:
        success(result, dst, approved)
    else:
        ordinary(result, "SAFE_MOVE_MOVE_FAILED")
        assert not dst.parent.exists() and src.exists()


def test_non_file_and_busy_source(pair):
    src, dst = pair
    directory = src.parent / "directory"; directory.mkdir()
    ordinary(move.safe_move(str(directory), str(dst), expected_fingerprint=SourceFingerprint(0, 0),
                            allowed_roots=(str(src.parent),)), "SAFE_MOVE_UNSUPPORTED_METADATA")
    with src.open("r+b"):
        ordinary(invoke(src, dst), "SAFE_MOVE_SOURCE_BUSY")
    assert src.exists() and not dst.exists()


def test_held_source_and_parent_deny_replacement_write_and_rename(pair, monkeypatch):
    src, dst = pair
    original = move._rename
    witnesses = []
    def attempt(handle, parent, name):
        for operation in [lambda: os.rename(src, src.with_name("stolen.txt")),
                          lambda: src.write_bytes(b"UNAPPROVED"),
                          lambda: os.rename(src.parent, src.parent.with_name(src.parent.name + "-stolen"))]:
            try:
                operation()
            except OSError as error:
                witnesses.append((error.winerror, error.errno))
            else:
                witnesses.append("UNSAFE_SUCCESS")
        return original(handle, parent, name)
    monkeypatch.setattr(move, "_rename", attempt)
    approved = fingerprint(src)
    result = invoke(src, dst)
    assert len(witnesses) == 3 and all(type(code) is tuple and any(type(v) is int for v in code)
                                       for code in witnesses)
    success(result, dst, approved)
    assert dst.read_bytes() == b"SYNTHETIC_APPROVED"


def test_destination_inserted_at_publication_not_overwritten(pair, monkeypatch):
    src, dst = pair
    original = move._rename; witnesses = []
    def insert(handle, parent, name):
        dst.write_bytes(b"INSERTED")
        witnesses.append(dst.read_bytes())
        return original(handle, parent, name)
    monkeypatch.setattr(move, "_rename", insert)
    ordinary(invoke(src, dst), "SAFE_MOVE_TARGET_OCCUPIED")
    assert witnesses == [b"INSERTED"]
    assert src.read_bytes() == b"SYNTHETIC_APPROVED" and dst.read_bytes() == b"INSERTED"
    assert list(dst.parent.glob(".xuxia-move-*")) == []


@pytest.mark.parametrize("kind", ["stream", "hardlink"])
@pytest.mark.parametrize("cross", [False, True])
def test_actual_complex_metadata(pair, second_volume, kind, cross):
    src, dst = pair
    sibling = src.with_name("hardlink.txt")
    if kind == "stream":
        Path(str(src) + ":evidence").write_bytes(b"NAMED_STREAM")
    else:
        os.link(src, sibling)
    approved = fingerprint(src); identity = src.stat().st_ino
    if cross:
        dst = second_volume / "complex.txt"
    result = invoke(src, dst)
    if cross:
        ordinary(result, "SAFE_MOVE_CROSS_VOLUME_BLOCKED")
        assert result.source_fingerprint == approved and fingerprint(src) == approved
        assert src.read_bytes() == b"SYNTHETIC_APPROVED" and not dst.exists()
        data_path = src
    else:
        success(result, dst, approved)
        assert dst.stat().st_ino == identity
        data_path = dst
    if kind == "stream":
        assert Path(str(data_path) + ":evidence").read_bytes() == b"NAMED_STREAM"
    else:
        assert sibling.read_bytes() == b"SYNTHETIC_APPROVED" and sibling.stat().st_ino == identity


def test_actual_junction_ancestor_and_reparse_source(pair):
    src, dst = pair
    actual = src.parent / "actual"; actual.mkdir()
    nested = actual / "source.txt"; nested.write_bytes(b"JUNCTION_DATA")
    junction = src.parent / "junction"
    constructed = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(actual)],
                                 capture_output=True, check=False)
    assert constructed.returncode == 0, (constructed.returncode, constructed.stdout, constructed.stderr)
    try:
        ordinary(invoke(junction / nested.name, dst, roots=(str(src.parent),)),
                 "SAFE_MOVE_UNSUPPORTED_METADATA")
        ordinary(move.safe_move(str(junction), str(dst), expected_fingerprint=SourceFingerprint(0, 0),
                                allowed_roots=(str(src.parent),)), "SAFE_MOVE_UNSUPPORTED_METADATA")
        assert nested.read_bytes() == b"JUNCTION_DATA" and not dst.exists()
    finally:
        # rmdir removes this exact owned junction, never recursively traverses it.
        os.rmdir(junction)
    assert actual.is_dir() and nested.exists()


def test_same_volume_rename_before_raise_is_recovery(pair, monkeypatch):
    src, dst = pair; real = move._rename; witnesses = []
    def rename_then_raise(*args):
        real(*args); witnesses.append(True)
        raise OSError(5, "after mutation")
    monkeypatch.setattr(move, "_rename", rename_then_raise)
    result = invoke(src, dst)
    assert witnesses == [True]
    recovery(result)
    assert not src.exists() and dst.read_bytes() == b"SYNTHETIC_APPROVED"
    assert str(dst) in result.owned_residue_paths


def test_r1_reentrant_admission_is_bounded_and_opens_no_second_transaction(pair, monkeypatch):
    src, dst = pair
    real_nt, real_open = move._nt_set, move._open
    opened, witnesses = [], []
    def open_file(*args, **kwargs):
        opened.append(args)
        return real_open(*args, **kwargs)
    def nt(*args):
        before = len(opened)
        nested = move.safe_move(str(src.with_name("nested.txt")), str(dst.with_name("nested-dst.txt")),
                                expected_fingerprint=SourceFingerprint(1, 1), allowed_roots=(str(src.parent),))
        witnesses.append((nested, len(opened) - before))
        return real_nt(*args)
    monkeypatch.setattr(move, "_open", open_file)
    monkeypatch.setattr(move, "_nt_set", nt)
    approved = fingerprint(src)
    success(invoke(src, dst), dst, approved)
    assert len(witnesses) == 1 and witnesses[0][1] == 0
    ordinary(witnesses[0][0], "SAFE_MOVE_MOVE_FAILED")
    assert move._OWNER.active is None and move._OWNER.quarantine is None


def test_r1_definitive_negative_unwritten_iosb_frees_exact_single_allocation(pair, monkeypatch):
    src, dst = pair
    allocations, freed = [], []
    alloc, free = move._heap_alloc, move._heap_free
    def allocate(amount):
        pointer = alloc(amount)
        allocations.append((pointer, amount))
        return pointer
    def release(pointer):
        freed.append(pointer)
        return free(pointer)
    monkeypatch.setattr(move, "_heap_alloc", allocate)
    monkeypatch.setattr(move, "_heap_free", release)
    renames = []
    def reject(*args):
        renames.append((move._OWNER.active.requests[-1].pointer, allocations[-1][1]))
        return ctypes.c_int32(0xC0000035).value
    monkeypatch.setattr(move, "_nt_set", reject)
    ordinary(invoke(src, dst), "SAFE_MOVE_TARGET_OCCUPIED")
    assert len(renames) == 1
    assert 0 < renames[0][1] <= 1024
    assert all(0 < amount <= 2048 for pointer, amount in allocations)
    assert [pointer for pointer, amount in allocations] == freed
    assert move._OWNER.quarantine is None
    assert src.read_bytes() == b"SYNTHETIC_APPROVED" and not dst.exists()


def test_repeated_transactions_release_native_handles(tmp_path, second_volume):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.GetProcessHandleCount.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.GetProcessHandleCount.restype = ctypes.c_int
    def count():
        value = ctypes.c_ulong()
        assert kernel.GetProcessHandleCount(kernel.GetCurrentProcess(), ctypes.byref(value))
        return value.value
    before = count()
    for index in range(25):
        src = tmp_path / f"source-{index}.txt"; src.write_bytes(b"SOURCE")
        cross_dst = second_volume / f"target-{index}.txt"; cross_dst.write_bytes(b"OCCUPIED")
        ordinary(invoke(src, cross_dst), "SAFE_MOVE_CROSS_VOLUME_BLOCKED")
        assert src.read_bytes() == b"SOURCE" and cross_dst.read_bytes() == b"OCCUPIED"
        dst = tmp_path / f"same-target-{index}.txt"; dst.write_bytes(b"OCCUPIED")
        ordinary(invoke(src, dst), "SAFE_MOVE_TARGET_OCCUPIED")
        dst.unlink()  # Owned test fixture, after the transaction released its handles.
        approved = fingerprint(src)
        success(invoke(src, dst), dst, approved)
        assert not src.exists() and dst.read_bytes() == b"SOURCE"
    after = count()
    # pytest/runtime may lazily allocate a few handles; a linear transaction leak cannot fit 4.
    assert after <= before + 4, (before, after)


def _evidence_identity():
    from src.core import rename_plan as values
    assert hasattr(values, "NativeFileIdentity"), "native identity contract missing"
    return values.NativeFileIdentity


def test_native_identity_only_preserves_edits(tmp_path):
    src, target, restored = tmp_path/"one.txt", tmp_path/"two.txt", tmp_path/"three.txt"
    src.write_bytes(b"FIRST_SYNTHETIC")
    first = invoke(src, target)
    assert first.success
    assert getattr(first, "source_identity", None) is not None, "held identity not returned"
    target.write_bytes(b"LEGITIMATE_SAME_FILE_EDIT")
    expected = fingerprint(target)
    second = move.safe_move(str(target), str(restored), expected_identity=first.source_identity,
                            allowed_roots=(str(tmp_path),))
    success(second, restored, expected)
    assert (second.source_identity.volume_serial, second.source_identity.file_index) == (
        first.source_identity.volume_serial, first.source_identity.file_index)
    assert restored.read_bytes() == b"LEGITIMATE_SAME_FILE_EDIT"
    assert not src.exists() and not target.exists()


@pytest.mark.parametrize("occupied", [False, True])
def test_native_capture_is_actual_held_info(pair, monkeypatch, occupied):
    identity = _evidence_identity()
    src, dst = pair
    if occupied: dst.write_bytes(b"OCCUPIED")
    real, witnesses = move._info, []
    def observed(handle):
        info = real(handle)
        if not info.attributes & (move._DIRECTORY | move._REPARSE) and info.fingerprint.size_bytes:
            witnesses.append(info)
        return info
    monkeypatch.setattr(move, "_info", observed)
    approved = fingerprint(src)
    result = invoke(src, dst)
    assert witnesses
    captured = witnesses[0] if occupied else witnesses[-1]
    assert result.source_identity == identity(captured.volume, captured.index, captured.creation)
    assert result.source_fingerprint == captured.fingerprint == approved
    if occupied:
        ordinary(result, "SAFE_MOVE_TARGET_OCCUPIED")
        assert src.read_bytes() == b"SYNTHETIC_APPROVED" and dst.read_bytes() == b"OCCUPIED"
    else:
        success(result, dst, approved)


@pytest.mark.parametrize("wrong", ["index", "creation"])
def test_identity_mismatch_before_guard_or_target_descendants(pair, monkeypatch, wrong):
    identity = _evidence_identity()
    src, _ = pair
    dst = src.parent/"absent"/"nested"/"target.txt"
    source = move._open(str(src))
    try: actual = move._info(source)
    finally: move._close(source)
    actions = []
    def forbidden(*args, **kwargs):
        actions.append(True)
        raise OSError("Guard/target mutation forbidden before identity admission")
    monkeypatch.setattr(move._Transaction, "guard", forbidden)
    monkeypatch.setattr(move, "_rename", forbidden)
    result = move.safe_move(str(src), str(dst), expected_identity=identity(
        actual.volume, actual.index ^ (wrong == "index"), actual.creation ^ (wrong == "creation")),
                            allowed_roots=(str(src.parent),))
    ordinary(result, "SAFE_MOVE_SOURCE_CHANGED")
    assert result.source_identity == identity(actual.volume, actual.index, actual.creation)
    assert actions == [] and not dst.parent.parent.exists()
    assert src.read_bytes() == b"SYNTHETIC_APPROVED"


def test_real_same_size_mtime_replacement_cannot_pass_historical_identity(pair):
    _evidence_identity()
    src, target = pair
    original = fingerprint(src)
    first = invoke(src, target)
    assert first.success
    assert getattr(first, "source_identity", None) is not None, "held identity not returned"
    retained = target.with_name("retained-original.txt")
    os.rename(target, retained)
    target.write_bytes(b"REPLACEMENT_BYTES!")  # Same length as SYNTHETIC_APPROVED.
    assert target.stat().st_size == original.size_bytes
    os.utime(target, ns=(target.stat().st_atime_ns, original.mtime_ns))
    assert fingerprint(target) == original and retained.stat().st_ino != target.stat().st_ino
    restored = target.with_name("restored.txt")
    result = move.safe_move(str(target), str(restored), expected_identity=first.source_identity,
                            allowed_roots=(str(src.parent),))
    ordinary(result, "SAFE_MOVE_SOURCE_CHANGED")
    assert result.source_identity != first.source_identity
    assert retained.read_bytes() == b"SYNTHETIC_APPROVED" and target.read_bytes() == b"REPLACEMENT_BYTES!"
    assert not restored.exists() and list(src.parent.glob(".xuxia-move-*")) == []


@pytest.mark.parametrize("bad_kind", ["neither", "identity-bool", "identity-tampered", "identity-subclass", "fingerprint-bad"])
def test_invalid_proofs_zero_native_actions(monkeypatch, bad_kind):
    identity = _evidence_identity()
    class Identity(identity): pass
    valid = identity(1, 2, 3)
    if bad_kind == "identity-tampered": object.__setattr__(valid, "creation_ticks", True)
    if bad_kind == "identity-subclass":
        valid = object.__new__(Identity)
        for field, value in (("volume_serial", 1), ("file_index", 2), ("creation_ticks", 3)):
            object.__setattr__(valid, field, value)
    proofs = {"expected_identity": valid}
    if bad_kind == "neither": proofs = {}
    elif bad_kind == "identity-bool": proofs = {"expected_identity": True, "expected_fingerprint": SourceFingerprint(1, 1)}
    elif bad_kind == "fingerprint-bad": proofs["expected_fingerprint"] = SourceFingerprint(True, 1)
    actions = []
    def forbidden(*args, **kwargs):
        actions.append(True)
        raise AssertionError("Invalid proof must not reach native boundary")
    for name in ("_open", "_nt_create", "_heap_alloc", "_rename"):
        monkeypatch.setattr(move, name, forbidden)
    result = move.safe_move("C:/approved/source.txt", "C:/approved/dest.txt",
                            allowed_roots=("C:/approved",), **proofs)
    ordinary(result, "SAFE_MOVE_INVALID_INPUT")
    assert result.source_identity is None and result.source_fingerprint is None and actions == []


@pytest.mark.parametrize("wrong", ["identity", "fingerprint", "neither"])
def test_both_proofs_independently_enforced(pair, monkeypatch, wrong):
    identity = _evidence_identity()
    src, dst = pair
    handle = move._open(str(src))
    try: info = move._info(handle)
    finally: move._close(handle)
    expected_identity = identity(info.volume, info.index ^ (wrong == "identity"), info.creation)
    expected_fingerprint = SourceFingerprint(info.fingerprint.size_bytes + (wrong == "fingerprint"), info.fingerprint.mtime_ns)
    published, rename = [], move._rename
    def observe(*args):
        rename(*args)
        published.append(move._info(args[0]))
    monkeypatch.setattr(move, "_rename", observe)
    result = move.safe_move(str(src), str(dst), expected_identity=expected_identity,
                            expected_fingerprint=expected_fingerprint, allowed_roots=(str(src.parent),))
    if wrong == "neither":
        success(result, dst, info.fingerprint)
        assert dst.read_bytes() == b"SYNTHETIC_APPROVED"
        assert len(published) == 1
        captured = published[0]
    else:
        ordinary(result, "SAFE_MOVE_SOURCE_CHANGED")
        assert src.read_bytes() == b"SYNTHETIC_APPROVED" and not dst.exists()
        assert published == []
        captured = info
    assert result.source_identity == identity(captured.volume, captured.index, captured.creation)


def test_controlled_creation_only_after_real_publication_captures_post_identity(pair, monkeypatch):
    """Controlled response classification, not an actual external metadata edit."""
    identity = _evidence_identity()
    src, dst = pair
    queried, published, witnesses = move._info, [], []
    rename = move._rename
    def actual_publish(*args):
        rename(*args)
        published.append(True)
    def info(handle):
        actual = queried(handle)
        if published and not actual.attributes & move._DIRECTORY and actual.fingerprint.size_bytes:
            from dataclasses import replace
            changed = replace(actual, creation=actual.creation ^ 1)
            witnesses.append(changed)
            return changed
        return actual
    monkeypatch.setattr(move, "_rename", actual_publish)
    monkeypatch.setattr(move, "_info", info)
    result = invoke(src, dst)
    assert published == [True] and len(witnesses) == 1
    success(result, dst, witnesses[0].fingerprint)
    assert not src.exists() and dst.read_bytes() == b"SYNTHETIC_APPROVED"
    assert result.source_identity == identity(witnesses[0].volume, witnesses[0].index, witnesses[0].creation)
    assert result.owned_residue_paths == ()
    assert list(src.parent.glob(".xuxia-move-*")) == []


@pytest.mark.parametrize("wrong", ["volume", "index", "size", "mtime"])
def test_controlled_held_postpublication_mismatch_is_recovery(pair, monkeypatch, wrong):
    """Fault injection after real rename; locks, publication and bytes are native."""
    identity = _evidence_identity()
    src, dst = pair
    queried, rename, published, witnesses, admitted = move._info, move._rename, [], [], []
    def actual_publish(handle, *args):
        admitted.append(queried(handle))
        rename(handle, *args)
        published.append(True)
    def query(handle):
        actual = queried(handle)
        if published and not actual.attributes & move._DIRECTORY and actual.fingerprint.size_bytes:
            from dataclasses import replace
            changes = {"volume": {"volume": actual.volume ^ 1}, "index": {"index": actual.index ^ 1},
                "size": {"fingerprint": SourceFingerprint(actual.fingerprint.size_bytes + 1, actual.fingerprint.mtime_ns)},
                "mtime": {"fingerprint": SourceFingerprint(actual.fingerprint.size_bytes, actual.fingerprint.mtime_ns + 100)}}
            changed = replace(actual, **changes[wrong])
            witnesses.append((actual, changed))
            return changed
        return actual
    monkeypatch.setattr(move, "_rename", actual_publish)
    monkeypatch.setattr(move, "_info", query)
    result = invoke(src, dst)
    assert published == [True] and len(witnesses) == 1 and len(admitted) == 1
    recovery(result)
    assert not src.exists() and dst.read_bytes() == b"SYNTHETIC_APPROVED"
    assert set(result.owned_residue_paths) == {str(src), str(dst)}
    assert result.source_identity == identity(admitted[0].volume, admitted[0].index, admitted[0].creation)
    assert result.source_fingerprint == admitted[0].fingerprint
    assert list(src.parent.glob(".xuxia-move-*")) == []


def test_real_deleted_names_forward_and_identity_only_reverse_capture_post(tmp_path, monkeypatch, capsys):
    """25 native forward + 25 reverse moves; no mandatory tunneling count/skip."""
    identity = _evidence_identity()
    witnesses, admissions, real, queried, opened = [], [], move._rename, move._info, move._Transaction.open_child
    pending_admission = []
    def open_source(transaction, parent, name, **kwargs):
        handle = opened(transaction, parent, name, **kwargs)
        if not kwargs.get("directory") and name.startswith(("source-", "target-")):
            pending_admission.append(handle)
        return handle
    def query(handle):
        info = queried(handle)
        if pending_admission and handle == pending_admission[0]:
            admissions.append(info)
            pending_admission.pop(0)
        return info
    def observed(handle, parent, name):
        before = queried(handle)
        real(handle, parent, name)
        after = queried(handle)
        witnesses.append((before, after))
    monkeypatch.setattr(move._Transaction, "open_child", open_source)
    monkeypatch.setattr(move, "_info", query)
    monkeypatch.setattr(move, "_rename", observed)
    forward, reverse = [], []
    pairs = []
    for index in range(25):
        src, dst = tmp_path/f"source-{index}.txt", tmp_path/f"target-{index}.txt"
        src.write_bytes(b"SOURCE")
        dst.write_bytes(b"OCCUPIED")
        dst.unlink()
        forward.append(invoke(src, dst))
        pairs.append((src, dst))
        assert not src.exists() and dst.read_bytes() == b"SOURCE"
    for (src, dst), first in zip(pairs, forward):
        reverse.append(move.safe_move(str(dst), str(src), expected_identity=first.source_identity,
                                       allowed_roots=(str(tmp_path),)))
        assert reverse[-1].success, f"Returned forward POST proof must admit reverse: {first!r}, {reverse[-1]!r}"
        assert src.read_bytes() == b"SOURCE" and not dst.exists()
    forward_changes = sum(before.creation != after.creation for before, after in witnesses[:25])
    reverse_changes = sum(before.creation != after.creation for before, after in witnesses[25:])
    with capsys.disabled():
        print(f"EVIDENCE_CREATION_REVISION forward_changes={forward_changes} reverse_changes={reverse_changes} "
              f"forward={forward!r} reverse={reverse!r} admissions={admissions!r} held_before_after={witnesses!r}")
    assert len(witnesses) == len(admissions) == 50 and pending_admission == []
    assert all(before.volume == after.volume and before.index == after.index
               and before.fingerprint == after.fingerprint for before, after in witnesses)
    assert all(admission == before for admission, (before, after) in zip(admissions, witnesses))
    for result, (before, after) in zip(forward + reverse, witnesses):
        assert result.success and not result.recovery_required and result.owned_residue_paths == ()
        assert result.source_identity == identity(after.volume, after.index, after.creation)
        assert result.source_fingerprint == after.fingerprint
    for first, admission in zip(forward, admissions[25:]):
        assert first.source_identity == identity(admission.volume, admission.index, admission.creation)
    assert list(tmp_path.glob(".xuxia-move-*")) == []
    for src, dst in pairs:
        src.unlink()  # Test-owned fixture after proven normal resource release.
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("proof_kind,field", [
    ("identity", "volume_serial"), ("identity", "file_index"), ("identity", "creation_ticks"),
    ("fingerprint", "size_bytes"), ("fingerprint", "mtime_ns"),
    ("identity", None), ("fingerprint", None),
])
@pytest.mark.parametrize("with_good_other_proof", [False, True])
def test_incomplete_supplied_proofs_invalid_input_zero_native_actions(monkeypatch, proof_kind, field, with_good_other_proof):
    identity = _evidence_identity()
    proof = identity(1, 2, 3) if proof_kind == "identity" else SourceFingerprint(1, 1)
    if field is None:
        proof = object.__new__(type(proof))
    else:
        object.__delattr__(proof, field)
    kwargs = {"expected_identity" if proof_kind == "identity" else "expected_fingerprint": proof}
    if with_good_other_proof:
        kwargs["expected_fingerprint" if proof_kind == "identity" else "expected_identity"] = (
            SourceFingerprint(1, 1) if proof_kind == "identity" else identity(1, 2, 3))
    actions = []
    def forbidden(*args, **kwargs):
        actions.append(True)
        raise AssertionError("Malformed proof must not reach native ownership or I/O")
    for name in ("_Transaction", "_open", "_nt_create", "_heap_alloc", "_rename"):
        monkeypatch.setattr(move, name, forbidden)
    result = move.safe_move("C:/approved/source.txt", "C:/approved/dest.txt",
                            allowed_roots=("C:/approved",), **kwargs)
    ordinary(result, "SAFE_MOVE_INVALID_INPUT")
    assert result.source_identity is None and result.source_fingerprint is None and actions == []

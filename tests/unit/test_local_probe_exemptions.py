"""Fake-native tests: no real firewall, heap, or SID APIs may be loaded."""
import ctypes as C
from ctypes import wintypes as W
import importlib.util
from pathlib import Path
import sys

import pytest


PATH = Path(__file__).resolve().parents[2] / "src" / "services" / "local_ai" / "native" / "exemptions.py"
SID = "S-1-15-2-1-2-3-4-5-6-7"
OTHER = "S-1-15-2-1-2-3-4-5-6-8"


def sid_bytes(text):
    return bytes([1, 8, 0, 0, 0, 0, 0, 15]) + b"".join(
        int(part).to_bytes(4, "little") for part in text.split("-")[3:])


@pytest.fixture
def module(monkeypatch):
    monkeypatch.setattr(C, "WinDLL", lambda *a, **k: pytest.fail("real DLL loaded"), raising=False)
    assert PATH.is_file(), "exemption helper not implemented"
    spec = importlib.util.spec_from_file_location("local_probe_exemptions", PATH)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = obj
    spec.loader.exec_module(obj)
    monkeypatch.setattr(obj, "_Bindings", lambda: pytest.fail("bindings initialized"), raising=False)
    return obj


class FakeApi:
    def __init__(self, module, sids=()):
        self.module = module
        self.sids = sids
        self.calls = []
        self.buffers = []
        self.live = {}
        self.status = 0
        self.bad_count = None
        self.bad_pointer = None
        self.fail_free = set()
        self.fail_convert = False
        self.raise_after_query_output = False
        self.raise_after_target_output = False
        self.mismatched_target = False
        self.fail_heap = False

    def alloc(self, label, data):
        buf = C.create_string_buffer(data)
        self.buffers.append(buf)
        ptr = C.addressof(buf)
        self.live[ptr] = label
        return ptr

    def ConvertStringSidToSidW(self, text, out):
        self.calls.append("convert")
        if self.fail_convert:
            C.set_last_error(8)
            return False
        C.cast(out, C.POINTER(C.c_void_p))[0] = self.alloc(
            "target", sid_bytes(OTHER if self.mismatched_target else text))
        if self.raise_after_target_output:
            raise RuntimeError("private target detail")
        return True

    def LocalFree(self, ptr):
        self.calls.append("local_free")
        assert self.live[ptr] == "target"
        if "target" in self.fail_free:
            C.set_last_error(6)
            return ptr
        del self.live[ptr]
        return None

    def NetworkIsolationGetAppContainerConfig(self, count, outer):
        self.calls.append("query")
        C.cast(count, C.POINTER(W.DWORD))[0] = len(self.sids) if self.bad_count is None else self.bad_count
        if self.sids:
            entries = (self.module.SID_AND_ATTRIBUTES * len(self.sids))()
            for i, sid in enumerate(self.sids):
                entries[i].Sid = self.alloc(f"sid{i}", sid_bytes(sid) if isinstance(sid, str) else sid)
            self.buffers.append(entries)
            pointer = C.addressof(entries)
            self.live[pointer] = "outer"
        else:
            pointer = None
        C.cast(outer, C.POINTER(C.c_void_p))[0] = pointer if self.bad_pointer is None else self.bad_pointer
        if self.raise_after_query_output:
            raise RuntimeError("private native detail")
        C.set_last_error(999)
        return self.status

    def IsValidSid(self, ptr):
        self.calls.append("valid")
        return C.string_at(ptr, 2) == bytes([1, 8])

    def EqualSid(self, left, right):
        self.calls.append("equal")
        return C.string_at(left, 40) == C.string_at(right, 40)

    def GetProcessHeap(self):
        self.calls.append("heap")
        if self.fail_heap:
            raise RuntimeError("private heap detail")
        return 123

    def HeapFree(self, heap, flags, ptr):
        assert heap == 123 and flags == 0
        label = self.live[ptr]
        self.calls.append(f"free:{label}")
        if label in self.fail_free:
            C.set_last_error(6)
            return False
        del self.live[ptr]
        return True


@pytest.fixture
def fake(module, monkeypatch):
    api = FakeApi(module)
    monkeypatch.setattr(module, "_api", api, raising=False)
    return api


def test_import_and_constructor_have_no_native_effects(module, fake):
    owner = module.OwnedLoopbackExemptionQuery(SID)
    assert fake.calls == []
    owner.close()
    assert fake.calls == []


@pytest.mark.parametrize("bad", [None, b"x", "", SID + "-8", SID + " ",
                                   "S-1-15-2-4294967296-2-3-4-5-6-7"])
def test_invalid_target_rejected_before_native_calls(module, fake, bad):
    with pytest.raises(module.ExemptionError) as exc:
        module.OwnedLoopbackExemptionQuery(bad)
    assert exc.value.stage == "sid_input"
    assert fake.calls == []


@pytest.mark.parametrize("sids,expected", [((), False), ((OTHER,), False), ((OTHER, SID), True)])
def test_exact_identity_and_completed_cleanup(module, fake, sids, expected):
    fake.sids = sids
    owner = module.OwnedLoopbackExemptionQuery(SID)
    result = owner.query()
    assert result.package_sid == SID
    assert result.exempt is expected
    assert result.count == len(sids)
    assert result.cleanup_complete is True
    assert not fake.live
    assert fake.calls.index("query") < fake.calls.index("local_free")
    for index in range(len(sids)):
        assert fake.calls.index(f"free:sid{index}") < fake.calls.index("free:outer")
    if expected:
        with pytest.raises(module.ExemptionError) as exc:
            owner.require_not_exempt()
        assert exc.value.stage == "target_exempt"
    else:
        assert owner.require_not_exempt() == result


def test_direct_status_not_stale_last_error(module, fake):
    assert module.OwnedLoopbackExemptionQuery(SID).query().exempt is False
    fake.status = 5
    with pytest.raises(module.ExemptionError) as exc:
        module.OwnedLoopbackExemptionQuery(SID).query()
    assert (exc.value.stage, exc.value.code) == ("query", 5)


@pytest.mark.parametrize("count,pointer,retained", [(4097, None, False), (1, 0, False),
                                                    (0, 1, True), (1, 1, True)])
def test_untrustworthy_layout_is_not_dereferenced_or_freed(module, fake, count, pointer, retained):
    fake.bad_count, fake.bad_pointer = count, pointer
    owner = module.OwnedLoopbackExemptionQuery(SID)
    with pytest.raises(module.ExemptionError) as exc:
        owner.query()
    assert exc.value.stage == "query_layout"
    assert not any(x.startswith("free:") for x in fake.calls)
    if retained:
        with pytest.raises(module.ExemptionError):
            owner.close()
    else:
        owner.close()


@pytest.mark.parametrize("bad_count", [0, 4097])
def test_allocated_outer_with_inconsistent_count_is_quarantined(module, fake, bad_count):
    fake.sids = (OTHER,)
    fake.bad_count = bad_count
    owner = module.OwnedLoopbackExemptionQuery(SID)
    with pytest.raises(module.ExemptionError) as exc:
        owner.query()
    assert exc.value.stage == "query_layout"
    outer_addresses = [address for address, label in fake.live.items() if label == "outer"]
    assert len(outer_addresses) == 1
    assert owner._quarantined_output == (bad_count, outer_addresses[0])
    assert "sid0" in fake.live.values()
    assert "valid" in fake.calls  # target only; do not inspect returned entry
    assert fake.calls.count("valid") == 1
    assert "equal" not in fake.calls
    assert not any(call.startswith("free:") for call in fake.calls)
    with pytest.raises(module.ExemptionError) as blocked:
        owner.require_not_exempt()
    assert blocked.value.stage == "context_state"
    with pytest.raises(module.ExemptionError) as close_error:
        owner.close()
    assert close_error.value.stage == "query_layout"
    assert owner._quarantined_output == (bad_count, outer_addresses[0])


def test_invalid_sid_rejected_and_trusted_allocations_released(module, fake):
    fake.sids = (bytes([2, 8]) + sid_bytes(OTHER)[2:],)
    owner = module.OwnedLoopbackExemptionQuery(SID)
    with pytest.raises(module.ExemptionError) as exc:
        owner.query()
    assert exc.value.stage == "entry_sid"
    assert not fake.live


def test_free_failure_retains_owner_and_retries_without_double_free(module, fake):
    fake.sids = (OTHER, SID)
    fake.fail_free.add("sid0")
    owner = module.OwnedLoopbackExemptionQuery(SID)
    with pytest.raises(module.ExemptionError) as exc:
        owner.query()
    assert exc.value.stage == "heap_free"
    assert "outer" in fake.live.values()
    assert "sid1" not in fake.live.values()
    assert fake.calls.count("free:sid1") == 1
    fake.fail_free.clear()
    owner.close()
    assert not fake.live
    assert fake.calls.count("free:sid1") == 1
    assert fake.calls[-1] == "free:outer"


def test_multiple_free_failures_can_retry_independently(module, fake):
    fake.sids = (OTHER, SID)
    fake.fail_free.update(("sid0", "sid1", "target"))
    owner = module.OwnedLoopbackExemptionQuery(SID)
    with pytest.raises(module.ExemptionError):
        owner.query()
    assert set(fake.live.values()) == {"sid0", "sid1", "outer", "target"}
    fake.fail_free.clear()
    owner.close()
    assert not fake.live


def test_target_allocation_failure_prevents_query(module, fake):
    fake.fail_convert = True
    owner = module.OwnedLoopbackExemptionQuery(SID)
    with pytest.raises(module.ExemptionError) as exc:
        owner.query()
    assert exc.value.stage == "sid_convert"
    assert "query" not in fake.calls


def test_partial_target_allocation_is_released_without_query(module, fake):
    fake.raise_after_target_output = True
    owner = module.OwnedLoopbackExemptionQuery(SID)
    with pytest.raises(module.ExemptionError) as exc:
        owner.query()
    assert exc.value.stage == "sid_convert"
    assert fake.live == {}
    assert "query" not in fake.calls
    assert "private" not in str(exc.value)


def test_query_exception_after_output_still_releases_owned_array(module, fake):
    fake.sids = (OTHER,)
    fake.raise_after_query_output = True
    owner = module.OwnedLoopbackExemptionQuery(SID)
    with pytest.raises(module.ExemptionError) as exc:
        owner.query()
    assert exc.value.stage == "query"
    assert fake.live == {}


def test_pointer_width_layout_matches_native_structure(module):
    pointer_size = C.sizeof(C.c_void_p)
    assert module.SID_AND_ATTRIBUTES.Sid.offset == 0
    assert module.SID_AND_ATTRIBUTES.Attributes.offset == pointer_size
    assert C.sizeof(module.SID_AND_ATTRIBUTES) == pointer_size * 2


def test_conversion_must_preserve_canonical_target_identity(module, fake):
    fake.mismatched_target = True
    owner = module.OwnedLoopbackExemptionQuery(SID)
    with pytest.raises(module.ExemptionError) as exc:
        owner.query()
    assert exc.value.stage == "sid_validate"
    assert "query" not in fake.calls
    assert not fake.live


def test_heap_handle_error_still_releases_target_and_allows_retry(module, fake):
    fake.sids = (OTHER,)
    fake.fail_heap = True
    owner = module.OwnedLoopbackExemptionQuery(SID)
    with pytest.raises(module.ExemptionError) as exc:
        owner.query()
    assert exc.value.stage == "process_heap"
    assert "target" not in fake.live.values()
    fake.fail_heap = False
    owner.close()
    assert not fake.live

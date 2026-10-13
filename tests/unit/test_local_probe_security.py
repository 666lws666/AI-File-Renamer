"""Token-helper unit tests; fake success is NOT AppContainer/network proof."""
import ctypes as C
from ctypes import wintypes as W
import importlib.util
from pathlib import Path
import sys

import pytest


MODULE = Path(__file__).resolve().parents[2] / "src" / "services" / "local_ai" / "native" / "security.py"
SID = "S-1-15-2-1-2-3-4-5-6-7"


def test_module_contract_exists():
    assert MODULE.is_file(), "token foundation has not been implemented"


@pytest.fixture
def security():
    assert MODULE.is_file(), "token foundation has not been implemented"
    spec = importlib.util.spec_from_file_location("local_probe_security", MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("value", [
    None, 1, b"S-1-15-2-1-2-3-4-5-6-7", "", "AC", "S-1-15-2-1",
    "S-1-15-2", "S-1-5-21-1-2-3-4", "S-1-15-3-1-2-3-4-5-6-7",
    SID + "-8", SID[:-2], SID + " ", " " + SID, SID + "\0",
    SID.replace("-7", "--7"), SID.replace("-7", "-07"),
    SID.replace("-7", "-4294967296"), SID.lower(),
])
def test_invalid_identity_has_no_native_calls(security, monkeypatch, value):
    class NoCalls:
        def __getattr__(self, name):
            pytest.fail("invalid SID must not invoke a native API")
    monkeypatch.setattr(security, "_api", NoCalls())
    with pytest.raises(security.SecurityContextError) as caught:
        security.AppContainerSecurity(value)
    assert caught.value.stage == "sid_input"
    assert caught.value.win32_error == 87
    assert str(caught.value) == "sid_input (87)"


def sid_bytes(value=SID):
    parts = [int(part) for part in value.split("-")[1:]]
    return bytes([parts[0], len(parts) - 2]) + parts[1].to_bytes(6, "big") + b"".join(
        part.to_bytes(4, "little") for part in parts[2:])


def put(pointer, ctype, value):
    C.cast(pointer, C.POINTER(ctype))[0] = value


class FakeApi:
    """Only Win32 boundary is simulated; buffers and helper parsing are real."""
    def __init__(self, fault=None):
        self.fault = fault
        self.allocated, self.freed, self.closed = [], [], []
        self.queries, self.validations = [], []

    def ConvertStringSidToSidW(self, value, out):
        if self.fault == "convert":
            C.set_last_error(5)
            return False
        if self.fault == "convert_null":
            return True
        buf = C.create_string_buffer(sid_bytes(value))
        self.allocated.append(buf)
        put(out, C.c_void_p, C.addressof(buf))
        return True

    def IsValidSid(self, pointer):
        self.validations.append(pointer)
        return self.fault != "invalid_sid"

    def EqualSid(self, left, right):
        return self.fault != "wrong_sid" and C.string_at(left, 40) == C.string_at(right, 40)

    def LocalFree(self, pointer):
        if self.fault == "free":
            C.set_last_error(6)
            return pointer
        self.freed.append(pointer)
        return None

    def OpenProcessToken(self, process, access, out):
        assert process == 123 and access == 8
        if self.fault == "open":
            C.set_last_error(5)
            return False
        put(out, W.HANDLE, 456)
        return True

    def CloseHandle(self, handle):
        self.closed.append(handle)
        if self.fault == "close":
            C.set_last_error(6)
            return False
        return True

    def GetTokenInformation(self, token, info, buffer, size, returned):
        assert token == 456
        self.queries.append((info, size))
        pointer_size = C.sizeof(C.c_void_p)
        needed = {29: 4, 31: pointer_size + 40, 30: 4}[info]
        if not buffer:
            if self.fault == "size_error":
                C.set_last_error(5)
                return False
            if self.fault == "size_success":
                return True
            needed = {"size_zero": 0, "size_huge": 65537}.get(self.fault, needed)
            put(returned, W.DWORD, needed)
            C.set_last_error(122)
            return False
        if self.fault == "fill_error":
            C.set_last_error(5)
            return False
        put(returned, W.DWORD, needed)
        if self.fault == "fill_zero":
            put(returned, W.DWORD, 0)
        if self.fault == "fill_overflow":
            put(returned, W.DWORD, size + 1)
        if info == 29:
            put(buffer, W.DWORD, 0 if self.fault == "not_container" else 1)
            if self.fault == "bool_two":
                put(buffer, W.DWORD, 2)
            if self.fault == "short_bool":
                put(returned, W.DWORD, 3)
        elif info == 30:
            put(buffer, W.DWORD, 1 if self.fault == "capabilities" else 0)
            if self.fault == "short_groups":
                put(returned, W.DWORD, 3)
        else:
            base = C.addressof(buffer)
            sid = base + pointer_size
            C.memmove(sid, sid_bytes(), 40)
            if self.fault == "null_sid":
                sid = 0
            elif self.fault == "outside_sid":
                sid = base + size
            elif self.fault == "before_sid":
                sid = base - 1
            elif self.fault == "overlap_sid":
                sid = base
            elif self.fault == "header_truncated":
                sid = base + size - 7
            elif self.fault == "extent_truncated":
                put(returned, W.DWORD, needed - 1)
            elif self.fault == "count_overflow":
                C.c_ubyte.from_address(sid + 1).value = 255
            elif self.fault == "revision_bad":
                C.c_ubyte.from_address(sid).value = 2
            put(buffer, C.c_void_p, sid)
            if self.fault == "short_sid_info":
                put(returned, W.DWORD, pointer_size - 1)
        return True


@pytest.fixture
def fake(security, monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(security, "_api", api)
    return api


def test_owned_zero_capability_abi_and_lifetime(security, fake):
    ctx = security.AppContainerSecurity(SID)
    with pytest.raises(security.SecurityContextError):
        _ = ctx.capabilities
    with ctx:
        caps = ctx.capabilities
        address = caps.AppContainerSid
        assert C.sizeof(caps) == (24 if C.sizeof(C.c_void_p) == 8 else 16)
        assert not caps.Capabilities and caps.CapabilityCount == caps.Reserved == 0
        assert C.string_at(address, 40) == sid_bytes()
        assert ctx.capabilities is caps and not fake.freed
        with pytest.raises(security.SecurityContextError):
            ctx.__enter__()
        result = ctx.verify_process(123)
        assert result == security.TokenEvidence(SID, True, 0)
        with pytest.raises(AttributeError):
            result.package_sid = "changed"
        assert caps.AppContainerSid == address
    assert fake.freed == [address] and fake.closed == [456]
    assert [item[0] for item in fake.queries] == [29, 29, 31, 31, 30, 30]
    assert caps.AppContainerSid is None
    ctx.close()
    assert fake.freed == [address]
    for operation in (ctx.__enter__, lambda: ctx.capabilities, lambda: ctx.verify_process(123)):
        with pytest.raises(security.SecurityContextError):
            operation()


@pytest.mark.parametrize("fault,stage", [
    ("convert", "sid_convert"), ("convert_null", "sid_convert"), ("invalid_sid", "sid_validate"),
])
def test_enter_failure_frees_any_allocation(security, fake, fault, stage):
    fake.fault = fault
    ctx = security.AppContainerSecurity(SID)
    with pytest.raises(security.SecurityContextError) as caught:
        ctx.__enter__()
    assert caught.value.stage == stage
    assert len(fake.freed) == len(fake.allocated)
    ctx.close()
    assert len(fake.freed) == len(fake.allocated)


@pytest.mark.parametrize("fault", [
    "open", "size_error", "size_success", "size_zero", "size_huge",
    "fill_error", "fill_zero", "fill_overflow", "not_container", "bool_two",
    "short_bool", "null_sid", "outside_sid", "before_sid", "overlap_sid",
    "header_truncated", "extent_truncated", "count_overflow", "revision_bad",
    "short_sid_info", "wrong_sid", "capabilities", "short_groups", "close",
])
def test_token_failure_never_returns_evidence(security, fake, fault):
    with security.AppContainerSecurity(SID) as ctx:
        fake.fault = fault
        with pytest.raises(security.SecurityContextError) as caught:
            ctx.verify_process(123)
        assert isinstance(caught.value.win32_error, int)
        assert str(caught.value) == f"{caught.value.stage} ({caught.value.win32_error})"
        assert fake.closed == ([] if fault == "open" else [456])
    assert len(fake.freed) == 1


@pytest.mark.parametrize("fault", ["null_sid", "outside_sid", "before_sid", "overlap_sid", "header_truncated", "extent_truncated", "count_overflow"])
def test_malformed_pointer_is_rejected_before_sid_api(security, fake, fault):
    with security.AppContainerSecurity(SID) as ctx:
        baseline = len(fake.validations)
        fake.fault = fault
        with pytest.raises(security.SecurityContextError):
            ctx.verify_process(123)
        assert len(fake.validations) == baseline


def test_failed_free_is_reported_and_can_be_retried_once(security, fake):
    ctx = security.AppContainerSecurity(SID).__enter__()
    fake.fault = "free"
    with pytest.raises(security.SecurityContextError) as caught:
        ctx.close()
    assert (caught.value.stage, caught.value.win32_error) == ("sid_free", 6)
    with pytest.raises(security.SecurityContextError):
        _ = ctx.capabilities
    fake.fault = None
    ctx.close()
    ctx.close()
    assert len(fake.freed) == 1


def test_windows_native_current_process_fails_closed(security):
    assert sys.platform == "win32", "native rejection must be verified on Windows"
    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = W.HANDLE
    with security.AppContainerSecurity(SID) as ctx:
        assert ctx.capabilities.AppContainerSid
        with pytest.raises(security.SecurityContextError) as caught:
            ctx.verify_process(kernel.GetCurrentProcess())
        assert caught.value.stage in {"token_is_appcontainer", "token_sid_mismatch"}
    # Rejection of our process is not successful sandbox creation.


@pytest.mark.parametrize("handle", [None, False, 0, -2, "123", 1 << (8 * C.sizeof(C.c_void_p))])
def test_invalid_process_handle_never_opens_token(security, fake, handle):
    with security.AppContainerSecurity(SID) as ctx:
        with pytest.raises(security.SecurityContextError) as caught:
            ctx.verify_process(handle)
        assert caught.value.stage == "process_handle"
    assert fake.closed == []


def test_no_use_before_entry_or_after_close_without_entry(security, fake):
    ctx = security.AppContainerSecurity(SID)
    with pytest.raises(security.SecurityContextError):
        ctx.verify_process(123)
    ctx.close()
    ctx.close()
    with pytest.raises(security.SecurityContextError):
        ctx.__enter__()
    assert not fake.allocated


@pytest.mark.parametrize("field,value", [("CapabilityCount", 1), ("Reserved", 1), ("AppContainerSid", 1)])
def test_mutated_abi_is_not_returned_or_verified(security, fake, field, value):
    with security.AppContainerSecurity(SID) as ctx:
        setattr(ctx.capabilities, field, value)
        for operation in (lambda: ctx.capabilities, lambda: ctx.verify_process(123)):
            with pytest.raises(security.SecurityContextError) as caught:
                operation()
            assert caught.value.stage == "context_modified"
        assert not fake.queries
    assert len(fake.freed) == 1


def test_native_exception_does_not_leak_its_text(security, fake, monkeypatch):
    def fail(*args):
        raise RuntimeError("synthetic-secret-must-not-appear")
    with security.AppContainerSecurity(SID) as ctx:
        monkeypatch.setattr(fake, "GetTokenInformation", fail)
        with pytest.raises(security.SecurityContextError) as caught:
            ctx.verify_process(123)
        assert str(caught.value) == "token_size (13)"
        assert caught.value.__suppress_context__
        assert fake.closed == [456]


def test_partial_open_failure_still_releases_returned_handle(security, fake, monkeypatch):
    def fail(process, access, out):
        put(out, W.HANDLE, 456)
        C.set_last_error(5)
        return False
    monkeypatch.setattr(fake, "OpenProcessToken", fail)
    with security.AppContainerSecurity(SID) as ctx:
        with pytest.raises(security.SecurityContextError) as caught:
            ctx.verify_process(123)
        assert (caught.value.stage, caught.value.win32_error) == ("token_open", 5)
    assert fake.closed == [456]


def test_null_successful_open_is_rejected(security, fake, monkeypatch):
    monkeypatch.setattr(fake, "OpenProcessToken", lambda *args: True)
    with security.AppContainerSecurity(SID) as ctx:
        with pytest.raises(security.SecurityContextError) as caught:
            ctx.verify_process(123)
        assert caught.value.stage == "token_open"
    assert fake.closed == [] and fake.queries == []


def test_conversion_failure_with_allocation_is_freed(security, fake, monkeypatch):
    convert = fake.ConvertStringSidToSidW
    def fail(value, out):
        convert(value, out)
        C.set_last_error(5)
        return False
    monkeypatch.setattr(fake, "ConvertStringSidToSidW", fail)
    with pytest.raises(security.SecurityContextError) as caught:
        with security.AppContainerSecurity(SID):
            pytest.fail("entry must fail")
    assert (caught.value.stage, caught.value.win32_error) == ("sid_convert", 5)
    assert len(fake.freed) == 1


@pytest.mark.parametrize("value", ["S-1-15-2-0-0-0-0-0-0-0", "S-1-15-2-4294967295-1-2-3-4-5-6"])
def test_canonical_uint32_boundaries_are_accepted(security, fake, value):
    with security.AppContainerSecurity(value) as ctx:
        assert C.string_at(ctx.capabilities.AppContainerSid, 40) == sid_bytes(value)
    assert len(fake.freed) == 1

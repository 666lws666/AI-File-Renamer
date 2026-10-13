"""Fake-boundary ownership checks only; NEVER invokes real profile APIs."""
import ctypes as C
from ctypes import wintypes as W
import importlib.util
from pathlib import Path
import sys

import pytest


MODULE = Path(__file__).resolve().parents[2] / "src" / "services" / "local_ai" / "native" / "profile.py"
NAME = "xuxia_probe_" + "0123456789abcdef" * 2
SID = "S-1-15-2-1-2-3-4-5-6-7"


@pytest.fixture(autouse=True)
def forbid_any_native_dll_loading(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("profile tests must not load a real native DLL")
    monkeypatch.setattr(C, "WinDLL", forbidden)


def test_module_contract_exists():
    assert MODULE.is_file(), "owned profile helper not implemented"


@pytest.fixture
def profile(monkeypatch):
    assert MODULE.is_file(), "owned profile helper not implemented"
    spec = importlib.util.spec_from_file_location("local_probe_profile", MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    def forbidden():
        pytest.fail("real native bindings must NEVER initialize in profile tests")
    monkeypatch.setattr(module, "_Bindings", forbidden)
    from scripts import local_probe_security
    monkeypatch.setattr(local_probe_security, "_Bindings", forbidden)
    return module


@pytest.mark.parametrize("value", [None, 1, b"bytes", "", "xuxia_probe_", NAME[:-1], NAME + "a",
    NAME.upper(), NAME + " ", " " + NAME, NAME + "\0", NAME.replace("a", "g"), "other_" + "a" * 32])
def test_invalid_names_rejected_without_binding(profile, value):
    with pytest.raises(profile.ProfileError) as caught:
        profile.OwnedAppContainerProfile(value)
    assert (caught.value.stage, caught.value.code) == ("profile_name", 87)
    assert str(caught.value) == "profile_name (87)"


def test_constructor_and_before_entry_close_have_no_side_effects(profile):
    ctx = profile.OwnedAppContainerProfile(NAME)
    for prop in ("name", "sid"):
        with pytest.raises(profile.ProfileError):
            getattr(ctx, prop)
    ctx.close()
    ctx.close()
    with pytest.raises(profile.ProfileError):
        ctx.__enter__()


class FakeApi:
    """Memory-real API fake. No function delegates to a native profile API."""
    def __init__(self):
        self.faults = {}
        self.calls = []
        self.live = {}
        self.freed = []
        self.buffers = []
        self.phase = None

    def allocate(self, out, label, text=None):
        if text is None:
            # SID revision/count/authority plus eight little-endian components.
            buf = C.create_string_buffer(bytes([1, 8, 0, 0, 0, 0, 0, 15]) + b"".join(
                part.to_bytes(4, "little") for part in [2, 1, 2, 3, 4, 5, 6, 7]))
        else:
            buf = C.create_unicode_buffer(text)
        self.buffers.append(buf)
        address = C.addressof(buf)
        self.live[address] = label
        C.cast(out, C.POINTER(C.c_void_p))[0] = address

    def DeriveAppContainerSidFromAppContainerName(self, name, out):
        assert name == NAME
        self.phase = "derive"
        self.calls.append(("derive", name))
        if not self.faults.get("derive_null"):
            self.allocate(out, "derive_sid")
        if self.faults.get("derive_exception"):
            raise RuntimeError("synthetic-secret")
        C.set_last_error(999)
        return self.faults.get("derive_hr", 0)

    def CreateAppContainerProfile(self, name, display, description, capabilities, count, out):
        assert name == NAME
        if name.startswith("xuxia_local_"):
            assert display == "Xuxia local private inference"
            assert description == "Local private inference profile; no network capabilities"
        else:
            assert display == "Xuxia local diagnostic probe"
            assert description == "Synthetic diagnostic profile; no network capabilities"
        assert capabilities is None and count == 0
        self.phase = "create"
        self.calls.append(("create", name))
        # Derivation allocations must be gone before any creation attempt.
        assert not any(label.startswith("derive") for label in self.live.values())
        if not self.faults.get("create_null"):
            self.allocate(out, "create_sid")
        if self.faults.get("create_exception"):
            raise RuntimeError("synthetic-secret")
        C.set_last_error(999)
        return self.faults.get("create_hr", 0)

    def ConvertSidToStringSidW(self, sid, out):
        assert self.live[sid] == self.phase + "_sid"
        self.calls.append(("convert", self.phase))
        if not self.faults.get(self.phase + "_string_null"):
            self.allocate(out, self.phase + "_string", self.faults.get(self.phase + "_text", SID))
        if self.faults.get(self.phase + "_convert_exception"):
            raise RuntimeError("synthetic-secret")
        if self.faults.get(self.phase + "_convert_error"):
            C.set_last_error(5)
            return False
        return True

    def FreeSid(self, pointer):
        label = self.live[pointer]
        assert label.endswith("_sid"), "FreeSid must not receive string allocations"
        self.calls.append(("FreeSid", label))
        if self.faults.get(label + "_exception"):
            raise RuntimeError("synthetic-free-secret")
        if self.faults.get(label + "_free"):
            return pointer
        self.freed.append(label)
        del self.live[pointer]
        return None

    def LocalFree(self, pointer):
        label = self.live[pointer]
        assert label.endswith("_string"), "LocalFree must not receive profile SIDs"
        self.calls.append(("LocalFree", label))
        if self.faults.get(label + "_exception"):
            raise RuntimeError("synthetic-free-secret")
        if self.faults.get(label + "_free"):
            C.set_last_error(6)
            return pointer
        self.freed.append(label)
        del self.live[pointer]
        return None

    def DeleteAppContainerProfile(self, name):
        assert name == NAME
        self.calls.append(("delete", name))
        if self.faults.get("delete_exception"):
            raise RuntimeError("synthetic-delete-secret")
        C.set_last_error(999)
        return self.faults.get("delete_hr", 0)


@pytest.fixture
def fake(profile, monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(profile, "_api", api)
    return api


def calls(fake, name):
    return [item for item in fake.calls if item[0] == name]


def test_success_owns_once_and_properties_are_read_only(profile, fake):
    ctx = profile.OwnedAppContainerProfile(NAME)
    assert fake.calls == []
    with ctx as entered:
        assert entered is ctx and ctx.name == NAME and ctx.sid == SID
        assert not fake.live and len(fake.freed) == 4
        assert len(calls(fake, "create")) == 1 and not calls(fake, "delete")
        with pytest.raises(profile.ProfileError):
            ctx.__enter__()
        for prop in ("name", "sid"):
            with pytest.raises(AttributeError):
                setattr(ctx, prop, "changed")
    assert calls(fake, "delete") == [("delete", NAME)]
    ctx.close()
    assert len(calls(fake, "delete")) == 1
    for operation in (ctx.__enter__, lambda: ctx.name, lambda: ctx.sid):
        with pytest.raises(profile.ProfileError):
            operation()


@pytest.mark.parametrize("hr", [0x800700B7, -2147024713])
def test_collision_never_adopts_or_deletes(profile, fake, hr):
    fake.faults["create_hr"] = hr
    ctx = profile.OwnedAppContainerProfile(NAME)
    with pytest.raises(profile.ProfileError) as caught:
        ctx.__enter__()
    assert (caught.value.stage, caught.value.code) == ("profile_create", 0x800700B7)
    assert not fake.live and not calls(fake, "delete")
    ctx.close()
    assert not calls(fake, "delete")


@pytest.mark.parametrize("fault,value,stage,code,created", [
    ("derive_hr", -2147024891, "profile_derive", 0x80070005, False),
    ("derive_hr", 0x80004005, "profile_derive", 0x80004005, False),
    ("derive_hr", 1, "profile_derive", 1, False),
    ("derive_null", True, "profile_sid", 13, False),
    ("derive_convert_error", True, "sid_string", 5, False),
    ("derive_string_null", True, "sid_string", 13, False),
    ("derive_text", "S-1-15-2-1", "sid_shape", 87, False),
    ("derive_exception", True, "profile_derive", 13, False),
    ("derive_convert_exception", True, "sid_string", 13, False),
    ("create_hr", -2147024891, "profile_create", 0x80070005, False),
    ("create_hr", 1, "profile_create", 1, False),
    ("create_exception", True, "profile_create", 13, False),
    ("create_null", True, "profile_sid", 13, True),
    ("create_convert_error", True, "sid_string", 5, True),
    ("create_convert_exception", True, "sid_string", 13, True),
    ("create_string_null", True, "sid_string", 13, True),
    ("create_text", "S-1-15-2-1", "sid_shape", 87, True),
    ("create_text", SID[:-1] + "8", "sid_identity", 13, True),
])
def test_failures_free_allocations_and_delete_only_after_s_ok(profile, fake, fault, value, stage, code, created):
    fake.faults[fault] = value
    ctx = profile.OwnedAppContainerProfile(NAME)
    with pytest.raises(profile.ProfileError) as caught:
        ctx.__enter__()
    assert (caught.value.stage, caught.value.code) == (stage, code)
    assert "synthetic-secret" not in str(caught.value)
    assert not fake.live
    assert len(calls(fake, "delete")) == int(created)
    ctx.close()
    assert len(calls(fake, "delete")) == int(created)


@pytest.mark.parametrize("phase,allocation", [("derive", "sid"), ("derive", "string"), ("create", "sid"), ("create", "string")])
def test_free_failure_is_reported_retained_and_explicitly_retried(profile, fake, phase, allocation):
    key = phase + "_" + allocation + "_free"
    fake.faults[key] = True
    ctx = profile.OwnedAppContainerProfile(NAME)
    with pytest.raises(profile.ProfileError) as caught:
        ctx.__enter__()
    assert caught.value.stage == ("sid_free" if allocation == "sid" else "string_free")
    assert list(fake.live.values()) == [phase + "_" + allocation]
    assert len(calls(fake, "delete")) == int(phase == "create")
    fake.faults.clear()
    ctx.close()
    ctx.close()
    assert not fake.live
    assert len(calls(fake, "delete")) == int(phase == "create")


@pytest.mark.parametrize("hr", [-2147024891, 0x80070005, 1])
def test_failed_delete_retains_ownership_for_explicit_retry(profile, fake, hr):
    ctx = profile.OwnedAppContainerProfile(NAME).__enter__()
    fake.faults["delete_hr"] = hr
    with pytest.raises(profile.ProfileError) as caught:
        ctx.close()
    assert (caught.value.stage, caught.value.code) == ("profile_delete", hr & 0xFFFFFFFF)
    for prop in ("name", "sid"):
        with pytest.raises(profile.ProfileError):
            getattr(ctx, prop)
    fake.faults.clear()
    ctx.close()
    ctx.close()
    assert len(calls(fake, "delete")) == 2


def test_failed_creation_validation_with_failed_cleanup_retains_exact_owner(profile, fake):
    fake.faults.update(create_null=True, delete_hr=0x80070005)
    ctx = profile.OwnedAppContainerProfile(NAME)
    with pytest.raises(profile.ProfileError) as caught:
        ctx.__enter__()
    assert caught.value.stage == "profile_delete"
    assert len(calls(fake, "create")) == len(calls(fake, "delete")) == 1
    fake.faults.clear()
    ctx.close()
    assert calls(fake, "delete") == [("delete", NAME), ("delete", NAME)]


def test_journal_persist_exception_still_cleans_live_owned_profile(profile, fake):
    with pytest.raises(RuntimeError, match="synthetic journal failure"):
        with profile.OwnedAppContainerProfile(NAME):
            raise RuntimeError("synthetic journal failure")
    assert calls(fake, "delete") == [("delete", NAME)]


def test_profile_class_has_no_destructor(profile):
    assert "__del__" not in vars(profile.OwnedAppContainerProfile)


@pytest.mark.parametrize("phase", ["derive", "create"])
@pytest.mark.parametrize("value", [None, False, True, "0", 0.0, 1 << 32, -(1 << 31) - 1])
def test_malformed_hresult_never_authorizes_creation_or_deletion(profile, fake, phase, value):
    fake.faults[phase + "_hr"] = value
    ctx = profile.OwnedAppContainerProfile(NAME)
    with pytest.raises(profile.ProfileError) as caught:
        ctx.__enter__()
    assert (caught.value.stage, caught.value.code) == ("profile_" + phase, 13)
    assert not calls(fake, "delete") and not fake.live
    ctx.close()
    assert not calls(fake, "delete")


def test_delete_exception_is_sanitized_and_retains_ownership(profile, fake):
    ctx = profile.OwnedAppContainerProfile(NAME).__enter__()
    fake.faults["delete_exception"] = True
    with pytest.raises(profile.ProfileError) as caught:
        ctx.close()
    assert str(caught.value) == "profile_delete (13)"
    assert caught.value.__suppress_context__
    fake.faults.clear()
    ctx.close()
    assert len(calls(fake, "delete")) == 2


@pytest.mark.parametrize("allocation", ["sid", "string"])
def test_free_exception_retains_only_its_allocation(profile, fake, allocation):
    fake.faults["create_" + allocation + "_exception"] = True
    ctx = profile.OwnedAppContainerProfile(NAME)
    with pytest.raises(profile.ProfileError) as caught:
        ctx.__enter__()
    assert caught.value.stage == ("sid_free" if allocation == "sid" else "string_free")
    assert caught.value.code == 13
    assert list(fake.live.values()) == ["create_" + allocation]
    assert len(calls(fake, "delete")) == 1
    fake.faults.clear()
    ctx.close()
    assert not fake.live


def test_free_and_delete_failure_both_retain_retryable_resources(profile, fake):
    fake.faults.update(create_string_free=True, delete_hr=0x80070005)
    ctx = profile.OwnedAppContainerProfile(NAME)
    with pytest.raises(profile.ProfileError) as caught:
        ctx.__enter__()
    assert caught.value.stage == "profile_delete"
    assert list(fake.live.values()) == ["create_string"]
    fake.faults.clear()
    ctx.close()
    ctx.close()
    assert not fake.live and len(calls(fake, "delete")) == 2


def test_collision_with_free_failure_still_never_deletes(profile, fake):
    fake.faults.update(create_hr=0x800700B7, create_sid_free=True)
    ctx = profile.OwnedAppContainerProfile(NAME)
    with pytest.raises(profile.ProfileError) as caught:
        ctx.__enter__()
    assert caught.value.stage == "sid_free" and not calls(fake, "delete")
    fake.faults.clear()
    ctx.close()
    assert not fake.live and not calls(fake, "delete")


def test_no_real_binding_can_initialize_even_on_valid_entry(profile):
    with pytest.raises(pytest.fail.Exception, match="real native bindings"):
        profile.OwnedAppContainerProfile(NAME).__enter__()


def test_prepare_derives_immutable_identity_without_creating(profile, fake):
    ctx = profile.OwnedAppContainerProfile(NAME)
    assert hasattr(ctx, "prepare"), "prepare lifecycle is not implemented"
    identity = ctx.prepare()
    assert isinstance(identity, profile.PreparedProfileIdentity)
    assert (identity.name, identity.sid) == (NAME, SID)
    assert ctx.prepare() is identity
    assert len(calls(fake, "derive")) == 1
    assert not calls(fake, "create") and not calls(fake, "delete") and not fake.live
    for key in ("name", "sid"):
        with pytest.raises(AttributeError):
            setattr(identity, key, "changed")
        with pytest.raises(profile.ProfileError):
            getattr(ctx, key)
    ctx.__enter__()
    assert ctx.sid == identity.sid and len(calls(fake, "derive")) == 1
    with pytest.raises(profile.ProfileError):
        ctx.prepare()
    ctx.close()
    with pytest.raises(profile.ProfileError):
        ctx.prepare()
    assert len(calls(fake, "delete")) == 1


def test_prepared_close_never_creates_or_deletes(profile, fake):
    ctx = profile.OwnedAppContainerProfile(NAME)
    assert hasattr(ctx, "prepare"), "prepare lifecycle is not implemented"
    ctx.prepare()
    ctx.close()
    ctx.close()
    assert not calls(fake, "create") and not calls(fake, "delete")
    for operation in (ctx.prepare, ctx.__enter__):
        with pytest.raises(profile.ProfileError):
            operation()


@pytest.mark.parametrize("allocation", ["sid", "string"])
def test_prepare_release_failure_retains_allocation_until_explicit_close(profile, fake, allocation):
    ctx = profile.OwnedAppContainerProfile(NAME)
    assert hasattr(ctx, "prepare"), "prepare lifecycle is not implemented"
    fake.faults["derive_" + allocation + "_free"] = True
    with pytest.raises(profile.ProfileError) as caught:
        ctx.prepare()
    assert caught.value.stage == ("sid_free" if allocation == "sid" else "string_free")
    assert list(fake.live.values()) == ["derive_" + allocation]
    assert not calls(fake, "create") and not calls(fake, "delete")
    with pytest.raises(profile.ProfileError):
        ctx.prepare()
    fake.faults.clear()
    ctx.close()
    assert not fake.live


def test_local_profile_namespace_prepares_creates_and_deletes_exact_owner(profile, fake, monkeypatch):
    local_name = "xuxia_local_" + "0123456789abcdef" * 2
    monkeypatch.setattr(sys.modules[__name__], "NAME", local_name)
    ctx = profile.OwnedAppContainerProfile(local_name)
    assert fake.calls == []
    assert ctx.prepare().name == local_name
    with ctx:
        assert ctx.name == local_name and ctx.sid == SID
    assert calls(fake, "delete") == [("delete", local_name)]


@pytest.mark.parametrize("name", ["xuxia_local_", "xuxia_local_" + "g" * 32,
                                  "xuxia_local_" + "a" * 31, "xuxia_local_" + "a" * 33,
                                  "xuxia_local_" + "A" * 32, "xuxia_custom_" + "a" * 32])
def test_local_profile_rejects_any_nonfixed_name(profile, name):
    with pytest.raises(profile.ProfileError) as error:
        profile.OwnedAppContainerProfile(name)
    assert error.value.stage == "profile_name"

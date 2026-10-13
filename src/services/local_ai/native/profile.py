"""Owned diagnostic profile foundation; importing/constructing has no effects."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import re
import sys

from src.services.local_ai.native.security import AppContainerSecurity, SecurityContextError


_api = None
_NAME = re.compile(r"xuxia_(?:probe|local)_[0-9a-f]{32}", re.ASCII)


@dataclass(frozen=True)
class PreparedProfileIdentity:
    """Derived intent only. This value confers no profile ownership."""
    name: str
    sid: str


class ProfileError(Exception):
    """Fixed stage plus numeric code; HRESULT codes are unsigned32, not BOOL."""
    def __init__(self, stage: str, code: int):
        self.stage, self.code = stage, int(code)
        super().__init__(f"{stage} ({self.code})")


class _Bindings:
    def __init__(self):
        if sys.platform != "win32":
            raise ProfileError("bindings", 50)
        try:
            userenv = C.WinDLL("userenv", use_last_error=True)
            advapi = C.WinDLL("advapi32", use_last_error=True)
            kernel = C.WinDLL("kernel32", use_last_error=True)
            self._dlls = (userenv, advapi, kernel)
            signatures = [
                (userenv, "CreateAppContainerProfile", C.c_int32,
                 [W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, C.c_void_p, W.DWORD, C.POINTER(C.c_void_p)]),
                (userenv, "DeriveAppContainerSidFromAppContainerName", C.c_int32,
                 [W.LPCWSTR, C.POINTER(C.c_void_p)]),
                (userenv, "DeleteAppContainerProfile", C.c_int32, [W.LPCWSTR]),
                (advapi, "FreeSid", C.c_void_p, [C.c_void_p]),
                (advapi, "ConvertSidToStringSidW", W.BOOL, [C.c_void_p, C.POINTER(C.c_void_p)]),
                (kernel, "LocalFree", C.c_void_p, [C.c_void_p]),
            ]
            for dll, name, result, arguments in signatures:
                function = getattr(dll, name)
                function.restype, function.argtypes = result, arguments
                setattr(self, name, function)
        except Exception:
            raise ProfileError("bindings", 50) from None


def _call(stage, function, *arguments):
    C.set_last_error(0)
    try:
        return function(*arguments)
    except Exception:
        raise ProfileError(stage, 13) from None


def _hresult(stage, function, *arguments):
    value = _call(stage, function, *arguments)
    if type(value) is not int or not -(1 << 31) <= value <= 0xFFFFFFFF:
        raise ProfileError(stage, 13)
    return value & 0xFFFFFFFF


class OwnedAppContainerProfile:
    """One-shot, thread-confined ownership, never inferred from a name or SID.

    Caller must write durable intent before entry, and persist confirmed creation
    after successful entry. Intent alone NEVER authorizes restart deletion. The
    live instance can clean up after journal persistence failure because it saw
    S_OK itself. This helper does not implement restart recovery or prove that
    Windows removed every storage artifact after a successful Delete return.
    """
    def __init__(self, name: str):
        if type(name) is not str or not _NAME.fullmatch(name):
            raise ProfileError("profile_name", 87)
        self._name = name
        self._sid = None
        self._state = "new"
        self._owned = False
        self._bindings = None
        self._allocations = []
        self._prepared = None

    def _active(self):
        if self._state != "active":
            raise ProfileError("context_state", 87)

    @property
    def name(self):
        self._active()
        return self._name

    @property
    def sid(self):
        self._active()
        return self._sid

    def prepare(self) -> PreparedProfileIdentity:
        """Derive once before durable intent; no Create/Delete calls are made."""
        if self._state == "prepared":
            return self._prepared
        if self._state != "new":
            raise ProfileError("context_state", 87)
        self._state = "closed"
        self._bindings = _api if _api is not None else _Bindings()
        intended_sid = self._obtain_sid(creating=False)
        self._prepared = PreparedProfileIdentity(self._name, intended_sid)
        self._state = "prepared"
        return self._prepared

    def __enter__(self):
        if self._state == "new":
            self.prepare()
        if self._state != "prepared":
            raise ProfileError("context_state", 87)
        self._state = "closed"
        try:
            actual_sid = self._obtain_sid(creating=True)
            if actual_sid != self._prepared.sid:
                raise ProfileError("sid_identity", 13)
            self._sid = actual_sid
            self._state = "active"
            return self
        except BaseException:
            # Temporary release was already attempted by _obtain_sid's finally.
            # Never automatically retry a failed free or infer ownership here.
            self._delete_owned()
            raise

    def _obtain_sid(self, *, creating):
        pointer = C.c_void_p()
        stage = "profile_create" if creating else "profile_derive"
        try:
            try:
                if creating:
                    local = self._name.startswith("xuxia_local_")
                    code = _hresult(stage, self._bindings.CreateAppContainerProfile,
                        self._name,
                        "Xuxia local private inference" if local else "Xuxia local diagnostic probe",
                        "Local private inference profile; no network capabilities" if local else
                        "Synthetic diagnostic profile; no network capabilities",
                        None, 0, C.byref(pointer))
                    if code == 0:
                        # This must precede all returned-SID validation/cleanup.
                        self._owned = True
                else:
                    code = _hresult(stage, self._bindings.DeriveAppContainerSidFromAppContainerName,
                                    self._name, C.byref(pointer))
            finally:
                if pointer.value:
                    self._allocations.append(("sid", pointer.value))
            if code != 0:
                # Includes ERROR_ALREADY_EXISTS: collision is NEVER adoption.
                raise ProfileError(stage, code)
            if not pointer.value:
                raise ProfileError("profile_sid", 13)
            return self._sid_to_text(pointer.value)
        finally:
            self._release_allocations()

    def _sid_to_text(self, sid_pointer):
        text_pointer = C.c_void_p()
        try:
            succeeded = _call("sid_string", self._bindings.ConvertSidToStringSidW,
                              sid_pointer, C.byref(text_pointer))
        finally:
            if text_pointer.value:
                self._allocations.append(("string", text_pointer.value))
        if not succeeded:
            raise ProfileError("sid_string", C.get_last_error() or 13)
        if not text_pointer.value:
            raise ProfileError("sid_string", 13)
        # Successful Win32 conversion supplies an allocated NUL-terminated string.
        text = C.wstring_at(text_pointer.value)
        try:
            AppContainerSecurity(text)  # pure shape validation; DO NOT enter
        except SecurityContextError:
            raise ProfileError("sid_shape", 87) from None
        return text

    def _release_allocations(self):
        first_error = None
        for kind, pointer in tuple(reversed(self._allocations)):
            stage = "sid_free" if kind == "sid" else "string_free"
            function = self._bindings.FreeSid if kind == "sid" else self._bindings.LocalFree
            try:
                remaining = _call(stage, function, pointer)
                if remaining:
                    # FreeSid documents NULL return, not a GetLastError contract.
                    code = 13 if kind == "sid" else C.get_last_error() or 13
                    raise ProfileError(stage, code)
                self._allocations.remove((kind, pointer))
            except ProfileError as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error

    def _delete_owned(self):
        if self._owned:
            code = _hresult("profile_delete", self._bindings.DeleteAppContainerProfile, self._name)
            if code != 0:
                raise ProfileError("profile_delete", code)
            self._owned = False

    def close(self):
        self._state = "closed"
        self._sid = None
        try:
            self._release_allocations()
        finally:
            # A deletion failure retains ownership even if a temporary free also
            # failed. Either failure is visible, and subsequent close can retry.
            self._delete_owned()

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

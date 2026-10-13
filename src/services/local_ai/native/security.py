"""Owned AppContainer token foundation; does not launch or sandbox a process."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import re
import sys


_api = None
_PACKAGE_SID = re.compile(r"S-1-15-2(?:-(?:0|[1-9][0-9]{0,9})){7}", re.ASCII)


class SecurityContextError(Exception):
    """Fixed diagnostic stage and numeric error; never includes caller data."""

    def __init__(self, stage: str, win32_error: int):
        self.stage = stage
        self.win32_error = int(win32_error)
        super().__init__(f"{stage} ({self.win32_error})")


class SID_AND_ATTRIBUTES(C.Structure):
    _fields_ = [("Sid", C.c_void_p), ("Attributes", W.DWORD)]


class SECURITY_CAPABILITIES(C.Structure):
    _fields_ = [("AppContainerSid", C.c_void_p),
                ("Capabilities", C.POINTER(SID_AND_ATTRIBUTES)),
                ("CapabilityCount", W.DWORD), ("Reserved", W.DWORD)]


@dataclass(frozen=True)
class TokenEvidence:
    package_sid: str
    is_appcontainer: bool
    capability_count: int


class _Bindings:
    def __init__(self):
        if sys.platform != "win32":
            raise SecurityContextError("bindings", 50)
        try:
            advapi = C.WinDLL("advapi32", use_last_error=True)
            kernel = C.WinDLL("kernel32", use_last_error=True)
            signatures = [
                (advapi, "ConvertStringSidToSidW", W.BOOL, [W.LPCWSTR, C.POINTER(C.c_void_p)]),
                (advapi, "IsValidSid", W.BOOL, [C.c_void_p]),
                (advapi, "EqualSid", W.BOOL, [C.c_void_p, C.c_void_p]),
                (advapi, "OpenProcessToken", W.BOOL, [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]),
                (advapi, "GetTokenInformation", W.BOOL, [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]),
                (kernel, "CloseHandle", W.BOOL, [W.HANDLE]),
                (kernel, "LocalFree", C.c_void_p, [C.c_void_p]),
            ]
            for dll, name, result, arguments in signatures:
                function = getattr(dll, name)
                function.restype, function.argtypes = result, arguments
                setattr(self, name, function)
        except Exception:
            raise SecurityContextError("bindings", 50) from None


def _call(stage, function, *arguments):
    C.set_last_error(0)
    try:
        return function(*arguments)
    except Exception:
        raise SecurityContextError(stage, 13) from None


def _failure(stage, default=13):
    return SecurityContextError(stage, C.get_last_error() or default)


class AppContainerSecurity:
    """One-shot, thread-confined context; no profile/token/system mutation.

    The caller must retain this context until its process attribute list is
    destroyed, and verify a still-suspended child before allowing execution.
    Exposed ctypes memory is for trusted native callers, not a security boundary
    against another thread modifying this Python process's own address space.
    """

    def __init__(self, package_sid: str):
        if (type(package_sid) is not str or not _PACKAGE_SID.fullmatch(package_sid)
                or any(int(part) > 0xFFFFFFFF for part in package_sid.split("-")[4:])):
            raise SecurityContextError("sid_input", 87)
        self._package_sid = package_sid
        self._state = "new"
        self._sid = C.c_void_p()
        self._caps = None
        self._bindings = None

    def __enter__(self):
        if self._state != "new":
            raise SecurityContextError("context_state", 87)
        self._state = "closed"
        self._bindings = _api if _api is not None else _Bindings()
        try:
            if not _call("sid_convert", self._bindings.ConvertStringSidToSidW,
                         self._package_sid, C.byref(self._sid)):
                raise _failure("sid_convert")
            if not self._sid.value:
                raise SecurityContextError("sid_convert", 13)
            if not _call("sid_validate", self._bindings.IsValidSid, self._sid.value):
                raise SecurityContextError("sid_validate", 13)
            # ConvertStringSidToSidW owns a valid allocation; confirm its exact
            # canonical bytes rather than trusting a different valid identity.
            header = C.string_at(self._sid.value, 8)
            expected_header = bytes([1, 8, 0, 0, 0, 0, 0, 15])
            if header != expected_header:
                raise SecurityContextError("sid_validate", 13)
            expected = expected_header + b"".join(int(part).to_bytes(4, "little")
                for part in self._package_sid.split("-")[3:])
            if C.string_at(self._sid.value, 40) != expected:
                raise SecurityContextError("sid_validate", 13)
            self._caps = SECURITY_CAPABILITIES(self._sid.value, None, 0, 0)
            self._state = "active"
            return self
        except BaseException:
            self.close()
            raise

    def _require_active(self):
        if self._state != "active":
            raise SecurityContextError("context_state", 87)
        if (self._caps.AppContainerSid != self._sid.value or self._caps.Capabilities
                or self._caps.CapabilityCount or self._caps.Reserved):
            raise SecurityContextError("context_modified", 87)

    @property
    def capabilities(self):
        self._require_active()
        return self._caps

    def _query(self, token, information):
        length = W.DWORD()
        succeeded = _call("token_size", self._bindings.GetTokenInformation,
                          token, information, None, 0, C.byref(length))
        if succeeded or C.get_last_error() != 122:
            raise _failure("token_size")
        if not 0 < length.value <= 65536:
            raise SecurityContextError("token_size", 13)
        capacity = length.value
        buffer = C.create_string_buffer(capacity)
        length.value = 0
        if not _call("token_query", self._bindings.GetTokenInformation,
                     token, information, buffer, capacity, C.byref(length)):
            raise _failure("token_query")
        if not 0 < length.value <= capacity:
            raise SecurityContextError("token_length", 13)
        return buffer, length.value

    def verify_process(self, process_handle):
        self._require_active()
        if (type(process_handle) is not int or process_handle == 0 or process_handle < -1
                or process_handle >= 1 << (8 * C.sizeof(W.HANDLE))):
            raise SecurityContextError("process_handle", 87)
        token = W.HANDLE()
        try:
            if not _call("token_open", self._bindings.OpenProcessToken,
                         process_handle, 8, C.byref(token)):
                raise _failure("token_open")
            if not token.value:
                raise SecurityContextError("token_open", 6)
            buffer, length = self._query(token.value, 29)
            if length < C.sizeof(W.DWORD):
                raise SecurityContextError("token_length", 13)
            if W.DWORD.from_buffer(buffer).value != 1:
                raise SecurityContextError("token_is_appcontainer", 5)
            sid_buffer, length = self._query(token.value, 31)
            pointer_size = C.sizeof(C.c_void_p)
            if length < pointer_size:
                raise SecurityContextError("token_sid_bounds", 13)
            pointer = C.c_void_p.from_buffer(sid_buffer).value
            base = C.addressof(sid_buffer)
            end = base + length
            # No dereference until BOTH the header and full extent are bounded.
            if pointer is None or pointer < base + pointer_size or pointer > end - 8:
                raise SecurityContextError("token_sid_bounds", 13)
            header = C.string_at(pointer, 8)
            extent = 8 + 4 * header[1]
            if header[0] != 1 or header[1] > 15 or extent > end - pointer:
                raise SecurityContextError("token_sid_bounds", 13)
            if not _call("token_sid_validate", self._bindings.IsValidSid, pointer):
                raise SecurityContextError("token_sid_validate", 13)
            if not _call("token_sid_mismatch", self._bindings.EqualSid, pointer, self._sid.value):
                raise SecurityContextError("token_sid_mismatch", 5)
            groups, length = self._query(token.value, 30)
            if length < C.sizeof(W.DWORD):
                raise SecurityContextError("token_length", 13)
            if W.DWORD.from_buffer(groups).value != 0:
                raise SecurityContextError("token_capabilities", 5)
            evidence = TokenEvidence(self._package_sid, True, 0)
        finally:
            if token.value:
                if not _call("token_close", self._bindings.CloseHandle, token.value):
                    raise _failure("token_close", 6)
        return evidence

    def close(self):
        self._state = "closed"
        if self._caps is not None:
            self._caps.AppContainerSid = None
        if self._sid.value:
            # Non-NULL means failure: the allocation remains owned and a later
            # explicit close may retry. Never silently forget or double-free it.
            if _call("sid_free", self._bindings.LocalFree, self._sid.value):
                raise _failure("sid_free", 6)
            self._sid.value = None

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

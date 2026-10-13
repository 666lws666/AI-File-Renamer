"""Read-only, explicitly owned Windows loopback-exemption metadata preflight."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import re
import sys

from src.services.local_ai.native.security import SID_AND_ATTRIBUTES


_api = None
_PACKAGE_SID = re.compile(r"S-1-15-2(?:-(?:0|[1-9][0-9]{0,9})){7}", re.ASCII)
_MAX_ENTRIES = 4096


class ExemptionError(Exception):
    """Fixed diagnostic stage and numeric code; never embeds installed SIDs."""

    def __init__(self, stage: str, code: int):
        self.stage, self.code = stage, int(code)
        super().__init__(f"{stage} ({self.code})")


@dataclass(frozen=True)
class ExemptionResult:
    package_sid: str
    exempt: bool
    count: int
    cleanup_complete: bool


class _Bindings:
    def __init__(self):
        if sys.platform != "win32":
            raise ExemptionError("bindings", 50)
        try:
            firewall = C.WinDLL("FirewallAPI.dll", use_last_error=True)
            advapi = C.WinDLL("advapi32.dll", use_last_error=True)
            kernel = C.WinDLL("kernel32.dll", use_last_error=True)
            self._dlls = (firewall, advapi, kernel)
            signatures = (
                (firewall, "NetworkIsolationGetAppContainerConfig", W.DWORD,
                 (C.POINTER(W.DWORD), C.POINTER(C.POINTER(SID_AND_ATTRIBUTES)))),
                (advapi, "ConvertStringSidToSidW", W.BOOL,
                 (W.LPCWSTR, C.POINTER(C.c_void_p))),
                (advapi, "IsValidSid", W.BOOL, (C.c_void_p,)),
                (advapi, "EqualSid", W.BOOL, (C.c_void_p, C.c_void_p)),
                (kernel, "GetProcessHeap", W.HANDLE, ()),
                (kernel, "HeapFree", W.BOOL, (W.HANDLE, W.DWORD, C.c_void_p)),
                (kernel, "LocalFree", C.c_void_p, (C.c_void_p,)),
            )
            for dll, name, result, arguments in signatures:
                function = getattr(dll, name)
                function.restype, function.argtypes = result, arguments
                setattr(self, name, function)
        except Exception:
            raise ExemptionError("bindings", 50) from None


def _call(stage, function, *args):
    C.set_last_error(0)
    try:
        return function(*args)
    except Exception:
        raise ExemptionError(stage, 13) from None


def _error(stage, default=13):
    return ExemptionError(stage, C.get_last_error() or default)


def _pointer_plausible(pointer):
    return type(pointer) is int and pointer >= 4096 and pointer % C.sizeof(C.c_void_p) == 0


class OwnedLoopbackExemptionQuery:
    """Single-use, thread-confined live owner; call close() to retry failed frees.

    No native operation occurs at import or construction. If native output layout
    is uncertain, close reports failure and intentionally retains that allocation.
    Keep this owner alive until every allocation is released or explicitly handed
    to a caller capable of retaining it; do not silently drop it on an error.
    """

    def __init__(self, package_sid: str):
        if (type(package_sid) is not str or not _PACKAGE_SID.fullmatch(package_sid)
                or any(int(part) > 0xFFFFFFFF for part in package_sid.split("-")[4:])):
            raise ExemptionError("sid_input", 87)
        self._package_sid = package_sid
        self._bindings = None
        self._state = "new"
        self._target = None
        self._outer = None
        self._sids = []
        self._uncertain = False
        self._quarantined_output = None
        self._result = None

    def _capture_layout(self, count, outer):
        # Preserve native output ownership before any consistency check. This
        # private live-owner record is never serialized or exposed in the result.
        self._quarantined_output = (count, outer)
        if count > _MAX_ENTRIES or (count == 0) != (outer is None) or (
                outer is not None and not _pointer_plausible(outer)):
            self._uncertain = bool(outer)
            raise ExemptionError("query_layout", 13)
        if not count:
            self._quarantined_output = None
            return
        try:
            entries = C.cast(outer, C.POINTER(SID_AND_ATTRIBUTES))
            pointers = [entries[i].Sid for i in range(count)]
        except Exception:
            self._uncertain = True
            raise ExemptionError("query_layout", 13) from None
        if (any(not _pointer_plausible(pointer) for pointer in pointers)
                or len(set(pointers)) != count or outer in pointers):
            self._uncertain = True
            raise ExemptionError("query_layout", 13)
        # All entry addresses are retained before any freeing of the outer array.
        self._sids = pointers
        self._outer = outer
        self._quarantined_output = None

    def _cleanup(self):
        first = None
        if not self._uncertain and self._bindings is not None:
            heap = None
            if self._sids or self._outer:
                try:
                    heap = _call("process_heap", self._bindings.GetProcessHeap)
                    if not heap:
                        raise _error("process_heap")
                except ExemptionError as error:
                    first = error
            if heap:
                for pointer in tuple(self._sids):
                    try:
                        if not _call("heap_free", self._bindings.HeapFree, heap, 0, pointer):
                            raise _error("heap_free")
                        self._sids.remove(pointer)
                    except ExemptionError as error:
                        if first is None:
                            first = error
                if self._outer and not self._sids:
                    try:
                        if not _call("heap_free", self._bindings.HeapFree, heap, 0, self._outer):
                            raise _error("heap_free")
                        self._outer = None
                    except ExemptionError as error:
                        if first is None:
                            first = error
        if self._target:
            try:
                if _call("target_free", self._bindings.LocalFree, self._target):
                    raise _error("target_free")
                self._target = None
            except ExemptionError as error:
                if first is None:
                    first = error
        if self._uncertain:
            raise ExemptionError("query_layout", 13)
        if first is not None:
            raise first

    def query(self) -> ExemptionResult:
        if self._state != "new":
            raise ExemptionError("context_state", 87)
        self._state = "queried"
        self._bindings = _api if _api is not None else _Bindings()
        primary = None
        count = W.DWORD()
        outer = C.POINTER(SID_AND_ATTRIBUTES)()
        exempt = False
        try:
            target = C.c_void_p()
            try:
                converted = _call("sid_convert", self._bindings.ConvertStringSidToSidW,
                                  self._package_sid, C.byref(target))
            finally:
                if target.value:
                    self._target = target.value
            if not converted or not self._target:
                raise _error("sid_convert")
            if not _call("sid_validate", self._bindings.IsValidSid, self._target):
                raise ExemptionError("sid_validate", 13)
            expected = bytes((1, 8, 0, 0, 0, 0, 0, 15)) + b"".join(
                int(part).to_bytes(4, "little") for part in self._package_sid.split("-")[3:])
            if C.string_at(self._target, len(expected)) != expected:
                raise ExemptionError("sid_validate", 13)
            try:
                status = _call("query", self._bindings.NetworkIsolationGetAppContainerConfig,
                               C.byref(count), C.byref(outer))
            finally:
                # Even a raised boundary call may have populated out parameters.
                self._capture_layout(count.value, C.cast(outer, C.c_void_p).value)
            if type(status) is not int or not 0 <= status <= 0xFFFFFFFF:
                raise ExemptionError("query", 13)
            if status:
                raise ExemptionError("query", status)
            for pointer in self._sids:
                if not _call("entry_sid", self._bindings.IsValidSid, pointer):
                    raise ExemptionError("entry_sid", 13)
                if _call("sid_equal", self._bindings.EqualSid, pointer, self._target):
                    exempt = True
        except ExemptionError as error:
            primary = error
        try:
            self._cleanup()
        except ExemptionError as error:
            raise error from None
        if primary is not None:
            raise primary
        self._result = ExemptionResult(self._package_sid, exempt, count.value, True)
        return self._result

    def require_not_exempt(self) -> ExemptionResult:
        """Checked preflight; an exempt SID never passes as a negative result."""
        if self._result is None:
            raise ExemptionError("context_state", 87)
        if self._result.exempt:
            raise ExemptionError("target_exempt", 5)
        return self._result

    def close(self):
        """Retry only still-owned allocations; a malformed layout remains retained."""
        self._state = "closed"
        self._cleanup()

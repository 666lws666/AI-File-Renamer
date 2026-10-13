"""Read-only Windows capacity measurement and conservative trial admission.

The caller owns validation and the lease for ``state_root``. These checks only
decide whether a local self-check may begin; they do not establish readiness.
"""

from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path


_MAX_U64 = 2**64 - 1
_GIB = 1024**3
_MIB = 1024**2
_MIN_TRIAL_AVAILABLE_MEMORY = 5 * _GIB
_DISK_RESERVE = 256 * _MIB
_MAX_STAGING_BYTES = 5 * _GIB


@dataclass(frozen=True, slots=True)
class HostCapacity:
    total_memory_bytes: int
    available_memory_bytes: int
    available_disk_bytes: int


class HostCapacityError(RuntimeError):
    """A fixed, content-free host measurement or admission failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _valid_capacity(capacity: object) -> bool:
    if type(capacity) is not HostCapacity:
        return False
    try:
        total = capacity.total_memory_bytes
        available = capacity.available_memory_bytes
        disk = capacity.available_disk_bytes
    except AttributeError:
        return False
    return (
        type(total) is int and 0 < total <= _MAX_U64
        and type(available) is int and 0 <= available <= total
        and type(disk) is int and 0 <= disk <= _MAX_U64
    )


def measure_host_capacity(state_root: Path) -> HostCapacity:
    """Query RAM and caller-available space on an already leased local drive."""
    if os.name != "nt" or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise HostCapacityError("HOST_UNSUPPORTED")
    if (
        not isinstance(state_root, Path)
        or not state_root.is_absolute()
        or re.fullmatch(r"[A-Za-z]:", state_root.drive) is None
        or "\x00" in str(state_root)
    ):
        raise HostCapacityError("HOST_INPUT_INVALID")

    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        memory_status = kernel.GlobalMemoryStatusEx
        memory_status.argtypes = [ctypes.POINTER(_MEMORYSTATUSEX)]
        memory_status.restype = wintypes.BOOL
        disk_space = kernel.GetDiskFreeSpaceExW
        disk_space.argtypes = [
            wintypes.LPCWSTR,
            ctypes.POINTER(ctypes.c_ulonglong),
            ctypes.POINTER(ctypes.c_ulonglong),
            ctypes.POINTER(ctypes.c_ulonglong),
        ]
        disk_space.restype = wintypes.BOOL

        memory = _MEMORYSTATUSEX()
        memory.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if not memory_status(ctypes.byref(memory)):
            raise HostCapacityError("HOST_MEASUREMENT_FAILED")

        caller_available = ctypes.c_ulonglong()
        volume_total = ctypes.c_ulonglong()
        volume_free = ctypes.c_ulonglong()
        if not disk_space(
            str(state_root),
            ctypes.byref(caller_available),
            ctypes.byref(volume_total),
            ctypes.byref(volume_free),
        ):
            raise HostCapacityError("HOST_MEASUREMENT_FAILED")
        capacity = HostCapacity(
            memory.ullTotalPhys,
            memory.ullAvailPhys,
            caller_available.value,
        )
        if not _valid_capacity(capacity):
            raise HostCapacityError("HOST_MEASUREMENT_FAILED")
        return capacity
    except Exception:
        raise HostCapacityError("HOST_MEASUREMENT_FAILED") from None


def require_host_capacity(capacity: HostCapacity, *, staging_bytes: int) -> None:
    """Admit a bounded trial only when RAM and staging reserve are available."""
    if (
        not _valid_capacity(capacity)
        or type(staging_bytes) is not int
        or not 0 <= staging_bytes <= _MAX_STAGING_BYTES
    ):
        raise HostCapacityError("HOST_INPUT_INVALID")
    if capacity.available_memory_bytes < _MIN_TRIAL_AVAILABLE_MEMORY:
        raise HostCapacityError("LOCAL_MEMORY_LOW")
    if capacity.available_disk_bytes < staging_bytes + _DISK_RESERVE:
        raise HostCapacityError("LOCAL_DISK_LOW")

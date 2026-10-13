"""Read-only host-capacity checks; native calls are faked except one OS probe."""

from __future__ import annotations

import ctypes
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest


GIB = 1024**3
MIB = 1024**2
MODULE = "src.services.local_ai.host_capacity"


def test_host_capacity_api_is_available():
    assert importlib.util.find_spec(MODULE) is not None, "host capacity API is missing"


@pytest.fixture
def capacity_module():
    return importlib.import_module(MODULE)


class NativeFunction:
    def __init__(self, implementation):
        self.implementation = implementation
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.implementation(*args)


def fake_kernel(monkeypatch, module, *, total=8 * GIB, available=5 * GIB,
                caller_disk=256 * MIB, volume_disk=0, memory_ok=True, disk_ok=True):
    calls = []

    def memory(status_pointer):
        status = status_pointer._obj
        calls.append(("memory", status.dwLength))
        assert status.dwLength == ctypes.sizeof(type(status))
        assert [name for name, _ in type(status)._fields_] == [
            "dwLength", "dwMemoryLoad", "ullTotalPhys", "ullAvailPhys",
            "ullTotalPageFile", "ullAvailPageFile", "ullTotalVirtual",
            "ullAvailVirtual", "ullAvailExtendedVirtual",
        ]
        if not memory_ok:
            return 0
        status.ullTotalPhys = total
        status.ullAvailPhys = available
        return 1

    def disk(path, caller_pointer, total_pointer, volume_pointer):
        calls.append(("disk", path))
        if not disk_ok:
            return 0
        caller_pointer._obj.value = caller_disk
        total_pointer._obj.value = 20 * GIB
        volume_pointer._obj.value = volume_disk
        return 1

    kernel = SimpleNamespace(
        GlobalMemoryStatusEx=NativeFunction(memory),
        GetDiskFreeSpaceExW=NativeFunction(disk),
    )
    monkeypatch.setattr(module.ctypes, "WinDLL", lambda name, **kwargs: kernel)
    return kernel, calls


def assert_code(module, expected, action):
    with pytest.raises(module.HostCapacityError) as caught:
        action()
    assert caught.value.code == expected
    assert str(caught.value) == expected
    assert repr(caught.value) == f"HostCapacityError('{expected}')"


def test_import_does_not_query_native_api(capacity_module, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("native API queried during import")

    monkeypatch.setattr(ctypes, "WinDLL", forbidden)
    importlib.reload(capacity_module)
    capacity_module.HostCapacity(8 * GIB, 5 * GIB, 256 * MIB)


def test_measurement_uses_typed_win32_abi_and_caller_available_disk(capacity_module, monkeypatch, tmp_path):
    kernel, calls = fake_kernel(monkeypatch, capacity_module, caller_disk=300 * MIB, volume_disk=50 * GIB)
    observed = capacity_module.measure_host_capacity(tmp_path)
    assert observed == capacity_module.HostCapacity(8 * GIB, 5 * GIB, 300 * MIB)
    assert calls == [("memory", ctypes.sizeof(capacity_module._MEMORYSTATUSEX)), ("disk", str(tmp_path))]
    assert kernel.GlobalMemoryStatusEx.argtypes == [ctypes.POINTER(capacity_module._MEMORYSTATUSEX)]
    assert kernel.GlobalMemoryStatusEx.restype is not None
    assert kernel.GetDiskFreeSpaceExW.argtypes == [
        ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulonglong),
        ctypes.POINTER(ctypes.c_ulonglong), ctypes.POINTER(ctypes.c_ulonglong),
    ]
    assert kernel.GetDiskFreeSpaceExW.restype is not None
    assert ctypes.sizeof(capacity_module._MEMORYSTATUSEX) == 64


@pytest.mark.parametrize("memory_ok,disk_ok", [(False, True), (True, False)])
def test_false_native_result_fails_closed(capacity_module, monkeypatch, tmp_path, memory_ok, disk_ok):
    fake_kernel(monkeypatch, capacity_module, memory_ok=memory_ok, disk_ok=disk_ok)
    assert_code(capacity_module, "HOST_MEASUREMENT_FAILED", lambda: capacity_module.measure_host_capacity(tmp_path))


def test_native_exception_is_not_disclosed(capacity_module, monkeypatch, tmp_path):
    def broken(*args, **kwargs):
        raise OSError("secret path and native error 123")

    monkeypatch.setattr(capacity_module.ctypes, "WinDLL", broken)
    assert_code(capacity_module, "HOST_MEASUREMENT_FAILED", lambda: capacity_module.measure_host_capacity(tmp_path))


@pytest.mark.parametrize("total,available", [(0, 0), (8 * GIB, 9 * GIB)])
def test_inconsistent_native_memory_is_not_returned(capacity_module, monkeypatch, tmp_path, total, available):
    fake_kernel(monkeypatch, capacity_module, total=total, available=available)
    assert_code(capacity_module, "HOST_MEASUREMENT_FAILED", lambda: capacity_module.measure_host_capacity(tmp_path))


@pytest.mark.parametrize("path", ["C:\\state", Path("relative"), Path(r"\\server\share\state"),
                                  Path(r"\\?\C:\state"), Path(r"\\.\C:\state")])
def test_nonlocal_or_non_path_input_is_refused(capacity_module, monkeypatch, path):
    def forbidden(*args, **kwargs):
        pytest.fail("native API queried for invalid path")

    monkeypatch.setattr(capacity_module.ctypes, "WinDLL", forbidden)
    assert_code(capacity_module, "HOST_INPUT_INVALID", lambda: capacity_module.measure_host_capacity(path))


def test_unsupported_platform_is_fixed_error(capacity_module, monkeypatch, tmp_path):
    monkeypatch.setattr(capacity_module, "os", SimpleNamespace(name="posix"))
    assert_code(capacity_module, "HOST_UNSUPPORTED", lambda: capacity_module.measure_host_capacity(tmp_path))


def test_32_bit_python_process_is_unsupported(capacity_module, monkeypatch, tmp_path):
    original_sizeof = ctypes.sizeof
    monkeypatch.setattr(ctypes, "sizeof", lambda item: 4 if item is ctypes.c_void_p else original_sizeof(item))
    assert_code(capacity_module, "HOST_UNSUPPORTED", lambda: capacity_module.measure_host_capacity(tmp_path))


def test_admission_exact_memory_and_disk_boundaries_pass(capacity_module):
    capacity_module.require_host_capacity(
        capacity_module.HostCapacity(5 * GIB, 5 * GIB, 256 * MIB), staging_bytes=0,
    )
    capacity_module.require_host_capacity(
        capacity_module.HostCapacity(8 * GIB, 5 * GIB, 5 * GIB + 256 * MIB), staging_bytes=5 * GIB,
    )


def test_one_byte_below_memory_floor_is_rejected(capacity_module):
    sample = capacity_module.HostCapacity(8 * GIB, 5 * GIB - 1, 8 * GIB)
    assert_code(capacity_module, "LOCAL_MEMORY_LOW", lambda: capacity_module.require_host_capacity(sample, staging_bytes=0))


@pytest.mark.parametrize("staging", [0, 123, 5 * GIB])
def test_one_byte_below_disk_reserve_is_rejected(capacity_module, staging):
    sample = capacity_module.HostCapacity(8 * GIB, 5 * GIB, staging + 256 * MIB - 1)
    assert_code(capacity_module, "LOCAL_DISK_LOW", lambda: capacity_module.require_host_capacity(sample, staging_bytes=staging))


@pytest.mark.parametrize("field,value", [
    ("total_memory_bytes", True), ("total_memory_bytes", 0),
    ("total_memory_bytes", -1), ("total_memory_bytes", 2**64),
    ("available_memory_bytes", False), ("available_memory_bytes", -1),
    ("available_memory_bytes", 2**64), ("available_memory_bytes", 9 * GIB),
    ("available_disk_bytes", True), ("available_disk_bytes", -1),
    ("available_disk_bytes", 2**64),
])
def test_invalid_capacity_fields_are_rejected(capacity_module, field, value):
    fields = dict(total_memory_bytes=8 * GIB, available_memory_bytes=5 * GIB, available_disk_bytes=8 * GIB)
    fields[field] = value
    sample = capacity_module.HostCapacity(**fields)
    assert_code(capacity_module, "HOST_INPUT_INVALID", lambda: capacity_module.require_host_capacity(sample, staging_bytes=0))


@pytest.mark.parametrize("staging", [True, -1, 5 * GIB + 1, 1.0, "0"])
def test_invalid_staging_size_is_rejected(capacity_module, staging):
    sample = capacity_module.HostCapacity(8 * GIB, 5 * GIB, 8 * GIB)
    assert_code(capacity_module, "HOST_INPUT_INVALID", lambda: capacity_module.require_host_capacity(sample, staging_bytes=staging))


def test_forged_dataclass_subclass_and_duck_type_are_rejected(capacity_module):
    class Forged(capacity_module.HostCapacity):
        pass

    valid = (8 * GIB, 5 * GIB, 8 * GIB)
    for sample in [Forged(*valid), SimpleNamespace(total_memory_bytes=valid[0],
                                                   available_memory_bytes=valid[1],
                                                   available_disk_bytes=valid[2])]:
        assert_code(capacity_module, "HOST_INPUT_INVALID", lambda: capacity_module.require_host_capacity(sample, staging_bytes=0))


def test_uninitialized_genuine_dataclass_is_rejected(capacity_module):
    forged = object.__new__(capacity_module.HostCapacity)
    assert_code(capacity_module, "HOST_INPUT_INVALID", lambda: capacity_module.require_host_capacity(forged, staging_bytes=0))


def test_actual_read_only_measurement_has_valid_bounds(capacity_module, tmp_path):
    result = capacity_module.measure_host_capacity(tmp_path)
    assert 0 < result.total_memory_bytes <= 2**64 - 1
    assert 0 <= result.available_memory_bytes <= result.total_memory_bytes
    assert 0 <= result.available_disk_bytes <= 2**64 - 1

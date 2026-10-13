# Local Host Capacity Admission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Refuse an obviously resource-starved local launch before creating its
private stage, and expose honest measurements without promising minimum hardware.

**Architecture:** One small production-owned read-only Windows measurement module;
the later coordinator calls it before staging and immediately before launch.
An admission check is not a reservation: later disk/memory failures still require
the existing exact-owner cleanup and never enable a cloud fallback.

**Tech Stack:** Python ctypes with explicit Windows ABI, immutable dataclasses,
standard-library integer validation and pytest injected API seams.

## Global Constraints

- No model/process/profile launch, cloud API/key/Credential Manager, download,
  private file, security change, QML/Golden, main checkout, merge or push.
- No import from diagnostic scripts; no reading environment variables for native
  paths or capacity; no logging paths/content or raw native exception messages.
- Do not call the admission thresholds minimum system requirements. The earlier
  real model working-set observation exceeded5GiB; self-check and workload Gates
  remain necessary. Do not promise GPU use or speed.
- Do not modify memory/pagefile settings, request administrator privilege, clean
  disk files, or expand this module into a performance-monitoring subsystem.

## Task 1: Read-only host measurement and bounded admission

Files: create `src/services/local_ai/host_capacity.py` and
`tests/unit/test_local_host_capacity.py`. Existing modules stay read-only.

```python
@dataclass(frozen=True, slots=True)
class HostCapacity:
    total_memory_bytes: int
    available_memory_bytes: int
    available_disk_bytes: int

class HostCapacityError(RuntimeError): ...  # fixed code attribute and text

def measure_host_capacity(state_root: Path) -> HostCapacity: ...
def require_host_capacity(capacity: HostCapacity, *, staging_bytes: int) -> None: ...
```

The caller supplies an existing leased/validated state directory, not a user
filename. Constructor/import performs no native query or filesystem I/O. Query
only when explicitly called. Require Windows and a64-bit Python process. Use
typed `GlobalMemoryStatusEx` and `GetDiskFreeSpaceExW`, validating return status;
the disk value is bytes available to this caller, not total volume free space.
Use `ctypes.WinDLL` inside the reader, explicit argtypes/restype and the documented
MEMORYSTATUSEX field order/width. No shell, subprocess, WMI or dependency install.

The path must be a Path, absolute local drive path with no UNC/device/relative
form. Do not create, modify, resolve via environment, or silently fall back to
another directory. ResourceStore owns reparse/identity validation; this read-only
measurement is not a substitute for that lease. Expose fixed codes
`HOST_UNSUPPORTED`, `HOST_MEASUREMENT_FAILED`, `HOST_INPUT_INVALID`,
`LOCAL_MEMORY_LOW`, `LOCAL_DISK_LOW`; no path/raw error in text or repr.

Require genuine HostCapacity, actual-int (not bool) fields, total memory>0,
0<=available memory<=total, disk>=0; all measurements <=2**64-1. staging_bytes is
actual-int in0..5GiB. No mutable object/duck-typing. The conservative trial
admission floor is `5 * 1024**3` available memory bytes. When staging_bytes>0,
require disk >= staging_bytes + `256 * 1024**2` reserve. When staging_bytes=0
(the copy already exists), require only the256MiB reserve. The exact boundary
passes; one byte below fails. These thresholds are safety checks for starting
self-check, not a guarantee an arbitrary workload will fit.

- [ ] RED tests: missing API; exact boundaries; negative/bool/overflow/forged
  dataclass inputs; unavailable native measurement; false API returns; total vs
  caller-available disk confusion; path refusal; fixed content-free errors.
- [ ] Mock the native function layer, not the whole measurement function, to
  exercise MEMORYSTATUSEX size/ABI argument pointers and failure handling.
- [ ] Import-under-failfast native API test: no measurement at import. Run one
  actual read-only measurement of a synthetic temp directory on Windows, assert
  only valid bounds (never assert this host has enough RAM for a model).
- [ ] Implement and run focused tests; diff check; scoped commit of only2files.
  Report RED/GREEN and actual commands to
  `.superpowers/sdd/local-host-capacity-report.md`. No model inference claim.

## Verified primary references

Checked2026-09-30: Microsoft documents volatile memory measurements, a caller-
quota-aware free-space value, and64-bit byte fields. These support the read-only
measurement contract, not the application's admission thresholds.

- [GlobalMemoryStatusEx](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-globalmemorystatusex)
- [MEMORYSTATUSEX](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/ns-sysinfoapi-memorystatusex)
- [GetDiskFreeSpaceExW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getdiskfreespaceexw)

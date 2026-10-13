"""Bounded, content-free crash journal; durable metadata never proves ownership.

The coordinator must retain its native owners until cleanup is confirmed. This
module neither creates nor cleans up processes, profiles, or staging directories.
Interrupted pinned writes can require explicit recovery; they are not rollbacks.
"""

from __future__ import annotations

import json
import os
import re
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, replace
from enum import Enum
from pathlib import Path

from .resource_store import (MARKER, ResourceStore, StoreBusy, StoreOwnershipError,
                             StoreOwnershipUncertain)


_NAMESPACE = "xuxia-local-inference-journal-v1"
_BASENAME = "inference-run.json"
_MAX_BYTES = 4096
_MAX_REVISION = 2**63 - 1
_HEX32 = re.compile(r"[0-9a-f]{32}")
_CATALOG = re.compile(r"[0-9a-f]{64}")
_PROFILE = re.compile(r"xuxia_local_([0-9a-f]{32})")
_STAGE = re.compile(r"stage_[0-9a-f]{32}")
_SID = re.compile(r"S-1-15-2-(?:0|[1-9][0-9]{0,9})(?:-(?:0|[1-9][0-9]{0,9})){6}")


class InferenceRecoveryRequired(RuntimeError):
    """Explicit recovery is required; no record contents are disclosed."""

    def __init__(self):
        super().__init__("RECOVERY_REQUIRED")


class InferenceRecoveryState(str, Enum):
    MISSING = "missing"
    CLEAN = "clean"
    RECOVERY_REQUIRED = "recovery_required"
    BUSY = "busy"


class InferenceJournalError(RuntimeError):
    """Only fixed, content-free reason codes can be exposed."""

    def __init__(self, reason="JOURNAL_STATE_INVALID"):
        if reason not in ("JOURNAL_STATE_INVALID", "JOURNAL_WRITE_FAILED",
                          "JOURNAL_LEASE_REQUIRED", "JOURNAL_RECORD_INVALID",
                          "JOURNAL_REVISION_OVERFLOW"):
            reason = "JOURNAL_STATE_INVALID"
        super().__init__(reason)


def _matches(pattern, value):
    return type(value) is str and pattern.fullmatch(value) is not None


def _integer(value, minimum, maximum):
    return type(value) is int and minimum <= value <= maximum


@dataclass(frozen=True, slots=True, repr=False)
class InferenceRunRecord:
    revision: int
    run_id: str | None
    phase: str
    catalog_id: str | None
    profile_name: str | None
    package_sid: str | None
    stage_name: str | None
    stage_identity: tuple[int, int] | None

    def __post_init__(self):
        if not _valid_record(self):
            raise InferenceJournalError("JOURNAL_RECORD_INVALID")

    def __repr__(self):
        return "InferenceRunRecord()"


def _valid_record(record):
    if (not _integer(record.revision, 0, _MAX_REVISION)
            or type(record.phase) is not str or record.phase not in ("clean", "active")):
        return False
    ownership = (record.run_id, record.catalog_id, record.profile_name,
                 record.package_sid, record.stage_name, record.stage_identity)
    if all(value is None for value in ownership):
        return record.phase == "clean" and record.revision == 0
    if (record.revision == 0 or not _matches(_HEX32, record.run_id)
            or not _matches(_CATALOG, record.catalog_id)
            or not _matches(_PROFILE, record.profile_name)
            or record.profile_name != "xuxia_local_" + record.run_id
            or not _matches(_SID, record.package_sid)):
        return False
    if any(int(value) > 2**32 - 1 for value in record.package_sid.split("-")[4:]):
        return False
    if record.stage_name is None:
        return record.stage_identity is None
    identity = record.stage_identity
    return (_matches(_STAGE, record.stage_name) and type(identity) is tuple
            and len(identity) == 2 and _integer(identity[0], 0, 2**32 - 1)
            and _integer(identity[1], 1, 2**64 - 1))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError()


def _decode(raw):
    try:
        if len(raw) > _MAX_BYTES:
            raise ValueError()
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
        if (type(data) is not dict
                or set(data) != {"schema_version", *InferenceRunRecord.__dataclass_fields__}
                or type(data["schema_version"]) is not int or data["schema_version"] != 1):
            raise ValueError()
        del data["schema_version"]
        identity = data["stage_identity"]
        if type(identity) is list:
            data["stage_identity"] = tuple(identity)
        return InferenceRunRecord(**data)
    except (ValueError, TypeError, RecursionError, InferenceJournalError):
        raise InferenceRecoveryRequired() from None


class LocalInferenceJournal:
    def __init__(self, root: Path):
        # ResourceStore construction is I/O-free; only lease() touches the root.
        self._store = ResourceStore(root, _NAMESPACE)
        self._record = None
        self._stream = None
        self._leased = False
        self._write_failed = False

    def inspect_recovery_state(self) -> InferenceRecoveryState:
        """Observe only: never initialize, reset, infer PID ownership or clean up."""
        try:
            with self._store.observe() as store:
                if store is None:
                    return InferenceRecoveryState.MISSING
                if _BASENAME not in self._check_children():
                    return InferenceRecoveryState.RECOVERY_REQUIRED
                with store.pin(_BASENAME).stream() as stream:
                    record = _decode(stream.read(_MAX_BYTES + 1))
                store.assert_safe()
                return (InferenceRecoveryState.CLEAN if record.phase == "clean"
                        else InferenceRecoveryState.RECOVERY_REQUIRED)
        except StoreBusy:
            return InferenceRecoveryState.BUSY
        except StoreOwnershipUncertain:
            raise
        except (StoreOwnershipError, OSError, InferenceRecoveryRequired):
            return InferenceRecoveryState.RECOVERY_REQUIRED

    @contextmanager
    def lease(self, *, create: bool = True):
        with ExitStack() as stack:
            try:
                store = stack.enter_context(self._store.lease(create=create))
            except StoreBusy:
                raise
            except StoreOwnershipUncertain:
                raise
            except (StoreOwnershipError, OSError):
                raise InferenceRecoveryRequired() from None
            if store is None:
                raise InferenceRecoveryRequired()
            self._leased = True
            self._write_failed = False
            try:
                children = self._check_children()
                missing = _BASENAME not in children
                if missing and not create:
                    raise InferenceRecoveryRequired()
                try:
                    # Pin once, with write access, without truncating existing bytes.
                    pin = store.pin(_BASENAME, writable=True, create=missing)
                    self._stream = pin.stream("r+b")
                    stack.callback(self._close_stream, self._stream)
                    if not missing:
                        self._record = _decode(self._stream.read(_MAX_BYTES + 1))
                except (StoreOwnershipError, OSError):
                    raise InferenceRecoveryRequired() from None
                if missing:
                    self._write(InferenceRunRecord(0, None, "clean", None, None, None, None, None))
                if self._record.phase != "clean":
                    raise InferenceRecoveryRequired()
                yield self
            finally:
                self._stream = None
                self._leased = False

    @staticmethod
    def _close_stream(stream):
        try:
            stream.close()
        except OSError:
            raise InferenceJournalError("JOURNAL_WRITE_FAILED") from None

    @property
    def record(self) -> InferenceRunRecord:
        if not self._leased or self._record is None:
            raise InferenceJournalError("JOURNAL_LEASE_REQUIRED")
        return self._record

    def _require_writable(self):
        if not self._leased or self._stream is None:
            raise InferenceJournalError("JOURNAL_LEASE_REQUIRED")
        if self._write_failed:
            raise InferenceJournalError("JOURNAL_WRITE_FAILED")

    def _check_children(self):
        try:
            names = {child.name for child in self._store.root.iterdir()}
        except OSError:
            raise InferenceRecoveryRequired() from None
        if MARKER not in names or names - {MARKER, _BASENAME}:
            raise InferenceRecoveryRequired()
        return names

    def _next_revision(self):
        if self.record.revision == _MAX_REVISION:
            raise InferenceJournalError("JOURNAL_REVISION_OVERFLOW")
        return self.record.revision + 1

    def _write(self, candidate):
        self._require_writable()
        raw = json.dumps({"schema_version": 1, **asdict(candidate)}, sort_keys=True,
                         separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
        if len(raw) > _MAX_BYTES:
            raise InferenceJournalError("JOURNAL_RECORD_INVALID")
        try:
            self._store.assert_safe()
            self._stream.seek(0)
            written = self._stream.write(raw)
            if type(written) is not int or written != len(raw):
                raise OSError()
            self._stream.truncate(len(raw))
            self._stream.flush()
            os.fsync(self._stream.fileno())
        except Exception:
            self._write_failed = True
            raise InferenceJournalError("JOURNAL_WRITE_FAILED") from None
        self._record = candidate
        return candidate

    def begin(self, *, catalog_id: str, profile_name: str,
              package_sid: str) -> InferenceRunRecord:
        self._require_writable()
        if self.record.phase != "clean":
            raise InferenceJournalError()
        if not _matches(_PROFILE, profile_name):
            raise InferenceJournalError("JOURNAL_RECORD_INVALID")
        candidate = InferenceRunRecord(self._next_revision(), profile_name[len("xuxia_local_"):],
                                       "active", catalog_id, profile_name, package_sid, None, None)
        self._check_children()
        return self._write(candidate)

    def attach_stage(self, run_id: str, *, name: str,
                     identity: tuple[int, int]) -> InferenceRunRecord:
        self._require_writable()
        current = self.record
        if current.phase != "active" or type(run_id) is not str or run_id != current.run_id:
            raise InferenceJournalError()
        if name is None or identity is None:
            raise InferenceJournalError("JOURNAL_RECORD_INVALID")
        # Validate before equality: bools must never alias integer identities.
        validated = replace(current, stage_name=name, stage_identity=identity)
        if current.stage_name is not None:
            if validated == current:
                return current
            raise InferenceJournalError()
        return self._write(replace(validated, revision=self._next_revision()))

    def complete(self, run_id: str) -> InferenceRunRecord:
        self._require_writable()
        current = self.record
        if type(run_id) is not str or run_id != current.run_id:
            raise InferenceJournalError()
        self._check_children()
        if current.phase == "clean":
            return current
        return self._write(replace(current, revision=self._next_revision(), phase="clean"))

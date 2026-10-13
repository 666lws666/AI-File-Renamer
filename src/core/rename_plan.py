"""M2 RenamePlan — pure data, frozen, zero I/O."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class SourceFingerprint:
    size_bytes: int
    mtime_ns: int


@dataclass(frozen=True)
class NativeFileIdentity:
    """Held native metadata, not a cryptographic or timeless identity proof."""
    volume_serial: int
    file_index: int
    creation_ticks: int

    def __post_init__(self):
        validate_native_identity(self)


def validate_native_identity(value):
    if type(value) is not NativeFileIdentity:
        raise ValueError("invalid_native_file_identity")
    volume, index, creation = (getattr(value, field, None) for field in
                               ("volume_serial", "file_index", "creation_ticks"))
    if (type(volume) is not int or not 0 <= volume < 2**32
            or type(index) is not int or not 0 <= index < 2**64
            or type(creation) is not int or not 0 <= creation < 2**64):
        raise ValueError("invalid_native_file_identity")


def validate_source_fingerprint(value):
    if type(value) is not SourceFingerprint:
        raise ValueError("invalid_source_fingerprint")
    size, mtime = (getattr(value, field, None) for field in ("size_bytes", "mtime_ns"))
    if type(size) is not int or size < 0 or type(mtime) is not int or mtime < 0:
        raise ValueError("invalid_source_fingerprint")


@dataclass(frozen=True)
class FileMoveEvidence:
    version: int
    identity: NativeFileIdentity
    fingerprint: SourceFingerprint
    allowed_roots: tuple[str, ...]

    def __post_init__(self):
        validate_move_evidence(self)


def validate_move_evidence(value):
    if type(value) is not FileMoveEvidence:
        raise ValueError("invalid_file_move_evidence")
    version = getattr(value, "version", None)
    if type(version) is not int or version != 1:
        raise ValueError("invalid_file_move_evidence")
    validate_native_identity(getattr(value, "identity", None))
    try:
        validate_source_fingerprint(getattr(value, "fingerprint", None))
    except ValueError:
        raise ValueError("invalid_file_move_evidence") from None
    roots = getattr(value, "allowed_roots", None)
    if (type(roots) is not tuple or not 1 <= len(roots) <= 2000
            or any(type(root) is not str or not root.strip() or len(root) > 4096 or "\x00" in root for root in roots)
            or len({root.replace("/", "\\").casefold() for root in roots}) != len(roots)):
        raise ValueError("invalid_file_move_evidence")


def encode_move_evidence(value):
    validate_move_evidence(value)
    return {"version": value.version,
            "identity": {"volume_serial": value.identity.volume_serial, "file_index": value.identity.file_index,
                         "creation_ticks": value.identity.creation_ticks},
            "fingerprint": {"size_bytes": value.fingerprint.size_bytes, "mtime_ns": value.fingerprint.mtime_ns},
            "allowed_roots": list(value.allowed_roots)}


def decode_move_evidence(data):
    if (type(data) is not dict or data.keys() != {"version", "identity", "fingerprint", "allowed_roots"}
            or type(data["identity"]) is not dict
            or data["identity"].keys() != {"volume_serial", "file_index", "creation_ticks"}
            or type(data["fingerprint"]) is not dict
            or data["fingerprint"].keys() != {"size_bytes", "mtime_ns"}
            or type(data["allowed_roots"]) is not list):
        raise ValueError("invalid_file_move_evidence")
    return FileMoveEvidence(data["version"], NativeFileIdentity(**data["identity"]),
                            SourceFingerprint(**data["fingerprint"]), tuple(data["allowed_roots"]))


@dataclass(frozen=True)
class RenamePlan:
    task_id: str
    source_path: str
    source_fingerprint: SourceFingerprint
    target_name: str
    target_parent: str
    extension: str
    batch_id: str = ""

    @property
    def target_path(self) -> str:
        import os
        return os.path.join(self.target_parent, self.target_name)


@dataclass(frozen=True)
class PreflightResult:
    can_execute: bool
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    resolved_source: Optional[str] = None
    resolved_target: Optional[str] = None
    allowed_roots: tuple[str, ...] = ()


@dataclass
class BatchResult:
    task_id: str
    batch_id: str
    success: bool
    error: Optional[str] = None
    new_path: str = ""
    recovery_required: bool = False
    move_evidence: FileMoveEvidence | None = None
    source_fingerprint: SourceFingerprint | None = None
    owned_residue_paths: tuple[str, ...] = ()


def validate_owned_residue_paths(value):
    """Bounded diagnostic paths, never authority for replay or removal."""
    if (type(value) is not tuple or len(value) > 8
            or any(type(path) is not str or not path.strip() or len(path) > 4096 or '\x00' in path
                   for path in value) or len(set(value)) != len(value)):
        raise ValueError('invalid_owned_residue_paths')


RECOVERY_REASONS = frozenset({
    'fileops.error.nativeRecovery', 'fileops.error.unknownOutcome',
    'fileops.error.historySaveRecovery', 'fileops.error.workspaceSaveRecovery',
    'fileops.error.fingerprintRecovery',
})

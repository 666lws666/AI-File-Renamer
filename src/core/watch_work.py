"""Immutable, non-serialized Watch admission values and pure lexical validation."""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from threading import Event

from src.core.processing_analysis import AnalysisWork
from src.core.processing_authority import ProcessingSnapshot
from src.core.rename_plan import SourceFingerprint
from src.core.watch_config import WatchConfig


def valid_admission_fields(config, incarnation, source_path, event_id) -> bool:
    """Bounded field checks only. Never reconstruct WatchConfig or touch disk."""
    if type(config) is not WatchConfig:
        return False
    if type(config.template_id) is not str or len(config.template_id) > 128 or "\0" in config.template_id:
        return False
    for value in (config.id, incarnation, event_id):
        if type(value) is not str or not value or len(value) > 128 or "\0" in value:
            return False
    for value in (source_path, config.source_dir, config.target_dir):
        if type(value) is not str or len(value) > 32768 or "\0" in value:
            return False
    if not source_path or not os.path.isabs(source_path):
        return False
    if config.target_dir and not os.path.isabs(config.target_dir):
        return False
    root = os.path.normcase(os.path.normpath(config.source_dir))
    path = os.path.normcase(os.path.normpath(source_path))
    if not os.path.isabs(root) or path == root:
        return False
    try:
        if os.path.commonpath((root, path)) != root:
            return False
    except ValueError:
        return False
    return config.recursive or os.path.dirname(path) == root


@dataclass(frozen=True)
class WatchAdmission:
    work: AnalysisWork = field(repr=False)
    watch_id: str
    watch_config: WatchConfig = field(repr=False)
    incarnation: str
    event_id: str
    cancel_event: Event = field(repr=False)


@dataclass(frozen=True)
class WatchAdmissionFailure:
    snapshot: ProcessingSnapshot
    watch_id: str
    watch_config: WatchConfig = field(repr=False)
    incarnation: str
    event_id: str
    reason: str


@dataclass(frozen=True)
class StableWatchEvent:
    admission: WatchAdmission = field(repr=False)
    fingerprint: SourceFingerprint
    protected_extension: str
    target_dir: str = field(repr=False)
    _delivery_identity: object = field(repr=False, compare=False)

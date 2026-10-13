"""Aggregated local and cloud capability health for the System Status UI."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from PySide6.QtCore import QObject, Property, Signal, Slot


class StatusLevel(str, Enum):
    READY = "ready"
    CHECKING = "checking"
    ATTENTION = "attention"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ComponentStatus:
    id: str
    name: str
    status: StatusLevel
    detail: str = ""
    last_checked: str = ""


@dataclass(frozen=True)
class SystemStatus:
    overall: StatusLevel
    components: tuple[ComponentStatus, ...]


def _safe_detail(value: object) -> str:
    text = str(value)
    text = re.sub(r"(?i)[A-Z]:[/\\]Users[/\\][^\s]+", "<redacted-path>", text)
    text = re.sub(r"(?i)(bearer\s+|api[_-]?key\s*[=:]\s*)\S+", r"\1<redacted>", text)
    return text[:240]


class StatusController(QObject):
    stateChanged = Signal()

    def __init__(self, probes: dict[str, Callable[[], ComponentStatus]] | None = None,
                 *, clock: Callable[[], float] | None = None,
                 ttl_seconds: float = 60.0, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._probes = dict(probes or {})
        self._clock = clock or time.monotonic
        self._ttl = float(ttl_seconds)
        self._cached: SystemStatus | None = None
        self._cached_at = float("-inf")

    @staticmethod
    def _overall(rows: tuple[ComponentStatus, ...]) -> StatusLevel:
        if not rows or all(row.status is StatusLevel.UNAVAILABLE for row in rows):
            return StatusLevel.UNAVAILABLE
        if any(row.status is StatusLevel.CHECKING for row in rows):
            return StatusLevel.CHECKING
        if any(row.status in {StatusLevel.ATTENTION, StatusLevel.UNAVAILABLE} for row in rows):
            return StatusLevel.ATTENTION
        return StatusLevel.READY

    def check_all(self, *, force: bool = False) -> SystemStatus:
        now = self._clock()
        if not force and self._cached is not None and now - self._cached_at < self._ttl:
            return self._cached
        rows = []
        for component_id, probe in self._probes.items():
            try:
                row = probe()
                if not isinstance(row, ComponentStatus):
                    raise TypeError("invalid component status")
                rows.append(row)
            except Exception as error:
                rows.append(ComponentStatus(
                    component_id, component_id, StatusLevel.UNAVAILABLE,
                    _safe_detail(error), "",
                ))
        result = SystemStatus(self._overall(tuple(rows)), tuple(rows))
        self._cached = result
        self._cached_at = now
        self.stateChanged.emit()
        return result

    @Slot()
    def checkAll(self) -> None:
        self.check_all(force=True)

    @Property(str, notify=stateChanged)
    def overall(self) -> str:
        return (self._cached.overall if self._cached else StatusLevel.CHECKING).value

    @Property("QVariantList", notify=stateChanged)
    def components(self) -> list[dict]:
        rows = self._cached.components if self._cached else ()
        return [{
            "id": row.id, "name": row.name, "status": row.status.value,
            "detail": row.detail, "lastChecked": row.last_checked,
        } for row in rows]
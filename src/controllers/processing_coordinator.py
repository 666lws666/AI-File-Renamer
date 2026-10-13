"""Qt-owned processing choices; no engine launch or implicit user-directory I/O.

Writer completion only posts to Qt. Writer drain and Qt acknowledgement drain
are deliberately separate boundaries; keep this object alive until both finish.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QCoreApplication, QObject, Property, QThread, Qt, Signal, Slot

from src.core.processing_authority import (
    LocalReadiness, ProcessingAuthority, ProcessingSnapshot,
)
from src.core.processing_intent_store import ProcessingIntentStore, ProcessingIntentWriter


class ProcessingCoordinator(QObject):
    stateChanged = Signal()
    _choiceCompleted = Signal(object, bool)

    def __init__(self, store: ProcessingIntentStore, *,
                 writer_factory=ProcessingIntentWriter, parent=None):
        super().__init__(parent)
        self._require_owner()
        startup = store.load()
        self._authority = ProcessingAuthority(initial_mode=startup.mode,
            initial_revision=startup.revision, startup_error=startup.startup_error)
        self._store = store
        self._open = True
        self._pending = []
        self._failed = None
        self._submitting = 0
        self._draining = False
        self._choiceCompleted.connect(self._consume_completion, Qt.ConnectionType.QueuedConnection)
        self._writer = writer_factory(store, self._authority,
                                      completion_callback=self._post_completion)

    def _require_owner(self):
        if QThread.currentThread() != self.thread():
            raise RuntimeError("PROCESSING_OWNER_THREAD_REQUIRED")

    def _require_open(self):
        self._require_owner()
        if not self._open:
            raise RuntimeError("PROCESSING_COORDINATOR_CLOSED")

    @property
    def authority(self) -> ProcessingAuthority:
        return self._authority

    @property
    def snapshot(self) -> ProcessingSnapshot:
        return self._authority.snapshot()

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def pending_ack_count(self) -> int:
        return len(self._pending)

    @Property(str, notify=stateChanged)
    def processingMode(self):
        return self.snapshot.mode.value

    @Property(str, notify=stateChanged)
    def localReadiness(self):
        return self.snapshot.local_readiness.value

    @Property(str, notify=stateChanged)
    def persistenceStatus(self):
        return self.snapshot.persistence_status.value

    @Property(str, notify=stateChanged)
    def errorCode(self):
        return self.snapshot.error_code or ""

    @Property(int, notify=stateChanged)
    def committedAttemptCount(self):
        return self.snapshot.committed_attempts

    @Property(bool, notify=stateChanged)
    def admissionOpen(self):
        return self._open

    def _submit(self, intent):
        # Reserve before publishing: a synchronous stateChanged handler may
        # close, drain or select another choice before submit returns.
        self._pending.append(intent)
        self._submitting += 1
        try:
            self.stateChanged.emit()
            return self._writer.submit(intent)
        finally:
            self._submitting -= 1

    @Slot(result=bool)
    def selectLocal(self):
        self._require_open()
        self._failed = None
        try:
            intent = self._authority.select_local().intent
        except Exception:
            # Revision exhaustion still closes CLOUD in the authority.
            self.stateChanged.emit()
            raise
        return self._submit(intent)

    @Slot(result=bool)
    def selectCloud(self):
        self._require_open()
        self._failed = None
        return self._submit(self._authority.request_cloud_choice())

    @Slot(result=bool)
    def retryChoice(self):
        self._require_open()
        intent = self._failed
        if intent is None or not self._authority.is_current_choice(intent):
            return False
        self._failed = None
        return self._submit(intent)

    def bind_cloud_engine(self, fingerprint):
        self._require_open()
        snapshot = self._authority.bind_cloud_engine(fingerprint)
        self.stateChanged.emit()
        return snapshot

    def invalidate_work(self):
        self._require_open()
        snapshot = self._authority.invalidate_work()
        self.stateChanged.emit()
        return snapshot

    def publish_catalog(self, source, catalog):
        """Publish one complete pure catalog before any reentrant public callback."""
        from src.core.analysis_catalog import AnalysisCatalog
        from src.core.processing_identity import cloud_engine_fingerprint
        self._require_open()
        if type(catalog) is not AnalysisCatalog:
            raise ValueError("Invalid analysis catalog")
        fingerprint = (cloud_engine_fingerprint(catalog.active_profile)
                       if catalog.active_profile is not None else None)
        with source.guard():
            self._authority.invalidate_work()
            source.install(catalog)
            if fingerprint is None:
                snapshot = self._authority.unbind_cloud_engine()
            else:
                snapshot = self._authority.bind_cloud_engine(fingerprint)
        self.stateChanged.emit()
        return snapshot

    def publish_local_state(self, expected_generation, state: LocalReadiness,
                            *, engine_fingerprint=None):
        self._require_open()
        accepted = self._authority.set_local_state(expected_generation, state,
            engine_fingerprint=engine_fingerprint)
        if accepted:
            self.stateChanged.emit()
        return accepted

    def _post_completion(self, intent, persisted):
        # Runs on the Python writer (or submit rejection) thread. No authority
        # or public-state mutation is permitted at this boundary.
        self._choiceCompleted.emit(intent, persisted)

    @Slot(object, bool)
    def _consume_completion(self, intent, persisted):
        self._require_owner()
        for index, expected in enumerate(self._pending):
            if expected is intent:
                del self._pending[index]
                break
        else:
            return
        if self._open and self._authority.is_current_choice(intent):
            self._authority.complete_choice(intent, persisted=persisted)
            self._failed = None if persisted else intent
        # Closing consumes acknowledgements without completing a CLOUD choice.
        self.stateChanged.emit()

    def begin_close(self):
        self._require_owner()
        if not self._open:
            return
        self._open = False
        self._failed = None
        self._authority.close_admission()
        self.stateChanged.emit()

    def drain_choice_writer(self, *, deadline):
        self._require_owner()
        try:
            valid_deadline = type(deadline) in (int, float) and math.isfinite(deadline)
        except OverflowError:
            valid_deadline = False
        if not valid_deadline:
            raise ValueError("PROCESSING_DRAIN_DEADLINE_ERROR")
        if self._draining:
            return False
        self._draining = True
        try:
            self.begin_close()
            if self._submitting:
                self._writer.close(timeout=0)
                return False
            while True:
                remaining = max(0.0, deadline - time.monotonic())
                writer_done = self._writer.close(timeout=min(0.01, remaining))
                if time.monotonic() < deadline:
                    # No coordinator/writer/authority lock is held here.
                    QCoreApplication.processEvents()
                if writer_done and not self._pending:
                    return True
                if time.monotonic() >= deadline:
                    return False
        finally:
            self._draining = False

"""Production Batch workspace controller for the QML shell.

The controller owns only local workspace state and delegates user-file writes to
RenameExecutor.  AI analysis is injected as a callable, which makes the full
pipeline testable without network access or credentials.
"""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import threading
import inspect
import uuid
from concurrent.futures import CancelledError, ThreadPoolExecutor
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    QThread,
    Property,
    Qt,
    QUrl,
    Signal,
    Slot,
)

from src.core.preflight_service import PreflightService
from src.core.rename_executor import RenameExecutor
from src.core.rename_history import RenameHistory
from src.core.rename_plan import RenamePlan, SourceFingerprint
from src.core.undo_manager import UndoManager
from src.core.template_model import OutputLanguage
from src.core.smart_naming import SMART_POLICY_VERSION
from src.core.batch_analysis import BatchAnalysisService, BatchAnalysisError
from src.core.processing_analysis import AnalysisWork, AnalysisOutcome, CloudAnalysisCoverage
from src.services.local_ai.preparation_protocol import PreparationCoverage, WARNING_CODES
from src.core.processing_authority import (
    ProcessingMode, ProcessingSuperseded, LocalProcessingUnavailable, CloudDispatchBlocked,
)
from src.utils.constants import SUPPORTED_EXTENSIONS
from src.controllers.managed_file_operation_lane import ManagedFileOperationLane
from src.controllers.batch_file_operations import BatchFileOperations


STATES = ("pending", "analyzing", "review_pending", "undone", "applied", "failed", "cancelled", "ignored")
LABELS = {
    "pending": "待处理", "analyzing": "分析中", "review_pending": "待确认",
    "undone": "已撤销", "applied": "已应用", "failed": "失败",
    "cancelled": "已取消", "ignored": "已忽略",
}

# Finite pending/running admissions, not a limit on accepted/history rows.
MAX_PENDING_WORK = 1000


@dataclass(frozen=True, slots=True)
class _ManagedCompletion:
    task_id: str
    attempt_id: str
    work: AnalysisWork = field(repr=False)
    context: object = field(repr=False)
    outcome: AnalysisOutcome | None = field(repr=False)
    failure: str


class BatchTaskListModel(QAbstractListModel):
    _KEYS = (
        "taskId", "originalName", "suggestedName", "extension", "status",
        "statusLabel", "selected", "thumbnailKind", "errorMessage", "canApply",
        "canRetry", "canIgnore", "canCancel", "canUndo", "isEditing",
        "validationError", "fileOperationPending", "fileOperationRecoveryRequired",
    )
    _ROLES = {Qt.UserRole + index + 1: QByteArray(key.encode("utf-8"))
              for index, key in enumerate(_KEYS)}
    _ROLE_KEYS = {role: key for role, key in zip(_ROLES, _KEYS)}

    def __init__(self, tasks: list[dict[str, Any]], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tasks = tasks

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._tasks)

    def roleNames(self):
        return self._ROLES

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._tasks):
            return None
        key = self._ROLE_KEYS.get(role)
        return self._tasks[index.row()].get(key) if key else None

    def reset(self, tasks: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self._tasks = tasks
        self.endResetModel()


class BatchWorkspaceController(QObject):
    tasksChanged = Signal()
    selectionChanged = Signal()
    progressChanged = Signal()
    filterChanged = Signal()
    targetDirectoryChanged = Signal()
    templateChanged = Signal()
    namingLanguageChanged = Signal()
    namingModeChanged = Signal()
    analysisCompleted = Signal(str, str, bool, str)
    importCompleted = Signal(int, int, int, int)
    importOverflow = Signal(int)
    _managedCompleted = Signal(object)

    def __init__(
        self,
        file_scanner: Any = None,
        parent: QObject | None = None,
        *,
        workspace_path: str | Path | None = None,
        history_path: str | Path | None = None,
        analyzer: Callable[[str, str], str] | None = None,
        background: bool = True,
        max_workers: int = 2,
        pending_work_limit: int = MAX_PENDING_WORK,
        file_operation_lane: ManagedFileOperationLane | None = None,
    ) -> None:
        super().__init__(parent)
        self._scanner = file_scanner  # backward-compatible M2 injection
        self._workspace_path = Path(workspace_path) if workspace_path else None
        self._history_path = Path(history_path) if history_path else None
        self._analyzer = analyzer
        self._managed_analyzer = None
        self._processing_authority = None
        self._analysis_work: dict[str, AnalysisWork] = {}
        self._submitted_futures = {}
        if type(pending_work_limit) is not int or not 1 <= pending_work_limit <= MAX_PENDING_WORK:
            raise ValueError("Invalid Batch pending work limit")
        self._pending_work_limit = pending_work_limit
        self._last_import_error = ""
        self._cancellation_events: dict[str, threading.Event] = {}
        self._analysis_attempts: dict[str, str] = {}
        self._closed = False
        self._background = bool(background)
        self._max_workers = max(1, int(max_workers))
        self._pool = ThreadPoolExecutor(max_workers=self._max_workers) if background else None
        self._tasks: list[dict[str, Any]] = []
        self._model = BatchTaskListModel(self._tasks, self)
        self._search = ""
        self._filter = "all"
        self._target_directory = ""
        self._template_options: list[dict[str, str]] = []
        self._selected_template_id = ""
        self._naming_language = ""
        self._naming_mode = "template"
        self._apply_active = False
        self._apply_current = 0
        self._apply_total = 0
        self._apply_success = 0
        self._apply_failed = 0
        self._file_operations = (BatchFileOperations(self, file_operation_lane)
                                 if file_operation_lane is not None else None)
        self.analysisCompleted.connect(self._on_analysis_completed)
        self._managedCompleted.connect(self._accept_managed_completion, Qt.QueuedConnection)
        self._load_workspace()
        for task in list(self._tasks):
            if task["status"] in {"pending", "analyzing"} and not self._file_operation_locked(task['taskId']):
                task["status"] = "pending"
                self._refresh_task(task)
                self._start_analysis(task["taskId"])

    # QML model/properties -------------------------------------------------
    @Property(QObject, constant=True)
    def tasksModel(self): return self._model

    @Property(int, notify=tasksChanged)
    def totalCount(self): return len(self._tasks)

    @property
    def total_count(self): return self.totalCount

    @Property(int, notify=filterChanged)
    def visibleCount(self): return len(self._visible_ids())

    @property
    def visible_count(self): return self.visibleCount

    @Property(int, notify=selectionChanged)
    def selectedCount(self): return sum(1 for task in self._tasks if task.get("selected"))

    @property
    def selected_count(self): return self.selectedCount

    @Property(int, notify=selectionChanged)
    def hiddenSelectedCount(self):
        visible = set(self._visible_ids())
        return sum(1 for task in self._tasks if task.get("selected") and task["taskId"] not in visible)

    @Property(str, notify=selectionChanged)
    def selectAllState(self):
        visible = self._visible_ids()
        selected_visible = sum(1 for task in self._tasks if task["taskId"] in visible and task.get("selected"))
        if visible and selected_visible == len(visible): return "all"
        return "partial" if selected_visible else "none"

    @Property(str, notify=filterChanged)
    def searchText(self): return self._search

    @Property(str, notify=filterChanged)
    def statusFilter(self): return self._filter

    @Property(str, notify=targetDirectoryChanged)
    def targetDirectory(self): return self._target_directory

    @Property("QVariantList", notify=templateChanged)
    def templateOptions(self): return copy.deepcopy(self._template_options)

    @Property(str, notify=templateChanged)
    def selectedTemplateId(self): return self._selected_template_id

    @Property(str, notify=namingLanguageChanged)
    def namingLanguage(self): return self._naming_language

    @Property(str, notify=namingModeChanged)
    def namingMode(self): return self._naming_mode

    @Slot(str)
    def setNamingMode(self, mode: str) -> None:
        self._require_owner()
        if mode not in {"template", "smart"}:
            raise ValueError("smart.error.unsupportedPolicy")
        if mode != self._naming_mode:
            self._naming_mode = mode
            self.namingModeChanged.emit()

    @Slot(str)
    def setNamingLanguage(self, language: str) -> None:
        self._require_owner()
        value = OutputLanguage(language).value if language else ""
        if value != self._naming_language:
            self._naming_language = value
            self.namingLanguageChanged.emit()

    def _effective_naming_language(self, mode: str | None = None) -> str:
        if self._naming_language:
            return self._naming_language
        if (mode or self._naming_mode) == "smart":
            return OutputLanguage.ZH.value
        option = next((item for item in self._template_options
                       if item['id'] == self._selected_template_id), {})
        return OutputLanguage(option.get('outputLanguage', 'zh')).value

    @Property(bool, notify=progressChanged)
    def applyInProgress(self): return self._apply_active

    @Property(int, notify=progressChanged)
    def applyCurrent(self): return self._apply_current

    @Property(int, notify=progressChanged)
    def applyTotal(self): return self._apply_total

    @Property(int, notify=progressChanged)
    def applySuccess(self): return self._apply_success

    @Property(int, notify=progressChanged)
    def applyFailed(self): return self._apply_failed

    @Property(float, notify=progressChanged)
    def applyProgress(self):
        return self._apply_current / self._apply_total if self._apply_total else 0.0

    @property
    def task_ids(self): return tuple(task["taskId"] for task in self._tasks)

    def task_snapshot(self, task_id: str) -> dict[str, Any]:
        task = self._find_task(task_id)
        if task is None: raise KeyError(task_id)
        return copy.deepcopy(task)

    @property
    def pending_worker_count(self):
        """Both runner exit and completion signal emission define idle."""
        return sum(not self._submission_drained(future, owner)
                   for future, owner in self._submitted_futures.items())

    @property
    def workers_idle(self):
        return (self.pending_worker_count == 0 and
                (self._file_operations is None or self._file_operations.workers_idle))

    @property
    def closed(self):
        return self._closed

    @Property(str, notify=importOverflow)
    def lastImportError(self):
        return self._last_import_error

    def _require_owner(self, *, always=False):
        if (always or self._managed_analyzer is not None or self._file_operations is not None) and QThread.currentThread() != self.thread():
            raise RuntimeError("Managed Batch requires its owning Qt thread")

    def _prune_workers(self):
        self._submitted_futures = {future: owner for future, owner in self._submitted_futures.items()
                                   if not self._submission_drained(future, owner)}

    @staticmethod
    def _submission_drained(future, owner):
        return future.done() and owner[2].is_set()

    def _pending_admissions(self):
        rows = sum(task["status"] in {"pending", "analyzing"} for task in self._tasks)
        orphans = sum(not self._submission_drained(future, owner)
                      and self._analysis_attempts.get(owner[0]) != owner[1]
                      for future, owner in self._submitted_futures.items())
        return rows + orphans

    def configure_templates(self, options, selected_id: str = "") -> None:
        self._require_owner()
        safe = [
            {"id": str(item.get("id", "")), "name": str(item.get("name", "")),
             "outputLanguage": OutputLanguage(item.get("outputLanguage", "zh")).value}
            for item in options
            if item.get("id") and item.get("name")
        ]
        valid_ids = {item["id"] for item in safe}
        preferred = self._selected_template_id or selected_id
        resolved_id = preferred if preferred in valid_ids else (
            safe[0]["id"] if safe else ""
        )
        if safe == self._template_options and resolved_id == self._selected_template_id:
            return
        self._template_options = safe
        self._selected_template_id = resolved_id
        if self._analyzer is not None and hasattr(self._analyzer, "set_template_id"):
            self._analyzer.set_template_id(self._selected_template_id)
        self.templateChanged.emit()
        self._save_workspace()

    @Slot(str)
    def setSelectedTemplate(self, template_id: str) -> None:
        self._require_owner()
        if template_id not in {item["id"] for item in self._template_options}:
            return
        if template_id == self._selected_template_id:
            return
        self._selected_template_id = template_id
        if self._analyzer is not None and hasattr(self._analyzer, "set_template_id"):
            self._analyzer.set_template_id(template_id)
        self.templateChanged.emit()
        self._save_workspace()

    def set_analyzer(self, analyzer) -> None:
        """Explicit legacy callable injection; never a managed fallback."""
        self._require_owner()
        if self._closed:
            return
        if self._managed_analyzer is not None and self._analysis_attempts:
            raise RuntimeError("Batch analysis is already active")
        self._managed_analyzer = self._processing_authority = None
        self._analyzer = analyzer
        if analyzer is not None and hasattr(analyzer, "set_template_id"):
            analyzer.set_template_id(self._selected_template_id)
        for task in list(self._tasks):
            if task["status"] == "pending":
                self._start_analysis(task["taskId"])

    def set_managed_analyzer(self, service, authority):
        """Install authentic capture/run route before restored pending work starts."""
        self._require_owner(always=True)
        if self._closed:
            return
        if not isinstance(service, BatchAnalysisService) or service._authority is not authority or not service._managed:
            raise ValueError("Invalid managed Batch analyzer")
        if self._analysis_attempts:
            raise RuntimeError("Batch analysis is already active")
        self._analyzer = None
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=self._max_workers)
        self._managed_analyzer, self._processing_authority = service, authority
        for task in list(self._tasks):
            if task["status"] == "pending":
                self._start_analysis(task["taskId"])

    # Import/analyze -------------------------------------------------------
    @Slot("QVariantList")
    def addPaths(self, paths):
        self._require_owner()
        self.add_files([self._local_path(path) for path in paths])

    @Slot("QVariantList")
    def importDropped(self, paths):
        self._require_owner()
        files: list[str] = []
        for raw in paths:
            path = self._local_path(raw)
            if os.path.isdir(path):
                try:
                    files.extend(str(item) for item in Path(path).rglob("*") if item.is_file())
                except OSError:
                    files.append(path)  # count unreadable directory, without exposing its path
            else:
                files.append(path)
        self.add_files(files)

    def add_files(self, paths: list[str]):
        self._require_owner()
        if self._closed:
            return
        existing = {os.path.normcase(os.path.abspath(task["originalName"])) for task in self._tasks}
        added: list[str] = []
        duplicate = unsupported = unavailable = 0
        overflow = 0
        capacity = self._pending_work_limit - self._pending_admissions()
        candidate = copy.deepcopy(self._tasks)
        # One import shares a policy and language, even if the next import uses
        # another mode. Existing tasks and saved templates are never rewritten.
        mode = self._naming_mode
        language = self._effective_naming_language(mode)
        for raw in paths:
            path = os.path.abspath(raw)
            if not os.path.isfile(path):
                unavailable += 1
                continue
            extension = Path(path).suffix.lower()
            if extension not in SUPPORTED_EXTENSIONS:
                unsupported += 1
                continue
            normalized = os.path.normcase(path)
            if normalized in existing:
                duplicate += 1
                continue
            if self._managed_analyzer is not None and len(added) >= capacity:
                overflow += 1
                continue
            try:
                stat = os.stat(path)
            except OSError:
                unavailable += 1
                continue
            task_id = f"task-{uuid.uuid4().hex}"
            task = self._new_task(task_id, path, extension, stat.st_size, stat.st_mtime_ns)
            task['templateId'] = self._selected_template_id if mode == "template" else ""
            task['outputLanguage'] = language
            task['namingMode'] = mode
            task['namingPolicyVersion'] = SMART_POLICY_VERSION
            candidate.append(task)
            existing.add(normalized)
            added.append(task_id)
        if added:
            self._commit_tasks(candidate)
        self.importCompleted.emit(len(added), duplicate, unsupported, unavailable)
        if self._managed_analyzer is not None:
            self._last_import_error = "batch.error.queueFull" if overflow else ""
            self.importOverflow.emit(overflow)
        for task_id in added: self._start_analysis(task_id)

    @Slot(str, bool)
    def addFolder(self, folder: str, recursive: bool = True):
        self._require_owner()
        root = Path(self._local_path(folder))
        if not root.is_dir():
            self.importCompleted.emit(0, 0, 0, 1)
            return
        iterator = root.rglob("*") if recursive else root.glob("*")
        self.add_files([str(path) for path in iterator if path.is_file()])

    def _start_analysis(self, task_id: str) -> None:
        self._require_owner()
        if self._closed or self._file_operation_locked(task_id):
            return
        task = self._find_task(task_id)
        if task is None or task["status"] not in {"pending", "failed", "cancelled", "ignored"}: return
        if self._managed_analyzer is not None:
            self._start_managed_analysis(task)
            return
        if self._analyzer is None:
            return  # honest pending state until a provider is configured
        changes = {"status": "analyzing", "errorMessage": ""}
        mode = task["namingMode"]
        if mode == "template" and not task.get("templateId"):
            changes["templateId"] = self._selected_template_id
        if not task.get("outputLanguage"):
            changes["outputLanguage"] = self._effective_naming_language(mode)
        self._update_task(task_id, **changes)
        task = self._find_task(task_id)
        if self._closed or task is None or task["status"] != "analyzing":
            return
        attempt_id = uuid.uuid4().hex
        cancellation_event = threading.Event()
        self._analysis_attempts[task_id] = attempt_id
        self._cancellation_events[task_id] = cancellation_event
        path = task["originalName"]
        # Snapshot on the Qt thread before a worker can observe another import.
        choices = (task.get('templateId', ''), task['outputLanguage'],
                   mode, task['namingPolicyVersion'])
        if self._background:
            bridge_done = threading.Event()
            future = self._pool.submit(self._run_analysis, path, task_id,
                                       cancellation_event, choices)
            self._prune_workers()
            self._submitted_futures[future] = (task_id, attempt_id, bridge_done)
            future.add_done_callback(
                lambda done, tid=task_id, aid=attempt_id, drained=bridge_done:
                    self._emit_future(tid, aid, done, drained))
        else:
            try:
                suggestion = self._run_analysis(path, task_id, cancellation_event, choices)
            except Exception as error:
                self._on_analysis_completed(task_id, attempt_id, False, str(error))
            else:
                self._on_analysis_completed(task_id, attempt_id, True, suggestion)

    def _start_managed_analysis(self, task):
        self._prune_workers()
        task_id = task["taskId"]
        if self.pending_worker_count >= self._pending_work_limit:
            self._commit_managed_task(task_id, dict(status="failed", errorMessage="batch.error.queueFull"))
            return
        attempt_id, event = uuid.uuid4().hex, threading.Event()
        service = self._managed_analyzer
        try:
            work = service.capture_work(task["originalName"], task_id,
                task_attempt_id=attempt_id, task_cancel_event=event,
                template_id=task.get("templateId", ""), output_language=task.get("outputLanguage", ""),
                naming_mode=task["namingMode"], naming_policy_version=task["namingPolicyVersion"],
                defer_execution_deadline=True)
        except Exception as error:
            event.set()
            self._commit_managed_task(task_id, dict(status="failed", errorMessage=self._managed_failure(error)))
            return
        if not self._commit_managed_task(task_id,
                dict(status="analyzing", errorMessage="", analysisCoverage=None,
                     analysisCoverageType="", analysisWarningCodes=[]), install_work=work):
            return
        if self._closed or self._analysis_work.get(task_id) is not work:
            return
        bridge_done = threading.Event()  # Before submit, including already-done Futures.
        try:
            future = self._pool.submit(self._run_managed_analysis, service, work)
        except Exception:
            self._managedCompleted.emit(_ManagedCompletion(task_id, attempt_id, work, work.context,
                                                           None, "batch.error.analysisFailed"))
            return
        self._submitted_futures[future] = (task_id, attempt_id, bridge_done)
        future.add_done_callback(lambda done, issued=work, drained=bridge_done:
                                 self._emit_managed_future(issued, done, drained))

    @staticmethod
    def _managed_failure(error, work=None):
        if isinstance(error, (ProcessingSuperseded, CancelledError)):
            return "batch.error.processingChanged"
        if isinstance(error, LocalProcessingUnavailable):
            return "batch.error.localUnavailable"
        if isinstance(error, CloudDispatchBlocked):
            return "batch.error.cloudBlocked"
        if isinstance(error, BatchAnalysisError) and str(error) in {
                "Local analysis timed out", "Cloud analysis queue timed out"}:
            return "batch.error.timeout"
        if isinstance(error, BatchAnalysisError) and str(error) in {
                "Local analysis queue is full", "Cloud analysis queue is full"}:
            return "batch.error.queueFull"
        if work is not None:
            return "batch.error.localFailed" if work.context.mode is ProcessingMode.LOCAL else "batch.error.cloudFailed"
        return "batch.error.analysisFailed"

    @classmethod
    def _run_managed_analysis(cls, service, work):
        try:
            outcome = service.run_prepared(work)
        except Exception as error:
            return _ManagedCompletion(work.task_id, work.task_attempt_id, work, work.context,
                                      None, cls._managed_failure(error, work))
        return _ManagedCompletion(work.task_id, work.task_attempt_id, work, work.context, outcome, "")

    def _emit_managed_future(self, work, future, bridge_done):
        try:
            try:
                completion = future.result()
            except Exception as error:
                completion = _ManagedCompletion(work.task_id, work.task_attempt_id, work, work.context,
                                                None, self._managed_failure(error, work))
            self._managedCompleted.emit(completion)
        finally:
            bridge_done.set()  # Worker touches only this synchronized completion fact.

    @Slot(object)
    def _accept_managed_completion(self, completion):
        self._require_owner(always=True)
        self._prune_workers()
        if self._closed or self._managed_analyzer is None or type(completion) is not _ManagedCompletion:
            return
        task_id, work = completion.task_id, completion.work
        if (type(task_id) is not str or type(completion.attempt_id) is not str
                or type(work) is not AnalysisWork or self._analysis_work.get(task_id) is not work
                or work.task_id != task_id
                or self._analysis_attempts.get(task_id) != completion.attempt_id
                or completion.attempt_id != work.task_attempt_id
                or completion.context is not work.context
                or self._cancellation_events.get(task_id) is not work.context.task_cancel_event):
            return
        task = self._find_task(task_id)
        if task is None or task["status"] != "analyzing":
            return
        if not self._processing_authority.is_current(work.context):
            changes = dict(status="cancelled", errorMessage="batch.error.processingChanged")
        elif completion.outcome is not None:
            outcome = completion.outcome
            if (type(outcome) is not AnalysisOutcome or outcome.context is not work.context
                    or type(outcome.suggested_name) is not str):
                changes = dict(status="failed", errorMessage="batch.error.invalidOutcome")
            else:
                try:
                    expected = PreparationCoverage if work.context.mode is ProcessingMode.LOCAL else CloudAnalysisCoverage
                    if type(outcome.coverage) is not expected:
                        raise ValueError
                    facts = self._safe_analysis_facts(outcome.coverage, outcome.warning_codes)
                except Exception:
                    changes = dict(status="failed", errorMessage="batch.error.invalidOutcome")
                else:
                    error = self._validate_suggested_name(task, outcome.suggested_name)
                    changes = (dict(status="failed", errorMessage=error) if error else
                               dict(status="review_pending", suggestedName=outcome.suggested_name,
                                    errorMessage=self._analysis_warning_message(facts), validationError="", **facts))
        else:
            safe = {"batch.error.processingChanged", "batch.error.localUnavailable", "batch.error.cloudBlocked",
                    "batch.error.timeout", "batch.error.localFailed", "batch.error.cloudFailed", "batch.error.analysisFailed",
                    "batch.error.queueFull"}
            failure = (completion.failure if type(completion.failure) is str and completion.failure in safe
                       else "batch.error.analysisFailed")
            changes = dict(status="cancelled" if failure == "batch.error.processingChanged" else "failed", errorMessage=failure)
        current = self._find_task(task_id)
        if (self._closed or self._analysis_work.get(task_id) is not work
                or self._analysis_attempts.get(task_id) != completion.attempt_id
                or current is None or current["status"] != "analyzing"):
            return
        if not self._processing_authority.is_current(work.context):
            changes = dict(status="cancelled", errorMessage="batch.error.processingChanged")
        self._commit_managed_task(task_id, changes, retire_work=work)

    @staticmethod
    def _safe_analysis_facts(coverage, warning_codes):
        # Exact reviewed types and field whitelist; never stringify arbitrary
        # outcome metadata or retain a preparation/model/source object.
        if (type(coverage) not in (PreparationCoverage, CloudAnalysisCoverage)
                or type(warning_codes) is not tuple or len(warning_codes) > len(WARNING_CODES)
                or any(type(code) is not str or code not in WARNING_CODES for code in warning_codes)
                or len(set(warning_codes)) != len(warning_codes)):
            raise ValueError("Invalid analysis facts")
        values = {item.name: getattr(coverage, item.name) for item in fields(PreparationCoverage)}
        if any(type(values[key]) is not str for key in ("content_kind", "text_source", "text_limit_reason")):
            raise ValueError("Invalid analysis facts")
        type(coverage)(**values)  # Revalidate even a mutated frozen injected object.
        required = {"character_limit": "text_character_limit", "utf8_limit": "text_utf8_limit",
                    "section_limit": "section_limit"}.get(coverage.text_limit_reason)
        if ((required is not None and required not in warning_codes)
                or (coverage.text_source == "metadata_only" and "metadata_only" not in warning_codes)):
            raise ValueError("Invalid analysis facts")
        return {"analysisCoverage": {key: list(value) if type(value) is tuple else value
                                     for key, value in values.items()},
                "analysisCoverageType": "local" if type(coverage) is PreparationCoverage else "cloud",
                "analysisWarningCodes": list(warning_codes)}

    @staticmethod
    def _analysis_warning_message(facts):
        coverage, codes = facts["analysisCoverage"], set(facts["analysisWarningCodes"])
        messages = set()
        if codes & {"text_character_limit", "text_utf8_limit", "section_limit", "pdf_page_limit"}:
            messages.add("partialRead")
        if "video_sampled" in codes or coverage["content_kind"] == "video":
            messages.add("videoSampled")
        if "no_text_content" in codes:
            messages.add("noTextContent")
        if "metadata_only" in codes:
            messages.add("metadataOnly")
        message = "limitedEvidence" if len(messages) > 1 else next(iter(messages), "")
        return "batch.error." + message if message else ""

    def _run_analysis(self, path: str, task_id: str,
                      cancellation_event: threading.Event, choices=None) -> str:
        # Bind the event at submission: retrying the same task must never lend
        # its new cancellation token to a queued/finishing older attempt.
        cancellation_token = cancellation_event.is_set
        if cancellation_token():
            raise CancelledError("Analysis attempt cancelled")
        try:
            parameters = inspect.signature(self._analyzer).parameters
        except (TypeError, ValueError):
            parameters = {}
        accepts_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD
                             for p in parameters.values())
        def accepts(name):
            return accepts_kwargs or name in parameters
        kwargs = {}
        if accepts("cancellation_token"):
            kwargs['cancellation_token'] = cancellation_token
        if choices is not None:
            template_id, language, mode, policy = choices
            if mode not in {"template", "smart"} or policy != SMART_POLICY_VERSION:
                raise ValueError("smart.error.unsupportedPolicy")
            if mode == "smart" and not all(accepts(name) for name in
                                           ("naming_mode", "naming_policy_version")):
                raise ValueError("smart.error.strategyUnavailable")
            for name, value in (("template_id", template_id), ("output_language", language),
                                ("naming_mode", mode), ("naming_policy_version", policy)):
                if accepts(name):
                    kwargs[name] = value
        # Even legacy analyzers without a token parameter must not be invoked
        # when their queued attempt has already been cancelled.
        if cancellation_token():
            raise CancelledError("Analysis attempt cancelled")
        result = self._analyzer(path, task_id, **kwargs)
        if not isinstance(result, str) or not result.strip():
            raise ValueError("Analyzer returned an empty filename")
        return result.strip()

    def _emit_future(self, task_id, attempt_id, future, bridge_done):
        try:
            try: self.analysisCompleted.emit(task_id, attempt_id, True, future.result())
            except Exception as error: self.analysisCompleted.emit(task_id, attempt_id, False, str(error))
        finally:
            bridge_done.set()

    @Slot(str, str, bool, str)
    def _on_analysis_completed(self, task_id: str, attempt_id: str, success: bool, value: str):
        self._require_owner()
        if self._managed_analyzer is not None or self._closed:
            return
        self._prune_workers()
        # Stale results cannot mutate either the new task state or its token.
        if self._analysis_attempts.get(task_id) != attempt_id:
            return
        task = self._find_task(task_id)
        if task is not None and task["status"] == "analyzing" and success:
            error = self._validate_suggested_name(task, value)
            if error:
                self._update_task(task_id, status="failed", errorMessage=error)
            else:
                self._update_task(task_id, status="review_pending", suggestedName=value,
                                  errorMessage="", validationError="")
        elif task is not None and task["status"] == "analyzing":
            self._update_task(task_id, status="failed", errorMessage=self._safe_error(value))
        # _update_task emits signals; a handler may have started another retry.
        if self._analysis_attempts.get(task_id) == attempt_id:
            self._analysis_attempts.pop(task_id, None)
            self._cancellation_events.pop(task_id, None)

    def _invalidate_analysis(self, task_id: str, ownership=None) -> None:
        self._require_owner()
        if ownership is not None:
            attempt_id, event = ownership
            if event is not None:
                event.set()
            if self._analysis_attempts.get(task_id) != attempt_id:
                return
        self._analysis_work.pop(task_id, None)
        self._analysis_attempts.pop(task_id, None)
        event = self._cancellation_events.pop(task_id, None)
        if event is not None:
            event.set()

    # Search, selection, editing ------------------------------------------
    @Slot(str)
    def setSearchText(self, value): self.set_search(value)

    def set_search(self, value: str):
        self._require_owner()
        self._search = value or ""; self.filterChanged.emit(); self.tasksChanged.emit()

    @Slot(str)
    def setStatusFilter(self, value): self.set_filter(value)

    def set_filter(self, value: str):
        self._require_owner()
        self._filter = value if value in STATES or value == "all" else "all"
        self.filterChanged.emit(); self.tasksChanged.emit()

    @Slot(str, result=bool)
    def isTaskVisible(self, task_id): return task_id in self._visible_ids()

    @Slot(str)
    def toggleTaskSelected(self, task_id): self.toggle_selected(task_id)

    def toggle_selected(self, task_id: str):
        task = self._find_task(task_id)
        if task is None: return
        self._update_task(task_id, selected=not task.get("selected", False), signal_selection=True)

    @Slot(str)
    def setSelectAllState(self, state):
        visible = set(self._visible_ids())
        candidate = copy.deepcopy(self._tasks)
        for task in candidate:
            if task["taskId"] in visible: task["selected"] = state == "all"
        self._commit_tasks(candidate, selection=True)

    def select_all_visible(self): self.setSelectAllState("all")
    def clear_selection(self):
        candidate = copy.deepcopy(self._tasks)
        for task in candidate: task["selected"] = False
        self._commit_tasks(candidate, selection=True)

    @Slot(str)
    def beginInlineEdit(self, task_id):
        if not self._file_operation_locked(task_id):
            self._update_task(task_id, isEditing=True, validationError="")

    @Slot(str, str)
    def confirmInlineEdit(self, task_id, new_name):
        if self._file_operation_locked(task_id): return
        task = self._find_task(task_id)
        if task is None: return
        stem = str(new_name).strip()
        candidate = stem + task["extension"]
        error = self._validate_suggested_name(task, candidate)
        if error: self._update_task(task_id, validationError=error, isEditing=True)
        else: self._update_task(task_id, suggestedName=candidate, validationError="", isEditing=False,
                               status="review_pending")

    @Slot(str)
    def cancelInlineEdit(self, task_id):
        if not self._file_operation_locked(task_id):
            self._update_task(task_id, isEditing=False, validationError="")

    # Apply/Undo -----------------------------------------------------------
    @Slot(str)
    def applyTask(self, task_id):
        if self._file_operations is not None:
            self._file_operations.apply((task_id,))
            return
        batch_id = f"batch-{uuid.uuid4().hex}"
        self._apply_one(task_id, batch_id)

    def _apply_one(self, task_id: str, batch_id: str) -> bool:
        task = self._find_task(task_id)
        if task is None or task["status"] not in {"review_pending", "undone"}: return False
        source = task["originalName"]
        if not os.path.isfile(source):
            self._update_task(task_id, status="failed", errorMessage="Source file not found")
            return False
        target_parent = self._target_directory or str(Path(source).parent)
        plan = RenamePlan(
            task_id,
            source,
            SourceFingerprint(task["sizeBytes"], task["modifiedNs"]),
            task["suggestedName"],
            target_parent,
            task["extension"],
        )
        executor = self._executor_for(source, target_parent)
        result = executor.execute([plan], batch_id)[0]
        if result.success:
            changes = {
                "status": "applied", "appliedPath": result.new_path,
                "selected": False,
                "errorMessage": self._safe_error(result.error) if result.recovery_required else "",
            }
            try:
                self._update_task(task_id, **changes)
            except Exception:
                # The rename and durable history already succeeded.  Keep the
                # running UI truthful; restart reconciliation repairs the JSON.
                current = self._find_task(task_id)
                if current is not None:
                    current.update(changes)
                    self._refresh_task(current)
                    self._model.reset(self._tasks)
                    self.tasksChanged.emit(); self.selectionChanged.emit()
            return True
        self._update_task(task_id, status="failed", errorMessage=self._safe_error(result.error),
                          selected=False)
        return False

    @Slot()
    def applySelected(self):
        if self._file_operations is not None:
            self._file_operations.apply(tuple(task['taskId'] for task in self._tasks if task.get('selected')))
            return
        selected = [task["taskId"] for task in self._tasks
                    if task.get("selected") and task["status"] in {"review_pending", "undone"}]
        self._apply_active = True
        self._apply_total = len(selected)
        self._apply_current = self._apply_success = self._apply_failed = 0
        self.progressChanged.emit()
        batch_id = f"batch-{uuid.uuid4().hex}"
        for task_id in selected:
            if self._apply_one(task_id, batch_id): self._apply_success += 1
            else: self._apply_failed += 1
            self._apply_current += 1; self.progressChanged.emit()
        self._apply_active = False; self.progressChanged.emit()

    @Slot(str)
    def undoTask(self, task_id):
        if self._file_operations is not None:
            self._file_operations.undo(task_id)
            return
        task = self._find_task(task_id)
        if task is None or task["status"] != "applied" or not self._history_path: return
        applied = task.get("appliedPath", "")
        executor = self._executor_for(applied or task["originalName"], str(Path(task["originalName"]).parent))
        result = UndoManager(str(self._history_path), executor).undo_task(task_id)
        if result and result.success:
            self._update_task(task_id, status="undone", appliedPath="", errorMessage="")
        elif result:
            self._update_task(task_id, status="failed", errorMessage=self._safe_error(result.error))

    @Slot(str)
    def retryTask(self, task_id):
        self._require_owner()
        if self._closed or self._file_operation_locked(task_id):
            return
        task = self._find_task(task_id)
        if task and task["status"] in {"failed", "cancelled", "ignored", "review_pending"}:
            if self._managed_analyzer is not None:
                if not self._commit_managed_task(task_id, dict(status="pending", errorMessage="")):
                    return
            else:
                self._update_task(task_id, status="pending", errorMessage="")
            self._start_analysis(task_id)

    @Slot(str)
    def ignoreTask(self, task_id):
        self._require_owner()
        if self._file_operation_locked(task_id): return
        task = self._find_task(task_id)
        if task and task["status"] != "applied":
            ownership = (self._analysis_attempts.get(task_id), self._cancellation_events.get(task_id))
            self._update_task(task_id, status="ignored", selected=False)
            self._invalidate_analysis(task_id, ownership)

    @Slot(str)
    def cancelTask(self, task_id):
        self._require_owner()
        if self._file_operation_locked(task_id): return
        task = self._find_task(task_id)
        if task and task["status"] in {"pending", "analyzing"}:
            ownership = (self._analysis_attempts.get(task_id), self._cancellation_events.get(task_id))
            self._update_task(task_id, status="cancelled", selected=False)
            self._invalidate_analysis(task_id, ownership)

    @Slot()
    def stopPending(self):
        self._require_owner()
        cancelled_ids = [task["taskId"] for task in self._tasks
                         if task["status"] in {"pending", "analyzing"}]
        ownership = {task_id: (self._analysis_attempts.get(task_id), self._cancellation_events.get(task_id))
                     for task_id in cancelled_ids}
        candidate = copy.deepcopy(self._tasks)
        for task in candidate:
            if task["status"] in {"pending", "analyzing"}: task["status"] = "cancelled"; self._refresh_task(task)
        self._commit_tasks(candidate)
        for task_id in cancelled_ids:
            self._invalidate_analysis(task_id, ownership[task_id])

    @Slot()
    def clearWorkspace(self): self.clear_workspace()

    def clear_workspace(self):
        self._require_owner()
        ownership = {task_id: (attempt_id, self._cancellation_events.get(task_id))
                     for task_id, attempt_id in self._analysis_attempts.items()}
        self._save_workspace([])
        if self._file_operations is not None: self._file_operations.advance_epoch()
        self._publish_tasks([])
        for task_id, issued in ownership.items():
            self._invalidate_analysis(task_id, issued)

    @Slot(str)
    def setTargetDirectory(self, directory):
        self._require_owner()
        local = self._local_path(directory)
        self._target_directory = local if local and os.path.isdir(local) else ""
        self.targetDirectoryChanged.emit(); self._save_workspace()

    @Slot()
    def close(self):
        """Stop accepting background work without waiting on slow providers."""
        self._require_owner()
        self._closed = True
        if self._file_operations is not None: self._file_operations.begin_close()
        for task_id in tuple(self._analysis_attempts):
            self._invalidate_analysis(task_id)
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)
        if self._managed_analyzer is not None:
            candidate = copy.deepcopy(self._tasks)
            for task in candidate:
                if task["status"] in {"pending", "analyzing"}:
                    task.update(status="cancelled", errorMessage="batch.error.processingChanged", selected=False)
            if candidate != self._tasks:
                self._commit_tasks(candidate)

    # Persistence/helpers --------------------------------------------------
    def _load_workspace(self):
        if self._workspace_path is None or not self._workspace_path.exists(): return
        try:
            data = json.loads(self._workspace_path.read_text(encoding="utf-8"))
            if data.get("schema_version") != 1 or not isinstance(data.get("tasks"), list):
                raise ValueError("unsupported workspace schema")
            self._target_directory = str(data.get("target_directory", ""))
            self._selected_template_id = str(data.get("selected_template_id", ""))
            self._tasks = [self._normalize_loaded_task(item) for item in data["tasks"]]
        except Exception:
            suffix = uuid.uuid4().hex[:8]
            quarantine = self._workspace_path.with_name(f"{self._workspace_path.name}.{suffix}.corrupted")
            os.replace(self._workspace_path, quarantine)
            self._tasks = []; self._model.reset(self._tasks)
            return
        # Parsing and reconciliation persistence have distinct failure meaning.
        # A valid JSON workspace must not be quarantined after a failed save.
        if self._file_operations is not None:
            try:
                changed = self._file_operations.reconcile(self._tasks)
            except Exception:
                # Unavailable history is not malformed workspace JSON. Preserve
                # every row, refuse replay, and expose only a fixed recovery ID.
                changed = True
                for task in self._tasks:
                    task.update(fileOperationPending=False, fileOperationRecoveryRequired=True,
                                errorMessage='fileops.error.interrupted')
                    self._refresh_task(task)
            if changed:
                try:
                    self._save_workspace(self._tasks)
                except Exception:
                    for task in self._tasks:
                        task.update(fileOperationRecoveryRequired=True,
                                    errorMessage='fileops.error.workspaceSaveRecovery')
                        self._refresh_task(task)
        else:
            try: self._reconcile_applied_history()
            except OSError: pass
        self._model.reset(self._tasks)

    def _reconcile_applied_history(self) -> None:
        """Repair workspace metadata from the durable rename log after a crash/write failure."""
        if not self._history_path or not self._history_path.exists():
            return
        history = RenameHistory(str(self._history_path))
        changed = False
        for task in self._tasks:
            if task.get("status") == "applied":
                continue
            record = history.get_latest_for_task(task["taskId"])
            if record is None:
                continue
            old_path, new_path = str(record.old_path), str(record.new_path)
            if os.path.isfile(new_path) and not os.path.exists(old_path):
                task.update(status="applied", appliedPath=new_path, selected=False,
                            errorMessage="")
                self._refresh_task(task)
                changed = True
        if changed:
            self._save_workspace(self._tasks)

    def _save_workspace(self, tasks: list[dict[str, Any]] | None = None):
        if self._workspace_path is None: return
        payload_tasks = tasks if tasks is not None else self._tasks
        payload = {"schema_version": 1, "target_directory": self._target_directory,
                   "selected_template_id": self._selected_template_id,
                   "tasks": [{key: value for key, value in task.items() if key != "task_id"}
                             for task in payload_tasks]}
        self._workspace_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=self._workspace_path.name + ".",
                                         suffix=".tmp", dir=str(self._workspace_path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush(); os.fsync(handle.fileno())
            os.replace(temp_name, self._workspace_path)
        except Exception:
            try: os.unlink(temp_name)
            except OSError: pass
            raise

    def _commit_tasks(self, candidate, selection=False):
        self._require_owner()
        self._save_workspace(candidate)
        self._publish_tasks(candidate, selection)

    def _publish_tasks(self, candidate, selection=False):
        """Pure Qt publication; callers finish persistence/ownership first."""
        self._require_owner()
        self._tasks = candidate
        for task in self._tasks: self._refresh_task(task)
        self._model.reset(self._tasks)
        self.tasksChanged.emit()
        if selection: self.selectionChanged.emit()

    def _retire_managed_work(self, work):
        task_id = work.task_id
        if (self._analysis_work.get(task_id) is work
                and self._analysis_attempts.get(task_id) == work.task_attempt_id
                and self._cancellation_events.get(task_id) is work.context.task_cancel_event):
            self._analysis_work.pop(task_id)
            self._analysis_attempts.pop(task_id)
            self._cancellation_events.pop(task_id)

    def _commit_managed_task(self, task_id, changes, *, install_work=None, retire_work=None):
        """Save first, then exact ownership transition, then public publication.

        Failed saves publish only a fixed, retryable in-memory failure. They do
        not publish an unsaved suggestion or claim the stored workspace changed.
        Ownership arguments are issued work values, never arbitrary callbacks.
        """
        self._require_owner(always=True)
        candidate = copy.deepcopy(self._tasks)
        target = next((task for task in candidate if task["taskId"] == task_id), None)
        if target is None:
            if install_work is not None:
                install_work.context.task_cancel_event.set()
            return False
        target.update(changes)
        try:
            self._save_workspace(candidate)
        except Exception:
            failed_work = install_work if install_work is not None else retire_work
            if failed_work is not None:
                failed_work.context.task_cancel_event.set()
                self._retire_managed_work(failed_work)
            candidate = copy.deepcopy(self._tasks)
            target = next(task for task in candidate if task["taskId"] == task_id)
            target.update(status="failed", errorMessage="batch.error.workspaceSaveFailed",
                          suggestedName="", analysisCoverage=None, analysisCoverageType="",
                          analysisWarningCodes=[], validationError="")
            self._publish_tasks(candidate)
            return False
        if install_work is not None:
            self._analysis_attempts[task_id] = install_work.task_attempt_id
            self._cancellation_events[task_id] = install_work.context.task_cancel_event
            self._analysis_work[task_id] = install_work
        if retire_work is not None:
            self._retire_managed_work(retire_work)
        # Model/public notifications may immediately retry. No old ownership
        # cleanup is allowed after this boundary.
        self._publish_tasks(candidate, "selected" in changes)
        return True

    def _update_task(self, task_id, signal_selection=False, **changes):
        self._require_owner()
        candidate = copy.deepcopy(self._tasks)
        target = next((task for task in candidate if task["taskId"] == task_id), None)
        if target is None: return
        target.update(changes); self._refresh_task(target)
        self._commit_tasks(candidate, selection=signal_selection or "selected" in changes)

    def _new_task(self, task_id, path, extension, size, mtime):
        return self._normalize_loaded_task({
            "taskId": task_id, "originalName": path, "suggestedName": "",
            "extension": extension, "status": "pending", "selected": False,
            "thumbnailKind": self._thumbnail_kind(extension), "errorMessage": "",
            "isEditing": False, "validationError": "", "appliedPath": "",
            "sizeBytes": size, "modifiedNs": mtime,
        })

    def _normalize_loaded_task(self, task):
        result = dict(task)
        task_id = str(result.get("taskId") or result.get("task_id") or f"task-{uuid.uuid4().hex}")
        result.update({
            "taskId": task_id, "task_id": task_id,
            "originalName": str(result.get("originalName", "")),
            "suggestedName": str(result.get("suggestedName", "")),
            "extension": str(result.get("extension", "")).lower(),
            "status": str(result.get("status", "pending")),
            "selected": bool(result.get("selected", False)),
            "errorMessage": str(result.get("errorMessage", "")),
            "isEditing": bool(result.get("isEditing", False)),
            "validationError": str(result.get("validationError", "")),
            "appliedPath": str(result.get("appliedPath", "")),
            "sizeBytes": int(result.get("sizeBytes", 0)),
            "modifiedNs": int(result.get("modifiedNs", 0)),
            "namingMode": str(result.get("namingMode", "template")),
            "namingPolicyVersion": str(result.get("namingPolicyVersion", SMART_POLICY_VERSION)),
            "fileOperationPending": False,
            "fileOperationRecoveryRequired": result.get("fileOperationRecoveryRequired") is True,
        })
        if result["status"] not in STATES: result["status"] = "pending"
        has_facts = any(key in result for key in ("analysisCoverage", "analysisCoverageType", "analysisWarningCodes"))
        empty_facts = (result.get("analysisCoverage") is None
                       and type(result.get("analysisCoverageType")) is str and result["analysisCoverageType"] == ""
                       and type(result.get("analysisWarningCodes")) is list and not result["analysisWarningCodes"])
        if has_facts and not empty_facts:
            try:
                values = result["analysisCoverage"]
                kind = result.get("analysisCoverageType")
                codes = result.get("analysisWarningCodes")
                if (type(values) is not dict or values.keys() != PreparationCoverage.__dataclass_fields__.keys()
                        or type(kind) is not str or kind not in {"local", "cloud"} or type(codes) is not list):
                    raise ValueError
                values = dict(values)
                for key in ("text_page_indices", "rendered_page_indices", "video_timestamps_seconds"):
                    if type(values[key]) is not list:
                        raise ValueError
                    values[key] = tuple(values[key])
                cls = PreparationCoverage if kind == "local" else CloudAnalysisCoverage
                facts = self._safe_analysis_facts(cls(**values), tuple(codes))
                result.update(facts)
                if result["status"] == "review_pending":
                    result["errorMessage"] = self._analysis_warning_message(facts)
            except Exception:
                result.update(analysisCoverage=None, analysisCoverageType="", analysisWarningCodes=[])
                if result["status"] == "review_pending":
                    result.update(status="failed", errorMessage="batch.error.invalidOutcome")
        self._refresh_task(result)
        return result

    def _file_operation_locked(self, task_id):
        self._require_owner()
        task = self._find_task(task_id)
        return bool(task and (task.get('fileOperationRecoveryRequired') or
                    (self._file_operations is not None and self._file_operations.owns(task_id))))

    def _refresh_task(self, task):
        state = task["status"]
        task['fileOperationPending'] = self._file_operations is not None and self._file_operations.owns(task['taskId'])
        task.setdefault('fileOperationRecoveryRequired', False)
        locked = task['fileOperationPending'] or task['fileOperationRecoveryRequired']
        task["statusLabel"] = LABELS[state]
        task["canApply"] = not locked and state in {"review_pending", "undone"}
        task["canRetry"] = not locked and state in {"failed", "cancelled", "review_pending"}
        task["canIgnore"] = not locked and state != "applied"
        task["canCancel"] = not locked and state in {"pending", "analyzing"}
        task["canUndo"] = not locked and state == "applied"
        task.setdefault("thumbnailKind", "doc")

    def _visible_ids(self):
        result = []
        query = self._search.casefold()
        for task in self._tasks:
            if self._filter != "all" and task["status"] != self._filter: continue
            if query and query not in task["originalName"].casefold() and query not in task["suggestedName"].casefold(): continue
            result.append(task["taskId"])
        return result

    def _find_task(self, task_id): return next((task for task in self._tasks if task["taskId"] == task_id), None)

    def _executor_for(self, source, target_parent):
        roots = {str(Path(source).resolve().parent), str(Path(target_parent).resolve())}
        history = RenameHistory(str(self._history_path)) if self._history_path else None
        return RenameExecutor(PreflightService(sorted(roots)), history)

    @staticmethod
    def _validate_suggested_name(task, value):
        name = Path(value).name
        if value != name: return "batch.validate.path"
        if not name or any(char in name for char in '<>:"/\\|?*'): return "batch.validate.illegalChars"
        if name.endswith((".", " ")): return "batch.validate.ending"
        stem, extension = os.path.splitext(name)
        if not stem: return "batch.validate.empty"
        if len(stem) > 200: return "batch.validate.tooLong"
        if extension.lower() != task["extension"].lower(): return "batch.validate.extension"
        if re.match(r"^(CON|PRN|AUX|NUL|COM\d|LPT\d)$", stem, re.IGNORECASE): return "batch.validate.reserved"
        return ""

    @staticmethod
    def _local_path(value):
        if hasattr(value, "toLocalFile"):
            local = value.toLocalFile()
            return str(local) if local else str(value)
        text = str(value)
        if text.startswith("file:"):
            local = QUrl(text).toLocalFile()
            return local or text
        return text

    @staticmethod
    def _thumbnail_kind(extension):
        if extension in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif"}: return "image"
        if extension in {".mp4", ".mov", ".mkv", ".avi", ".webm", ".wmv", ".flv"}: return "video"
        return "doc"

    @staticmethod
    def _safe_error(value):
        text = str(value or "")
        setup_errors = {
            "No active AI provider is configured": "batch.error.providerMissing",
            "The active AI provider has no credential": "batch.error.credentialMissing",
            "Source file exceeds the configured size limit": "batch.error.fileTooLarge",
            "Vision cloud processing is disabled": "batch.error.privacyDisabled",
            "Video keyframe cloud processing is disabled": "batch.error.privacyDisabled",
            "Text cloud processing is disabled": "batch.error.privacyDisabled",
        }
        if text in setup_errors:
            return setup_errors[text]
        text = re.sub(r"(?i)[A-Z]:[/\\]Users[/\\][^\s]+", "<redacted-path>", text)
        text = re.sub(r"(?i)(bearer\s+|api[_-]?key\s*[=:]\s*)\S+", r"\1<redacted>", text)
        lowered = text.lower()
        if "rate limit" in lowered or "429" in lowered:
            return "batch.error.rateLimit"
        if "timeout" in lowered or "timed out" in lowered:
            return "batch.error.timeout"
        if any(token in lowered for token in ("401", "403", "unauthorized", "authentication")):
            return "batch.error.authentication"
        if any(token in lowered for token in ("network", "connection", "dns")):
            return "batch.error.network"
        return text[:240]

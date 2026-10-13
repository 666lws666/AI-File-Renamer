"""QML-facing presentation controller for Watch Folders.

QML sends user intents through this boundary.  Filesystem monitoring,
configuration persistence, Review First, and Auto Apply remain in their
existing domain/controller services.
"""

from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import uuid4

from PySide6.QtCore import QObject, Property, Signal, Slot

from src.controllers.watch_controller import WatchController
from src.controllers.watch_edit_handler import WatchEditHandler
from src.core.watch_config import WatchConfig, WatchMode, WatchStatus
from src.core.watch_review_queue import ReviewItem
from src.core.managed_watch_metadata import ManagedWatchMetadata, auto_apply_review_reason


class WatchPageController(QObject):
    """Stable Qt boundary for the Watch page and per-watch results panel."""

    stateChanged = Signal()

    def __init__(
        self,
        *,
        watch_controller: WatchController,
        edit_handler: WatchEditHandler,
        review_handler: Any = None,
        templates_provider: Callable[[], Iterable[Any]] | None = None,
        results_provider: Callable[[str], Iterable[Any]] | None = None,
        notice_provider: Callable[[str], str] | None = None,
        availability_provider: Callable[[], bool] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._watch_controller = watch_controller
        self._edit_handler = edit_handler
        self._review_handler = review_handler
        self._templates_provider = templates_provider or (lambda: ())
        self._results_provider = results_provider
        self._notice_provider = notice_provider
        self._availability_provider = availability_provider
        self._form_open = False
        self._form_mode = "create"
        self._editing_id = ""
        self._draft_source = ""
        self._draft_target = ""
        self._draft_template = ""
        self._draft_recursive = True
        self._draft_mode = WatchMode.REVIEW_FIRST.value
        self._error_message = ""
        self._results_open = False
        self._selected_watch_id = ""

    @staticmethod
    def _template_row(item: Any) -> dict[str, str]:
        if isinstance(item, dict):
            return {"id": str(item.get("id", "")), "name": str(item.get("name", ""))}
        return {"id": str(getattr(item, "id", "")), "name": str(getattr(item, "name", ""))}

    def _result_items(self, watch_id: str) -> list[Any]:
        try:
            if self._results_provider is not None:
                return list(self._results_provider(watch_id))
            if self._review_handler is not None and hasattr(self._review_handler, "items"):
                return list(self._review_handler.items(watch_id))
        except Exception:
            return []
        return []

    @staticmethod
    def _result_row(item: Any) -> dict[str, Any]:
        state = getattr(item, "state", "")
        if hasattr(state, "value"):
            state = state.value
        confidence = getattr(item, "confidence", None)
        if (type(confidence) not in (int, float)
                or not 0 <= confidence <= 1 or not math.isfinite(confidence)):
            confidence = None
        projection = dict(contentKind="", warningCodes=[], requestedQuality="",
                          effectiveQuality="", autoApplyReviewReason="", coverage={})
        metadata = getattr(item, "managed_metadata", None)
        if type(item) is ReviewItem and type(metadata) is ManagedWatchMetadata:
            confidence = None
            try:
                reason = auto_apply_review_reason(metadata)
                projection.update(contentKind=metadata.content_kind,
                    warningCodes=list(metadata.warning_codes),
                    requestedQuality=metadata.requested_quality,
                    effectiveQuality=metadata.effective_quality, autoApplyReviewReason=reason)
                coverage = metadata.coverage
                if coverage is not None:
                    projection["coverage"] = dict(textSource=coverage.text_source,
                        sectionsProcessed=coverage.sections_processed, sectionsTotal=coverage.sections_total,
                        textTruncated=coverage.text_truncated, textLimitReason=coverage.text_limit_reason,
                        pdfTotalPages=coverage.pdf_total_pages, textPageIndices=list(coverage.text_page_indices),
                        renderedPageIndices=list(coverage.rendered_page_indices),
                        videoDurationSeconds=coverage.video_duration_seconds,
                        videoTimestampsSeconds=list(coverage.video_timestamps_seconds))
            except (TypeError, ValueError, AttributeError):
                pass  # Invalid foreign/tampered facts never become a projected review claim.
        return {
            "id": str(getattr(item, "id", "")),
            "watchId": str(getattr(item, "watch_id", "")),
            "displayName": str(getattr(item, "display_name", "")),
            "suggestedName": str(getattr(item, "suggested_name", "")),
            "state": str(state),
            "confidence": confidence,
            "errorCategory": str(getattr(item, "error_category", "")),
            "recoveryRequired": bool(getattr(item, "recovery_required", False)),
            "canApprove": (state in {"awaiting_approval", "undone"}
                and not getattr(item, "recovery_required", False)
                and getattr(item, "file_operation", None) is None),
            "canRetry": (state in {"failed", "cancelled"}
                and getattr(item, "error_category", "") != "retried"
                and not getattr(item, "recovery_required", False)
                and getattr(item, "file_operation", None) is None),
            "canUndo": (state == "applied" and bool(getattr(item, "applied_path", ""))
                and bool(getattr(item, "batch_id", "")) and not getattr(item, "recovery_required", False)
                and getattr(item, "file_operation", None) is None),
            **projection,
        }

    def _watch_row(self, config: WatchConfig) -> dict[str, Any]:
        template_name = next(
            (row["name"] for row in self.templates if row["id"] == config.template_id),
            config.template_id,
        )
        return {
            "id": config.id,
            "sourceDir": config.source_dir,
            "sourceName": Path(config.source_dir).name or config.source_dir,
            "targetDir": config.target_dir,
            "templateId": config.template_id,
            "templateName": template_name,
            "recursive": config.recursive,
            "mode": config.mode.value,
            "status": config.status.value,
            "resultCount": len(self._result_items(config.id)),
        }

    @Property("QVariantList", notify=stateChanged)
    def watches(self) -> list[dict[str, Any]]:
        return [self._watch_row(item) for item in self._watch_controller.list_configs()]

    @Property(int, notify=stateChanged)
    def watchCount(self) -> int:
        return len(self._watch_controller.list_configs())

    @Property("QVariantList", notify=stateChanged)
    def templates(self) -> list[dict[str, str]]:
        return [self._template_row(item) for item in self._templates_provider()]

    @Property(bool, notify=stateChanged)
    def formOpen(self) -> bool:
        return self._form_open

    @Property(str, notify=stateChanged)
    def formMode(self) -> str:
        return self._form_mode

    @Property(str, notify=stateChanged)
    def draftSource(self) -> str:
        return self._draft_source

    @Property(str, notify=stateChanged)
    def draftTarget(self) -> str:
        return self._draft_target

    @Property(str, notify=stateChanged)
    def draftTemplate(self) -> str:
        return self._draft_template

    @Property(bool, notify=stateChanged)
    def draftRecursive(self) -> bool:
        return self._draft_recursive

    @Property(str, notify=stateChanged)
    def draftMode(self) -> str:
        return self._draft_mode

    @Property(str, notify=stateChanged)
    def errorMessage(self) -> str:
        return self._error_message

    @Property(bool, notify=stateChanged)
    def resultsOpen(self) -> bool:
        return self._results_open

    @Property(str, notify=stateChanged)
    def selectedWatchId(self) -> str:
        return self._selected_watch_id

    @Property("QVariantList", notify=stateChanged)
    def results(self) -> list[dict[str, Any]]:
        return [self._result_row(item) for item in self._result_items(self._selected_watch_id)]

    @Property(bool, notify=stateChanged)
    def available(self):
        return self._availability_provider() if self._availability_provider is not None else True

    @Property(str, notify=stateChanged)
    def resultNotice(self):
        if self._notice_provider is None or not self._selected_watch_id: return ""
        return self._notice_provider(self._selected_watch_id)

    @Slot()
    def refresh(self) -> None:
        if not self.thread().isCurrentThread():
            raise RuntimeError("watch_owner_thread_required")
        self.stateChanged.emit()

    @Slot()
    def beginCreate(self) -> None:
        self._form_mode = "create"
        self._editing_id = ""
        self._draft_source = ""
        self._draft_target = ""
        templates = self.templates
        self._draft_template = templates[0]["id"] if templates else ""
        self._draft_recursive = True
        self._draft_mode = WatchMode.REVIEW_FIRST.value
        self._error_message = ""
        self._form_open = True
        self.stateChanged.emit()

    @Slot(str, result=bool)
    def beginEdit(self, watch_id: str) -> bool:
        try:
            self._edit_handler.prepare_edit(watch_id)
            config = self._watch_controller.get_config(watch_id)
            self._form_mode = "edit"
            self._editing_id = watch_id
            self._draft_source = config.source_dir
            self._draft_target = config.target_dir
            self._draft_template = config.template_id
            self._draft_recursive = config.recursive
            self._draft_mode = config.mode.value
            self._error_message = ""
            self._form_open = True
            self.stateChanged.emit()
            return True
        except Exception as error:
            self._error_message = str(error)
            self.stateChanged.emit()
            return False

    @Slot()
    def cancelForm(self) -> None:
        self._form_open = False
        self._error_message = ""
        self.stateChanged.emit()

    @Slot(str)
    def setDraftSource(self, value: str) -> None:
        self._draft_source = str(value).strip()
        self._error_message = ""
        self.stateChanged.emit()

    @Slot(str)
    def setDraftTarget(self, value: str) -> None:
        self._draft_target = str(value).strip()
        self._error_message = ""
        self.stateChanged.emit()

    @Slot(str)
    def setDraftTemplate(self, value: str) -> None:
        self._draft_template = str(value)
        self._error_message = ""
        self.stateChanged.emit()

    @Slot(bool)
    def setDraftRecursive(self, value: bool) -> None:
        self._draft_recursive = bool(value)
        self.stateChanged.emit()

    @Slot(str)
    def setDraftMode(self, value: str) -> None:
        if value in {mode.value for mode in WatchMode}:
            self._draft_mode = value
            self._error_message = ""
            self.stateChanged.emit()

    @Slot(result=bool)
    def saveDraft(self) -> bool:
        try:
            now = datetime.now(timezone.utc).isoformat()
            config = WatchConfig(
                id=self._editing_id or str(uuid4()),
                source_dir=self._draft_source,
                target_dir=self._draft_target,
                template_id=self._draft_template,
                recursive=self._draft_recursive,
                mode=WatchMode(self._draft_mode),
                status=(WatchStatus.PAUSED if self._editing_id else WatchStatus.ACTIVE),
                created_at=now,
                updated_at=now,
            )
            if self._editing_id:
                previous = self._watch_controller.get_config(self._editing_id)
                config = WatchConfig(
                    **{
                        **config.to_dict(),
                        "mode": config.mode,
                        "status": config.status,
                        "created_at": previous.created_at,
                        "version": previous.version + 1,
                    }
                )
                self._watch_controller.update_watch(config)
            else:
                self._watch_controller.add_watch(config)
            self._form_open = False
            self._error_message = ""
            self.stateChanged.emit()
            return True
        except Exception as error:
            self._error_message = str(error)
            self.stateChanged.emit()
            return False

    def _watch_action(self, action: Callable[[str], Any], watch_id: str) -> bool:
        try:
            action(watch_id)
            self._error_message = ""
            self.stateChanged.emit()
            return True
        except Exception as error:
            self._error_message = str(error)
            self.stateChanged.emit()
            return False

    @Slot(str, result=bool)
    def pauseWatch(self, watch_id: str) -> bool:
        return self._watch_action(self._watch_controller.pause_watch, watch_id)

    @Slot(str, result=bool)
    def resumeWatch(self, watch_id: str) -> bool:
        return self._watch_action(self._watch_controller.resume_watch, watch_id)

    @Slot(str, result=bool)
    def removeWatch(self, watch_id: str) -> bool:
        return self._watch_action(self._edit_handler.delete_watch, watch_id)

    @Slot(str)
    def openResults(self, watch_id: str) -> None:
        self._selected_watch_id = watch_id
        self._results_open = True
        self._error_message = ""
        self.stateChanged.emit()

    @Slot()
    def closeResults(self) -> None:
        self._results_open = False
        self._selected_watch_id = ""
        self.stateChanged.emit()

    def _result_action(self, method_name: str, item_id: str) -> bool:
        if not self.thread().isCurrentThread():
            raise RuntimeError("watch_owner_thread_required")
        if self._review_handler is None or not hasattr(self._review_handler, method_name):
            self._error_message = "watch.actionUnavailable"
            self.stateChanged.emit()
            return False
        try:
            accepted = getattr(self._review_handler, method_name)(item_id)
            if accepted is False:
                self._error_message = "watch.actionUnavailable"
                self.stateChanged.emit()
                return False
            self._error_message = ""
            self.stateChanged.emit()
            return True
        except Exception as error:
            self._error_message = "watch.actionUnavailable"
            self.stateChanged.emit()
            return False

    @Slot(str, result=bool)
    def approveResult(self, item_id: str) -> bool:
        return self._result_action("approve", item_id)

    @Slot(str, result=bool)
    def ignoreResult(self, item_id: str) -> bool:
        return self._result_action("ignore", item_id)

    @Slot(str, result=bool)
    def retryResult(self, item_id: str) -> bool:
        return self._result_action("retry", item_id)

    @Slot(str, result=bool)
    def undoResult(self, item_id: str) -> bool:
        return self._result_action("undo", item_id)

"""QML-facing Watch page controller contract tests."""

from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
import pytest

from src.controllers.watch_controller import ObserverFactory, WatchController
from src.controllers.watch_edit_handler import WatchEditHandler
from src.controllers.watch_page_controller import WatchPageController
from src.core.watch_config import WatchConfigStore, WatchStatus
from src.core.watch_review_queue import ReviewItem, ReviewItemState
from src.core.managed_watch_metadata import ManagedWatchMetadata
from src.services.local_ai.preparation_protocol import PreparationCoverage


@dataclass
class _ReviewItem:
    id: str
    watch_id: str
    display_name: str
    suggested_name: str
    state: ReviewItemState
    confidence: float = 0.9
    error_category: str = ""


@pytest.mark.parametrize("value", [None, True, "0.8", float("nan"), float("inf"), -1, 2, object()])
def test_result_projection_unknown_confidence_is_not_a_guessed_score(value):
    row = WatchPageController._result_row(SimpleNamespace(confidence=value))
    assert row["confidence"] is None


def test_result_projection_missing_and_legacy_have_stable_empty_metadata():
    for item, confidence in ((SimpleNamespace(), None), (SimpleNamespace(confidence=0.73), 0.73)):
        row = WatchPageController._result_row(item)
        assert row["confidence"] == confidence
        assert {key: row[key] for key in ("contentKind", "warningCodes", "requestedQuality",
            "effectiveQuality", "autoApplyReviewReason")} == dict(contentKind="", warningCodes=[],
            requestedQuality="", effectiveQuality="", autoApplyReviewReason="")


def test_result_projection_managed_facts_are_descriptive_qvariant_values():
    metadata = ManagedWatchMetadata("text", "high", "economy",
        PreparationCoverage("text", sections_processed=1, sections_total=1), ())
    item = ReviewItem("id", "watch", "C:/synthetic.txt", 1, 2, ".txt", "synthetic.txt",
        ReviewItemState.AWAITING_APPROVAL, "suggested.txt", confidence=None, managed_metadata=metadata)
    row = WatchPageController._result_row(item)
    assert row["confidence"] is None and row["state"] == "awaiting_approval"
    assert row["id"] == "id" and row["suggestedName"] == "suggested.txt"
    assert row["contentKind"] == "text" and row["warningCodes"] == []
    assert row["requestedQuality"] == "high" and row["effectiveQuality"] == "economy"
    assert row["autoApplyReviewReason"] == "quality_degraded"
    assert row["coverage"]["sectionsProcessed"] == 1
    assert row["coverage"]["sectionsTotal"] == 1
    assert row["coverage"]["videoTimestampsSeconds"] == []
    partial = ManagedWatchMetadata("text", "balanced", "balanced",
        PreparationCoverage("text", text_source="metadata_only"), ("metadata_only",))
    row = WatchPageController._result_row(replace(item, managed_metadata=partial))
    assert row["warningCodes"] == ["metadata_only"]
    assert row["autoApplyReviewReason"] == "metadata_only"


def test_result_projection_does_not_interpret_foreign_metadata():
    row = WatchPageController._result_row(SimpleNamespace(confidence=None,
        managed_metadata={"content_kind": "image", "secret": "private"}))
    assert row["contentKind"] == "" and row["autoApplyReviewReason"] == ""


class _ReviewHandler:
    def __init__(self):
        self.rows = []
        self.actions = []

    def items(self, watch_id=None):
        return [item for item in self.rows if watch_id is None or item.watch_id == watch_id]

    def approve(self, item_id):
        self.actions.append(("approve", item_id))

    def ignore(self, item_id):
        self.actions.append(("ignore", item_id))

    def retry(self, item_id):
        self.actions.append(("retry", item_id))


def _page(tmp_path):
    store = WatchConfigStore(tmp_path / "watches.json")
    review = _ReviewHandler()
    backend = WatchController(
        store,
        observer_factory=ObserverFactory(use_mock=True),
        review_first_handler=review,
    )
    page = WatchPageController(
        watch_controller=backend,
        edit_handler=WatchEditHandler(backend),
        review_handler=review,
        templates_provider=lambda: [
            {"id": "general", "name": "General Naming (Default)"},
            {"id": "archive", "name": "Archive"},
        ],
    )
    return page, backend, review


def test_result_refusal_and_absent_action_are_truthful_fixed_notices(tmp_path):
    page, backend, review = _page(tmp_path)
    review.approve = lambda _: False
    assert page.approveResult("absent") is False
    assert page.errorMessage == "watch.actionUnavailable"
    assert page.undoResult("absent") is False
    def private_failure(_): raise RuntimeError("PRIVATE PATH OR KEY")
    review.retry = private_failure
    assert page.retryResult("absent") is False
    assert page.errorMessage == "watch.actionUnavailable"
    backend.begin_close()


def test_create_pause_resume_and_remove_watch(tmp_path):
    page, backend, _review = _page(tmp_path)
    source = tmp_path / "source"
    source.mkdir()

    page.beginCreate()
    page.setDraftSource(str(source))
    page.setDraftTemplate("general")
    page.setDraftRecursive(False)
    assert page.saveDraft() is True

    assert page.watchCount == 1
    watch_id = page.watches[0]["id"]
    assert page.watches[0]["status"] == "active"
    assert backend._get_observer(watch_id).running is True

    assert page.pauseWatch(watch_id) is True
    assert page.watches[0]["status"] == "paused"
    assert page.resumeWatch(watch_id) is True
    assert page.watches[0]["status"] == "active"
    assert page.removeWatch(watch_id) is True
    assert page.watchCount == 0


def test_edit_pauses_first_and_persists_updated_config_as_paused(tmp_path):
    page, backend, _review = _page(tmp_path)
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    page.beginCreate()
    page.setDraftSource(str(source))
    assert page.saveDraft() is True
    watch_id = page.watches[0]["id"]

    assert page.beginEdit(watch_id) is True
    assert backend.get_status(watch_id) is WatchStatus.PAUSED
    page.setDraftTarget(str(target))
    page.setDraftTemplate("archive")
    page.setDraftMode("auto_apply")
    assert page.saveDraft() is True

    config = backend.get_config(watch_id)
    assert config.target_dir == str(target.resolve())
    assert config.template_id == "archive"
    assert config.mode.value == "auto_apply"
    assert config.status is WatchStatus.PAUSED


def test_form_validation_is_fail_closed(tmp_path):
    page, _backend, _review = _page(tmp_path)
    page.beginCreate()
    page.setDraftSource(str(tmp_path / "missing"))

    assert page.saveDraft() is False
    assert page.formOpen is True
    assert page.watchCount == 0
    assert page.errorMessage


def test_results_are_scoped_to_selected_watch_and_actions_delegate(tmp_path):
    page, _backend, review = _page(tmp_path)
    review.rows = [
        _ReviewItem("one", "watch-a", "invoice.pdf", "2026_invoice.pdf", ReviewItemState.AWAITING_APPROVAL),
        _ReviewItem("two", "watch-b", "other.pdf", "other_named.pdf", ReviewItemState.FAILED, error_category="provider"),
    ]

    page.openResults("watch-a")
    assert page.resultsOpen is True
    assert page.selectedWatchId == "watch-a"
    assert [row["id"] for row in page.results] == ["one"]
    assert page.approveResult("one") is True
    assert page.ignoreResult("one") is True
    assert page.retryResult("one") is True
    assert review.actions == [("approve", "one"), ("ignore", "one"), ("retry", "one")]

    page.closeResults()
    assert page.resultsOpen is False

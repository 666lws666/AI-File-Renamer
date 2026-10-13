"""M5 Watch page QML component, geometry, and interaction tests."""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtQml import QQmlExpression
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.controllers.watch_controller import ObserverFactory, WatchController
from src.controllers.watch_edit_handler import WatchEditHandler
from src.controllers.watch_page_controller import WatchPageController
from src.core.watch_config import WatchConfig, WatchConfigStore, WatchMode, WatchStatus
from src.core.watch_review_queue import ReviewItemState
from tests.qml.conftest import make_handle


QML = Path(__file__).parents[2] / "src" / "ui_qml"


@dataclass
class _Result:
    id: str
    watch_id: str
    display_name: str
    suggested_name: str
    state: ReviewItemState
    confidence: float = 0.92
    error_category: str = ""
    recovery_required: bool = False
    applied_path: str = ""
    batch_id: str = ""


class _Reviews:
    def __init__(self):
        self.rows = []
        self.undone = []

    def items(self, watch_id=None):
        return [row for row in self.rows if watch_id is None or row.watch_id == watch_id]

    def approve(self, _item_id): pass
    def ignore(self, _item_id): pass
    def retry(self, _item_id): pass
    def undo(self, item_id): self.undone.append(item_id); return True


def _controller(tmp_path, states=()):
    store = WatchConfigStore(tmp_path / "watches.json")
    for index, status in enumerate(states):
        source = tmp_path / f"source-{index}"
        source.mkdir()
        store.add(WatchConfig(
            id=f"watch-{index}",
            source_dir=str(source),
            template_id="general",
            mode=WatchMode.REVIEW_FIRST if index % 2 == 0 else WatchMode.AUTO_APPLY,
            status=status,
        ))
    reviews = _Reviews()
    backend = WatchController(
        store,
        observer_factory=ObserverFactory(use_mock=True),
        review_first_handler=reviews,
    )
    page = WatchPageController(
        watch_controller=backend,
        edit_handler=WatchEditHandler(backend),
        review_handler=reviews,
        templates_provider=lambda: [{"id": "general", "name": "General Naming (Default)"}],
    )
    return page, reviews


def _find(handle, name):
    return handle.root.findChild(QQuickItem, name)


def _mouse_click(handle, item):
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(handle._host_view, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(50)


def test_empty_state_and_real_add_click_open_left_fixed_form(tmp_path):
    ctrl, _reviews = _controller(tmp_path)
    handle = make_handle(QML / "WatchPage.qml", 1000, 668, ctrl)
    try:
        assert _find(handle, "watchPageTitle") is not None
        assert _find(handle, "watchEmptyState").property("visible") is True
        _mouse_click(handle, _find(handle, "addWatchButton"))
        form = _find(handle, "watchForm")
        assert ctrl.formOpen is True
        assert form.property("visible") is True
        assert form.property("width") <= 440
        assert form.property("x") <= 32
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_minimum_size_form_keeps_actions_visible_and_scrollable(tmp_path):
    ctrl, _reviews = _controller(tmp_path)
    ctrl.beginCreate()
    handle = make_handle(QML / "WatchPage.qml", 852, 608, ctrl)
    try:
        assert _find(handle, "watchFormSaveButton") is not None
        assert _find(handle, "watchFormCancelButton") is not None
        scroll = _find(handle, "watchFormScroll")
        assert scroll is not None
        save = _find(handle, "watchFormSaveButton")
        bottom = save.mapToScene(QPointF(save.width() / 2, save.height())).y()
        assert bottom <= handle.root.height()
        assert scroll.property("contentHeight") > 0
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_four_watch_status_cards_render_without_budget_state(tmp_path):
    ctrl, _reviews = _controller(
        tmp_path,
        (WatchStatus.ACTIVE, WatchStatus.PAUSED, WatchStatus.ERROR, WatchStatus.RESOURCE_PAUSED),
    )
    handle = make_handle(QML / "WatchPage.qml", 1000, 668, ctrl)
    try:
        view = _find(handle, "watchList")
        assert view.property("count") == 4
        statuses = {row["status"] for row in ctrl.watches}
        assert statuses == {"active", "paused", "error", "resource_paused"}
        assert all("budget" not in value for value in statuses)
        for index in range(4):
            row, undefined = QQmlExpression(handle.engine.rootContext(), view, f"itemAtIndex({index})").evaluate()
            assert undefined is False
            assert row is not None
            assert row.findChild(QQuickItem, "watchResultsButton") is not None
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_results_panel_is_scoped_to_selected_watch(tmp_path):
    ctrl, reviews = _controller(tmp_path, (WatchStatus.PAUSED, WatchStatus.PAUSED))
    reviews.rows = [
        _Result("a", "watch-0", "invoice.pdf", "2026_invoice.pdf", ReviewItemState.AWAITING_APPROVAL),
        _Result("b", "watch-1", "other.pdf", "named.pdf", ReviewItemState.FAILED, error_category="provider"),
    ]
    ctrl.openResults("watch-0")
    handle = make_handle(QML / "WatchPage.qml", 1000, 668, ctrl)
    try:
        panel = _find(handle, "watchResultsPanel")
        assert panel.property("visible") is True
        results_list = _find(handle, "watchResultsList")
        assert results_list.property("count") == 1
        assert ctrl.results[0]["id"] == "a"
        close_button = _find(handle, "watchResultsCloseButton")
        assert close_button.mapToScene(QPointF(0, 0)).x() > panel.mapToScene(QPointF(panel.width() / 2, 0)).x()
        row, undefined = QQmlExpression(handle.engine.rootContext(), results_list, "itemAtIndex(0)").evaluate()
        assert undefined is False
        state_text = row.findChild(QQuickItem, "watchResultStateText")
        assert state_text.property("text") == "待确认"
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_main_router_opens_real_watch_page_with_precreation_controller(tmp_path):
    from src.models.app_config import AppConfig
    from src.qml_bootstrap import build_qml_runtime

    class Credentials:
        def get(self, *_args): return None
        def set(self, *_args): return True
        def delete(self, *_args): return True

    ctrl, _reviews = _controller(tmp_path)
    runtime = build_qml_runtime(
        live_config=AppConfig(),
        config_file=tmp_path / "settings.json",
        credential_store=Credentials(),
        connection_test_service=lambda *_args: None,
        usage_recorder=None,
        template_controller=None,
        watch_controller=ctrl,
    )
    try:
        router = runtime.root.findChild(QObject, "pageRouter")
        QQmlExpression(runtime.engine.rootContext(), router, "navigate('watch')").evaluate()
        QApplication.processEvents()
        assert router.property("currentPage") == "watch"
        assert router.property("currentItem").objectName() == "watchPage"
        runtime.assert_zero_warnings()
    finally:
        runtime.cleanup()


def test_results_actual_undo_and_recovery_hold_are_visible(tmp_path):
    ctrl, reviews = _controller(tmp_path, (WatchStatus.PAUSED,))
    reviews.rows = [
        _Result("applied", "watch-0", "original.txt", "named.txt", ReviewItemState.APPLIED,
            applied_path="synthetic/named.txt", batch_id="batch"),
        _Result("held", "watch-0", "held.txt", "held.txt", ReviewItemState.AWAITING_APPROVAL,
            recovery_required=True),
    ]
    ctrl._notice_provider = lambda _: "recovery_required"
    ctrl.openResults("watch-0")
    handle = make_handle(QML / "WatchPage.qml", 1000, 668, ctrl)
    try:
        notice = _find(handle, "watchResultNotice")
        assert notice is not None and notice.property("visible") is True
        view = _find(handle, "watchResultsList")
        applied, _ = QQmlExpression(handle.engine.rootContext(), view, "itemAtIndex(0)").evaluate()
        held, _ = QQmlExpression(handle.engine.rootContext(), view, "itemAtIndex(1)").evaluate()
        undo = applied.findChild(QQuickItem, "watchResultUndoButton")
        assert undo is not None and undo.property("visible") is True
        assert held.findChild(QQuickItem, "watchResultApproveButton").property("visible") is False
        assert held.findChild(QQuickItem, "watchResultRecoveryText").property("visible") is True
        _mouse_click(handle, undo)
        assert reviews.undone == ["applied"]
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_unavailable_watch_storage_is_visible_without_opening_results(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl._availability_provider = lambda: False
    handle = make_handle(QML / "WatchPage.qml", 1000, 668, ctrl)
    try:
        notice = _find(handle, "watchUnavailableNotice")
        assert notice is not None and notice.property("visible") is True
        assert "存储不可用" in notice.property("text")
        assert _find(handle, "addWatchButton").property("enabled") is False
        assert _find(handle, "watchEmptyAddButton").property("enabled") is False
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_actual_managed_video_sampling_coverage_is_rendered_without_full_content_claim(tmp_path):
    from src.core.managed_watch_metadata import ManagedWatchMetadata
    from src.core.watch_review_queue import ReviewItem
    from src.services.local_ai.preparation_protocol import PreparationCoverage
    ctrl, reviews = _controller(tmp_path, (WatchStatus.PAUSED,))
    metadata = ManagedWatchMetadata("video", "economy", "economy",
        PreparationCoverage("video", text_source="none", video_duration_seconds=8,
            video_timestamps_seconds=(0, 2, 4, 6)), ("video_sampled",))
    reviews.rows = [ReviewItem("video", "watch-0", str(tmp_path / "synthetic.mp4"), 1, 1,
        ".mp4", "synthetic.mp4", ReviewItemState.AWAITING_APPROVAL, "named.mp4", managed_metadata=metadata)]
    ctrl.openResults("watch-0")
    handle = make_handle(QML / "WatchPage.qml", 1000, 668, ctrl)
    try:
        view = _find(handle, "watchResultsList")
        row, _ = QQmlExpression(handle.engine.rootContext(), view, "itemAtIndex(0)").evaluate()
        coverage = row.findChild(QQuickItem, "watchResultCoverageText")
        assert coverage.property("visible") is True
        assert "采样关键帧" in coverage.property("text")
        assert "0, 2, 4, 6s" in coverage.property("text")
        assert ctrl.results[0]["confidence"] is None and ctrl.results[0]["autoApplyReviewReason"] == ""
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()

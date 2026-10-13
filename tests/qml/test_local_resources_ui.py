"""D4 component behavior: Qt mouse/state tests, not native visual acceptance."""
from pathlib import Path
import time

import pytest
from PySide6.QtCore import QObject, Property, Signal, Slot, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.qml.conftest import QML_DIR, make_handle
from src.controllers.processing_coordinator import ProcessingCoordinator
from src.core.processing_intent_store import ProcessingIntentStore
from src.core.processing_authority import LocalReadiness


class ChoiceWriter:
    def __init__(self, store, authority, completion_callback):
        self.callback = completion_callback
        self.pending = []
        self.accept = True

    def submit(self, intent):
        self.pending.append(intent)
        return self.accept

    def finish(self, success=True):
        self.callback(self.pending.pop(0), success)
        QApplication.processEvents()

    def close(self, **kwargs):
        return True


_DEFAULTS = dict(phase="NOT_READY", resourceState="missing", errorCode="",
    operationId="", busy=False, canPause=False, verifiedBytes=0,
    acquiredBytes=0, remainingTransferBytes=3431786583, totalBytes=3431786583,
    currentResourceId="", resourceRoot="C:/synthetic/public-resources/" + "long-folder/" * 15,
    modelName="Qwen/Qwen3.5-4B", runtimeVersion="b10885", recoveryState="missing",
    canPrepare=True, canDownload=True, canImport=True, canRetryCleanup=False)


class Resources(QObject):
    """Synthetic QObject resource boundary; no files, executables, or network."""
    stateChanged = Signal()
    phase = Property(str, lambda self: self.state["phase"], notify=stateChanged)
    resourceState = Property(str, lambda self: self.state["resourceState"], notify=stateChanged)
    errorCode = Property(str, lambda self: self.state["errorCode"], notify=stateChanged)
    operationId = Property(str, lambda self: self.state["operationId"], notify=stateChanged)
    busy = Property(bool, lambda self: self.state["busy"], notify=stateChanged)
    canPause = Property(bool, lambda self: self.state["canPause"], notify=stateChanged)
    verifiedBytes = Property("qlonglong", lambda self: self.state["verifiedBytes"], notify=stateChanged)
    acquiredBytes = Property("qlonglong", lambda self: self.state["acquiredBytes"], notify=stateChanged)
    remainingTransferBytes = Property("qlonglong", lambda self: self.state["remainingTransferBytes"], notify=stateChanged)
    totalBytes = Property("qlonglong", lambda self: self.state["totalBytes"], notify=stateChanged)
    currentResourceId = Property(str, lambda self: self.state["currentResourceId"], notify=stateChanged)
    resourceRoot = Property(str, lambda self: self.state["resourceRoot"], notify=stateChanged)
    modelName = Property(str, lambda self: self.state["modelName"], notify=stateChanged)
    runtimeVersion = Property(str, lambda self: self.state["runtimeVersion"], notify=stateChanged)
    recoveryState = Property(str, lambda self: self.state["recoveryState"], notify=stateChanged)
    canPrepare = Property(bool, lambda self: self.state["canPrepare"], notify=stateChanged)
    canDownload = Property(bool, lambda self: self.state["canDownload"], notify=stateChanged)
    canImport = Property(bool, lambda self: self.state["canImport"], notify=stateChanged)
    canRetryCleanup = Property(bool, lambda self: self.state["canRetryCleanup"], notify=stateChanged)

    def __init__(self):
        super().__init__()
        self.state = dict(_DEFAULTS)
        self.calls = []

    def update(self, **values):
        self.state.update(values)
        self.stateChanged.emit()
        QApplication.processEvents()

    def call(self, name, *args):
        self.calls.append((name, *args))
        return True

    @Slot(result=bool)
    def inspect(self): return self.call("inspect")
    @Slot("QVariant", result=bool)
    def downloadAndEnable(self, consent): return self.call("download", consent)
    @Slot(str, result=bool)
    def importAndEnable(self, path): return self.call("import", path)
    @Slot(result=bool)
    def prepareExisting(self): return self.call("prepare")
    @Slot(result=bool)
    def pause(self): return self.call("pause")
    @Slot(result=bool)
    def cancel(self): return self.call("cancel")
    @Slot(str, result=bool)
    def repairResource(self, rid): return self.call("repair", rid)
    @Slot(result=bool)
    def retryCleanup(self): return self.call("cleanup")


@pytest.fixture
def coordinator(tmp_path):
    ctrl = ProcessingCoordinator(ProcessingIntentStore(tmp_path / "choice.json"),
                                 writer_factory=ChoiceWriter)
    yield ctrl
    while ctrl._writer.pending:
        ctrl._writer.finish()
    assert ctrl.drain_choice_writer(deadline=time.monotonic() + 2)


@pytest.fixture
def ui(coordinator):
    handles = []
    def build(component, resources=None, locale="en-US", width=900, height=640):
        path = QML_DIR / component
        assert path.exists(), f"D4 component missing: {component}"
        ctrl = coordinator if component == "ProcessingModeBar.qml" else resources
        handle = make_handle(path, width, height, ctrl=ctrl, loc=locale)
        handle.root.setProperty("processingCoordinator", coordinator)
        if component == "ProcessingModeBar.qml":
            handle.root.setProperty("resourcesController", resources)
        handle._resource_reference = resources
        QApplication.processEvents()
        handles.append(handle)
        return handle
    yield build
    for handle in reversed(handles):
        handle.cleanup()
        handle.assert_zero_warnings()


def find(h, name):
    item = h.root.findChild(QObject, name)
    assert item is not None, name
    return item


def click(h, name):
    item = find(h, name)
    assert item.property("visible") and item.property("enabled"), name
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(h._host_view, Qt.LeftButton, Qt.NoModifier, point)
    QApplication.processEvents()


def test_real_choice_fences_cloud_and_waits_for_cloud_ack(ui, coordinator):
    h = ui("ProcessingModeBar.qml")
    click(h, "selectLocalButton")
    assert coordinator.processingMode == "local"
    assert coordinator.persistenceStatus == "pending"
    coordinator._writer.finish()
    click(h, "selectCloudButton")
    assert coordinator.processingMode == "local"
    assert "Saving" in find(h, "processingPersistenceText").property("text")
    coordinator._writer.finish()
    assert coordinator.processingMode == "cloud"


@pytest.mark.parametrize("readiness,key", [(LocalReadiness.PREPARING,"Preparing"),
    (LocalReadiness.FAILED,"failed"), (LocalReadiness.CANCELLED,"cancelled"),
    (LocalReadiness.READY,"enabled")])
def test_readiness_uses_coordinator_not_resource_available(ui, coordinator, readiness, key):
    resources = Resources()
    resources.update(phase="AVAILABLE", resourceState="available", operationId="checked")
    h = ui("ProcessingModeBar.qml", resources)
    click(h, "selectLocalButton")
    kwargs = {"engine_fingerprint": "a" * 64} if readiness is LocalReadiness.READY else {}
    coordinator.publish_local_state(coordinator.snapshot.generation, readiness, **kwargs)
    QApplication.processEvents()
    assert key in find(h, "processingStatusText").property("text")
    assert coordinator.processingMode == "local"


def test_inert_not_checked_available_not_enabled_and_64bit_bytes(ui, coordinator):
    resources = Resources()
    h = ui("LocalResourcesCard.qml", resources)
    assert "not checked" in find(h, "resourceStatusText").property("text")
    assert "3431786583" in find(h, "resourceBytesText").property("text")
    resources.update(operationId="checked", phase="AVAILABLE", resourceState="available",
                     verifiedBytes=3431786583, acquiredBytes=3431786583, remainingTransferBytes=0)
    assert "not enabled" in find(h, "resourceStatusText").property("text")
    assert "3431786583" in find(h, "resourceBytesText").property("text")


def test_download_consent_refusal_then_exact_true(ui, coordinator):
    coordinator.selectLocal()
    resources = Resources()
    h = ui("LocalResourcesCard.qml", resources, height=1000)
    click(h, "resourceDownloadButton")
    assert not resources.calls
    click(h, "resourceConsentRefuseButton")
    assert not resources.calls
    click(h, "resourceDownloadButton")
    click(h, "resourceConsentAcceptButton")
    assert resources.calls == [("download", True)]


def test_offline_exact_folder_dispatch_and_no_cloud_fallback(ui, coordinator):
    coordinator.selectLocal()
    resources = Resources()
    h = ui("LocalResourcesCard.qml", resources)
    h.root.importSelectedFolder("file:///C:/synthetic/public%20resources")
    assert resources.calls == [("import", "C:/synthetic/public resources")]
    resources.update(phase="FAILED", errorCode="HASH_MISMATCH", operationId="op")
    assert coordinator.processingMode == "local"
    resources.update(phase="CANCELLED")
    assert coordinator.processingMode == "local"


def test_pause_cancel_remain_pending_until_owner_changes(ui, coordinator):
    coordinator.selectLocal()
    resources = Resources()
    resources.update(phase="TRANSFERRING", busy=True, canPause=True, operationId="op", currentResourceId="model")
    h = ui("LocalResourcesCard.qml", resources, height=1000)
    click(h, "resourcePauseButton")
    assert "Waiting" in find(h, "resourceActionText").property("text")
    assert resources.busy
    click(h, "resourceCancelButton")
    assert resources.calls == [("pause",), ("cancel",)]
    resources.update(phase="CANCELLED", busy=False)
    assert "cancelled" in find(h, "resourceStatusText").property("text")
    assert coordinator.processingMode == "local"


def test_recovery_has_no_reset_and_only_retained_owner_cleanup(ui, coordinator):
    coordinator.selectLocal()
    resources = Resources()
    resources.update(phase="RECOVERY_REQUIRED", recoveryState="recovery_required", operationId="op")
    h = ui("LocalResourcesCard.qml", resources, height=1000)
    assert "previous" in find(h, "resourceStatusText").property("text")
    assert not find(h, "resourceCleanupButton").property("enabled")
    assert h.root.findChild(QObject, "resourceResetButton") is None
    resources.update(phase="CLEANUP_PENDING", canRetryCleanup=True)
    click(h, "resourceCleanupButton")
    assert resources.calls == [("cleanup",)]


@pytest.mark.parametrize("locale,expected", [("en-US","Local resources"),
    ("zh-CN","本地资源"), ("zh-HK","本機資源")])
def test_live_three_locale_text_and_safe_actions(ui, coordinator, locale, expected):
    resources = Resources()
    h = ui("LocalResourcesCard.qml", resources, height=1000)
    h.i18n.set_locale(locale)
    QApplication.processEvents()
    assert find(h, "resourceTitleText").property("text") == expected
    click(h, "resourceInspectButton")
    assert resources.calls == [("inspect",)]


def test_unavailable_bar_stays_visible(ui):
    h = ui("ProcessingModeBar.qml")
    h.root.setProperty("ctrl", None)
    QApplication.processEvents()
    assert "unavailable" in find(h, "processingStatusText").property("text")
    assert not find(h, "selectLocalButton").property("enabled")
    assert h.root.property("visible")


def test_unavailable_card_has_no_action_or_warning(ui):
    h = ui("LocalResourcesCard.qml", Resources())
    h.root.setProperty("ctrl", None)
    QApplication.processEvents()
    assert "unavailable" in find(h, "resourceStatusText").property("text")
    for name in ("resourceInspectButton", "resourcePrepareButton", "resourceDownloadButton",
                 "resourceImportButton", "resourcePauseButton", "resourceCancelButton",
                 "resourceRepairButton", "resourceCleanupButton"):
        assert not find(h, name).property("enabled")


def test_exact_known_item_repair_and_prepare_clicks(ui, coordinator):
    coordinator.selectLocal()
    resources = Resources()
    resources.update(operationId="checked", phase="FAILED", resourceState="error",
                     currentResourceId="model-q4")
    h = ui("LocalResourcesCard.qml", resources, height=1000)
    click(h, "resourceRepairButton")
    assert resources.calls == [("repair", "model-q4")]
    resources.update(currentResourceId="unknown-child")
    assert not find(h, "resourceRepairButton").property("enabled")
    resources.update(phase="AVAILABLE", resourceState="available", currentResourceId="")
    click(h, "resourcePrepareButton")
    assert resources.calls[-1] == ("prepare",)


def test_bar_keyboard_selection_and_persistence_failure(ui, coordinator):
    h = ui("ProcessingModeBar.qml")
    button = find(h, "selectLocalButton")
    button.forceActiveFocus()
    QTest.keyClick(h._host_view, Qt.Key_Space)
    QApplication.processEvents()
    assert coordinator.processingMode == "local"
    coordinator._writer.finish(False)
    assert coordinator.persistenceStatus == "error"
    click(h, "processingRetryButton")
    # Accepted retry reuses the intent: coordinator retains ERROR until ack.
    assert len(coordinator._writer.pending) == 1
    coordinator._writer.finish()
    assert coordinator.persistenceStatus == "saved"


def test_selected_local_is_named_in_text_not_only_button_color(ui, coordinator):
    h = ui("ProcessingModeBar.qml", Resources())
    click(h, "selectLocalButton")
    text = find(h, "processingStatusText").property("text")
    assert "Local privacy selected" in text and "not checked" in text


def test_current_resource_has_human_label_and_secondary_catalog_id(ui, coordinator):
    resources = Resources()
    resources.update(phase="TRANSFERRING", busy=True, currentResourceId="model-q4")
    h = ui("LocalResourcesCard.qml", resources)
    assert "Q4_K_M model" in find(h, "resourceCurrentText").property("text")
    assert "model-q4" in find(h, "resourceCurrentText").property("text")


@pytest.mark.parametrize("locale,retained", [
    ("en-US", "local mode is retained"),
    ("zh-CN", "仍保持本地模式"),
    ("zh-HK", "仍保持本機模式"),
])
@pytest.mark.parametrize("phase", ["FAILED", "CANCELLED", "PAUSED"])
def test_terminal_card_never_claims_local_after_acknowledged_cloud(ui, coordinator, locale, retained, phase):
    coordinator.selectLocal()
    coordinator._writer.finish()
    resources = Resources()
    resources.update(phase=phase, operationId="terminal-operation")
    card = ui("LocalResourcesCard.qml", resources, locale=locale)
    bar = ui("ProcessingModeBar.qml", resources, locale=locale)
    assert coordinator.processingMode == "local"
    assert card.i18n.tr("local.status.localSelected", card.i18n.locale) in find(card, "resourceStatusText").property("text")
    click(bar, "selectCloudButton")
    assert coordinator.processingMode == "local"  # not optimistic CLOUD paint
    coordinator._writer.finish()
    assert coordinator.processingMode == "cloud"
    text = find(card, "resourceStatusText").property("text")
    assert retained not in text, text
    assert card.i18n.tr("local.status.localSelected", card.i18n.locale) not in text


@pytest.mark.parametrize("phase", ["READY", "AVAILABLE"])
def test_same_ready_owner_busy_journal_is_enabled_not_recovery(ui, coordinator, phase):
    coordinator.selectLocal()
    coordinator._writer.finish()
    coordinator.publish_local_state(coordinator.snapshot.generation, LocalReadiness.READY,
                                    engine_fingerprint="c" * 64)
    resources = Resources()
    resources.update(phase=phase, resourceState="available", recoveryState="busy",
                     operationId="last-prepare-or-inspect", errorCode="")
    card = ui("LocalResourcesCard.qml", resources, height=1000)
    text = find(card, "resourceStatusText").property("text")
    assert text == card.i18n.tr("local.status.ready", card.i18n.locale)
    assert not card.root.property("safeRecovery")
    click(card, "resourcePrepareButton")
    assert resources.calls == [("prepare",)]
    bar = ui("ProcessingModeBar.qml", resources)
    click(bar, "selectCloudButton")
    coordinator._writer.finish()
    assert coordinator.processingMode == "cloud"
    assert find(card, "resourceStatusText").property("text") != card.i18n.tr("local.status.ready", card.i18n.locale)
    assert not find(card, "resourcePrepareButton").property("enabled")


@pytest.mark.parametrize("readiness,values", [
    (LocalReadiness.NOT_READY, dict(phase="AVAILABLE", resourceState="available", recoveryState="busy")),
    (LocalReadiness.READY, dict(phase="RECOVERY_REQUIRED", resourceState="available", recoveryState="busy")),
    (LocalReadiness.READY, dict(phase="READY", resourceState="available", recoveryState="recovery_required")),
    (LocalReadiness.READY, dict(phase="READY", resourceState="available", recoveryState="busy", errorCode="NATIVE_OWNERSHIP_UNCERTAIN")),
    (LocalReadiness.READY, dict(phase="READY", resourceState="available", recoveryState="busy", errorCode="RECOVERY_REQUIRED")),
    (LocalReadiness.READY, dict(phase="AVAILABLE", resourceState="error", recoveryState="busy", errorCode="HASH_MISMATCH")),
])
def test_busy_reconciliation_never_clears_unready_recovery_or_known_error(ui, coordinator, readiness, values):
    coordinator.selectLocal()
    coordinator._writer.finish()
    kwargs = {"engine_fingerprint": "d" * 64} if readiness is LocalReadiness.READY else {}
    coordinator.publish_local_state(coordinator.snapshot.generation, readiness, **kwargs)
    resources = Resources()
    resources.update(operationId="checked", **values)
    card = ui("LocalResourcesCard.qml", resources, height=1000)
    assert card.root.property("safeRecovery")
    assert find(card, "resourceStatusText").property("text") != card.i18n.tr("local.status.ready", card.i18n.locale)
    for name in ("resourceDownloadButton", "resourceImportButton", "resourcePrepareButton", "resourceRepairButton"):
        assert not find(card, name).property("enabled")


@pytest.mark.parametrize("phase", ["READY", "AVAILABLE"])
def test_known_error_cannot_claim_enabled_even_with_clean_observer(ui, coordinator, phase):
    coordinator.selectLocal()
    coordinator._writer.finish()
    coordinator.publish_local_state(coordinator.snapshot.generation, LocalReadiness.READY,
                                    engine_fingerprint="e" * 64)
    resources = Resources()
    resources.update(phase=phase, resourceState="available", recoveryState="clean",
                     operationId="checked", errorCode="HASH_MISMATCH")
    card = ui("LocalResourcesCard.qml", resources)
    assert not card.root.property("healthyLocalReady")
    assert find(card, "resourceStatusText").property("text") != card.i18n.tr("local.status.ready", card.i18n.locale)


def test_refused_mode_action_retranslates_visible_message(ui, coordinator):
    coordinator._writer.accept = False
    bar = ui("ProcessingModeBar.qml")
    click(bar, "selectLocalButton")
    english = bar.i18n.tr("local.action.refused", "en-US")
    message = next(item for item in bar.root.findChildren(QObject) if item.property("text") == english)
    assert message.property("visible")
    bar.i18n.set_locale("zh-HK")
    QApplication.processEvents()
    assert message.property("text") == bar.i18n.tr("local.action.refused", "zh-HK")


@pytest.mark.parametrize("locale", ["zh-CN", "zh-HK", "en-US"])
@pytest.mark.parametrize("size", [(1000, 700), (900, 640)])
def test_main_routing_same_references_and_minimum_scroll(coordinator, locale, size):
    resources = Resources()
    h = make_handle(QML_DIR / "main.qml", *size, loc=locale)
    h._resource_reference = resources
    try:
        h.root.setProperty("processingCoordinator", coordinator)
        h.root.setProperty("resourcesController", resources)
        QApplication.processEvents()
        bar = find(h, "processingModeBar")
        assert bar.property("ctrl") is coordinator
        assert bar.property("resourcesController") is resources
        router = find(h, "pageRouter")
        assert router.y() >= bar.y() + bar.height()
        router.navigate("preferences")
        QApplication.processEvents()
        card = find(h, "localResourcesCard")
        assert card.property("ctrl") is resources
        assert card.property("processingCoordinator") is coordinator
        general = find(h, "generalSettingsCard")
        assert card.y() >= general.y() + general.height()
        scroll = find(h, "preferencesScroll")
        flick = scroll.property("contentItem")
        assert flick.property("contentHeight") > flick.height()
        # Reach actual action controls through the single existing scroll area.
        button = find(h, "resourceInspectButton")
        target = button.mapToItem(flick, QPointF(0, 0)).y() + flick.property("contentY")
        flick.setProperty("contentY", min(target, flick.property("contentHeight") - flick.height()))
        QApplication.processEvents()
        center = button.mapToScene(QPointF(button.width()/2, button.height()/2))
        assert 0 <= center.x() <= size[0] and 0 <= center.y() <= size[1] - 56
        QTest.mouseClick(h.root, Qt.LeftButton, Qt.NoModifier, center.toPoint())
        QApplication.processEvents()
        assert resources.calls == [("inspect",)]
        assert find(h, "saveBtn").mapToScene(QPointF(0,0)).y() >= size[1] - 56
    finally:
        h.cleanup()
        h.assert_zero_warnings()

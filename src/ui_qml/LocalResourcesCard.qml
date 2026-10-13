import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs

Rectangle {
    id: root
    objectName: "localResourcesCard"
    property var ctrl: null
    property var processingCoordinator: null
    property bool consentOpen: false
    property string actionMessageKey: ""
    property string pendingOperationId: ""
    readonly property bool localSelected: !!processingCoordinator && processingCoordinator.processingMode === "local"
    readonly property bool idle: !!ctrl && !ctrl.busy
    // A read-only journal observer also sees BUSY for this graph's own READY
    // service lease. Only reconcile that observation with current shared READY,
    // verified available resources, and an error-free completed controller state.
    readonly property bool healthyLocalReady: localSelected && !!ctrl
        && processingCoordinator.localReadiness === "ready"
        && (ctrl.phase === "READY" || ctrl.phase === "AVAILABLE")
        && ctrl.resourceState === "available" && ctrl.errorCode === ""
        && ["missing", "clean", "busy"].indexOf(ctrl.recoveryState) >= 0
    readonly property bool safeRecovery: !!ctrl && (ctrl.phase === "RECOVERY_REQUIRED"
        || ctrl.errorCode === "RECOVERY_REQUIRED" || ctrl.errorCode === "NATIVE_OWNERSHIP_UNCERTAIN"
        || ctrl.recoveryState === "recovery_required"
        || (ctrl.recoveryState === "busy" && !healthyLocalReady))
    readonly property bool exactRepair: !!ctrl && ["runtime-cpu", "model-q4", "vision-f16"].indexOf(ctrl.currentResourceId) >= 0 && (ctrl.resourceState === "error" || ctrl.resourceState === "partial")
    color: DesignTokens.bgPrimary
    radius: DesignTokens.radiusLg
    border.width: 1; border.color: DesignTokens.borderLight
    implicitHeight: content.implicitHeight + DesignTokens.spacingXl * 2

    function statusKey() {
        if (!ctrl) return "local.status.unavailable"
        if (ctrl.phase === "CLEANUP_PENDING" && ctrl.canRetryCleanup) return "local.status.cleanup"
        if (safeRecovery) return "local.status.recovery"
        if (healthyLocalReady) return "local.status.ready"
        if (!ctrl.operationId && ctrl.phase === "NOT_READY") return "local.status.unchecked"
        if ((ctrl.phase === "READY" || ctrl.phase === "AVAILABLE") && ctrl.errorCode !== "") return "local.status.failed"
        if (ctrl.phase === "READY") {
            return ctrl.resourceState === "available" ? "local.status.available" : "local.status.notReady"
        }
        switch (ctrl.phase) {
        case "AVAILABLE": return "local.status.available"
        case "TRANSFERRING": return "local.status.transferring"
        case "VERIFYING": return "local.status.verifying"
        case "PREPARING": return "local.status.preparing"
        case "CLEANUP_PENDING": return "local.status.cleanup"
        case "FAILED": return "local.status.failed"
        case "CANCELLED": return "local.status.cancelled"
        case "PAUSED": return "local.status.paused"
        }
        return ctrl.resourceState === "partial" ? "local.status.partial" : "local.status.missing"
    }
    function acted(accepted, pending) {
        actionMessageKey = accepted ? (pending ? "local.action.waiting" : "local.action.accepted") : "local.action.refused"
        pendingOperationId = pending && ctrl ? ctrl.operationId : ""
    }
    function currentResourceLabel() {
        if (!ctrl) return ""
        switch (ctrl.currentResourceId) {
        case "runtime-cpu": return i18n.tr("local.item.runtime", i18n.locale) + " (runtime-cpu)"
        case "model-q4": return i18n.tr("local.item.model", i18n.locale) + " (model-q4)"
        case "vision-f16": return i18n.tr("local.item.vision", i18n.locale) + " (vision-f16)"
        }
        return i18n.tr("local.item.unknown", i18n.locale)
    }
    function terminalModeSuffix() {
        if (!ctrl || !localSelected || ["FAILED", "CANCELLED", "PAUSED"].indexOf(ctrl.phase) < 0) return ""
        return " · " + i18n.tr("local.status.localSelected", i18n.locale)
    }
    // FolderDialog supplies a local URL. Decode once; never pick executables or manifests.
    function importSelectedFolder(url) {
        if (!ctrl || !localSelected || !ctrl.canImport || !idle || safeRecovery) return
        var value = String(url)
        if (value.indexOf("file:///") !== 0) { acted(false, false); return }
        var path = decodeURIComponent(value.substring(8))
        acted(ctrl.importAndEnable(path), false)
    }
    Connections {
        target: root.ctrl || null
        function onStateChanged() {
            if (root.pendingOperationId !== "" && (!root.ctrl.busy || root.ctrl.operationId !== root.pendingOperationId)) {
                root.pendingOperationId = ""
                root.actionMessageKey = ""
            }
        }
    }
    Connections {
        target: root.processingCoordinator || null
        function onStateChanged() { if (!root.localSelected) root.consentOpen = false }
    }
    FolderDialog {
        id: resourceFolderDialog
        objectName: "resourceFolderDialog"
        title: i18n.tr("local.import.title", i18n.locale)
        onAccepted: root.importSelectedFolder(selectedFolder)
    }

    ColumnLayout {
        id: content
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        anchors.margins: DesignTokens.spacingXl
        spacing: DesignTokens.spacingMd
        Text {
            objectName: "resourceTitleText"
            Layout.fillWidth: true; wrapMode: Text.Wrap
            text: i18n.tr("local.resources.title", i18n.locale)
            font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeLg
            font.bold: true; color: DesignTokens.textPrimary
        }
        Text {
            objectName: "resourceStatusText"
            Layout.fillWidth: true; wrapMode: Text.Wrap
            text: i18n.tr(root.statusKey(), i18n.locale) + root.terminalModeSuffix()
            font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeMd
            color: DesignTokens.textPrimary
            Accessible.role: Accessible.StaticText; Accessible.name: text
        }
        ProgressBar {
            Layout.fillWidth: true
            visible: !!root.ctrl && root.ctrl.busy
            indeterminate: true
        }
        Text {
            objectName: "resourceIdentityText"
            Layout.fillWidth: true; wrapMode: Text.Wrap
            text: "Qwen/Qwen3.5-4B · Q4_K_M · " + i18n.tr("local.resources.vision", i18n.locale) + " · llama.cpp b10885\n" + i18n.tr("local.resources.pinned", i18n.locale)
            font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeMd
            color: DesignTokens.textPrimary
        }
        Text {
            objectName: "resourceLocationText"
            Layout.fillWidth: true; wrapMode: Text.Wrap
            text: i18n.tr("local.resources.location", i18n.locale) + "\n" + (root.ctrl ? root.ctrl.resourceRoot : i18n.tr("local.status.unavailable", i18n.locale))
            font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm
            color: DesignTokens.textSecondary
        }
        Text {
            objectName: "resourceBytesText"
            Layout.fillWidth: true; wrapMode: Text.Wrap
            text: i18n.tr("local.bytes.verified", i18n.locale) + ": " + (root.ctrl ? root.ctrl.verifiedBytes : "—") + " B\n"
                  + i18n.tr("local.bytes.acquired", i18n.locale) + ": " + (root.ctrl ? root.ctrl.acquiredBytes : "—") + " B\n"
                  + i18n.tr("local.bytes.remaining", i18n.locale) + ": " + (root.ctrl ? root.ctrl.remainingTransferBytes : "—") + " B\n"
                  + i18n.tr("local.bytes.installed", i18n.locale) + ": 3431786583 B (3.43 GB)"
            font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeMd
            color: DesignTokens.textPrimary
        }
        Text {
            objectName: "resourceSourceText"
            Layout.fillWidth: true; wrapMode: Text.Wrap
            text: i18n.tr("local.resources.sources", i18n.locale)
            font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm
            color: DesignTokens.textSecondary
        }
        Text {
            Layout.fillWidth: true; wrapMode: Text.Wrap
            text: i18n.tr("local.resources.observations", i18n.locale) + "\n" + i18n.tr("local.resources.storage", i18n.locale)
            font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm
            color: DesignTokens.textSecondary
        }
        Text {
            objectName: "resourceCurrentText"
            visible: !!root.ctrl && root.ctrl.currentResourceId !== ""
            Layout.fillWidth: true; wrapMode: Text.Wrap
            text: i18n.tr("local.resources.current", i18n.locale) + ": " + root.currentResourceLabel()
            font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm
            color: DesignTokens.textSecondary
        }
        Text {
            visible: !root.localSelected
            Layout.fillWidth: true; wrapMode: Text.Wrap
            text: i18n.tr("local.resources.chooseLocal", i18n.locale)
            font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeMd
            color: DesignTokens.textSecondary
        }
        Flow {
            Layout.fillWidth: true
            spacing: DesignTokens.spacingSm
            AppButton {
                objectName: "resourceInspectButton"
                text: i18n.tr("local.action.inspect", i18n.locale)
                enabled: root.idle
                onClicked: root.acted(root.ctrl.inspect(), false)
            }
            AppButton {
                objectName: "resourceDownloadButton"
                text: i18n.tr("local.action.download", i18n.locale)
                primary: true
                enabled: root.idle && root.localSelected && root.ctrl.canDownload && !root.safeRecovery
                onClicked: root.consentOpen = true
            }
            AppButton {
                objectName: "resourceImportButton"
                text: i18n.tr("local.action.import", i18n.locale)
                enabled: root.idle && root.localSelected && root.ctrl.canImport && !root.safeRecovery
                onClicked: resourceFolderDialog.open()
            }
            AppButton {
                objectName: "resourcePrepareButton"
                text: i18n.tr("local.action.prepare", i18n.locale)
                enabled: root.idle && root.localSelected && root.ctrl.canPrepare && !root.safeRecovery
                onClicked: root.acted(root.ctrl.prepareExisting(), false)
            }
            AppButton {
                objectName: "resourcePauseButton"
                text: i18n.tr("local.action.pause", i18n.locale)
                enabled: !!root.ctrl && root.ctrl.busy && root.ctrl.canPause
                onClicked: root.acted(root.ctrl.pause(), true)
            }
            AppButton {
                objectName: "resourceCancelButton"
                text: i18n.tr("local.action.cancel", i18n.locale)
                enabled: !!root.ctrl && root.ctrl.busy
                onClicked: root.acted(root.ctrl.cancel(), true)
            }
            AppButton {
                objectName: "resourceRepairButton"
                text: i18n.tr("local.action.repair", i18n.locale)
                enabled: root.idle && root.localSelected && root.ctrl.canPrepare && root.exactRepair && !root.safeRecovery
                onClicked: root.acted(root.ctrl.repairResource(root.ctrl.currentResourceId), false)
            }
            AppButton {
                objectName: "resourceCleanupButton"
                text: i18n.tr("local.action.cleanup", i18n.locale)
                enabled: root.idle && root.localSelected && root.ctrl.canRetryCleanup
                onClicked: root.acted(root.ctrl.retryCleanup(), false)
            }
        }
        ColumnLayout {
            visible: root.consentOpen
            Layout.fillWidth: true
            spacing: DesignTokens.spacingSm
            Text {
                objectName: "resourceConsentText"
                Layout.fillWidth: true; wrapMode: Text.Wrap
                text: i18n.tr("local.consent.body", i18n.locale)
                font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
            }
            Flow {
                Layout.fillWidth: true; spacing: DesignTokens.spacingSm
                AppButton {
                    objectName: "resourceConsentAcceptButton"
                    text: i18n.tr("local.consent.accept", i18n.locale)
                    primary: true
                    enabled: root.idle && root.localSelected && root.ctrl.canDownload && !root.safeRecovery
                    onClicked: { root.consentOpen = false; root.acted(root.ctrl.downloadAndEnable(true), false) }
                }
                AppButton {
                    objectName: "resourceConsentRefuseButton"
                    text: i18n.tr("local.consent.refuse", i18n.locale)
                    onClicked: root.consentOpen = false
                }
            }
        }
        Text {
            objectName: "resourceActionText"
            visible: root.actionMessageKey !== ""
            Layout.fillWidth: true; wrapMode: Text.Wrap
            text: root.actionMessageKey !== "" ? i18n.tr(root.actionMessageKey, i18n.locale) : ""
            font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeMd
            color: DesignTokens.textPrimary
        }
        Text {
            objectName: "resourceImmediateText"
            Layout.fillWidth: true; wrapMode: Text.Wrap
            text: i18n.tr("local.resources.immediate", i18n.locale) + "\n" + i18n.tr("local.resources.repairScope", i18n.locale)
            font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm
            color: DesignTokens.textSecondary
        }
    }
}

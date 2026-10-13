import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "processingModeBar"
    property var ctrl: null
    property var resourcesController: null
    // Explicit reference forwarded by the shell; no copied choice flag.
    property var processingCoordinator: ctrl
    property string actionMessageKey: ""
    color: DesignTokens.bgSecondary
    implicitHeight: content.implicitHeight + DesignTokens.spacingMd * 2

    function statusKey() {
        if (!ctrl) return "local.status.unavailable"
        if (ctrl.processingMode === "cloud") return "local.status.cloud"
        switch (ctrl.localReadiness) {
        case "ready": return "local.status.ready"
        case "preparing": return "local.status.preparing"
        case "failed": return "local.status.failed"
        case "cancelled": return "local.status.cancelled"
        }
        if (!resourcesController) return "local.status.unavailable"
        if (resourcesController.phase === "AVAILABLE") return "local.status.available"
        if (!resourcesController.operationId) return "local.status.unchecked"
        return "local.status.notReady"
    }
    function choose(local) {
        if (!ctrl || !ctrl.admissionOpen) return
        var accepted = local ? ctrl.selectLocal() : ctrl.selectCloud()
        actionMessageKey = accepted ? "" : "local.action.refused"
    }
    function persistenceText() {
        if (!ctrl) return ""
        switch (ctrl.persistenceStatus) {
        case "pending": return i18n.tr("local.persistence.pending", i18n.locale)
        case "saved": return i18n.tr("local.persistence.saved", i18n.locale)
        case "error": return i18n.tr("local.persistence.error", i18n.locale)
        }
        return ""
    }

    ColumnLayout {
        id: content
        anchors.left: parent.left; anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: DesignTokens.spacingMd
        spacing: DesignTokens.spacingSm
        RowLayout {
            Layout.fillWidth: true
            spacing: DesignTokens.spacingMd
            Text {
                text: i18n.tr("local.processing.title", i18n.locale)
                font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeMd
                font.bold: true; color: DesignTokens.textPrimary
            }
            AppButton {
                objectName: "selectCloudButton"
                text: i18n.tr("local.processing.cloud", i18n.locale)
                primary: !!root.ctrl && root.ctrl.processingMode === "cloud"
                enabled: !!root.ctrl && root.ctrl.admissionOpen
                onClicked: root.choose(false)
            }
            AppButton {
                objectName: "selectLocalButton"
                text: i18n.tr("local.processing.local", i18n.locale)
                primary: !!root.ctrl && root.ctrl.processingMode === "local"
                enabled: !!root.ctrl && root.ctrl.admissionOpen
                onClicked: root.choose(true)
            }
            Text {
                objectName: "processingStatusText"
                Layout.fillWidth: true
                text: (root.ctrl && root.ctrl.processingMode === "local" ? i18n.tr("local.status.localSelected", i18n.locale) + " · " : "") + i18n.tr(root.statusKey(), i18n.locale)
                wrapMode: Text.Wrap
                font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
                Accessible.role: Accessible.StaticText
                Accessible.name: text
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Text {
                objectName: "processingPersistenceText"
                Layout.fillWidth: true
                text: root.persistenceText()
                wrapMode: Text.Wrap
                font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm
                color: DesignTokens.textSecondary
            }
            AppButton {
                objectName: "processingRetryButton"
                visible: !!root.ctrl && root.ctrl.persistenceStatus === "error"
                enabled: !!root.ctrl && root.ctrl.admissionOpen
                text: i18n.tr("local.action.retryChoice", i18n.locale)
                onClicked: root.actionMessageKey = root.ctrl.retryChoice() ? "" : "local.action.refused"
            }
        }
        Text {
            objectName: "processingPrivacyText"
            Layout.fillWidth: true
            text: i18n.tr("local.processing.scope", i18n.locale)
            wrapMode: Text.Wrap
            font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm
            color: DesignTokens.textSecondary
        }
        Text {
            objectName: "processingActionText"
            visible: root.actionMessageKey !== ""
            Layout.fillWidth: true; wrapMode: Text.Wrap
            text: root.actionMessageKey !== "" ? i18n.tr(root.actionMessageKey, i18n.locale) : ""
            font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm
            color: DesignTokens.accentError
        }
    }
}

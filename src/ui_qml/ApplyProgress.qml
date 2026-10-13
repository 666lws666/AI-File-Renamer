import QtQuick; import QtQuick.Controls.Basic; import QtQuick.Layouts

Rectangle {
    id: root; objectName: "batchApplyProgress"
    color: DesignTokens.bgSecondary; radius: DesignTokens.radiusMd
    border.width: 1; border.color: DesignTokens.borderLight
    property var ctrl: null
    property bool active: ctrl ? ctrl.applyInProgress : false

    ColumnLayout {
        anchors.fill: parent; anchors.margins: 8; spacing: 5
        visible: root.active
        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            Text {
                objectName: "applyProgressSummary"
                text: i18n.tr("batch.progress.applying", i18n.locale) + " "
                      + (ctrl ? ctrl.applyCurrent : 0) + "/" + (ctrl ? ctrl.applyTotal : 0)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd; font.bold: true
                color: DesignTokens.textPrimary
            }
            Item { Layout.fillWidth: true }
            Text {
                text: i18n.tr("batch.progress.success", i18n.locale).replace("{n}", ctrl ? ctrl.applySuccess : 0)
                color: DesignTokens.accentSuccess; font.pixelSize: DesignTokens.fontSizeSm
            }
            Text {
                text: i18n.tr("batch.progress.failed", i18n.locale).replace("{n}", ctrl ? ctrl.applyFailed : 0)
                color: DesignTokens.accentError; font.pixelSize: DesignTokens.fontSizeSm
            }
        }
        ProgressBar {
            objectName: "applyProgressBar"
            Layout.fillWidth: true
            Layout.preferredHeight: 8
            from: 0; to: ctrl ? ctrl.applyTotal : 1
            value: ctrl ? ctrl.applyCurrent : 0
        }
    }
}

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "systemStatusModal"
    property var ctrl: null
    readonly property string overall: ctrl ? ctrl.overall : "checking"
    readonly property int componentCount: ctrl ? ctrl.components.length : 0
    signal openSettingsRequested()
    signal closeRequested()
    function levelLabel(value) {
        if (value === "ready") return i18n.tr("status.level.ready", i18n.locale)
        if (value === "attention") return i18n.tr("status.level.attention", i18n.locale)
        if (value === "unavailable") return i18n.tr("status.level.unavailable", i18n.locale)
        return i18n.tr("status.level.checking", i18n.locale)
    }
    color: "#66000000"
    visible: true

    function open() {
        visible = true
        if (ctrl) ctrl.checkAll()
    }
    function close() {
        visible = false
        closeRequested()
    }

    TapHandler { onTapped: function(_point, button) { button.accepted = true } }

    Rectangle {
        id: card
        objectName: "statusCard"
        anchors.centerIn: parent
        width: Math.min(560, parent.width - 64)
        height: Math.min(468, parent.height - 56)
        radius: DesignTokens.radiusLg
        color: DesignTokens.bgPrimary
        border.width: 1
        border.color: DesignTokens.borderLight

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: DesignTokens.spacingXl
            spacing: DesignTokens.spacingMd

            RowLayout {
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    text: i18n.tr("status.title", i18n.locale)
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeXl
                    font.bold: true
                    color: DesignTokens.textPrimary
                }
                StatusChip {
                    status: root.overall
                    label: root.levelLabel(root.overall)
                }
            }

            Text {
                Layout.fillWidth: true
                text: i18n.tr("status.description", i18n.locale)
                wrapMode: Text.WordWrap
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textSecondary
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: DesignTokens.spacingSm
                Repeater {
                    model: root.ctrl ? root.ctrl.components : []
                    ComponentStatusRow {
                        required property var modelData
                        Layout.fillWidth: true
                        title: i18n.tr(modelData.name, i18n.locale)
                        detail: modelData.detail ? i18n.tr(modelData.detail, i18n.locale) : ""
                        status: modelData.status
                    }
                }
                Item { Layout.fillHeight: true }
            }

            Text {
                Layout.fillWidth: true
                visible: root.componentCount === 0
                text: i18n.tr("status.empty", i18n.locale)
                horizontalAlignment: Text.AlignHCenter
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textSecondary
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: DesignTokens.spacingSm
                Button {
                    objectName: "statusRecheckButton"
                    text: i18n.tr("status.recheck", i18n.locale)
                    onClicked: if (root.ctrl) root.ctrl.checkAll()
                }
                Item { Layout.fillWidth: true }
                Button {
                    objectName: "statusSettingsButton"
                    text: i18n.tr("status.openSettings", i18n.locale)
                    onClicked: root.openSettingsRequested()
                }
                Button {
                    objectName: "statusCloseButton"
                    text: i18n.tr("common.close", i18n.locale)
                    onClicked: root.close()
                }
            }
        }
    }
}

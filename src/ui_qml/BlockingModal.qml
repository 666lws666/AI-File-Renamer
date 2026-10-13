import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    property string title: ""
    property string message: ""
    property string actionText: ""
    signal actionRequested()
    signal closeRequested()
    color: "#66000000"
    visible: false
    Rectangle {
        id: card
        objectName: "blockingCard"
        anchors.centerIn: parent
        width: Math.min(440, parent.width - 64)
        implicitHeight: col.implicitHeight + DesignTokens.spacingXl * 2
        radius: DesignTokens.radiusLg
        color: DesignTokens.bgPrimary
        border.width: 1
        border.color: DesignTokens.borderLight
        ColumnLayout {
            id: col
            anchors.fill: parent
            anchors.margins: DesignTokens.spacingXl
            spacing: DesignTokens.spacingLg
            Text {
                Layout.fillWidth: true
                text: root.title
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeLg
                font.bold: true
                color: DesignTokens.textPrimary
            }
            Text {
                Layout.fillWidth: true
                text: root.message
                wrapMode: Text.WordWrap
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textSecondary
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                Button {
                    visible: root.actionText.length > 0
                    text: root.actionText
                    onClicked: root.actionRequested()
                }
                Button {
                    text: i18n.tr("common.close", i18n.locale)
                    onClicked: { root.visible = false; root.closeRequested() }
                }
            }
        }
    }
}

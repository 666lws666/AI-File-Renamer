import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    property string message: ""
    property bool retryable: false
    signal retryRequested()
    implicitHeight: row.implicitHeight + DesignTokens.spacingSm * 2
    color: "#fff7ed"
    radius: DesignTokens.radiusSm
    border.width: 1
    border.color: "#fed7aa"
    RowLayout {
        id: row
        anchors.fill: parent
        anchors.margins: DesignTokens.spacingSm
        Text { text: "!"; font.bold: true; color: DesignTokens.accentError }
        Text {
            Layout.fillWidth: true
            text: root.message
            wrapMode: Text.WordWrap
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeSm
            color: DesignTokens.textPrimary
        }
        Button {
            objectName: "fileErrorRetry"
            visible: root.retryable
            text: i18n.tr("error.retry", i18n.locale)
            onClicked: root.retryRequested()
        }
    }
}

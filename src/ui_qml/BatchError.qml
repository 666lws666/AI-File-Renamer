import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    property int successCount: 0
    property int failureCount: 0
    property bool retryable: false
    signal retryRequested()
    implicitHeight: row.implicitHeight + DesignTokens.spacingMd * 2
    radius: DesignTokens.radiusMd
    color: "#fff7ed"
    border.width: 1
    border.color: "#fed7aa"
    RowLayout {
        id: row
        anchors.fill: parent
        anchors.margins: DesignTokens.spacingMd
        Text {
            objectName: "batchErrorSummary"
            Layout.fillWidth: true
            text: i18n.tr("error.batch.summary", i18n.locale)
                .replace("{success}", root.successCount)
                .replace("{failed}", root.failureCount)
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeMd
            color: DesignTokens.textPrimary
        }
        Button {
            visible: root.retryable
            text: i18n.tr("error.retryFailed", i18n.locale)
            onClicked: root.retryRequested()
        }
    }
}

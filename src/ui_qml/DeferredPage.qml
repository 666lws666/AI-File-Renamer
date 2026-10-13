import QtQuick
import QtQuick.Controls.Basic

Rectangle {
    id: root
    color: DesignTokens.bgPrimary

    property string pageId: ""
    property bool developmentScaffold: true

    Column {
        anchors.centerIn: parent
        spacing: DesignTokens.spacingMd

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "🚧"
            font.pixelSize: 32
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: i18n.tr("deferred.title")
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeXl
            color: DesignTokens.textSecondary
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: i18n.tr("deferred.description")
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeMd
            color: DesignTokens.textSecondary
        }
    }
}

import QtQuick
import QtQuick.Controls.Basic

Rectangle {
    id: root
    height: 32
    color: DesignTokens.bgPrimary

    signal minimizeRequested()
    signal maximizeRequested()
    signal closeRequested()

    DragHandler {
        onActiveChanged: if (active) root.Window.window?.startSystemMove()
    }

    Text {
        anchors.left: parent.left; anchors.leftMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        text: i18n.tr("app.name")
        font.family: DesignTokens.fontFamily
        font.pixelSize: DesignTokens.fontSizeSm
        color: DesignTokens.textSecondary
    }

    Row {
        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 2; height: parent.height
        Rectangle {
            width: 36; height: parent.height; color: "transparent"; radius: 0
            Text { anchors.centerIn: parent; text: "─"; font.pixelSize: DesignTokens.fontSizeMd; color: DesignTokens.textSecondary }
            TapHandler { onTapped: root.minimizeRequested() }
            Accessible.name: i18n.tr("titlebar.minimize")
        }
        Rectangle {
            width: 36; height: parent.height; color: "transparent"; radius: 0
            Text { anchors.centerIn: parent; text: "□"; font.pixelSize: DesignTokens.fontSizeMd; color: DesignTokens.textSecondary }
            TapHandler { onTapped: root.maximizeRequested() }
            Accessible.name: i18n.tr("titlebar.maximize")
        }
        Rectangle {
            width: 36; height: parent.height; color: "transparent"; radius: 0
            Text { anchors.centerIn: parent; text: "✕"; font.pixelSize: DesignTokens.fontSizeSm; color: DesignTokens.textSecondary }
            TapHandler { onTapped: root.closeRequested() }
            Accessible.name: i18n.tr("titlebar.close")
        }
    }
}

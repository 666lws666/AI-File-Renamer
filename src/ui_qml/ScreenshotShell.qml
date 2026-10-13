import QtQuick
import QtQuick.Controls.Basic

Rectangle {
    id: root
    width: 1000; height: 700
    color: DesignTokens.bgPrimary
    objectName: "screenshotShell"

    TitleBar {
        id: titleBar
        anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
        height: DesignTokens.titleBarHeight
    }

    NavBar {
        id: navBar
        anchors.top: titleBar.bottom; anchors.left: parent.left; anchors.bottom: parent.bottom
        width: DesignTokens.navBarWidth
        currentPage: pageRouter.currentPage
        onPageSelected: function(p) { pageRouter.navigate(p) }
    }

    PageRouter {
        id: pageRouter
        anchors.top: titleBar.bottom; anchors.left: navBar.right; anchors.right: parent.right; anchors.bottom: parent.bottom
    }

    Component.onCompleted: pageRouter.navigate("batch")
}

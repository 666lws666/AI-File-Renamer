import QtQuick
import QtQuick.Controls.Basic

Rectangle {
    id: shell
    color: DesignTokens.bgPrimary
    anchors.fill: parent

    TitleBar {
        id: titleBar
        anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
        height: DesignTokens.titleBarHeight
        onMinimizeRequested: shell.Window.window?.showMinimized()
        onMaximizeRequested: { if (shell.Window.window?.visibility === Window.Maximized) shell.Window.window.showNormal(); else shell.Window.window?.showMaximized() }
        onCloseRequested: {
            if (pageRouter.requestClose()) shell.Window.window?.close()
        }
    }

    NavBar {
        id: navBar
        anchors.top: titleBar.bottom; anchors.left: parent.left; anchors.bottom: parent.bottom
        width: DesignTokens.navBarWidth
        currentPage: statusModal.visible ? "status" : pageRouter.currentPage
        statusOverall: shell.statusController ? shell.statusController.overall : "checking"
        statusAvailable: shell.statusController !== null
        onPageSelected: function(p) {
            if (p === "status") {
                statusModal.open()
            } else {
                statusModal.visible = false
                pageRouter.navigate(p)
            }
        }
    }

    property var settingsController: null
    property var templateController: null
    property var watchController: null
    property var statusController: null
    property var processingCoordinator: null
    property var resourcesController: null

    ProcessingModeBar {
        id: processingBar
        anchors.top: titleBar.bottom; anchors.left: navBar.right; anchors.right: parent.right
        height: implicitHeight
        ctrl: shell.processingCoordinator
        resourcesController: shell.resourcesController
    }

    PageRouter {
        id: pageRouter
        settingsController: shell.settingsController
        templateController: shell.templateController
        watchController: shell.watchController
        processingCoordinator: shell.processingCoordinator
        resourcesController: shell.resourcesController
        anchors.top: processingBar.bottom; anchors.left: navBar.right; anchors.right: parent.right; anchors.bottom: parent.bottom
    }

    StatusModal {
        id: statusModal
        ctrl: shell.statusController
        anchors.fill: parent
        visible: false
        z: 200
        onOpenSettingsRequested: {
            visible = false
            pageRouter.navigate("preferences")
        }
    }

    Rectangle {
        id: windowBoundary
        objectName: "windowBoundary"
        anchors.fill: parent
        color: "transparent"
        readonly property int boundaryWidth: DesignTokens.windowBorderWidth
        readonly property color boundaryColor: DesignTokens.windowBorderColor
        border.width: boundaryWidth
        border.color: boundaryColor
        enabled: false
        visible: shell.Window.window
                 && shell.Window.window.visibility !== Window.Maximized
                 && shell.Window.window.visibility !== Window.FullScreen
        z: 1000
    }

    Component.onCompleted: pageRouter.navigate("batch")
}

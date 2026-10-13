import QtQuick
import QtQuick.Controls.Basic
import ui_qml 1.0

ApplicationWindow {
    id: appWindow
    width: 1000
    height: 700
    minimumWidth: 900
    minimumHeight: 640
    visible: true
    flags: Qt.FramelessWindowHint | Qt.Window
    color: DesignTokens.bgPrimary

    // B: injectable SettingsController — provided by the QML bootstrap
    // factory before component creation (createWithInitialProperties).
    property var settingsController: null
    property var templateController: null
    property var watchController: null
    property var statusController: null
    property var processingCoordinator: typeof processingController !== "undefined" ? processingController : null
    property var resourcesController: typeof localResourcesController !== "undefined" ? localResourcesController : null

    Shell {
        id: mainShell
        objectName: "m1Shell"
        settingsController: appWindow.settingsController
        templateController: appWindow.templateController
        watchController: appWindow.watchController
        statusController: appWindow.statusController
        processingCoordinator: appWindow.processingCoordinator
        resourcesController: appWindow.resourcesController
        anchors.fill: parent
    }
}

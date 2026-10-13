import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

StackView {
    id: root
    objectName: "pageRouter"

    property string currentPage: "batch"
    property var settingsController: null
    property var templateController: null
    property var watchController: null
    property var processingCoordinator: null
    property var resourcesController: null

    // F: pending destination while the unsaved-changes dialog is open
    property string pendingPage: ""

    function currentPreferences() {
        var item = root.currentItem
        if (item && item.objectName === "preferencesPage") return item
        return null
    }

    function requestClose() {
        var prefs = currentPreferences()
        if (prefs && prefs.ctrl && prefs.ctrl.dirty) {
            root.pendingPage = "__close__"
            unsavedDialog.visible = true
            return false
        }
        return true
    }

    function doCloseWindow() {
        var win = root.Window.window
        if (win) win.close()
    }

    function navigate(pageId) {
        if (pageId === "preferences") {
            doNavigate(pageId)
            return
        }
        // F.1: dirty Preferences must not be replaced immediately
        var prefs = currentPreferences()
        if (prefs && prefs.ctrl && prefs.ctrl.dirty) {
            root.pendingPage = pageId
            unsavedDialog.visible = true
            return
        }
        doNavigate(pageId)
    }

    function doNavigate(pageId) {
        var comp = null
        var props = {}
        switch (pageId) {
            case "batch": comp = batchComponent; break
            case "watch":
                comp = watchComponent
                props.pageId = pageId
                props.ctrl = root.watchController
                break
            case "templates":
                comp = templatesComponent
                props.pageId = pageId
                props.ctrl = root.templateController
                break
            case "status":
                comp = deferredComponent
                props.pageId = pageId
                break
            case "preferences":
                comp = preferencesComponent
                props.ctrl = root.settingsController
                props.router = root
                props.templateController = root.templateController
                props.processingCoordinator = root.processingCoordinator
                props.resourcesController = root.resourcesController
                break
            default:
                comp = deferredComponent
                props.pageId = pageId
                break
        }
        if (comp) {
            if (root.depth === 0) {
                root.push(comp, props, StackView.Immediate)
            } else {
                root.replace(root.currentItem, comp, props, StackView.Immediate)
            }
            root.currentPage = pageId
        }
    }

    // --- Unsaved-changes dialog actions (F) ---

    function onUnsavedSave() {
        // F.3: save first; navigate only after saveSucceeded
        var prefs = currentPreferences()
        var target = root.pendingPage
        if (!prefs || !prefs.ctrl) {
            root.pendingPage = ""
            unsavedDialog.visible = false
            doNavigate(target)
            return
        }
        prefs.doSave()
    }

    function onUnsavedDiscard() {
        // F.4: discard then navigate
        var prefs = currentPreferences()
        var target = root.pendingPage
        root.pendingPage = ""
        unsavedDialog.visible = false
        if (prefs && prefs.ctrl) prefs.ctrl.cancel()
        if (target === "__close__") doCloseWindow()
        else doNavigate(target)
    }

    function onUnsavedKeep() {
        // F.5: close the dialog, stay on Preferences, draft untouched
        root.pendingPage = ""
        unsavedDialog.visible = false
    }

    // PreferencesPage cancel button (dirty) reuses the same discard semantics
    function openUnsavedForCancel() {
        root.pendingPage = "batch"
        unsavedDialog.visible = true
    }

    function leavePreferences() {
        doNavigate("batch")
    }

    // Save outcome drives pending navigation
    Connections {
        target: root.settingsController
        function onSaveSucceeded() {
            if (root.pendingPage !== "") {
                var target = root.pendingPage
                root.pendingPage = ""
                unsavedDialog.visible = false
                if (target === "__close__") doCloseWindow()
                else doNavigate(target)
            }
        }
        function onSaveFailed(msg) {
            // F.3: stay on Preferences; the page displays the error
            root.pendingPage = ""
            unsavedDialog.visible = false
        }
    }

    Component {
        id: batchComponent
        BatchPage {}
    }

    Component {
        id: deferredComponent
        DeferredPage {}
    }

    Component {
        id: preferencesComponent
        PreferencesPage {}
    }

    Component {
        id: templatesComponent
        TemplatesPage {}
    }

    Component {
        id: watchComponent
        WatchPage {}
    }

    // --- F: Unsaved-changes confirmation dialog (three options) ---
    Rectangle {
        id: unsavedDialog
        objectName: "unsavedDialog"
        visible: false
        anchors.fill: parent
        z: 100
        color: "#66000000"

        Rectangle {
            id: dialogCard
            anchors.centerIn: parent
            width: 380
            implicitHeight: dialogCol.implicitHeight + DesignTokens.spacingXl * 2
            radius: DesignTokens.radiusLg
            color: DesignTokens.bgPrimary
            border.width: 1
            border.color: DesignTokens.borderLight

            ColumnLayout {
                id: dialogCol
                anchors.fill: parent
                anchors.margins: DesignTokens.spacingXl
                spacing: DesignTokens.spacingLg

                Text {
                    text: i18n.tr("prefs.unsaved.title")
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeLg
                    font.bold: true
                    color: DesignTokens.textPrimary
                }
                Text {
                    text: i18n.tr("prefs.unsaved.message")
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeMd
                    color: DesignTokens.textSecondary
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: DesignTokens.spacingMd
                    Button {
                        objectName: "unsavedSaveBtn"
                        text: i18n.tr("prefs.unsaved.save")
                        onClicked: root.onUnsavedSave()
                    }
                    Button {
                        objectName: "unsavedDiscardBtn"
                        text: i18n.tr("prefs.unsaved.discard")
                        onClicked: root.onUnsavedDiscard()
                    }
                    Button {
                        objectName: "unsavedKeepBtn"
                        text: i18n.tr("prefs.unsaved.continue")
                        onClicked: root.onUnsavedKeep()
                    }
                }
            }
        }
    }
}

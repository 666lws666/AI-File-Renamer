import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs

Rectangle {
    id: root
    color: DesignTokens.bgPrimary
    property var ctrl: batchController
    property var importCounts: [0, 0, 0, 0]
    property bool importNoticeVisible: false
    property var pendingImportPaths: []
    property string pendingImportKind: ""

    function requestImport(kind, paths) {
        if (!root.ctrl || namingDialog.visible || paths.length === 0) return
        root.pendingImportKind = kind
        root.pendingImportPaths = root.localPaths(paths)
        const options = root.ctrl.templateOptions || []
        const selected = options.find(item => item.id === root.ctrl.selectedTemplateId)
        namingDialog.templateName = selected ? selected.name : i18n.tr("prefs.general.templateAuto", i18n.locale)
        namingDialog.templateLanguage = selected && selected.outputLanguage ? selected.outputLanguage : "zh"
        namingDialog.draftLanguage = typeof root.ctrl.namingLanguage === "string" ? root.ctrl.namingLanguage : ""
        namingDialog.visible = true
    }
    function clearPendingImport() {
        namingDialog.visible = false
        root.pendingImportPaths = []
        root.pendingImportKind = ""
    }
    NamingLanguageDialog {
        id: namingDialog
        anchors.fill: parent
        z: 1000
        namingMode: root.ctrl && typeof root.ctrl.namingMode === "string"
            ? root.ctrl.namingMode : "template"
        onCancelled: root.clearPendingImport()
        onConfirmed: function(language) {
            const paths = root.pendingImportPaths
            const kind = root.pendingImportKind
            if (root.ctrl && paths.length > 0) {
                if (typeof root.ctrl.setNamingLanguage === "function") root.ctrl.setNamingLanguage(language)
                root.clearPendingImport()
                if (kind === "folder") root.ctrl.addFolder(paths[0].toString(), true)
                else if (kind === "drop") root.ctrl.importDropped(paths)
                else root.ctrl.addPaths(paths)
            }
        }
    }

    Connections {
        target: root.ctrl
        ignoreUnknownSignals: true
        function onImportCompleted(added, duplicate, unsupported, unavailable) {
            root.importCounts = [added, duplicate, unsupported, unavailable]
            root.importNoticeVisible = true
            importNoticeTimer.restart()
        }
    }
    Timer {
        id: importNoticeTimer
        interval: 10000
        onTriggered: root.importNoticeVisible = false
    }

    function localPaths(urls) {
        const result = []
        for (let index = 0; index < urls.length; ++index)
            result.push(urls[index])
        return result
    }

    FileDialog {
        id: fileDialog
        objectName: "batchFileDialog"
        title: i18n.tr("batch.dialog.selectFiles", i18n.locale)
        fileMode: FileDialog.OpenFiles
        nameFilters: [i18n.tr("batch.dialog.supportedFiles", i18n.locale) + " (*)"]
        onAccepted: root.requestImport("files", root.localPaths(selectedFiles))
    }
    FolderDialog {
        id: folderDialog
        objectName: "batchFolderDialog"
        title: i18n.tr("batch.dialog.selectFolder", i18n.locale)
        onAccepted: root.requestImport("folder", [selectedFolder.toString()])
    }
    FolderDialog {
        id: targetDialog
        objectName: "batchTargetDialog"
        title: i18n.tr("batch.dialog.selectTarget", i18n.locale)
        onAccepted: if (root.ctrl) root.ctrl.setTargetDirectory(selectedFolder.toString())
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        BatchToolbar {
            id: toolbar
            Layout.fillWidth: true
            ctrl: root.ctrl
            onAddFilesRequested: fileDialog.open()
            onAddFolderRequested: folderDialog.open()
            onTargetDirectoryRequested: targetDialog.open()
        }
        ApplyProgress {
            Layout.fillWidth: true
            Layout.preferredHeight: 52
            ctrl: root.ctrl
            visible: root.ctrl ? root.ctrl.applyInProgress : false
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: importFeedback.implicitHeight + 20
            visible: root.importNoticeVisible
            color: DesignTokens.bgSecondary
            Text {
                id: importFeedback
                objectName: "batchImportFeedback"
                anchors.left: parent.left
                anchors.right: dismissImport.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.margins: 12
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
                wrapMode: Text.WordWrap
                text: i18n.tr("batch.import.summary", i18n.locale)
                    .replace("{added}", root.importCounts[0])
                    .replace("{duplicate}", root.importCounts[1])
                    .replace("{unsupported}", root.importCounts[2])
                    .replace("{unavailable}", root.importCounts[3])
            }
            Button {
                id: dismissImport
                objectName: "batchDismissImportFeedback"
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.rightMargin: 12
                text: i18n.tr("common.close", i18n.locale)
                onClicked: root.importNoticeVisible = false
            }
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Loader {
                anchors.fill: parent
                sourceComponent: (root.ctrl && root.ctrl.totalCount > 0) ? queueComponent : emptyComponent
            }
        }
    }

    Component {
        id: emptyComponent
        DropZone {
            anchors.fill: parent
            anchors.margins: 40
            ctrl: root.ctrl
            requestImport: function(paths) { root.requestImport("drop", paths) }
            onAddFilesClicked: fileDialog.open()
            onAddFolderClicked: folderDialog.open()
        }
    }

    Component {
        id: queueComponent
        TaskQueue { anchors.fill: parent; anchors.margins: 8; ctrl: root.ctrl }
    }
}

import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "batchDropZone"
    color: dropArea.containsDrag ? DesignTokens.bgNavSelected : DesignTokens.bgSecondary
    radius: DesignTokens.radiusLg
    border.width: 2
    border.color: dropArea.containsDrag ? DesignTokens.accentInfo : DesignTokens.borderLight
    property var ctrl: null
    property var requestImport: null

    signal addFilesClicked()
    signal addFolderClicked()

    DropArea {
        id: dropArea
        objectName: "batchDropArea"
        anchors.fill: parent
        keys: ["text/uri-list"]
        onDropped: function(drop) {
            const paths = []
            for (let index = 0; index < drop.urls.length; ++index)
                paths.push(drop.urls[index])
            if (root.requestImport) root.requestImport(paths)
            else if (root.ctrl) root.ctrl.importDropped(paths)
            drop.acceptProposedAction()
        }
    }

    ColumnLayout {
        anchors.centerIn: parent
        width: Math.max(0, Math.min(560, parent.width - 32))
        spacing: 12
        Image {
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 36; Layout.preferredHeight: 36
            source: "icons/watch_folder.svg"
            sourceSize.width: 36; sourceSize.height: 36
        }
        Text {
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: i18n.tr("batch.dropzone.hint", i18n.locale)
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeLg
            color: DesignTokens.textSecondary
        }
        Text {
            objectName: "formatsText"
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: i18n.tr("batch.dropzone.formatExamples", i18n.locale)
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeSm
            color: DesignTokens.textSecondary
        }
        Text {
            objectName: "batchFirstRunSteps"
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: i18n.tr("batch.dropzone.steps", i18n.locale)
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeMd
            color: DesignTokens.textPrimary
        }
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: 8
            AppButton {
                objectName: "dropZoneAddFilesButton"
                primary: true
                text: i18n.tr("batch.toolbar.addFiles", i18n.locale)
                onClicked: root.addFilesClicked()
            }
            AppButton {
                objectName: "dropZoneAddFolderButton"
                text: i18n.tr("batch.toolbar.addFolder", i18n.locale)
                onClicked: root.addFolderClicked()
            }
        }
        Text {
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: i18n.tr("batch.dropzone.reviewHint", i18n.locale)
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeSm
            color: DesignTokens.textSecondary
        }
    }
}

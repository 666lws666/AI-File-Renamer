import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs

Rectangle {
    id: root
    signal exportRequested(string destination)
    signal closeRequested()
    property string resultMessage: ""
    color: "#66000000"
    visible: false
    Rectangle {
        anchors.centerIn: parent
        width: Math.min(520, parent.width - 64)
        implicitHeight: col.implicitHeight + DesignTokens.spacingXl * 2
        radius: DesignTokens.radiusLg
        color: DesignTokens.bgPrimary
        border.width: 1
        border.color: DesignTokens.borderLight
        ColumnLayout {
            id: col
            anchors.fill: parent
            anchors.margins: DesignTokens.spacingXl
            spacing: DesignTokens.spacingMd
            Text {
                text: i18n.tr("diagnostics.title", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeXl
                font.bold: true
                color: DesignTokens.textPrimary
            }
            Text {
                text: i18n.tr("diagnostics.preview", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textSecondary
            }
            Text {
                objectName: "diagnosticsIncluded"
                Layout.fillWidth: true
                text: i18n.tr("diagnostics.included", i18n.locale)
                wrapMode: Text.WordWrap
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
            }
            Text {
                objectName: "diagnosticsExcluded"
                Layout.fillWidth: true
                text: i18n.tr("diagnostics.excluded", i18n.locale)
                wrapMode: Text.WordWrap
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.accentError
            }
            Text {
                objectName: "diagnosticsResult"
                visible: root.resultMessage.length > 0
                Layout.fillWidth: true
                text: root.resultMessage
                wrapMode: Text.WordWrap
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeSm
                color: DesignTokens.textSecondary
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                Button {
                    text: i18n.tr("common.cancel", i18n.locale)
                    onClicked: { root.visible = false; root.closeRequested() }
                }
                Button {
                    objectName: "diagnosticsExportButton"
                    text: i18n.tr("diagnostics.export", i18n.locale)
                    onClicked: saveDialog.open()
                }
            }
        }
    }

    FileDialog {
        id: saveDialog
        objectName: "diagnosticsSaveDialog"
        title: i18n.tr("diagnostics.saveAs", i18n.locale)
        fileMode: FileDialog.SaveFile
        nameFilters: [i18n.tr("diagnostics.zipFilter", i18n.locale)]
        defaultSuffix: "zip"
        onAccepted: root.exportRequested(selectedFile.toString())
    }
}

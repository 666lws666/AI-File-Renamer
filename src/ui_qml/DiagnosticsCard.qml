import QtQuick; import QtQuick.Controls.Basic; import QtQuick.Layouts

// Diagnostics card — honest export state.
//
// M7 will provide a real diagnostic-export service.  Until then:
// - serviceAvailable=false → the export button is DISABLED and shows only
//   "诊断服务尚未连接" — clicking it does nothing and never claims success;
// - a future real service must report completion through its own dedicated
//   completion signal, NOT through requestDiagnosticsExport().
Rectangle {
    id: root
    property var ctrl: null
    objectName: "diagnosticsCard"
    color: DesignTokens.bgPrimary
    radius: DesignTokens.radiusLg
    border.width: 1
    border.color: DesignTokens.borderLight
    implicitWidth: 400
    implicitHeight: diagColumn.implicitHeight + DesignTokens.spacingXl * 2

    // M7 exposes availability from the injected diagnostics exporter.
    property bool serviceAvailable: ctrl ? ctrl.diagnosticsAvailable : false

    ColumnLayout {
        id: diagColumn
        anchors.fill: parent
        anchors.margins: DesignTokens.spacingXl
        spacing: DesignTokens.spacingMd

        Text {
            text: i18n.tr("prefs.diag.title", i18n.locale)
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeLg
            font.bold: true
            color: DesignTokens.textPrimary
        }

        Text {
            text: i18n.tr("prefs.diag.description", i18n.locale)
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeMd
            color: DesignTokens.textSecondary
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
        }

        // Service unavailable notice
        Rectangle {
            visible: !root.serviceAvailable
            Layout.fillWidth: true
            Layout.preferredHeight: serviceNoticeText.implicitHeight + 16
            color: "#fefce8"
            radius: DesignTokens.radiusMd
            border.width: 1
            border.color: "#fde68a"
            Text {
                id: serviceNoticeText
                anchors.centerIn: parent
                text: i18n.tr("prefs.diag.notAvailable", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeSm
                color: DesignTokens.accentWarning
            }
        }

        // Export button — DISABLED until a real service exists.  Never
        // claims completion from a mere request.
        AppButton {
            objectName: "diagnosticsExportBtn"
            enabled: root.serviceAvailable
            text: i18n.tr("prefs.diag.export", i18n.locale)
            onClicked: {
                // A future real service reports success through its OWN
                // completion signal — requestDiagnosticsExport() only
                // triggers the export.
                if (root.ctrl) root.ctrl.requestDiagnosticsExport()
            }
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeSm
        }
    }
}

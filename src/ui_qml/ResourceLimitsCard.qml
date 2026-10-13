import QtQuick; import QtQuick.Controls.Basic; import QtQuick.Layouts

// Resource limits card — display value and user edits are wired directly to
// SettingsController draft via ctrl. No local shadow properties.
Rectangle {
    id: root
    property var ctrl: null
    objectName: "resourceLimitsCard"
    color: DesignTokens.bgPrimary
    radius: DesignTokens.radiusLg
    border.width: 1
    border.color: DesignTokens.borderLight
    implicitWidth: 400
    implicitHeight: limitsColumn.implicitHeight + DesignTokens.spacingXl * 2

    ColumnLayout {
        id: limitsColumn
        anchors.fill: parent
        anchors.margins: DesignTokens.spacingXl
        spacing: DesignTokens.spacingMd

        Text {
            text: i18n.tr("prefs.resource.title", i18n.locale)
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeLg
            font.bold: true
            color: DesignTokens.textPrimary
        }

        // --- Max Concurrent Requests ---
        RowLayout {
            Layout.fillWidth: true
            spacing: DesignTokens.spacingMd
            Text {
                text: i18n.tr("prefs.resource.concurrent", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
                Layout.fillWidth: true
            }
            SpinBox {
                objectName: "maxConcurrentSpin"
                Layout.preferredWidth: 140
                from: 1
                to: 20
                editable: true
                value: root.ctrl ? root.ctrl.maxConcurrentRequests : 4
                onValueChanged: {
                    if (root.ctrl) root.ctrl.maxConcurrentRequests = value
                }
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
            }
        }

        // --- Request Timeout ---
        RowLayout {
            Layout.fillWidth: true
            spacing: DesignTokens.spacingMd
            Text {
                text: i18n.tr("prefs.resource.timeout", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
                Layout.fillWidth: true
            }
            SpinBox {
                objectName: "timeoutSpin"
                Layout.preferredWidth: 140
                from: 5
                to: 300
                stepSize: 5
                editable: true
                value: root.ctrl ? root.ctrl.requestTimeoutSeconds : 30
                onValueChanged: {
                    if (root.ctrl) root.ctrl.requestTimeoutSeconds = value
                }
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
            }
        }

        // --- Max Retries ---
        RowLayout {
            Layout.fillWidth: true
            spacing: DesignTokens.spacingMd
            Text {
                text: i18n.tr("prefs.resource.maxRetries", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
                Layout.fillWidth: true
            }
            SpinBox {
                objectName: "maxRetriesSpin"
                Layout.preferredWidth: 140
                from: 0
                to: 10
                editable: true
                value: root.ctrl ? root.ctrl.maxRetries : 3
                onValueChanged: {
                    if (root.ctrl) root.ctrl.maxRetries = value
                }
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
            }
        }

        // --- Max PDF Scan Pages ---
        RowLayout {
            Layout.fillWidth: true
            spacing: DesignTokens.spacingMd
            Text {
                text: i18n.tr("prefs.resource.maxPdfPages", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
                Layout.fillWidth: true
            }
            SpinBox {
                objectName: "maxPdfPagesSpin"
                Layout.preferredWidth: 140
                from: 1
                to: 200
                editable: true
                value: root.ctrl ? root.ctrl.maxPdfPages : 50
                onValueChanged: {
                    if (root.ctrl) root.ctrl.maxPdfPages = value
                }
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
            }
        }

        // --- Max Video Keyframes ---
        RowLayout {
            Layout.fillWidth: true
            spacing: DesignTokens.spacingMd
            Text {
                text: i18n.tr("prefs.resource.maxVideoFrames", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
                Layout.fillWidth: true
            }
            SpinBox {
                objectName: "maxVideoKeyframesSpin"
                Layout.preferredWidth: 140
                from: 1
                to: 32
                editable: true
                value: root.ctrl ? root.ctrl.maxVideoKeyframes : 8
                onValueChanged: {
                    if (root.ctrl) root.ctrl.maxVideoKeyframes = value
                }
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
            }
        }
    }
}

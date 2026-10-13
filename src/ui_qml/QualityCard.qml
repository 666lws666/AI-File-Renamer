import QtQuick; import QtQuick.Controls.Basic; import QtQuick.Layouts

// Quality mode card — display value and user edits are wired directly to
// SettingsController draft via ctrl. No local shadow properties.
Rectangle {
    id: root
    property var ctrl: null
    objectName: "qualityCard"
    color: DesignTokens.bgPrimary
    radius: DesignTokens.radiusLg
    border.width: 1
    border.color: DesignTokens.borderLight
    implicitWidth: 400
    implicitHeight: qualityColumn.implicitHeight + DesignTokens.spacingXl * 2

    ColumnLayout {
        id: qualityColumn
        anchors.fill: parent
        anchors.margins: DesignTokens.spacingXl
        spacing: DesignTokens.spacingMd

        Text {
            text: i18n.tr("prefs.quality.title", i18n.locale)
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeLg
            font.bold: true
            color: DesignTokens.textPrimary
        }

        Text {
            text: i18n.tr("prefs.quality.description", i18n.locale)
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeSm
            color: DesignTokens.textSecondary
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
        }

        // Economy
        RowLayout {
            Layout.fillWidth: true
            spacing: DesignTokens.spacingMd
            RadioButton {
                objectName: "qualityEconomyRadio"
                checked: root.ctrl ? root.ctrl.qualityMode === "economy" : false
                onCheckedChanged: {
                    if (checked && root.ctrl) root.ctrl.qualityMode = "economy"
                }
            }
            ColumnLayout {
                spacing: DesignTokens.spacingXs
                Layout.fillWidth: true
                Text {
                    text: i18n.tr("prefs.quality.economy", i18n.locale)
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeMd
                    font.bold: true
                    color: DesignTokens.textPrimary
                }
                Text {
                    text: i18n.tr("prefs.quality.economy.desc", i18n.locale)
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeSm
                    color: DesignTokens.textSecondary
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                }
            }
        }

        // Balanced (Recommended)
        RowLayout {
            Layout.fillWidth: true
            spacing: DesignTokens.spacingMd
            RadioButton {
                objectName: "qualityBalancedRadio"
                checked: root.ctrl ? root.ctrl.qualityMode === "balanced" : false
                onCheckedChanged: {
                    if (checked && root.ctrl) root.ctrl.qualityMode = "balanced"
                }
            }
            ColumnLayout {
                spacing: DesignTokens.spacingXs
                Layout.fillWidth: true
                RowLayout {
                    spacing: DesignTokens.spacingSm
                    Text {
                        text: i18n.tr("prefs.quality.balanced", i18n.locale)
                        font.family: DesignTokens.fontFamily
                        font.pixelSize: DesignTokens.fontSizeMd
                        font.bold: true
                        color: DesignTokens.textPrimary
                    }
                    Rectangle {
                        width: recLabel.implicitWidth + 10
                        height: 20
                        radius: DesignTokens.radiusSm
                        color: "#eff6ff"
                        Text {
                            id: recLabel
                            anchors.centerIn: parent
                            text: i18n.tr("prefs.quality.recommended", i18n.locale)
                            font.family: DesignTokens.fontFamily
                            font.pixelSize: 10
                            color: DesignTokens.accentInfo
                        }
                    }
                }
                Text {
                    text: i18n.tr("prefs.quality.balanced.desc", i18n.locale)
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeSm
                    color: DesignTokens.textSecondary
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                }
            }
        }

        // High Quality
        RowLayout {
            Layout.fillWidth: true
            spacing: DesignTokens.spacingMd
            RadioButton {
                objectName: "qualityHighRadio"
                checked: root.ctrl ? root.ctrl.qualityMode === "high" : false
                onCheckedChanged: {
                    if (checked && root.ctrl) root.ctrl.qualityMode = "high"
                }
            }
            ColumnLayout {
                spacing: DesignTokens.spacingXs
                Layout.fillWidth: true
                Text {
                    text: i18n.tr("prefs.quality.high", i18n.locale)
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeMd
                    font.bold: true
                    color: DesignTokens.textPrimary
                }
                Text {
                    text: i18n.tr("prefs.quality.high.desc", i18n.locale)
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeSm
                    color: DesignTokens.textSecondary
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                }
            }
        }
    }
}

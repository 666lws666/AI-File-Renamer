import QtQuick; import QtQuick.Controls.Basic; import QtQuick.Layouts

// Privacy card — display value and user edits are wired directly to
// SettingsController draft via ctrl. No local shadow properties.
Rectangle {
    id: root
    property var ctrl: null
    objectName: "privacyCard"
    color: DesignTokens.bgPrimary
    radius: DesignTokens.radiusLg
    border.width: 1
    border.color: DesignTokens.borderLight
    implicitWidth: 420
    implicitHeight: privacyColumn.implicitHeight + DesignTokens.spacingXl * 2

    ColumnLayout {
        id: privacyColumn
        anchors.fill: parent
        anchors.margins: DesignTokens.spacingXl
        spacing: DesignTokens.spacingMd

        Text {
            text: i18n.tr("prefs.privacy.title", i18n.locale)
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeLg
            font.bold: true
            color: DesignTokens.textPrimary
        }

        Text {
            text: i18n.tr("prefs.privacy.description", i18n.locale)
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeSm
            color: DesignTokens.textSecondary
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
        }

        // --- Allow Text to Cloud ---
        RowLayout {
            Layout.fillWidth: true
            spacing: DesignTokens.spacingMd
            Text {
                text: i18n.tr("prefs.privacy.text", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
            }
            Switch {
                objectName: "allowTextCloudSwitch"
                checked: root.ctrl ? root.ctrl.allowTextCloud : false
                onCheckedChanged: {
                    if (root.ctrl) root.ctrl.allowTextCloud = checked
                }
                Layout.alignment: Qt.AlignVCenter
            }
        }

        // --- Allow Images/Scans to Vision ---
        RowLayout {
            Layout.fillWidth: true
            spacing: DesignTokens.spacingMd
            Text {
                text: i18n.tr("prefs.privacy.vision", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
            }
            Switch {
                objectName: "allowVisionCloudSwitch"
                checked: root.ctrl ? root.ctrl.allowVisionCloud : false
                onCheckedChanged: {
                    if (root.ctrl) root.ctrl.allowVisionCloud = checked
                }
                Layout.alignment: Qt.AlignVCenter
            }
        }

        // --- Allow Video Keyframes to Vision ---
        RowLayout {
            Layout.fillWidth: true
            spacing: DesignTokens.spacingMd
            Text {
                text: i18n.tr("prefs.privacy.video", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
            }
            Switch {
                objectName: "allowVideoCloudSwitch"
                checked: root.ctrl ? root.ctrl.allowVideoKeyframesCloud : false
                onCheckedChanged: {
                    if (root.ctrl) root.ctrl.allowVideoKeyframesCloud = checked
                }
                Layout.alignment: Qt.AlignVCenter
            }
        }

        // Video privacy notice — the container height follows the wrapped
        // text (implicitHeight + vertical padding), so the notice sits fully
        // inside the card in both locales instead of overflowing.
        Rectangle {
            objectName: "videoNoticeBox"
            Layout.fillWidth: true
            Layout.topMargin: DesignTokens.spacingSm
            Layout.preferredHeight: videoNoticeText.contentHeight + DesignTokens.spacingMd * 2
            color: "#eff6ff"
            radius: DesignTokens.radiusMd
            border.width: 1
            border.color: "#bfdbfe"
            Text {
                id: videoNoticeText
                objectName: "videoNoticeText"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.margins: DesignTokens.spacingMd
                text: i18n.tr("prefs.privacy.video.notice", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeSm
                color: DesignTokens.accentInfo
                wrapMode: Text.WordWrap
            }
        }
    }
}

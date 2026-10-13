import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ListView {
    id: root
    objectName: "vocabularyList"
    property var ctrl: null
    model: ctrl ? ctrl.vocabularyEntries : []
    clip: true
    spacing: DesignTokens.spacingXs

    delegate: Rectangle {
        required property var modelData
        required property int index
        width: root.width
        height: 48
        radius: DesignTokens.radiusSm
        color: index % 2 === 0 ? DesignTokens.bgSecondary : DesignTokens.bgPrimary

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: DesignTokens.spacingMd
            anchors.rightMargin: DesignTokens.spacingMd
            spacing: DesignTokens.spacingMd
            Text {
                Layout.preferredWidth: 160
                text: modelData.displayName
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                text: modelData.conceptId
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeSm
                color: DesignTokens.textSecondary
                elide: Text.ElideMiddle
            }
            Rectangle {
                implicitWidth: sourceLabel.implicitWidth + 14
                implicitHeight: 22
                radius: 11
                color: modelData.source === "system" ? "#eef2ff" : "#ecfdf5"
                Text {
                    id: sourceLabel
                    objectName: "vocabularySourceLabel"
                    anchors.centerIn: parent
                    text: i18n.tr("vocab.source." + (["ai_suggestion", "ai_auto"].indexOf(modelData.source) >= 0 ? "ai" : modelData.source), i18n.locale)
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeSm
                    color: DesignTokens.textSecondary
                }
            }
            AppButton {
                text: modelData.source === "system" ? i18n.tr("vocab.hide") : i18n.tr("vocab.delete")
                implicitHeight: 28
                onClicked: if (root.ctrl) root.ctrl.deleteVocabularyEntry(modelData.id)
            }
        }
    }

    Text {
        anchors.centerIn: parent
        visible: root.count === 0
        text: i18n.tr("vocab.empty")
        font.family: DesignTokens.fontFamily
        color: DesignTokens.textSecondary
    }
}

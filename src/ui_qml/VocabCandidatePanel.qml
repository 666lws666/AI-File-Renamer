import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "vocabularyCandidatePanel"
    property var ctrl: null
    property int candidateCount: ctrl ? ctrl.candidateCount : 0
    color: DesignTokens.bgSecondary
    border.width: 1
    border.color: DesignTokens.borderLight
    radius: DesignTokens.radiusLg

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: DesignTokens.spacingMd
        spacing: DesignTokens.spacingSm
        Text {
            text: i18n.tr("vocab.candidates") + " (" + root.candidateCount + ")"
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeMd
            font.bold: true
            color: DesignTokens.textPrimary
        }
        Text {
            Layout.fillWidth: true
            text: i18n.tr("vocab.candidates.help")
            wrapMode: Text.WordWrap
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeSm
            color: DesignTokens.textSecondary
        }
        ListView {
            objectName: "vocabularyCandidateList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: DesignTokens.spacingSm
            model: root.ctrl ? root.ctrl.candidateEntries : []
            delegate: Rectangle {
                required property var modelData
                width: ListView.view.width
                height: 112
                radius: DesignTokens.radiusMd
                color: DesignTokens.bgPrimary
                border.width: 1
                border.color: DesignTokens.borderLight
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: DesignTokens.spacingSm
                    Text { text: modelData.displayName; font.family: DesignTokens.fontFamily; font.bold: true; color: DesignTokens.textPrimary }
                    Text {
                        Layout.fillWidth: true
                        text: modelData.conceptId + " · " + Math.round(modelData.confidence * 100) + "%"
                        font.family: DesignTokens.fontFamily
                        font.pixelSize: DesignTokens.fontSizeSm
                        color: DesignTokens.textSecondary
                        elide: Text.ElideMiddle
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: DesignTokens.spacingXs
                        Button {
                            objectName: "candidateAcceptButton"
                            Layout.fillWidth: true; Layout.minimumWidth: 0
                            text: i18n.tr("vocab.accept"); implicitHeight: 28
                            font.pixelSize: DesignTokens.fontSizeSm
                            onClicked: if (root.ctrl) root.ctrl.acceptCandidate(modelData.id)
                        }
                        Button {
                            objectName: "candidateUseOnceButton"
                            Layout.fillWidth: true; Layout.minimumWidth: 0
                            text: i18n.tr("vocab.useOnce"); implicitHeight: 28
                            font.pixelSize: DesignTokens.fontSizeSm
                            onClicked: if (root.ctrl) root.ctrl.useCandidateOnce(modelData.id)
                        }
                        Button {
                            objectName: "candidateIgnoreButton"
                            Layout.fillWidth: true; Layout.minimumWidth: 0
                            text: i18n.tr("vocab.ignore"); implicitHeight: 28
                            font.pixelSize: DesignTokens.fontSizeSm
                            onClicked: if (root.ctrl) root.ctrl.ignoreCandidate(modelData.id)
                        }
                    }
                }
            }
        }
    }
}

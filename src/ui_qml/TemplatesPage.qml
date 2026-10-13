import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "templatesPage"
    property string pageId: "templates"
    property var ctrl: null
    property bool hasVocabularyMainNavigation: false
    property int controlledFieldCount: 5
    property bool vocabularyAvailable: ctrl ? ctrl.vocabularyCount > 0 : false
    property bool contentFits: width >= 760 && height >= 540
    color: DesignTokens.bgPrimary

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: DesignTokens.spacingXl
        spacing: DesignTokens.spacingMd

        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Layout.fillWidth: true
                spacing: DesignTokens.spacingXs
                Text {
                    objectName: "templatesPageTitle"
                    text: i18n.tr("templates.title")
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeXl
                    font.bold: true
                    color: DesignTokens.textPrimary
                }
                Text {
                    text: i18n.tr("templates.subtitle")
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeMd
                    color: DesignTokens.textSecondary
                }
            }
            AppButton {
                objectName: "addTemplateButton"
                primary: true
                visible: !root.ctrl || root.ctrl.activeTab === "templates"
                text: "+ " + i18n.tr("templates.add")
                onClicked: if (root.ctrl) root.ctrl.beginCreateTemplate()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: DesignTokens.spacingSm
            AppButton {
                objectName: "templatesTabButton"
                text: i18n.tr("templates.tab.templates")
                checkable: true
                checked: !root.ctrl || root.ctrl.activeTab === "templates"
                onClicked: if (root.ctrl) root.ctrl.setActiveTab("templates")
            }
            AppButton {
                objectName: "vocabularyTabButton"
                text: i18n.tr("templates.tab.vocabulary")
                checkable: true
                checked: root.ctrl && root.ctrl.activeTab === "vocabulary"
                onClicked: if (root.ctrl) root.ctrl.setActiveTab("vocabulary")
            }
            Item { Layout.fillWidth: true }
            Text {
                text: root.ctrl
                      ? ((root.ctrl.activeTab === "templates" ? root.ctrl.templateCount : root.ctrl.vocabularyCount) + " " + i18n.tr("common.items"))
                      : ""
                font.family: DesignTokens.fontFamily
                color: DesignTokens.textSecondary
            }
        }

        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: DesignTokens.borderLight }

        RowLayout {
            visible: !root.ctrl || root.ctrl.activeTab === "templates"
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: DesignTokens.spacingMd

            Rectangle {
                Layout.preferredWidth: root.ctrl && root.ctrl.editorOpen ? 320 : -1
                Layout.fillWidth: !(root.ctrl && root.ctrl.editorOpen)
                Layout.fillHeight: true
                radius: DesignTokens.radiusLg
                border.width: 1
                border.color: DesignTokens.borderLight
                color: DesignTokens.bgPrimary

                ListView {
                    id: templateList
                    objectName: "templateList"
                    anchors.fill: parent
                    anchors.margins: DesignTokens.spacingSm
                    clip: true
                    spacing: DesignTokens.spacingSm
                    model: root.ctrl ? root.ctrl.templates : []
                    ScrollBar.vertical: ScrollBar { objectName: "templateListScrollBar"; policy: ScrollBar.AsNeeded }
                    delegate: Rectangle {
                        required property var modelData
                        width: templateList.width
                        height: cardContent.implicitHeight + DesignTokens.spacingMd * 2
                        radius: DesignTokens.radiusMd
                        color: DesignTokens.bgSecondary
                        border.width: 1
                        border.color: DesignTokens.borderLight
                        RowLayout {
                            id: cardContent
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: DesignTokens.spacingMd
                            spacing: DesignTokens.spacingSm
                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                Layout.preferredWidth: 0
                                Text { Layout.fillWidth: true; text: modelData.name; font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeMd; font.bold: true; color: DesignTokens.textPrimary; elide: Text.ElideRight }
                                Text { objectName: "templateDescription"; Layout.fillWidth: true; text: modelData.description; font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm; color: DesignTokens.textSecondary; wrapMode: Text.Wrap }
                                Text { objectName: "templateExample"; Layout.fillWidth: true; text: i18n.tr("templates.example") + modelData.example; font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeMd; color: DesignTokens.textPrimary; wrapMode: Text.WrapAnywhere }
                                Text { Layout.fillWidth: true; text: modelData.formula; font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm; color: DesignTokens.textSecondary; elide: Text.ElideMiddle }
                                Text { text: i18n.tr("templates.version") + " " + modelData.version; font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm; color: DesignTokens.textSecondary }
                            }
                            AppButton { objectName: "editTemplateButton"; Layout.preferredWidth: 56; text: i18n.tr("templates.edit"); onClicked: if (root.ctrl) root.ctrl.beginEditTemplate(modelData.id) }
                            AppButton {
                                objectName: "deleteTemplateButton"
                                Layout.preferredWidth: 56
                                visible: root.ctrl && root.ctrl.templateCount > 1
                                text: i18n.tr("common.delete")
                                onClicked: if (root.ctrl) root.ctrl.deleteTemplate(modelData.id)
                            }
                        }
                    }
                }
            }

            TemplateEditor {
                visible: root.ctrl && root.ctrl.editorOpen
                Layout.fillWidth: true
                Layout.fillHeight: true
                ctrl: root.ctrl
            }
        }

        VocabTab {
            visible: root.ctrl && root.ctrl.activeTab === "vocabulary"
            Layout.fillWidth: true
            Layout.fillHeight: true
            ctrl: root.ctrl
        }
    }
}

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Item {
    id: root
    objectName: "vocabularyTab"
    property var ctrl: null
    property bool adding: false

    function categoryLabel(category) {
        switch (category) {
        case "subject": return i18n.tr("vocab.category.subject")
        case "organization": return i18n.tr("vocab.category.organization")
        case "project": return i18n.tr("vocab.category.project")
        case "status": return i18n.tr("vocab.category.status")
        case "type": return i18n.tr("vocab.category.type")
        default: return category
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: DesignTokens.spacingMd

        RowLayout {
            Layout.fillWidth: true
            TextField {
                objectName: "vocabularySearch"
                Layout.fillWidth: true
                placeholderText: i18n.tr("vocab.search")
                onTextEdited: if (root.ctrl) root.ctrl.setVocabularyQuery(text)
            }
            AppComboBox {
                objectName: "vocabularySourceFilter"
                Layout.preferredWidth: 150
                textRole: "label"
                valueRole: "value"
                model: [
                    {label: i18n.tr("vocab.source.all"), value: "all"},
                    {label: i18n.tr("vocab.source.system"), value: "system"},
                    {label: i18n.tr("vocab.source.user"), value: "user"},
                    {label: i18n.tr("vocab.source.ai"), value: "ai_suggestion"}
                ]
                onActivated: if (root.ctrl) root.ctrl.setVocabularySource(currentValue)
            }
            AppButton {
                objectName: "newVocabularyEntryButton"
                primary: true
                text: "+ " + i18n.tr("vocab.new")
                onClicked: root.adding = true
            }
            AppButton {
                text: i18n.tr("vocab.restoreCategory")
                onClicked: if (root.ctrl) root.ctrl.restoreVocabularyCategory()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: DesignTokens.spacingSm
            Repeater {
                model: ["subject", "organization", "project", "status", "type"]
                AppButton {
                    required property string modelData
                    text: root.categoryLabel(modelData)
                    checkable: true
                    checked: root.ctrl && root.ctrl.vocabularyCategory === modelData
                    onClicked: if (root.ctrl) root.ctrl.setVocabularyCategory(modelData)
                }
            }
            Item { Layout.fillWidth: true }
        }

        Rectangle {
            id: entryForm
            objectName: "vocabularyEntryForm"
            visible: root.adding
            Layout.fillWidth: true
            implicitHeight: formRow.implicitHeight + DesignTokens.spacingMd * 2
            radius: DesignTokens.radiusMd
            color: DesignTokens.bgSecondary
            border.width: 1
            border.color: DesignTokens.borderLight
            RowLayout {
                id: formRow
                anchors.fill: parent
                anchors.margins: DesignTokens.spacingMd
                TextField { id: entryName; objectName: "vocabularyNameField"; Layout.fillWidth: true; placeholderText: i18n.tr("vocab.name") }
                TextField { id: entryConcept; objectName: "vocabularyConceptField"; Layout.fillWidth: true; placeholderText: i18n.tr("vocab.conceptId") }
                AppButton {
                    objectName: "saveVocabularyEntryButton"
                    primary: true
                    text: i18n.tr("common.save")
                    enabled: entryName.text.trim().length > 0 && entryConcept.text.trim().length > 0
                    onClicked: {
                        if (root.ctrl && root.ctrl.addVocabularyEntry(entryName.text, entryConcept.text)) {
                            entryName.text = ""; entryConcept.text = ""; root.adding = false
                        }
                    }
                }
                AppButton { text: i18n.tr("common.cancel"); onClicked: root.adding = false }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: DesignTokens.spacingMd
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: DesignTokens.radiusLg
                border.width: 1
                border.color: DesignTokens.borderLight
                color: DesignTokens.bgPrimary
                VocabList { anchors.fill: parent; anchors.margins: 1; ctrl: root.ctrl }
            }
            VocabCandidatePanel {
                Layout.preferredWidth: 280
                Layout.fillHeight: true
                ctrl: root.ctrl
            }
        }
    }
}

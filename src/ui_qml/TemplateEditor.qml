import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "templateEditor"
    property var ctrl: null
    color: DesignTokens.bgPrimary
    border.width: 1
    border.color: DesignTokens.borderLight
    radius: DesignTokens.radiusLg
    clip: true

    Flickable {
        id: editorScroll
        objectName: "templateEditorScroll"
        anchors.fill: parent
        anchors.margins: DesignTokens.spacingLg
        contentWidth: width
        contentHeight: editorColumn.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        ScrollBar.vertical: ScrollBar { objectName: "templateEditorScrollBar" }

        ColumnLayout {
            id: editorColumn
            width: parent.width - DesignTokens.spacingSm
            spacing: DesignTokens.spacingMd

            RowLayout {
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    text: root.ctrl && root.ctrl.editorMode === "edit"
                          ? i18n.tr("templates.editor.edit") : i18n.tr("templates.editor.new")
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeLg
                    font.bold: true
                    color: DesignTokens.textPrimary
                }
                AppButton {
                    text: "×"
                    implicitWidth: 32
                    onClicked: if (root.ctrl) root.ctrl.cancelDraft()
                }
            }

            Text { text: i18n.tr("templates.editor.name"); font.family: DesignTokens.fontFamily; color: DesignTokens.textSecondary }
            TextField {
                id: nameField
                objectName: "templateNameField"
                Layout.fillWidth: true
                text: root.ctrl ? root.ctrl.draftName : ""
                placeholderText: i18n.tr("templates.editor.namePlaceholder")
                onTextEdited: if (root.ctrl) root.ctrl.setDraftName(text)
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: DesignTokens.spacingMd
                rowSpacing: DesignTokens.spacingSm

                Text { text: i18n.tr("templates.editor.dateFormat"); font.family: DesignTokens.fontFamily; color: DesignTokens.textSecondary }
                AppComboBox {
                    objectName: "templateDateFormat"
                    Layout.fillWidth: true
                    textRole: "label"
                    valueRole: "value"
                    model: [
                        {label: i18n.tr("templates.date.YYYYMMDD", i18n.locale), value: "YYYYMMDD"},
                        {label: i18n.tr("templates.date.YYYYMM", i18n.locale), value: "YYYYMM"},
                        {label: i18n.tr("templates.date.YYYY-MM-DD", i18n.locale), value: "YYYY-MM-DD"},
                        {label: i18n.tr("templates.date.YYYY-MM", i18n.locale), value: "YYYY-MM"}
                    ]
                    currentValue: root.ctrl ? root.ctrl.draftOptions.dateFormat : "YYYYMMDD"
                    onActivated: if (root.ctrl) root.ctrl.setDraftOption("dateFormat", currentValue)
                }
                Text { text: i18n.tr("templates.editor.separator"); font.family: DesignTokens.fontFamily; color: DesignTokens.textSecondary }
                AppComboBox {
                    objectName: "templateSeparator"
                    Layout.fillWidth: true
                    textRole: "label"
                    valueRole: "value"
                    model: [
                        {label: i18n.tr("templates.separator.underscore", i18n.locale), value: "_"},
                        {label: i18n.tr("templates.separator.hyphen", i18n.locale), value: "-"}
                    ]
                    currentValue: root.ctrl ? root.ctrl.draftOptions.separator : "_"
                    onActivated: if (root.ctrl) root.ctrl.setDraftOption("separator", currentValue)
                }
                Text { text: i18n.tr("templates.editor.organization"); font.family: DesignTokens.fontFamily; color: DesignTokens.textSecondary }
                AppComboBox {
                    objectName: "templateOrgMode"
                    Layout.fillWidth: true
                    textRole: "label"
                    valueRole: "value"
                    model: [
                        {label: i18n.tr("templates.org.flat"), value: "flat"},
                        {label: i18n.tr("templates.org.subject"), value: "subject_tree"},
                        {label: i18n.tr("templates.org.type"), value: "type_tree"},
                        {label: i18n.tr("templates.org.project"), value: "project_tree"}
                    ]
                    currentValue: root.ctrl ? root.ctrl.draftOptions.orgMode : "flat"
                    onActivated: if (root.ctrl) root.ctrl.setDraftOption("orgMode", currentValue)
                }
                Text { text: i18n.tr("templates.editor.outputLanguage"); font.family: DesignTokens.fontFamily; color: DesignTokens.textSecondary }
                AppComboBox {
                    objectName: "templateOutputLanguage"
                    Layout.fillWidth: true
                    textRole: "label"
                    valueRole: "value"
                    model: [
                        {label: i18n.tr("templates.language.zh", i18n.locale), value: "zh"},
                        {label: i18n.tr("templates.language.en", i18n.locale), value: "en"},
                        {label: i18n.tr("templates.language.ja", i18n.locale), value: "ja"},
                        {label: i18n.tr("templates.language.es", i18n.locale), value: "es"},
                        {label: i18n.tr("templates.language.zh-HK", i18n.locale), value: "zh-HK"}
                    ]
                    currentValue: root.ctrl ? root.ctrl.draftOptions.outputLanguage : "zh"
                    onActivated: if (root.ctrl) root.ctrl.setDraftOption("outputLanguage", currentValue)
                }
            }

            Text { text: i18n.tr("templates.editor.fields"); font.family: DesignTokens.fontFamily; font.bold: true; color: DesignTokens.textPrimary }
            Text {
                Layout.fillWidth: true
                text: i18n.tr("templates.editor.vocabularyHint")
                wrapMode: Text.WordWrap
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeSm
                color: DesignTokens.textSecondary
            }
            FieldSorter {
                ctrl: root.ctrl
                Layout.fillWidth: true
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: previewColumn.implicitHeight + DesignTokens.spacingMd * 2
                radius: DesignTokens.radiusMd
                color: "#f1f5f9"
                ColumnLayout {
                    id: previewColumn
                    anchors.fill: parent
                    anchors.margins: DesignTokens.spacingMd
                    Text { text: i18n.tr("templates.editor.preview"); font.family: DesignTokens.fontFamily; font.bold: true; color: DesignTokens.textSecondary }
                    Text {
                        objectName: "templatePreviewText"
                        Layout.fillWidth: true
                        text: root.ctrl ? root.ctrl.previewText : ""
                        font.family: DesignTokens.fontFamily
                        font.pixelSize: DesignTokens.fontSizeMd
                        color: DesignTokens.textPrimary
                        wrapMode: Text.WrapAnywhere
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                visible: root.ctrl && root.ctrl.errorMessage !== ""
                text: root.ctrl ? root.ctrl.errorMessage : ""
                color: DesignTokens.accentError
                font.family: DesignTokens.fontFamily
                wrapMode: Text.WordWrap
            }

            RowLayout {
                Layout.alignment: Qt.AlignRight
                AppButton { text: i18n.tr("common.cancel"); onClicked: if (root.ctrl) root.ctrl.cancelDraft() }
                AppButton {
                    objectName: "templateSaveButton"
                    primary: true
                    text: i18n.tr("common.save")
                    enabled: nameField.text.trim().length > 0
                    onClicked: {
                        if (root.ctrl) {
                            root.ctrl.setDraftName(nameField.text)
                            root.ctrl.saveDraft()
                        }
                    }
                }
            }
        }
    }
}

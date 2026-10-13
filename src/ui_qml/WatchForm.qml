import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs

Rectangle {
    id: root
    objectName: "watchForm"
    property var ctrl: null
    width: 432
    implicitHeight: formColumn.implicitHeight + DesignTokens.spacingLg * 2 + 2
    radius: DesignTokens.radiusLg
    color: DesignTokens.bgPrimary
    border.width: 1
    border.color: DesignTokens.borderLight

    FolderDialog {
        id: sourceDialog
        title: i18n.tr("watch.form.chooseSource")
        onAccepted: if (root.ctrl) root.ctrl.setDraftSource(selectedFolder.toString().replace(/^file:\/\//, ""))
    }
    FolderDialog {
        id: targetDialog
        title: i18n.tr("watch.form.chooseTarget")
        onAccepted: if (root.ctrl) root.ctrl.setDraftTarget(selectedFolder.toString().replace(/^file:\/\//, ""))
    }

    Flickable {
        id: formScroll
        objectName: "watchFormScroll"
        anchors.fill: parent
        anchors.margins: 1
        clip: true
        contentWidth: width
        contentHeight: formColumn.implicitHeight + DesignTokens.spacingLg * 2
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: formColumn
            x: DesignTokens.spacingLg
            y: DesignTokens.spacingLg
            width: formScroll.width - DesignTokens.spacingLg * 2
            spacing: DesignTokens.spacingMd

            Text {
                Layout.fillWidth: true
                text: root.ctrl && root.ctrl.formMode === "edit"
                      ? i18n.tr("watch.form.editTitle") : i18n.tr("watch.form.addTitle")
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeLg
                font.bold: true
                color: DesignTokens.textPrimary
            }

            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: DesignTokens.borderLight }

            Text { text: i18n.tr("watch.form.source"); font.family: DesignTokens.fontFamily; color: DesignTokens.textPrimary }
            RowLayout {
                Layout.fillWidth: true
                TextField {
                    id: sourceField
                    objectName: "watchSourceField"
                    Layout.fillWidth: true
                    text: root.ctrl ? root.ctrl.draftSource : ""
                    placeholderText: i18n.tr("watch.form.sourcePlaceholder")
                    onTextEdited: if (root.ctrl) root.ctrl.setDraftSource(text)
                }
                AppButton { objectName: "watchSourceBrowseButton"; text: i18n.tr("watch.form.browse", i18n.locale); onClicked: sourceDialog.open() }
            }

            Text { text: i18n.tr("watch.form.target"); font.family: DesignTokens.fontFamily; color: DesignTokens.textPrimary }
            RowLayout {
                Layout.fillWidth: true
                TextField {
                    objectName: "watchTargetField"
                    Layout.fillWidth: true
                    text: root.ctrl ? root.ctrl.draftTarget : ""
                    placeholderText: i18n.tr("watch.form.targetPlaceholder")
                    onTextEdited: if (root.ctrl) root.ctrl.setDraftTarget(text)
                }
                AppButton { objectName: "watchTargetBrowseButton"; text: i18n.tr("watch.form.browse", i18n.locale); onClicked: targetDialog.open() }
            }

            Text { text: i18n.tr("watch.form.template"); font.family: DesignTokens.fontFamily; color: DesignTokens.textPrimary }
            AppComboBox {
                id: templateCombo
                objectName: "watchTemplateCombo"
                Layout.fillWidth: true
                model: root.ctrl ? root.ctrl.templates : []
                textRole: "name"
                valueRole: "id"
                currentIndex: {
                    if (!root.ctrl) return -1
                    for (var i = 0; i < count; ++i) {
                        if (valueAt(i) === root.ctrl.draftTemplate) return i
                    }
                    return count > 0 ? 0 : -1
                }
                onActivated: if (root.ctrl && currentIndex >= 0) root.ctrl.setDraftTemplate(valueAt(currentIndex))
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: DesignTokens.spacingSm
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: Math.max(recursiveOptions.implicitHeight, autoOptions.implicitHeight) + DesignTokens.spacingSm * 2
                    radius: DesignTokens.radiusMd
                    color: DesignTokens.bgSecondary
                    border.width: 1
                    border.color: DesignTokens.borderLight
                    ColumnLayout {
                        id: recursiveOptions
                        anchors.fill: parent; anchors.margins: DesignTokens.spacingSm; spacing: 2
                        RowLayout {
                            Layout.fillWidth: true
                            Text { objectName: "watchRecursiveLabel"; Layout.fillWidth: true; Layout.minimumWidth: 0; wrapMode: Text.Wrap; font.pixelSize: DesignTokens.fontSizeMd; text: i18n.tr("watch.form.recursive", i18n.locale); font.family: DesignTokens.fontFamily; font.bold: true; color: DesignTokens.textPrimary }
                            Switch { objectName: "watchRecursiveSwitch"; checked: root.ctrl ? root.ctrl.draftRecursive : true; onToggled: if (root.ctrl) root.ctrl.setDraftRecursive(checked) }
                        }
                        Text { Layout.fillWidth: true; text: i18n.tr("watch.form.recursiveHint"); wrapMode: Text.WordWrap; font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm; color: DesignTokens.textSecondary }
                    }
                }
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: Math.max(recursiveOptions.implicitHeight, autoOptions.implicitHeight) + DesignTokens.spacingSm * 2
                    radius: DesignTokens.radiusMd
                    color: DesignTokens.bgSecondary
                    border.width: 1
                    border.color: DesignTokens.borderLight
                    ColumnLayout {
                        id: autoOptions
                        anchors.fill: parent; anchors.margins: DesignTokens.spacingSm; spacing: 2
                        RowLayout {
                            Layout.fillWidth: true
                            Text { Layout.fillWidth: true; Layout.minimumWidth: 0; wrapMode: Text.Wrap; font.pixelSize: DesignTokens.fontSizeMd; text: i18n.tr("watch.form.autoApply", i18n.locale); font.family: DesignTokens.fontFamily; font.bold: true; color: DesignTokens.textPrimary }
                            Switch { objectName: "watchAutoApplySwitch"; checked: Boolean(root.ctrl && root.ctrl.draftMode === "auto_apply"); onToggled: if (root.ctrl) root.ctrl.setDraftMode(checked ? "auto_apply" : "review_first") }
                        }
                        Text {
                            objectName: "watchModeHint"
                            Layout.fillWidth: true
                            text: root.ctrl && root.ctrl.draftMode === "auto_apply"
                                  ? i18n.tr("watch.form.autoModeHint", i18n.locale)
                                  : i18n.tr("watch.form.reviewModeHint", i18n.locale)
                            wrapMode: Text.WordWrap
                            font.family: DesignTokens.fontFamily
                            font.pixelSize: DesignTokens.fontSizeSm
                            color: DesignTokens.textSecondary
                        }
                    }
                }
            }

            Text {
                visible: Boolean(root.ctrl && root.ctrl.errorMessage !== "")
                Layout.fillWidth: true
                text: root.ctrl ? root.ctrl.errorMessage : ""
                wrapMode: Text.WordWrap
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeSm
                color: DesignTokens.accentError
            }

            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                AppButton { objectName: "watchFormCancelButton"; text: i18n.tr("common.cancel"); onClicked: if (root.ctrl) root.ctrl.cancelForm() }
                AppButton {
                    objectName: "watchFormSaveButton"
                    primary: true
                    text: root.ctrl && root.ctrl.formMode === "edit" ? i18n.tr("common.save") : i18n.tr("watch.form.addAction")
                    enabled: Boolean(root.ctrl && root.ctrl.draftSource.length > 0)
                    onClicked: if (root.ctrl) root.ctrl.saveDraft()
                }
            }
        }
    }
}

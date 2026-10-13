import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    height: root.isEditing ? DesignTokens.taskCardHeight + 52 : DesignTokens.taskCardHeight
    color: root.hovered ? DesignTokens.bgSecondary : DesignTokens.bgPrimary
    radius: DesignTokens.radiusMd
    border.width: 1
    border.color: root.selected ? DesignTokens.accentInfo : (root.hovered ? DesignTokens.borderLight : "transparent")

    property string taskId: ""
    property string originalName: ""
    property string suggestedName: ""
    property string extension: ""
    property string status: "pending"
    property string statusLabel: ""
    property bool selected: false
    property string errorMessage: ""
    property bool canApply: false
    property bool canRetry: false
    property bool canIgnore: false
    property bool canCancel: false
    property bool canUndo: false
    property bool isEditing: false
    property string validationError: ""
    property bool hovered: false
    property bool fileOperationPending: false
    property bool fileOperationRecoveryRequired: false
    readonly property bool fileOperationLocked: fileOperationPending || fileOperationRecoveryRequired
    property var ctrl: null

    function translatedError() {
        return (root.errorMessage.indexOf("fileops.error.") === 0 || root.errorMessage.indexOf("batch.error.") === 0 || root.errorMessage.indexOf("smart.error.") === 0 || root.errorMessage.indexOf("capability.") === 0)
            ? i18n.tr(root.errorMessage, i18n.locale) : root.errorMessage
    }

    function translatedStatus() {
        if (root.fileOperationPending) return i18n.tr('fileops.status.running', i18n.locale)
        const keys = {
            "pending": "batch.state.pending", "analyzing": "batch.state.analyzing",
            "review_pending": "batch.state.review", "undone": "batch.state.undone",
            "applied": "batch.state.applied", "failed": "batch.state.failed",
            "cancelled": "batch.state.cancelled", "ignored": "batch.state.ignored"
        }
        return i18n.tr(keys[root.status] || "batch.state.pending", i18n.locale)
    }

    HoverHandler { id: hoverHandler; onHoveredChanged: root.hovered = hoverHandler.hovered }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 10
        CheckBox {
            objectName: "taskCheckBox"
            checked: root.selected
            Layout.alignment: Qt.AlignVCenter
            onClicked: if (root.ctrl) root.ctrl.toggleTaskSelected(root.taskId)
        }
        Rectangle {
            Layout.preferredWidth: 32
            Layout.preferredHeight: 32
            radius: 4
            color: DesignTokens.bgSecondary
            Text { anchors.centerIn: parent; text: root.translatedStatus()[0] || "?"; font.pixelSize: 14; color: DesignTokens.textPrimary }
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            InlineEdit {
                id: inlineEdit
                enabled: !root.fileOperationLocked
                objectName: "taskInlineEdit"
                visible: root.isEditing
                Layout.fillWidth: true
                Layout.preferredHeight: 58
                taskId: root.taskId
                extension: root.extension
                validationError: root.validationError
                function loadCurrentName() {
                    let stem = root.suggestedName || ""
                    if (root.extension && stem.endsWith(root.extension))
                        stem = stem.slice(0, -root.extension.length)
                    begin(stem, root.extension)
                }
                onVisibleChanged: if (visible) loadCurrentName()
                Component.onCompleted: if (root.isEditing) loadCurrentName()
                onConfirmed: function(newName) { if (root.ctrl) root.ctrl.confirmInlineEdit(root.taskId, newName) }
                onCancelled: function() { if (root.ctrl) root.ctrl.cancelInlineEdit(root.taskId) }
            }
            Text {
                visible: !root.isEditing
                text: root.fileOperationPending ? root.translatedStatus() : (root.suggestedName || root.translatedStatus())
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                font.bold: root.suggestedName !== ""
                color: DesignTokens.textPrimary
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
            Text {
                visible: !root.isEditing
                text: root.originalName
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeSm
                color: DesignTokens.textSecondary
                elide: Text.ElideMiddle
                Layout.fillWidth: true
            }
            Text {
                objectName: "taskErrorMessage"
                visible: !root.isEditing && root.errorMessage !== ""
                text: root.translatedError()
                font.pixelSize: 10
                color: DesignTokens.accentError
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
        }
        RowLayout {
            enabled: !root.fileOperationLocked
            visible: (root.hovered || root.selected) && root.ctrl && !root.isEditing
            spacing: 4
            Layout.alignment: Qt.AlignVCenter
            Rectangle {
                objectName: "inlineEditButton"
                visible: root.suggestedName !== ""
                Layout.preferredWidth: 26; Layout.preferredHeight: 24; radius: 4; color: DesignTokens.bgNavSelected
                Text { anchors.centerIn: parent; text: "✎"; font.pixelSize: 12; color: DesignTokens.textSecondary }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: if (root.ctrl) root.ctrl.beginInlineEdit(root.taskId) }
            }
            Rectangle {
                objectName: "taskApplyButton"
                visible: root.canApply
                Layout.preferredWidth: 42; Layout.preferredHeight: 24; radius: 4; color: DesignTokens.btnPrimary
                Text { anchors.centerIn: parent; text: i18n.tr("batch.actions.apply", i18n.locale); font.pixelSize: 10; color: DesignTokens.btnPrimaryText }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: if (root.ctrl) root.ctrl.applyTask(root.taskId) }
            }
            Rectangle {
                objectName: "taskRetryButton"
                visible: root.canRetry
                Layout.preferredWidth: 42; Layout.preferredHeight: 24; radius: 4; color: DesignTokens.borderLight
                Text { anchors.centerIn: parent; text: i18n.tr("batch.actions.retry", i18n.locale); font.pixelSize: 10; color: DesignTokens.textPrimary }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: if (root.ctrl) root.ctrl.retryTask(root.taskId) }
            }
            Rectangle {
                objectName: "taskCancelButton"
                visible: root.canCancel
                Layout.preferredWidth: 42; Layout.preferredHeight: 24; radius: 4; color: DesignTokens.borderLight
                Text { anchors.centerIn: parent; text: i18n.tr("batch.actions.cancel", i18n.locale); font.pixelSize: 10; color: DesignTokens.textPrimary }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: if (root.ctrl) root.ctrl.cancelTask(root.taskId) }
            }
            Rectangle {
                objectName: "taskUndoButton"
                visible: root.canUndo
                Layout.preferredWidth: 42; Layout.preferredHeight: 24; radius: 4; color: DesignTokens.borderLight
                Text { anchors.centerIn: parent; text: i18n.tr("batch.actions.undo", i18n.locale); font.pixelSize: 10; color: DesignTokens.textPrimary }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: if (root.ctrl) root.ctrl.undoTask(root.taskId) }
            }
            Rectangle {
                objectName: "taskIgnoreButton"
                visible: root.canIgnore
                Layout.preferredWidth: 42; Layout.preferredHeight: 24; radius: 4; color: DesignTokens.borderLight
                Text { anchors.centerIn: parent; text: i18n.tr("batch.actions.ignore", i18n.locale); font.pixelSize: 10; color: DesignTokens.textPrimary }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: if (root.ctrl) root.ctrl.ignoreTask(root.taskId) }
            }
        }
    }
}

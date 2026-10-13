import QtQuick; import QtQuick.Controls.Basic

ListView {
    id: root; objectName: "batchTaskQueue"; clip: true; spacing: 4
    property var ctrl: null
    property int visibleCount: ctrl ? ctrl.visibleCount : 0
    property int totalCount: ctrl ? ctrl.totalCount : 0

    model: ctrl ? ctrl.tasksModel : null
    delegate: Item {
        id: delegateRoot
        width: ListView.view.width
        // Depend explicitly on both filter properties: their shared notify signal
        // causes every delegate to re-evaluate after either a search or a status
        // filter changes, even where the result count happens to stay the same.
        property string filterKey: root.ctrl ? root.ctrl.statusFilter + "|" + root.ctrl.searchText : ""
        property bool taskVisible: {
            const refresh = filterKey
            return !root.ctrl || root.ctrl.isTaskVisible(model.taskId)
        }
        height: taskVisible ? card.height : 0
        visible: taskVisible

        TaskCard {
            id: card
            width: parent.width
            taskId: model.taskId; originalName: model.originalName; suggestedName: model.suggestedName
            extension: model.extension; status: model.status; statusLabel: model.statusLabel
            selected: model.selected; errorMessage: model.errorMessage
            canApply: model.canApply; canRetry: model.canRetry; canIgnore: model.canIgnore
            canCancel: model.canCancel; canUndo: model.canUndo
            fileOperationPending: model.fileOperationPending === true
            fileOperationRecoveryRequired: model.fileOperationRecoveryRequired === true
            isEditing: model.isEditing; validationError: model.validationError
            ctrl: root.ctrl
        }
    }

    Rectangle {
        anchors.centerIn: parent; visible: root.visibleCount === 0 && root.totalCount > 0
        color: "transparent"
        Text { anchors.centerIn: parent; text: i18n.tr("batch.noMatching", i18n.locale); font.pixelSize: 14; color: DesignTokens.textSecondary }
    }
}

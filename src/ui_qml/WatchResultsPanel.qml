import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "watchResultsPanel"
    property var ctrl: null

    function stateText(state) {
        if (state === "pending") return i18n.tr("watch.resultState.pending")
        if (state === "analyzing") return i18n.tr("watch.resultState.analyzing")
        if (state === "awaiting_approval") return i18n.tr("watch.resultState.awaitingApproval")
        if (state === "applying") return i18n.tr("watch.resultState.applying")
        if (state === "applied") return i18n.tr("watch.resultState.applied")
        if (state === "undone") return i18n.tr("watch.resultState.undone")
        if (state === "ignored") return i18n.tr("watch.resultState.ignored")
        if (state === "failed") return i18n.tr("watch.resultState.failed")
        if (state === "cancelled") return i18n.tr("watch.resultState.cancelled")
        return state
    }

    function coverageText(row) {
        let coverage = row.coverage
        if (!row.contentKind || !coverage || coverage.sectionsProcessed === undefined) return ""
        let text = i18n.tr("watch.results.coverage") + ": " + row.contentKind
        text += " · " + coverage.sectionsProcessed + "/" + (coverage.sectionsTotal === null ? "?" : coverage.sectionsTotal)
        if (coverage.pdfTotalPages !== null)
            text += " · " + i18n.tr("watch.results.pages") + ": " + coverage.textPageIndices.concat(coverage.renderedPageIndices).map(function(i) { return i + 1 }).join(", ") + "/" + coverage.pdfTotalPages
        if (coverage.videoTimestampsSeconds.length > 0)
            text += " · " + i18n.tr("watch.results.keyframes") + ": " + coverage.videoTimestampsSeconds.join(", ") + "s"
        return text
    }

    radius: DesignTokens.radiusLg
    color: DesignTokens.bgPrimary
    border.width: 1
    border.color: DesignTokens.borderLight

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: DesignTokens.spacingLg
        spacing: DesignTokens.spacingMd

        Item {
            Layout.fillWidth: true
            implicitWidth: root.width - DesignTokens.spacingLg * 2
            implicitHeight: 40
            ColumnLayout {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.right: closeButton.left
                anchors.rightMargin: DesignTokens.spacingSm
                spacing: 2
                Text { text: i18n.tr("watch.results.title"); font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeLg; font.bold: true; color: DesignTokens.textPrimary }
                Text { text: root.ctrl ? root.ctrl.selectedWatchId : ""; font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm; color: DesignTokens.textSecondary }
            }
            Button {
                id: closeButton
                objectName: "watchResultsCloseButton"
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                text: i18n.tr("common.close")
                onClicked: if (root.ctrl) root.ctrl.closeResults()
            }
        }

        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: DesignTokens.borderLight }

        Text {
            objectName: "watchResultNotice"
            Layout.fillWidth: true
            visible: Boolean(root.ctrl && (!root.ctrl.available || root.ctrl.resultNotice))
            text: root.ctrl ? i18n.tr("watch.notice." + (root.ctrl.available ? root.ctrl.resultNotice : "queue_unavailable")) : ""
            wrapMode: Text.WordWrap
            font.family: DesignTokens.fontFamily
            color: DesignTokens.accentError
        }
        Text {
            Layout.fillWidth: true
            visible: Boolean(root.ctrl && root.ctrl.errorMessage)
            text: root.ctrl ? i18n.tr(root.ctrl.errorMessage) : ""
            wrapMode: Text.WordWrap
            color: DesignTokens.accentError
        }

        Text {
            visible: !root.ctrl || root.ctrl.results.length === 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            text: i18n.tr("watch.results.empty")
            font.family: DesignTokens.fontFamily
            color: DesignTokens.textSecondary
        }

        ListView {
            id: resultsList
            objectName: "watchResultsList"
            visible: Boolean(root.ctrl && root.ctrl.results.length > 0)
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: DesignTokens.spacingSm
            model: root.ctrl ? root.ctrl.results : []
            delegate: Rectangle {
                required property var modelData
                width: resultsList.width
                height: Math.max(78, details.implicitHeight + DesignTokens.spacingSm * 2)
                radius: DesignTokens.radiusMd
                color: DesignTokens.bgSecondary
                border.width: 1
                border.color: DesignTokens.borderLight
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: DesignTokens.spacingSm
                    spacing: DesignTokens.spacingSm
                    ColumnLayout {
                        id: details
                        Layout.fillWidth: true
                        Text { Layout.fillWidth: true; text: modelData.suggestedName || modelData.displayName; elide: Text.ElideRight; font.family: DesignTokens.fontFamily; font.bold: true; color: DesignTokens.textPrimary }
                        Text { Layout.fillWidth: true; text: modelData.displayName; elide: Text.ElideMiddle; font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm; color: DesignTokens.textSecondary }
                        Text { objectName: "watchResultStateText"; text: root.stateText(modelData.state); font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm; color: modelData.state === "failed" ? DesignTokens.accentError : DesignTokens.textSecondary }
                        Text { objectName: "watchResultRecoveryText"; visible: modelData.recoveryRequired; text: i18n.tr("watch.notice.recovery_required"); Layout.fillWidth: true; wrapMode: Text.WordWrap; color: DesignTokens.accentError; font.pixelSize: DesignTokens.fontSizeSm }
                        Text { objectName: "watchResultCoverageText"; visible: text.length > 0; text: root.coverageText(modelData); Layout.fillWidth: true; wrapMode: Text.WordWrap; color: DesignTokens.textSecondary; font.pixelSize: DesignTokens.fontSizeSm }
                        Text { visible: Boolean(modelData.requestedQuality); text: i18n.tr("watch.results.quality") + ": " + modelData.requestedQuality + " → " + modelData.effectiveQuality; color: DesignTokens.textSecondary; font.pixelSize: DesignTokens.fontSizeSm }
                        Text { visible: Boolean(modelData.autoApplyReviewReason); text: i18n.tr("watch.reviewReason." + modelData.autoApplyReviewReason); Layout.fillWidth: true; wrapMode: Text.WordWrap; color: DesignTokens.accentError; font.pixelSize: DesignTokens.fontSizeSm }
                        Text { visible: modelData.warningCodes.length > 0; text: i18n.tr("watch.results.warnings") + ": " + modelData.warningCodes.join(", "); Layout.fillWidth: true; wrapMode: Text.WordWrap; color: DesignTokens.textSecondary; font.pixelSize: DesignTokens.fontSizeSm }
                    }
                    Button { objectName: "watchResultApproveButton"; visible: modelData.canApprove; enabled: Boolean(root.ctrl && root.ctrl.available); text: i18n.tr("watch.results.approve"); onClicked: if (root.ctrl) root.ctrl.approveResult(modelData.id) }
                    Button { objectName: "watchResultRetryButton"; visible: modelData.canRetry; enabled: Boolean(root.ctrl && root.ctrl.available); text: i18n.tr("watch.results.retry"); onClicked: if (root.ctrl) root.ctrl.retryResult(modelData.id) }
                    Button { objectName: "watchResultUndoButton"; visible: modelData.canUndo; enabled: Boolean(root.ctrl && root.ctrl.available); text: i18n.tr("watch.results.undo"); onClicked: if (root.ctrl) root.ctrl.undoResult(modelData.id) }
                    Button { visible: modelData.canApprove && modelData.state !== "undone"; enabled: Boolean(root.ctrl && root.ctrl.available); text: i18n.tr("watch.results.ignore"); onClicked: if (root.ctrl) root.ctrl.ignoreResult(modelData.id) }
                }
            }
        }
    }
}

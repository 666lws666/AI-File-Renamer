import QtQuick; import QtQuick.Controls.Basic; import QtQuick.Layouts

Item {
    id: root
    objectName: "preferencesPage"

    property var ctrl: null
    property var templateController: null
    property var processingCoordinator: null
    property var resourcesController: null
    property var router: null  // PageRouter — used for the unsaved guard
    property bool dirty: ctrl ? ctrl.dirty : false
    property bool saving: ctrl ? ctrl.saving : false

    // Save/cancel handlers
    function doSave() {
        if (ctrl && !generalCard.inputError) ctrl.saveAll()
    }
    function doCancel() {
        if (ctrl) ctrl.cancel()
    }
    function requestCancel() {
        if (root.dirty) {
            // F.7: Cancel must not silently discard a dirty draft — reuse the
            // explicit discard-confirmation semantics.
            if (root.router) root.router.openUnsavedForCancel()
        } else {
            root.doCancel()
            if (root.router) root.router.leavePreferences()
        }
    }

    // Test hook: shorten the success-feedback auto-dismiss window.
    function setSuccessFeedbackInterval(ms) {
        saveSuccessTimer.interval = ms
    }

    Component.onCompleted: {
        if (ctrl) ctrl.openSession()
    }
    Component.onDestruction: {
        // Don't trigger dirty check on destruction — just close
    }

    Connections {
        target: ctrl
        function onSaveSucceeded() {
            // M6 correction: visible "settings saved" feedback (timed).
            saveErrorText.text = ""
            saveSuccessText.text = i18n.tr("prefs.save.success", i18n.locale)
            saveSuccessTimer.restart()
        }
        function onSaveFailed(msg) {
            // Failure always shows the error; success feedback must not mask it.
            saveErrorText.text = msg
            saveSuccessText.text = ""
            saveSuccessTimer.stop()
        }
        function onDirtyChanged() {
            root.dirty = ctrl ? ctrl.dirty : false
            // A new edit after a successful save clears the success feedback.
            if (root.dirty) {
                saveSuccessText.text = ""
                saveSuccessTimer.stop()
            }
        }
        function onSavingChanged() { root.saving = ctrl ? ctrl.saving : false }
        function onDiagnosticsExportRequested() {
            diagnosticsDialog.resultMessage = ""
            diagnosticsDialog.visible = true
        }
        function onDiagnosticsExportFinished(success, _detail) {
            diagnosticsDialog.resultMessage = i18n.tr(
                success ? "diagnostics.success" : "diagnostics.failure", i18n.locale)
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Scrollable content
        ScrollView {
            id: scroll
            objectName: "preferencesScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            ScrollBar.vertical.policy: ScrollBar.AsNeeded

            contentWidth: availableWidth

            ColumnLayout {
                width: scroll.width
                spacing: DesignTokens.spacingLg

                // Page title
                Text {
                    objectName: "preferencesTitle"
                    text: i18n.tr("prefs.title", i18n.locale)
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeXl
                    font.bold: true
                    color: DesignTokens.textPrimary
                    Layout.leftMargin: DesignTokens.spacingXl
                    Layout.topMargin: DesignTokens.spacingXl
                }

                GeneralSettingsCard {
                    id: generalCard
                    templateController: root.templateController
                    Layout.fillWidth: true
                    Layout.leftMargin: DesignTokens.spacingXl
                    Layout.rightMargin: DesignTokens.spacingXl
                    ctrl: root.ctrl
                }

                LocalResourcesCard {
                    Layout.fillWidth: true
                    Layout.leftMargin: DesignTokens.spacingXl
                    Layout.rightMargin: DesignTokens.spacingXl
                    ctrl: root.resourcesController
                    processingCoordinator: root.processingCoordinator
                }

                ProviderSettingsCard {
                    Layout.fillWidth: true
                    Layout.leftMargin: DesignTokens.spacingXl
                    Layout.rightMargin: DesignTokens.spacingXl
                    ctrl: root.ctrl
                }

                QualityCard {
                    Layout.fillWidth: true
                    Layout.leftMargin: DesignTokens.spacingXl
                    Layout.rightMargin: DesignTokens.spacingXl
                    ctrl: root.ctrl
                }

                ResourceLimitsCard {
                    Layout.fillWidth: true
                    Layout.leftMargin: DesignTokens.spacingXl
                    Layout.rightMargin: DesignTokens.spacingXl
                    ctrl: root.ctrl
                }

                PrivacyCard {
                    Layout.fillWidth: true
                    Layout.leftMargin: DesignTokens.spacingXl
                    Layout.rightMargin: DesignTokens.spacingXl
                    ctrl: root.ctrl
                }

                CacheCard {
                    Layout.fillWidth: true
                    Layout.leftMargin: DesignTokens.spacingXl
                    Layout.rightMargin: DesignTokens.spacingXl
                    ctrl: root.ctrl
                }

                UsageCard {
                    Layout.fillWidth: true
                    Layout.leftMargin: DesignTokens.spacingXl
                    Layout.rightMargin: DesignTokens.spacingXl
                    ctrl: root.ctrl
                    // Minimal binding: no service injected or unreadable
                    // storage → unavailable; empty store → empty state.
                    usageAvailable: root.ctrl ? root.ctrl.usageAvailable : false
                    usageData: root.ctrl ? root.ctrl.usageData : []
                }

                DiagnosticsCard {
                    Layout.fillWidth: true
                    Layout.leftMargin: DesignTokens.spacingXl
                    Layout.rightMargin: DesignTokens.spacingXl
                    ctrl: root.ctrl
                }

                Item { Layout.preferredHeight: DesignTokens.spacingXl }
            }
        }

        // Fixed bottom action bar
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 56
            color: DesignTokens.bgSecondary
            border.color: DesignTokens.borderLight

            RowLayout {
                anchors.right: parent.right
                anchors.rightMargin: DesignTokens.spacingXl
                anchors.verticalCenter: parent.verticalCenter
                spacing: DesignTokens.spacingMd

                // M6 correction: success feedback (timed inline status)
                Text {
                    id: saveSuccessText
                    objectName: "saveSuccessText"
                    visible: text !== ""
                    color: DesignTokens.accentSuccess
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeSm
                }
                Timer {
                    id: saveSuccessTimer
                    objectName: "saveSuccessTimer"
                    interval: 3000
                    running: false
                    repeat: false
                    onTriggered: saveSuccessText.text = ""
                }

                Text {
                    id: saveErrorText
                    objectName: "saveErrorText"
                    visible: text !== ""
                    color: DesignTokens.accentError
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeSm
                }

                AppButton {
                    id: cancelBtn
                    objectName: "cancelBtn"
                    text: i18n.tr("common.cancel", i18n.locale)
                    onClicked: root.requestCancel()
                }

                AppButton {
                    id: saveBtn
                    objectName: "saveBtn"
                    primary: true
                    text: i18n.tr("common.save", i18n.locale)
                    enabled: root.dirty && !root.saving && !generalCard.inputError
                    onClicked: root.doSave()
                }
            }
        }
    }

    DiagnosticsDialog {
        id: diagnosticsDialog
        objectName: "preferencesDiagnosticsDialog"
        anchors.fill: parent
        z: 200
        visible: false
        onExportRequested: function(destination) {
            if (root.ctrl) root.ctrl.exportDiagnostics(destination)
        }
    }
}

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "batchToolbar"
    implicitHeight: 144
    height: implicitHeight
    color: DesignTokens.bgPrimary
    property var ctrl: null
    readonly property string activeLocale: i18n.locale
    readonly property bool englishLocale: activeLocale.startsWith("en")
    // Retained as a compatibility observation, never hide critical labels.
    readonly property bool compactActions: false
    readonly property string targetPath: root.ctrl ? root.ctrl.targetDirectory : ""
    readonly property string namingMode: root.ctrl && typeof root.ctrl.namingMode === "string"
        ? root.ctrl.namingMode : "template"
    readonly property bool targetDetailsVisible: targetDetails.visible
    function tr(key) { return i18n.tr(key, activeLocale) }
    signal addFilesRequested()
    signal addFolderRequested()
    signal targetDirectoryRequested()

    component Caption: Text {
        font.family: DesignTokens.fontFamily
        font.pixelSize: 12
        color: DesignTokens.textSecondary
        textFormat: Text.PlainText
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 8
        RowLayout {
            objectName: "batchConfigurationRow"
            Layout.fillWidth: true
            spacing: 8
            ColumnLayout {
                spacing: 4
                Layout.preferredWidth: root.englishLocale ? 152 : 132
                Layout.minimumWidth: root.englishLocale ? 152 : 132
                Layout.maximumWidth: root.englishLocale ? 152 : 132
                Caption { objectName: "batchNamingModeLabel"; text: root.tr("batch.toolbar.namingMode") }
                AppComboBox {
                    id: namingModeSelector
                    objectName: "batchNamingModeSelector"
                    property bool popupVisible: popup.visible
                    readonly property var modes: ["template", "smart"]
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.preferredHeight: 32
                    font.pixelSize: 12
                    Accessible.name: root.tr("batch.toolbar.namingMode")
                    model: [
                        {label: root.tr("batch.namingMode.template"), value: "template"},
                        {label: root.tr("batch.namingMode.smart"), value: "smart"}
                    ]
                    textRole: "label"
                    valueRole: "value"
                    function syncMode() {
                        currentIndex = Math.max(0, modes.indexOf(root.namingMode))
                    }
                    onActivated: if (root.ctrl) root.ctrl.setNamingMode(currentValue)
                    onModelChanged: Qt.callLater(syncMode)
                    Component.onCompleted: syncMode()
                    Connections {
                        target: root.ctrl
                        ignoreUnknownSignals: true
                        function onNamingModeChanged() { namingModeSelector.syncMode() }
                    }
                }
            }
            ColumnLayout {
                spacing: 4
                Layout.preferredWidth: 192
                Layout.minimumWidth: 192
                Layout.maximumWidth: 192
                Caption {
                    objectName: "batchTemplateLabel"
                    text: root.tr(root.namingMode === "template" ? "batch.toolbar.template" : "batch.toolbar.namingRule")
                }
                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 32
                    AppComboBox {
                        id: templateSelector
                        objectName: "batchTemplateSelector"
                        property bool popupVisible: popup.visible
                        anchors.fill: parent
                        visible: root.namingMode === "template"
                        enabled: visible
                        font.pixelSize: 12
                        Accessible.name: root.tr("batch.toolbar.template")
                        model: root.ctrl ? root.ctrl.templateOptions : []
                        textRole: "name"
                        valueRole: "id"
                        function syncSelection() {
                            if (!root.ctrl) return
                            for (let index = 0; index < count; ++index) {
                                if (valueAt(index) === root.ctrl.selectedTemplateId) {
                                    currentIndex = index
                                    return
                                }
                            }
                        }
                        onActivated: if (root.ctrl) root.ctrl.setSelectedTemplate(currentValue)
                        Component.onCompleted: syncSelection()
                        Connections {
                            target: root.ctrl
                            function onTemplateChanged() { templateSelector.syncSelection() }
                        }
                    }
                    Text {
                        objectName: "batchSmartNamingGuidance"
                        anchors.fill: parent
                        visible: root.namingMode === "smart"
                        text: root.tr("batch.toolbar.smartHint")
                        textFormat: Text.PlainText
                        font.family: DesignTokens.fontFamily
                        font.pixelSize: 11
                        color: DesignTokens.textSecondary
                        wrapMode: Text.WordWrap
                        verticalAlignment: Text.AlignVCenter
                        Accessible.name: text
                    }
                }
            }
            AppButton {
                Layout.preferredHeight: 32; Layout.alignment: Qt.AlignBottom
                Layout.minimumWidth: root.englishLocale ? 78 : 72
                Layout.preferredWidth: root.englishLocale ? 78 : 72
                Layout.maximumWidth: root.englishLocale ? 78 : 72
                font.pixelSize: 12; Accessible.name: text
                objectName: "batchAddFilesButton"
                text: root.tr("batch.toolbar.addFiles")
                onClicked: root.addFilesRequested()
            }
            AppButton {
                Layout.preferredHeight: 32; Layout.alignment: Qt.AlignBottom
                Layout.minimumWidth: root.englishLocale ? 88 : 84
                Layout.preferredWidth: root.englishLocale ? 88 : 84
                Layout.maximumWidth: root.englishLocale ? 88 : 84
                font.pixelSize: 12; Accessible.name: text
                objectName: "batchAddFolderButton"
                text: root.tr("batch.toolbar.addFolder")
                onClicked: root.addFolderRequested()
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 180
                spacing: 4
                Caption { objectName: "batchTargetLabel"; text: root.tr("batch.toolbar.destinationLabel") }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    AppButton {
                        Layout.preferredHeight: 32; Layout.alignment: Qt.AlignBottom
                        Layout.minimumWidth: root.englishLocale ? 104 : 88
                        Layout.preferredWidth: root.englishLocale ? 104 : 88
                        Layout.maximumWidth: root.englishLocale ? 104 : 88
                        font.pixelSize: 12; Accessible.name: text
                        objectName: "batchTargetDirectoryButton"
                        text: root.tr("batch.toolbar.targetDirCompact")
                        onClicked: root.targetDirectoryRequested()
                    }
                    AppButton {
                        id: targetSummary
                        objectName: "batchTargetSummary"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 72
                        Layout.preferredWidth: 72
                        Layout.preferredHeight: 32
                        implicitWidth: 72
                        font.pixelSize: 12
                        enabled: root.targetPath !== ""
                        text: root.targetPath ? root.tr("batch.toolbar.moveTo").replace("{path}", root.targetPath)
                                              : root.tr("batch.toolbar.sameFolder")
                        Accessible.name: text
                        Accessible.description: root.tr("batch.toolbar.viewPath")
                        contentItem: Text {
                            text: targetSummary.text
                            textFormat: Text.PlainText
                            color: root.targetPath ? DesignTokens.accentInfo : DesignTokens.textSecondary
                            font: targetSummary.font
                            elide: Text.ElideMiddle
                            verticalAlignment: Text.AlignVCenter
                        }
                        onClicked: targetDetails.open()
                    }
                }
            }
        }
        RowLayout {
            objectName: "batchWorkspaceRow"
            Layout.fillWidth: true
            spacing: 8
            RowLayout {
                Layout.alignment: Qt.AlignBottom
                Layout.preferredHeight: 36
                spacing: 4
                CheckBox {
                    objectName: "batchSelectAll"
                    Accessible.name: root.tr("batch.toolbar.selectVisible")
                    checkState: root.ctrl ? (root.ctrl.selectAllState === "all" ? Qt.Checked
                        : root.ctrl.selectAllState === "partial" ? Qt.PartiallyChecked : Qt.Unchecked) : Qt.Unchecked
                    onClicked: if (root.ctrl) root.ctrl.setSelectAllState(checkState === Qt.Checked ? "all" : "none")
                }
                Column {
                    Text {
                        objectName: "batchSelectedCount"
                        text: root.tr("batch.toolbar.selectedCount").replace("{count}", root.ctrl ? root.ctrl.selectedCount : 0)
                        font.family: DesignTokens.fontFamily; font.pixelSize: 12
                        color: DesignTokens.textPrimary
                    }
                    Caption {
                        objectName: "batchVisibleCount"
                        text: root.tr("batch.toolbar.visibleCount")
                            .replace("{visible}", root.ctrl ? root.ctrl.visibleCount : 0)
                            .replace("{total}", root.ctrl ? root.ctrl.totalCount : 0)
                    }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 110
                spacing: 4
                Caption { objectName: "batchSearchLabel"; text: root.tr("batch.toolbar.searchLabel") }
                TextField {
                    objectName: "batchSearchField"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 32
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: 12
                    selectByMouse: true
                    Accessible.name: root.tr("batch.toolbar.searchLabel")
                    placeholderText: root.tr("batch.toolbar.search")
                    text: root.ctrl ? root.ctrl.searchText : ""
                    onTextChanged: if (root.ctrl && root.ctrl.searchText !== text) root.ctrl.setSearchText(text)
                }
            }
            ColumnLayout {
                Layout.preferredWidth: root.englishLocale ? 146 : 112
                Layout.minimumWidth: root.englishLocale ? 146 : 112
                Layout.maximumWidth: root.englishLocale ? 146 : 112
                spacing: 4
                Caption { objectName: "batchStatusLabel"; text: root.tr("batch.toolbar.statusLabel") }
                AppComboBox {
                    id: statusFilter
                    objectName: "batchStatusFilter"
                    property bool popupVisible: popup.visible
                    Layout.fillWidth: true
                    Layout.preferredHeight: 32
                    font.pixelSize: 12
                    Accessible.name: root.tr("batch.toolbar.statusLabel")
                    model: [root.tr("batch.toolbar.filterAll"), root.tr("batch.state.pending"), root.tr("batch.state.analyzing"), root.tr("batch.state.review"), root.tr("batch.state.undone"), root.tr("batch.state.applied"), root.tr("batch.state.failed"), root.tr("batch.state.cancelled"), root.tr("batch.state.ignored")]
                    readonly property var filters: ["all", "pending", "analyzing", "review_pending", "undone", "applied", "failed", "cancelled", "ignored"]
                    function syncFilter() {
                        currentIndex = Math.max(0, filters.indexOf(root.ctrl ? root.ctrl.statusFilter : "all"))
                    }
                    onActivated: function(index) { if (root.ctrl && index >= 0) root.ctrl.setStatusFilter(filters[index]) }
                    onModelChanged: Qt.callLater(syncFilter)
                    Component.onCompleted: syncFilter()
                    Connections {
                        target: root.ctrl
                        function onFilterChanged() { statusFilter.syncFilter() }
                    }
                }
            }
            AppButton {
                Layout.preferredHeight: 32; Layout.alignment: Qt.AlignBottom
                Layout.minimumWidth: root.englishLocale ? 104 : 84
                Layout.preferredWidth: root.englishLocale ? 104 : 84
                Layout.maximumWidth: root.englishLocale ? 104 : 84
                font.pixelSize: 12; Accessible.name: text
                objectName: "batchApplySelectedButton"
                primary: true
                property string accessibleName: root.tr("batch.actions.applyAllCompact")
                text: accessibleName
                enabled: root.ctrl && root.ctrl.selectedCount > 0
                onClicked: if (root.ctrl) root.ctrl.applySelected()
            }
            AppButton {
                Layout.preferredHeight: 32; Layout.alignment: Qt.AlignBottom
                Layout.minimumWidth: root.englishLocale ? 82 : 72
                Layout.preferredWidth: root.englishLocale ? 82 : 72
                Layout.maximumWidth: root.englishLocale ? 82 : 72
                font.pixelSize: 12; Accessible.name: text
                objectName: "batchStopButton"
                property string accessibleName: root.tr("batch.actions.stopCompact")
                text: accessibleName
                onClicked: if (root.ctrl) root.ctrl.stopPending()
            }
            AppButton {
                Layout.preferredHeight: 32; Layout.alignment: Qt.AlignBottom
                Layout.minimumWidth: root.englishLocale ? 116 : 84
                Layout.preferredWidth: root.englishLocale ? 116 : 84
                Layout.maximumWidth: root.englishLocale ? 116 : 84
                font.pixelSize: 12; Accessible.name: text
                objectName: "batchClearButton"
                property string accessibleName: root.tr("batch.actions.clearWorkspaceCompact")
                text: accessibleName
                onClicked: if (root.ctrl) root.ctrl.clearWorkspace()
            }
        }
    }
    Rectangle {
        anchors.bottom: parent.bottom
        width: parent.width; height: 1
        color: DesignTokens.borderLight
    }
    Dialog {
        id: targetDetails
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(560, parent ? parent.width - 32 : 560)
        height: Math.min(300, parent ? parent.height - 32 : 300)
        modal: true
        focus: true
        title: root.tr("batch.toolbar.destinationLabel")
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onClosed: targetSummary.forceActiveFocus(Qt.TabFocusReason)
        contentItem: ScrollView {
            clip: true
            TextArea {
                objectName: "batchTargetFullPath"
                text: root.targetPath
                textFormat: TextEdit.PlainText
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.WrapAnywhere
                font.family: DesignTokens.fontFamily
                font.pixelSize: 13
                Accessible.name: root.tr("batch.toolbar.destinationLabel")
            }
        }
        footer: DialogButtonBox {
            AppButton {
                text: root.tr("common.close")
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
                onClicked: targetDetails.close()
            }
        }
    }
}

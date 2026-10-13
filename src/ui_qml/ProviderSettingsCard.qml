import QtQuick; import QtQuick.Controls.Basic; import QtQuick.Layouts

// Provider settings card — preset + custom provider list with capability
// chips (text / vision / video-keyframe / JSON status), three-state key
// status, guarded activation, and an embedded ProviderForm.
//
// Row interaction layer (M6 gate):
// - the row background is a TapHandler at z=0 — the action Buttons sit
//   above it, so clicking an action never triggers row activation;
// - edit / delete / activate are explicit Buttons with stable objectNames;
// - the form's visibility is owned by this card: the form emits
//   closeRequested() and the card flips formVisible (the form NEVER assigns
//   visible itself).
Rectangle {
    id: root
    objectName: "providerSettingsCard"
    color: DesignTokens.bgPrimary
    radius: DesignTokens.radiusLg; border.width: 1; border.color: DesignTokens.borderLight

    property var ctrl: null
    property bool formVisible: false

    function openFormForNew() {
        providerForm.openNew()
        formVisible = true
    }

    function openFormForExisting(profile) {
        providerForm.openExisting(profile)
        formVisible = true
    }

    function closeForm() {
        formVisible = false
    }

    function hasProviderRow(pid) {
        for (var i = 0; i < providerList.count; i++) {
            var item = providerList.itemAt(i)
            if (item && item.objectName === "providerRow_" + pid) return true
        }
        return false
    }

    // QML-side geometry helper for tests — returns the CENTER of an action
    // button in window/scene coordinates so QTest can deliver a REAL mouse
    // click (Repeater delegates live outside the QObject tree in Qt 6.11).
    // QML-side action invocation used by the RUNTIME integration tests,
    // where real mouse clicks cannot reach Flickable content in offscreen
    // mode.  It calls the Button's own click() API — the same path a real
    // press/release takes — and returns success.  (Standalone-card tests
    // deliver genuine QTest mouse clicks to these buttons.)
    function clickAction(pid, action) {
        for (var i = 0; i < providerList.count; i++) {
            var item = providerList.itemAt(i)
            if (item && item.objectName === "providerRow_" + pid) {
                var btn = item.actionButton(action)
                if (btn && btn.visible) { btn.click(); return true }
                return false
            }
        }
        return false
    }

    function rowCenter(pid) {
        for (var i = 0; i < providerList.count; i++) {
            var item = providerList.itemAt(i)
            if (item && item.objectName === "providerRow_" + pid) {
                var p = item.mapToGlobal(item.width / 2, item.height / 2)
                return [p.x, p.y]
            }
        }
        return [0, 0]
    }
    function actionButtonPos(pid, action) {
        for (var i = 0; i < providerList.count; i++) {
            var item = providerList.itemAt(i)
            if (item && item.objectName === "providerRow_" + pid) {
                var pos = item.actionButtonPos(action)
                return [pos[0], pos[1]]
            }
        }
        return [0, 0]
    }

    implicitHeight: col.implicitHeight + DesignTokens.spacingXl * 2

    ColumnLayout {
        id: col
        anchors.fill: parent
        anchors.margins: DesignTokens.spacingXl
        spacing: DesignTokens.spacingMd

        Text { text: i18n.tr("prefs.provider.title", i18n.locale); font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeLg; font.bold: true; color: DesignTokens.textPrimary }

        Repeater {
            id: providerList
            objectName: "providerListRepeater"
            // Qt 6.11 Repeater delegates live outside the QObject tree and
            // the Repeater itself does not participate in ColumnLayout —
            // pin explicit geometry so rows lay out correctly.
            width: root.width - DesignTokens.spacingXl * 2
            height: providerList.count * 84
            Layout.fillWidth: true
            Layout.preferredHeight: providerList.count * 84
            model: root.ctrl ? root.ctrl.providerProfiles : []
            delegate: Rectangle {
                id: row
                objectName: "providerRow_" + modelData.id
                width: providerList.width
                height: 80
                radius: DesignTokens.radiusMd
                color: modelData.active ? "#e8f0fe" : (rowTapHover.hovered ? DesignTokens.bgSecondary : DesignTokens.bgPrimary)
                border.width: modelData.active ? 1 : 0
                border.color: modelData.active ? DesignTokens.accentInfo : "transparent"

                // Test helper: center of an action button in global coords.
                // (mapToScene was removed in Qt 6.11 — QQuickItem
                // mapToGlobal is the supported replacement; the offscreen
                // test window sits at 0,0 so global == window coords.)
                function sceneCenter(item) {
                    var p = item.mapToGlobal(item.width / 2, item.height / 2)
                    return [p.x, p.y]
                }
                function actionButtonPos(action) {
                    var btn = action === "activate" ? activateBtn
                        : (action === "edit" ? editBtn : deleteBtn)
                    if (!btn.visible) return [0, 0]
                    return sceneCenter(btn)
                }
                function actionButton(action) {
                    return action === "activate" ? activateBtn
                        : (action === "edit" ? editBtn : deleteBtn)
                }

                // Row background activation — below the action buttons (z=0)
                TapHandler {
                    id: rowTapHover
                    acceptedButtons: Qt.LeftButton
                    onTapped: {
                        // D.14: the controller enforces configured/verified/
                        // unavailable guards — row taps cannot bypass them.
                        if (root.ctrl) root.ctrl.setActiveProvider(modelData.id)
                    }
                }

                RowLayout {
                    anchors.fill: parent; anchors.margins: DesignTokens.spacingMd; spacing: DesignTokens.spacingSm
                    anchors.bottomMargin: 36
                    Text { text: modelData.displayName; font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeMd; font.bold: modelData.active; color: DesignTokens.textPrimary; Layout.fillWidth: true; elide: Text.ElideRight }
                    Rectangle { visible: modelData.recommended; color: "#fef3c7"; radius: DesignTokens.radiusSm; Layout.preferredWidth: recLabel.implicitWidth + 8; Layout.preferredHeight: 20
                        Text { id: recLabel; anchors.centerIn: parent; text: i18n.tr("prefs.provider.recommended", i18n.locale); font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm; color: "#92400e" } }
                    Rectangle { visible: modelData.active; color: DesignTokens.accentInfo; radius: DesignTokens.radiusSm; Layout.preferredWidth: actLabel.implicitWidth + 8; Layout.preferredHeight: 20
                        Text { id: actLabel; anchors.centerIn: parent; text: i18n.tr("prefs.provider.active", i18n.locale); font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm; color: "#ffffff" } }
                    // Capability chips (display-only; no monetary data)
                    Rectangle { visible: modelData.textSupported; color: DesignTokens.bgSecondary; radius: DesignTokens.radiusSm; Layout.preferredWidth: txtChip.implicitWidth + 8; Layout.preferredHeight: 18
                        Text { id: txtChip; anchors.centerIn: parent; text: i18n.tr("prefs.provider.capability.text", i18n.locale); font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm; color: DesignTokens.textSecondary } }
                    Rectangle { visible: modelData.visionSupported; color: DesignTokens.bgSecondary; radius: DesignTokens.radiusSm; Layout.preferredWidth: visChip.implicitWidth + 8; Layout.preferredHeight: 18
                        Text { id: visChip; anchors.centerIn: parent; text: i18n.tr("prefs.provider.capability.vision", i18n.locale); font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm; color: DesignTokens.textSecondary } }
                    Rectangle { visible: modelData.structuredJsonStatus !== "unsupported"; color: modelData.structuredJsonStatus === "unverified" ? "#fefce8" : DesignTokens.bgSecondary; radius: DesignTokens.radiusSm; Layout.preferredWidth: jsonChip.implicitWidth + 8; Layout.preferredHeight: 18
                        Text { id: jsonChip; anchors.centerIn: parent; text: modelData.structuredJsonStatus === "unverified" ? i18n.tr("prefs.provider.capability.unverified", i18n.locale) : i18n.tr("prefs.provider.capability.json", i18n.locale); font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm; color: modelData.structuredJsonStatus === "unverified" ? DesignTokens.accentWarning : DesignTokens.textSecondary } }
                    // Key status (three-state: configured / unconfigured / unavailable)
                    Text {
                        text: modelData.credentialUnavailable ? i18n.tr("prefs.provider.apiKey.unavailable", i18n.locale)
                            : (modelData.configured ? i18n.tr("prefs.provider.apiKey.configured", i18n.locale)
                                : i18n.tr("prefs.provider.apiKey.notConfigured", i18n.locale))
                        font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm
                        color: modelData.credentialUnavailable ? DesignTokens.accentError
                            : (modelData.configured ? DesignTokens.accentSuccess : DesignTokens.textSecondary)
                    }
                    Text { visible: modelData.staged; text: "*"; font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm; color: DesignTokens.accentWarning }
                    // Activate action — gated by the same conditions the
                    // controller enforces (configured + verified + available).
                    AppButton {
                        id: activateBtn
                        objectName: "providerActivate_" + modelData.id
                        visible: modelData.canActivate === true
                        text: "▷"
                        onClicked: { if (root.ctrl) root.ctrl.setActiveProvider(modelData.id) }
                        font.pixelSize: DesignTokens.fontSizeLg
                        implicitWidth: 32; implicitHeight: 28
                    }
                    // Edit action
                    AppButton {
                        id: editBtn
                        objectName: "providerEdit_" + modelData.id
                        visible: !modelData.active
                        text: i18n.tr("prefs.provider.edit", i18n.locale)
                        onClicked: root.openFormForExisting(modelData)
                        font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm
                        implicitWidth: 48; implicitHeight: 28
                    }
                    // Delete action (custom providers only)
                    AppButton {
                        id: deleteBtn
                        objectName: "providerDelete_" + modelData.id
                        visible: !modelData.isPreset && !modelData.active
                        text: i18n.tr("prefs.provider.delete", i18n.locale)
                        onClicked: root.openFormForExisting(modelData)
                        font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm
                        implicitWidth: 48; implicitHeight: 28
                    }
                }
                Text {
                    visible: modelData.videoKeyframesSupported
                    anchors.left: parent.left; anchors.right: parent.right
                    anchors.leftMargin: DesignTokens.spacingMd
                    anchors.rightMargin: DesignTokens.spacingMd
                    anchors.bottom: parent.bottom; anchors.bottomMargin: 8
                    text: i18n.tr("prefs.provider.capability.video", i18n.locale)
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeSm
                    color: DesignTokens.textSecondary
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                }
            }
        }

        // Add custom provider button — opens the ProviderForm (D.1)
        AppButton {
            id: addProviderBtn
            objectName: "addProviderBtn"
            text: i18n.tr("prefs.provider.add", i18n.locale)
            onClicked: root.openFormForNew()
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeSm
        }

        // Embedded form — nothing is added to the draft until Save (D.2).
        // Visibility is OWNED by this card: the form emits closeRequested()
        // and never assigns visible itself.
        ProviderForm {
            id: providerForm
            objectName: "providerForm"
            visible: root.formVisible
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: col.width
            Layout.maximumWidth: col.width
            ctrl: root.ctrl
            onCloseRequested: root.formVisible = false
        }
    }
}

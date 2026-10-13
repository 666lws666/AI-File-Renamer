import QtQuick; import QtQuick.Controls.Basic; import QtQuick.Layouts

// Provider edit form — opened by ProviderSettingsCard for a new custom
// provider or an existing profile.
//
// Contract (M6 Provider Integration Gate):
// - The API Key field is ALWAYS empty when the form opens; only the
//   configured/unconfigured/unavailable status badge is shown.
// - The form NEVER assigns root.visible — it emits closeRequested() and the
//   owning card flips formVisible, keeping the visibility binding intact.
// - Connection tests pass the FULL candidate to ctrl.testConnectionCandidate;
//   the controller builds/validates the profile, runs the connection service,
//   and binds the result to the candidate's fingerprint.  Any field or key
//   change invalidates the test result (testInvalidated + controller
//   fingerprint).
// - REGIONAL presets expose a region selector (+ workspace id when the
//   endpoint template needs it); fixed-endpoint presets cannot override the
//   official Base URL.
Rectangle {
    id: root
    objectName: "providerForm"
    color: DesignTokens.bgSecondary
    radius: DesignTokens.radiusMd
    border.width: 1
    border.color: DesignTokens.borderLight

    property var ctrl: null
    signal closeRequested()
    onCloseRequested: invalidateCandidate()
    onVisibleChanged: invalidateCandidate()

    function invalidateCandidate() {
        if (root.ctrl) root.ctrl.invalidateConnectionCandidate()
    }

    // Editing state
    property bool isNew: false
    property bool isPreset: false
    property string editingId: ""

    // Form fields
    property string providerName: ""
    property string providerId: ""
    property string baseUrl: ""
    property string model: ""
    property var modelOptions: []
    readonly property bool isDeepSeek: isPreset && providerId === "deepseek"
    onModelChanged: refreshModelCapabilities()

    function refreshModelCapabilities() {
        if (!isDeepSeek || !ctrl) return
        var caps = ctrl.presetModelCapabilities(providerId, model)
        capText = caps.text
        capVision = caps.vision
        capJson = caps.json_mode
        capVideo = caps.vision
    }
    property bool capText: true
    property bool capVision: false
    property bool capJson: false
    property bool capVideo: false
    property string credentialState: "unconfigured"
    property string validationError: ""
    property string apiKey: ""  // never pre-filled — D.5

    // REGIONAL preset support
    property var regions: []            // [{name, needsWorkspaceId}]
    property string providerRegion: ""
    property string workspaceId: ""
    property bool regionNeedsWorkspace: false
    property bool requiresUserModel: false

    // Test-state display: scoped to THIS provider, invalidated on edit.
    // The effective id is editingId for existing profiles and the typed
    // providerId for a NEW custom provider (which has no editingId yet).
    // Both ctrl.connectionTestProviderId and ctrl.connectionTestState are
    // Properties notified by connectionTestStateChanged, so this binding
    // re-evaluates on EVERY test-state change; markEdited() resets it to
    // idle by flipping testInvalidated.
    property bool testInvalidated: false
    property string effectiveTestId: root.isNew ? root.providerId : root.editingId
    property string testState: {
        if (!root.ctrl || root.testInvalidated) return "idle"
        if (root.ctrl.connectionTestProviderId !== root.effectiveTestId) return "idle"
        return root.ctrl.connectionTestState
    }

    function openNew() {
        invalidateCandidate()
        modelOptions = []
        isNew = true
        isPreset = false
        editingId = ""
        providerName = ""
        providerId = ""
        baseUrl = ""
        model = ""
        capText = true
        capVision = false
        capJson = false
        capVideo = false
        credentialState = "unconfigured"
        regions = []
        providerRegion = ""
        workspaceId = ""
        regionNeedsWorkspace = false
        requiresUserModel = false
        validationError = ""
        testInvalidated = false
        apiKey = ""
    }

    function openExisting(profile) {
        invalidateCandidate()
        modelOptions = profile.modelOptions || []
        isNew = false
        isPreset = profile.isPreset === true
        editingId = profile.id || ""
        providerName = profile.displayName || ""
        providerId = profile.id || ""
        baseUrl = profile.baseUrl || ""
        model = profile.model || ""
        capText = profile.textSupported !== false
        capVision = profile.visionSupported === true
        capJson = profile.structuredJsonStatus !== "unsupported"
        capVideo = profile.videoKeyframesSupported === true
        credentialState = profile.credentialState || "unconfigured"
        requiresUserModel = profile.requiresUserModel === true
        regions = profile.regions || []
        providerRegion = profile.region || ""
        regionNeedsWorkspace = root.regionNeedsWorkspaceFor(providerRegion)
        workspaceId = ""
        validationError = ""
        testInvalidated = false
        apiKey = ""  // D.5: key field is always empty on open
    }

    function regionNeedsWorkspaceFor(regionName) {
        for (var i = 0; i < root.regions.length; i++) {
            if (root.regions[i].name === regionName) {
                return root.regions[i].needsWorkspaceId === true
            }
        }
        return false
    }

    function markEdited() {
        invalidateCandidate()
        root.testInvalidated = true
    }

    function buildCandidate() {
        validationError = ""
        var name = root.providerName.trim()
        var id = root.providerId.trim()
        var url = root.baseUrl.trim()
        var mdl = root.model.trim()
        if (!name) { validationError = i18n.tr("prefs.provider.error.name", i18n.locale); return null }
        if (!id) { validationError = i18n.tr("prefs.provider.error.id", i18n.locale); return null }
        if (!/^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?$/.test(id)) {
            validationError = i18n.tr("prefs.provider.error.idFormat", i18n.locale)
            return null
        }
        // Base URL is required for new custom providers; presets carry the
        // official endpoint (fixed or regional) and cannot override it.
        if (root.isNew && !url) { validationError = i18n.tr("prefs.provider.error.baseUrl", i18n.locale); return null }
        if (!mdl) { validationError = i18n.tr("prefs.provider.error.model", i18n.locale); return null }
        if (root.requiresUserModel && !mdl) {
            validationError = i18n.tr("prefs.provider.error.model", i18n.locale)
            return null
        }
        var candidate = {
            id: id,
            display_name: name,
            model: mdl,
            capabilities: { text: root.capText, vision: root.capVision, json_mode: root.capJson }
        }
        if (!root.isPreset) {
            candidate.base_url = url
        } else if (root.regions.length > 0) {
            // REGIONAL preset — region is mandatory, workspace where needed
            if (!root.providerRegion) {
                validationError = i18n.tr("prefs.provider.error.region", i18n.locale)
                return null
            }
            candidate.region = root.providerRegion
            if (root.regionNeedsWorkspace) {
                if (!root.workspaceId.trim()) {
                    validationError = i18n.tr("prefs.provider.error.workspace", i18n.locale)
                    return null
                }
                candidate.workspace_id = root.workspaceId.trim()
            }
        }
        return candidate
    }

    function doTestConnection() {
        var candidate = root.buildCandidate()
        if (!candidate) return
        root.testInvalidated = false
        if (root.ctrl) root.ctrl.testConnectionCandidate(candidate, root.apiKey.trim())
    }

    function doSave() {
        var candidate = root.buildCandidate()
        if (!candidate) return
        if (root.ctrl) {
            // addOrUpdateProvider verifies the candidate fingerprint matches
            // the last SUCCESSFUL test; otherwise it saves unverified.
            root.ctrl.addOrUpdateProvider(candidate, root.apiKey.trim())
            if (root.apiKey.trim() !== "") {
                root.ctrl.stageProviderKey(root.providerId.trim(), root.apiKey.trim())
            }
        }
        root.closeRequested()
    }

    function doCancel() {
        root.closeRequested()
    }

    function doClearKey() {
        root.apiKey = ""
        if (root.ctrl && root.editingId !== "") {
            root.ctrl.clearProviderKey(root.editingId)
        }
    }

    function doDelete() {
        if (root.ctrl && !root.isPreset && root.editingId !== "") {
            root.ctrl.removeProvider(root.editingId)
        }
        root.closeRequested()
    }

    Connections {
        target: root.ctrl
        // testState is a binding on ctrl.connectionTestProviderId /
        // ctrl.connectionTestState (both notified by
        // connectionTestStateChanged) — no imperative sync needed.
        function onProviderProfilesChanged() {
            if (root.ctrl && root.editingId !== "") {
                var profiles = root.ctrl.providerProfiles
                for (var i = 0; i < profiles.length; i++) {
                    if (profiles[i].id === root.editingId) {
                        root.credentialState = profiles[i].credentialState
                        break
                    }
                }
            }
        }
    }

    implicitHeight: formColumn.implicitHeight + DesignTokens.spacingMd * 2

    ColumnLayout {
        id: formColumn
        anchors.fill: parent
        anchors.margins: DesignTokens.spacingMd
        spacing: DesignTokens.spacingMd

        // Validation error
        Rectangle {
            visible: root.validationError !== ""
            Layout.fillWidth: true
            Layout.preferredHeight: validationText.implicitHeight + 8
            color: "#fef2f2"
            radius: DesignTokens.radiusSm
            border.color: DesignTokens.accentError
            Text {
                id: validationText
                anchors.centerIn: parent
                text: root.validationError
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeSm
                color: DesignTokens.accentError
            }
        }

        // Name field
        ColumnLayout {
            spacing: DesignTokens.spacingXs
            Layout.fillWidth: true
            Text {
                text: i18n.tr("prefs.provider.name", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
            }
            TextField {
                objectName: "pfNameField"
                Layout.fillWidth: true
                Layout.preferredHeight: 32
                text: root.providerName
                onTextChanged: { root.providerName = text; root.markEdited() }
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
                background: Rectangle {
                    radius: DesignTokens.radiusSm
                    border.color: DesignTokens.borderLight
                    color: DesignTokens.bgPrimary
                }
            }
        }

        // ID field
        ColumnLayout {
            spacing: DesignTokens.spacingXs
            Layout.fillWidth: true
            Text {
                text: i18n.tr("prefs.provider.id.label", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
            }
            TextField {
                objectName: "pfIdField"
                Layout.fillWidth: true
                Layout.preferredHeight: 32
                enabled: root.isNew
                placeholderText: i18n.tr("prefs.provider.id.placeholder", i18n.locale)
                text: root.providerId
                onTextChanged: { root.providerId = text; root.markEdited() }
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
                background: Rectangle {
                    radius: DesignTokens.radiusSm
                    border.color: DesignTokens.borderLight
                    color: DesignTokens.bgPrimary
                }
            }
        }

        // Base URL field — disabled for presets (official endpoints only)
        ColumnLayout {
            spacing: DesignTokens.spacingXs
            Layout.fillWidth: true
            Text {
                text: i18n.tr("prefs.provider.baseUrl", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
            }
            TextField {
                objectName: "pfBaseUrlField"
                Layout.fillWidth: true
                Layout.preferredHeight: 32
                enabled: root.isNew
                placeholderText: root.isPreset
                    ? i18n.tr("prefs.provider.baseUrl.preset", i18n.locale)
                    : i18n.tr("prefs.provider.baseUrl.placeholder", i18n.locale)
                text: root.baseUrl
                onTextChanged: { root.baseUrl = text; root.markEdited() }
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: root.isPreset ? DesignTokens.textSecondary : DesignTokens.textPrimary
                background: Rectangle {
                    radius: DesignTokens.radiusSm
                    border.color: DesignTokens.borderLight
                    color: DesignTokens.bgPrimary
                }
            }
        }

        // Region selector (REGIONAL presets, e.g. Qwen)
        ColumnLayout {
            visible: root.regions.length > 0
            spacing: DesignTokens.spacingXs
            Layout.fillWidth: true
            Text {
                text: i18n.tr("prefs.provider.region.label", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
            }
            AppComboBox {
                objectName: "pfRegionCombo"
                Layout.fillWidth: true
                Layout.preferredHeight: 32
                model: {
                    var names = []
                    for (var i = 0; i < root.regions.length; i++) names.push(root.regions[i].name)
                    return names
                }
                currentIndex: {
                    for (var i = 0; i < root.regions.length; i++) {
                        if (root.regions[i].name === root.providerRegion) return i
                    }
                    return -1
                }
                onCurrentIndexChanged: {
                    // Fires for BOTH user selection and programmatic changes;
                    // the write-back of the binding's own index is a no-op.
                    if (currentIndex >= 0 && currentIndex < root.regions.length) {
                        var region = root.regions[currentIndex]
                        if (region.name !== root.providerRegion) {
                            root.providerRegion = region.name
                            root.regionNeedsWorkspace = region.needsWorkspaceId === true
                            root.workspaceId = ""
                            root.markEdited()
                        }
                    }
                }
            }
        }

        // Workspace id (REGIONAL endpoints that embed it)
        ColumnLayout {
            visible: root.regionNeedsWorkspace
            spacing: DesignTokens.spacingXs
            Layout.fillWidth: true
            Text {
                text: i18n.tr("prefs.provider.workspace.label", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
            }
            TextField {
                objectName: "pfWorkspaceField"
                Layout.fillWidth: true
                Layout.preferredHeight: 32
                placeholderText: i18n.tr("prefs.provider.workspace.placeholder", i18n.locale)
                text: root.workspaceId
                onTextChanged: { root.workspaceId = text; root.markEdited() }
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
                background: Rectangle {
                    radius: DesignTokens.radiusSm
                    border.color: DesignTokens.borderLight
                    color: DesignTokens.bgPrimary
                }
            }
        }

        // Model field
        ColumnLayout {
            spacing: DesignTokens.spacingXs
            Layout.fillWidth: true
            Text {
                text: i18n.tr("prefs.provider.model", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
            }
            AppComboBox {
                objectName: "pfDeepSeekModels"
                visible: root.isDeepSeek
                Layout.fillWidth: true
                Layout.preferredHeight: 32
                model: [
                    i18n.tr("prefs.provider.deepseek.flash", i18n.locale),
                    i18n.tr("prefs.provider.deepseek.pro", i18n.locale),
                    i18n.tr("prefs.provider.deepseek.vision", i18n.locale),
                    i18n.tr("prefs.provider.deepseek.legacyFlash", i18n.locale)
                ]
                currentIndex: root.modelOptions.indexOf(root.model)
                displayText: currentIndex >= 0 ? currentText : i18n.tr("prefs.provider.deepseek.choose", i18n.locale)
                onActivated: function(index) {
                    if (index >= 0 && index < root.modelOptions.length) {
                        root.model = root.modelOptions[index]
                        root.markEdited()
                    }
                }
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
            }
            TextField {
                objectName: "pfModelField"
                Layout.fillWidth: true
                Layout.preferredHeight: 32
                placeholderText: root.requiresUserModel
                    ? i18n.tr("prefs.provider.model.required", i18n.locale)
                    : i18n.tr("prefs.provider.model.placeholder", i18n.locale)
                text: root.model
                onTextChanged: { root.model = text; root.markEdited() }
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
                background: Rectangle {
                    radius: DesignTokens.radiusSm
                    border.color: DesignTokens.borderLight
                    color: DesignTokens.bgPrimary
                }
            }
            Text {
                objectName: "pfDeepSeekModelHint"
                visible: root.isDeepSeek
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: 0
                wrapMode: Text.WordWrap
                text: i18n.tr(root.capVision ? "prefs.provider.deepseek.visionHint"
                    : (root.capJson ? "prefs.provider.deepseek.textHint" : "prefs.provider.deepseek.unknownHint"), i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeSm
                color: DesignTokens.textSecondary
            }
        }

        // Capabilities
        ColumnLayout {
            spacing: DesignTokens.spacingXs
            Layout.fillWidth: true
            Text {
                text: i18n.tr("prefs.provider.capabilities.label", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: DesignTokens.spacingLg
                CheckBox {
                    objectName: "pfTextCap"
                    enabled: !root.isDeepSeek
                    text: i18n.tr("prefs.provider.capability.text", i18n.locale)
                    checked: root.capText
                    onCheckedChanged: { root.capText = checked; root.markEdited() }
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeSm
                }
                CheckBox {
                    objectName: "pfVisionCap"
                    enabled: !root.isDeepSeek
                    text: i18n.tr("prefs.provider.capability.vision", i18n.locale)
                    checked: root.capVision
                    onCheckedChanged: { root.capVision = checked; root.markEdited() }
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeSm
                }
                CheckBox {
                    objectName: "pfJsonCap"
                    enabled: !root.isDeepSeek
                    text: i18n.tr("prefs.provider.capability.json", i18n.locale)
                    checked: root.capJson
                    onCheckedChanged: { root.capJson = checked; root.markEdited() }
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeSm
                }
            }
        }

        // API Key field — always empty; status badge only
        ColumnLayout {
            spacing: DesignTokens.spacingXs
            Layout.fillWidth: true
            Text {
                text: i18n.tr("prefs.provider.apiKey", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: DesignTokens.spacingSm
                TextField {
                    objectName: "pfApiKeyField"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 32
                    echoMode: TextInput.Password
                    placeholderText: i18n.tr("prefs.provider.apiKey.placeholder", i18n.locale)
                    text: root.apiKey
                    onTextChanged: { root.apiKey = text; root.markEdited() }
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeMd
                    color: DesignTokens.textPrimary
                    background: Rectangle {
                        radius: DesignTokens.radiusSm
                        border.color: DesignTokens.borderLight
                        color: DesignTokens.bgPrimary
                    }
                }
                // Key status badge (three-state)
                Rectangle {
                    id: keyStatusBadge
                    objectName: "pfKeyStatus"
                    Layout.preferredWidth: statusLabel.implicitWidth + 16
                    Layout.preferredHeight: 24
                    radius: DesignTokens.radiusSm
                    color: root.credentialState === "configured" ? "#f0fdf4"
                        : (root.credentialState === "unavailable" ? "#fef2f2" : "#fefce8")
                    border.color: root.credentialState === "configured" ? DesignTokens.accentSuccess
                        : (root.credentialState === "unavailable" ? DesignTokens.accentError : DesignTokens.accentWarning)
                    Text {
                        id: statusLabel
                        objectName: "pfKeyStatusText"
                        anchors.centerIn: parent
                        text: root.credentialState === "configured"
                            ? i18n.tr("prefs.provider.apiKey.configured", i18n.locale)
                            : (root.credentialState === "unavailable"
                                ? i18n.tr("prefs.provider.apiKey.unavailable", i18n.locale)
                                : i18n.tr("prefs.provider.apiKey.notConfigured", i18n.locale))
                        font.family: DesignTokens.fontFamily
                        font.pixelSize: DesignTokens.fontSizeSm
                        color: root.credentialState === "configured" ? DesignTokens.accentSuccess
                            : (root.credentialState === "unavailable" ? DesignTokens.accentError : DesignTokens.accentWarning)
                    }
                }
                // Clear key button
                AppButton {
                    objectName: "pfClearKeyBtn"
                    visible: root.credentialState === "configured" || root.apiKey.trim() !== ""
                    text: i18n.tr("prefs.provider.apiKey.clear", i18n.locale)
                    onClicked: root.doClearKey()
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeSm
                }
            }
        }

        // Test connection
        RowLayout {
            Layout.fillWidth: true
            spacing: DesignTokens.spacingMd
            AppButton {
                objectName: "pfTestConnBtn"
                text: i18n.tr("prefs.provider.testConnection", i18n.locale)
                onClicked: root.doTestConnection()
            }
            Text {
                objectName: "pfTestStatus"
                text: {
                    if (root.testState === "testing") return i18n.tr("prefs.provider.test.testing", i18n.locale)
                    if (root.testState === "success") return i18n.tr("prefs.provider.test.success", i18n.locale)
                    if (root.testState === "failure") return i18n.tr("prefs.provider.test.failure", i18n.locale)
                    return i18n.tr("prefs.provider.test.idle", i18n.locale)
                }
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeSm
                color: root.testState === "success" ? DesignTokens.accentSuccess
                    : (root.testState === "failure" ? DesignTokens.accentError : DesignTokens.textSecondary)
            }
        }

        // Actions
        RowLayout {
            Layout.fillWidth: true
            spacing: DesignTokens.spacingMd
            AppButton {
                objectName: "pfSaveBtn"
                primary: true
                text: i18n.tr("common.save", i18n.locale)
                onClicked: root.doSave()
            }
            AppButton {
                objectName: "pfCancelBtn"
                text: i18n.tr("common.cancel", i18n.locale)
                onClicked: root.doCancel()
            }
            Item { Layout.fillWidth: true }
            AppButton {
                objectName: "pfDeleteBtn"
                visible: !root.isNew && !root.isPreset
                text: i18n.tr("prefs.provider.delete", i18n.locale)
                onClicked: root.doDelete()
            }
        }
    }
}

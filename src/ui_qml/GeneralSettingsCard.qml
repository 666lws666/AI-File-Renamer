import QtQuick; import QtQuick.Controls.Basic; import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "generalSettingsCard"
    color: DesignTokens.bgPrimary
    radius: DesignTokens.radiusLg
    border.width: 1; border.color: DesignTokens.borderLight

    property var ctrl: null
    property var templateController: null
    readonly property var templateChoices: [{id: "", name: i18n.tr("prefs.general.templateAuto", i18n.locale)}].concat(templateController ? templateController.templates : [])
    readonly property bool unknownTemplate: !!ctrl && ctrl.defaultTemplateId !== "" && defaultTemplateCombo.currentIndex < 0

    // M6 correction: true while the max-file-size field holds an
    // out-of-range value — the page gates Save on it.
    property bool inputError: maxFileSizeField.error || unknownTemplate

    implicitHeight: col.implicitHeight + DesignTokens.spacingXl * 2

    ColumnLayout {
        id: col
        anchors.fill: parent
        anchors.margins: DesignTokens.spacingXl
        spacing: DesignTokens.spacingMd

        Text { text: i18n.tr("prefs.general.title", i18n.locale); font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeLg; font.bold: true; color: DesignTokens.textPrimary }

        // Language — writes BOTH the controller draft (persistence) and the
        // I18n locale (the current page re-translates immediately, because
        // every text binding depends on i18n.locale).
        RowLayout { Layout.fillWidth: true; spacing: DesignTokens.spacingMd
            Text { text: i18n.tr("prefs.general.language", i18n.locale); Layout.preferredWidth: 140; font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeMd; color: DesignTokens.textSecondary }
            AppComboBox {
                objectName: "languageCombo"
                Layout.preferredWidth: 160
                textRole: "label"
                valueRole: "value"
                model: [
                    {label: i18n.tr("prefs.general.language.zh_CN", i18n.locale), value: "zh_CN"},
                    {label: i18n.tr("prefs.general.language.en_US", i18n.locale), value: "en_US"},
                    {label: i18n.tr("prefs.general.language.zh_HK", i18n.locale), value: "zh_HK"}
                ]
                currentValue: root.ctrl ? root.ctrl.language.replace("-", "_") : "zh_CN"
                onActivated: {
                    if (root.ctrl && currentIndex >= 0) {
                        root.ctrl.language = currentValue
                        i18n.setLocale(currentValue)
                    }
                }
            }
        }

        // Theme
        RowLayout { Layout.fillWidth: true; spacing: DesignTokens.spacingMd
            Text { text: i18n.tr("prefs.general.theme", i18n.locale); Layout.preferredWidth: 140; font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeMd; color: DesignTokens.textSecondary }
            Text { text: i18n.tr("prefs.general.theme.light", i18n.locale); font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeMd; color: DesignTokens.textPrimary }
        }

        // Default template
        RowLayout { Layout.fillWidth: true; spacing: DesignTokens.spacingMd
            Text { text: i18n.tr("prefs.general.defaultTemplate", i18n.locale); Layout.preferredWidth: 140; font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeMd; color: DesignTokens.textSecondary }
            AppComboBox {
                id: defaultTemplateCombo
                objectName: "defaultTemplateField"
                Layout.fillWidth: true
                editable: false
                model: root.templateChoices
                textRole: "name"
                valueRole: "id"
                currentValue: root.ctrl ? root.ctrl.defaultTemplateId : ""
                displayText: currentIndex < 0 ? i18n.tr("prefs.general.templateUnavailable", i18n.locale) : currentText
                onActivated: if (root.ctrl && currentIndex >= 0) root.ctrl.defaultTemplateId = currentValue
            }
        }
        Text {
            objectName: "defaultTemplateError"
            Layout.fillWidth: true
            Layout.leftMargin: 152
            visible: root.unknownTemplate
            text: i18n.tr("prefs.general.templateUnavailable", i18n.locale)
            wrapMode: Text.Wrap
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeSm
            color: DesignTokens.accentError
        }

        // Max file size — validated input with visible inline error for
        // out-of-range values (0 / 1000 ...).  The raw text stays in the
        // field; only legal values reach the controller draft.
        ColumnLayout { Layout.fillWidth: true; spacing: DesignTokens.spacingXs
            RowLayout { Layout.fillWidth: true; spacing: DesignTokens.spacingMd
                Text { text: i18n.tr("prefs.general.maxFileSize", i18n.locale); Layout.preferredWidth: 140; font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeMd; color: DesignTokens.textSecondary }
                ValidatedNumberField {
                    id: maxFileSizeField
                    objectName: "maxFileSizeSpin"
                    Layout.preferredWidth: 140
                    from: 1
                    to: 500
                    value: root.ctrl ? root.ctrl.maxFileSizeMb : 50
                    onValueChanged: {
                        if (root.ctrl) root.ctrl.maxFileSizeMb = value
                    }
                }
            }
            Text {
                id: maxFileSizeError
                objectName: "maxFileSizeError"
                visible: maxFileSizeField.error
                Layout.leftMargin: 148
                text: i18n.tr("prefs.general.maxFileSize.error", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeSm
                color: DesignTokens.accentError
            }
        }

        // Max content chars
        RowLayout { Layout.fillWidth: true; spacing: DesignTokens.spacingMd
            Text { text: i18n.tr("prefs.general.maxContentChars", i18n.locale); Layout.preferredWidth: 140; font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeMd; color: DesignTokens.textSecondary }
            SpinBox { objectName: "maxContentCharsSpin"; Layout.preferredWidth: 140; from: 500; to: 16000; stepSize: 100; value: root.ctrl ? root.ctrl.maxContentChars : 4000
                onValueChanged: { if (root.ctrl) root.ctrl.maxContentChars = value } }
        }
    }
}

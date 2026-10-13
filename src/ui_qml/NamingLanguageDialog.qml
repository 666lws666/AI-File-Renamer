import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Item {
    id: root
    objectName: "namingLanguageDialog"
    visible: false
    property string templateName: ""
    property string templateLanguage: "zh"
    property string namingMode: "template"
    property string draftLanguage: ""
    signal confirmed(string language)
    signal cancelled()
    function initializeLanguage() {
        if (root.namingMode === "smart" && root.draftLanguage === "")
            root.draftLanguage = "zh"
    }
    onVisibleChanged: if (visible) { initializeLanguage(); forceActiveFocus() }
    onNamingModeChanged: if (visible) initializeLanguage()
    Keys.onEscapePressed: function(event) { root.cancelled(); event.accepted = true }

    Rectangle { anchors.fill: parent; color: "#55000000" }
    MouseArea { anchors.fill: parent; onClicked: root.forceActiveFocus() }
    Rectangle {
        anchors.centerIn: parent
        width: Math.max(0, Math.min(520, parent.width - 32))
        height: content.implicitHeight + 40
        radius: 10
        color: DesignTokens.bgPrimary
        border.color: DesignTokens.borderLight
        ColumnLayout {
            id: content
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
            anchors.margins: 20
            spacing: 16
            Text {
                Layout.fillWidth: true
                text: i18n.tr("naming.prompt.title", i18n.locale)
                font.family: DesignTokens.fontFamily; font.pixelSize: 18; font.bold: true
                color: DesignTokens.textPrimary; wrapMode: Text.Wrap
            }
            Text {
                objectName: "namingTemplateSummary"
                Layout.fillWidth: true
                visible: root.namingMode === "template"
                text: i18n.tr("naming.prompt.template", i18n.locale) + root.templateName
                font.family: DesignTokens.fontFamily; font.pixelSize: 13
                color: DesignTokens.textSecondary; wrapMode: Text.Wrap
            }
            Text {
                objectName: "namingSmartSummary"
                Layout.fillWidth: true
                visible: root.namingMode === "smart"
                text: i18n.tr("naming.prompt.smart", i18n.locale)
                font.family: DesignTokens.fontFamily; font.pixelSize: 13
                color: DesignTokens.textSecondary; wrapMode: Text.Wrap
            }
            Text {
                Layout.fillWidth: true
                text: i18n.tr("naming.prompt.language", i18n.locale)
                font.family: DesignTokens.fontFamily; font.pixelSize: 13
                color: DesignTokens.textPrimary
            }
            AppComboBox {
                id: languageChoice
                objectName: "namingLanguageChoice"
                Layout.fillWidth: true
                textRole: "label"; valueRole: "value"
                readonly property var languageChoices: [
                    {label: i18n.tr("naming.language.zh", i18n.locale), value: "zh"},
                    {label: i18n.tr("templates.language.zh-HK", i18n.locale), value: "zh-HK"},
                    {label: i18n.tr("templates.language.en", i18n.locale), value: "en"},
                    {label: i18n.tr("templates.language.ja", i18n.locale), value: "ja"},
                    {label: i18n.tr("templates.language.es", i18n.locale), value: "es"}
                ]
                model: root.namingMode === "smart" ? languageChoices : [
                    {label: i18n.tr("naming.prompt.follow", i18n.locale) + " · " + i18n.tr("templates.language." + root.templateLanguage, i18n.locale), value: ""}
                ].concat(languageChoices)
                function syncSelection() {
                    const index = indexOfValue(root.draftLanguage)
                    currentIndex = index >= 0 ? index : 0
                }
                onActivated: if (currentIndex >= 0) root.draftLanguage = currentValue
                onModelChanged: Qt.callLater(syncSelection)
                Component.onCompleted: syncSelection()
                Connections {
                    target: root
                    function onDraftLanguageChanged() { languageChoice.syncSelection() }
                    function onNamingModeChanged() { Qt.callLater(languageChoice.syncSelection) }
                }
            }
            Text {
                Layout.fillWidth: true
                text: i18n.tr("naming.prompt.hint", i18n.locale)
                font.family: DesignTokens.fontFamily; font.pixelSize: 13
                color: DesignTokens.textSecondary; wrapMode: Text.Wrap
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                spacing: 12
                AppButton {
                    objectName: "namingLanguageCancel"
                    text: i18n.tr("common.cancel", i18n.locale)
                    onClicked: root.cancelled()
                }
                AppButton {
                    objectName: "namingLanguageConfirm"
                    primary: true
                    text: i18n.tr("naming.prompt.confirm", i18n.locale)
                    onClicked: root.confirmed(root.draftLanguage)
                }
            }
        }
    }
}

import QtQuick; import QtQuick.Controls.Basic; import QtQuick.Layouts

Rectangle {
    id: root; color: DesignTokens.bgPrimary; radius: DesignTokens.radiusMd
    border.width: 1; border.color: DesignTokens.accentInfo
    property var ctrl: null; property string taskId: ""
    property string currentValue: ""; property string extension: ""
    property string validationError: ""
    property string localValidationError: ""
    property bool externalErrorDismissed: false
    property alias nameField: nameField
    signal confirmed(string newName); signal cancelled()

    function displayedError() {
        if (root.localValidationError !== "") return root.localValidationError
        return root.externalErrorDismissed ? "" : root.validationError
    }
    function validationMessage() {
        const error = root.displayedError()
        return error.indexOf("batch.validate.") === 0 ? i18n.tr(error, i18n.locale) : error
    }

    onValidationErrorChanged: externalErrorDismissed = false
    function begin(val, ext) {
        currentValue = val; extension = ext
        localValidationError = ""; externalErrorDismissed = false
        nameField.text = val
        Qt.callLater(function() { if (root.visible) nameField.forceActiveFocus() })
    }

    RowLayout {
        id: inputRow
        anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
        anchors.margins: 4; height: 30; spacing: 4
        TextField {
            id: nameField; objectName: "inlineNameField"
            Layout.fillWidth: true; Layout.preferredHeight: 28
            font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeMd
            onTextEdited: { root.localValidationError = ""; root.externalErrorDismissed = true }
            Keys.onReturnPressed: root.validateAndConfirm()
            Keys.onEscapePressed: root.cancelled()
        }
        Text { text: root.extension; font.pixelSize: DesignTokens.fontSizeMd; color: DesignTokens.textSecondary; Layout.alignment: Qt.AlignVCenter }
        Rectangle { width: 24; height: 24; radius: 4; color: DesignTokens.btnPrimary
            Text { anchors.centerIn: parent; text: "✓"; color: "#fff"; font.pixelSize: 12 }
            TapHandler { onTapped: root.validateAndConfirm() }
        }
        Rectangle { width: 24; height: 24; radius: 4; color: DesignTokens.borderLight
            Text { anchors.centerIn: parent; text: "✕"; color: DesignTokens.textPrimary; font.pixelSize: 12 }
            TapHandler { onTapped: root.cancelled() }
        }
    }
    Text {
        objectName: "inlineValidationError"
        visible: root.displayedError() !== ""; text: root.validationMessage(); color: DesignTokens.accentError
        font.pixelSize: 10; elide: Text.ElideRight
        anchors.top: inputRow.bottom; anchors.topMargin: 2
        anchors.left: parent.left; anchors.right: parent.right
        anchors.leftMargin: 4; anchors.rightMargin: 4
    }

    function validateAndConfirm() {
        var name = nameField.text.trim()
        if (name === "") { root.localValidationError = "batch.validate.empty"; return }
        var illegal = /[<>:"/\\|?*]/
        if (illegal.test(name)) { root.localValidationError = "batch.validate.illegalChars"; return }
        if (/[. ]$/.test(name)) { root.localValidationError = "batch.validate.ending"; return }
        var reserved = /^(CON|PRN|AUX|NUL|COM\d|LPT\d)$/i
        if (reserved.test(name)) { root.localValidationError = "batch.validate.reserved"; return }
        if (name.length > 200) { root.localValidationError = "batch.validate.tooLong"; return }
        root.confirmed(name)
    }
}

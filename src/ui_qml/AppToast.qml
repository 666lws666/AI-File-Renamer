import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    property string message: ""
    property string severity: "warning"
    property int durationMs: 4000
    signal dismissed()
    implicitWidth: Math.min(420, toastRow.implicitWidth + DesignTokens.spacingLg * 2)
    implicitHeight: toastRow.implicitHeight + DesignTokens.spacingMd * 2
    radius: DesignTokens.radiusMd
    color: severity === "error" ? "#7f1d1d" : "#1e293b"
    visible: false

    function show(text, level) {
        message = text
        severity = level || "warning"
        visible = true
        hideTimer.restart()
    }

    RowLayout {
        id: toastRow
        anchors.fill: parent
        anchors.margins: DesignTokens.spacingMd
        Text {
            Layout.fillWidth: true
            text: root.message
            wrapMode: Text.WordWrap
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeMd
            color: "white"
        }
        Button {
            flat: true
            text: "×"
            onClicked: { root.visible = false; root.dismissed() }
        }
    }
    Timer {
        id: hideTimer
        interval: root.durationMs
        onTriggered: { root.visible = false; root.dismissed() }
    }
}

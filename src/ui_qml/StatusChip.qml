import QtQuick

Rectangle {
    id: root
    property string status: "checking"
    property string label: ""
    implicitWidth: chipText.implicitWidth + 20
    implicitHeight: 26
    radius: 13
    color: status === "ready" ? "#dcfce7"
         : status === "checking" ? "#dbeafe"
         : status === "attention" ? "#ffedd5" : "#fee2e2"

    Text {
        id: chipText
        anchors.centerIn: parent
        text: root.label
        font.family: DesignTokens.fontFamily
        font.pixelSize: DesignTokens.fontSizeSm
        font.bold: true
        color: root.status === "ready" ? "#166534"
             : root.status === "checking" ? "#1d4ed8"
             : root.status === "attention" ? "#9a3412" : "#991b1b"
    }
}

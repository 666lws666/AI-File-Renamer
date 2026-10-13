import QtQuick
import QtQuick.Controls.Basic as Basic

Basic.Button {
    id: control
    property bool primary: false
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    font.family: DesignTokens.fontFamily
    font.pixelSize: DesignTokens.fontSizeMd
    leftPadding: 8
    rightPadding: 8
    topPadding: 6
    bottomPadding: 6
    implicitWidth: Math.max(32, implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(32, implicitContentHeight + topPadding + bottomPadding)
    palette.buttonText: !enabled ? "#94a3b8" : (primary || checked ? DesignTokens.btnPrimaryText : DesignTokens.textPrimary)
    icon.color: palette.buttonText
    background: Rectangle {
        objectName: "appButtonBackground"
        radius: 6
        color: !control.enabled ? DesignTokens.bgSecondary
             : control.primary || control.checked ? (control.down ? "#020617" : DesignTokens.btnPrimary)
             : control.down ? "#e2e8f0" : control.hovered ? "#f1f5f9" : "#ffffff"
        border.width: control.visualFocus ? 2 : 1
        border.color: control.visualFocus ? DesignTokens.accentInfo
                    : control.primary || control.checked ? color : "#cbd5e1"
    }
}

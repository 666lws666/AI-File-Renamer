import QtQuick
import QtQuick.Controls.Basic as Basic

Basic.ComboBox {
    id: control
    editable: false
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    font.family: DesignTokens.fontFamily
    font.pixelSize: DesignTokens.fontSizeMd
    implicitWidth: 160
    implicitHeight: 32
    leftPadding: 10
    rightPadding: 34
    topPadding: 6
    bottomPadding: 6
    contentItem: Text {
        text: control.displayText
        font: control.font
        color: control.enabled ? DesignTokens.textPrimary : "#94a3b8"
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    indicator: Image {
        objectName: "selectChevron"
        x: control.width - width - 10
        y: (control.height - height) / 2
        width: 16
        height: 16
        source: "icons/chevron_down.svg"
        opacity: control.enabled ? 1 : 0.4
    }
    background: Rectangle {
        radius: 6
        color: control.enabled ? "#ffffff" : DesignTokens.bgSecondary
        border.width: control.visualFocus ? 2 : 1
        border.color: control.visualFocus ? DesignTokens.accentInfo : control.hovered ? "#94a3b8" : "#cbd5e1"
    }
    delegate: Basic.ItemDelegate {
        required property int index
        width: ListView.view.width
        implicitHeight: 32
        text: control.textAt(index)
        font: control.font
        highlighted: control.highlightedIndex === index
        hoverEnabled: true
        palette.text: DesignTokens.textPrimary
        palette.highlightedText: DesignTokens.textPrimary
        background: Rectangle {
            radius: 4
            color: parent.highlighted || parent.hovered ? "#eef2f6" : "transparent"
        }
    }
    popup: Basic.Popup {
        y: control.height + 4
        width: control.width
        padding: 4
        margins: 8
        height: Math.min(contentItem.implicitHeight + 8, Math.max(40, Math.min(320, control.Window.height - 16)))
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.delegateModel
            currentIndex: control.highlightedIndex
            highlightMoveDuration: 0
            Basic.ScrollBar.vertical: Basic.ScrollBar { policy: Basic.ScrollBar.AsNeeded }
        }
        background: Rectangle {
            radius: 6
            color: "#ffffff"
            border.width: 1
            border.color: "#cbd5e1"
        }
    }
}

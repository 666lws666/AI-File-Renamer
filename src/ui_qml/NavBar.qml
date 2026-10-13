import QtQuick
import QtQuick.Controls.Basic

Rectangle {
    id: root
    width: DesignTokens.navBarWidth
    color: DesignTokens.bgSecondary
    property string currentPage: "batch"
    property string statusOverall: "checking"
    property bool statusAvailable: false
    signal pageSelected(string page)

    Column {
        anchors.top: parent.top
        anchors.topMargin: 8
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 4
        NavBtn { pageId: "batch"; iconPath: "icons/nav_batch.svg" }
        NavBtn { pageId: "watch"; iconPath: "icons/nav_watch.svg" }
        NavBtn { pageId: "templates"; iconPath: "icons/nav_templates.svg" }
    }
    Column {
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 8
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 4
        NavBtn { pageId: "status"; iconPath: "icons/nav_status.svg" }
        NavBtn { pageId: "preferences"; iconPath: "icons/nav_preferences.svg" }
    }
    Rectangle {
        anchors.right: parent.right
        width: 1; height: parent.height
        color: DesignTokens.borderLight
    }

    component NavBtn: Button {
        id: control
        property string pageId
        property url iconPath
        objectName: "nav_" + pageId
        width: root.width - 8
        height: 56
        padding: 4
        hoverEnabled: true
        focusPolicy: Qt.StrongFocus
        text: i18n.tr("nav.short." + pageId, i18n.locale)
        checked: root.currentPage === pageId
        Accessible.name: i18n.tr("nav." + pageId, i18n.locale)
        onClicked: root.pageSelected(pageId)
        Keys.onReturnPressed: root.pageSelected(pageId)
        Keys.onEnterPressed: root.pageSelected(pageId)
        contentItem: Item {
            Column {
                anchors.centerIn: parent
                width: parent.width
                spacing: 4
                Image {
                    anchors.horizontalCenter: parent.horizontalCenter
                    source: control.iconPath
                    width: 20; height: 20
                    sourceSize.width: 20; sourceSize.height: 20
                    opacity: control.checked ? 1 : 0.8
                }
                Text {
                    objectName: "navLabel_" + control.pageId
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: control.text
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: 12
                    font.weight: control.checked ? Font.DemiBold : Font.Normal
                    color: DesignTokens.textPrimary
                }
            }
        }
        background: Rectangle {
            radius: DesignTokens.radiusMd
            color: control.down ? "#dbe3ec" : control.checked ? DesignTokens.bgNavSelected
                 : control.hovered ? "#eef2f6" : "transparent"
            border.width: control.visualFocus ? 2 : 0
            border.color: DesignTokens.accentInfo
        }
        Rectangle {
            objectName: control.pageId === "status" ? "statusNavBadge" : ""
            visible: control.pageId === "status" && root.statusAvailable
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.rightMargin: 18; anchors.topMargin: 4
            width: 7; height: 7; radius: 4
            color: root.statusOverall === "ready" ? DesignTokens.accentSuccess
                 : root.statusOverall === "checking" ? DesignTokens.accentInfo
                 : root.statusOverall === "attention" ? DesignTokens.accentWarning
                 : DesignTokens.accentError
        }
    }
}

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "watchPage"
    property string pageId: "watch"
    property var ctrl: null
    color: DesignTokens.bgPrimary

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: DesignTokens.spacingXl
        spacing: DesignTokens.spacingMd

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredWidth: root.width - DesignTokens.spacingXl * 2
            ColumnLayout {
                Layout.fillWidth: true
                spacing: DesignTokens.spacingXs
                Text {
                    objectName: "watchPageTitle"
                    text: i18n.tr("watch.title")
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeXl
                    font.bold: true
                    color: DesignTokens.textPrimary
                }
                Text {
                    text: i18n.tr("watch.subtitle")
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeMd
                    color: DesignTokens.textSecondary
                }
            }
            AppButton {
                id: addButton
                objectName: "addWatchButton"
                primary: true
                text: "+ " + i18n.tr("watch.add")
                enabled: Boolean(root.ctrl && root.ctrl.available && !root.ctrl.formOpen)
                onClicked: if (root.ctrl) root.ctrl.beginCreate()
            }
        }

        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: DesignTokens.borderLight }

        Text {
            objectName: "watchUnavailableNotice"
            Layout.fillWidth: true
            visible: !root.ctrl || !root.ctrl.available
            text: i18n.tr("watch.notice.queue_unavailable")
            wrapMode: Text.WordWrap
            font.family: DesignTokens.fontFamily
            color: DesignTokens.accentError
        }

        Item {
            id: content
            Layout.fillWidth: true
            Layout.fillHeight: true

            WatchForm {
                visible: Boolean(root.ctrl && root.ctrl.formOpen)
                ctrl: root.ctrl
                anchors.top: parent.top
                anchors.left: parent.left
                width: Math.min(432, parent.width)
                height: Math.min(implicitHeight, parent.height)
            }

            Item {
                id: emptyState
                objectName: "watchEmptyState"
                visible: (!root.ctrl || root.ctrl.watchCount === 0) && (!root.ctrl || !root.ctrl.formOpen)
                anchors.fill: parent

                Canvas {
                    anchors.fill: parent
                    onPaint: {
                        var ctx = getContext("2d")
                        ctx.clearRect(0, 0, width, height)
                        ctx.strokeStyle = DesignTokens.borderLight
                        ctx.lineWidth = 1
                        ctx.setLineDash([5, 4])
                        ctx.beginPath()
                        ctx.roundedRect(0.5, 0.5, width - 1, height - 1, DesignTokens.radiusLg, DesignTokens.radiusLg)
                        ctx.stroke()
                    }
                }

                ColumnLayout {
                    anchors.centerIn: parent
                    width: Math.min(460, parent.width - 48)
                    spacing: DesignTokens.spacingMd
                    Rectangle {
                        Layout.alignment: Qt.AlignHCenter
                        width: 44; height: 44; radius: DesignTokens.radiusMd
                        color: DesignTokens.bgNavSelected
                        Image { anchors.centerIn: parent; width: 26; height: 26; source: "icons/watch_folder.svg"; fillMode: Image.PreserveAspectFit }
                    }
                    Text { Layout.fillWidth: true; text: i18n.tr("watch.empty.title"); horizontalAlignment: Text.AlignHCenter; font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeXl; font.bold: true; color: DesignTokens.textPrimary }
                    Text { Layout.fillWidth: true; text: i18n.tr("watch.empty.subtitle"); horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeMd; color: DesignTokens.textSecondary }
                    AppButton { objectName: "watchEmptyAddButton"; Layout.alignment: Qt.AlignHCenter; enabled: Boolean(root.ctrl && root.ctrl.available); text: "+ " + i18n.tr("watch.empty.action"); onClicked: if (root.ctrl) root.ctrl.beginCreate() }
                }
            }

            ListView {
                id: watchList
                objectName: "watchList"
                visible: Boolean(root.ctrl && root.ctrl.watchCount > 0 && !root.ctrl.formOpen)
                anchors.fill: parent
                clip: true
                spacing: DesignTokens.spacingSm
                model: root.ctrl ? root.ctrl.watches : []
                delegate: WatchCard {
                    required property var modelData
                    width: watchList.width
                    ctrl: root.ctrl
                    watchData: modelData
                }
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            }
        }
    }

    Rectangle {
        visible: Boolean(root.ctrl && root.ctrl.resultsOpen)
        anchors.fill: parent
        z: 40
        color: "#66000000"
        MouseArea { anchors.fill: parent; onClicked: if (root.ctrl) root.ctrl.closeResults() }
        WatchResultsPanel {
            visible: parent.visible
            ctrl: root.ctrl
            width: Math.min(680, parent.width - 64)
            height: Math.min(520, parent.height - 64)
            anchors.centerIn: parent
            z: 1
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton }
        }
    }
}

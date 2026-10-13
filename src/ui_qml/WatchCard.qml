import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    property var ctrl: null
    property var watchData: ({})
    width: parent ? parent.width : 760
    height: 108
    radius: DesignTokens.radiusLg
    color: hover.hovered ? DesignTokens.bgSecondary : DesignTokens.bgPrimary
    border.width: 1
    border.color: DesignTokens.borderLight

    function statusText(status) {
        if (status === "active") return i18n.tr("watch.status.active")
        if (status === "paused") return i18n.tr("watch.status.paused")
        if (status === "error") return i18n.tr("watch.status.error")
        if (status === "resource_paused") return i18n.tr("watch.status.resourcePaused")
        return status
    }

    HoverHandler { id: hover }

    RowLayout {
        anchors.fill: parent
        anchors.margins: DesignTokens.spacingMd
        spacing: DesignTokens.spacingMd

        Rectangle {
            Layout.preferredWidth: 42
            Layout.preferredHeight: 42
            radius: DesignTokens.radiusMd
            color: DesignTokens.bgNavSelected
            Image { anchors.centerIn: parent; width: 24; height: 24; source: "icons/watch_folder.svg"; fillMode: Image.PreserveAspectFit }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            RowLayout {
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    text: root.watchData.sourceName || ""
                    elide: Text.ElideRight
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeMd
                    font.bold: true
                    color: DesignTokens.textPrimary
                }
                Rectangle {
                    implicitWidth: statusLabel.implicitWidth + 16
                    implicitHeight: 24
                    radius: 12
                    color: root.watchData.status === "active" ? "#dcfce7"
                         : root.watchData.status === "error" ? "#fee2e2"
                         : root.watchData.status === "resource_paused" ? "#ffedd5" : "#f1f5f9"
                    Text {
                        id: statusLabel
                        anchors.centerIn: parent
                        text: root.statusText(root.watchData.status || "")
                        font.family: DesignTokens.fontFamily
                        font.pixelSize: DesignTokens.fontSizeSm
                        color: root.watchData.status === "active" ? DesignTokens.accentSuccess
                             : root.watchData.status === "error" ? DesignTokens.accentError
                             : root.watchData.status === "resource_paused" ? DesignTokens.accentWarning : DesignTokens.textSecondary
                    }
                }
            }
            Text { Layout.fillWidth: true; text: root.watchData.sourceDir || ""; elide: Text.ElideMiddle; font.family: DesignTokens.fontFamily; font.pixelSize: DesignTokens.fontSizeSm; color: DesignTokens.textSecondary }
            Text {
                Layout.fillWidth: true
                text: (root.watchData.mode === "auto_apply" ? i18n.tr("watch.mode.autoApply") : i18n.tr("watch.mode.reviewFirst"))
                      + " · " + (root.watchData.templateName || i18n.tr("watch.template.none"))
                elide: Text.ElideRight
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeSm
                color: DesignTokens.textSecondary
            }
        }

        RowLayout {
            visible: hover.hovered || root.width >= 760
            spacing: DesignTokens.spacingXs
            Button {
                objectName: "watchResultsButton"
                text: i18n.tr("watch.results.action") + (root.watchData.resultCount > 0 ? " (" + root.watchData.resultCount + ")" : "")
                onClicked: if (root.ctrl) root.ctrl.openResults(root.watchData.id)
            }
            Button {
                objectName: "watchPauseResumeButton"
                text: root.watchData.status === "active" ? i18n.tr("watch.pause") : i18n.tr("watch.resume")
                onClicked: {
                    if (!root.ctrl) return
                    if (root.watchData.status === "active") root.ctrl.pauseWatch(root.watchData.id)
                    else root.ctrl.resumeWatch(root.watchData.id)
                }
            }
            Button { objectName: "watchEditButton"; text: i18n.tr("common.edit"); onClicked: if (root.ctrl) root.ctrl.beginEdit(root.watchData.id) }
            Button { objectName: "watchDeleteButton"; text: i18n.tr("common.delete"); onClicked: if (root.ctrl) root.ctrl.removeWatch(root.watchData.id) }
        }
    }
}
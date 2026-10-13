import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root
    property string title: ""
    property string detail: ""
    property string status: "checking"
    function levelLabel(value) {
        if (value === "ready") return i18n.tr("status.level.ready", i18n.locale)
        if (value === "attention") return i18n.tr("status.level.attention", i18n.locale)
        if (value === "unavailable") return i18n.tr("status.level.unavailable", i18n.locale)
        return i18n.tr("status.level.checking", i18n.locale)
    }
    implicitHeight: 72
    radius: DesignTokens.radiusMd
    color: DesignTokens.bgSecondary
    border.width: 1
    border.color: DesignTokens.borderLight

    RowLayout {
        anchors.fill: parent
        anchors.margins: DesignTokens.spacingMd
        spacing: DesignTokens.spacingMd

        Rectangle {
            Layout.preferredWidth: 34
            Layout.preferredHeight: 34
            radius: 10
            color: root.status === "ready" ? "#dcfce7"
                 : root.status === "checking" ? "#dbeafe"
                 : root.status === "attention" ? "#ffedd5" : "#fee2e2"
            Text {
                anchors.centerIn: parent
                text: root.status === "ready" ? "✓" : root.status === "checking" ? "…" : "!"
                font.family: DesignTokens.fontFamily
                font.pixelSize: 16
                font.bold: true
                color: root.status === "ready" ? "#166534"
                     : root.status === "checking" ? "#1d4ed8"
                     : root.status === "attention" ? "#9a3412" : "#991b1b"
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 3
            Text {
                text: root.title
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                font.bold: true
                color: DesignTokens.textPrimary
            }
            Text {
                Layout.fillWidth: true
                visible: text.length > 0
                text: root.detail
                elide: Text.ElideRight
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeSm
                color: DesignTokens.textSecondary
            }
        }

        StatusChip {
            status: root.status
            label: root.levelLabel(root.status)
        }
    }
}

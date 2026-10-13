import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "fieldSorter"
    property var ctrl: null
    color: DesignTokens.bgSecondary
    border.width: 1
    border.color: DesignTokens.borderLight
    radius: DesignTokens.radiusMd
    implicitHeight: fieldColumn.implicitHeight + DesignTokens.spacingMd * 2

    Column {
        id: fieldColumn
        anchors.fill: parent
        anchors.margins: DesignTokens.spacingMd
        spacing: DesignTokens.spacingXs

        Repeater {
            model: root.ctrl ? root.ctrl.draftFields : []
            delegate: Rectangle {
                required property var modelData
                width: fieldColumn.width
                height: 32
                color: "transparent"

                RowLayout {
                    anchors.fill: parent
                    spacing: DesignTokens.spacingSm
                    CheckBox {
                        objectName: "fieldEnabled_" + modelData.dcName
                        checked: modelData.enabled
                        onToggled: if (root.ctrl) root.ctrl.setDraftFieldEnabled(modelData.dcName, checked)
                    }
                    Text {
                        objectName: "fieldLabel_" + modelData.dcName
                        Layout.fillWidth: true
                        text: i18n.tr("templates.field." + modelData.dcName, i18n.locale) + "  {" + modelData.dcName + "}"
                        font.family: DesignTokens.fontFamily
                        font.pixelSize: DesignTokens.fontSizeMd
                        color: modelData.enabled ? DesignTokens.textPrimary : DesignTokens.textSecondary
                        elide: Text.ElideRight
                    }
                    AppButton {
                        objectName: "fieldUp_" + modelData.dcName
                        text: "↑"
                        enabled: modelData.order > 1
                        implicitWidth: 30; implicitHeight: 28
                        onClicked: if (root.ctrl) root.ctrl.moveDraftField(modelData.dcName, -1)
                    }
                    AppButton {
                        objectName: "fieldDown_" + modelData.dcName
                        text: "↓"
                        enabled: root.ctrl && modelData.order < root.ctrl.draftFields.length
                        implicitWidth: 30; implicitHeight: 28
                        onClicked: if (root.ctrl) root.ctrl.moveDraftField(modelData.dcName, 1)
                    }
                }
            }
        }
    }
}

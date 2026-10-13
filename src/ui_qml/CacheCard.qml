import QtQuick; import QtQuick.Controls.Basic; import QtQuick.Layouts

// Cache card — display value and user edits are wired directly to
// SettingsController draft via ctrl. TTL is expressed in DAYS, matching
// the controller's cacheTtlDays field. The clear button calls
// ctrl.clearCache() and reflects cacheClearFinished(bool).
//
// Current-usage row (M6 contract): shows an explicit "not yet tracked"
// state when no stats service is injected — it NEVER forges 0 MB.  A stats
// service can flip usageAvailable and inject usageMb.
Rectangle {
    id: root
    property var ctrl: null
    objectName: "cacheCard"
    color: DesignTokens.bgPrimary
    radius: DesignTokens.radiusLg
    border.width: 1
    border.color: DesignTokens.borderLight
    implicitWidth: 400
    implicitHeight: cacheColumn.implicitHeight + DesignTokens.spacingXl * 2

    property string clearStatus: ""  // "", "cleared", "error"

    // Injectable stats — no service in the M6 slice: unavailable by default.
    property bool usageAvailable: false
    property int usageMb: 0

    Connections {
        target: root.ctrl
        function onCacheClearFinished(ok) {
            root.clearStatus = ok ? "cleared" : "error"
        }
    }

    ColumnLayout {
        id: cacheColumn
        anchors.fill: parent
        anchors.margins: DesignTokens.spacingXl
        spacing: DesignTokens.spacingMd

        Text {
            text: i18n.tr("prefs.cache.title", i18n.locale)
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeLg
            font.bold: true
            color: DesignTokens.textPrimary
        }

        // --- Enable Cache Toggle ---
        RowLayout {
            Layout.fillWidth: true
            spacing: DesignTokens.spacingMd
            Text {
                text: i18n.tr("prefs.cache.enabled", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
                Layout.fillWidth: true
            }
            Switch {
                objectName: "cacheEnabledSwitch"
                checked: root.ctrl ? root.ctrl.cacheEnabled : false
                onCheckedChanged: {
                    if (root.ctrl) root.ctrl.cacheEnabled = checked
                }
                Layout.alignment: Qt.AlignVCenter
            }
        }

        // --- Capacity Limit (MB) ---
        RowLayout {
            Layout.fillWidth: true
            spacing: DesignTokens.spacingMd
            Text {
                text: i18n.tr("prefs.cache.maxSize", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
                Layout.fillWidth: true
            }
            SpinBox {
                objectName: "cacheMaxMbSpin"
                Layout.preferredWidth: 140
                from: 10
                to: 10000
                stepSize: 50
                editable: true
                value: root.ctrl ? root.ctrl.cacheMaxMb : 500
                onValueChanged: {
                    if (root.ctrl) root.ctrl.cacheMaxMb = value
                }
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
            }
        }

        // --- TTL (days) ---
        RowLayout {
            Layout.fillWidth: true
            spacing: DesignTokens.spacingMd
            Text {
                text: i18n.tr("prefs.cache.ttl", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
                Layout.fillWidth: true
            }
            SpinBox {
                objectName: "cacheTtlDaysSpin"
                Layout.preferredWidth: 140
                from: 1
                to: 90
                editable: true
                value: root.ctrl ? root.ctrl.cacheTtlDays : 7
                onValueChanged: {
                    if (root.ctrl) root.ctrl.cacheTtlDays = value
                }
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
            }
        }

        // --- Current Usage (M6 contract) ---
        RowLayout {
            objectName: "cacheUsageRow"
            Layout.fillWidth: true
            spacing: DesignTokens.spacingMd
            Text {
                text: i18n.tr("prefs.cache.currentUsage", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textPrimary
                Layout.fillWidth: true
            }
            Text {
                objectName: "cacheUsageText"
                text: root.usageAvailable
                    ? root.usageMb + " MB"
                    : i18n.tr("prefs.cache.currentUsage.unavailable", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: root.usageAvailable ? DesignTokens.textPrimary : DesignTokens.textSecondary
            }
        }

        // Divider
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: DesignTokens.borderLight
        }

        // --- Clear Cache Button ---
        AppButton {
            objectName: "cacheClearBtn"
            text: {
                if (root.clearStatus === "cleared") return i18n.tr("prefs.cache.clear.success", i18n.locale)
                if (root.clearStatus === "error") return i18n.tr("prefs.cache.clear.failure", i18n.locale)
                return i18n.tr("prefs.cache.clear", i18n.locale)
            }
            onClicked: {
                if (root.ctrl) root.ctrl.clearCache()
            }
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeSm
        }
    }
}

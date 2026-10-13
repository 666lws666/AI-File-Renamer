import QtQuick; import QtQuick.Controls.Basic; import QtQuick.Layouts

// Usage card — shows NON-monetary usage only: provider, request count,
// input tokens, output tokens.  No monetary data of any kind is rendered.
// No real usage-reading service exists in the M6 slice:
// usageAvailable=false renders an explicit "unavailable" state instead of
// manufacturing fake data; a future injectable service flips
// usageAvailable and populates usageData:
//   [{provider: string, requests: int, tokensIn: int, tokensOut: int}]
//
// Column geometry (M6 correction): the header and every data row are built
// from ONE shared set of column widths — a plain Row with explicit widths,
// so the four column left edges are identical between header and rows.
// The provider column absorbs the leftover width (elided when narrow); the
// three numeric columns are stable.
Rectangle {
    id: root
    property var ctrl: null
    objectName: "usageCard"
    color: DesignTokens.bgPrimary
    radius: DesignTokens.radiusLg
    border.width: 1
    border.color: DesignTokens.borderLight
    implicitWidth: 480
    implicitHeight: usageColumn.implicitHeight + DesignTokens.spacingXl * 2

    // No real usage service yet — explicit unavailable state (never fake data).
    property bool usageAvailable: false
    property var usageData: []  // [{provider, requests, tokensIn, tokensOut}]

    // ── Shared column geometry (header AND rows use exactly these) ──
    property int colRequestsWidth: 110
    property int colTokensInWidth: 110
    property int colTokensOutWidth: 110
    property int colSpacing: 12

    function providerColWidth(total) {
        var fixed = root.colRequestsWidth + root.colTokensInWidth
            + root.colTokensOutWidth + root.colSpacing * 3
        return Math.max(80, total - fixed)
    }

    // The table area is the card content width (card minus the column
    // margins) — derived from root.width so header and rows share ONE
    // stable value that never depends on a layout pass.
    function tableWidth() {
        return root.width - DesignTokens.spacingXl * 2
    }

    // Test helpers (Repeater delegates live outside the QObject tree in
    // Qt 6.11 — the runtime tests read rows through these functions).
    function usageRowCount() {
        return usageRows.count
    }
    function usageRowField(index, field) {
        var item = usageRows.itemAt(index)
        if (!item) return ""
        return item.fieldValue(field)
    }

    // Column-geometry helpers for tests: x offsets of a column in the
    // header and in a data row are both measured in the records block's
    // coordinate space, so they are directly comparable (<= 1 px allowed).
    function headerTextItem(field) {
        if (field === "provider") return headerProviderText
        if (field === "requests") return headerRequestsText
        if (field === "tokensIn") return headerTokensInText
        if (field === "tokensOut") return headerTokensOutText
        return null
    }
    function headerColumnX(field) {
        var t = root.headerTextItem(field)
        return t ? headerRow.x + t.x : -1
    }
    function headerColumnWidth(field) {
        var t = root.headerTextItem(field)
        return t ? t.width : -1
    }
    function headerColumnRight(field) {
        return root.headerColumnX(field) + root.headerColumnWidth(field)
    }
    function rowColumnX(index, field) {
        var item = usageRows.itemAt(index)
        if (!item) return -1
        return item.rowColumnX(field)
    }
    function rowColumnWidth(index, field) {
        var item = usageRows.itemAt(index)
        if (!item) return -1
        return item.rowColumnWidth(field)
    }
    function rowColumnContentWidth(index, field) {
        var item = usageRows.itemAt(index)
        if (!item) return -1
        return item.rowColumnContentWidth(field)
    }

    ColumnLayout {
        id: usageColumn
        anchors.fill: parent
        anchors.margins: DesignTokens.spacingXl
        spacing: DesignTokens.spacingMd

        Text {
            text: i18n.tr("prefs.usage.title", i18n.locale)
            font.family: DesignTokens.fontFamily
            font.pixelSize: DesignTokens.fontSizeLg
            font.bold: true
            color: DesignTokens.textPrimary
        }

        // Unavailable state
        Rectangle {
            visible: !root.usageAvailable
            Layout.fillWidth: true
            Layout.preferredHeight: 80
            color: DesignTokens.bgSecondary
            radius: DesignTokens.radiusMd
            Text {
                id: usageUnavailableText
                objectName: "usageUnavailableText"
                anchors.centerIn: parent
                text: i18n.tr("prefs.usage.unavailable", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textSecondary
            }
        }

        // Empty state (service connected but no records yet)
        Rectangle {
            visible: root.usageAvailable && (!root.usageData || root.usageData.length === 0)
            Layout.fillWidth: true
            Layout.preferredHeight: 80
            color: DesignTokens.bgSecondary
            radius: DesignTokens.radiusMd
            Text {
                id: usageEmptyText
                objectName: "usageEmptyText"
                anchors.centerIn: parent
                text: i18n.tr("prefs.usage.empty", i18n.locale)
                font.family: DesignTokens.fontFamily
                font.pixelSize: DesignTokens.fontSizeMd
                color: DesignTokens.textSecondary
            }
        }

        // Records (non-monetary usage list)
        ColumnLayout {
            id: usageRecordsBlock
            visible: root.usageAvailable && root.usageData && root.usageData.length !== 0
            Layout.fillWidth: true
            spacing: DesignTokens.spacingSm

            // Header row — same column widths as every data row.
            Row {
                id: headerRow
                width: root.tableWidth()
                spacing: root.colSpacing
                Text {
                    id: headerProviderText
                    objectName: "usageHeaderProvider"
                    width: root.providerColWidth(headerRow.width)
                    text: i18n.tr("prefs.usage.provider", i18n.locale)
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeSm
                    font.bold: true
                    color: DesignTokens.textSecondary
                    elide: Text.ElideRight
                }
                Text {
                    id: headerRequestsText
                    objectName: "usageHeaderRequests"
                    width: root.colRequestsWidth
                    text: i18n.tr("prefs.usage.requests", i18n.locale)
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeSm
                    font.bold: true
                    color: DesignTokens.textSecondary
                }
                Text {
                    id: headerTokensInText
                    objectName: "usageHeaderTokensIn"
                    width: root.colTokensInWidth
                    text: i18n.tr("prefs.usage.tokensIn", i18n.locale)
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeSm
                    font.bold: true
                    color: DesignTokens.textSecondary
                }
                Text {
                    id: headerTokensOutText
                    objectName: "usageHeaderTokensOut"
                    width: root.colTokensOutWidth
                    text: i18n.tr("prefs.usage.tokensOut", i18n.locale)
                    font.family: DesignTokens.fontFamily
                    font.pixelSize: DesignTokens.fontSizeSm
                    font.bold: true
                    color: DesignTokens.textSecondary
                }
            }

            Repeater {
                id: usageRows
                objectName: "usageRowsRepeater"
                Layout.fillWidth: true
                model: root.usageData
                delegate: Rectangle {
                    id: usageRowDelegate
                    width: root.tableWidth()
                    height: 28
                    radius: DesignTokens.radiusSm
                    color: index % 2 === 0 ? DesignTokens.bgPrimary : DesignTokens.bgSecondary

                    function fieldValue(field) {
                        var t = rowTextItem(field)
                        return t ? t.text : ""
                    }
                    function rowColumnX(field) {
                        var t = rowTextItem(field)
                        return t ? rowRow.x + t.x : -1
                    }
                    function rowColumnWidth(field) {
                        var t = rowTextItem(field)
                        return t ? t.width : -1
                    }
                    function rowColumnContentWidth(field) {
                        var t = rowTextItem(field)
                        return t ? t.contentWidth : -1
                    }
                    function rowTextItem(field) {
                        if (field === "provider") return providerText
                        if (field === "requests") return requestsText
                        if (field === "tokensIn") return tokensInText
                        if (field === "tokensOut") return tokensOutText
                        return null
                    }

                    Row {
                        id: rowRow
                        anchors.fill: parent
                        spacing: root.colSpacing
                        Text {
                            id: providerText
                            objectName: "usageProviderText"
                            width: root.providerColWidth(rowRow.width)
                            text: modelData.provider !== undefined ? String(modelData.provider) : ""
                            font.family: DesignTokens.fontFamily
                            font.pixelSize: DesignTokens.fontSizeSm
                            color: DesignTokens.textPrimary
                            elide: Text.ElideRight
                        }
                        Text {
                            id: requestsText
                            objectName: "usageRequestsText"
                            width: root.colRequestsWidth
                            text: modelData.requests !== undefined ? String(modelData.requests) : ""
                            font.family: DesignTokens.fontFamily
                            font.pixelSize: DesignTokens.fontSizeSm
                            color: DesignTokens.textPrimary
                        }
                        Text {
                            id: tokensInText
                            objectName: "usageTokensInText"
                            width: root.colTokensInWidth
                            text: modelData.tokensIn !== undefined ? String(modelData.tokensIn) : ""
                            font.family: DesignTokens.fontFamily
                            font.pixelSize: DesignTokens.fontSizeSm
                            color: DesignTokens.textPrimary
                        }
                        Text {
                            id: tokensOutText
                            objectName: "usageTokensOutText"
                            width: root.colTokensOutWidth
                            text: modelData.tokensOut !== undefined ? String(modelData.tokensOut) : ""
                            font.family: DesignTokens.fontFamily
                            font.pixelSize: DesignTokens.fontSizeSm
                            color: DesignTokens.textPrimary
                        }
                    }
                }
            }
        }
    }
}

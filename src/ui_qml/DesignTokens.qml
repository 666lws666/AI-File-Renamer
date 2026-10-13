pragma Singleton
import QtQuick

QtObject {
    // Window
    readonly property int baseWindowWidth: 1000
    readonly property int baseWindowHeight: 700
    readonly property int minimumWindowWidth: 900
    readonly property int minimumWindowHeight: 640
    readonly property int titleBarHeight: 32
    readonly property int navBarWidth: 80
    readonly property int taskCardHeight: 70

    // Spacing
    readonly property int spacingXs: 4
    readonly property int spacingSm: 8
    readonly property int spacingMd: 12
    readonly property int spacingLg: 16
    readonly property int spacingXl: 24

    // Radius
    readonly property int radiusSm: 4
    readonly property int radiusMd: 8
    readonly property int radiusLg: 12

    // Colors — Light theme
    readonly property color bgPrimary: "#ffffff"
    readonly property color bgSecondary: "#f8fafc"
    readonly property color bgNavSelected: "#e8ecf0"
    readonly property color borderLight: "#e2e8f0"
    readonly property int windowBorderWidth: 1
    readonly property color windowBorderColor: "#94a3b8"
    readonly property color textPrimary: "#1e293b"
    readonly property color textSecondary: "#64748b"
    readonly property color btnPrimary: "#0f172a"
    readonly property color btnPrimaryText: "#ffffff"
    readonly property color accentSuccess: "#16a34a"
    readonly property color accentError: "#dc2626"
    readonly property color accentWarning: "#ea580c"
    readonly property color accentInfo: "#2563eb"

    // Typography
    readonly property string fontFamily: "Microsoft YaHei UI"
    readonly property int fontSizeSm: 11
    readonly property int fontSizeMd: 13
    readonly property int fontSizeLg: 15
    readonly property int fontSizeXl: 18

    // Interactive
    readonly property int minClickSize: 24
}

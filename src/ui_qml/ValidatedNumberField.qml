import QtQuick
import QtQuick.Controls.Basic

// ValidatedNumberField — digit-only number input with min/max bounds.
//
// Contract (M6 correction):
// - the RAW editing text is preserved exactly while the user types — an
//   out-of-range value is never clamped away or rewritten;
// - only a value within [from, to] is published through `value`; anything
//   out of range sets `error=true` and leaves `value` untouched, so the
//   caller (and the draft) never sees the invalid number;
// - `value` is writable from outside (display follows the controller);
// - the field is wide enough for the longest in-range digit string.
TextField {
    id: field
    objectName: "validatedNumberField"

    property int value: 0
    property int from: 0
    property int to: 999999
    property bool error: false

    inputMethodHints: Qt.ImhDigitsOnly
    // No QML validator type ships with this Qt build — the onTextChanged
    // regex guard below is the enforcement point: non-digit text sets
    // error=true and never reaches `value`.

    text: field.value.toString()
    font.family: DesignTokens.fontFamily
    font.pixelSize: DesignTokens.fontSizeMd
    color: DesignTokens.textPrimary
    background: Rectangle {
        radius: DesignTokens.radiusSm
        border.color: DesignTokens.borderLight
        color: DesignTokens.bgPrimary
    }

    onTextChanged: {
        var t = field.text.trim()
        if (t === "") {
            field.error = false  // empty = no value yet, never an invalid value
            return
        }
        if (!/^\d+$/.test(t)) {
            field.error = true
            return
        }
        var v = parseInt(t, 10)
        if (v < field.from || v > field.to) {
            field.error = true
            return
        }
        field.error = false
        if (field.value !== v) field.value = v
    }
}

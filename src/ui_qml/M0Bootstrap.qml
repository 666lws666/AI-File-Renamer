import QtQuick

// M0 QML Bootstrap — minimal window for technical verification
// Not a production Shell. M1 replaces this with the full custom Shell.
Rectangle {
    width: 400
    height: 300
    color: "#ffffff"

    Text {
        anchors.centerIn: parent
        text: "序匣 M0 OK"
        font.pixelSize: 18
        color: "#1e293b"
    }
}

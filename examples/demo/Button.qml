import QtQuick

Rectangle {
    id: root
    property string label
    property color accent: "#4f8cff"
    signal clicked

    width: 56
    height: 40
    radius: 8
    color: mouse.pressed ? Qt.darker(accent, 1.4) : accent
    Behavior on color { ColorAnimation { duration: 90 } }

    Text {
        anchors.centerIn: parent
        text: root.label
        color: "white"
        font.pixelSize: 22
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        onClicked: root.clicked()
    }
}

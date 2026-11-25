import QtQuick

Rectangle {
    id: root
    property bool checked: false
    signal toggled(bool on)

    width: 52
    height: 28
    radius: 14
    color: "#596277"

    Rectangle {
        id: knob
        x: 3; y: 3
        width: 22; height: 22
        radius: 11
        color: "white"
        Behavior on x { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
    }
    Behavior on color { ColorAnimation { duration: 180 } }
    MouseArea {
        anchors.fill: parent
        onClicked: {
            root.checked = !root.checked
            root.toggled(root.checked)
        }
    }
    states: [
        State {
            name: "on"
            when: root.checked
            PropertyChanges { target: knob; x: 27 }
            PropertyChanges { target: root; color: "#4caf50" }
        }
    ]
}

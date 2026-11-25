import QtQuick

Rectangle {
    id: root
    property int value: 0      // 0..100

    height: 12
    radius: 6
    color: "#1e2430"

    Rectangle {
        width: Math.max(12, root.width * root.value / 100)
        height: root.height
        radius: 6
        color: "#4f8cff"
    }
}

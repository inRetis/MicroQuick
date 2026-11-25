import QtQuick

// MicroQuick demo for the M5Stack Core2 (320x240 capacitive touch screen).
// Reuses the Button, Switch and ProgressBar components of examples/demo.
Rectangle {
    id: root
    width: 320
    height: 240
    color: "#1e2430"

    property int count: 0
    property int seconds: 0
    property int page: 0
    property int added: 0

    Component.onCompleted: console.log("MicroQuick on M5Stack Core2")

    // ------------------------------------------------------------ header
    Image {
        id: logo
        source: "../demo/images/logo.png"
        x: 8; y: 6
        width: 24; height: 24
    }
    Text {
        x: 38
        anchors.verticalCenter: logo.verticalCenter
        text: "MicroQuick"
        color: "white"
        font.pixelSize: 16
    }
    Item {
        x: 128; y: 4; width: 186; height: 28
        Rectangle {
            width: 62; height: 28
            radius: 7
            color: "#3d4659"
            x: root.page * 62
            Behavior on x { SpringAnimation { spring: 4; damping: 0.35 } }
        }
        Row {
            Repeater {
                model: ["Controls", "Sensors", "Tasks"]
                delegate: Text {
                    width: 62; height: 28
                    text: modelData
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    color: root.page === index ? "white" : "#9aa4b8"
                    font.pixelSize: 12
                    MouseArea { anchors.fill: parent; onClicked: root.page = index }
                }
            }
        }
    }

    // ------------------------------------------------------------ pages
    Item {
        x: 0; y: 38; width: 320; height: 168
        clip: true

        Item {
            id: pages
            x: -root.page * 320
            width: 960; height: 168
            Behavior on x { NumberAnimation { duration: 300; easing.type: Easing.InOutCubic } }

            // ===== page 1: controls
            Rectangle {
                x: 8; y: 4; width: 148; height: 160
                radius: 10
                color: "#2b3242"
                border.width: 1
                border.color: "#3d4659"
                Text { x: 10; y: 8; text: "Counter"; color: "#9aa4b8"; font.pixelSize: 12 }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 28
                    text: count
                    color: count >= 10 ? "#ffb347" : "white"
                    font.pixelSize: 40
                    Behavior on color { ColorAnimation { duration: 300 } }
                }
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 12
                    spacing: 6
                    Button { width: 40; height: 36; label: "-"; onClicked: count = Math.max(0, count - 1) }
                    Button { width: 40; height: 36; label: "+"; accent: "#4caf50"; onClicked: count++ }
                    Button { width: 40; height: 36; label: "0"; accent: "#e05252"; onClicked: count = 0 }
                }
            }
            Rectangle {
                x: 164; y: 4; width: 148; height: 160
                radius: 10
                color: "#2b3242"
                border.width: 1
                border.color: "#3d4659"
                Text { x: 10; y: 12; text: "Turbo"; color: "white"; font.pixelSize: 14 }
                Switch { id: turbo; x: 86; y: 8 }
                Text {
                    x: 10; y: 54
                    text: "Progress: " + progress.value + " %"
                    color: "#9aa4b8"
                    font.pixelSize: 12
                }
                ProgressBar { id: progress; x: 10; y: 76; width: 128 }
                Text {
                    x: 10; y: 100; width: 128
                    text: turbo.checked ? "Fast refresh (40 ms) running on the ESP32"
                                        : "Normal refresh (150 ms) running on the ESP32"
                    wrapMode: Text.WordWrap
                    color: turbo.checked ? "#4caf50" : "#9aa4b8"
                    font.pixelSize: 12
                }
            }

            // ===== page 2: sensors
            Rectangle {
                x: 328; y: 4; width: 304; height: 160
                radius: 10
                color: "#2b3242"
                border.width: 1
                border.color: "#3d4659"
                ListView {
                    id: sensors
                    x: 6; y: 6; width: 292; height: 148
                    clip: true
                    spacing: 2
                    model: ListModel {
                        ListElement { name: "Temperature"; value: 21.5; unit: "°C"; tint: "#ff8a65" }
                        ListElement { name: "Humidity"; value: 48; unit: "%"; tint: "#4fc3f7" }
                        ListElement { name: "Pressure"; value: 1013; unit: "hPa"; tint: "#b39ddb" }
                        ListElement { name: "CO2"; value: 612; unit: "ppm"; tint: "#aed581" }
                        ListElement { name: "Light"; value: 340; unit: "lx"; tint: "#ffd54f" }
                        ListElement { name: "Noise"; value: 42; unit: "dB"; tint: "#f06292" }
                        ListElement { name: "Battery"; value: 87; unit: "%"; tint: "#81c784" }
                        ListElement { name: "Wind"; value: 12; unit: "km/h"; tint: "#90a4ae" }
                    }
                    highlight: Rectangle { radius: 6; color: "#3d4659" }
                    delegate: Item {
                        width: 292; height: 34
                        Rectangle { x: 10; y: 13; width: 8; height: 8; radius: 4; color: tint }
                        Text {
                            x: 26; height: 34
                            verticalAlignment: Text.AlignVCenter
                            text: name
                            color: "white"
                            font.pixelSize: 14
                        }
                        Text {
                            width: 282; height: 34
                            horizontalAlignment: Text.AlignRight
                            verticalAlignment: Text.AlignVCenter
                            text: value + " " + unit
                            color: ListView.isCurrentItem ? tint : "#9aa4b8"
                            font.pixelSize: 14
                        }
                        MouseArea { anchors.fill: parent; onClicked: sensors.currentIndex = index }
                    }
                }
            }

            // ===== page 3: tasks
            Rectangle {
                x: 648; y: 4; width: 200; height: 160
                radius: 10
                color: "#2b3242"
                border.width: 1
                border.color: "#3d4659"
                ListView {
                    id: todoList
                    x: 6; y: 6; width: 188; height: 148
                    clip: true
                    model: todoModel
                    highlight: Rectangle { radius: 6; color: "#3d4659" }
                    section.property: "group"
                    section.delegate: Text {
                        width: 188; height: 18
                        text: section
                        color: "#ffb347"
                        font.pixelSize: 12
                        verticalAlignment: Text.AlignBottom
                    }
                    delegate: Item {
                        width: 188; height: 28
                        Rectangle {
                            x: 4; y: 7; width: 14; height: 14; radius: 4
                            color: done ? "#4caf50" : "transparent"
                            border.width: 2
                            border.color: done ? "#4caf50" : "#9aa4b8"
                            Behavior on color { ColorAnimation { duration: 150 } }
                        }
                        // a wide hit area for fingers: the left part toggles, the rest selects
                        MouseArea {
                            width: 34; height: 28
                            onClicked: todoModel.setProperty(index, "done", !done)
                        }
                        Text {
                            x: 26; width: 158; height: 28
                            verticalAlignment: Text.AlignVCenter
                            text: title
                            elide: Text.ElideRight
                            color: done ? "#5d6680" : "white"
                            font.pixelSize: 14
                        }
                        MouseArea { x: 34; width: 154; height: 28; onClicked: todoList.currentIndex = index }
                    }
                }
            }
            Rectangle {
                x: 856; y: 4; width: 96; height: 160
                radius: 10
                color: "#2b3242"
                border.width: 1
                border.color: "#3d4659"
                Loader {
                    x: 8; y: 10
                    sourceComponent: todoModel.count > 0 ? statsView : emptyView
                }
                Column {
                    x: 8; y: 66
                    spacing: 8
                    Button { width: 80; height: 36; label: "+"; accent: "#4caf50"; onClicked: root.addTask() }
                    Button {
                        width: 80; height: 36; label: "×"; accent: "#e05252"
                        onClicked: if (todoModel.count > 0) todoModel.remove(todoList.currentIndex)
                    }
                }
            }
        }
    }

    ListModel {
        id: todoModel
        capacity: 16
        ListElement { title: "Connect the display"; group: "Hardware"; done: true }
        ListElement { title: "Flash the Core2"; group: "Hardware"; done: false }
        ListElement { title: "Write the QML"; group: "Software"; done: true }
        ListElement { title: "Measure RAM usage"; group: "Software"; done: false }
    }
    function addTask() {
        added++
        todoModel.append({title: "New task " + added, group: "Added", done: false})
        todoList.currentIndex = todoModel.count - 1
        todoList.positionViewAtIndex(todoModel.count - 1, ListView.End)
    }
    function doneCount() {
        var n = 0
        for (var i = 0; i < todoModel.count; i++)
            if (todoModel.get(i).done) n++
        return n
    }
    Component {
        id: statsView
        Text {
            width: 80
            text: root.doneCount() + " / " + todoModel.count + " done"
            wrapMode: Text.WordWrap
            color: "white"
            font.pixelSize: 14
        }
    }
    Component {
        id: emptyView
        Text { width: 80; text: "Nothing to do!"; wrapMode: Text.WordWrap; color: "#4caf50"; font.pixelSize: 14 }
    }

    // ------------------------------------------------------------ footer
    Row {
        anchors.horizontalCenter: parent.horizontalCenter
        y: 210
        spacing: 6
        Repeater {
            model: 3
            delegate: Rectangle {
                width: index === root.page ? 16 : 6
                height: 6
                radius: 3
                color: index === root.page ? "white" : "#5d6680"
                Behavior on width { NumberAnimation { duration: 250 } }
            }
        }
    }
    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 4
        text: "Uptime " + seconds + " s • ESP32 • no malloc"
        color: "#5d6680"
        font.pixelSize: 12
    }

    Timer {
        interval: turbo.checked ? 40 : 150
        running: true
        repeat: true
        onTriggered: progress.value = (progress.value + 1) % 101
    }
    Timer {
        interval: 1000
        running: true
        repeat: true
        onTriggered: seconds++
    }
}

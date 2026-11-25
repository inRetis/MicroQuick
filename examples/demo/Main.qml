import QtQuick

// MicroQuick demo: 480x272 (typical STM32 Discovery board display).
// Page 1: controls (buttons, switch, timers). Page 2: sensor ListView.
// Page 3: tasks (editable ListModel, sections, highlight, Loader).
Rectangle {
    id: root
    width: 480
    height: 272
    color: "#1e2430"

    property int count: 0
    property int seconds: 0
    property int page: 0
    // sensor selected in the list
    property string selName: "Temperature"
    property real selValue: 21.5
    property string selUnit: "°C"
    property string selTint: "#ff8a65"

    onCountChanged: {
        if (count > 0 && count % 5 == 0)
            console.log("counter =", count)
    }
    Component.onCompleted: console.log("MicroQuick demo started")

    // ------------------------------------------------------------ header
    Image {
        id: logo
        source: "images/logo.png"
        x: 16
        y: 10
    }
    Text {
        anchors.left: logo.right
        anchors.leftMargin: 10
        anchors.verticalCenter: logo.verticalCenter
        text: "MicroQuick"
        color: "white"
        font.pixelSize: 22
    }

    // tabs with an animated highlight
    Item {
        id: tabs
        x: 216; y: 12; width: 252; height: 32
        Rectangle {
            width: 84; height: 32
            radius: 8
            color: "#3d4659"
            x: root.page * 84
            Behavior on x { SpringAnimation { spring: 4; damping: 0.35 } }
        }
        Row {
            Repeater {
                model: ["Controls", "Sensors", "Tasks"]
                delegate: Text {
                    width: 84; height: 32
                    text: modelData
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    color: root.page === index ? "white" : "#9aa4b8"
                    font.pixelSize: 14
                    MouseArea { anchors.fill: parent; onClicked: root.page = index }
                }
            }
        }
    }

    // ------------------------------------------------------------ pages
    Item {
        id: viewport
        x: 0; y: 56; width: 480; height: 176
        clip: true

        Item {
            id: pages
            x: -root.page * 480
            width: 1440; height: 176
            Behavior on x { NumberAnimation { duration: 350; easing.type: Easing.InOutCubic } }

            // ===== page 1: controls
            Rectangle {
                x: 16; y: 8; width: 216; height: 160
                radius: 12
                color: "#2b3242"
                border.width: 1
                border.color: "#3d4659"

                Text { x: 16; y: 12; text: "Counter"; color: "#9aa4b8"; font.pixelSize: 14 }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 34
                    text: count
                    color: count >= 10 ? "#ffb347" : "white"
                    font.pixelSize: 40
                    Behavior on color { ColorAnimation { duration: 300 } }
                }
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 16
                    spacing: 10
                    Button { label: "-"; onClicked: count = Math.max(0, count - 1) }
                    Button { id: plus; label: "+"; accent: "#4caf50"; onClicked: count++ }
                    Button { label: "0"; accent: "#e05252"; onClicked: count = 0 }
                }
            }
            Rectangle {
                x: 248; y: 8; width: 216; height: 160
                radius: 12
                color: "#2b3242"
                border.width: 1
                border.color: "#3d4659"

                Text { x: 16; y: 16; text: "Turbo mode"; color: "white"; font.pixelSize: 16 }
                Switch { id: turbo; x: 148; y: 12 }
                Text {
                    x: 16; y: 60
                    text: "Progress: " + progress.value + " %"
                    color: "#9aa4b8"
                    font.pixelSize: 14
                }
                ProgressBar { id: progress; x: 16; y: 86; width: 184 }
                Text {
                    x: 16; y: 116
                    text: turbo.checked ? "Fast (40 ms)" : "Normal (150 ms)"
                    color: turbo.checked ? "#4caf50" : "#9aa4b8"
                    font.pixelSize: 14
                }
            }

            // ===== page 2: sensors
            Rectangle {
                x: 496; y: 8; width: 216; height: 160
                radius: 12
                color: "#2b3242"
                border.width: 1
                border.color: "#3d4659"

                ListView {
                    id: sensors
                    x: 8; y: 8; width: 200; height: 144
                    clip: true
                    spacing: 4
                    model: ListModel {
                        ListElement { name: "Temperature"; value: 21.5; unit: "°C"; tint: "#ff8a65" }
                        ListElement { name: "Humidity"; value: 48; unit: "%"; tint: "#4fc3f7" }
                        ListElement { name: "Pressure"; value: 1013; unit: "hPa"; tint: "#b39ddb" }
                        ListElement { name: "CO2"; value: 612; unit: "ppm"; tint: "#aed581" }
                        ListElement { name: "Light"; value: 340; unit: "lx"; tint: "#ffd54f" }
                        ListElement { name: "Noise"; value: 42; unit: "dB"; tint: "#f06292" }
                        ListElement { name: "Battery"; value: 87; unit: "%"; tint: "#81c784" }
                        ListElement { name: "Wind"; value: 12; unit: "km/h"; tint: "#90a4ae" }
                        ListElement { name: "Flow"; value: 3.2; unit: "L/min"; tint: "#4dd0e1" }
                    }
                    delegate: Rectangle {
                        width: sensors.width
                        height: 32
                        radius: 6
                        color: root.selName === name ? "#3d4659" : "#2b3242"
                        Rectangle {
                            x: 10; y: 12; width: 8; height: 8; radius: 4
                            color: tint
                        }
                        Text {
                            x: 26; height: 32
                            verticalAlignment: Text.AlignVCenter
                            text: name
                            color: "white"
                            font.pixelSize: 14
                        }
                        Text {
                            x: 0; width: 190; height: 32
                            horizontalAlignment: Text.AlignRight
                            verticalAlignment: Text.AlignVCenter
                            text: value + " " + unit
                            color: "#9aa4b8"
                            font.pixelSize: 14
                        }
                        MouseArea {
                            anchors.fill: parent
                            onClicked: {
                                root.selName = name
                                root.selValue = value
                                root.selUnit = unit
                                root.selTint = tint
                            }
                        }
                    }
                }
            }
            Rectangle {
                x: 728; y: 8; width: 216; height: 160
                radius: 12
                color: "#2b3242"
                border.width: 1
                border.color: "#3d4659"

                Text { x: 16; y: 14; text: root.selName; color: "#9aa4b8"; font.pixelSize: 16 }
                Text {
                    x: 16; y: 44
                    text: root.selValue + " " + root.selUnit
                    color: root.selTint
                    font.pixelSize: 40
                    Behavior on color { ColorAnimation { duration: 400 } }
                }
                // pulsing "live" indicator
                Rectangle {
                    id: dot
                    x: 16; y: 128; width: 10; height: 10; radius: 5
                    color: "#4caf50"
                    SequentialAnimation on opacity {
                        loops: Animation.Infinite
                        NumberAnimation { to: 0.2; duration: 600; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 1.0; duration: 600; easing.type: Easing.InOutSine }
                    }
                }
                Text {
                    x: 34; y: 124
                    text: "live • " + sensors.count + " sensors"
                    color: "#5d6680"
                    font.pixelSize: 14
                }
            }

            // ===== page 3: tasks (editable ListModel, sections, highlight, Loader)
            Rectangle {
                x: 976; y: 8; width: 216; height: 160
                radius: 12
                color: "#2b3242"
                border.width: 1
                border.color: "#3d4659"

                ListView {
                    id: todoList
                    x: 8; y: 8; width: 200; height: 144
                    clip: true
                    model: todoModel
                    highlight: Rectangle { radius: 6; color: "#3d4659" }
                    section.property: "group"
                    section.delegate: Text {
                        width: 200; height: 20
                        text: section
                        color: "#ffb347"
                        font.pixelSize: 12
                        verticalAlignment: Text.AlignBottom
                    }
                    delegate: Item {
                        width: 200; height: 26
                        Rectangle {
                            x: 6; y: 6; width: 14; height: 14; radius: 4
                            color: done ? "#4caf50" : "transparent"
                            border.width: 2
                            border.color: done ? "#4caf50" : "#9aa4b8"
                            Behavior on color { ColorAnimation { duration: 150 } }
                            MouseArea { anchors.fill: parent; onClicked: todoModel.setProperty(index, "done", !done) }
                        }
                        Text {
                            x: 28; width: 166; height: 26
                            verticalAlignment: Text.AlignVCenter
                            text: title
                            elide: Text.ElideRight
                            color: done ? "#5d6680" : "white"
                            font.pixelSize: 14
                        }
                        MouseArea { x: 26; width: 174; height: 26; onClicked: todoList.currentIndex = index }
                    }
                }
            }
            Rectangle {
                x: 1208; y: 8; width: 216; height: 160
                radius: 12
                color: "#2b3242"
                border.width: 1
                border.color: "#3d4659"

                Text {
                    x: 12; y: 10; width: 192
                    text: "Tap a box to check it, a row to select it. \"+\" adds a task, \"×\" deletes the selected one."
                    wrapMode: Text.WordWrap
                    maximumLineCount: 3
                    elide: Text.ElideRight
                    color: "#9aa4b8"
                    font.pixelSize: 12
                }
                Loader {
                    x: 12; y: 70
                    sourceComponent: todoModel.count > 0 ? statsView : emptyView
                }
                Row {
                    x: 12; y: 108
                    spacing: 10
                    Button { label: "+"; accent: "#4caf50"; onClicked: root.addTask() }
                    Button {
                        label: "×"; accent: "#e05252"
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
        ListElement { title: "Flash the board"; group: "Hardware"; done: false }
        ListElement { title: "Write the QML"; group: "Software"; done: true }
        ListElement { title: "Measure RAM usage"; group: "Software"; done: false }
    }
    property int added: 0
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
            text: root.doneCount() + " / " + todoModel.count + " done"
            color: "white"
            font.pixelSize: 16
        }
    }
    Component {
        id: emptyView
        Text { text: "Nothing to do!"; color: "#4caf50"; font.pixelSize: 16 }
    }

    // ------------------------------------------------------------ footer
    Row {
        anchors.horizontalCenter: parent.horizontalCenter
        y: 238
        spacing: 8
        Repeater {
            model: 3
            delegate: Rectangle {
                width: index === root.page ? 20 : 8
                height: 8
                radius: 4
                color: index === root.page ? "white" : "#5d6680"
                Behavior on width { NumberAnimation { duration: 250 } }
            }
        }
    }
    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 6
        text: "Uptime " + seconds + " s • QML compiled to C++ • no malloc"
        color: "#5d6680"
        font.pixelSize: 14
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

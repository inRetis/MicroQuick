"""Tests of the mqc QML -> C++ compiler (run: python3 -m unittest tests/test_mqc.py)."""
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "mqc"))

from codegen import Generator          # noqa: E402
from parser import QmlError            # noqa: E402

CXX = shutil.which("clang++") or shutil.which("g++")


class MqcTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="mqc_test_")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def compile(self, files, main="Main.qml"):
        paths = []
        for name, src in files.items():
            p = os.path.join(self.dir, name)
            with open(p, "w") as f:
                f.write(textwrap.dedent(src))
            paths.append(p)
        gen = Generator()
        gen.compile(paths, os.path.join(self.dir, main))
        out = os.path.join(self.dir, "out")
        gen.write(out)
        gen.write_manifest(os.path.join(out, "mq_assets.txt"))
        with open(os.path.join(out, "mq_app.cpp")) as f:
            return gen, f.read()

    def assertQmlError(self, src, fragment, line=None):
        with self.assertRaises(QmlError) as cm:
            self.compile({"Main.qml": src})
        self.assertIn(fragment, cm.exception.msg)
        if line is not None:
            self.assertEqual(cm.exception.line, line)

    def assertCompilesAsCpp(self):
        if not CXX:
            self.skipTest("no C++ compiler")
        out = os.path.join(self.dir, "out")
        stub = os.path.join(out, "stub.cpp")
        with open(stub, "w") as f:
            f.write('#include "mq_app.h"\n'
                    "extern const mq::FontData *const mq_fonts[] = {nullptr};\n"
                    "extern const int mq_font_count = 0;\n")
        for src in ("mq_app.cpp", "stub.cpp"):
            r = subprocess.run([CXX, "-std=c++17", "-fsyntax-only", "-Wall", "-Werror",
                                "-Wno-unused-parameter", "-fno-exceptions", "-fno-rtti",
                                "-I", os.path.join(ROOT, "runtime", "include"), "-I", out,
                                os.path.join(out, src)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    # ------------------------------------------------------------ success
    def test_component_with_everything(self):
        gen, cpp = self.compile({
            "Main.qml": """
                import QtQuick
                Rectangle {
                    id: root
                    width: 320; height: 240
                    property int count: 0
                    property real ratio: count / 3
                    property string title: "n=" + count
                    color: count > 2 ? "red" : "#102030"
                    function bump(step: int): int { count += step; return count }
                    Text { id: t; text: root.title; font.pixelSize: 18; anchors.centerIn: parent }
                    Widget { id: w; label: "x"; onActivated: (n) => { count = n } }
                    MouseArea { anchors.fill: parent; onClicked: { var v = bump(2); if (v > 10) count = 0 } }
                    Timer { interval: 100; running: true; onTriggered: count++ }
                }
            """,
            "Widget.qml": """
                Item {
                    property alias label: txt.text
                    signal activated(int n)
                    Text { id: txt }
                    Component.onCompleted: activated(5)
                }
            """})
        self.assertIn("mq::js::div(", cpp)                 # JS '/' is floating point
        self.assertIn('(mq::String::lit("n=") + ', cpp)     # string concatenation (literal, no copy)
        self.assertIn("mq::Color(0xffff0000u)", cpp)        # color literal
        self.assertIn("self->w.txt.text.setValue", cpp)     # alias resolved statically
        self.assertIn(18, gen.font_sizes)
        self.assertCompilesAsCpp()

    def test_states_and_when(self):
        self.compile({"Main.qml": """
            Rectangle {
                id: r
                property bool on: false
                states: [
                    State { name: "a"; when: r.on; PropertyChanges { target: r; color: "blue"; width: 10 } },
                    State { name: "b"; PropertyChanges { r.height: 20 } }
                ]
            }
        """})
        self.assertCompilesAsCpp()

    def test_transitions_and_explicit_state(self):
        _, cpp = self.compile({"Main.qml": """
            Rectangle {
                id: r
                property bool hot: false
                state: "idle"
                states: [
                    State { name: "idle"; PropertyChanges { target: r; color: "gray"; width: 10 } },
                    State { name: "alarm"; when: r.hot; PropertyChanges { target: r; color: "red"; x: 40 } }
                ]
                transitions: [
                    Transition {
                        from: "*"; to: "alarm"; reversible: true
                        SequentialAnimation {
                            NumberAnimation { properties: "x,width"; duration: 200; easing.type: Easing.OutBack }
                            ColorAnimation { duration: 100 }
                        }
                    }
                ]
                MouseArea { anchors.fill: parent; onClicked: r.state = "idle" }
            }
        """})
        self.assertIn("setStartDelay(200)", cpp)
        self.assertIn("setTransitions(", cpp)
        self.assertIn("&mq::StateGroup::whenChanged", cpp)
        self.assertCompilesAsCpp()

    def test_constant_vs_binding(self):
        _, cpp = self.compile({"Main.qml": """
            Item { width: 10 * 2 + 1; height: width }
        """})
        self.assertIn("self->width.setValue(((10 * 2) + 1));", cpp)
        self.assertIn("mq::Binding", open(os.path.join(self.dir, "out", "mq_app.h")).read())

    # ------------------------------------------------------------- errors
    def test_unknown_property(self):
        self.assertQmlError("Item {\n  colour: 'red'\n}\n", "has no property 'colour'", line=2)

    def test_type_mismatch(self):
        self.assertQmlError("Item { width: 'abc' }", "cannot convert string to int")

    def test_dynamic_color_from_string(self):
        _, cpp = self.compile({"Main.qml": "Rectangle { property string c: 'red'; color: c }"})
        self.assertIn("mq::Color::fromString(", cpp)
        self.assertCompilesAsCpp()

    # ------------------------------------------------- animations / views
    def test_animations(self):
        _, cpp = self.compile({"Main.qml": """
            Rectangle {
                id: r
                width: 100; height: 100
                color: "red"
                Behavior on x { NumberAnimation { duration: 200; easing.type: Easing.OutQuad } }
                Behavior on color { ColorAnimation { duration: 100 } }
                NumberAnimation on opacity { from: 0; to: 1; duration: 300 }
                SequentialAnimation {
                    id: seq
                    loops: Animation.Infinite
                    NumberAnimation { target: r; property: "y"; to: 50; duration: 100 }
                    PauseAnimation { duration: 50 }
                    ColorAnimation { target: r; property: "border.color"; to: "blue"; duration: 100 }
                }
                MouseArea { anchors.fill: parent; onClicked: { seq.start(); r.x = 40 } }
            }
        """})
        self.assertIn("mq::Behavior<int, mq::NumberAnimation>", open(os.path.join(self.dir, "out", "mq_app.h")).read())
        self.assertIn(".setHasFrom(true);", cpp)
        self.assertIn(".setChildren(", cpp)
        self.assertCompilesAsCpp()

    def test_animation_type_errors(self):
        self.assertQmlError("Rectangle { Behavior on color { NumberAnimation {} } }", "cannot animate a color")
        self.assertQmlError("Item { NumberAnimation { duration: 10 } }", "needs a target")
        self.assertQmlError("Item { Behavior on x { } }", "exactly one")

    def test_list_view_and_repeater(self):
        _, cpp = self.compile({"Main.qml": """
            Rectangle {
                id: root
                width: 200; height: 200
                property int selected: -1
                ListModel {
                    id: fruits
                    ListElement { name: "Apple"; cost: 2; tint: "#ff0000" }
                    ListElement { name: "Pear"; cost: 1.5; tint: "green" }
                }
                ListView {
                    id: list
                    width: 200; height: 100
                    model: fruits
                    delegate: Rectangle {
                        width: list.width; height: 30
                        color: index === root.selected ? model.tint : "white"
                        Text { text: name + " " + cost.toFixed(2) }
                        MouseArea { anchors.fill: parent; onClicked: root.selected = index }
                    }
                }
                Row {
                    y: 120
                    Repeater { model: 3; delegate: Rectangle { width: 20; height: 20; color: modelData > 0 ? "red" : "blue" } }
                }
                ListView {
                    y: 150; width: 200; height: 40; orientation: ListView.Horizontal
                    model: root.selected + 10
                    delegate: Text { width: 40; height: 40; text: index }
                }
            }
        """})
        h = open(os.path.join(self.dir, "out", "mq_app.h")).read()
        self.assertIn("Main_Delegate1 _pool", h)
        self.assertIn('{"Apple", 2.0f, "#ff0000"}', cpp)
        self.assertIn("self->outer->", cpp)
        self.assertCompilesAsCpp()

    def test_view_errors(self):
        self.assertQmlError("Item { ListView { model: 3 } }", "needs a delegate")
        self.assertQmlError("Item { Loader { } }", "needs a sourceComponent or a source")
        self.assertQmlError("Item { ListModel { id: m; ListElement { a: 1 } } "
                            "Component.onCompleted: m.append({b: 2}) }", "no role 'b'")
        self.assertQmlError("Item { Loader { source: \"Nope.qml\" } }", "not a QML file of the project")

    def test_dynamic_views_loader_flickable(self):
        _, cpp = self.compile({
            "Main.qml": """
                Item {
                    id: root
                    width: 320; height: 240
                    property int n: 5
                    property bool second: false
                    ListModel {
                        id: todo
                        capacity: 20
                        ListElement { title: "Milk"; done: false; group: "Shopping" }
                        ListElement { title: "Bread"; done: true; group: "Shopping" }
                        ListElement { title: "Code"; done: false; group: "Work" }
                    }
                    Component { id: line; Rectangle { width: 100; height: 10 + index * 2; color: done ? "green" : "red"
                        Text { width: 80; text: title; elide: Text.ElideRight; wrapMode: Text.WordWrap }
                        MouseArea { anchors.fill: parent; onClicked: { todo.setProperty(index, "done", !done); ListView.view.currentIndex = index } }
                        opacity: ListView.isCurrentItem ? 1 : 0.5 } }
                    ListView {
                        id: list
                        width: 160; height: 120
                        model: todo
                        delegate: line
                        highlight: Rectangle { color: "yellow" }
                        header: Text { text: "Header" }
                        footer: Text { text: "Total " + list.count }
                        section.property: "group"
                        section.delegate: Text { text: section; font.pixelSize: 12 }
                    }
                    GridView {
                        x: 160; width: 160; height: 120; cellWidth: 40; cellHeight: 40
                        model: ["a", "b", "c", "d", "e"]
                        delegate: Text { text: modelData + index }
                    }
                    Row { Repeater { model: root.n; capacity: 8; delegate: Rectangle { width: 5; height: 5 } } }
                    Flickable {
                        y: 120; width: 100; height: 100; contentHeight: 400
                        Column { Repeater { model: todo; delegate: Text { text: title } } }
                    }
                    Component { id: pageA; Rectangle { color: "blue"; Text { text: root.n } } }
                    Loader { id: loader; width: 50; height: 50; sourceComponent: root.second ? pageA : pageB }
                    Loader { source: root.second ? "Other.qml" : "" }
                    Component { id: pageB; Text { text: "B" } }
                    Text { text: loader.item.width + " " + todo.get(0).title }
                    Component.onCompleted: {
                        todo.append({title: "Gym", group: "Personal"})
                        todo.insert(0, {title: "Coffee", done: true, group: "Shopping"})
                        todo.move(0, 2, 1)
                        todo.remove(1)
                        todo.set(0, {done: true})
                        list.positionViewAtIndex(2, ListView.Beginning)
                        list.incrementCurrentIndex()
                    }
                }
            """,
            "Other.qml": "Rectangle { width: 10; height: 10 }"})
        self.assertIn("mq::LoaderStorage<Main_Delegate", cpp.replace("\n", " ") + open(os.path.join(self.dir, "out", "mq_app.h")).read())
        self.assertIn("setSections(", cpp)
        self.assertIn("setSizeCache(", cpp)
        self.assertIn("mq::js::listInsert(", cpp)
        self.assertIn("contentItem", cpp)
        self.assertCompilesAsCpp()

    def test_invalid_color(self):
        self.assertQmlError("Rectangle { color: '#12345' }", "invalid color")

    def test_js_inference_and_arrays(self):
        _, cpp = self.compile({"Main.qml": """
            Item {
                id: root
                property var n: 3
                property var names: ["one", "two", "three"]
                property list<int> primes: [2, 3, 5, 7]
                property string label: names[n - 1] || "?"
                property int total: sum(primes.length, 10)
                property real half: sum(1.5, n)
                function sum(a, b) { return a + b }
                function fact(k: int): int { return k <= 1 ? 1 : k * fact(k - 1) }
                function describe(x) {
                    var s = ""
                    for (var i = 0; i < x; i++) s = s + names[i % names.length] + " "
                    return s
                }
                Text { text: root.describe(2) + root.fact(4) }
            }
        """})
        self.assertIn("sum__int_int(", cpp)
        self.assertIn("sum__real_int(", cpp)
        self.assertIn("mq::js::truthy(t_)", cpp)
        self.assertIn("static const char *const mq_array_1[3]", cpp)
        self.assertCompilesAsCpp()

    def test_recursive_generic_needs_annotation(self):
        self.assertQmlError("Item { property int r: f(3); function f(k) { return k <= 1 ? 1 : k * f(k - 1) } }",
                            "needs a return type annotation")

    def test_unknown_name(self):
        self.assertQmlError("Item { width: foo }", "unknown name 'foo'")

    def test_readonly(self):
        self.assertQmlError("Item { MouseArea { pressed: true } }", "read-only")

    def test_unknown_type(self):
        self.assertQmlError("Item { PathView { } }", "unknown type 'PathView'")

    def test_recursive_components(self):
        with self.assertRaises(QmlError) as cm:
            self.compile({"Main.qml": "A { }", "A.qml": "Item { B {} }", "B.qml": "Item { A {} }"})
        self.assertIn("recursive", cm.exception.msg)


if __name__ == "__main__":
    unittest.main()

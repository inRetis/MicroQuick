"""Type registry: value types and the built-in QML object types."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# value types -> C++ types
CPP_TYPES = {
    "int": "int",
    "real": "mq::real",
    "bool": "bool",
    "string": "mq::String",
    "color": "mq::Color",
    "image": "const mq::ImageData *",
    "void": "void",
}
TYPE_ALIASES = {"double": "real", "url": "image", "var": None}
NUMERIC = ("int", "real")


def normalize_type(name: str) -> Optional[str]:
    if name in CPP_TYPES:
        return name
    if name.startswith("list<") and name.endswith(">"):
        inner = normalize_type(name[5:-1])
        return f"array:{inner}" if inner in ("int", "real", "bool", "string", "color") else None
    return TYPE_ALIASES.get(name, name)


def is_array(t) -> bool:
    return isinstance(t, str) and t.startswith("array:")


def elem_type(t) -> str:
    return t[6:]


def elem_cpp(t) -> str:
    return "const char *" if t == "string" else CPP_TYPES[t]


def cpp_type(t) -> str:
    if isinstance(t, ObjType):
        return t.cpp + " *"
    if is_array(t):
        return f"mq::ConstArray<{elem_cpp(elem_type(t))}>"
    return CPP_TYPES[t]


def valid_type(t) -> bool:
    return (t in CPP_TYPES and t != "void") or is_array(t)


def default_value(t) -> str:
    return {"int": "0", "real": "0.0f", "bool": "false", "string": "mq::String()",
            "color": "mq::Color()", "image": "nullptr"}.get(t, "{}")


@dataclass
class PropInfo:
    name: str          # QML name ('border.width')
    type: object       # value type name or ObjType
    cpp: str           # C++ member name / path ('border_width', '_o2.text')
    readonly: bool = False
    alias_of: Optional["PropInfo"] = None


@dataclass
class SignalInfo:
    name: str
    params: List[tuple]    # (name, type)
    cpp: str


@dataclass
class MethodInfo:
    name: str
    params: List[tuple]
    ret: str
    cpp: str
    min_args: int = -1             # optional trailing parameters (built-in methods)
    generic: bool = False          # untyped parameters / inferred return: specialized per call
    decl: object = None            # FunctionDecl (QML functions)
    owner: object = None           # Component declaring it
    specs: dict = field(default_factory=dict)


@dataclass
class ObjType:
    name: str
    cpp: str
    base: Optional["ObjType"] = None
    is_item: bool = True
    props: Dict[str, PropInfo] = field(default_factory=dict)
    signals: Dict[str, SignalInfo] = field(default_factory=dict)
    methods: Dict[str, MethodInfo] = field(default_factory=dict)
    enums: Dict[str, str] = field(default_factory=dict)   # name -> C++ constant
    implicit_size: bool = False                           # width/height follow implicit size
    builtin: bool = True
    groups: tuple = ()
    creatable: bool = True

    def find_prop(self, name) -> Optional[PropInfo]:
        t = self
        while t:
            if name in t.props:
                return t.props[name]
            t = t.base
        return None

    def find_signal(self, name) -> Optional[SignalInfo]:
        t = self
        while t:
            if name in t.signals:
                return t.signals[name]
            t = t.base
        return None

    def find_method(self, name) -> Optional[MethodInfo]:
        t = self
        while t:
            if name in t.methods:
                return t.methods[name]
            t = t.base
        return None

    def has_group(self, name) -> bool:
        t = self
        while t:
            if name in t.groups:
                return True
            t = t.base
        return False

    def inherits(self, name) -> bool:
        t = self
        while t:
            if t.name == name:
                return True
            t = t.base
        return False

    def builtin_root(self) -> "ObjType":
        t = self
        while not t.builtin:
            t = t.base
        return t


def _props(*specs, ro=()):
    out = {}
    for spec in specs:
        name, typ = spec.split(":")
        out[name] = PropInfo(name, typ, name.replace(".", "_"), name in ro)
    return out


def _signals(*names):
    return {n: SignalInfo(n, [], "sig_" + n) for n in names}


def builtin_types() -> Dict[str, ObjType]:
    obj = ObjType("QtObject", "mq::Object", None, is_item=False)
    item = ObjType("Item", "mq::Item", obj, props=_props(
        "x:int", "y:int", "width:int", "height:int", "implicitWidth:int", "implicitHeight:int",
        "opacity:real", "visible:bool", "enabled:bool", "clip:bool", "state:string"))
    rect = ObjType("Rectangle", "mq::Rectangle", item, props=_props(
        "color:color", "radius:int", "border.width:int", "border.color:color"), groups=("border",))
    text = ObjType("Text", "mq::Text", item, props=_props(
        "text:string", "color:color", "font.pixelSize:int",
        "horizontalAlignment:int", "verticalAlignment:int", "wrapMode:int", "elide:int",
        "maximumLineCount:int", "lineCount:int", ro=("lineCount",)), groups=("font",), implicit_size=True,
        enums={n: "mq::Text::" + n for n in
               ("AlignLeft", "AlignRight", "AlignHCenter", "AlignTop", "AlignBottom", "AlignVCenter",
                "NoWrap", "WordWrap", "WrapAnywhere", "Wrap",
                "ElideLeft", "ElideRight", "ElideMiddle", "ElideNone")})
    image = ObjType("Image", "mq::Image", item, props=_props("source:image", "fillMode:int"),
                    implicit_size=True,
                    enums={n: "mq::Image::" + n for n in ("Stretch", "Pad", "Tile")})
    mouse = ObjType("MouseArea", "mq::MouseArea", item,
                    props=_props("pressed:bool", "mouseX:int", "mouseY:int",
                                 ro=("pressed", "mouseX", "mouseY")),
                    signals=_signals("pressed", "released", "clicked", "canceled"))
    row = ObjType("Row", "mq::Row", item, props=_props("spacing:int"), implicit_size=True)
    col = ObjType("Column", "mq::Column", item, props=_props("spacing:int"), implicit_size=True)
    timer = ObjType("Timer", "mq::Timer", obj, is_item=False,
                    props=_props("interval:int", "running:bool", "repeat:bool", "triggeredOnStart:bool"),
                    signals=_signals("triggered"),
                    methods={m: MethodInfo(m, [], "void", m) for m in ("start", "stop", "restart")})
    anim = ObjType("Animation", "mq::Animation", obj, is_item=False, creatable=False,
                   props=_props("running:bool", "loops:int", "duration:int"),
                   signals=_signals("started", "stopped", "finished"),
                   methods={m: MethodInfo(m, [], "void", m) for m in ("start", "stop", "restart", "complete")},
                   enums={"Infinite": "mq::Animation::Infinite"})
    number = ObjType("NumberAnimation", "mq::NumberAnimation", anim, is_item=False,
                     props=_props("from:real", "to:real", "easing.type:int"), groups=("easing",))
    coloranim = ObjType("ColorAnimation", "mq::ColorAnimation", anim, is_item=False,
                        props=_props("from:color", "to:color", "easing.type:int"), groups=("easing",))
    spring = ObjType("SpringAnimation", "mq::SpringAnimation", anim, is_item=False,
                     props=_props("spring:real", "damping:real", "mass:real", "epsilon:real",
                                  "velocity:real", "to:real"))
    smoothed = ObjType("SmoothedAnimation", "mq::SmoothedAnimation", anim, is_item=False,
                       props=_props("velocity:real", "to:real"))
    pause = ObjType("PauseAnimation", "mq::PauseAnimation", anim, is_item=False)
    seq = ObjType("SequentialAnimation", "mq::SequentialAnimation", anim, is_item=False)
    par = ObjType("ParallelAnimation", "mq::ParallelAnimation", anim, is_item=False)
    behavior = ObjType("Behavior", "mq::Behavior", obj, is_item=False, props=_props("enabled:bool"))
    easing = ObjType("Easing", "", None, is_item=False, creatable=False,
                     enums={n: "mq::Easing::" + n for n in (
                         "Linear", "InQuad", "OutQuad", "InOutQuad", "InCubic", "OutCubic",
                         "InOutCubic", "InSine", "OutSine", "InOutSine", "OutBack", "OutBounce",
                         "OutElastic")})
    model = ObjType("ListModel", "mq::ListModel", obj, is_item=False,
                    props=_props("count:int", "capacity:int", ro=("count",)),
                    methods={m: MethodInfo(m, [], "void", m) for m in
                             ("append", "insert", "remove", "clear", "set", "setProperty", "move", "get")})
    repeater = ObjType("Repeater", "mq::Repeater", obj, is_item=False,
                       props=_props("count:int", "capacity:int", ro=("count",)))
    flick = ObjType("Flickable", "mq::Flickable", item,
                    props=_props("contentX:int", "contentY:int", "contentWidth:int", "contentHeight:int",
                                 "flickableDirection:int", "interactive:bool", "moving:bool",
                                 ro=("moving",)),
                    methods={"cancelFlick": MethodInfo("cancelFlick", [], "void", "cancelFlick")},
                    enums={n: "mq::Flickable::" + n for n in (
                        "AutoFlickDirection", "HorizontalFlick", "VerticalFlick",
                        "HorizontalAndVerticalFlick")})
    pos_modes = {n: str(i) for i, n in enumerate(("Beginning", "Center", "End", "Visible", "Contain"))}
    itemview = ObjType("ItemView", "mq::ItemView", flick, creatable=False,
                       props=_props("count:int", "spacing:int", "currentIndex:int",
                                    "highlightFollowsCurrentItem:bool", "highlightMoveDuration:int",
                                    "keyNavigationWraps:bool", "capacity:int", ro=("count",)),
                       methods={"incrementCurrentIndex": MethodInfo("incrementCurrentIndex", [], "void",
                                                                    "incrementCurrentIndex"),
                                "decrementCurrentIndex": MethodInfo("decrementCurrentIndex", [], "void",
                                                                    "decrementCurrentIndex"),
                                "positionViewAtIndex": MethodInfo("positionViewAtIndex",
                                                                  [("index", "int"), ("mode", "int")], "void",
                                                                  "positionViewAt", min_args=1),
                                "positionViewAtBeginning": MethodInfo("positionViewAtBeginning", [], "void",
                                                                      "positionViewAtBeginning"),
                                "positionViewAtEnd": MethodInfo("positionViewAtEnd", [], "void",
                                                                "positionViewAtEnd")})
    listview = ObjType("ListView", "mq::ListView", itemview,
                       props=_props("orientation:int"),
                       enums=dict({"Horizontal": "mq::ListView::Horizontal",
                                   "Vertical": "mq::ListView::Vertical"}, **pos_modes))
    gridview = ObjType("GridView", "mq::GridView", itemview,
                       props=_props("cellWidth:int", "cellHeight:int", "flow:int"),
                       enums=dict({"FlowLeftToRight": "mq::GridView::FlowLeftToRight",
                                   "FlowTopToBottom": "mq::GridView::FlowTopToBottom"}, **pos_modes))
    loader = ObjType("Loader", "mq::Loader", item,
                     props=_props("active:bool", "status:int", ro=("status",)),
                     signals=_signals("loaded"), implicit_size=True,
                     enums={"Null": "0", "Ready": "1"})
    types = {t.name: t for t in (obj, item, rect, text, image, mouse, row, col, timer, anim, number,
                                 coloranim, spring, smoothed, pause, seq, par, behavior, easing, model, repeater,
                                 flick, itemview, listview, gridview, loader)}
    return types


# SVG / CSS color names accepted by QML (subset of the most common ones).
NAMED_COLORS = {
    "transparent": 0x00000000,
    "black": 0xff000000, "white": 0xffffffff, "red": 0xffff0000, "green": 0xff008000,
    "lime": 0xff00ff00, "blue": 0xff0000ff, "yellow": 0xffffff00, "cyan": 0xff00ffff,
    "aqua": 0xff00ffff, "magenta": 0xffff00ff, "fuchsia": 0xffff00ff, "gray": 0xff808080,
    "grey": 0xff808080, "darkgray": 0xffa9a9a9, "darkgrey": 0xffa9a9a9, "lightgray": 0xffd3d3d3,
    "lightgrey": 0xffd3d3d3, "dimgray": 0xff696969, "silver": 0xffc0c0c0, "gainsboro": 0xffdcdcdc,
    "whitesmoke": 0xfff5f5f5, "maroon": 0xff800000, "olive": 0xff808000, "navy": 0xff000080,
    "purple": 0xff800080, "teal": 0xff008080, "orange": 0xffffa500, "darkorange": 0xffff8c00,
    "orangered": 0xffff4500, "gold": 0xffffd700, "pink": 0xffffc0cb, "hotpink": 0xffff69b4,
    "deeppink": 0xffff1493, "crimson": 0xffdc143c, "tomato": 0xffff6347, "coral": 0xffff7f50,
    "salmon": 0xfffa8072, "brown": 0xffa52a2a, "chocolate": 0xffd2691e, "tan": 0xffd2b48c,
    "beige": 0xfff5f5dc, "ivory": 0xfffffff0, "khaki": 0xfff0e68c, "lavender": 0xffe6e6fa,
    "violet": 0xffee82ee, "indigo": 0xff4b0082, "orchid": 0xffda70d6, "plum": 0xffdda0dd,
    "skyblue": 0xff87ceeb, "lightblue": 0xffadd8e6, "steelblue": 0xff4682b4,
    "royalblue": 0xff4169e1, "dodgerblue": 0xff1e90ff, "deepskyblue": 0xff00bfff,
    "darkblue": 0xff00008b, "midnightblue": 0xff191970, "slategray": 0xff708090,
    "slategrey": 0xff708090, "lightslategray": 0xff778899, "darkslategray": 0xff2f4f4f,
    "turquoise": 0xff40e0d0, "aquamarine": 0xff7fffd4, "springgreen": 0xff00ff7f,
    "limegreen": 0xff32cd32, "forestgreen": 0xff228b22, "darkgreen": 0xff006400,
    "seagreen": 0xff2e8b57, "lightgreen": 0xff90ee90, "yellowgreen": 0xff9acd32,
    "olivedrab": 0xff6b8e23, "darkred": 0xff8b0000, "firebrick": 0xffb22222,
    "mintcream": 0xfff5fffa, "snow": 0xfffffafa, "linen": 0xfffaf0e6,
}


def parse_color(text: str) -> Optional[int]:
    """Returns 0xAARRGGBB or None."""
    s = text.strip()
    if s.startswith("#"):
        h = s[1:]
        try:
            if len(h) == 3:
                return 0xff000000 | int("".join(c * 2 for c in h), 16)
            if len(h) == 6:
                return 0xff000000 | int(h, 16)
            if len(h) == 8:
                return int(h, 16)
        except ValueError:
            return None
        return None
    return NAMED_COLORS.get(s.lower())

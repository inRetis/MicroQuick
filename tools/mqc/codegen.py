"""QML -> C++ code generator.

Every QML file becomes a C++ class deriving from the class of its root
object. Child objects become members, bindings become mq::Binding members with
a static evaluation function, handlers become mq::Connection / ChangeHandler
members, and functions become methods. Everything is statically allocated.
"""

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import parser as P
from parser import QmlError
from qtypes import (ObjType, PropInfo, SignalInfo, MethodInfo, builtin_types, cpp_type,
                    default_value, normalize_type, parse_color, CPP_TYPES, NUMERIC,
                    is_array, elem_type, elem_cpp, valid_type)

CPP_KEYWORDS = set("""alignas alignof and and_eq asm auto bitand bitor bool break case catch char
char16_t char32_t class compl const constexpr const_cast continue decltype default delete do double
dynamic_cast else enum explicit export extern false float for friend goto if inline int long mutable
namespace new noexcept not not_eq nullptr operator or or_eq private protected public register
reinterpret_cast return short signed sizeof static static_assert static_cast struct switch template
this thread_local throw true try typedef typeid typename union unsigned using virtual void volatile
wchar_t while xor xor_eq self mq""".split())

ANCHOR_NAMES = {"fill", "centerIn", "left", "right", "top", "bottom", "horizontalCenter",
                "verticalCenter", "margins", "leftMargin", "rightMargin", "topMargin",
                "bottomMargin", "horizontalCenterOffset", "verticalCenterOffset"}

DEFAULT_FONT_SIZE = 16


def cstr(s: str) -> str:
    out = ['"']
    for b in s.encode("utf-8"):
        c = chr(b)
        if c == '"': out.append('\\"')
        elif c == "\\": out.append("\\\\")
        elif c == "\n": out.append("\\n")
        elif c == "\t": out.append("\\t")
        elif 32 <= b < 127: out.append(c)
        else: out.append("\\%03o" % b)
    out.append('"')
    return "".join(out)


def sanitize(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if s[:1].isdigit():
        s = "_" + s
    return s


# --------------------------------------------------------------- values

@dataclass
class V:
    kind: str                 # val, prop, local, obj, group, type, signal, method
    code: str = ""
    type: object = None       # value type name or ObjType
    prop: Optional[PropInfo] = None
    obj: Optional["Obj"] = None
    owner: str = ""           # for prop/group/signal/method: C++ lvalue of the object
    name: str = ""
    lit: Optional[str] = None # string literal value
    info: object = None
    dynamic_parent: bool = False


class RowType:
    """Type of `model.get(i)`: a row whose roles are accessed with '.role'."""
    def __init__(self, info):
        self.info = info
        self.name = "model row"


@dataclass
class Obj:
    odef: P.ObjectDef
    type: ObjType
    name: str                 # C++ member name ('' for root)
    parent: Optional["Obj"]
    comp: "Component"
    children: List["Obj"] = field(default_factory=list)
    model: Optional[dict] = None       # ListModel rows / view model description
    delegate: Optional["Component"] = None

    @property
    def is_root(self):
        return self.parent is None

    def access(self):
        return "(*self)" if self.is_root else f"self->{self.name}"

    def member(self, cpp):
        return f"self->{cpp}" if self.is_root else f"self->{self.name}.{cpp}"


class Ctx:
    def __init__(self, comp, scope, ret=None):
        self.comp = comp
        self.scope = scope
        self.locals = [{}]
        self.reads = False
        self.ret = ret

    def lookup_local(self, name):
        for frame in reversed(self.locals):
            if name in frame:
                return frame[name]
        return None


class Component:
    def __init__(self, gen, name, doc):
        self.gen = gen
        self.name = name
        self.doc = doc
        self.file = doc.file
        self.objects: List[Obj] = []
        self.ids: Dict[str, Obj] = {}
        self.type: Optional[ObjType] = None
        self.root: Optional[Obj] = None
        self.counter = 0
        # generated pieces
        self.members: List[str] = []
        self.decls: List[str] = []       # static function / method declarations
        self.defs: List[str] = []        # out-of-class definitions
        self.ctor_parent: List[str] = []
        self.ctor_values: List[str] = []
        self.ctor_bindings: List[str] = []
        self.ctor_handlers: List[str] = []
        self.ctor_states: List[str] = []
        self.ctor_views: List[str] = []
        self.complete: List[str] = []
        self.extra_complete: List[str] = []
        self.pre_defs: List[str] = []     # file scope definitions (model rows)
        self.extra_props: List[PropInfo] = []
        self.link_estimate = 0
        self.pools: List[tuple] = []      # (delegate component, instances)
        self.outer: Optional["Component"] = None   # set for delegate components
        self.delegates: List["Component"] = []

    def uid(self, prefix):
        self.counter += 1
        return f"_{prefix}{self.counter}"

    def err(self, msg, node=None, line=None, col=None):
        if node is not None and hasattr(node, "line"):
            line, col = node.line, node.col
        raise QmlError(msg, self.file, line or 0, col or 0)


class Generator:
    def __init__(self):
        self.types: Dict[str, ObjType] = builtin_types()
        self.components: List[Component] = []
        self.images: Dict[str, str] = {}       # abs path -> symbol
        self.font_sizes = {DEFAULT_FONT_SIZE}
        self.strings: set = set()
        self.warnings: List[str] = []
        self.arrays: Dict[tuple, str] = {}
        self.array_defs: List[str] = []

    # ---------------------------------------------------------- driver
    def compile(self, files: List[str], main_file: str, assets: List[str] = ()):
        self.main_file = main_file
        docs = {}
        for a in assets:
            if a.lower().endswith(self.IMAGE_EXTS):
                self.add_image(a)
        for f in files:
            with open(f, encoding="utf-8") as fh:
                src = fh.read()
            for tok in P.tokenize(src, f):
                if tok.kind == "str":
                    self.strings.add(tok.value)
                    # any literal naming an existing image is embedded (dynamic sources)
                    if tok.value.lower().endswith(self.IMAGE_EXTS):
                        cand = os.path.join(os.path.dirname(f), tok.value.replace("qrc:/", ""))
                        if os.path.exists(cand):
                            self.add_image(cand)
            name = os.path.splitext(os.path.basename(f))[0]
            if not name[:1].isupper():
                raise QmlError("QML component file names must start with an upper case letter", f, 1, 1)
            if name in docs or name in self.types:
                raise QmlError(f"component name '{name}' clashes with an existing type", f, 1, 1)
            docs[name] = P.parse_qml(src, f)
        for doc in docs.values():
            self._pp_file = doc.file
            table = {}
            self.collect_components(doc.root, table)
            self.preprocess(doc.root, table)
        order = self.topo_sort(docs)
        for name in order:
            comp = Component(self, name, docs[name])
            self.build_interface(comp)
            self.components.extend(self.all_delegates(comp))
            self.components.append(comp)
        for comp in self.components:
            self.generate(comp)
        main_name = os.path.splitext(os.path.basename(main_file))[0]
        self.main = next(c for c in self.components if c.name == main_name)

    def all_delegates(self, comp):
        out = []
        for d in comp.delegates:
            out.extend(self.all_delegates(d))
            out.append(d)
        return out

    def topo_sort(self, docs):
        deps = {}
        for name, doc in docs.items():
            used = set()

            def walk(o):
                if o.type in docs:
                    used.add(o.type)
                for c in o.children:
                    walk(c)
                for c in getattr(o, "components", {}).values():
                    walk(c)
                for c in getattr(o, "loader_components", {}).values():
                    walk(c)
                if o.type == "Loader":
                    for a in o.assignments:
                        if a.path == ["source"] and isinstance(a.value, P.Script):
                            for n in self.walk_nodes(a.value.node):
                                if isinstance(n, P.Str) and n.value.endswith(".qml"):
                                    used.add(os.path.splitext(os.path.basename(n.value))[0])
                for a in o.assignments:
                    if isinstance(a.value, P.ObjectDef):
                        walk(a.value)
                    elif isinstance(a.value, list):
                        for v in a.value:
                            walk(v)
            walk(doc.root)
            deps[name] = {u for u in used if u in docs and u != name} | {u for u in used if u == name}
        order, state = [], {}

        def visit(n, stack):
            if state.get(n) == 2:
                return
            if state.get(n) == 1:
                raise QmlError(f"recursive component instantiation: {' -> '.join(stack + [n])}",
                               docs[n].file, 1, 1)
            state[n] = 1
            for d in sorted(deps[n]):
                visit(d, stack + [n])
            state[n] = 2
            order.append(n)
        for n in sorted(docs):
            visit(n, [])
        return order

    # ------------------------------------------------------- interface
    def resolve_type(self, comp, name, node):
        t = self.types.get(name)
        if t is None:
            comp.err(f"unknown type '{name}'", line=node.line, col=node.col)
        if not t.creatable:
            comp.err(f"'{name}' cannot be instantiated", line=node.line, col=node.col)
        return t

    VIEW_COMPONENTS = ("delegate", "highlight", "header", "footer", "section.delegate")
    MODEL_MUTATORS = ("append", "insert", "remove", "clear", "set", "setProperty", "move")

    def collect_components(self, odef, table):
        """Removes 'Component { id: x; ... }' objects from the tree; table[id] = inner object."""
        keep = []
        for c in odef.children:
            if c.type == "Component":
                if len(c.children) != 1 or c.assignments or c.properties:
                    raise QmlError("Component must contain exactly one object", self._pp_file, c.line, c.col)
                if c.id:
                    table[c.id] = c.children[0]
                self.collect_components(c.children[0], table)
                continue
            keep.append(c)
            self.collect_components(c, table)
        odef.children = keep
        for a in odef.assignments:
            vals = a.value if isinstance(a.value, list) else [a.value]
            for v in vals:
                if isinstance(v, P.ObjectDef):
                    self.collect_components(v, table)

    def component_value(self, a, table):
        v = a.value
        if isinstance(v, P.ObjectDef):
            if v.type == "Component":
                if len(v.children) != 1:
                    raise QmlError("Component must contain exactly one object", self._pp_file, v.line, v.col)
                return v.children[0]
            return v
        if isinstance(v, P.Script) and isinstance(v.node, P.Ident) and v.node.name in table:
            return table[v.node.name]
        raise QmlError(f"'{'.'.join(a.path)}' must be a component (an object, Component {{ }} or a "
                       f"Component id)", self._pp_file, a.line, a.col)

    def preprocess(self, odef, table, counter=[0]):
        """Moves components (delegates...) out of the assignments, turns inline models into children."""
        if odef.type in ("ListView", "GridView", "Repeater"):
            keep = []
            odef.components = {}
            for a in odef.assignments:
                key = ".".join(a.path)
                if key in self.VIEW_COMPONENTS:
                    c = self.component_value(a, table)
                    odef.components[key] = c
                    self.preprocess(c, table)
                    continue
                if a.path == ["model"] and isinstance(a.value, P.ObjectDef):
                    m = a.value
                    if m.type != "ListModel":
                        raise QmlError("only ListModel can be used as an inline model", self._pp_file, a.line, a.col)
                    if not m.id:
                        counter[0] += 1
                        m.id = f"listModel_{counter[0]}"
                    odef.children.append(m)
                    a = P.Assignment(["model"], P.Script(P.Ident(m.id, line=a.line, col=a.col), m.id),
                                     a.line, a.col)
                keep.append(a)
            odef.assignments = keep
            odef.delegate = odef.components.get("delegate")
        if odef.type == "Loader":
            odef.loader_components = {}
            for a in odef.assignments:
                if a.path == ["sourceComponent"] and isinstance(a.value, P.Script):
                    for n in self.walk_nodes(a.value.node):
                        if isinstance(n, P.Ident) and n.name in table:
                            odef.loader_components[n.name] = table[n.name]
                            self.preprocess(table[n.name], table)
                elif a.path == ["sourceComponent"] and isinstance(a.value, P.ObjectDef):
                    inner = self.component_value(a, table)
                    counter[0] += 1
                    key = f"inlineComponent_{counter[0]}"
                    table[key] = inner
                    odef.loader_components[key] = inner
                    a.value = P.Script(P.Ident(key, line=a.line, col=a.col), key)
                    self.preprocess(inner, table)
        for c in odef.children:
            self.preprocess(c, table)
        for a in odef.assignments:
            if isinstance(a.value, list):
                for v in a.value:
                    self.preprocess(v, table)

    def walk_nodes(self, node):
        """Yields every AST node (expressions, statements, QML objects) below `node`."""
        stack = [node]
        seen = set()
        while stack:
            n = stack.pop()
            if isinstance(n, (list, tuple)):
                stack.extend(n)
                continue
            if isinstance(n, dict):
                stack.extend(n.values())
                continue
            if not hasattr(n, "__dataclass_fields__") or id(n) in seen:
                continue
            seen.add(id(n))
            yield n
            for f in n.__dataclass_fields__:
                stack.append(getattr(n, f))
            for extra in ("components", "loader_components"):
                if hasattr(n, extra):
                    stack.append(getattr(n, extra))

    def build_interface(self, comp: Component):
        root_def = comp.doc.root
        base = self.resolve_type(comp, root_def.type, root_def)
        ctype = ObjType(comp.name, comp.name, base, is_item=base.is_item, builtin=False)
        comp.type = ctype
        self.types[comp.name] = ctype

        # objects tree
        def make(odef, parent):
            t = ctype if parent is None else self.resolve_type(comp, odef.type, odef)
            if parent is None:
                name = ""
            elif odef.id:
                name = odef.id + ("_" if odef.id in CPP_KEYWORDS else "")
            else:
                name = comp.uid("o")
            o = Obj(odef, t, name, parent, comp)
            comp.objects.append(o)
            if odef.id:
                if odef.id in comp.ids:
                    comp.err(f"duplicate id '{odef.id}'", line=odef.line, col=odef.col)
                comp.ids[odef.id] = o
            for c in odef.children:
                if c.type == "ListElement":
                    if odef.type != "ListModel":
                        comp.err("ListElement must be inside a ListModel", line=c.line, col=c.col)
                    continue
                co = make(c, o)
                o.children.append(co)
            return o
        comp.root = make(root_def, None)
        for o in comp.objects:
            if o.parent is not None and o.type.is_item and not o.parent.type.is_item:
                comp.err("visual items must be children of an Item", line=o.odef.line, col=o.odef.col)
            if o.parent is not None and o.type.name in ("State", "PropertyChanges"):
                comp.err(f"{o.type.name} must be used inside 'states'", line=o.odef.line)

        # declared properties
        for pd in root_def.properties:
            if base.find_prop(pd.name) or pd.name in ctype.props:
                comp.err(f"property '{pd.name}' already exists", line=pd.line, col=pd.col)
            if pd.type in ("alias", "var"):
                continue
            t = normalize_type(pd.type)
            if t is None or not valid_type(t):
                comp.err(f"unsupported property type '{pd.type}'", line=pd.line, col=pd.col)
            ctype.props[pd.name] = PropInfo(pd.name, t, pd.name + ("_" if pd.name in CPP_KEYWORDS else ""),
                                            pd.readonly)
        for o in comp.objects:
            if o is not comp.root and (o.odef.properties or o.odef.signals or o.odef.functions):
                comp.err("properties, signals and functions can only be declared on the root object "
                         "(move them to a separate component)", line=o.odef.line, col=o.odef.col)
        for sd in root_def.signals:
            params = []
            for pname, ptype in sd.params:
                t = normalize_type(ptype)
                if not valid_type(t):
                    comp.err(f"unsupported signal parameter type '{ptype}'", line=sd.line)
                params.append((pname, t))
            ctype.signals[sd.name] = SignalInfo(sd.name, params, "sig_" + sd.name)
        for fd in root_def.functions:
            params = []
            for pname, ptype in fd.params:
                t = None
                if ptype is not None:
                    t = normalize_type(ptype)
                    if not valid_type(t):
                        comp.err(f"unsupported parameter type '{ptype}'", line=fd.line)
                params.append((pname, t))
            ret = None
            if fd.ret:
                ret = normalize_type(fd.ret)
                if not (valid_type(ret) or ret == "void"):
                    comp.err(f"unsupported return type '{fd.ret}'", line=fd.line)
            generic = ret is None or any(t is None for _, t in params)
            ctype.methods[fd.name] = MethodInfo(fd.name, params, ret,
                                                fd.name + ("_" if fd.name in CPP_KEYWORDS else ""),
                                                generic=generic, decl=fd, owner=comp)
        # aliases (need ids)
        for pd in root_def.properties:
            if pd.type != "alias":
                continue
            if not isinstance(pd.value, P.Script):
                comp.err("alias needs a target", line=pd.line)
            target = self.alias_target(comp, pd.value.node)
            ctype.props[pd.name] = PropInfo(pd.name, target[1].type, target[0], target[1].readonly,
                                            alias_of=target[1])
        # 'property var x: value' -> type inferred from the value
        for pd in root_def.properties:
            if pd.type != "var":
                continue
            if not isinstance(pd.value, P.Script):
                comp.err(f"'var' property '{pd.name}' needs an initial value to infer its type",
                         line=pd.line, col=pd.col)
            ctx = Ctx(comp, comp.root)
            _, t = self.value(ctx, pd.value.node)
            if not valid_type(t):
                comp.err(f"cannot store a {self.tname(t)} in property '{pd.name}'", line=pd.line)
            ctype.props[pd.name] = PropInfo(pd.name, t, pd.name + ("_" if pd.name in CPP_KEYWORDS else ""),
                                            pd.readonly)
        # delegate context: index, model roles, modelData
        for name, t in getattr(comp, "context_props", []):
            if ctype.find_prop(name) is None:
                p = PropInfo(name, t, name + ("_" if name in CPP_KEYWORDS else ""))
                ctype.props[name] = p
                comp.extra_props.append(p)
        ctx_names = [n for n, _ in getattr(comp, "context_props", [])]
        if "index" in ctx_names and ctype.find_prop("modelData") is None:
            ctype.props["modelData"] = PropInfo("modelData", "int", ctype.find_prop("index").cpp, True)
        # models: mutable when a mutating method is called anywhere in the document
        mutated = set()
        for n in self.walk_nodes(comp.doc.root):
            if isinstance(n, P.Call) and isinstance(n.fn, P.Member) and isinstance(n.fn.obj, P.Ident) \
                    and n.fn.name in self.MODEL_MUTATORS:
                mutated.add(n.fn.obj.name)
        for o in comp.objects:
            if o.type.name == "ListModel":
                o.model = self.list_model_info(comp, o, o.odef.id in mutated)
        # views, repeaters and loaders get generated classes for their components
        for o in comp.objects:
            if o.type.name in ("ListView", "GridView", "Repeater"):
                comps = getattr(o.odef, "components", {})
                if "delegate" not in comps:
                    comp.err(f"{o.type.name} needs a delegate", line=o.odef.line, col=o.odef.col)
                o.model = self.view_model(comp, o)
                o.delegate = self.make_delegate(comp, o, comps["delegate"],
                                                [("index", "int")] + list(o.model["roles"]))
                o.extras = {}
                for key in ("highlight", "header", "footer"):
                    if key in comps:
                        if o.type.name == "Repeater":
                            comp.err(f"Repeater has no {key}", line=o.odef.line)
                        o.extras[key] = self.make_delegate(comp, o, comps[key], [])
                if "section.delegate" in comps:
                    if o.type.name != "ListView":
                        comp.err("sections are only supported by ListView", line=o.odef.line)
                    o.extras["section"] = self.make_delegate(comp, o, comps["section.delegate"],
                                                             [("section", "string")])
            if o.type.name == "Loader":
                o.loader = []
                for key, odef in getattr(o.odef, "loader_components", {}).items():
                    o.loader.append((key, self.make_delegate(comp, o, odef, [])))
                for a in o.odef.assignments:
                    if a.path == ["source"] and isinstance(a.value, P.Script):
                        for n in self.walk_nodes(a.value.node):
                            if isinstance(n, P.Str) and n.value:
                                tname = os.path.splitext(os.path.basename(n.value))[0]
                                t = self.types.get(tname)
                                if t is None or t.builtin or not n.value.endswith(".qml"):
                                    comp.err(f"Loader source '{n.value}' is not a QML file of the project", n)
                                if not t.is_item:
                                    comp.err(f"'{tname}' is not an Item", n)
                                if all(k != n.value for k, _ in o.loader):
                                    o.loader.append((n.value, t))

    def list_model_info(self, comp, o, mutable=False):
        roles, rows = {}, []
        for el in o.odef.children:
            if el.type != "ListElement":
                comp.err("a ListModel may only contain ListElement objects", line=el.line)
            if el.children or el.properties or el.id:
                comp.err("ListElement only accepts role: value pairs", line=el.line)
            row = {}
            for a in el.assignments:
                if len(a.path) != 1 or not isinstance(a.value, P.Script):
                    comp.err("invalid ListElement role", line=a.line, col=a.col)
                n = a.value.node
                neg = False
                if isinstance(n, P.Unary) and n.op == "-" and isinstance(n.expr, P.Num):
                    n, neg = n.expr, True
                if isinstance(n, P.Str):
                    t, v = "string", n.value
                elif isinstance(n, P.Bool):
                    t, v = "bool", n.value
                elif isinstance(n, P.Num):
                    t, v = ("real" if isinstance(n.value, float) else "int"), (-n.value if neg else n.value)
                else:
                    comp.err("ListElement values must be literals", n)
                role = a.path[0]
                old = roles.get(role)
                if old and old != t:
                    if {old, t} == {"int", "real"}:
                        t = "real"
                    else:
                        comp.err(f"role '{role}' has inconsistent types ({old} / {t})", n)
                roles[role] = t
                row[role] = v
            rows.append(row)
        cap = None
        for a in o.odef.assignments:
            if a.path == ["capacity"]:
                n = a.value.node if isinstance(a.value, P.Script) else None
                if not (isinstance(n, P.Num) and isinstance(n.value, int)):
                    comp.err("ListModel capacity must be an integer literal", line=a.line)
                cap = n.value
        if mutable and cap is None:
            cap = len(rows) + 32
            self.warnings.append(f"{comp.file}:{o.odef.line}: warning: ListModel '{o.odef.id}' is modified: "
                                 f"storage for {cap} rows reserved (set 'capacity' to choose)")
        if mutable and not roles:
            comp.err(f"ListModel '{o.odef.id}' is modified but has no ListElement to define its roles",
                     line=o.odef.line)
        if mutable:   # rows live in RAM inside the component
            struct, sym, size = f"{o.name}_Row", f"{o.name}_rows", f"{o.name}_size"
        else:         # rows are const data in flash
            struct, sym, size = f"{comp.name}_{o.name}_Row", f"{comp.name}_{o.name}_rows", None
        return {"kind": "list", "roles": list(roles.items()), "rows": rows, "count": len(rows),
                "struct": struct, "sym": sym, "size": size, "obj": o, "mutable": mutable,
                "capacity": cap or len(rows)}

    def view_model(self, comp, o):
        a = next((a for a in o.odef.assignments if a.path == ["model"]), None)
        if a is None:
            comp.err(f"{o.type.name} needs a model", line=o.odef.line, col=o.odef.col)
        n = a.value.node
        if isinstance(n, P.Ident) and n.name in comp.ids and comp.ids[n.name].type.name == "ListModel":
            info = comp.ids[n.name].model
            count = None if info["mutable"] else info["count"]
            return {"kind": "list", "count": count, "roles": info["roles"], "info": info, "a": a,
                    "capacity": info["capacity"]}
        if isinstance(n, P.Num) and isinstance(n.value, int):
            return {"kind": "int", "count": n.value, "roles": [], "a": a, "capacity": n.value}
        _, t = self.value(Ctx(comp, o), n)
        if is_array(t):
            count = len(n.items) if isinstance(n, P.ArrayLit) else None
            return {"kind": "array", "count": count, "roles": [("modelData", elem_type(t))], "a": a,
                    "elem": elem_type(t), "capacity": count}
        if t not in NUMERIC:
            comp.err("a model must be an integer, an array or a ListModel", n)
        return {"kind": "dynamic", "count": None, "roles": [], "a": a, "capacity": None}

    def make_delegate(self, comp, owner, odef, context_props):
        name = f"{comp.name}_Delegate{len(comp.delegates) + 1}"
        doc = P.Document(comp.file, comp.doc.imports, odef)
        d = Component(self, name, doc)
        d.outer = comp
        d.view = owner
        d.context_props = context_props
        self.build_interface(d)
        comp.delegates.append(d)
        return d

    def alias_target(self, comp, node):
        parts = []
        n = node
        while isinstance(n, P.Member):
            parts.insert(0, n.name)
            n = n.obj
        if not isinstance(n, P.Ident) or n.name not in comp.ids or not parts:
            comp.err("alias target must be <id>.<property>", node)
        o = comp.ids[n.name]
        pname = ".".join(parts)
        prop = o.type.find_prop(pname)
        if prop is None:
            comp.err(f"'{o.type.name}' has no property '{pname}'", node)
        path = prop.cpp if o.is_root else f"{o.name}.{prop.cpp}"
        return path, prop

    # ---------------------------------------------------------- generation
    def generate(self, comp: Component):
        ctype = comp.type
        # members: declared properties & signals
        for pd in comp.doc.root.properties:
            if pd.type == "alias":
                continue
            p = ctype.props[pd.name]
            comp.members.append(f"mq::Property<{cpp_type(p.type)}> {p.cpp};")
        for p in comp.extra_props:
            comp.members.append(f"mq::Property<{cpp_type(p.type)}> {p.cpp};")
        for s in ctype.signals.values():
            args = ", ".join(cpp_type(t) for _, t in s.params)
            comp.members.append(f"mq::Signal<{args}> {s.cpp};")
        if comp.outer is not None:
            comp.members.append(f"{comp.outer.name} *outer = nullptr;")
        # child objects as members
        for o in comp.objects:
            if o.is_root:
                continue
            if o.type.name == "Behavior":
                comp.members.append(f"{self.behavior_cpp(comp, o)} {o.name};")
            else:
                comp.members.append(f"{o.type.cpp} {o.name};")
            if o.type.is_item:
                comp.ctor_parent.append(f"{o.name}.setParentItem(&{self.item_access(o.parent)});")
            if o.type.name == "ListModel":
                self.gen_model_rows(comp, o)
            if o.delegate is not None:
                self.gen_view_pool(comp, o)
            if getattr(o, "loader", None) is not None:
                self.gen_loader(comp, o)
        # functions
        for fd in comp.doc.root.functions:
            self.gen_function(comp, fd)
        # declared property initial values
        for pd in comp.doc.root.properties:
            if pd.type == "alias":
                if pd.value is None:
                    continue
                continue
            if pd.value is not None:
                self.gen_assignment(comp, comp.root, ctype.props[pd.name], pd.value, pd, decl=True)
        # assignments of every object
        for o in comp.objects:
            self.gen_object(comp, o)

    def item_access(self, o: Obj):
        base = "(*this)" if o.is_root else o.name
        if o.type.inherits("Flickable"):
            return base + ".contentItem"   # children of a Flickable scroll with its content
        return base

    # ------------------------------------------------------ models / views
    def role_cpp(self, t, mutable):
        if t == "string":
            return "mq::String" if mutable else "const char *"
        return cpp_type(t)

    def role_literal(self, t, v, mutable):
        if t == "string":
            return f"mq::String::lit({cstr(v or '')})" if mutable else cstr(v or "")
        if t == "bool":
            return "true" if v else "false"
        if t == "real":
            return f"{float(v or 0)!r}f"
        return str(int(v or 0))

    def gen_model_rows(self, comp, o):
        info = o.model
        mut = info["mutable"]
        if not info["roles"]:
            comp.ctor_values.append(f"{o.member('count')}.setValue({info['count']});")
            return
        fields = "".join(f" {self.role_cpp(t, mut)} {r}{{}};" for r, t in info["roles"])
        if mut:
            # rows live in RAM, inside the component (no heap): capacity is fixed
            comp.members.append(f"struct {info['struct']} {{{fields} }};")
            comp.members.append(f"{info['struct']} {info['sym']}[{info['capacity']}];")
            comp.members.append(f"int {info['size']} = 0;")
            for i, row in enumerate(info["rows"]):
                vals = ", ".join(self.role_literal(t, row.get(r), True) for r, t in info["roles"])
                comp.ctor_values.append(f"self->{info['sym']}[{i}] = {info['struct']}{{{vals}}};")
            comp.ctor_values.append(f"self->{info['size']} = {info['count']};")
            comp.ctor_values.append(f"{o.member('changed')}({info['count']});")
            return
        lines = [f"struct {info['struct']} {{{fields} }};",
                 f"static const {info['struct']} {info['sym']}[{max(info['count'], 1)}] = {{"]
        for row in info["rows"]:
            lines.append("    {" + ", ".join(self.role_literal(t, row.get(r), False)
                                             for r, t in info["roles"]) + "},")
        lines.append("};")
        comp.pre_defs.append("\n".join(lines))
        comp.ctor_values.append(f"{o.member('count')}.setValue({info['count']});")

    def model_row(self, comp, info, index):
        """C++ expression of model row `index` seen from component `comp` (self)."""
        if info["mutable"]:
            return f"self->{info['sym']}[{index}]"
        return f"{info['sym']}[{index}]"

    def role_value(self, info, row, role, t):
        v = f"{row}.{role}"
        if t == "string" and not info["mutable"]:
            v = f"mq::String::lit({v})"
        return v

    def view_bind_fn(self, comp, o, fn, d):
        m = o.model
        body = [f"auto *self = static_cast<{comp.name} *>(ctx);", "(void)self;",
                f"auto *d = static_cast<{d.name} *>(item);",
                f"d->{d.type.find_prop('index').cpp}.setValue(index);"]
        if m["kind"] == "array":
            code, t = self.value(Ctx(comp, o), m["a"].value.node)
            v = f"({code}).at(index)"
            if m["elem"] == "string":
                v = f"mq::String::lit({v})"
            p = d.type.find_prop("modelData")
            body.append(f"d->{p.cpp}.setValue({self.conv(Ctx(comp, o), v, m['elem'], p.type, None)});")
        if m["kind"] == "list":
            info = m["info"]
            row = self.model_row(comp, info, "index")
            for r, t in info["roles"]:
                p = d.type.find_prop(r)
                if p is None:
                    continue
                v = self.role_value(info, row, r, t)
                if p.type != t:
                    v = self.conv(Ctx(comp, comp.root), v, t, p.type, None)
                body.append(f"d->{p.cpp}.setValue({v});")
        comp.decls.append(f"static void {fn}(void *ctx, mq::Item *item, int index);")
        comp.defs.append(f"void {comp.name}::{fn}(void *ctx, mq::Item *item, int index)\n{{\n"
                         + "".join(f"    {l}\n" for l in body) + "}\n")

    def const_assign(self, odef, name):
        for a in odef.assignments:
            if a.path == [name] and isinstance(a.value, P.Script):
                n = a.value.node
                if isinstance(n, P.Num) and isinstance(n.value, int):
                    return n.value
                if isinstance(n, P.Member) and isinstance(n.obj, P.Ident) and n.obj.name in ("ListView", "GridView"):
                    return n.name
        return None

    def model_count_and_reset(self, comp, o, reset_code):
        """Binds the view's count to its model; runs reset_code when the model data changes."""
        m = o.model
        if m["count"] is not None:
            comp.ctor_values.append(f"{o.member('count')}.setValue({m['count']});")
        elif m["kind"] == "array":
            code, _ = self.value(Ctx(comp, o), m["a"].value.node)
            self.emit_binding(comp, o.member("count"), "int", f"return ({code}).size();", "model.length")
        elif m["kind"] == "list":
            mo = m["info"]["obj"]
            self.emit_binding(comp, o.member("count"), "int", f"return {mo.member('count')}.get();", "model.count")
        else:
            self.gen_assignment(comp, o, o.type.find_prop("count"), m["a"].value, m["a"], decl=True)
        if m["kind"] == "list" and m["info"]["mutable"]:
            h = comp.uid("rev")
            comp.members.append(f"mq::ChangeHandler {h};")
            comp.decls.append(f"static void {h}_fn(void *ctx);")
            comp.defs.append(f"void {comp.name}::{h}_fn(void *ctx)\n{{\n"
                             f"    auto *self = static_cast<{comp.name} *>(ctx);\n    (void)self;\n"
                             f"    {reset_code}\n}}\n")
            comp.ctor_views.append(f"{h}.init(&{m['info']['obj'].member('revision')}, self, &{comp.name}::{h}_fn);")

    def gen_single(self, comp, o, d, setter):
        """One instance of a view component (highlight, header, footer)."""
        k = comp.uid("one")
        comp.members.append(f"{d.name} {k};")
        comp.ctor_views.append(f"{k}.mq_setup(self);")
        comp.ctor_views.append(f"{o.member(setter)}(&{k});")
        comp.extra_complete.append(f"{k}.componentComplete();")
        comp.pools.append((d, 1))

    def gen_view_pool(self, comp, o):
        d, m = o.delegate, o.model
        pid = comp.uid("pool")
        if o.type.name == "Repeater":
            if o.parent is None or not o.parent.type.is_item:
                comp.err("Repeater must be the child of an Item", line=o.odef.line)
            n = m["count"]
            if n is None:
                n = self.const_assign(o.odef, "capacity") or m.get("capacity")
                if n is None:
                    n = 32
                    self.warnings.append(f"{comp.file}:{o.odef.line}: warning: Repeater with a dynamic model: "
                                         f"{n} delegates preallocated (set 'capacity' to choose)")
            if n == 0:
                return
            comp.members.append(f"{d.name} {pid}[{n}];")
            comp.pools.append((d, n))
            comp.ctor_parent.append(f"for (auto &d : {pid}) d.setParentItem(&{self.item_access(o.parent)});")
            fn = pid + "_bind"
            self.view_bind_fn(comp, o, fn, d)
            upd = pid + "_update"
            comp.decls.append(f"static void {upd}(void *ctx);")
            comp.defs.append(f"// shows the delegates of the {o.type.name} rows, hides the others\n"
                             f"void {comp.name}::{upd}(void *ctx)\n{{\n"
                             f"    auto *self = static_cast<{comp.name} *>(ctx);\n"
                             f"    const int n = {o.member('count')}.value();\n"
                             f"    for (int i = 0; i < {n}; ++i) {{\n"
                             f"        if (i < n) {fn}(self, &self->{pid}[i], i);\n"
                             f"        self->{pid}[i].visible.setValue(i < n);\n"
                             f"    }}\n}}\n")
            comp.ctor_views.append(f"for (auto &d : {pid}) d.mq_setup(self);")
            self.model_count_and_reset(comp, o, f"{upd}(self);")
            if m["count"] is None:
                h = comp.uid("cnt")
                comp.members.append(f"mq::ChangeHandler {h};")
                comp.ctor_views.append(f"{h}.init(&{o.member('count')}, self, &{comp.name}::{upd});")
            comp.ctor_views.append(f"{upd}(self);")
            comp.extra_complete.append(f"for (auto &d : {pid}) d.componentComplete();")
            return

        # ListView / GridView: pool sized to cover the viewport, recycled while scrolling
        grid = o.type.name == "GridView"
        if grid:
            horizontal = self.const_assign(o.odef, "flow") == "FlowTopToBottom"
            dim, cross = ("width", "height") if horizontal else ("height", "width")
            cell = self.const_assign(o.odef, "cellWidth" if horizontal else "cellHeight") or 100
            cell_cross = self.const_assign(o.odef, "cellHeight" if horizontal else "cellWidth") or 100
            view_size = self.const_assign(o.odef, dim)
            view_cross = self.const_assign(o.odef, cross)
            n = None
            if isinstance(view_size, int) and isinstance(view_cross, int):
                n = (-(-view_size // max(cell, 1)) + 1) * max(1, view_cross // max(cell_cross, 1))
            item_size = cell
        else:
            horizontal = self.const_assign(o.odef, "orientation") == "Horizontal"
            dim = "width" if horizontal else "height"
            view_size = self.const_assign(o.odef, dim)
            item_size = self.const_assign(d.doc.root, dim)
            spacing = self.const_assign(o.odef, "spacing")
            n = None
            if isinstance(view_size, int) and isinstance(item_size, int) and item_size > 0:
                step = item_size + (spacing if isinstance(spacing, int) else 0)
                n = -(-view_size // max(step, 1)) + 1
        explicit = self.const_assign(o.odef, "capacity")
        cap_rows = m["count"] if m["count"] is not None else m.get("capacity")
        if explicit:
            n = explicit
        if cap_rows is not None:
            n = cap_rows if n is None else min(n, cap_rows)
        if n is None:
            n = 16
            self.warnings.append(f"{comp.file}:{o.odef.line}: warning: {o.type.name} preallocates {n} delegates; "
                                 f"give it a constant {dim} and a constant delegate {dim} (or set 'capacity')")
        if n > 64:
            self.warnings.append(f"{comp.file}:{o.odef.line}: warning: {o.type.name} preallocates {n} delegates; "
                                 f"give it a constant {dim} and a constant delegate {dim} to reduce RAM")
        n = max(n, 1)
        extras = getattr(o, "extras", {})
        if "highlight" in extras:   # first: drawn below the delegates
            self.gen_single(comp, o, extras["highlight"], "setHighlight")
        comp.pools.append((d, n))
        comp.members.append(f"{d.name} {pid}[{n}];")
        comp.members.append(f"mq::Item *{pid}_slots[{n}];")
        comp.members.append(f"int {pid}_rows[{n}];")
        fn = pid + "_bind"
        self.view_bind_fn(comp, o, fn, d)
        comp.ctor_views.append(f"for (int i = 0; i < {n}; ++i) {{ {pid}[i].mq_setup(self); "
                               f"{pid}_slots[i] = &{pid}[i]; }}")
        comp.ctor_views.append(f"{o.member('setDelegates')}({pid}_slots, {pid}_rows, {n}, self, "
                               f"&{comp.name}::{fn});")
        comp.extra_complete.append(f"for (auto &d : {pid}) d.componentComplete();")
        if not grid and not isinstance(item_size, int):
            # delegates of different sizes: measured sizes are cached per row
            rows = cap_rows if cap_rows is not None else 256
            comp.members.append(f"int16_t {pid}_sizes[{max(rows, 1)}];")
            comp.ctor_views.append(f"{o.member('setSizeCache')}({pid}_sizes, {max(rows, 1)});")
        if "section" in extras:
            self.gen_sections(comp, o, extras["section"], n)
        for key, setter in (("header", "setHeader"), ("footer", "setFooter")):
            if key in extras:
                self.gen_single(comp, o, extras[key], setter)
        self.model_count_and_reset(comp, o, f"{o.member('modelReset')}();")

    def gen_sections(self, comp, o, sd, n):
        role = None
        for a in o.odef.assignments:
            if a.path == ["section", "property"]:
                if not (isinstance(a.value, P.Script) and isinstance(a.value.node, P.Str)):
                    comp.err("section.property must be a string literal", line=a.line)
                role = a.value.node.value
        o.odef.assignments = [a for a in o.odef.assignments if a.path[0] != "section"]
        if role is None:
            comp.err("section.delegate needs section.property", line=o.odef.line)
        m = o.model
        if m["kind"] == "list":
            rt = dict(m["info"]["roles"]).get(role)
            if rt is None:
                comp.err(f"the model has no role '{role}'", line=o.odef.line)
            v = self.role_value(m["info"], self.model_row(comp, m["info"], "index"), role, rt)
        elif m["kind"] == "array" and role == "modelData":
            code, _ = self.value(Ctx(comp, o), m["a"].value.node)
            rt, v = m["elem"], f"({code}).at(index)"
            if rt == "string":
                v = f"mq::String::lit({v})"
        else:
            comp.err("sections need a ListModel (or an array with section.property: \"modelData\")",
                     line=o.odef.line)
        if rt != "string":
            v = f"mq::toString({v})"
        pid = comp.uid("sec")
        comp.members.append(f"{sd.name} {pid}[{n}];")
        comp.members.append(f"mq::Item *{pid}_slots[{n}];")
        comp.members.append(f"int {pid}_rows[{n}];")
        comp.pools.append((sd, n))
        comp.decls.append(f"static mq::String {pid}_of(void *ctx, int index);")
        comp.decls.append(f"static void {pid}_bind(void *ctx, mq::Item *item, const mq::String &section);")
        comp.defs.append(f"mq::String {comp.name}::{pid}_of(void *ctx, int index)\n{{\n"
                         f"    auto *self = static_cast<{comp.name} *>(ctx);\n    (void)self;\n"
                         f"    return {v};\n}}\n")
        comp.defs.append(f"void {comp.name}::{pid}_bind(void *ctx, mq::Item *item, const mq::String &section)\n{{\n"
                         f"    (void)ctx;\n    static_cast<{sd.name} *>(item)->{sd.type.find_prop('section').cpp}"
                         f".setValue(section);\n}}\n")
        comp.ctor_views.append(f"for (int i = 0; i < {n}; ++i) {{ {pid}[i].mq_setup(self); "
                               f"{pid}_slots[i] = &{pid}[i]; }}")
        comp.ctor_views.append(f"{o.member('setSections')}({pid}_slots, {pid}_rows, {n}, self, "
                               f"&{comp.name}::{pid}_of, &{comp.name}::{pid}_bind);")
        comp.extra_complete.append(f"for (auto &d : {pid}) d.componentComplete();")

    # ------------------------------------------------------------- Loader
    def gen_loader(self, comp, o):
        cands = o.loader
        if not cands:
            comp.err("Loader needs a sourceComponent or a source", line=o.odef.line)
        lid = comp.uid("ld")
        classes = [c.name if isinstance(c, Component) else c.cpp for _, c in cands]
        comp.members.append(f"mq::LoaderStorage<{', '.join(classes)}> {lid}_buf;")
        comp.members.append(f"mq::Property<int> {lid}_which{{-1}};")
        comp.members.append(f"mq::ChangeHandler {lid}_changed;")
        # which candidate: from 'active' and source / sourceComponent
        src = None
        for a in o.odef.assignments:
            if a.path in (["source"], ["sourceComponent"]):
                if src is not None:
                    comp.err("Loader: use either source or sourceComponent", line=a.line)
                src = a
        o.odef.assignments = [a for a in o.odef.assignments if a.path not in (["source"], ["sourceComponent"])]
        keys = [k for k, _ in cands]
        ctx = Ctx(comp, o)

        def pick(node):
            if isinstance(node, P.Cond):
                return f"({self.cond(ctx, node.test)} ? {pick(node.then)} : {pick(node.other)})"
            if isinstance(node, P.Ident) and node.name in keys:
                return str(keys.index(node.name))
            if isinstance(node, P.Str):
                return str(keys.index(node.value)) if node.value in keys else "-1"
            comp.err("Loader source must be a component id, a .qml file name or a conditional of those", node)
        expr = pick(src.value.node)
        active = f"{o.member('active')}.get()"
        self.emit_binding(comp, f"self->{lid}_which", "int", f"return {active} ? {expr} : -1;", "Loader source")
        cases = []
        for i, (key, c) in enumerate(cands):
            cls = classes[i]
            setup = "    obj->mq_setup(self);\n" if isinstance(c, Component) else ""
            cases.append(f"    case {i}: {{\n"
                         f"        auto *obj = new (self->{lid}_buf.data) {cls}();\n"
                         f"    {setup}"
                         f"        {o.member('attach')}(obj, obj, [](void *p) {{ static_cast<{cls} *>(p)->~{cls.split('::')[-1]}(); }});\n"
                         f"        obj->componentComplete();\n"
                         f"        break;\n    }}\n")
            if isinstance(c, Component):
                comp.pools.append((c, 1))
        comp.decls.append(f"static void {lid}_load(void *ctx);")
        comp.defs.append(f"// Loader: (re)creates the selected component in place\n"
                         f"void {comp.name}::{lid}_load(void *ctx)\n{{\n"
                         f"    auto *self = static_cast<{comp.name} *>(ctx);\n"
                         f"    {o.member('unload')}();\n"
                         f"    switch (self->{lid}_which.value()) {{\n" + "".join(cases) +
                         f"    default: break;\n    }}\n}}\n")
        comp.ctor_views.append(f"{lid}_changed.init(&{lid}_which, self, &{comp.name}::{lid}_load);")
        comp.ctor_views.append(f"{lid}_load(self);")
        explicit = any(a.path[0] in ("width", "height") or a.path[0] == "anchors" for a in o.odef.assignments)
        if explicit:
            comp.ctor_values.append(f"{o.member('setResizeItem')}(true);")

    # ---------------------------------------------------------- animations
    def anim_target(self, comp, o):
        """Returns (C++ property expression, PropInfo) animated by `o`, or None."""
        if o.odef.on:
            if o.parent is None:
                comp.err("'on' syntax needs a parent object", line=o.odef.line)
            pname = ".".join(o.odef.on)
            prop = o.parent.type.find_prop(pname)
            if prop is None:
                comp.err(f"'{o.parent.type.name}' has no property '{pname}'", line=o.odef.line)
            return o.parent.member(prop.cpp), prop
        tgt = next((a for a in o.odef.assignments if a.path == ["target"]), None)
        pr = next((a for a in o.odef.assignments if a.path == ["property"]), None)
        if tgt is None and pr is None:
            # inside 'SequentialAnimation on x { ... }': inherit the group's property
            p = o.parent
            while p is not None and p.type.inherits("Animation"):
                if p.odef.on:
                    return self.anim_target(comp, p)
                p = p.parent
            return None
        if tgt is None or pr is None:
            comp.err("an animation needs both 'target' and 'property'", line=o.odef.line)
        tn, pn = tgt.value.node, pr.value.node
        if not isinstance(tn, P.Ident) or tn.name not in comp.ids:
            comp.err("animation target must be an id", tn)
        if not isinstance(pn, P.Str):
            comp.err("animation property must be a string literal", pn)
        to = comp.ids[tn.name]
        prop = to.type.find_prop(pn.value)
        if prop is None:
            comp.err(f"'{to.type.name}' has no property '{pn.value}'", pn)
        return to.member(prop.cpp), prop

    def check_anim_type(self, comp, o, prop):
        want = ("color",) if o.type.name == "ColorAnimation" else ("int", "real")
        if prop.type not in want:
            comp.err(f"{o.type.name} cannot animate a {self.tname(prop.type)} property", line=o.odef.line)

    def behavior_cpp(self, comp, o):
        if not o.odef.on:
            comp.err("use 'Behavior on <property> { ... }'", line=o.odef.line)
        _, prop = self.anim_target(comp, o)
        anims = [c for c in o.children if c.type.inherits("Animation")]
        if len(anims) != 1 or anims[0].type.name not in ("NumberAnimation", "ColorAnimation",
                                                          "SpringAnimation", "SmoothedAnimation"):
            comp.err("Behavior needs exactly one NumberAnimation, ColorAnimation, SpringAnimation "
                     "or SmoothedAnimation", line=o.odef.line)
        self.check_anim_type(comp, anims[0], prop)
        return f"mq::Behavior<{cpp_type(prop.type)}, {anims[0].type.cpp}>"

    def gen_animation(self, comp, o, assigned):
        if o.type.name == "Behavior":
            target, prop = self.anim_target(comp, o)
            anim = next(c for c in o.children if c.type.inherits("Animation"))
            comp.ctor_values.append(f"{o.member('install')}(&{target}, &self->{anim.name});")
            return
        if not o.type.inherits("Animation"):
            return
        in_behavior = o.parent is not None and o.parent.type.name == "Behavior"
        if in_behavior and o.odef.on:
            comp.err("an animation inside a Behavior must not use 'on'", line=o.odef.line)
        if o.type.name in ("SpringAnimation", "SmoothedAnimation") and not in_behavior:
            comp.err(f"{o.type.name} must be used inside a Behavior", line=o.odef.line)
        if o.type.name in ("NumberAnimation", "ColorAnimation") and not in_behavior:
            t = self.anim_target(comp, o)
            if t is None:
                comp.err(f"{o.type.name} needs a target and a property (or 'on <property>')",
                         line=o.odef.line)
            self.check_anim_type(comp, o, t[1])
            comp.ctor_values.append(f"{o.member('setTarget')}(&{t[0]});")
        if o.odef.on and not in_behavior:
            self.anim_target(comp, o)   # validates the property
            if "running" not in assigned:
                comp.ctor_values.append(f"{o.member('running')}.setValue(true);")
        if "from" in assigned:
            comp.ctor_values.append(f"{o.member('setHasFrom')}(true);")
        if o.type.name in ("SequentialAnimation", "ParallelAnimation"):
            kids = [c for c in o.children if c.type.inherits("Animation")]
            if len(kids) != len(o.children):
                comp.err("animation groups may only contain animations", line=o.odef.line)
            if kids:
                arr = comp.uid("anims")
                comp.members.append(f"mq::Animation *{arr}[{len(kids)}];")
                for i, k in enumerate(kids):
                    comp.ctor_values.append(f"{arr}[{i}] = &self->{k.name};")
                comp.ctor_values.append(f"{o.member('setChildren')}({arr}, {len(kids)});")

    def gen_object(self, comp: Component, o: Obj):
        anchors = {}
        assigned = set()
        states = None
        transitions = None
        for a in o.odef.assignments:
            path = a.path
            name = ".".join(path)
            if path[0] == "anchors":
                if len(path) != 2 or path[1] not in ANCHOR_NAMES:
                    comp.err(f"unsupported anchor '{name}'", line=a.line, col=a.col)
                anchors[path[1]] = a
                continue
            if name == "states":
                states = a
                continue
            if name == "transitions":
                transitions = a
                continue
            if name == "Component.onCompleted":
                self.gen_completed(comp, o, a)
                continue
            if name == "model" and o.type.name in ("ListView", "GridView", "Repeater"):
                continue   # handled by gen_view_pool
            if name == "capacity" and o.type.name in ("ListView", "GridView", "Repeater", "ListModel"):
                continue   # compile time storage size
            if name in ("target", "property") and o.type.inherits("Animation"):
                continue   # handled by gen_animation
            last = path[-1]
            if len(path) == 1 and re.match(r"^on[A-Z]", last):
                self.gen_handler(comp, o, a)
                continue
            prop = o.type.find_prop(name)
            if prop is None:
                if o.type.has_group(path[0]) and len(path) == 1:
                    comp.err(f"'{name}' is a grouped property, assign its members (e.g. {name}.width)",
                             line=a.line, col=a.col)
                comp.err(f"'{o.type.name}' has no property '{name}'", line=a.line, col=a.col)
            if name in assigned:
                comp.err(f"property '{name}' assigned twice", line=a.line, col=a.col)
            assigned.add(name)
            self.gen_assignment(comp, o, prop, a.value, a)
        if anchors:
            assigned |= self.gen_anchors(comp, o, anchors)
        # width/height follow implicit size unless set (Text, Image, Row, Column)
        if o.type.builtin and o.type.implicit_size:
            for dim, imp in (("width", "implicitWidth"), ("height", "implicitHeight")):
                if dim not in assigned:
                    self.emit_binding(comp, o.member(dim), "int",
                                      f"return {o.member(imp)}.get();", f"{dim}: {imp} (implicit)")
        if states is not None:
            self.gen_states(comp, o, states, transitions)
        elif transitions is not None:
            comp.err("transitions need states", line=transitions.line)
        if o.odef.on and not (o.type.inherits("Animation") or o.type.name == "Behavior"):
            comp.err("the 'on' syntax is only supported for animations and Behavior", line=o.odef.line)
        self.gen_animation(comp, o, assigned)

    # ------------------------------------------------ assignments / bindings
    def gen_assignment(self, comp, o: Obj, prop: PropInfo, value, a, decl=False):
        target = o.member(prop.cpp)
        if isinstance(value, (P.ObjectDef, list)):
            comp.err(f"cannot assign an object to property '{prop.name}'", line=a.line, col=a.col)
        if prop.readonly and not decl:
            comp.err(f"property '{prop.name}' is read-only", line=a.line, col=a.col)
        node = value.node
        if isinstance(node, P.FuncExpr):
            comp.err("functions cannot be assigned to properties", node)
        ctx = Ctx(comp, o, ret=prop.type)
        if isinstance(node, P.Block):
            body = self.gen_block_body(ctx, node, prop.type)
            self.emit_binding(comp, target, prop.type, body, value.text)
            return
        code, t = self.value(ctx, node, prop.type)
        code = self.conv(ctx, code, t, prop.type, node)
        if prop.name == "font.pixelSize":
            if isinstance(node, P.Num) and isinstance(node.value, int):
                self.font_sizes.add(node.value)
            else:
                self.warnings.append(f"{comp.file}:{a.line}: warning: non constant font.pixelSize; "
                                     "the nearest pre-rendered font size will be used")
        if ctx.reads:
            self.emit_binding(comp, target, prop.type, f"return {code};", value.text)
        else:
            comp.ctor_values.append(f"{target}.setValue({code});")

    def emit_binding(self, comp, target, typ, body, text):
        b = comp.uid("b")
        ct = cpp_type(typ)
        comp.members.append(f"mq::Binding<{ct}> {b};")
        comp.decls.append(f"static {ct} {b}_fn(void *ctx);")
        comment = (text or "").strip().rstrip(";").replace("*/", "* /").replace("\n", " ")
        comp.defs.append(f"// {comment}\n{ct} {comp.name}::{b}_fn(void *ctx)\n{{\n"
                         f"    auto *self = static_cast<{comp.name} *>(ctx);\n    (void)self;\n"
                         f"{indent(body, 1)}\n}}\n")
        comp.ctor_bindings.append(f"{b}.init(&{target}, self, &{comp.name}::{b}_fn);")
        comp.link_estimate += body.count(".get()") + 1

    def gen_block_body(self, ctx, block, ret):
        lines = self.stmts(ctx, block.body)
        if ret != "void":
            lines.append(f"return {default_value(ret)};")
        return "\n".join(lines)

    # ------------------------------------------------------------ anchors
    def gen_anchors(self, comp, o: Obj, anchors):
        if o.is_root:
            pass
        ctx = Ctx(comp, o)

        def margin(name, fallback="margins"):
            a = anchors.get(name) or anchors.get(fallback) if fallback else anchors.get(name)
            if a is None:
                return "0"
            c, t = self.value(ctx, a.value.node, "int")
            return "(" + self.conv(ctx, c, t, "int", a.value.node) + ")"

        def target_obj(a):
            v = self.expr(ctx, a.value.node)
            if v.kind != "obj":
                comp.err("anchor target must be an item (parent or a sibling id)", a.value.node)
            return v

        def is_parent(v: V):
            return v.dynamic_parent or (o.parent is not None and v.obj is o.parent)

        def line(a, horizontal):
            node = a.value.node
            if not isinstance(node, P.Member):
                comp.err("anchor line expected (e.g. parent.left)", node)
            tv = self.expr(ctx, node.obj)
            if tv.kind != "obj":
                comp.err("anchor target must be an item", node)
            valid = ("left", "right", "horizontalCenter") if horizontal else ("top", "bottom", "verticalCenter")
            if node.name not in valid:
                comp.err(f"invalid anchor line '{node.name}' here", node)
            base = "0" if is_parent(tv) else f"{tv.code}.{'x' if horizontal else 'y'}.get()"
            size = f"{tv.code}.{'width' if horizontal else 'height'}.get()"
            if node.name in ("left", "top"):
                return base
            if node.name in ("right", "bottom"):
                return f"{base} + {size}"
            return f"{base} + {size} / 2"

        out = {}
        if "fill" in anchors:
            t = target_obj(anchors["fill"])
            bx = "0" if is_parent(t) else f"{t.code}.x.get()"
            by = "0" if is_parent(t) else f"{t.code}.y.get()"
            lm, rm = margin("leftMargin"), margin("rightMargin")
            tm, bm = margin("topMargin"), margin("bottomMargin")
            out["x"] = f"{bx} + {lm}"
            out["y"] = f"{by} + {tm}"
            out["width"] = f"{t.code}.width.get() - {lm} - {rm}"
            out["height"] = f"{t.code}.height.get() - {tm} - {bm}"
        if "centerIn" in anchors:
            t = target_obj(anchors["centerIn"])
            bx = "0" if is_parent(t) else f"{t.code}.x.get()"
            by = "0" if is_parent(t) else f"{t.code}.y.get()"
            ho = margin("horizontalCenterOffset", None)
            vo = margin("verticalCenterOffset", None)
            out["x"] = f"{bx} + ({t.code}.width.get() - {o.member('width')}.get()) / 2 + {ho}"
            out["y"] = f"{by} + ({t.code}.height.get() - {o.member('height')}.get()) / 2 + {vo}"
        for horizontal, (lo, hi, mid, pos, size, off) in (
                (True, ("left", "right", "horizontalCenter", "x", "width", "horizontalCenterOffset")),
                (False, ("top", "bottom", "verticalCenter", "y", "height", "verticalCenterOffset"))):
            if lo in anchors or hi in anchors or mid in anchors:
                if pos in out:
                    comp.err(f"conflicting anchors on '{o.odef.type}'", line=o.odef.line)
                lom = margin(lo + "Margin")
                him = margin(hi + "Margin")
                if lo in anchors and hi in anchors:
                    L = line(anchors[lo], horizontal)
                    H = line(anchors[hi], horizontal)
                    out[pos] = f"{L} + {lom}"
                    out[size] = f"({H}) - {him} - ({L}) - {lom}"
                elif lo in anchors:
                    out[pos] = f"{line(anchors[lo], horizontal)} + {lom}"
                elif hi in anchors:
                    out[pos] = f"{line(anchors[hi], horizontal)} - {him} - {o.member(size)}.get()"
                else:
                    out[pos] = (f"{line(anchors[mid], horizontal)} - {o.member(size)}.get() / 2 + "
                                f"{margin(off, None)}")
        for k, code in out.items():
            self.emit_binding(comp, o.member(k), "int", f"return {code};", f"anchors -> {k}")
        return set(out)

    # ------------------------------------------------------------- handlers
    def handler_body(self, ctx, node, params):
        """Returns C++ statements for a handler script."""
        frame = {}
        if isinstance(node, P.FuncExpr):
            if len(node.params) > len(params):
                ctx.comp.err("handler declares more parameters than the signal provides", node)
            for i, pname in enumerate(node.params):
                frame[pname] = (params[i][1], "a_" + params[i][0])
            body = node.body
        else:
            for pname, ptype in params:
                frame[pname] = (ptype, "a_" + pname)
            body = node
        ctx.locals.append(frame)
        if isinstance(body, P.Block):
            lines = self.stmts(ctx, body.body)
        else:
            lines = self.stmts(ctx, [P.ExprStmt(body, line=body.line, col=body.col)])
        ctx.locals.pop()
        return "\n".join(lines)

    def gen_handler(self, comp, o: Obj, a):
        hname = a.path[0]
        base = hname[2].lower() + hname[3:]
        if not isinstance(a.value, P.Script):
            comp.err("handler must be a script", line=a.line, col=a.col)
        sig = o.type.find_signal(base)
        ctx = Ctx(comp, o, ret="void")
        if sig is not None:
            body = self.handler_body(ctx, a.value.node, sig.params)
            c = comp.uid("c")
            args = ", ".join(cpp_type(t) for _, t in sig.params)
            comp.members.append(f"mq::Connection<{args}> {c};")
            params = "".join(f", {cpp_type(t)} a_{n}" for n, t in sig.params)
            unused = "".join(f" (void)a_{n};" for n, _ in sig.params)
            comp.decls.append(f"static void {c}_fn(void *ctx{params});")
            comp.defs.append(f"// {hname}\nvoid {comp.name}::{c}_fn(void *ctx{params})\n{{\n"
                             f"    auto *self = static_cast<{comp.name} *>(ctx);\n    (void)self;{unused}\n"
                             f"{indent(body, 1)}\n}}\n")
            comp.ctor_handlers.append(f"{c}.connect({o.member(sig.cpp)}, self, &{comp.name}::{c}_fn);")
            return
        if base.endswith("Changed"):
            pname = base[:-7]
            prop = o.type.find_prop(pname)
            if prop is not None:
                body = self.handler_body(ctx, a.value.node, [])
                h = comp.uid("h")
                comp.members.append(f"mq::ChangeHandler {h};")
                comp.decls.append(f"static void {h}_fn(void *ctx);")
                comp.defs.append(f"// {hname}\nvoid {comp.name}::{h}_fn(void *ctx)\n{{\n"
                                 f"    auto *self = static_cast<{comp.name} *>(ctx);\n    (void)self;\n"
                                 f"{indent(body, 1)}\n}}\n")
                comp.ctor_handlers.append(f"{h}.init(&{o.member(prop.cpp)}, self, &{comp.name}::{h}_fn);")
                return
        comp.err(f"'{o.type.name}' has no signal '{base}' (handler {hname})", line=a.line, col=a.col)

    def gen_completed(self, comp, o, a):
        ctx = Ctx(comp, o, ret="void")
        body = self.handler_body(ctx, a.value.node, [])
        f = comp.uid("done")
        comp.decls.append(f"static void {f}_fn({comp.name} *self);")
        comp.defs.append(f"// Component.onCompleted\nvoid {comp.name}::{f}_fn({comp.name} *self)\n{{\n"
                         f"    (void)self;\n{indent(body, 1)}\n}}\n")
        comp.complete.append(f"{f}_fn(this);")

    def gen_function(self, comp, fd: P.FunctionDecl):
        m = comp.type.methods[fd.name]
        if m.generic:
            return   # specialized on demand for the argument types of each call
        ctx = Ctx(comp, comp.root, ret=m.ret)
        ctx.locals.append({n: (t, "a_" + n) for n, t in m.params})
        body = self.gen_block_body(ctx, fd.body, m.ret)
        params = ", ".join(f"{cpp_type(t)} a_{n}" for n, t in m.params)
        ret = cpp_type(m.ret)
        comp.decls.append(f"{ret} {m.cpp}({params});")
        unused = "".join(f" (void)a_{n};" for n, _ in m.params)
        comp.defs.append(f"// function {fd.name}\n{ret} {comp.name}::{m.cpp}({params})\n{{\n"
                         f"    auto *self = this;\n    (void)self;{unused}\n{indent(body, 1)}\n}}\n")

    # --------------------------------------------------------------- states
    def gen_states(self, comp, o: Obj, a, transitions):
        if not isinstance(a.value, list):
            comp.err("states must be a list of State objects", line=a.line, col=a.col)
        if not o.type.is_item:
            comp.err("states are only supported on items", line=a.line)
        names, whens = [], []
        changed = []          # (target object, PropInfo) touched by any state
        sid = comp.uid("st")
        for si, sdef in enumerate(a.value):
            if sdef.type != "State":
                comp.err("expected State", line=sdef.line, col=sdef.col)
            sname = None
            changes = []
            for sa in sdef.assignments:
                key = ".".join(sa.path)
                if key == "name":
                    if not isinstance(sa.value.node, P.Str):
                        comp.err("state name must be a string literal", sa.value.node)
                    sname = sa.value.node.value
                elif key == "when":
                    whens.append((si, sa.value))
                else:
                    comp.err(f"unsupported State property '{key}'", line=sa.line, col=sa.col)
            if sname is None:
                comp.err("State needs a name", line=sdef.line)
            names.append(sname)
            for pc in sdef.children:
                if pc.type != "PropertyChanges":
                    comp.err("only PropertyChanges is supported inside State", line=pc.line)
                target = None
                for pa in pc.assignments:
                    if pa.path == ["target"]:
                        n = pa.value.node
                        if not isinstance(n, P.Ident) or n.name not in comp.ids:
                            comp.err("PropertyChanges target must be an id", n)
                        target = comp.ids[n.name]
                for pa in pc.assignments:
                    if pa.path == ["target"]:
                        continue
                    path = pa.path
                    tgt = target
                    if path[0] in comp.ids and len(path) > 1:   # Qt 6 syntax: id.prop: value
                        tgt = comp.ids[path[0]]
                        path = path[1:]
                    if tgt is None:
                        comp.err("PropertyChanges needs a target", line=pa.line, col=pa.col)
                    pname = ".".join(path)
                    prop = tgt.type.find_prop(pname)
                    if prop is None:
                        comp.err(f"'{tgt.type.name}' has no property '{pname}'", line=pa.line, col=pa.col)
                    ctx = Ctx(comp, comp.root, ret=prop.type)
                    node = pa.value.node
                    if isinstance(node, P.Block):
                        body = self.gen_block_body(ctx, node, prop.type)
                    else:
                        c, t = self.value(ctx, node, prop.type)
                        body = f"return {self.conv(ctx, c, t, prop.type, node)};"
                    pcid = comp.uid("pc")
                    ct = cpp_type(prop.type)
                    comp.members.append(f"mq::PropertyChange<{ct}> {pcid};")
                    comp.link_estimate += body.count(".get()") + 1
                    comp.decls.append(f"static {ct} {pcid}_fn(void *ctx);")
                    comp.defs.append(f"// state '{sname}': {pname}\n{ct} {comp.name}::{pcid}_fn(void *ctx)\n{{\n"
                                     f"    auto *self = static_cast<{comp.name} *>(ctx);\n    (void)self;\n"
                                     f"{indent(body, 1)}\n}}\n")
                    comp.ctor_states.append(f"{pcid}.init(&{tgt.member(prop.cpp)}, self, &{comp.name}::{pcid}_fn);")
                    changes.append(pcid)
                    if not any(t is tgt and p.cpp == prop.cpp for t, p in changed):
                        changed.append((tgt, prop))
            arr = f"{sid}_s{si}"
            if changes:
                comp.members.append(f"mq::PropertyChangeBase *{arr}[{len(changes)}];")
                for i, c in enumerate(changes):
                    comp.ctor_states.append(f"{arr}[{i}] = &{c};")
            when = "nullptr"
            for wi, script in whens:
                if wi != si:
                    continue
                when = f"&{sid}_w{si}"
                comp.members.append(f"mq::Property<bool> {sid}_w{si};")
                comp.members.append(f"mq::ChangeHandler {sid}_wh{si};")
                ctx = Ctx(comp, o, ret="bool")
                c, t = self.value(ctx, script.node, "bool")
                self.emit_binding(comp, f"self->{sid}_w{si}", "bool",
                                  f"return {self.conv(ctx, c, t, 'bool', script.node)};",
                                  f"State '{sname}' when")
                comp.ctor_states.append(f"{sid}_wh{si}.init(&{sid}_w{si}, &{sid}_group, "
                                        f"&mq::StateGroup::whenChanged);")
            comp.ctor_states.append(f"{sid}[{si}] = mq::State{{{cstr(sname)}, "
                                    f"{arr if changes else 'nullptr'}, {len(changes)}, {when}}};")
        comp.members.append(f"mq::State {sid}[{len(names)}];")
        comp.members.append(f"mq::StateGroup {sid}_group;")
        if transitions is not None:
            self.gen_transitions(comp, o, sid, transitions, changed)
        comp.ctor_states.append(f"{sid}_group.init(&{o.member('state')}, {sid}, {len(names)});")

    # ---------------------------------------------------------- transitions
    def const_of(self, comp, odef, name, default):
        for a in odef.assignments:
            if ".".join(a.path) != name:
                continue
            n = a.value.node if isinstance(a.value, P.Script) else None
            if isinstance(n, P.Num):
                return n.value
            if isinstance(n, P.Bool):
                return n.value
            if isinstance(n, P.Str):
                return n.value
            if isinstance(n, P.Member) and isinstance(n.obj, P.Ident) and n.obj.name == "Easing":
                if n.name not in self.types["Easing"].enums:
                    comp.err(f"unknown easing '{n.name}'", n)
                return self.types["Easing"].enums[n.name]
            comp.err(f"'{name}' must be a constant here", line=a.line, col=a.col)
        return default

    def gen_transitions(self, comp, o, sid, a, changed):
        if not isinstance(a.value, list):
            comp.err("transitions must be a list of Transition objects", line=a.line)
        tid = sid + "_tr"
        entries = []
        for ti, tdef in enumerate(a.value):
            if tdef.type != "Transition":
                comp.err("expected Transition", line=tdef.line, col=tdef.col)
            frm = self.const_of(comp, tdef, "from", "*")
            to = self.const_of(comp, tdef, "to", "*")
            rev = bool(self.const_of(comp, tdef, "reversible", False))
            for ta in tdef.assignments:
                if ".".join(ta.path) not in ("from", "to", "reversible"):
                    comp.err(f"unsupported Transition property '{'.'.join(ta.path)}'", line=ta.line)
            leaves = []

            def walk(node, start):
                kind = node.type
                if kind in ("NumberAnimation", "ColorAnimation", "PauseAnimation"):
                    d = int(self.const_of(comp, node, "duration", 250))
                    if kind != "PauseAnimation":
                        leaves.append((node, start, d))
                    return d
                if kind in ("SequentialAnimation", "ParallelAnimation"):
                    t, longest = start, 0
                    for c in node.children:
                        d = walk(c, t if kind == "SequentialAnimation" else start)
                        if kind == "SequentialAnimation":
                            t += d
                        longest = max(longest, d)
                    return t - start if kind == "SequentialAnimation" else longest
                comp.err(f"{kind} is not supported in a Transition", line=node.line)
            for c in tdef.children:
                walk(c, 0)
            tracks = []
            for leaf, delay, dur in leaves:
                props = self.const_of(comp, leaf, "properties", None) or self.const_of(comp, leaf, "property", None)
                names = [p.strip() for p in props.split(",")] if props else None
                targets = None
                for la in leaf.assignments:
                    if la.path in (["target"], ["targets"]):
                        n = la.value.node
                        items = n.items if isinstance(n, P.ArrayLit) else [n]
                        targets = []
                        for it in items:
                            if not isinstance(it, P.Ident) or it.name not in comp.ids:
                                comp.err("animation targets must be ids", it)
                            targets.append(comp.ids[it.name])
                is_color = leaf.type == "ColorAnimation"
                for tgt, prop in changed:
                    if names is not None and prop.name not in names:
                        continue
                    if targets is not None and tgt not in targets:
                        continue
                    if is_color != (prop.type == "color"):
                        continue
                    if not is_color and prop.type not in NUMERIC:
                        continue
                    k = comp.uid("ta")
                    acpp = "mq::ColorAnimation" if is_color else "mq::NumberAnimation"
                    comp.members.append(f"{acpp} {k};")
                    comp.members.append(f"mq::TransitionTrack<{cpp_type(prop.type)}, {acpp}> {k}_track;")
                    comp.ctor_states.append(f"{k}.duration.setValue({dur});")
                    easing = self.const_of(comp, leaf, "easing.type", None)
                    if easing:
                        comp.ctor_states.append(f"{k}.easing_type.setValue({easing});")
                    if delay:
                        comp.ctor_states.append(f"{k}.setStartDelay({delay});")
                    comp.ctor_states.append(f"{k}_track.init(&{tgt.member(prop.cpp)}, &{k});")
                    comp.extra_complete.append(f"{k}.componentComplete();")
                    tracks.append(f"&{k}_track")
            arr = f"{tid}{ti}_tracks"
            if tracks:
                comp.members.append(f"mq::TransitionTrackBase *{arr}[{len(tracks)}];")
                for i, t in enumerate(tracks):
                    comp.ctor_states.append(f"{arr}[{i}] = {t};")
            entries.append(f"mq::Transition{{{cstr(str(frm))}, {cstr(str(to))}, {'true' if rev else 'false'}, "
                           f"{arr if tracks else 'nullptr'}, {len(tracks)}}}")
        comp.members.append(f"mq::Transition {tid}[{len(entries)}];")
        for i, e in enumerate(entries):
            comp.ctor_states.append(f"{tid}[{i}] = {e};")
        comp.ctor_states.append(f"{sid}_group.setTransitions({tid}, {len(entries)});")

    # ============================================================ JS -> C++
    def stmts(self, ctx, body):
        out = []
        for s in body:
            out.extend(self.stmt(ctx, s))
        return out

    def stmt(self, ctx, s) -> List[str]:
        comp = ctx.comp
        if isinstance(s, P.Empty):
            return []
        if isinstance(s, P.Block):
            ctx.locals.append({})
            inner = self.stmts(ctx, s.body)
            ctx.locals.pop()
            return ["{"] + ["    " + l for l in inner] + ["}"]
        if isinstance(s, P.ExprStmt):
            return [self.effect(ctx, s.expr) + ";"]
        if isinstance(s, P.VarDecl):
            if s.init is None:
                comp.err(f"variable '{s.name}' needs an initial value (its type is inferred from it)", s)
            code, t = self.value(ctx, s.init)
            if isinstance(t, ObjType):
                comp.err("object references in variables are not supported", s)
            cname = "l_" + s.name
            ctx.locals[-1][s.name] = (t, cname)
            const = "const " if s.kind == "const" else ""
            return [f"{const}{cpp_type(t)} {cname} = {code};"]
        if isinstance(s, P.If):
            c = self.cond(ctx, s.test)
            out = [f"if ({c}) {{"] + self.sub(ctx, s.then) + ["}"]
            if s.other is not None:
                if isinstance(s.other, P.If):
                    rest = self.stmt(ctx, s.other)
                    out[-1] = "} else " + rest[0]
                    out.extend(rest[1:])
                else:
                    out[-1] = "} else {"
                    out += self.sub(ctx, s.other) + ["}"]
            return out
        if isinstance(s, P.While):
            return [f"while ({self.cond(ctx, s.test)}) {{"] + self.sub(ctx, s.body) + ["}"]
        if isinstance(s, P.For):
            ctx.locals.append({})
            init = ""
            if isinstance(s.init, P.VarDecl):
                init = self.stmt(ctx, s.init)[0].rstrip(";")
            elif s.init is not None:
                init = self.effect(ctx, s.init.expr)
            test = self.cond(ctx, s.test) if s.test is not None else ""
            upd = self.effect(ctx, s.update) if s.update is not None else ""
            out = [f"for ({init}; {test}; {upd}) {{"] + self.sub(ctx, s.body) + ["}"]
            ctx.locals.pop()
            return out
        if isinstance(s, P.Return):
            if ctx.ret == "?":
                if s.value is None:
                    return ["return;"]
                code, t = self.value(ctx, s.value)
                ctx.returns.append(t)
                return [f"return {code};"]
            if ctx.ret in (None, "void"):
                if s.value is not None:
                    comp.err("cannot return a value here", s)
                return ["return;"]
            if s.value is None:
                comp.err("a value must be returned", s)
            code, t = self.value(ctx, s.value, ctx.ret)
            return [f"return {self.conv(ctx, code, t, ctx.ret, s.value)};"]
        if isinstance(s, P.Jump):
            return [s.kind + ";"]
        comp.err("unsupported statement", s)

    def sub(self, ctx, s):
        ctx.locals.append({})
        if isinstance(s, P.Block):
            out = self.stmts(ctx, s.body)
        else:
            out = self.stmt(ctx, s)
        ctx.locals.pop()
        return ["    " + l for l in out]

    def cond(self, ctx, node):
        code, t = self.value(ctx, node, "bool")
        return self.to_bool(code, t)

    def to_bool(self, code, t):
        if t == "bool":
            return code
        if t in ("int", "real", "string"):
            return f"mq::js::truthy({code})"
        return f"({code}) != nullptr"

    # side-effect expressions (statements)
    def effect(self, ctx, e) -> str:
        comp = ctx.comp
        if isinstance(e, P.Assign):
            value = e.value
            if e.op != "=":
                value = P.Binary(e.op[0], e.target, e.value, line=e.line, col=e.col)
            return self.assign(ctx, e.target, value)
        if isinstance(e, P.Update):
            value = P.Binary("+" if e.op == "++" else "-", e.target, P.Num(1, line=e.line, col=e.col),
                             line=e.line, col=e.col)
            return self.assign(ctx, e.target, value)
        if isinstance(e, P.Call):
            return self.call(ctx, e, statement=True)[0]
        code, _ = self.value(ctx, e)
        return f"(void)({code})"

    def assign(self, ctx, target_node, value_node) -> str:
        comp = ctx.comp
        tv = self.expr(ctx, target_node)
        if tv.kind == "local":
            code, t = self.value(ctx, value_node, tv.type)
            return f"{tv.code} = {self.conv(ctx, code, t, tv.type, value_node)}"
        if tv.kind != "prop":
            comp.err("left side of assignment is not a property or variable", target_node)
        if tv.prop.readonly:
            comp.err(f"property '{tv.prop.name}' is read-only", target_node)
        code, t = self.value(ctx, value_node, tv.prop.type)
        code = self.conv(ctx, code, t, tv.prop.type, value_node)
        return f"{tv.owner}.{tv.prop.cpp}.set({code})"

    # rvalue
    def value(self, ctx, node, expect=None):
        v = self.expr(ctx, node, expect)
        return self.rvalue(ctx, v, node)

    def rvalue(self, ctx, v: V, node):
        if v.kind == "val":
            return v.code, v.type
        if v.kind == "local":
            return v.code, v.type
        if v.kind == "prop":
            ctx.reads = True
            return f"{v.owner}.{v.prop.cpp}.get()", v.prop.type
        if v.kind == "obj":
            ctx.comp.err("an object cannot be used as a value here", node)
        ctx.comp.err(f"'{v.name or v.code}' cannot be used as a value", node)

    def conv(self, ctx, code, frm, to, node):
        comp = ctx.comp
        if to is None or frm == to:
            return code
        if frm == "int" and to == "real":
            return f"mq::real({code})"
        if frm == "real" and to == "int":
            return f"int({code})"
        if to == "string" and frm in ("int", "real", "bool"):
            return f"mq::toString({code})"
        if to == "bool" and frm in ("int", "real", "string"):
            return self.to_bool(code, frm)
        if to in ("int", "real") and frm == "bool":
            return f"{cpp_type(to)}({code})"
        if to == "color" and frm == "string":
            return f"mq::Color::fromString({code})"
        if to == "image" and frm == "string":
            return f"mq::imageForPath({code})"
        comp.err(f"cannot convert {self.tname(frm)} to {self.tname(to)}", node)

    @staticmethod
    def tname(t):
        return t.name if isinstance(t, ObjType) else t

    def literal_string(self, ctx, node, expect):
        s = node.value
        comp = ctx.comp
        if expect == "color":
            c = parse_color(s)
            if c is None:
                comp.err(f"invalid color '{s}'", node)
            return V("val", f"mq::Color(0x{c:08x}u)", "color")
        if expect == "image":
            base = os.path.dirname(os.path.abspath(comp.file))
            path = os.path.normpath(os.path.join(base, s.replace("qrc:/", "").replace("file:", "")))
            if not os.path.exists(path):
                comp.err(f"image not found: {path}", node)
            return V("val", f"&{self.add_image(path)}", "image")
        return V("val", f"mq::String::lit({cstr(s)})", "string", lit=s)

    IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif")

    def add_image(self, path):
        """Embeds an image; returns its symbol. Keys are relative to the main QML file."""
        path = os.path.normpath(os.path.abspath(path))
        sym = self.images.get(path)
        if sym is None:
            rel = os.path.relpath(path, os.path.dirname(os.path.abspath(self.main_file)))
            sym = "mq_img_" + sanitize(os.path.splitext(rel)[0])
            while sym in self.images.values():
                sym += "_"
            self.images[path] = sym
        return sym

    def expr(self, ctx, node, expect=None) -> V:
        comp = ctx.comp
        if isinstance(node, P.Num):
            if isinstance(node.value, float):
                r = repr(node.value)
                return V("val", r + "f" if ("." in r or "e" in r) else r + ".0f", "real")
            return V("val", str(node.value), "int")
        if isinstance(node, P.Str):
            return self.literal_string(ctx, node, expect)
        if isinstance(node, P.Bool):
            return V("val", "true" if node.value else "false", "bool")
        if isinstance(node, P.Ident):
            return self.ident(ctx, node)
        if isinstance(node, P.Member):
            return self.member(ctx, node)
        if isinstance(node, P.Call):
            code, t = self.call(ctx, node)
            if t == "void":
                comp.err("function returns nothing", node)
            return V("val", code, t)
        if isinstance(node, P.Unary):
            code, t = self.value(ctx, node.expr, expect if node.op != "!" else None)
            if node.op == "!":
                return V("val", f"!({self.to_bool(code, t)})", "bool")
            if t not in NUMERIC:
                comp.err(f"operator {node.op} needs a number", node)
            if node.op == "~":
                return V("val", f"~int({code})", "int")
            return V("val", f"({node.op}{code})" if node.op == "-" else code, t)
        if isinstance(node, P.Binary):
            return self.binary(ctx, node, expect)
        if isinstance(node, P.Cond):
            c = self.cond(ctx, node.test)
            a, ta = self.value(ctx, node.then, expect)
            b, tb = self.value(ctx, node.other, expect)
            if ta != tb and expect is not None and expect in (ta, tb):
                t = expect
            else:
                t = self.unify(ctx, ta, tb, node)
            return V("val", f"({c} ? {self.conv(ctx, a, ta, t, node)} : {self.conv(ctx, b, tb, t, node)})", t)
        if isinstance(node, (P.Assign, P.Update)):
            comp.err("assignments are only allowed as statements", node)
        if isinstance(node, P.ArrayLit):
            return self.array_literal(ctx, node, expect)
        if isinstance(node, P.Index):
            code, t = self.value(ctx, node.obj)
            if not is_array(t):
                comp.err("only arrays can be indexed", node)
            i, ti = self.value(ctx, node.index, "int")
            i = self.conv(ctx, i, ti, "int", node.index)
            et = elem_type(t)
            v = f"({code}).at({i})"
            if et == "string":
                v = f"mq::String::lit({v})"
            return V("val", v, et)
        if isinstance(node, P.FuncExpr):
            comp.err("function expressions are only allowed as signal handlers", node)
        comp.err("unsupported expression", node)

    def array_literal(self, ctx, node, expect):
        comp = ctx.comp
        want = elem_type(expect) if is_array(expect) else None
        vals, et = [], want
        for item in node.items:
            n, neg = item, False
            if isinstance(n, P.Unary) and n.op == "-" and isinstance(n.expr, P.Num):
                n, neg = n.expr, True
            if isinstance(n, P.Str):
                if want == "color":
                    c = parse_color(n.value)
                    if c is None:
                        comp.err(f"invalid color '{n.value}'", n)
                    vals.append((f"mq::Color(0x{c:08x}u)", "color"))
                else:
                    vals.append((cstr(n.value), "string"))
            elif isinstance(n, P.Bool):
                vals.append(("true" if n.value else "false", "bool"))
            elif isinstance(n, P.Num):
                v = -n.value if neg else n.value
                vals.append((f"{float(v)!r}f", "real") if isinstance(v, float) else (str(v), "int"))
            else:
                comp.err("array elements must be literals (arrays are constant data)", item)
        for _, t in vals:
            if et is None:
                et = t
            elif et != t:
                if {et, t} <= {"int", "real"}:
                    et = "real"
                else:
                    comp.err(f"array mixes {et} and {t} elements", node)
        if et is None:
            et = want or "int"
        if et == "real":
            vals = [(c if t == "real" else f"{c}.0f", t) for c, t in vals]
        key = (et, tuple(c for c, _ in vals))
        sym = self.arrays.get(key)
        if sym is None:
            sym = f"mq_array_{len(self.arrays) + 1}"
            self.arrays[key] = sym
            decl = "static const char *const" if et == "string" else f"static const {elem_cpp(et)}"
            self.array_defs.append(f"{decl} {sym}[{max(len(vals), 1)}] = "
                                   f"{{{', '.join(c for c, _ in vals) or '{}'}}};")
        return V("val", f"mq::ConstArray<{elem_cpp(et)}>({sym}, {len(vals)})", f"array:{et}")

    def unify(self, ctx, a, b, node):
        if a == b:
            return a
        if a in NUMERIC and b in NUMERIC:
            return "real"
        ctx.comp.err(f"incompatible types {self.tname(a)} and {self.tname(b)}", node)

    def binary(self, ctx, node, expect):
        op = node.op
        comp = ctx.comp
        if op in ("&&", "||"):
            if expect != "bool":
                # JS semantics: the result is one of the operands (a || b, a && b)
                a, ta = self.value(ctx, node.left, expect)
                b, tb = self.value(ctx, node.right, expect if expect else ta)
                if ta == tb and ta in ("int", "real", "string") or (ta in NUMERIC and tb in NUMERIC and ta != tb):
                    t = ta if ta == tb else "real"
                    a, b = self.conv(ctx, a, ta, t, node), self.conv(ctx, b, tb, t, node)
                    ct = cpp_type(t)
                    pick = "t_ : " + f"{ct}({b})" if op == "||" else f"{ct}({b}) : t_"
                    return V("val", f"[&]() -> {ct} {{ {ct} t_ = {a}; return mq::js::truthy(t_) ? {pick}; }}()", t)
            a = self.cond(ctx, node.left)
            b = self.cond(ctx, node.right)
            return V("val", f"({a} {op} {b})", "bool")
        if op in ("==", "!=", "===", "!=="):
            cop = "==" if op in ("==", "===") else "!="
            # literal on the left: evaluate the other side first to know its type
            if isinstance(node.left, P.Str):
                b, tb = self.value(ctx, node.right)
                a, ta = self.value(ctx, node.left, tb)
            else:
                a, ta = self.value(ctx, node.left)
                b, tb = self.value(ctx, node.right, ta)
            if ta != tb:
                if ta in NUMERIC and tb in NUMERIC:
                    a, b = self.conv(ctx, a, ta, "real", node), self.conv(ctx, b, tb, "real", node)
                else:
                    comp.err(f"cannot compare {self.tname(ta)} with {self.tname(tb)}", node)
            return V("val", f"({a} {cop} {b})", "bool")
        a, ta = self.value(ctx, node.left)
        b, tb = self.value(ctx, node.right)
        if op == "+" and ("string" in (ta, tb)):
            for t, n in ((ta, node.left), (tb, node.right)):
                if t not in ("string", "int", "real", "bool"):
                    comp.err(f"cannot concatenate {self.tname(t)}", n)
            left = a if ta == "string" else f"mq::toString({a})"
            return V("val", f"({left} + {b})", "string")
        if ta not in NUMERIC or tb not in NUMERIC:
            if op in ("<", ">", "<=", ">=") and ta == tb == "string":
                comp.err("string ordering is not supported", node)
            comp.err(f"operator {op} needs numbers (got {self.tname(ta)} and {self.tname(tb)})", node)
        if op in ("<", ">", "<=", ">="):
            return V("val", f"({a} {op} {b})", "bool")
        if op == "/":
            return V("val", f"mq::js::div({self.conv(ctx, a, ta, 'real', node)}, "
                            f"{self.conv(ctx, b, tb, 'real', node)})", "real")
        t = "int" if ta == tb == "int" else "real"
        a, b = self.conv(ctx, a, ta, t, node), self.conv(ctx, b, tb, t, node)
        if op == "%":
            return V("val", f"mq::js::mod({a}, {b})", t)
        if op in ("&", "|", "^"):
            return V("val", f"(int({a}) {op} int({b}))", "int")
        return V("val", f"({a} {op} {b})", t)

    # --------------------------------------------------------------- names
    def obj_value(self, o: Obj):
        return V("obj", o.access(), o.type, obj=o)

    def members_of(self, owner_code, otype: ObjType, name, node=None):
        prop = otype.find_prop(name)
        if prop is not None:
            return V("prop", owner=owner_code, prop=prop, type=prop.type, name=name)
        if otype.has_group(name):
            return V("group", owner=owner_code, type=otype, name=name)
        sig = otype.find_signal(name)
        if sig is not None:
            return V("signal", owner=owner_code, info=sig, name=name)
        m = otype.find_method(name)
        if m is not None:
            return V("method", owner=owner_code, info=m, name=name)
        return None

    def ident(self, ctx, node) -> V:
        name = node.name
        comp = ctx.comp
        loc = ctx.lookup_local(name)
        if loc is not None:
            return V("local", loc[1], loc[0], name=name)
        if name in comp.ids:
            return self.obj_value(comp.ids[name])
        scope = ctx.scope
        v = self.members_of(scope.access() if not scope.is_root else "(*self)", scope.type, name)
        if v is not None:
            return self.fix_owner(v, scope)
        if not scope.is_root:
            v = self.members_of("(*self)", comp.root.type, name)
            if v is not None:
                return self.fix_owner(v, comp.root)
        if name == "parent":
            return self.parent_of(ctx, scope)
        if name == "model" and comp.outer is not None:
            return V("model", name="model")
        # delegates see the ids and root properties of the enclosing component(s)
        outer, prefix = comp.outer, "self->outer"
        while outer is not None:
            if name in outer.ids:
                o = outer.ids[name]
                code = f"(*{prefix})" if o.is_root else f"{prefix}->{o.name}"
                return V("obj", code, o.type, obj=o)
            v = self.members_of(f"(*{prefix})", outer.root.type, name)
            if v is not None:
                return v
            outer, prefix = outer.outer, prefix + "->outer"
        if name in ("Math", "Qt", "console") or name in self.types:
            return V("type", name=name)
        if name in ("parseInt", "parseFloat"):
            return V("type", name=name)
        comp.err(f"unknown name '{name}'", node)

    def fix_owner(self, v: V, o: Obj):
        # use 'self->member' form for readability
        if o.is_root:
            v.owner = "(*self)"
        return v

    def parent_of(self, ctx, o: Obj) -> V:
        if o.parent is not None:
            return self.obj_value(o.parent)
        ctx.reads = True
        return V("obj", "mq::Item::orDummy(self->parent.get())", self.types["Item"], dynamic_parent=True)

    def member(self, ctx, node) -> V:
        comp = ctx.comp
        base = self.expr(ctx, node.obj)
        name = node.name
        if base.kind == "type" and base.name in ("ListView", "GridView") and name in ("isCurrentItem", "view"):
            # attached properties inside a delegate
            c = comp
            while c is not None and not (getattr(c, "view", None) is not None
                                         and c.view.type.name in ("ListView", "GridView")):
                c = c.outer
            if c is None or c.outer is None:
                comp.err(f"{base.name}.{name} is only available inside a view delegate", node)
            hops = "self"
            cc = comp
            while cc is not c:
                hops += "->outer"
                cc = cc.outer
            view = c.view
            vcode = f"(*{hops}->outer)" if view.is_root else f"{hops}->outer->{view.name}"
            if name == "view":
                return V("obj", vcode, view.type, obj=view)
            ctx.reads = True
            idx = c.type.find_prop("index").cpp
            return V("val", f"({hops}->{idx}.get() == {vcode}.currentIndex.get())", "bool")
        if base.kind == "type":
            if base.name == "Math":
                if name == "PI":
                    return V("val", "mq::js::kPi", "real")
                return V("type", name="Math." + name)
            if base.name in ("Qt", "console"):
                return V("type", name=f"{base.name}.{name}")
            t = self.types.get(base.name)
            if t is not None and name in t.enums:
                return V("val", t.enums[name], "int")
            comp.err(f"unknown member '{base.name}.{name}'", node)
        if base.kind == "model":
            prop = comp.type.find_prop(name)
            if prop is None:
                comp.err(f"the model has no role '{name}'", node)
            return V("prop", owner="(*self)", prop=prop, type=prop.type, name=name)
        if base.kind == "obj":
            if name == "parent" and base.obj is not None and base.obj.comp is comp:
                return self.parent_of(ctx, base.obj)
            if name == "item" and base.type.inherits("Loader"):
                ctx.reads = True
                return V("obj", f"mq::Item::orDummy({base.code}.item.get())", self.types["Item"],
                         dynamic_parent=True)
            v = self.members_of(base.code, base.type, name)
            if v is None:
                comp.err(f"'{base.type.name}' has no member '{name}'", node)
            v.obj = base.obj
            return v
        if base.kind == "group":
            prop = base.type.find_prop(f"{base.name}.{name}")
            if prop is None:
                comp.err(f"unknown property '{base.name}.{name}'", node)
            return V("prop", owner=base.owner, prop=prop, type=prop.type, name=prop.name)
        if base.kind == "val" and isinstance(base.type, RowType):
            rt = dict(base.type.info["roles"]).get(name)
            if rt is None:
                comp.err(f"the model has no role '{name}'", node)
            return V("val", self.role_value(base.type.info, base.code, name, rt), rt)
        # members of values
        code, t = self.rvalue(ctx, base, node.obj)
        if t == "string" and name == "length":
            return V("val", f"({code}).charCount()", "int")
        if is_array(t) and name == "length":
            return V("val", f"({code}).size()", "int")
        if t in ("string", "int", "real", "color", "bool"):
            return V("method", owner=code, info=t, name=name, type="valuemethod")
        comp.err(f"unknown member '{name}'", node)

    # --------------------------------------------------------------- calls
    def args(self, ctx, nodes, types, node):
        if len(nodes) != len(types):
            ctx.comp.err(f"expected {len(types)} argument(s), got {len(nodes)}", node)
        out = []
        for n, t in zip(nodes, types):
            c, ct = self.value(ctx, n, t)
            out.append(self.conv(ctx, c, ct, t, n))
        return out

    def call(self, ctx, node, statement=False):
        comp = ctx.comp
        fn = self.expr(ctx, node.fn)
        if fn.kind == "type":
            return self.builtin_call(ctx, fn.name, node)
        if fn.kind == "signal":
            sig = fn.info
            a = self.args(ctx, node.args, [t for _, t in sig.params], node)
            return f"{fn.owner}.{sig.cpp}.fire({', '.join(a)})", "void"
        if fn.kind == "method":
            if fn.type == "valuemethod":
                return self.value_method(ctx, fn, node)
            if fn.obj is not None and fn.obj.type.name == "ListModel":
                return self.model_call(ctx, fn, node)
            m = fn.info
            ctx.reads = True    # the function may read properties
            if m.generic:
                if len(node.args) > len(m.params):
                    comp.err(f"too many arguments for '{m.name}'", node)
                codes, types = [], []
                for i, (pname, ptype) in enumerate(m.params):
                    if i >= len(node.args):
                        comp.err(f"missing argument '{pname}' for '{m.name}'", node)
                    c, t = self.value(ctx, node.args[i], ptype)
                    if ptype is not None:
                        c, t = self.conv(ctx, c, t, ptype, node.args[i]), ptype
                    if isinstance(t, ObjType):
                        comp.err("objects cannot be passed to functions", node.args[i])
                    codes.append(c)
                    types.append(t)
                cpp, ret = self.specialize(m, tuple(types), node, ctx.comp)
                return f"{fn.owner}.{cpp}({', '.join(codes)})", ret
            params = [t for _, t in m.params]
            if m.min_args >= 0 and m.min_args <= len(node.args) < len(params):
                params = params[:len(node.args)]
            a = self.args(ctx, node.args, params, node)
            return f"{fn.owner}.{m.cpp}({', '.join(a)})", m.ret
        comp.err("not a function", node)

    def model_call(self, ctx, fn, node):
        comp, o = ctx.comp, fn.obj
        info = o.model
        name = fn.name
        prefix = fn.owner[:-len(o.name)] if fn.owner.endswith(o.name) else None
        if not info["mutable"] and name != "get" or prefix is None:
            comp.err(f"ListModel.{name}() is not supported here", node)
        roles = dict(info["roles"])
        if info["mutable"]:
            rows, size = prefix + info["sym"], prefix + info["size"]
        else:
            rows, size = info["sym"], str(info["count"])
        changed = f"{fn.owner}.changed({size})"

        def arg(i, t):
            if i >= len(node.args):
                comp.err(f"ListModel.{name}() needs more arguments", node)
            c, ct = self.value(ctx, node.args[i], t)
            return self.conv(ctx, c, ct, t, node.args[i])

        def row_from(obj_node):
            if not isinstance(obj_node, P.ObjectLit):
                comp.err("expected an object literal: {role: value, ...}", obj_node)
            given = {}
            for k, vnode in obj_node.props:
                if k not in roles:
                    comp.err(f"the model has no role '{k}'", vnode)
                c, ct = self.value(ctx, vnode, roles[k])
                given[k] = self.conv(ctx, c, ct, roles[k], vnode)
            return given

        if name == "get":
            i = arg(0, "int")
            if info["mutable"]:
                ctx.reads = True   # bindings using get() follow the model's changes
                return f"((void){fn.owner}.revision.get(), mq::js::listAt({rows}, {size}, {i}))", RowType(info)
            return f"{rows}[mq::clamp({i}, 0, {max(info['count'] - 1, 0)})]", RowType(info)
        if name in ("append", "insert"):
            at = size if name == "append" else arg(0, "int")
            obj_node = node.args[0 if name == "append" else 1] if len(node.args) > (0 if name == "append" else 1) \
                else comp.err(f"ListModel.{name}() needs an object", node)
            given = row_from(obj_node)
            init = ", ".join(given.get(r, f"{self.role_cpp(t, True)}{{}}") for r, t in info["roles"])
            return (f"{{ mq::js::listInsert({rows}, {size}, {at}, {o.comp.name}::{info['struct']}{{{init}}}); "
                    f"{changed}; }}"), "void"
        if name == "remove":
            i = arg(0, "int")
            n = arg(1, "int") if len(node.args) > 1 else "1"
            return f"{{ mq::js::listRemove({rows}, {size}, {i}, {n}); {changed}; }}", "void"
        if name == "clear":
            return f"{{ mq::js::listRemove({rows}, {size}, 0, {size}); {changed}; }}", "void"
        if name == "move":
            a, b = arg(0, "int"), arg(1, "int")
            n = arg(2, "int") if len(node.args) > 2 else "1"
            return f"{{ mq::js::listMove({rows}, {size}, {a}, {b}, {n}); {changed}; }}", "void"
        if name == "set":
            i = arg(0, "int")
            given = row_from(node.args[1] if len(node.args) > 1 else None)
            sets = " ".join(f"r_.{k} = {v};" for k, v in given.items())
            return f"{{ auto &r_ = mq::js::listAt({rows}, {size}, {i}); {sets} {changed}; }}", "void"
        if name == "setProperty":
            i = arg(0, "int")
            if len(node.args) < 3 or not isinstance(node.args[1], P.Str):
                comp.err("setProperty(index, \"role\", value): the role must be a string literal", node)
            role = node.args[1].value
            if role not in roles:
                comp.err(f"the model has no role '{role}'", node.args[1])
            v = arg(2, roles[role])
            return f"{{ mq::js::listAt({rows}, {size}, {i}).{role} = {v}; {changed}; }}", "void"
        comp.err(f"ListModel.{name}() is not supported", node)

    def specialize(self, m, types, node, caller):
        """Generates (once) the version of a QML function for these argument types."""
        if types in m.specs:
            cpp, ret = m.specs[types]
            if ret is None:
                caller.err(f"recursive function '{m.name}' needs a return type annotation "
                           f"(function {m.name}(...): int)", node)
            return cpp, ret
        comp, fd = m.owner, m.decl
        all_typed = all(t is not None for _, t in m.params)
        cpp = m.cpp if all_typed else m.cpp + "__" + "_".join(sanitize(t.replace(":", "_")) for t in types)
        m.specs[types] = (cpp, m.ret)
        params = [(n, t) for (n, _), t in zip(m.params, types)]
        ret = m.ret
        if ret is None:
            # pass 1: infer the return type from the return statements
            ctx = Ctx(comp, comp.root, ret="?")
            ctx.returns = []
            ctx.locals.append({n: (t, "a_" + n) for n, t in params})
            self.stmts(ctx, fd.body.body)
            ret = "void"
            for t in ctx.returns:
                ret = t if ret == "void" else self.unify(ctx, ret, t, fd)
        m.specs[types] = (cpp, ret)
        ctx = Ctx(comp, comp.root, ret=ret)
        ctx.locals.append({n: (t, "a_" + n) for n, t in params})
        body = self.gen_block_body(ctx, fd.body, ret)
        plist = ", ".join(f"{cpp_type(t)} a_{n}" for n, t in params)
        rc = cpp_type(ret)
        comp.decls.append(f"{rc} {cpp}({plist});")
        unused = "".join(f" (void)a_{n};" for n, _ in params)
        comp.defs.append(f"// function {fd.name}({', '.join(self.tname(t) for t in types)})\n"
                         f"{rc} {comp.name}::{cpp}({plist})\n{{\n"
                         f"    auto *self = this;\n    (void)self;{unused}\n{indent(body, 1)}\n}}\n")
        return cpp, ret

    def value_method(self, ctx, fn, node):
        comp = ctx.comp
        t, code, name = fn.info, fn.owner, fn.name
        if name == "toString" and not node.args:
            return (code if t == "string" else f"mq::toString({code})"), "string"
        if name == "toFixed" and t in NUMERIC:
            a = self.args(ctx, node.args, ["int"], node)
            return f"mq::js::toFixed(mq::real({code}), {a[0]})", "string"
        if t == "color" and name in ("lighter", "darker"):
            a = self.args(ctx, node.args, ["real"], node) if node.args else []
            return f"({code}).{name}({', '.join(a)})", "color"
        if t == "string" and name in ("toUpperCase", "toLowerCase", "indexOf", "substring", "slice"):
            comp.err(f"string method '{name}' is not supported", node)
        comp.err(f"unknown method '{name}'", node)

    def builtin_call(self, ctx, name, node):
        comp = ctx.comp
        if name == "console.log" or name in ("console.info", "console.debug", "console.warn"):
            parts = []
            for i, n in enumerate(node.args):
                c, t = self.value(ctx, n)
                if t not in ("string", "int", "real", "bool"):
                    comp.err(f"cannot log a {self.tname(t)}", n)
                parts.append(c if t == "string" else f"mq::toString({c})")
            if not parts:
                return 'mq::log("")', "void"
            expr = parts[0] if len(parts) == 1 else "(" + " + \" \" + ".join(
                [parts[0]] + parts[1:]) + ")"
            if len(parts) > 1:
                expr = "(" + parts[0] + "".join(f' + " " + {p}' for p in parts[1:]) + ")"
            return f"mq::log(mq::String({expr}).c_str())", "void"
        if name.startswith("Math."):
            f = name[5:]
            if f in ("floor", "ceil", "round"):
                a = self.args(ctx, node.args, ["real"], node)
                return f"mq::js::{f}({a[0]})", "int"
            if f in ("sqrt", "sin", "cos", "tan"):
                a = self.args(ctx, node.args, ["real"], node)
                return f"mq::js::{f}({a[0]})", "real"
            if f in ("atan2", "pow"):
                a = self.args(ctx, node.args, ["real", "real"], node)
                return f"mq::js::{f}({a[0]}, {a[1]})", "real"
            if f == "abs":
                c, t = self.value(ctx, node.args[0]) if len(node.args) == 1 else comp.err("abs takes 1 argument", node)
                if t not in NUMERIC:
                    comp.err("Math.abs needs a number", node)
                return f"mq::js::abs({c})", t
            if f in ("min", "max"):
                if len(node.args) < 2:
                    comp.err(f"Math.{f} needs at least 2 arguments", node)
                vals = [self.value(ctx, n) for n in node.args]
                t = "int" if all(v[1] == "int" for v in vals) else "real"
                for (c, vt), n in zip(vals, node.args):
                    if vt not in NUMERIC:
                        comp.err(f"Math.{f} needs numbers", n)
                cs = [self.conv(ctx, c, vt, t, n) for (c, vt), n in zip(vals, node.args)]
                code = cs[0]
                for c in cs[1:]:
                    code = f"mq::js::{f}({code}, {c})"
                return code, t
            comp.err(f"Math.{f} is not supported", node)
        if name in ("Qt.rgba", "Qt.rgb"):
            n = 4 if name == "Qt.rgba" else 3
            a = self.args(ctx, node.args, ["real"] * n, node)
            return f"mq::Color::rgbaF({', '.join(a)})", "color"
        if name == "Qt.lighter" or name == "Qt.darker":
            a = self.args(ctx, node.args[:1], ["color"], node) if node.args else comp.err("missing color", node)
            f = self.args(ctx, node.args[1:], ["real"], node) if len(node.args) > 1 else []
            return f"({a[0]}).{name[3:]}({', '.join(f)})", "color"
        if name in ("parseInt", "parseFloat"):
            a = self.args(ctx, node.args, ["string"], node)
            return (f"({a[0]}).toInt()", "int") if name == "parseInt" else (f"({a[0]}).toReal()", "real")
        comp.err(f"'{name}' is not supported", node)

    # ============================================================ output
    def write(self, out_dir, header_name="mq_app.h"):
        os.makedirs(out_dir, exist_ok=True)
        h = ["// Generated by mqc (MicroQuick QML compiler). Do not edit.", "#pragma once", "",
             "#include <mq/mq.h>", ""]
        for sym in sorted(self.images.values()):
            h.append(f"extern const mq::ImageData {sym};")
        h.append("")
        for comp in self.components:
            h.append(f"class {comp.name};")
        h.append("")
        for comp in self.components:
            base = comp.type.base.cpp
            h.append(f"// {os.path.basename(comp.file)}")
            h.append(f"class {comp.name} : public {base}")
            h.append("{")
            h.append("public:")
            h.append(f"    {comp.name}();")
            h.append("    void componentComplete() override;")
            if comp.outer is not None:
                h.append(f"    // delegate: bindings are set up once the enclosing component exists")
                h.append(f"    void mq_setup({comp.outer.name} *o);")
            for m in comp.members:
                h.append("    " + m)
            for d in comp.decls:
                h.append("    " + d)
            h.append("};")
            h.append("")
        h.append("// Creates (once) and returns the application root item.")
        h.append("mq::Item *mq_app_root();")
        h.append(f"constexpr int mq_app_width = {self.root_dim('width', 480)};")
        h.append(f"constexpr int mq_app_height = {self.root_dim('height', 272)};")
        h.append("")
        with open(os.path.join(out_dir, header_name), "w") as f:
            f.write("\n".join(h))

        c = ["// Generated by mqc (MicroQuick QML compiler). Do not edit.",
             f'#include "{header_name}"', "#include <new>", "",
             "extern const mq::FontData *const mq_fonts[];", "extern const int mq_font_count;", ""]
        c.extend(self.array_defs)
        c.append("")
        for comp in self.components:
            c.append(f"// ===== {comp.name} ({os.path.basename(comp.file)})")
            c.extend(comp.pre_defs)
            if comp.pre_defs:
                c.append("")
            sections = [("parent items", comp.ctor_parent), ("constant values", comp.ctor_values),
                        ("bindings", comp.ctor_bindings), ("signal handlers", comp.ctor_handlers),
                        ("states", comp.ctor_states), ("views", comp.ctor_views)]
            setup = []
            if comp.outer is not None:
                setup, sections = sections[2:], sections[:2]
            for header, secs in ((f"{comp.name}::{comp.name}()", sections),
                                 (f"void {comp.name}::mq_setup({comp.outer.name if comp.outer else ''} *o)",
                                  setup)):
                if header.startswith("void") and comp.outer is None:
                    continue
                c.append(header)
                c.append("{")
                if header.startswith("void"):
                    c.append("    outer = o;")
                c.append(f"    {comp.name} *self = this;")
                c.append("    (void)self;")
                for section, lines in secs:
                    if lines:
                        c.append(f"    // {section}")
                        c.extend("    " + l for l in lines)
                c.append("}")
                c.append("")
            c.append(f"void {comp.name}::componentComplete()")
            c.append("{")
            for o in comp.objects:
                if not o.is_root:
                    c.append(f"    {o.name}.componentComplete();")
            c.extend("    " + l for l in comp.extra_complete)
            c.append(f"    {comp.type.base.cpp}::componentComplete();")
            c.extend("    " + l for l in comp.complete)
            c.append("}")
            c.append("")
            c.extend(comp.defs)
        pool = int(self.links_needed(self.main) * 1.5) + 64
        main_dir = os.path.dirname(os.path.abspath(self.main_file))
        entries = [f"    {{{cstr(os.path.relpath(p, main_dir).replace(os.sep, '/'))}, &{sym}}},"
                   for p, sym in sorted(self.images.items(), key=lambda kv: kv[1])]
        c += ["// images reachable from computed sources",
              f"static const mq::ImageEntry mq_images[{max(len(entries), 1)}] = {{"] + \
             (entries or ["    {\"\", nullptr},"]) + ["};", ""]
        c += [f"// dependency links for every binding of the application (estimated)",
              "#ifdef MQ_APP_PLATFORM_STORAGE",
              "// The platform provides the memory once at startup (e.g. from the internal",
              "// heap when the static RAM segment is too small, as on the ESP32).",
              "void *mq_platform_alloc(size_t size, size_t align);",
              "#else",
              f"static mq::Link mq_link_pool[{pool}];",
              "#endif", "",
              "mq::Item *mq_app_root()",
              "{",
              "#ifdef MQ_APP_PLATFORM_STORAGE",
              f"    static mq::Link *mq_link_pool = new (mq_platform_alloc(sizeof(mq::Link) * {pool}, alignof(mq::Link))) mq::Link[{pool}];",
              "#endif",
              f"    static bool poolRegistered = (mq::registerLinkPool(mq_link_pool, {pool}), true);",
              "    (void)poolRegistered;",
              f"    mq::registerImages(mq_images, {len(entries)});",
              "    static bool fontsRegistered = (mq::registerFonts(mq_fonts, mq_font_count), true);",
              "    (void)fontsRegistered;",
              "#ifdef MQ_APP_PLATFORM_STORAGE",
              f"    static {self.main.name} &root = *new (mq_platform_alloc(sizeof({self.main.name}), alignof({self.main.name}))) {self.main.name};",
              "#else",
              f"    static {self.main.name} root;",
              "#endif",
              "    static bool completed = (root.componentComplete(), true);",
              "    (void)completed;",
              "    return &root;",
              "}", ""]
        if not self.main.type.is_item:
            raise QmlError("the main component must be an Item", self.main.file, 1, 1)
        with open(os.path.join(out_dir, "mq_app.cpp"), "w") as f:
            f.write("\n".join(c))

    def links_needed(self, comp, depth=0):
        if depth > 32:
            return 0
        total = comp.link_estimate
        for o in comp.objects:
            if not o.is_root and not o.type.builtin:
                sub = next((c for c in self.components if c.name == o.type.name), None)
                if sub is not None:
                    total += self.links_needed(sub, depth + 1)
        for d, n in comp.pools:
            total += n * self.links_needed(d, depth + 1)
        return total

    def root_dim(self, name, default):
        for a in self.main.doc.root.assignments:
            if a.path == [name] and isinstance(a.value, P.Script) and isinstance(a.value.node, P.Num):
                return int(a.value.node.value)
        return default

    def write_manifest(self, path):
        chars = set(range(32, 127)) | set(range(0xA0, 0x100)) | {0x2026, 0x20AC, 0x2019, 0x2013, 0x2014}
        for s in self.strings:
            chars |= {ord(ch) for ch in s if ord(ch) >= 32}
        lines = ["font_sizes " + " ".join(str(s) for s in sorted(self.font_sizes)),
                 "charset " + " ".join(f"{c:x}" for c in sorted(chars))]
        for p, sym in sorted(self.images.items(), key=lambda kv: kv[1]):
            lines.append(f"image {sym} {p}")
        content = "\n".join(lines) + "\n"
        old = None
        if os.path.exists(path):
            with open(path) as f:
                old = f.read()
        if old != content:
            with open(path, "w") as f:
                f.write(content)


def indent(text, n):
    pad = "    " * n
    return "\n".join(pad + l if l else l for l in text.split("\n"))

"""Lexer and parsers for the QML / JavaScript subset understood by mqc."""

from dataclasses import dataclass, field
from typing import List, Optional, Any


class QmlError(Exception):
    def __init__(self, msg, file=None, line=0, col=0):
        super().__init__(msg)
        self.msg, self.file, self.line, self.col = msg, file, line, col

    def __str__(self):
        loc = f"{self.file or '<input>'}:{self.line}:{self.col}"
        return f"{loc}: error: {self.msg}"


# ----------------------------------------------------------------------- lexer

@dataclass
class Token:
    kind: str          # ident, num, str, punct, eof
    value: Any
    line: int
    col: int
    nl: bool = False   # a line break precedes this token
    raw: str = ""


PUNCTS = sorted("""=== !== == != <= >= && || ++ -- += -= *= /= %= => ...
{ } ( ) [ ] ; , . : ? + - * / % < > = ! & | ^ ~""".split(), key=len, reverse=True)


def tokenize(src: str, file: str) -> List[Token]:
    toks = []
    i, line, col, n = 0, 1, 1, len(src)
    nl = True

    def err(msg):
        raise QmlError(msg, file, line, col)

    while i < n:
        c = src[i]
        if c == "\n":
            i += 1; line += 1; col = 1; nl = True
            continue
        if c in " \t\r﻿":
            i += 1; col += 1
            continue
        if src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0:
                err("unterminated comment")
            chunk = src[i:j + 2]
            line += chunk.count("\n")
            if "\n" in chunk:
                nl = True
                col = len(chunk) - chunk.rfind("\n")
            else:
                col += len(chunk)
            i = j + 2
            continue
        start_line, start_col = line, col
        if c.isalpha() or c in "_$":
            j = i
            while j < n and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            toks.append(Token("ident", src[i:j], start_line, start_col, nl))
            col += j - i; i = j; nl = False
            continue
        if c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            j = i
            if src.startswith(("0x", "0X"), i):
                j += 2
                while j < n and src[j] in "0123456789abcdefABCDEF":
                    j += 1
                val, is_float = int(src[i:j], 16), False
            else:
                while j < n and src[j].isdigit():
                    j += 1
                is_float = False
                if j < n and src[j] == "." and not src.startswith("..", j):
                    is_float = True
                    j += 1
                    while j < n and src[j].isdigit():
                        j += 1
                if j < n and src[j] in "eE":
                    is_float = True
                    j += 1
                    if j < n and src[j] in "+-":
                        j += 1
                    while j < n and src[j].isdigit():
                        j += 1
                text = src[i:j]
                val = float(text) if is_float else int(text)
            t = Token("num", val, start_line, start_col, nl, src[i:j])
            toks.append(t)
            col += j - i; i = j; nl = False
            continue
        if c in "'\"":
            q = c
            j = i + 1
            out = []
            while True:
                if j >= n or src[j] == "\n":
                    err("unterminated string literal")
                ch = src[j]
                if ch == q:
                    j += 1
                    break
                if ch == "\\":
                    j += 1
                    e = src[j]
                    if e == "n": out.append("\n")
                    elif e == "t": out.append("\t")
                    elif e == "r": out.append("\r")
                    elif e == "u":
                        out.append(chr(int(src[j + 1:j + 5], 16))); j += 4
                    elif e == "x":
                        out.append(chr(int(src[j + 1:j + 3], 16))); j += 2
                    else: out.append(e)
                    j += 1
                    continue
                out.append(ch)
                j += 1
            toks.append(Token("str", "".join(out), start_line, start_col, nl, src[i:j]))
            col += j - i; i = j; nl = False
            continue
        if c == "`":
            err("template literals are not supported")
        for p in PUNCTS:
            if src.startswith(p, i):
                toks.append(Token("punct", p, start_line, start_col, nl))
                i += len(p); col += len(p); nl = False
                break
        else:
            err(f"unexpected character {c!r}")
    toks.append(Token("eof", None, line, col, True))
    return toks


# ------------------------------------------------------------------- JS AST

@dataclass
class Node:
    line: int = field(default=0, kw_only=True)
    col: int = field(default=0, kw_only=True)


@dataclass
class Num(Node):
    value: Any
    is_float: bool = False

@dataclass
class Str(Node):
    value: str

@dataclass
class Bool(Node):
    value: bool

@dataclass
class Ident(Node):
    name: str

@dataclass
class Member(Node):
    obj: Node
    name: str

@dataclass
class Call(Node):
    fn: Node
    args: List[Node]

@dataclass
class Unary(Node):
    op: str
    expr: Node

@dataclass
class Binary(Node):
    op: str
    left: Node
    right: Node

@dataclass
class Cond(Node):
    test: Node
    then: Node
    other: Node

@dataclass
class Assign(Node):
    op: str            # '=', '+=', ...
    target: Node
    value: Node

@dataclass
class Update(Node):
    op: str            # '++' / '--'
    prefix: bool
    target: Node

@dataclass
class Index(Node):
    obj: Node
    index: Node

@dataclass
class ArrayLit(Node):
    items: List[Node]

@dataclass
class ObjectLit(Node):
    props: List[tuple]     # (key, expression)

@dataclass
class FuncExpr(Node):
    params: List[str]
    body: Node         # Block or expression

# statements
@dataclass
class Block(Node):
    body: List[Node]

@dataclass
class ExprStmt(Node):
    expr: Node

@dataclass
class VarDecl(Node):
    kind: str
    name: str
    init: Optional[Node]

@dataclass
class If(Node):
    test: Node
    then: Node
    other: Optional[Node]

@dataclass
class While(Node):
    test: Node
    body: Node

@dataclass
class For(Node):
    init: Optional[Node]
    test: Optional[Node]
    update: Optional[Node]
    body: Node

@dataclass
class Return(Node):
    value: Optional[Node]

@dataclass
class Jump(Node):
    kind: str          # break / continue

@dataclass
class Empty(Node):
    pass


# ----------------------------------------------------------------- QML AST

@dataclass
class Assignment:
    path: List[str]            # e.g. ['anchors', 'fill']
    value: Any                 # Script, ObjectDef or list[ObjectDef]
    line: int
    col: int

@dataclass
class Script:
    node: Node                 # expression or Block / FuncExpr
    text: str = ""

@dataclass
class PropertyDecl:
    type: str
    name: str
    value: Any
    readonly: bool
    line: int
    col: int

@dataclass
class SignalDecl:
    name: str
    params: List[tuple]        # (name, type)
    line: int
    col: int

@dataclass
class FunctionDecl:
    name: str
    params: List[tuple]        # (name, type)
    ret: Optional[str]
    body: Block
    line: int
    col: int

@dataclass
class ObjectDef:
    type: str
    line: int
    col: int
    id: Optional[str] = None
    assignments: List[Assignment] = field(default_factory=list)
    properties: List[PropertyDecl] = field(default_factory=list)
    signals: List[SignalDecl] = field(default_factory=list)
    functions: List[FunctionDecl] = field(default_factory=list)
    children: List["ObjectDef"] = field(default_factory=list)
    on: Optional[List[str]] = None         # 'Behavior on x' / 'NumberAnimation on x'
    delegate: Optional["ObjectDef"] = None  # ListView / Repeater delegate (set by codegen)

@dataclass
class Document:
    file: str
    imports: List[str]
    root: ObjectDef


# ------------------------------------------------------------------ parsers

BINARY_PREC = {
    "||": 4, "&&": 5, "|": 6, "^": 7, "&": 8,
    "==": 9, "!=": 9, "===": 9, "!==": 9,
    "<": 10, ">": 10, "<=": 10, ">=": 10,
    "+": 12, "-": 12, "*": 13, "/": 13, "%": 13,
}
ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%="}


class Parser:
    def __init__(self, src: str, file: str):
        self.file = file
        self.src = src
        self.toks = tokenize(src, file)
        self.pos = 0

    # helpers
    def peek(self, k=0) -> Token:
        return self.toks[min(self.pos + k, len(self.toks) - 1)]

    def next(self) -> Token:
        t = self.toks[self.pos]
        if t.kind != "eof":
            self.pos += 1
        return t

    def error(self, msg, tok=None):
        tok = tok or self.peek()
        raise QmlError(msg, self.file, tok.line, tok.col)

    def is_p(self, value, k=0):
        t = self.peek(k)
        return t.kind == "punct" and t.value == value

    def is_ident(self, value=None, k=0):
        t = self.peek(k)
        return t.kind == "ident" and (value is None or t.value == value)

    def expect_p(self, value):
        t = self.next()
        if t.kind != "punct" or t.value != value:
            self.error(f"expected '{value}'", t)
        return t

    def expect_ident(self, what="identifier"):
        t = self.next()
        if t.kind != "ident":
            self.error(f"expected {what}", t)
        return t

    def loc(self, tok):
        return {"line": tok.line, "col": tok.col}

    # ---------------------------------------------------------- expressions
    def parse_expression(self, min_prec=0):
        return self.parse_assign()

    def parse_assign(self):
        start = self.peek()
        if self.is_arrow_start():
            return self.parse_arrow()
        left = self.parse_cond()
        t = self.peek()
        if t.kind == "punct" and t.value in ASSIGN_OPS:
            self.next()
            value = self.parse_assign()
            return Assign(t.value, left, value, **self.loc(start))
        return left

    def is_arrow_start(self):
        if self.is_ident() and self.is_p("=>", 1):
            return True
        if not self.is_p("("):
            return False
        depth, k = 0, 0
        while True:
            t = self.peek(k)
            if t.kind == "eof":
                return False
            if t.kind == "punct" and t.value == "(":
                depth += 1
            elif t.kind == "punct" and t.value == ")":
                depth -= 1
                if depth == 0:
                    return self.is_p("=>", k + 1)
            k += 1

    def parse_params(self):
        """'(' a [: type], ... ')' -> list of (name, type or None)."""
        self.expect_p("(")
        params = []
        while not self.is_p(")"):
            name = self.expect_ident("parameter name").value
            ptype = None
            if self.is_p(":"):
                self.next()
                ptype = self.parse_type_name()
            params.append((name, ptype))
            if not self.is_p(")"):
                self.expect_p(",")
        self.expect_p(")")
        return params

    def parse_type_name(self):
        t = self.expect_ident("type name").value
        while self.is_p("."):
            self.next()
            t += "." + self.expect_ident("type name").value
        return t

    def parse_arrow(self):
        start = self.peek()
        if self.is_ident():
            params = [self.next().value]
        else:
            params = [p[0] for p in self.parse_params()]
        self.expect_p("=>")
        body = self.parse_block() if self.is_p("{") else self.parse_assign()
        return FuncExpr(params, body, **self.loc(start))

    def parse_cond(self):
        start = self.peek()
        test = self.parse_binary(0)
        if self.is_p("?"):
            self.next()
            a = self.parse_assign()
            self.expect_p(":")
            b = self.parse_assign()
            return Cond(test, a, b, **self.loc(start))
        return test

    def parse_binary(self, min_prec):
        left = self.parse_unary()
        while True:
            t = self.peek()
            if t.kind != "punct" or t.value not in BINARY_PREC:
                return left
            prec = BINARY_PREC[t.value]
            if prec <= min_prec:
                return left
            self.next()
            right = self.parse_binary(prec)
            left = Binary(t.value, left, right, line=t.line, col=t.col)

    def parse_unary(self):
        t = self.peek()
        if t.kind == "punct" and t.value in ("!", "-", "+", "~"):
            self.next()
            return Unary(t.value, self.parse_unary(), **self.loc(t))
        if t.kind == "punct" and t.value in ("++", "--"):
            self.next()
            return Update(t.value, True, self.parse_unary(), **self.loc(t))
        if t.kind == "ident" and t.value == "typeof":
            self.error("'typeof' is not supported")
        return self.parse_postfix()

    def parse_postfix(self):
        e = self.parse_call_member()
        t = self.peek()
        if t.kind == "punct" and t.value in ("++", "--") and not t.nl:
            self.next()
            return Update(t.value, False, e, line=e.line, col=e.col)
        return e

    def parse_call_member(self):
        e = self.parse_primary()
        while True:
            t = self.peek()
            if t.kind == "punct" and t.value == ".":
                self.next()
                name = self.expect_ident("member name").value
                e = Member(e, name, line=t.line, col=t.col)
            elif t.kind == "punct" and t.value == "(" and not t.nl:
                self.next()
                args = []
                while not self.is_p(")"):
                    args.append(self.parse_assign())
                    if not self.is_p(")"):
                        self.expect_p(",")
                self.expect_p(")")
                e = Call(e, args, line=e.line, col=e.col)
            elif t.kind == "punct" and t.value == "[" and not t.nl:
                self.next()
                idx = self.parse_expression()
                self.expect_p("]")
                e = Index(e, idx, line=t.line, col=t.col)
            else:
                return e

    def parse_primary(self):
        t = self.next()
        L = self.loc(t)
        if t.kind == "num":
            return Num(t.value, isinstance(t.value, float), **L)
        if t.kind == "str":
            return Str(t.value, **L)
        if t.kind == "ident":
            if t.value in ("true", "false"):
                return Bool(t.value == "true", **L)
            if t.value == "function":
                if self.is_ident():
                    self.next()
                params = [p[0] for p in self.parse_params()]
                return FuncExpr(params, self.parse_block(), **L)
            if t.value in ("null", "undefined", "new", "this"):
                self.error(f"'{t.value}' is not supported", t)
            return Ident(t.value, **L)
        if t.kind == "punct" and t.value == "(":
            e = self.parse_expression()
            self.expect_p(")")
            return e
        if t.kind == "punct" and t.value == "{":
            props = []
            while not self.is_p("}"):
                k = self.next()
                if k.kind not in ("ident", "str"):
                    self.error("expected a property name", k)
                self.expect_p(":")
                props.append((k.value, self.parse_assign()))
                if not self.is_p("}"):
                    self.expect_p(",")
            self.expect_p("}")
            return ObjectLit(props, **L)
        if t.kind == "punct" and t.value == "[":
            items = []
            while not self.is_p("]"):
                items.append(self.parse_assign())
                if not self.is_p("]"):
                    self.expect_p(",")
            self.expect_p("]")
            return ArrayLit(items, **L)
        self.error("unexpected token in expression", t)

    # ----------------------------------------------------------- statements
    def end_statement(self):
        if self.is_p(";"):
            self.next()
            return
        t = self.peek()
        if t.nl or t.kind == "eof" or (t.kind == "punct" and t.value == "}"):
            return
        self.error("expected ';' or end of line")

    def parse_block(self):
        start = self.expect_p("{")
        body = []
        while not self.is_p("}"):
            if self.peek().kind == "eof":
                self.error("unexpected end of file in block")
            body.append(self.parse_statement())
        self.expect_p("}")
        return Block(body, **self.loc(start))

    def parse_statement(self):
        t = self.peek()
        L = self.loc(t)
        if t.kind == "punct" and t.value == "{":
            return self.parse_block()
        if t.kind == "punct" and t.value == ";":
            self.next()
            return Empty(**L)
        if t.kind == "ident":
            kw = t.value
            if kw in ("var", "let", "const"):
                self.next()
                name = self.expect_ident("variable name").value
                if self.is_p(":"):     # optional QML-style type annotation (ignored)
                    self.next(); self.parse_type_name()
                init = None
                if self.is_p("="):
                    self.next()
                    init = self.parse_assign()
                if self.is_p(","):
                    self.error("declare one variable per statement")
                self.end_statement()
                return VarDecl(kw, name, init, **L)
            if kw == "if":
                self.next(); self.expect_p("(")
                test = self.parse_expression(); self.expect_p(")")
                then = self.parse_statement()
                other = None
                if self.is_ident("else"):
                    self.next()
                    other = self.parse_statement()
                return If(test, then, other, **L)
            if kw == "while":
                self.next(); self.expect_p("(")
                test = self.parse_expression(); self.expect_p(")")
                return While(test, self.parse_statement(), **L)
            if kw == "for":
                self.next(); self.expect_p("(")
                init = None
                if not self.is_p(";"):
                    if self.is_ident("var") or self.is_ident("let"):
                        kt = self.next()
                        name = self.expect_ident().value
                        self.expect_p("=")
                        init = VarDecl(kt.value, name, self.parse_assign(), **self.loc(kt))
                    else:
                        init = ExprStmt(self.parse_expression(), **L)
                self.expect_p(";")
                test = None if self.is_p(";") else self.parse_expression()
                self.expect_p(";")
                update = None if self.is_p(")") else self.parse_expression()
                self.expect_p(")")
                return For(init, test, update, self.parse_statement(), **L)
            if kw == "return":
                self.next()
                value = None
                nt = self.peek()
                if not (nt.nl or (nt.kind == "punct" and nt.value in (";", "}"))):
                    value = self.parse_expression()
                self.end_statement()
                return Return(value, **L)
            if kw in ("break", "continue"):
                self.next(); self.end_statement()
                return Jump(kw, **L)
            if kw in ("switch", "try", "throw", "do", "function", "class"):
                self.error(f"'{kw}' statements are not supported")
        e = self.parse_expression()
        self.end_statement()
        return ExprStmt(e, **L)


class QmlParser(Parser):
    def parse_document(self) -> Document:
        imports = []
        while self.is_ident("import") or self.is_ident("pragma"):
            first = self.next()
            parts = []
            while True:
                t = self.peek()
                if t.kind == "eof" or (t.nl and t is not first):
                    break
                if t.kind == "punct" and t.value == ";":
                    self.next()
                    break
                parts.append(str(t.value))
                self.next()
            if first.value == "import":
                imports.append(" ".join(parts))
        root = self.parse_object()
        if self.peek().kind != "eof":
            self.error("only one root object is allowed")
        return Document(self.file, imports, root)

    def parse_object(self, type_tok=None) -> ObjectDef:
        t = type_tok or self.expect_ident("object type")
        tname = t.value
        while self.is_p("."):
            self.next()
            tname += "." + self.expect_ident("type name").value
        if not tname.split(".")[-1][:1].isupper():
            self.error(f"'{tname}' is not an object type (must start with an upper case letter)", t)
        obj = ObjectDef(tname.split(".")[-1], t.line, t.col)
        if self.is_ident("on"):
            self.next()
            obj.on = [self.expect_ident("property name").value]
            while self.is_p("."):
                self.next()
                obj.on.append(self.expect_ident("property name").value)
        self.expect_p("{")
        self.parse_members(obj, [])
        self.expect_p("}")
        return obj

    def parse_members(self, obj: ObjectDef, prefix: List[str]):
        while not self.is_p("}"):
            t = self.peek()
            if t.kind == "eof":
                self.error("unexpected end of file, missing '}'")
            if t.kind == "punct" and t.value in (";", ","):
                self.next()
                continue
            if t.kind != "ident":
                self.error("expected a property, object or declaration")
            if not prefix:
                if t.value == "id" and self.is_p(":", 1):
                    self.next(); self.next()
                    if obj.id:
                        self.error("duplicate id")
                    obj.id = self.expect_ident("id").value
                    if obj.id[:1].isupper():
                        self.error("ids must start with a lower case letter")
                    self.end_statement()
                    continue
                if self.is_declaration():
                    self.parse_declaration(obj)
                    continue
            # qualified name
            start_pos = self.pos
            name_tok = self.next()
            path = [name_tok.value]
            while self.is_p("."):
                self.next()
                path.append(self.expect_ident().value)
            if self.is_p("{") or (self.is_ident("on") and path[-1][:1].isupper()):
                if path[-1][:1].isupper():
                    # child object (possibly with a module qualifier)
                    self.pos = start_pos
                    child = self.parse_object()
                    if prefix:
                        self.error("objects are not allowed inside grouped properties", name_tok)
                    obj.children.append(child)
                else:
                    self.next()
                    self.parse_members(obj, prefix + path)
                    self.expect_p("}")
                continue
            self.expect_p(":")
            value = self.parse_value()
            obj.assignments.append(Assignment(prefix + path, value, name_tok.line, name_tok.col))

    def is_declaration(self):
        k = 0
        while self.is_ident("readonly", k) or self.is_ident("default", k) or self.is_ident("required", k):
            k += 1
        if self.is_ident("property", k) and self.is_ident(None, k + 1):
            return True
        if k == 0 and self.is_ident("signal") and self.is_ident(None, 1):
            return True
        if k == 0 and self.is_ident("function") and self.is_ident(None, 1):
            return True
        if k == 0 and self.is_ident("enum") and self.is_ident(None, 1):
            return True
        return False

    def parse_declaration(self, obj: ObjectDef):
        t = self.peek()
        readonly = False
        while self.is_ident("readonly") or self.is_ident("default") or self.is_ident("required"):
            if self.next().value == "readonly":
                readonly = True
        kw = self.next()
        if kw.value == "property":
            ptype = self.parse_type_name()
            if self.is_p("<"):
                self.next()
                ptype = f"list<{self.parse_type_name()}>"
                self.expect_p(">")
            name = self.expect_ident("property name").value
            value = None
            if self.is_p(":"):
                self.next()
                value = self.parse_value()
            else:
                self.end_statement()
            obj.properties.append(PropertyDecl(ptype, name, value, readonly, t.line, t.col))
        elif kw.value == "signal":
            name = self.expect_ident("signal name").value
            params = []
            if self.is_p("("):
                self.next()
                while not self.is_p(")"):
                    a = self.expect_ident().value
                    if self.is_p(":"):           # name: type
                        self.next()
                        params.append((a, self.parse_type_name()))
                    else:                        # type name
                        params.append((self.expect_ident("parameter name").value, a))
                    if not self.is_p(")"):
                        self.expect_p(",")
                self.expect_p(")")
            self.end_statement()
            obj.signals.append(SignalDecl(name, params, t.line, t.col))
        elif kw.value == "function":
            name = self.expect_ident("function name").value
            params = self.parse_params()
            ret = None
            if self.is_p(":"):
                self.next()
                ret = self.parse_type_name()
            body = self.parse_block()
            obj.functions.append(FunctionDecl(name, params, ret, body, t.line, t.col))
        else:
            self.error("enums are not supported", kw)

    def parse_value(self):
        start = self.peek()
        # list of objects: [ Type { ... }, ... ]
        if self.is_p("[") and self.is_ident(None, 1) and str(self.peek(1).value)[:1].isupper() \
                and (self.is_p("{", 2) or self.is_p(".", 2)):
            self.next()
            objs = []
            while not self.is_p("]"):
                objs.append(self.parse_object())
                if not self.is_p("]"):
                    self.expect_p(",")
            self.expect_p("]")
            self.end_statement()
            return objs
        # single object value: Type { ... }
        if self.is_ident() and str(start.value)[:1].isupper() and self.is_p("{", 1):
            o = self.parse_object()
            self.end_statement()
            return o
        begin = self.pos
        if self.is_p("{"):
            node = self.parse_block()
        elif self.peek().kind == "ident" and self.peek().value in ("if", "for", "while", "var", "let",
                                                                    "const", "return"):
            # a single statement after the colon (onClicked: if (x) y())
            node = Block([self.parse_statement()], **self.loc(self.peek()))
        else:
            node = self.parse_expression()
            self.end_statement()
        end_tok = self.toks[self.pos - 1]
        text = self.source_text(begin, self.pos)
        return Script(node, text)

    def source_text(self, a, b):
        toks = self.toks[a:b]
        return " ".join(str(t.raw or t.value) for t in toks if t.kind != "eof")


def parse_qml(src: str, file: str) -> Document:
    return QmlParser(src, file).parse_document()

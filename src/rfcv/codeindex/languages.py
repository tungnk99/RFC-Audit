"""Tri thức cú pháp theo ngôn ngữ cho bộ dựng chỉ mục: nút nào là định nghĩa, lời gọi, tham chiếu (tree-sitter).

Mỗi ngôn ngữ khai báo phần mở rộng tệp, gói grammar, và các hàm trích ký hiệu, lời gọi. Không có mã nào ở đây chạy mã
của kho mã: chỉ đọc cây cú pháp.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Node = Any  # tree_sitter.Node; để Any để mô-đun nhập được khi chưa cài tree-sitter


@dataclass(frozen=True)
class Sym:
    kind: str
    name: str
    node: Node  # nút bao toàn bộ định nghĩa (khoảng dòng)
    name_node: Node | None
    signature: str


@dataclass(frozen=True)
class LanguageSpec:
    name: str
    module: str  # gói Python của grammar, có hàm language()
    extensions: tuple[str, ...]
    symbols: Callable[[Node, bool], list[Sym]]  # (nút, đang ở phạm vi tệp) -> ký hiệu định nghĩa tại nút
    call_target: Callable[[Node], tuple[str, str] | None]  # nút lời gọi -> (tên được gọi, loại)
    identifier_types: frozenset[str]
    function_types: frozenset[str]  # nút mở phạm vi hàm (để biết phạm vi tệp)
    body_types: frozenset[str]  # thân hàm (để lấy khối lệnh)
    control_types: frozenset[str]  # câu lệnh điều khiển cấp một (danh sách khối lệnh)


def text(node: Node | None) -> str:
    if node is None or node.text is None:
        return ""
    return bytes(node.text).decode("utf-8", errors="replace")


def field(node: Node | None, name: str) -> Node | None:
    return None if node is None else node.child_by_field_name(name)


def signature(node: Node, source: bytes) -> str:
    """Phần đầu định nghĩa tới trước thân (hoặc dòng đầu), gộp khoảng trắng, tối đa 200 ký tự."""
    body = field(node, "body") or field(node, "value")
    end = body.start_byte if body is not None else node.end_byte
    raw = source[node.start_byte : end].decode("utf-8", errors="replace")
    if body is None:
        raw = raw.split("\n", 1)[0]
    sig = " ".join(raw.split()).rstrip("{=; ")
    return sig[:200]


# ---------------------------------------------------------------- C

_C_NAME_TYPES = frozenset({"identifier", "field_identifier", "type_identifier"})


def c_declarator_name(node: Node | None) -> tuple[str, Node] | None:
    """Tên trong một declarator C, đi qua con trỏ, mảng, hàm, ngoặc."""
    seen = 0
    while node is not None and seen < 32:
        seen += 1
        if node.type in _C_NAME_TYPES:
            return text(node), node
        nxt = field(node, "declarator")
        if nxt is None:
            nxt = next(
                (c for c in node.named_children if c.type.endswith("declarator") or c.type in _C_NAME_TYPES), None
            )
        node = nxt
    return None


def _c_is_function_declarator(node: Node | None) -> bool:
    seen = 0
    while node is not None and seen < 32:
        seen += 1
        if node.type == "function_declarator":
            return True
        if node.type in _C_NAME_TYPES:
            return False
        node = field(node, "declarator")
    return False


def c_symbols(node: Node, file_scope: bool) -> list[Sym]:
    t = node.type
    out: list[Sym] = []
    if t == "function_definition":
        got = c_declarator_name(field(node, "declarator"))
        if got:
            out.append(Sym("function", got[0], node, got[1], ""))
    elif t in ("struct_specifier", "union_specifier", "enum_specifier"):
        name = field(node, "name")
        if name is not None and field(node, "body") is not None:
            out.append(Sym(t.removesuffix("_specifier"), text(name), node, name, ""))
    elif t == "type_definition":
        for child in node.children_by_field_name("declarator"):
            got = c_declarator_name(child)
            if got:
                out.append(Sym("typedef", got[0], node, got[1], ""))
    elif t in ("preproc_def", "preproc_function_def"):
        name = field(node, "name")
        if name is not None:
            out.append(Sym("macro", text(name), node, name, ""))
    elif t == "enumerator":
        name = field(node, "name")
        if name is not None:
            out.append(Sym("enumerator", text(name), node, name, ""))
    elif t == "declaration" and file_scope:
        for child in node.children_by_field_name("declarator"):
            if child.type == "init_declarator":
                got = c_declarator_name(field(child, "declarator"))
                if got:
                    out.append(Sym("variable", got[0], node, got[1], ""))
            elif _c_is_function_declarator(child):
                got = c_declarator_name(child)
                if got:
                    out.append(Sym("prototype", got[0], node, got[1], ""))
    return out


def c_call_target(node: Node) -> tuple[str, str] | None:
    if node.type != "call_expression":
        return None
    fn = field(node, "function")
    if fn is None:
        return None
    if fn.type == "identifier":
        return text(fn), "direct"
    if fn.type == "field_expression":
        f = field(fn, "field")
        return (text(f), "indirect") if f is not None else None
    if fn.type == "parenthesized_expression" and fn.named_children:
        inner = fn.named_children[0]
        if inner.type == "pointer_expression":
            arg = field(inner, "argument")
            if arg is not None and arg.type == "identifier":
                return text(arg), "indirect"
    return None


C = LanguageSpec(
    name="c",
    module="tree_sitter_c",
    extensions=(".c", ".h", ".inc"),
    symbols=c_symbols,
    call_target=c_call_target,
    identifier_types=frozenset({"identifier", "field_identifier", "type_identifier"}),
    function_types=frozenset({"function_definition"}),
    body_types=frozenset({"compound_statement"}),
    control_types=frozenset(
        {
            "if_statement",
            "for_statement",
            "while_statement",
            "do_statement",
            "switch_statement",
            "compound_statement",
            "preproc_if",
            "preproc_ifdef",
        }
    ),
)

# ---------------------------------------------------------------- Rust

_RUST_KINDS = {
    "struct_item": "struct",
    "enum_item": "enum",
    "union_item": "union",
    "trait_item": "trait",
    "type_item": "type",
    "mod_item": "module",
    "const_item": "const",
    "static_item": "variable",
    "macro_definition": "macro",
    "enum_variant": "enumerator",
}


def _inside(node: Node, types: frozenset[str]) -> bool:
    p = node.parent
    depth = 0
    while p is not None and depth < 64:
        if p.type in types:
            return True
        p = p.parent
        depth += 1
    return False


def rust_symbols(node: Node, file_scope: bool) -> list[Sym]:
    t = node.type
    name = field(node, "name")
    if t == "function_item" and name is not None:
        kind = "method" if _inside(node, frozenset({"impl_item", "trait_item"})) else "function"
        return [Sym(kind, text(name), node, name, "")]
    if t == "function_signature_item" and name is not None:
        return [Sym("prototype", text(name), node, name, "")]
    if t == "impl_item":
        ty = field(node, "type")
        if ty is not None:
            return [Sym("impl", text(ty), node, ty, "")]
    if t in _RUST_KINDS and name is not None:
        return [Sym(_RUST_KINDS[t], text(name), node, name, "")]
    return []


def rust_call_target(node: Node) -> tuple[str, str] | None:
    if node.type == "macro_invocation":
        m = field(node, "macro")
        if m is not None:
            last = field(m, "name") if m.type == "scoped_identifier" else m
            return (text(last), "macro") if last is not None else None
        return None
    if node.type != "call_expression":
        return None
    fn = field(node, "function")
    seen = 0
    while fn is not None and fn.type == "generic_function" and seen < 8:
        fn = field(fn, "function")
        seen += 1
    if fn is None:
        return None
    if fn.type == "identifier":
        return text(fn), "direct"
    if fn.type == "scoped_identifier":
        n = field(fn, "name")
        return (text(n), "direct") if n is not None else None
    if fn.type == "field_expression":
        f = field(fn, "field")
        return (text(f), "method") if f is not None else None
    return None


RUST = LanguageSpec(
    name="rust",
    module="tree_sitter_rust",
    extensions=(".rs",),
    symbols=rust_symbols,
    call_target=rust_call_target,
    identifier_types=frozenset({"identifier", "field_identifier", "type_identifier"}),
    function_types=frozenset({"function_item", "closure_expression"}),
    body_types=frozenset({"block"}),
    control_types=frozenset(
        {"if_expression", "match_expression", "for_expression", "while_expression", "loop_expression", "block"}
    ),
)

# ---------------------------------------------------------------- Go


def go_symbols(node: Node, file_scope: bool) -> list[Sym]:
    t = node.type
    name = field(node, "name")
    if t == "function_declaration" and name is not None:
        return [Sym("function", text(name), node, name, "")]
    if t == "method_declaration" and name is not None:
        return [Sym("method", text(name), node, name, "")]
    if t == "type_spec" and name is not None:
        ty = field(node, "type")
        kind = {"struct_type": "struct", "interface_type": "interface"}.get(ty.type if ty is not None else "", "type")
        return [Sym(kind, text(name), node, name, "")]
    if t in ("const_spec", "var_spec") and file_scope:
        kind = "const" if t == "const_spec" else "variable"
        return [Sym(kind, text(n), node, n, "") for n in node.children_by_field_name("name")]
    if t in ("method_spec", "method_elem") and name is not None:
        return [Sym("prototype", text(name), node, name, "")]
    return []


def go_call_target(node: Node) -> tuple[str, str] | None:
    if node.type != "call_expression":
        return None
    fn = field(node, "function")
    if fn is None:
        return None
    if fn.type == "identifier":
        return text(fn), "direct"
    if fn.type == "selector_expression":
        f = field(fn, "field")
        return (text(f), "method") if f is not None else None
    return None


GO = LanguageSpec(
    name="go",
    module="tree_sitter_go",
    extensions=(".go",),
    symbols=go_symbols,
    call_target=go_call_target,
    identifier_types=frozenset({"identifier", "field_identifier", "type_identifier"}),
    function_types=frozenset({"function_declaration", "method_declaration", "func_literal"}),
    body_types=frozenset({"block"}),
    control_types=frozenset(
        {
            "if_statement",
            "for_statement",
            "expression_switch_statement",
            "type_switch_statement",
            "select_statement",
            "block",
        }
    ),
)

LANGUAGES: tuple[LanguageSpec, ...] = (C, RUST, GO)


def language_for(path: str) -> LanguageSpec | None:
    lower = path.lower()
    return next((lang for lang in LANGUAGES if lower.endswith(lang.extensions)), None)

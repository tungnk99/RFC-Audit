"""Dựng chỉ mục SQLite từ bản sao phạm vi bằng tree-sitter (tài liệu khám phá mã, mục 12).

Tất định: duyệt tệp theo thứ tự, không ghi thời gian vào chỉ mục; cùng bản sao và cùng phiên bản grammar cho cùng
chỉ mục. Chạy trong container `code-indexer` (không mạng, kho mã chỉ đọc, chỉ /out ghi được):

    python -m rfcv.codeindex build --root /repo --out /out/index.db
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from rfcv.codeindex.languages import LANGUAGES, LanguageSpec, Node, language_for, signature, text
from rfcv.codeindex.languages import field as child

INDEX_FORMAT = "rfcv-codeindex/1"
MAX_PARSE_BYTES = 4 * 1024 * 1024
LONG_FUNCTION = 100  # hàm dài hơn mức này được ghi danh sách khối lệnh (read_function trang 1)
CONTAINER_KINDS = frozenset({"function", "method", "variable", "const"})
_FIRST_LINE_KINDS = frozenset({"macro", "enumerator", "variable", "const", "prototype", "typedef"})

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE files(path TEXT PRIMARY KEY, lang TEXT, sha256 TEXT NOT NULL, nlines INTEGER NOT NULL, content TEXT NOT NULL);
CREATE TABLE symbols(file TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
                     line_start INTEGER NOT NULL, line_end INTEGER NOT NULL, signature TEXT NOT NULL);
CREATE TABLE calls(caller TEXT NOT NULL, callee TEXT NOT NULL, file TEXT NOT NULL, line INTEGER NOT NULL,
                   kind TEXT NOT NULL);
CREATE TABLE refs(name TEXT NOT NULL, file TEXT NOT NULL, line INTEGER NOT NULL, container TEXT NOT NULL,
                  kind TEXT NOT NULL);
CREATE TABLE blocks(file TEXT NOT NULL, line_start INTEGER NOT NULL, line_end INTEGER NOT NULL, kind TEXT NOT NULL,
                    head TEXT NOT NULL);
CREATE TABLE pp_branches(file TEXT NOT NULL, chain INTEGER NOT NULL, idx INTEGER NOT NULL, line_start INTEGER NOT NULL,
                         line_end INTEGER NOT NULL, cond TEXT NOT NULL);
"""

INDEXES = """
CREATE INDEX symbols_name ON symbols(name);
CREATE INDEX symbols_file ON symbols(file, line_start);
CREATE INDEX calls_caller ON calls(caller, callee);
CREATE INDEX refs_name ON refs(name);
CREATE INDEX blocks_file ON blocks(file, line_start);
CREATE INDEX pp_file ON pp_branches(file);
"""


class IndexBuildError(RuntimeError):
    pass


def _line(node: Node) -> int:
    return int(node.start_point[0]) + 1


def _end_line(node: Node) -> int:
    row, col = int(node.end_point[0]), int(node.end_point[1])
    if col == 0 and row > int(node.start_point[0]):
        return row  # nút kết thúc ở đầu dòng sau: dòng cuối là dòng trước đó
    return row + 1


def _parser_for(lang: LanguageSpec) -> Any:
    try:
        from tree_sitter import Language, Parser
    except ImportError as exc:  # pragma: no cover - phụ thuộc môi trường
        raise IndexBuildError("cần cài tree-sitter: pip install 'rfcv[codeindex]'") from exc
    try:
        grammar = importlib.import_module(lang.module)
    except ImportError as exc:  # pragma: no cover
        raise IndexBuildError(f"thiếu grammar {lang.module}: pip install 'rfcv[codeindex]'") from exc
    capsule: object = grammar.language()  # PyCapsule; kiểu object để không rơi vào overload int đã deprecated
    return Parser(Language(capsule))


def tool_versions() -> dict[str, str]:
    out: dict[str, str] = {}
    for pkg in ("tree-sitter", *(lang.module.replace("_", "-") for lang in LANGUAGES)):
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            out[pkg] = "missing"
    return out


@dataclass
class _FileFacts:
    symbols: list[tuple[str, str, str, int, int, str]] = field(
        default_factory=list[tuple[str, str, str, int, int, str]]
    )
    calls: list[tuple[str, str, str, int, str]] = field(default_factory=list[tuple[str, str, str, int, str]])
    refs: list[tuple[str, str, int, str, str]] = field(default_factory=list[tuple[str, str, int, str, str]])
    blocks: list[tuple[str, int, int, str, str]] = field(default_factory=list[tuple[str, int, int, str, str]])
    branches: list[tuple[str, int, int, int, int, str]] = field(
        default_factory=list[tuple[str, int, int, int, int, str]]
    )


# ---------------------------------------------------------------- tiền xử lý C


def cond_json(node: Node | None) -> dict[str, Any]:
    """Biểu thức điều kiện #if thành cây JSON nhỏ để đánh giá theo cờ build lúc truy vấn."""
    if node is None:
        return {"op": "unknown"}
    t = node.type
    if t == "preproc_defined":
        ident = next((c for c in node.named_children if c.type == "identifier"), None)
        return {"op": "defined", "name": text(ident)} if ident is not None else {"op": "unknown"}
    if t == "unary_expression":
        op = child(node, "operator")
        if op is not None and op.type == "!":
            return {"op": "not", "a": cond_json(child(node, "argument"))}
    if t == "binary_expression":
        op = child(node, "operator")
        o = op.type if op is not None else ""
        left, right = cond_json(child(node, "left")), cond_json(child(node, "right"))
        if o == "&&":
            return {"op": "and", "a": left, "b": right}
        if o == "||":
            return {"op": "or", "a": left, "b": right}
        if o in ("==", "!=", ">", ">=", "<", "<="):
            return {"op": "cmp", "o": o, "a": left, "b": right}
    if t == "parenthesized_expression" and node.named_children:
        return cond_json(node.named_children[0])
    if t == "number_literal":
        raw = text(node).rstrip("uUlL")
        try:
            return {"op": "num", "v": int(raw, 0)}
        except ValueError:
            return {"op": "unknown"}
    if t == "identifier":
        return {"op": "ident", "name": text(node)}
    return {"op": "unknown"}


def _ifdef_cond(node: Node) -> dict[str, Any]:
    name = child(node, "name")
    directive = node.children[0].type if node.children else ""
    base: dict[str, Any] = {"op": "defined", "name": text(name)} if name is not None else {"op": "unknown"}
    return {"op": "not", "a": base} if directive.endswith("ifndef") else base


def _record_chain(top: Node, file: str, chain: int, facts: _FileFacts) -> None:
    branches: list[tuple[int, int, dict[str, Any]]] = []
    cond = _ifdef_cond(top) if top.type == "preproc_ifdef" else cond_json(child(top, "condition"))
    alt = child(top, "alternative")
    start = _line(top)
    end = (_line(alt) - 1) if alt is not None else _end_line(top)
    branches.append((start, end, cond))
    seen = 0
    while alt is not None and seen < 256:
        seen += 1
        nxt = child(alt, "alternative")
        a_start = _line(alt)
        a_end = (_line(nxt) - 1) if nxt is not None else _end_line(alt)
        if alt.type == "preproc_else":
            branches.append((a_start, a_end, {"op": "else"}))
        elif alt.type == "preproc_elifdef":
            branches.append((a_start, a_end, _ifdef_cond(alt)))
        else:
            branches.append((a_start, a_end, cond_json(child(alt, "condition"))))
        alt = nxt
    for i, (a, b, c) in enumerate(branches):
        facts.branches.append((file, chain, i, a, b, json.dumps(c, sort_keys=True)))


# ---------------------------------------------------------------- duyệt cây


def _ref_kind(node: Node) -> str:
    parent = node.parent
    if parent is None:
        return "read"
    pt = parent.type
    if pt == "call_expression" and _same(child(parent, "function"), node):
        return "call"
    if pt in ("field_expression", "selector_expression") and _same(child(parent, "field"), node):
        grand = parent.parent
        if grand is not None and grand.type == "call_expression" and _same(child(grand, "function"), parent):
            return "call"
        if (
            grand is not None
            and grand.type in ("assignment_expression", "compound_assignment_expr")
            and _same(child(grand, "left"), parent)
        ):
            return "write"
        if grand is not None and grand.type == "update_expression":
            return "write"
        return "read"
    if pt in ("assignment_expression", "compound_assignment_expr") and _same(child(parent, "left"), node):
        return "write"
    if pt == "update_expression":
        return "write"
    if pt == "expression_list":  # Go: a, b = ...
        grand = parent.parent
        if grand is not None and grand.type == "assignment_statement" and _same(child(grand, "left"), parent):
            return "write"
    if pt == "inc_statement" or pt == "dec_statement":
        return "write"
    return "read"


def _same(a: Node | None, b: Node | None) -> bool:
    return (
        a is not None
        and b is not None
        and a.start_byte == b.start_byte
        and a.end_byte == b.end_byte
        and a.type == b.type
    )


def _block_head(node: Node, lines: list[str]) -> str:
    ln = _line(node)
    head = lines[ln - 1].strip() if 0 < ln <= len(lines) else node.type
    return f"{node.type.removesuffix('_statement').removesuffix('_expression')}: {head[:100]}"


def index_file(lang: LanguageSpec, parser: Any, file: str, source: bytes, lines: list[str], facts: _FileFacts) -> None:
    tree = parser.parse(source)
    defining: set[tuple[int, int]] = set()
    chain = 0
    # (nút, tên vùng chứa, đang trong hàm)
    stack: list[tuple[Node, str, bool]] = [(tree.root_node, "", False)]
    while stack:
        node, container, in_fn = stack.pop()
        t = node.type

        syms = lang.symbols(node, not in_fn)
        inner_container = container
        for s in syms:
            sig = (
                (lines[_line(s.node) - 1].strip()[:200] if _line(s.node) <= len(lines) else s.name)
                if s.kind in _FIRST_LINE_KINDS
                else signature(s.node, source)
            )
            a, b = _line(s.node), _end_line(s.node)
            facts.symbols.append((file, s.name, s.kind, a, b, sig))
            if s.name_node is not None:
                defining.add((s.name_node.start_byte, s.name_node.end_byte))
            if s.kind in CONTAINER_KINDS:
                inner_container = s.name
            if s.kind in ("function", "method") and b - a + 1 > LONG_FUNCTION:
                body = child(s.node, "body")
                if body is not None:
                    for stmt in body.named_children:
                        if stmt.type in lang.control_types or _end_line(stmt) - _line(stmt) >= 5:
                            facts.blocks.append(
                                (file, _line(stmt), _end_line(stmt), stmt.type, _block_head(stmt, lines))
                            )

        # Lời gọi ở phạm vi tệp (ví dụ trong bộ khởi tạo bảng) vẫn ghi, gắn với biến chứa nó.
        target = lang.call_target(node)
        if target is not None and inner_container:
            facts.calls.append((inner_container, target[0], file, _line(node), target[1]))

        # Nút đầu chuỗi #if/#ifdef; các nhánh #elif/#else là "alternative" của nó, có kiểu nút khác.
        if lang.name == "c" and t in ("preproc_if", "preproc_ifdef"):
            chain += 1
            _record_chain(node, file, chain, facts)

        if t in lang.identifier_types:
            if (node.start_byte, node.end_byte) not in defining:
                facts.refs.append((text(node), file, _line(node), container, _ref_kind(node)))
            continue

        now_in_fn = in_fn or t in lang.function_types
        for c in reversed(node.children):
            stack.append((c, inner_container, now_in_fn))


# ---------------------------------------------------------------- tệp


def iter_files(root: Path) -> Iterator[tuple[str, Path]]:
    """Mọi tệp thường dưới root (không theo symlink, bỏ .git), theo thứ tự tất định."""
    items: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for name in filenames:
            p = Path(dirpath) / name
            if p.is_symlink() or not p.is_file():
                continue
            items.append((p.relative_to(root).as_posix(), p))
    yield from sorted(items)


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def build_index(root: Path, out: Path) -> dict[str, str]:
    """Dựng chỉ mục cho mọi tệp văn bản dưới `root` vào `out` (ghi đè). Trả bảng meta."""
    root = root.resolve()
    if not root.is_dir():
        raise IndexBuildError(f"không có thư mục kho mã: {root}")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(str(tmp))
    try:
        conn.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;" + SCHEMA)
        parsers: dict[str, Any] = {}
        snapshot = hashlib.sha256()
        counts = {"files": 0, "parsed": 0, "parse_errors": 0}
        for rel, path in iter_files(root):
            data = path.read_bytes()
            if _is_binary(data):
                continue
            digest = hashlib.sha256(data).hexdigest()
            snapshot.update(f"{rel}\0{digest}\n".encode())
            content = data.decode("utf-8", errors="replace")
            lines = [ln.removesuffix("\r") for ln in content.split("\n")]
            if lines and lines[-1] == "":
                lines.pop()
            lang = language_for(rel)
            conn.execute(
                "INSERT INTO files VALUES (?,?,?,?,?)",
                (rel, lang.name if lang else None, digest, len(lines), "\n".join(lines)),
            )
            counts["files"] += 1
            if lang is None or len(data) > MAX_PARSE_BYTES:
                continue
            if lang.name not in parsers:
                parsers[lang.name] = _parser_for(lang)
            facts = _FileFacts()
            try:
                index_file(lang, parsers[lang.name], rel, data, lines, facts)
            except (RecursionError, ValueError):
                counts["parse_errors"] += 1
                continue
            counts["parsed"] += 1
            conn.executemany("INSERT INTO symbols VALUES (?,?,?,?,?,?)", facts.symbols)
            conn.executemany("INSERT INTO calls VALUES (?,?,?,?,?)", facts.calls)
            conn.executemany("INSERT INTO refs VALUES (?,?,?,?,?)", facts.refs)
            conn.executemany("INSERT INTO blocks VALUES (?,?,?,?,?)", facts.blocks)
            conn.executemany("INSERT INTO pp_branches VALUES (?,?,?,?,?,?)", facts.branches)

        # Tham chiếu "đọc" tới tên một hàm (không gọi) là lấy địa chỉ hàm: gán vào con trỏ, bảng xử lý.
        conn.execute(
            "UPDATE refs SET kind='fn_pointer' WHERE kind='read' AND name IN "
            "(SELECT name FROM symbols WHERE kind IN ('function','method'))"
        )
        conn.executescript(INDEXES)
        meta = {
            "format": INDEX_FORMAT,
            "snapshot": "sha256:" + snapshot.hexdigest(),
            **{k: str(v) for k, v in counts.items()},
            **{f"version:{k}": v for k, v in tool_versions().items()},
        }
        conn.executemany("INSERT INTO meta VALUES (?,?)", sorted(meta.items()))
        conn.commit()
    finally:
        conn.close()
    os.replace(tmp, out)
    return meta

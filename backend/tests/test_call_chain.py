"""Công cụ `code.call_chain` (gen-50): BFS hai chiều, cạnh/dòng đã hiển thị, đầu ra bị chặn kích thước."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from rfcv.core.ifc import TrustLabel
from rfcv.domains.rfc_protocol.call_chain import CallChainParams, call_chain_tool_spec
from rfcv.gates.code_gate import InMemoryCodeIndex, Reference, SymbolInfo
from rfcv.gates.tool_gateway import ToolResult, ToolSession

SOURCE = [
    "int entry(Msg *m) {",  # 1
    "    int ret = parse(m);",  # 2
    "    if (ret == BAD_LEN) return react(m);",  # 3
    "    return 0;",  # 4
    "}",  # 5
    "int parse(Msg *m) {",  # 6
    "    m->len = 0;",  # 7
    "    log_len(m->len);",  # 8
    "    use(m->len);",  # 9
    "    copy(m->len);",  # 10
    "    trace_len(m->len);",  # 11
    "    if (check_len(m)) return BAD_LEN;",  # 12
    "    return memcpy_wrap(m->len);",  # 13
    "}",  # 14
    "int check_len(Msg *m) {",  # 15
    "    return m->len > MAX_LEN;",  # 16
    "}",  # 17
    "int top(Msg *m) {",  # 18
    "    return entry(m);",  # 19
    "}",  # 20
]
FILE = "src/a.c"


def index() -> InMemoryCodeIndex:
    spans = {"entry": (1, 5), "parse": (6, 14), "check_len": (15, 17), "top": (18, 20)}
    return InMemoryCodeIndex(
        sources={FILE: SOURCE},
        symbols=[SymbolInfo(FILE, n, "function", a, b) for n, (a, b) in spans.items()],
        calls={("top", "entry"), ("entry", "parse"), ("parse", "check_len"), ("parse", "memcpy")},
        refs=[
            Reference(FILE, 19, "top", "call"),
            Reference(FILE, 2, "entry", "call"),
            Reference(FILE, 12, "parse", "call"),
        ],
    )


def run(code_index: Any, **args: Any) -> ToolResult:
    spec = call_chain_tool_spec(SimpleNamespace(providers=SimpleNamespace(code_index=code_index)))
    session = ToolSession("r", "code_reader", "REQ", 5)

    async def call() -> ToolResult:
        return await spec.handler(CallChainParams(**args), session)

    return asyncio.run(call())


def test_callees_follow_two_hops_and_skip_external_functions() -> None:
    r = run(index(), symbol="entry", direction="callees")
    assert r.label is TrustLabel.UNTRUSTED
    assert r.shown_edges == {("entry", "parse"), ("parse", "check_len")}
    assert "memcpy" not in r.text and "== callers ==" not in r.text
    assert not r.shown_lines


def test_callers_follow_two_hops() -> None:
    r = run(index(), symbol="check_len", direction="callers")
    assert r.shown_edges == {("parse", "check_len"), ("entry", "parse")}
    assert "== callees ==" not in r.text


def test_depth_and_max_nodes_limit_the_walk() -> None:
    assert run(index(), symbol="entry", direction="callees", depth=1).shown_edges == {("entry", "parse")}
    capped = run(index(), symbol="entry", direction="callees", max_nodes=1)
    assert capped.shown_edges == {("entry", "parse")} and "max_nodes=1" in capped.text


def test_reference_without_call_edge_is_not_a_caller() -> None:
    idx = index()
    idx.calls.discard(("entry", "parse"))
    assert not run(idx, symbol="parse", direction="callers").shown_edges


def test_filter_prefers_decision_lines_and_marks_only_printed_lines() -> None:
    r = run(index(), symbol="parse", direction="callees", depth=1, filter_identifier="len")
    # `parse` có 7 dòng khớp: giữ hai dòng if/return rồi mới tới dòng khác; `->` không được coi là phép so sánh.
    # `check_len` khớp ở dòng khai báo (15) và dòng return (16).
    assert r.shown_lines == {(FILE, n) for n in (7, 8, 12, 13, 15, 16)}
    for file, n in r.shown_lines:
        assert f"{file}:{n}: {SOURCE[n - 1].strip()}" in r.text


def test_filter_extracts_if_and_return_lines_across_the_chain() -> None:
    r = run(index(), symbol="entry", direction="callees", depth=1, filter_identifier="BAD_LEN")
    assert r.shown_lines == {(FILE, 3), (FILE, 12)}


def test_unknown_symbol_and_missing_index_do_not_raise() -> None:
    r = run(index(), symbol="nope", filter_identifier="len")
    assert "nope" in r.text and not r.shown_edges and not r.shown_lines
    assert run(None, symbol="entry").label is TrustLabel.DERIVED


def test_large_output_is_cut_and_unprinted_edges_are_not_marked_shown() -> None:
    names = [f"callee_{i:02d}_" + "x" * 500 for i in range(40)]
    idx = InMemoryCodeIndex(
        sources={FILE: SOURCE},
        symbols=[SymbolInfo(FILE, n, "function", 1, 1) for n in ["root", *names]],
        calls={("root", n) for n in names},
    )
    r = run(idx, symbol="root", direction="callees", max_nodes=40)
    assert len(r.text.encode("utf-8")) <= 16 * 1024
    assert 0 < len(r.shown_edges) < 40
    assert all(f"{a} -> {b} " in r.text for a, b in r.shown_edges)

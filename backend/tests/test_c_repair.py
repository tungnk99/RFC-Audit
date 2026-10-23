"""Đường lui của chỉ mục C: hàm tree-sitter bỏ sót hoặc cắt ngắn do macro (đo trên wolfSSL `src/internal.c`)."""

from __future__ import annotations

from rfcv.codeindex.c_repair import find_functions, repair_symbols

SRC = """\
#define X(a) \
    (a)

static int GetRecordHeader(WOLFSSL* ssl, word32* inOutIdx,
                           RecordLayerHeader* rh, word16 *size)
{
    int ret = 0;
#if defined(A)
    if (ret) {
    }
#endif
    return ret;
}

static int
Plain(int x)
{
    return x;
}

struct S {
    int a;
};
"""


def test_finds_multiline_head_and_closing_brace_at_column_zero() -> None:
    funcs = {name: (a, b) for name, a, b, _ in find_functions(SRC.split("\n"))}
    assert funcs["GetRecordHeader"] == (3, 12)
    assert funcs["Plain"] == (14, 18)  # kiểu trả về ở dòng trên
    assert "S" not in funcs and "X" not in funcs


def test_repair_adds_missing_extends_truncated_and_drops_inner_variables() -> None:
    lines = SRC.split("\n")
    have = [
        ("f.c", "Plain", "function", 14, 15, "int Plain(int x)"),
        ("f.c", "ret", "variable", 6, 6, "int ret = 0;"),
    ]
    out = {(s[1], s[2]): (s[3], s[4]) for s in repair_symbols("f.c", lines, have)}
    assert out[("GetRecordHeader", "function")] == (3, 12)
    assert out[("Plain", "function")][1] == 18
    assert ("ret", "variable") not in out


def test_repair_never_shrinks_or_removes_treesitter_functions() -> None:
    lines = SRC.split("\n")
    have = [("f.c", "Plain", "function", 14, 40, "int Plain(int x)")]
    out = {s[1]: (s[3], s[4]) for s in repair_symbols("f.c", lines, have)}
    assert out["Plain"] == (14, 40)


PP = """\
int f(int e) {
#ifndef WOLFSSL_TLS13
    if (a != b)
#else
    if (a != b ||
        c != d)
#endif
    {
#if defined(A) && !defined(B) || 0
        x();
#elif DEFINED_LATER > 1
        y();
#else
        z();
#endif
    }
}
"""


def test_preproc_branches_follow_the_directive_structure_not_the_syntax_tree() -> None:
    from rfcv.codeindex.c_repair import parse_pp_condition, preproc_branches

    got = {(c, i): (a, b, cond) for c, i, a, b, cond in preproc_branches(PP.split("\n"))}
    assert got[(1, 0)][:2] == (2, 3) and got[(1, 1)][:2] == (4, 7)  # nhánh #else dài tới #endif, không kéo dài hơn
    assert got[(1, 0)][2] == {"op": "not", "a": {"op": "defined", "name": "WOLFSSL_TLS13"}}
    assert got[(1, 1)][2] == {"op": "else"}
    assert got[(2, 0)][:2] == (9, 10) and got[(2, 1)][:2] == (11, 12) and got[(2, 2)][:2] == (13, 15)
    assert got[(2, 0)][2]["op"] == "or"
    assert got[(2, 1)][2] == {
        "op": "cmp",
        "o": ">",
        "a": {"op": "ident", "name": "DEFINED_LATER"},
        "b": {"op": "num", "v": 1},
    }
    assert parse_pp_condition("1 + 2") == {"op": "unknown"}


def test_continued_directive_lines_and_comments() -> None:
    from rfcv.codeindex.c_repair import preproc_branches

    src = ["#if defined(A) || \\", "    defined(B) /* why */", "x;", "#endif"]
    ((chain, idx, a, b, cond),) = preproc_branches(src)
    assert (chain, idx, a, b) == (1, 0, 1, 4) and cond["op"] == "or"

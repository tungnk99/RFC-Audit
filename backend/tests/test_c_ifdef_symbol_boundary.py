"""Ranh giới hàm C kiểu K&R có `#if` cắt ngang câu lệnh (gen-53, mô phỏng `read_kex_algos` của Dropbear)."""

from __future__ import annotations

from pathlib import Path

import pytest

from rfcv.codeindex.c_repair import find_functions

SOURCE = """\
static void read_kex_algos(void);

static void read_kex_algos() {
	algo_type * algo = NULL;
	char * erralgo = NULL;

#if DROPBEAR_EXT_INFO
	if (IS_SERVER) {
		ses.allow_ext_info = 1;
	}
#endif

	algo = buf_match_algo(ses.payload, sshkex);
	if (algo == NULL) {
		erralgo = "kex";
		goto error;
	}
	TRACE(("kexguess2 %d", kexguess2))
	DEBUG3(("kex algo %s", algo->name))

#if DROPBEAR_AEAD_MODE
	if (c2s_cipher->aead_crypt != NULL) {
		c2s_hash = NULL;
	} else
#endif
	if (c2s_hash == NULL) {
		erralgo = "mac c->s";
		goto error;
	}
	DEBUG2(("hmac c2s is %s", c2s_hash ? c2s_hash->name : "<implicit>"))

	if (buf_getbool(ses.payload)) {
#if DROPBEAR_AEAD_MODE
			s2c_hash == NULL ? ses.recv_crypt->aead_mac :
#endif
			(struct dropbear_hash*)s2c_hash->data;
#if DROPBEAR_AEAD_MODE
			c2s_hash == NULL ? ses.trans_crypt->aead_mac :
#endif
			(struct dropbear_cipher_mode*)s2c_cipher->mode;
#if DROPBEAR_AEAD_MODE
			c2s_hash == NULL ? ses.recv_crypt->aead_mac :
#endif
			(struct dropbear_hash*)c2s_hash->data;
#if DROPBEAR_AEAD_MODE
			s2c_hash == NULL ? ses.trans_crypt->aead_mac :
#endif
		ses.trans_comp = s2c_comp->val;
	}
#if DROPBEAR_FUZZ
	if (fuzz.fuzzing) {
	}
#endif
	return;

error:
	dropbear_exit("No matching algo %s", erralgo);
}

static void after(void) {
	done();
}
""".splitlines()


def _line_of(needle: str) -> int:
    return next(i for i, row in enumerate(SOURCE, 1) if needle in row)


def test_containing_symbol_covers_lines_after_ifdef_blocks(tmp_path: Path) -> None:
    pytest.importorskip("tree_sitter_c")
    from rfcv.codeindex.builder import build_index
    from rfcv.codeindex.sqlite_index import SqliteCodeIndex

    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "kex.c").write_text("\n".join(SOURCE) + "\n", encoding="utf-8")
    build_index(tmp_path / "repo", tmp_path / "index.db")
    index = SqliteCodeIndex(tmp_path / "index.db")
    start = _line_of("static void read_kex_algos() {")
    end = _line_of("static void after(void)") - 2
    for needle in ("buf_match_algo", 'erralgo = "kex"', 'erralgo = "mac c->s"', "s2c_comp->val", "dropbear_exit"):
        sym = index.containing_symbol("kex.c", _line_of(needle))
        assert sym is not None, needle
        assert (sym.name, sym.kind, sym.line_start, sym.line_end) == ("read_kex_algos", "function", start, end)
    after = index.containing_symbol("kex.c", _line_of("done();"))
    assert after is not None and after.name == "after"


def test_find_functions_same_line_brace_with_wrapped_parameters_and_ifdef_headers() -> None:
    lines = [
        "static int",
        "parse(const char *buf,",
        "\t\tsize_t len) {  /* comment */",
        "\treturn 0;",
        "} /* parse */",
        "#ifdef A",
        "void pick(int a) {",
        "#else",
        "void pick(void) {",
        "#endif",
        "\trun();",
        "}",
    ]
    assert [(n, a, b) for n, a, b, _ in find_functions(lines)] == [("parse", 1, 5), ("pick", 7, 12)]


@pytest.mark.parametrize(
    "lines",
    [
        ["static const struct x table[] = {", "\t{1},", "};"],
        ["struct s {", "\tint a;", "}"],
        ["TABLE(foo) = {", "\t1,", "}"],
        ["if (x) {", "\ty();", "}"],
        ["void a(void) {", "\tx();", "};"],
        # `}` đóng thân bị thụt lề: không được kéo `a` trùm lên hàm kế tiếp.
        ["void a(void) {", "\tx();", "\t}", "void b(void) {", "\ty();", "}"],
    ],
)
def test_find_functions_same_line_brace_rejects_ambiguous_shapes(lines: list[str]) -> None:
    assert [n for n, *_ in find_functions(lines) if n != "b"] == []

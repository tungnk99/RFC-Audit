"""Khám phá mã: mô tả công cụ kiểu MCP, explore, bản sao phạm vi tại commit, chỉ mục tree-sitter, Locator, cạnh textual."""

from __future__ import annotations

import contextlib
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from rfcv.codeindex.sqlite_index import eval_cond, parse_build_flags
from rfcv.codeindex.workspace import WorkspaceError, git_head, prepare_workspace, stage_scope
from rfcv.core.policy import PolicyStore
from rfcv.core.trace import TraceLog
from rfcv.domains.rfc_protocol.payloads import AspectName, AspectValue, Finding
from rfcv.domains.rfc_protocol.schema_gate import SchemaGate
from rfcv.domains.rfc_protocol.schemas import AspectClaim, CheckKind, LocationClaim
from rfcv.gates import explore_policy
from rfcv.gates.code_gate import InMemoryCodeIndex, Reference, SymbolInfo, build_code_tools
from rfcv.gates.explore_policy import CodeScope, CommandRejected
from rfcv.gates.tool_gateway import ToolGateway, ToolSession
from rfcv.testing import check_code_index_contract

# ---------------------------------------------------------------- dữ liệu mẫu

SRC = [f"/* line {i} */" for i in range(1, 200)]
SRC[19] = "static int GetRecordHeader(WOLFSSL* ssl, word16* size)"
SRC[24] = "    if (*size > MAX_RECORD_SIZE + MAX_MSG_EXTRA) {"
SRC[25] = "        SendAlert(ssl, alert_fatal, record_overflow);"
SRC[99] = "static const Handler handlers[] = {"
SRC[100] = "    ProcessHandshake,"
SRC[101] = "};"
SRC[119] = "int Dispatch(WOLFSSL* ssl, int t)"
SRC[121] = "    return handlers[t](ssl);"


@pytest.fixture
def index() -> InMemoryCodeIndex:
    return InMemoryCodeIndex(
        sources={"src/internal.c": SRC},
        symbols=[
            SymbolInfo("src/internal.c", "GetRecordHeader", "function", 20, 40, "static int GetRecordHeader(...)"),
            SymbolInfo("src/internal.c", "handlers", "variable", 100, 102, "static const Handler handlers[] = {"),
            SymbolInfo("src/internal.c", "Dispatch", "function", 120, 125, "int Dispatch(WOLFSSL* ssl, int t)"),
            SymbolInfo("src/internal.c", "ProcessHandshake", "function", 150, 170, "int ProcessHandshake(...)"),
        ],
        calls={("ProcessReply", "GetRecordHeader")},
        refs=[Reference("src/internal.c", 101, "handlers", "fn_pointer")],
    )


class EchoExecutor:
    def __init__(self, output: str) -> None:
        self.output = output
        self.calls: list[list[list[str]]] = []

    async def run(self, segments: list[list[str]], timeout_s: float) -> str:
        self.calls.append(segments)
        return self.output


@pytest.fixture
def scope(tmp_path: Path) -> CodeScope:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "internal.c").write_text("\n".join(SRC) + "\n")
    return CodeScope(root=tmp_path, include=("src/**",), exclude=("**/*.key",))


def gateway(
    policy: PolicyStore, trace: TraceLog, index: InMemoryCodeIndex, scope: CodeScope, out: str = ""
) -> ToolGateway:
    gw = ToolGateway(policy, trace)
    for spec in build_code_tools(index, EchoExecutor(out), scope):
        gw.register(spec)
    return gw


def session() -> ToolSession:
    return ToolSession("run-test", "code_reader", "TLS13-0042", max_tool_calls=30)


# ---------------------------------------------------------------- mô tả công cụ kiểu MCP


def test_tools_are_described_like_mcp(
    policy: PolicyStore, trace: TraceLog, index: InMemoryCodeIndex, scope: CodeScope
) -> None:
    listing = gateway(policy, trace, index, scope).tools_list("code_reader")["tools"]
    names = {t["name"] for t in listing}
    assert {
        "code__list_dir", "code__file_outline", "code__search_text", "code__search_symbol", "code__read_function",
        "code__read_range", "code__get_definition", "code__find_references", "code__callees", "code__explore",
    } <= names  # fmt: skip
    for tool in listing:
        assert {"name", "title", "description", "inputSchema", "annotations"} <= set(tool)
        assert "Ví dụ" in tool["description"] and "Trả về" in tool["description"]
        assert tool["annotations"]["readOnlyHint"] is True and tool["annotations"]["openWorldHint"] is False
        for prop in tool["inputSchema"].get("properties", {}).values():
            assert prop.get("description"), tool["name"]
    # vai trò đặc quyền không thấy công cụ đọc mã
    assert gateway(policy, trace, index, scope).tools_list("planner")["tools"] == []


# ---------------------------------------------------------------- explore


def test_explore_scope_allows_parent_dir_of_included_files(scope: CodeScope) -> None:
    assert explore_policy.validate("rg -n record_overflow src", scope)  # include là "src/**", không ghi "src"


@pytest.mark.parametrize(
    "cmd",
    [
        "rg -n 'record_overflow$' src",
        "sg run -p 'SendAlert($S, $L, record_overflow)' -l c src",
        "grep -n -e 'x$' -r src",
    ],
)
def test_explore_allows_dollar_only_inside_patterns(cmd: str, scope: CodeScope) -> None:
    assert explore_policy.validate(cmd, scope)


@pytest.mark.parametrize(
    ("cmd", "code"),
    [
        ("ls $HOME", "FORBIDDEN_SYNTAX"),
        ("rg x ${PWD}", "FORBIDDEN_SYNTAX"),
        ("cat src/internal.c", "FLAG_NOT_ALLOWED"),
        ("grep -R x src", "FLAG_NOT_ALLOWED"),
    ],
)
def test_explore_new_rejections(cmd: str, code: str, scope: CodeScope) -> None:
    with pytest.raises(CommandRejected) as exc:
        explore_policy.validate(cmd, scope)
    assert exc.value.code == code


async def test_explore_sed_output_is_numbered_and_counts_as_shown(
    policy: PolicyStore, trace: TraceLog, index: InMemoryCodeIndex, scope: CodeScope
) -> None:
    gw = gateway(policy, trace, index, scope, out="\n".join(SRC[23:26]) + "\n")
    s = session()
    result = await gw.call(s, "code.explore", {"command": "sed -n '24,26p' src/internal.c"})
    assert "    25     if (*size > MAX_RECORD_SIZE" in result.text
    assert {("src/internal.c", n) for n in (24, 25, 26)} <= s.shown_lines


async def test_explore_denial_reason_is_logged_but_not_returned(
    policy: PolicyStore, trace: TraceLog, index: InMemoryCodeIndex, scope: CodeScope
) -> None:
    gw = gateway(policy, trace, index, scope)
    with pytest.raises(Exception, match="COMMAND_REJECTED"):
        await gw.call(session(), "code.explore", {"command": "find src -delete"})
    denied = list(trace.events("tool_denied"))
    assert denied[-1]["payload"]["reason"] == "FLAG_BLOCKED"


# ---------------------------------------------------------------- công cụ cấu trúc


async def test_search_text_reports_containing_function_and_ignores_fake_locations(
    policy: PolicyStore, trace: TraceLog, index: InMemoryCodeIndex, scope: CodeScope
) -> None:
    out = (
        "./src/internal.c-25-    if (*size > MAX_RECORD_SIZE + MAX_MSG_EXTRA) {\n"
        "./src/internal.c:26:        SendAlert(ssl, alert_fatal, record_overflow);\n"
        "nothere.c:5: không phải tệp trong chỉ mục\n"
    )
    gw = gateway(policy, trace, index, scope, out=out)
    s = session()
    result = await gw.call(s, "code.search_text", {"regex": "record_overflow"})
    assert "hàm chứa: src/internal.c GetRecordHeader" in result.text
    assert {("src/internal.c", 25), ("src/internal.c", 26)} <= s.shown_lines
    assert not any(f == "nothere.c" for f, _ in s.shown_lines)


async def test_find_references_shows_code_line_and_pointer_edge(
    policy: PolicyStore, trace: TraceLog, index: InMemoryCodeIndex, scope: CodeScope
) -> None:
    gw = gateway(policy, trace, index, scope)
    s = session()
    result = await gw.call(s, "code.find_references", {"name": "ProcessHandshake"})
    assert "src/internal.c:101: [fn_pointer in handlers] ProcessHandshake," in result.text
    assert ("src/internal.c", 101) in s.shown_lines and ("handlers", "ProcessHandshake") in s.shown_edges


async def test_read_function_disambiguates_same_name(
    policy: PolicyStore, trace: TraceLog, index: InMemoryCodeIndex, scope: CodeScope
) -> None:
    index.sources["src/tls13.c"] = SRC
    index.symbols.append(SymbolInfo("src/tls13.c", "GetRecordHeader", "function", 20, 40))
    gw = gateway(policy, trace, index, scope)
    first = await gw.call(session(), "code.read_function", {"symbol": "GetRecordHeader"})
    assert "cùng tên còn: src/tls13.c:20" in first.text
    chosen = await gw.call(session(), "code.read_function", {"symbol": "GetRecordHeader", "file": "src/tls13.c"})
    assert "tool=read_function src/tls13.c GetRecordHeader" in chosen.text


# ---------------------------------------------------------------- Schema gate: cạnh textual


def _claim(call_path: list[str]) -> LocationClaim:
    return LocationClaim(
        file="src/internal.c",
        symbol="ProcessHandshake",
        line_start=150,
        line_end=152,
        check_kind=CheckKind.STATE_CHECK,
        finding=Finding.PRESENT,
        aspects=[AspectClaim(aspect=AspectName.CONDITION, value=AspectValue.MATCH, lines=(150, 151))],
        call_path=call_path,
    )


def test_textual_edge_through_function_pointer_table(index: InMemoryCodeIndex) -> None:
    gate = SchemaGate(index, set())
    s = session()
    s.shown_lines |= {("src/internal.c", n) for n in (*range(150, 153), 101, 122)}
    result = gate.check_location(
        _claim(["Dispatch", "handlers", "ProcessHandshake"]), s, run_id="r", requirement_id="R", msg_id="m"
    )
    assert result.accepted and result.draft is not None
    assert result.draft.payload.call_edge_kinds == ("textual", "textual")  # type: ignore[attr-defined]
    # chưa đọc dòng trong bảng thì cạnh không có căn cứ
    s2 = session()
    s2.shown_lines |= {("src/internal.c", n) for n in (*range(150, 153), 122)}
    bad = gate.check_location(
        _claim(["Dispatch", "handlers", "ProcessHandshake"]), s2, run_id="r", requirement_id="R", msg_id="m"
    )
    assert "CALL_EDGE_UNKNOWN" in bad.errors


# ---------------------------------------------------------------- tiền xử lý


def test_build_flag_evaluation_is_three_valued() -> None:
    defines, undefs = parse_build_flags(["--enable-tls13", "-DWOLFSSL_TLS13", "-DLEVEL=2", "-UNO_TLS"])
    assert defines == {"WOLFSSL_TLS13": "1", "LEVEL": "2"} and undefs == {"NO_TLS"}
    d = {"op": "defined", "name": "WOLFSSL_TLS13"}
    assert eval_cond(d, defines, undefs) is True
    assert eval_cond({"op": "not", "a": {"op": "defined", "name": "NO_TLS"}}, defines, undefs) is True
    assert eval_cond({"op": "defined", "name": "HAVE_UNKNOWN"}, defines, undefs) is None
    assert eval_cond({"op": "and", "a": d, "b": {"op": "defined", "name": "HAVE_UNKNOWN"}}, defines, undefs) is None
    assert eval_cond({"op": "or", "a": d, "b": {"op": "defined", "name": "HAVE_UNKNOWN"}}, defines, undefs) is True
    assert (
        eval_cond(
            {"op": "cmp", "o": ">=", "a": {"op": "ident", "name": "LEVEL"}, "b": {"op": "num", "v": 2}}, defines, undefs
        )
        is True
    )
    assert eval_cond({"op": "num", "v": 0}, defines, undefs) == 0


# ---------------------------------------------------------------- bản sao phạm vi tại commit


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "wolfssl"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "internal.c").write_text("int a;\n")
    (repo / "certs").mkdir()
    (repo / "certs" / "server.key").write_text("SECRET\n")
    (repo / "src" / "ca.pem").write_text("CERT\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "t.c").write_text("int t;\n")
    git = repo / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/master\n")
    (git / "refs" / "heads" / "master").write_text("a" * 40 + "\n")
    return repo


def test_git_head_reads_refs_without_running_git(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert git_head(repo) == "a" * 40
    (repo / ".git" / "refs" / "heads" / "master").unlink()
    (repo / ".git" / "packed-refs").write_text("# pack-refs\n" + "b" * 40 + " refs/heads/master\n")
    assert git_head(repo) == "b" * 40
    (repo / ".git" / "HEAD").write_text("c" * 40 + "\n")
    assert git_head(repo) == "c" * 40


def test_stage_scope_copies_only_scope_files(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    if hasattr(os, "symlink"):
        with contextlib.suppress(OSError):  # Windows không có quyền tạo symlink
            (repo / "src" / "escape.c").symlink_to(tmp_path / "outside.c")
    digest, files, _skipped = stage_scope(repo, ("src/**",), ("**/*.pem", "**/*.key"), tmp_path / "stage")
    staged = sorted(
        p.relative_to(tmp_path / "stage").as_posix() for p in (tmp_path / "stage").rglob("*") if p.is_file()
    )
    assert staged == ["src/internal.c"] and files == 1 and digest.startswith("sha256:")


def test_prepare_workspace_verifies_commit(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with pytest.raises(WorkspaceError, match="adapter yêu cầu"):
        prepare_workspace(repo, tmp_path / "code1", ("src/**",), (), "f" * 40)
    ws = prepare_workspace(repo, tmp_path / "code2", ("src/**",), (), "a" * 40)
    assert ws.commit == "a" * 40 and ws.manifest_entries()["code:commit"] == "a" * 40
    assert prepare_workspace(repo, tmp_path / "code2", ("src/**",), (), "a" * 40) == ws  # dùng lại


# ---------------------------------------------------------------- Locator


def test_locator_ranks_by_documented_formula(index: InMemoryCodeIndex) -> None:
    from agents.locator.service import Locator

    index.calls |= {("ProcessReply", "GetRecordHeader")}
    manifest = SimpleNamespace(
        component_taxonomy=("record_layer", "handshake"),
        locator_hints={
            "record_layer": {
                "keywords": ("MAX_RECORD_SIZE", "record"),
                "entry_points": ("ProcessReply",),
                "paths": ("src/internal.c",),
            }
        },
    )
    loc = Locator(index, manifest)
    loc.register("TLS13-0042", ("record", "length", "record_overflow"))
    component, _kws, ranked = loc.suggest("TLS13-0042")
    assert component == "record_layer"
    top = ranked[0]
    assert top.symbol.name == "GetRecordHeader"
    # kw: record, record_overflow, MAX_RECORD_SIZE; near: cách điểm vào 1 bước; hint: đúng đường dẫn
    assert top.kw == 3 and top.near == pytest.approx(0.5) and top.hint == 1
    assert top.score == pytest.approx(3 * top.kw + 2 * top.comp + 2 * 0.5 + 1)


# ---------------------------------------------------------------- chỉ mục tree-sitter thật

C_SOURCE = """\
#define MAX_RECORD_SIZE 16384
enum AlertDescription { decode_error = 50, record_overflow = 22 };

static int GetRecordHeader(int size)
{
    if (size > MAX_RECORD_SIZE) {
        SendAlert(record_overflow);
        return -1;
    }
    return 0;
}

#ifdef WOLFSSL_TLS13
static int Tls13Only(void) { return 1; }
#else
static int Tls12Only(void) { return 2; }
#endif

#if 0
static int Dead(void) { return 3; }
#endif

typedef int (*Handler)(int);
static Handler handlers[] = { GetRecordHeader };

int ProcessReply(int size)
{
    int n = GetRecordHeader(size);
    n = handlers[0](size);
    return n;
}
"""


def test_treesitter_index_on_c(tmp_path: Path) -> None:
    pytest.importorskip("tree_sitter_c")
    from rfcv.codeindex.builder import build_index
    from rfcv.codeindex.sqlite_index import SqliteCodeIndex

    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "internal.c").write_text(C_SOURCE)
    meta = build_index(root, tmp_path / "index.db")
    assert meta["format"] == "rfcv-codeindex/1" and meta["parsed"] == "1"
    idx = SqliteCodeIndex(tmp_path / "index.db")
    try:
        assert not check_code_index_contract(idx, "src/internal.c")
        fn = idx.symbol_in_file("src/internal.c", "GetRecordHeader")
        assert fn is not None and fn.kind == "function" and (fn.line_start, fn.line_end) == (4, 11)
        assert {s.kind for s in idx.lookup("MAX_RECORD_SIZE")} == {"macro"}
        assert {s.kind for s in idx.lookup("record_overflow")} == {"enumerator"}
        assert idx.has_call_edge("ProcessReply", "GetRecordHeader")
        assert ("SendAlert", 7) in idx.callees("GetRecordHeader")
        kinds = {(r.container, r.kind) for r in idx.references("GetRecordHeader")}
        assert ("ProcessReply", "call") in kinds and ("handlers", "fn_pointer") in kinds
        sym = idx.containing_symbol("src/internal.c", 6)
        assert sym is not None and sym.name == "GetRecordHeader"
        # #if 0 luôn tắt; #ifdef WOLFSSL_TLS13 bật theo -D thì nhánh #else tắt
        compiled = idx.compiled_lines("src/internal.c", ["-DWOLFSSL_TLS13"])
        assert compiled is not None
        assert 14 in compiled and 16 not in compiled and 20 not in compiled and 6 in compiled
        unknown = idx.compiled_lines("src/internal.c", [])
        assert unknown is not None and 14 in unknown and 16 in unknown and 20 not in unknown
    finally:
        idx.close()


@pytest.mark.skipif(shutil.which("rg") is None, reason="cần ripgrep trên máy")
async def test_local_executor_runs_argv_without_shell(tmp_path: Path) -> None:
    from rfcv.codeindex.executors import LocalExecutor

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.c").write_text("int x; /* $(id) */\nrecord_overflow;\n")
    ex = LocalExecutor(tmp_path)
    out = await ex.run([["rg", "-n", "record_overflow", "src"], ["wc", "-l"]], timeout_s=10)
    assert out.strip() == "1"
    none = await ex.run([["rg", "-n", "no_such_token", "src"]], timeout_s=10)
    assert none == ""

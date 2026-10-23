"""Bộ công cụ đọc mã kiểu Claude Code: grep, glob, read, eval (và bộ tính biểu thức C `cexpr`)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from rfcv.core.policy import PolicyStore
from rfcv.core.trace import TraceLog
from rfcv.gates import cexpr
from rfcv.gates.code_gate import InMemoryCodeIndex, SymbolInfo, build_code_tools
from rfcv.gates.code_tools import GlobParams, GrepParams, ReadParams
from rfcv.gates.explore_policy import CodeScope
from rfcv.gates.tool_gateway import ToolGateway, ToolSession

SOURCE = [f"/* line {i} */" for i in range(1, 1500)]
SOURCE[811] = "    if (*size > MAX_RECORD_SIZE + MAX_MSG_EXTRA) {"
SOURCE[814] = "        SendAlert(ssl, alert_fatal, record_overflow);"
HEADER = [f"/* h {i} */" for i in range(1, 300)]
HEADER[99] = "#define MAX_RECORD_SIZE 16384"
HEADER[109] = "    MAX_MSG_EXTRA   = 38 + WC_MAX_DIGEST_SIZE,"
HEADER[119] = "#define WC_MAX_DIGEST_SIZE 64"


class RecordingExecutor:
    def __init__(self, output: str = "") -> None:
        self.output = output
        self.argvs: list[list[str]] = []

    async def run(self, segments: list[list[str]], timeout_s: float) -> str:
        self.argvs += segments
        return self.output


@pytest.fixture
def index() -> InMemoryCodeIndex:
    return InMemoryCodeIndex(
        sources={"src/internal.c": list(SOURCE), "wolfssl/internal.h": list(HEADER)},
        symbols=[
            SymbolInfo("src/internal.c", "GetRecordHeader", "function", 800, 830, "static int GetRecordHeader(...)"),
            SymbolInfo("src/internal.c", "Big", "function", 900, 1400, "int Big(void)"),
            SymbolInfo("wolfssl/internal.h", "MAX_RECORD_SIZE", "macro", 100, 100),
            SymbolInfo("wolfssl/internal.h", "MAX_MSG_EXTRA", "enumerator", 110, 110),
            SymbolInfo("wolfssl/internal.h", "WC_MAX_DIGEST_SIZE", "macro", 120, 120),
        ],
    )


def gateway(policy: PolicyStore, trace: TraceLog, index: InMemoryCodeIndex, ex: RecordingExecutor) -> ToolGateway:
    gw = ToolGateway(policy, trace)
    for spec in build_code_tools(index, ex, CodeScope(root=Path(".")), ()):
        gw.register(spec)
    return gw


def session() -> ToolSession:
    return ToolSession("run-test", "code_reader", "TLS13-0042", max_tool_calls=30)


async def test_grep_builds_a_fixed_argv_and_annotates_the_containing_function(
    policy: PolicyStore, trace: TraceLog, index: InMemoryCodeIndex
) -> None:
    ex = RecordingExecutor(
        "./src/internal.c-814-x\n./src/internal.c:815:        SendAlert(ssl, alert_fatal, record_overflow);"
    )
    s = session()
    r = await gateway(policy, trace, index, ex).call(
        s, "code.grep", {"pattern": "record_overflow", "type": "c", "context": 3, "glob": "src/*.c"}
    )
    argv = ex.argvs[0]
    assert argv[:2] == ["rg", "--no-heading"] and "-C" in argv and argv[argv.index("-t") + 1] == "c"
    assert argv[-2:] == ["--", "."]
    assert "hàm chứa: src/internal.c GetRecordHeader [800–830] ← dòng 815" in r.text
    assert ("src/internal.c", 815) in s.shown_lines and ("src/internal.c", 814) in s.shown_lines


async def test_grep_pages_instead_of_denying_large_output(
    policy: PolicyStore, trace: TraceLog, index: InMemoryCodeIndex
) -> None:
    out = "\n--\n".join(f"./src/internal.c:{n}:hit {n}" for n in range(1, 301))
    r = await gateway(policy, trace, index, RecordingExecutor(out)).call(
        session(), "code.grep", {"pattern": "hit", "head_limit": 10}
    )
    assert "src/internal.c:10:hit 10" in r.text and "src/internal.c:11:hit 11" not in r.text
    assert "offset=10" in r.text


async def test_grep_reports_empty_results(policy: PolicyStore, trace: TraceLog, index: InMemoryCodeIndex) -> None:
    gw = gateway(policy, trace, index, RecordingExecutor(""))
    assert "(không có kết quả)" in (await gw.call(session(), "code.grep", {"pattern": "zzz"})).text


@pytest.mark.parametrize("bad", ["../etc/passwd", "/etc/passwd", "-e", "~/x", "src/../../x"])
def test_paths_cannot_escape_scope_or_inject_flags(bad: str) -> None:
    for model, field in ((GrepParams, "path"), (GrepParams, "glob"), (GlobParams, "path")):
        with pytest.raises(ValidationError):
            model.model_validate({"pattern": "x", field: bad})
    with pytest.raises(ValidationError):
        ReadParams.model_validate({"file": bad})


def test_read_needs_a_target() -> None:
    with pytest.raises(ValidationError):
        ReadParams.model_validate({"offset": 5})


async def test_read_returns_a_large_window_and_marks_every_returned_line_as_shown(
    policy: PolicyStore, trace: TraceLog, index: InMemoryCodeIndex
) -> None:
    s = session()
    r = await gateway(policy, trace, index, RecordingExecutor()).call(
        s, "code.read", {"file": "src/internal.c", "offset": 800, "limit": 300}
    )
    assert "lines 800–1099" in r.text and "of 1499" in r.text
    assert {("src/internal.c", n) for n in range(800, 1100)} <= s.shown_lines
    assert ("src/internal.c", 1100) not in s.shown_lines and "offset=1100" in r.text


async def test_read_symbol_returns_the_whole_function_and_pages_long_ones(
    policy: PolicyStore, trace: TraceLog, index: InMemoryCodeIndex
) -> None:
    gw = gateway(policy, trace, index, RecordingExecutor())
    whole = await gw.call(session(), "code.read", {"symbol": "GetRecordHeader"})
    assert "lines 800–830" in whole.text and "còn tiếp" not in whole.text
    page = await gw.call(session(), "code.read", {"symbol": "Big", "limit": 100})
    assert "lines 900–999" in page.text and "còn tiếp tới dòng 1400; đọc tiếp offset=101" in page.text


async def test_read_unknown_file_is_a_hint_not_a_crash(
    policy: PolicyStore, trace: TraceLog, index: InMemoryCodeIndex
) -> None:
    r = await gateway(policy, trace, index, RecordingExecutor()).call(session(), "code.read", {"file": "internal.h"})
    assert "không có trong phạm vi" in r.text


async def test_read_symbol_falls_back_to_ripgrep_when_the_index_misses_it(
    policy: PolicyStore, trace: TraceLog, index: InMemoryCodeIndex
) -> None:
    index.sources["src/internal.c"][399] = "static int MissedByIndex(WOLFSSL* ssl)"
    index.sources["src/internal.c"][400] = "{"
    index.sources["src/internal.c"][404] = "}"
    ex = RecordingExecutor("./src/internal.c:400:static int MissedByIndex(WOLFSSL* ssl)")
    r = await gateway(policy, trace, index, ex).call(session(), "code.read", {"symbol": "MissedByIndex"})
    assert "chỉ mục không có ký hiệu này" in r.text and "lines 400–405" in r.text


async def test_eval_resolves_nested_constants_and_marks_the_definition_lines_as_shown(
    policy: PolicyStore, trace: TraceLog, index: InMemoryCodeIndex
) -> None:
    s = session()
    r = await gateway(policy, trace, index, RecordingExecutor()).call(
        s, "code.eval", {"expr": "MAX_RECORD_SIZE + MAX_MSG_EXTRA"}
    )
    assert "giá trị: 16486" in r.text and "WC_MAX_DIGEST_SIZE = 64" in r.text
    assert ("wolfssl/internal.h", 110) in s.shown_lines


async def test_eval_never_guesses_unknown_names(policy: PolicyStore, trace: TraceLog, index: InMemoryCodeIndex) -> None:
    r = await gateway(policy, trace, index, RecordingExecutor()).call(session(), "code.eval", {"expr": "NOPE + 1"})
    assert "chưa xác định" in r.text and "NOPE" in r.text


def test_cexpr_precedence_shifts_casts_and_errors() -> None:
    table = {"A": ("1 << 14", "t"), "B": ("(word32)A + 256", "t")}
    assert cexpr.evaluate("B", lambda n: table.get(n)).value == 16640
    assert cexpr.evaluate("2 + 3 * 4", lambda n: None).value == 14
    assert cexpr.evaluate("0x10 | 1", lambda n: None).value == 17
    with pytest.raises(cexpr.EvalError):
        cexpr.evaluate("1 / 0", lambda n: None)
    with pytest.raises(cexpr.EvalError):
        cexpr.evaluate("1 +", lambda n: None)
    assert cexpr.strip_definition("#define X 5 /* five */", "X") == "5"
    assert cexpr.strip_definition("  MAX = 38 + D,", "MAX") == "38 + D"


async def test_eval_answers_defined_from_build_flags_and_definitions(
    policy: PolicyStore, trace: TraceLog, index: InMemoryCodeIndex
) -> None:
    gw = ToolGateway(policy, trace)
    for spec in build_code_tools(index, RecordingExecutor(), CodeScope(root=Path(".")), ("-DHAVE_X=1",)):
        gw.register(spec)
    yes = await gw.call(session(), "code.eval", {"expr": "defined(HAVE_X) + defined(MAX_RECORD_SIZE)"})
    assert "giá trị: 2" in yes.text
    no = await gw.call(session(), "code.eval", {"expr": "defined(HAVE_MAX_FRAGMENT)"})
    assert "giá trị: 0" in no.text and "không có -D" in no.text

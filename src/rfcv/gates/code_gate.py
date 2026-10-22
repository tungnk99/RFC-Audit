"""Code gate: cấp công cụ chỉ đọc trên chỉ mục mã cho vùng cách ly (giao diện I5).

Mọi kết quả mang nhãn UNTRUSTED, có tiêu đề `[UNTRUSTED CODE]`, có số dòng, và bị giới hạn kích thước.
Lớp bọc trích "tập dòng đã hiển thị" từ đầu ra để Schema gate kiểm tra (tài liệu khám phá mã, mục 6).
Chỉ mục thật (tree-sitter → SQLite) và bộ chạy lệnh trong container code-index-worker
cài đặt các Protocol bên dưới; InMemoryCodeIndex dùng cho kiểm thử.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from rfcv.core.ifc import TrustLabel
from rfcv.gates import explore_policy
from rfcv.gates.tool_gateway import DenyCode, ToolDenied, ToolResult, ToolSession, ToolSpec
from rfcv.spi import Effect, ToolDescriptor

MAX_LINES = 200
MAX_BYTES = 16 * 1024
READ_WINDOW = 100
MAX_RESULTS = 50

_LOCATED = re.compile(r"^(?P<file>[^:\s]+):(?P<line>\d+)[:-]")


@dataclass(frozen=True)
class SymbolInfo:
    file: str
    name: str
    kind: str
    line_start: int
    line_end: int
    signature: str = ""


@dataclass(frozen=True)
class Reference:
    file: str
    line: int
    container: str
    kind: str  # call | read | write | fn_pointer


class CodeIndex(Protocol):
    def files(self) -> Sequence[str]: ...
    def outline(self, file: str) -> Sequence[SymbolInfo]: ...
    def lookup(self, name: str) -> Sequence[SymbolInfo]: ...
    def symbol_in_file(self, file: str, name: str) -> SymbolInfo | None: ...
    def lines(self, file: str, start: int, end: int) -> Sequence[str]: ...
    def references(self, name: str) -> Sequence[Reference]: ...
    def callees(self, function: str) -> Sequence[tuple[str, int]]: ...
    def has_call_edge(self, caller: str, callee: str) -> bool: ...


class SandboxExecutor(Protocol):
    async def run(self, segments: list[list[str]], timeout_s: float) -> str: ...


@dataclass
class InMemoryCodeIndex:
    """Chỉ mục trong bộ nhớ cho kiểm thử và ví dụ; không phân tích mã."""

    sources: dict[str, list[str]]
    symbols: list[SymbolInfo] = field(default_factory=list[SymbolInfo])
    calls: set[tuple[str, str]] = field(default_factory=set[tuple[str, str]])
    refs: list[Reference] = field(default_factory=list[Reference])

    def files(self) -> Sequence[str]:
        return sorted(self.sources)

    def outline(self, file: str) -> Sequence[SymbolInfo]:
        return [s for s in self.symbols if s.file == file]

    def lookup(self, name: str) -> Sequence[SymbolInfo]:
        return [s for s in self.symbols if s.name == name]

    def symbol_in_file(self, file: str, name: str) -> SymbolInfo | None:
        return next((s for s in self.symbols if s.file == file and s.name == name), None)

    def lines(self, file: str, start: int, end: int) -> Sequence[str]:
        src = self.sources.get(file, [])
        return src[max(0, start - 1) : min(len(src), end)]

    def references(self, name: str) -> Sequence[Reference]:
        return [r for r in self.refs if r.container != name and name in self.lines(r.file, r.line, r.line)[0]]

    def callees(self, function: str) -> Sequence[tuple[str, int]]:
        sym = next((s for s in self.symbols if s.name == function), None)
        return [(callee, sym.line_start if sym else 0) for caller, callee in sorted(self.calls) if caller == function]

    def has_call_edge(self, caller: str, callee: str) -> bool:
        return (caller, callee) in self.calls


def _limit(text: str) -> str:
    if text.count("\n") + 1 > MAX_LINES or len(text.encode("utf-8")) > MAX_BYTES:
        raise ToolDenied(DenyCode.OUTPUT_TOO_LARGE)
    return text


def _numbered(index: CodeIndex, file: str, start: int, end: int) -> tuple[str, frozenset[tuple[str, int]]]:
    body = index.lines(file, start, end)
    shown = frozenset((file, start + i) for i in range(len(body)))
    return "\n".join(f"{start + i:>6} {line}" for i, line in enumerate(body)), shown


def located_lines(output: str) -> frozenset[tuple[str, int]]:
    """Trích (tệp, dòng) từ đầu ra dạng `tệp:dòng:` của rg/grep/explore."""
    out: set[tuple[str, int]] = set()
    for line in output.splitlines():
        m = _LOCATED.match(line)
        if m:
            out.add((m.group("file").removeprefix("./"), int(m.group("line"))))
    return frozenset(out)


def _untrusted(
    header: str,
    body: str,
    shown: frozenset[tuple[str, int]] = frozenset(),
    edges: frozenset[tuple[str, str]] = frozenset(),
) -> ToolResult:
    return ToolResult(_limit(f"[UNTRUSTED CODE] {header}\n{body}"), TrustLabel.UNTRUSTED, shown, edges)


class _P(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListDirParams(_P):
    path: str = "."
    depth: int = Field(default=1, ge=1, le=2)


class FileParams(_P):
    file: str


class SymbolParams(_P):
    name: str = Field(min_length=1, max_length=200)
    kind: str | None = None


class ReadFunctionParams(_P):
    symbol: str = Field(min_length=1, max_length=200)
    page: int = Field(default=1, ge=1)


class ReadRangeParams(_P):
    file: str
    start: int = Field(ge=1)
    end: int = Field(ge=1)


class SearchTextParams(_P):
    regex: str = Field(min_length=1, max_length=300)
    path_glob: str | None = None


class ExploreParams(_P):
    command: str = Field(min_length=1, max_length=500)


def build_code_tools(index: CodeIndex, executor: SandboxExecutor, scope: explore_policy.CodeScope) -> list[ToolSpec]:
    async def list_dir(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, ListDirParams)
        prefix = "" if p.path in (".", "") else p.path.rstrip("/") + "/"
        entries = sorted(
            {"/".join(f[len(prefix) :].split("/")[: p.depth]) for f in index.files() if f.startswith(prefix)}
        )
        return _untrusted(f"tool=list_dir {p.path}", "\n".join(entries[: MAX_LINES - 1]))

    async def file_outline(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, FileParams)
        syms = index.outline(p.file)
        body = "\n".join(f"{x.line_start:>6} {x.kind} {x.signature or x.name}" for x in syms[: MAX_LINES - 1])
        return _untrusted(f"tool=file_outline {p.file}", body, frozenset((p.file, x.line_start) for x in syms))

    async def search_symbol(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, SymbolParams)
        hits = [x for x in index.lookup(p.name) if p.kind is None or x.kind == p.kind][:MAX_RESULTS]
        body = "\n".join(f"{x.file}:{x.line_start}: {x.kind} {x.signature or x.name}" for x in hits)
        return _untrusted(f"tool=search_symbol {p.name}", body, located_lines(body))

    async def read_function(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, ReadFunctionParams)
        syms = index.lookup(p.symbol)
        if not syms:
            return _untrusted(f"tool=read_function {p.symbol}", "(không tìm thấy ký hiệu)")
        sym = syms[0]
        start = sym.line_start + (p.page - 1) * READ_WINDOW
        end = min(sym.line_end, start + READ_WINDOW - 1)
        pages = max(1, -(-(sym.line_end - sym.line_start + 1) // READ_WINDOW))
        body, shown = _numbered(index, sym.file, start, end)
        return _untrusted(
            f"tool=read_function {sym.file} {sym.name} lines {start}–{end} page {p.page}/{pages}", body, shown
        )

    async def read_range(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, ReadRangeParams)
        end = min(p.end, p.start + READ_WINDOW - 1)
        body, shown = _numbered(index, p.file, p.start, end)
        return _untrusted(f"tool=read_range {p.file} lines {p.start}–{end}", body, shown)

    async def get_definition(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, SymbolParams)
        parts: list[str] = []
        shown: set[tuple[str, int]] = set()
        for sym in index.lookup(p.name)[:3]:
            body, sh = _numbered(index, sym.file, sym.line_start, min(sym.line_end, sym.line_start + 30))
            parts.append(f"{sym.file} {sym.kind} {sym.name}\n{body}")
            shown |= sh
        return _untrusted(
            f"tool=get_definition {p.name}", "\n".join(parts) or "(không có định nghĩa)", frozenset(shown)
        )

    async def find_references(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, SymbolParams)
        refs = list(index.references(p.name))[:MAX_RESULTS]
        body = "\n".join(f"{r.file}:{r.line}: {r.kind} in {r.container}" for r in refs)
        edges = frozenset((r.container, p.name) for r in refs if r.kind in ("call", "fn_pointer"))
        return _untrusted(f"tool=find_references {p.name}", body, located_lines(body), edges)

    async def callees(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, SymbolParams)
        found = list(index.callees(p.name))[:100]
        body = "\n".join(f"{name} (line {line})" for name, line in found)
        return _untrusted(f"tool=callees {p.name}", body, edges=frozenset((p.name, n) for n, _ in found))

    async def search_text(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, SearchTextParams)
        argv = ["rg", "-n", "-C", "2", "-m", str(MAX_RESULTS), "-e", p.regex]
        if p.path_glob:
            argv += ["-g", p.path_glob]
        out = await executor.run([[*argv, "."]], timeout_s=10)
        return _untrusted(f"tool=search_text {p.regex!r}", out, located_lines(out))

    async def explore(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, ExploreParams)
        try:
            segments = explore_policy.validate(p.command, scope)
        except explore_policy.CommandRejected as exc:
            raise ToolDenied(DenyCode.COMMAND_REJECTED) from exc
        out = await executor.run(segments, timeout_s=10)
        return _untrusted(f"tool=explore cmd={p.command!r}", out, located_lines(out))

    return [
        ToolSpec("code.list_dir", "Cây thư mục trong phạm vi adapter.", ListDirParams, list_dir),
        ToolSpec("code.file_outline", "Chữ ký hàm, struct, macro trong một tệp, kèm dòng.", FileParams, file_outline),
        ToolSpec("code.search_symbol", "Ký hiệu khớp tên: loại, tệp, dòng, chữ ký.", SymbolParams, search_symbol),
        ToolSpec("code.read_function", "Thân hàm có số dòng, 100 dòng mỗi trang.", ReadFunctionParams, read_function),
        ToolSpec("code.read_range", "Đoạn mã bất kỳ có số dòng, tối đa 100 dòng.", ReadRangeParams, read_range),
        ToolSpec("code.get_definition", "Định nghĩa macro, hằng, struct, kiểu.", SymbolParams, get_definition),
        ToolSpec(
            "code.find_references",
            "Mọi chỗ dùng ký hiệu, kèm hàm chứa và loại tham chiếu.",
            SymbolParams,
            find_references,
        ),
        ToolSpec("code.callees", "Các hàm được gọi trong thân hàm.", SymbolParams, callees),
        ToolSpec(
            "code.search_text", "Tìm theo regex, ±2 dòng ngữ cảnh, tối đa 50 kết quả.", SearchTextParams, search_text
        ),
        ToolSpec(
            "code.explore",
            "Lệnh đọc trong danh sách cho phép (rg, sg, find, sed -n, head…), nối bằng |.",
            ExploreParams,
            explore,
        ),
    ]


# Khai báo công cụ đọc mã để Policy store kiểm tra lúc nạp. Mọi công cụ ở đây đọc dữ liệu không tin cậy,
# nên chỉ agent vùng cách ly được có. Công cụ chạy lệnh trong sandbox khai SANDBOXED_RUN.
CODE_TOOL_DESCRIPTORS: tuple[ToolDescriptor, ...] = (
    ToolDescriptor("code.list_dir", Effect.READ, reads_untrusted=True),
    ToolDescriptor("code.file_outline", Effect.READ, reads_untrusted=True),
    ToolDescriptor("code.search_symbol", Effect.READ, reads_untrusted=True),
    ToolDescriptor("code.read_function", Effect.READ, reads_untrusted=True),
    ToolDescriptor("code.read_range", Effect.READ, reads_untrusted=True),
    ToolDescriptor("code.get_definition", Effect.READ, reads_untrusted=True),
    ToolDescriptor("code.find_references", Effect.READ, reads_untrusted=True),
    ToolDescriptor("code.callees", Effect.READ, reads_untrusted=True),
    ToolDescriptor("code.search_text", Effect.SANDBOXED_RUN, reads_untrusted=True),
    ToolDescriptor("code.explore", Effect.SANDBOXED_RUN, reads_untrusted=True),
)

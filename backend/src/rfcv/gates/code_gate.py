"""Code gate: cấp công cụ chỉ đọc trên chỉ mục mã cho vùng cách ly (giao diện I5).

Mọi kết quả mang nhãn UNTRUSTED, có tiêu đề `[UNTRUSTED CODE]`, có số dòng, và bị giới hạn kích thước.
Lớp bọc trích "tập dòng đã hiển thị" từ đầu ra để Schema gate kiểm tra (tài liệu khám phá mã, mục 6): chỉ những cặp
(tệp, dòng) thật sự hiện ra kèm số dòng, và chỉ với tệp có trong chỉ mục.
Chỉ mục thật (tree-sitter → SQLite, `rfcv.codeindex`) và bộ chạy lệnh trong container code-index-worker cài đặt các
Protocol bên dưới; InMemoryCodeIndex dùng cho kiểm thử.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfcv.core.ifc import TrustLabel
from rfcv.gates import explore_policy
from rfcv.gates.tool_gateway import DenyCode, ToolDenied, ToolResult, ToolSession, ToolSpec
from rfcv.spi import Effect, ToolDescriptor

MAX_LINES = 200
MAX_BYTES = 16 * 1024
READ_WINDOW = 100
MAX_RESULTS = 50
MAX_CALLEES = 100
MAX_ENTRIES = 200
MAX_BLOCKS = 40
DEF_LINES = 40
COMMAND_TIMEOUT_S = 10.0
# Tiền tố cho thông báo của chính bộ chạy lệnh (lỗi lệnh, quá thời gian), để không nhầm với đầu ra của lệnh.
EXECUTOR_NOTE = "[rfcv] "

# Ngân sách byte cho phần thân của công cụ đọc: chừa chỗ cho tiêu đề và ghi chú.
_BODY_BYTES = MAX_BYTES - 2048

_LOCATED = re.compile(r"^(?P<file>[^:\s]+):(?P<line>\d+)[:-]")
_MATCH = re.compile(r"^(?P<file>[^:\s]+):(?P<line>\d+):")
_CONTEXT = re.compile(r"^(?P<file>[^:\s]+?)-(?P<line>\d+)-")
_CAT_N = re.compile(r"^\s*(?P<line>\d+)\t")

FUNCTION_KINDS = frozenset({"function", "method"})
# Khai báo không phải định nghĩa: get_definition ưu tiên định nghĩa thật.
_DECLARATION_KINDS = frozenset({"prototype"})


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
    def containing_symbol(self, file: str, line: int) -> SymbolInfo | None: ...
    def lines(self, file: str, start: int, end: int) -> Sequence[str]: ...
    def references(self, name: str) -> Sequence[Reference]: ...
    def callees(self, function: str) -> Sequence[tuple[str, int]]: ...
    def has_call_edge(self, caller: str, callee: str) -> bool: ...


# Khả năng tuỳ chọn của chỉ mục (dò bằng getattr, không bắt buộc với plugin):
#   line_count(file) -> int | None                         số dòng mỗi tệp cho list_dir
#   blocks(file, start, end) -> Sequence[tuple[int, int, str]]  khối lệnh cấp một của hàm dài cho read_function
#   compiled_lines(file, flags) -> set[int] | None          dòng được biên dịch theo cờ build (Schema gate, kiểm tra 5)


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
        return sorted((s for s in self.symbols if s.file == file), key=lambda s: s.line_start)

    def lookup(self, name: str) -> Sequence[SymbolInfo]:
        return [s for s in self.symbols if s.name == name]

    def symbol_in_file(self, file: str, name: str) -> SymbolInfo | None:
        return next((s for s in self.symbols if s.file == file and s.name == name), None)

    def containing_symbol(self, file: str, line: int) -> SymbolInfo | None:
        covering = [s for s in self.symbols if s.file == file and s.line_start <= line <= s.line_end]
        return min(covering, key=lambda s: s.line_end - s.line_start, default=None)

    def lines(self, file: str, start: int, end: int) -> Sequence[str]:
        src = self.sources.get(file, [])
        return src[max(0, start - 1) : min(len(src), end)]

    def line_count(self, file: str) -> int | None:
        return len(self.sources[file]) if file in self.sources else None

    def references(self, name: str) -> Sequence[Reference]:
        out: list[Reference] = []
        for r in self.refs:
            text = self.lines(r.file, r.line, r.line)
            if r.container != name and text and name in text[0]:
                out.append(r)
        return out

    def callees(self, function: str) -> Sequence[tuple[str, int]]:
        sym = next((s for s in self.symbols if s.name == function), None)
        return [(callee, sym.line_start if sym else 0) for caller, callee in sorted(self.calls) if caller == function]

    def has_call_edge(self, caller: str, callee: str) -> bool:
        return (caller, callee) in self.calls


def _limit(text: str) -> str:
    if text.count("\n") + 1 > MAX_LINES or len(text.encode("utf-8")) > MAX_BYTES:
        raise ToolDenied(DenyCode.OUTPUT_TOO_LARGE)
    return text


def _numbered(
    index: CodeIndex, file: str, start: int, end: int, budget: int = _BODY_BYTES
) -> tuple[str, frozenset[tuple[str, int]], int]:
    """Đoạn mã có số dòng. Dừng sớm nếu vượt ngân sách byte (dòng rất dài); trả dòng cuối thực sự hiển thị."""
    out: list[str] = []
    used = 0
    last = start - 1
    for i, line in enumerate(index.lines(file, start, end)):
        row = f"{start + i:>6} {line}"
        used += len(row.encode("utf-8")) + 1
        if used > budget and out:
            break
        out.append(row)
        last = start + i
    shown = frozenset((file, n) for n in range(start, last + 1))
    return "\n".join(out), shown, last


def located_lines(output: str, known: Callable[[str], bool] | None = None) -> frozenset[tuple[str, int]]:
    """Trích (tệp, dòng) từ đầu ra dạng `tệp:dòng:` (dòng khớp) và `tệp-dòng-` (dòng ngữ cảnh) của rg/grep.

    `known` lọc theo tệp có trong chỉ mục: một chuỗi trông giống vị trí nhưng không phải tệp thật thì không tính.
    """
    out: set[tuple[str, int]] = set()
    for line in output.splitlines():
        m = _LOCATED.match(line) or _CONTEXT.match(line)
        if m:
            file = m.group("file").removeprefix("./")
            if known is None or known(file):
                out.add((file, int(m.group("line"))))
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


_FILE_DOC = "Đường dẫn tệp tương đối từ gốc kho mã, đúng như các công cụ khác in ra."


class ListDirParams(_P):
    path: str = Field(
        default=".", max_length=500, description="Thư mục tương đối từ gốc kho mã; '.' là gốc.", examples=[".", "src"]
    )
    depth: int = Field(default=1, ge=1, le=2, description="Số cấp thư mục hiển thị (1 hoặc 2).")


class FileParams(_P):
    file: str = Field(min_length=1, max_length=500, description=_FILE_DOC, examples=["src/internal.c"])


class SymbolParams(_P):
    name: str = Field(
        min_length=1,
        max_length=200,
        description="Tên ký hiệu chính xác (phân biệt hoa thường): hàm, macro, hằng, enum, struct, biến, trường.",
        examples=["GetRecordHeader", "MAX_RECORD_SIZE"],
    )
    kind: str | None = Field(
        default=None,
        max_length=40,
        description=(
            "Lọc tuỳ chọn. Với search_symbol/get_definition: loại ký hiệu (function, method, macro, struct, union, enum, "
            "enumerator, typedef, variable, const, type, trait, impl, interface). Với find_references: loại tham chiếu "
            "(call, read, write, fn_pointer)."
        ),
    )


class ReadFunctionParams(_P):
    symbol: str = Field(min_length=1, max_length=200, description="Tên hàm cần đọc.", examples=["GetRecordHeader"])
    file: str | None = Field(
        default=None, max_length=500, description="Chọn định nghĩa khi nhiều tệp có hàm cùng tên. " + _FILE_DOC
    )
    page: int = Field(
        default=1, ge=1, description="Trang 100 dòng; trang 1 của hàm dài kèm chữ ký và danh sách khối lệnh."
    )


class ReadRangeParams(_P):
    file: str = Field(min_length=1, max_length=500, description=_FILE_DOC, examples=["src/conn.c"])
    start: int = Field(ge=1, description="Dòng đầu (tính từ 1).", examples=[4395])
    end: int = Field(ge=1, description="Dòng cuối (bao gồm); tối đa start+99.", examples=[4415])

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end < self.start:
            raise ValueError("end < start")
        return self


class SearchTextParams(_P):
    regex: str = Field(
        min_length=1,
        max_length=300,
        description="Biểu thức chính quy cú pháp ripgrep (Rust regex).",
        examples=["msg_too_long", r"MAX_MSG_SIZE\s*\+"],
    )
    path_glob: str | None = Field(
        default=None, max_length=200, description="Glob lọc tệp kiểu rg -g.", examples=["src/*.c", "*.h"]
    )


class ExploreParams(_P):
    command: str = Field(
        min_length=1,
        max_length=500,
        description="Một lệnh đọc, có thể nối bằng |. Không dùng ; && || > < $ ` hay biến môi trường.",
        examples=[
            "rg -n msg_too_long src/",
            "sg run -p 'send_error($C, msg_too_long)' -l c src",
            "sed -n '910,940p' src/parser.c",
        ],
    )


# Mô tả công cụ cho mô hình theo kiểu MCP (`tools/list`): làm gì, khi nào dùng, trả về gì, giới hạn, ví dụ.
# Agent chỉ thấy các mô tả này và JSON Schema của tham số, nên đây là "hướng dẫn sử dụng" duy nhất của nó.
TOOL_DOCS: dict[str, str] = {
    "code.list_dir": (
        "Xem cây thư mục của kho mã trong phạm vi kiểm chứng (bước định hướng).\n"
        "Khi dùng: lúc mới bắt đầu, để biết tệp nào có thể chứa phần xử lý cần tìm.\n"
        "Trả về: mỗi dòng một mục; thư mục kết thúc bằng '/', tệp kèm số dòng. Tối đa 200 mục.\n"
        'Ví dụ: {"path": "src", "depth": 1}'
    ),
    "code.file_outline": (
        "Liệt kê ký hiệu trong một tệp: hàm, struct, enum, macro, biến toàn cục, kèm dòng bắt đầu và khoảng dòng; "
        "không có thân hàm.\n"
        "Khi dùng: trước khi đọc một tệp lớn, để chọn hàm cần đọc.\n"
        "Trả về: '<dòng> <loại> <chữ ký>  [đầu–cuối]'. Tối đa 200 ký hiệu.\n"
        'Ví dụ: {"file": "src/parser.c"}'
    ),
    "code.search_symbol": (
        "Tìm ký hiệu theo tên chính xác trong chỉ mục cấu trúc (không phải tìm văn bản).\n"
        "Khi dùng: đã biết tên hàm/macro/kiểu và cần biết nó nằm ở đâu; với Rust/Go trả mọi phương thức trùng tên.\n"
        "Trả về: '<tệp>:<dòng>: <loại> <chữ ký>'. Tối đa 50 kết quả.\n"
        'Ví dụ: {"name": "parse_header"} hoặc {"name": "Read", "kind": "method"}'
    ),
    "code.read_function": (
        "Đọc thân một hàm, có số dòng, 100 dòng mỗi trang.\n"
        "Khi dùng: đã biết tên hàm ứng viên. Hàm dài: trang 1 kèm chữ ký và danh sách khối lệnh cấp một để chọn trang.\n"
        "Trả về: tiêu đề '<tệp> <hàm> lines A–B page i/n' rồi các dòng '<số dòng> <mã>'. Nếu trùng tên ở nhiều tệp, "
        "tiêu đề nêu các định nghĩa khác; gọi lại với 'file'.\n"
        'Ví dụ: {"symbol": "parse_header"}, {"symbol": "process_input", "page": 2}'
    ),
    "code.read_range": (
        "Đọc một khoảng dòng bất kỳ của một tệp, có số dòng, tối đa 100 dòng mỗi lần.\n"
        "Khi dùng: đọc mã ngoài hàm (bảng con trỏ hàm, khai báo, khối #ifdef), đọc tiếp quanh một dòng khớp, và "
        "TỰ KIỂM TRA: đọc lại đúng các dòng sẽ dẫn trong LocationClaim.\n"
        "Trả về: '<số dòng> <mã>'. Dòng nào chưa hiện qua công cụ thì không được dẫn.\n"
        'Ví dụ: {"file": "src/conn.c", "start": 4395, "end": 4415}'
    ),
    "code.get_definition": (
        "Tra định nghĩa macro, hằng, enum/enumerator, struct, typedef (và hàm nếu không còn gì khác).\n"
        "Khi dùng: LUÔN tra trước khi kết luận về ngưỡng, hằng số, mã lỗi; khi gặp tên viết hoa trong điều kiện.\n"
        "Trả về: thân định nghĩa có số dòng; nếu trùng tên (ví dụ macro định nghĩa khác nhau theo #ifdef) in tối đa 3 "
        "định nghĩa và liệt kê phần còn lại.\n"
        'Ví dụ: {"name": "MAX_MSG_SIZE"}, {"name": "msg_too_long", "kind": "enumerator"}'
    ),
    "code.find_references": (
        "Tìm mọi chỗ dùng một ký hiệu: nơi gọi hàm (thay cho 'callers'), nơi đọc/ghi biến hay trường struct, nơi gán "
        "hàm vào con trỏ hoặc bảng xử lý.\n"
        "Khi dùng: lần ngược luồng gọi tới hàm ứng viên; theo dấu biến độ dài hay trường trạng thái.\n"
        "Trả về: '<tệp>:<dòng>: [<loại> in <hàm chứa>] <dòng mã>'; loại là call, read, write hoặc fn_pointer. "
        "Tối đa 50 kết quả; lọc bằng kind.\n"
        'Ví dụ: {"name": "parse_header"}, {"name": "cur_len", "kind": "write"}'
    ),
    "code.callees": (
        "Liệt kê các hàm được gọi trong thân một hàm, kèm dòng gọi.\n"
        "Khi dùng: lần xuôi luồng xử lý từ một điểm vào.\n"
        "Trả về: '<dòng> <tên hàm được gọi>'. Tối đa 100 kết quả. Lời gọi qua con trỏ hàm hiện bằng tên trường.\n"
        'Ví dụ: {"name": "process_input"}'
    ),
    "code.search_text": (
        "Tìm văn bản theo regex trong toàn phạm vi (ripgrep), ±2 dòng ngữ cảnh.\n"
        "Khi dùng: tìm điểm vào theo thuật ngữ của yêu cầu: tên mã lỗi, tên trường, hằng số, thông điệp lỗi.\n"
        "Trả về: dòng khớp '<tệp>:<dòng>:<mã>', ngữ cảnh '<tệp>-<dòng>-<mã>', cuối cùng là danh sách 'hàm chứa'. "
        "Tối đa 50 kết quả.\n"
        'Ví dụ: {"regex": "msg_too_long"}, {"regex": "MAX_MSG_SIZE", "path_glob": "src/*.c"}'
    ),
    "code.explore": (
        "Tự khám phá như trên terminal, chỉ với lệnh đọc trong danh sách cho phép, chạy trong sandbox chỉ đọc, "
        "không mạng. Dùng khi các công cụ trên không làm gọn được: tìm theo mẫu cấu trúc (ast-grep), thống kê, ghép "
        "nhiều bước tìm, theo dấu bảng con trỏ hàm.\n"
        "Lệnh được phép: rg/grep (-n -l -c -i -w -F -E -r -e -g -t -A -B -C -m), sg run (-p -l --lang --json), "
        "find (-name -path -type -maxdepth), ls, tree, sed -n 'A,Bp' <tệp>, head/tail -n N, cat -n, wc, sort, uniq, cut; "
        "nối bằng |. Bị chặn: ; && || > < $ ` &, rg --pre, find -exec/-delete, sed -i, sg -r/-U, mọi lệnh khác.\n"
        "Trả về: đầu ra của lệnh. Lệnh đọc một tệp (sed -n, head, tail, cat -n) được đánh số dòng; dòng dạng "
        "'<tệp>:<dòng>:' của rg -n cũng tính là đã đọc. Tối đa 10 giây, 200 dòng hoặc 16 KB: quá thì bị từ chối "
        "(OUTPUT_TOO_LARGE), hãy thu hẹp lệnh.\n"
        'Ví dụ: {"command": "rg -n msg_too_long src/"}, '
        '{"command": "sg run -p \'if ($S > MAX_MSG_SIZE + $$$) { $$$ }\' -l c src"}, '
        '{"command": "rg -l send_error src | sort"}'
    ),
}


def _strip_dot(text: str) -> str:
    return "\n".join(line.removeprefix("./") for line in text.splitlines())


def build_code_tools(index: CodeIndex, executor: SandboxExecutor, scope: explore_policy.CodeScope) -> list[ToolSpec]:
    known_files = frozenset(index.files())

    def known(file: str) -> bool:
        return file in known_files

    def count_lines(file: str) -> int | None:
        counter: Any = getattr(index, "line_count", None)
        return counter(file) if counter is not None else None

    def container_of(file: str, line: int) -> SymbolInfo | None:
        return index.containing_symbol(file, line)

    async def list_dir(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, ListDirParams)
        prefix = "" if p.path.strip("./") == "" else p.path.strip("/").removeprefix("./") + "/"
        entries: dict[str, str] = {}
        for f in index.files():
            if not f.startswith(prefix):
                continue
            parts = f[len(prefix) :].split("/")
            for d in range(1, min(p.depth, len(parts)) + 1):
                key = "/".join(parts[:d])
                if d == len(parts):
                    n = count_lines(f)
                    entries.setdefault(key, f"{key} ({n} dòng)" if n is not None else key)
                else:
                    entries.setdefault(key + "/", key + "/")
        rows = [entries[k] for k in sorted(entries)]
        if not rows:
            body = "(không có tệp nào trong phạm vi ở đường dẫn này)"
        elif len(rows) > MAX_ENTRIES:
            body = "\n".join(rows[: MAX_ENTRIES - 1]) + f"\n(còn {len(rows) - MAX_ENTRIES + 1} mục; chọn thư mục con)"
        else:
            body = "\n".join(rows)
        return _untrusted(f"tool=list_dir {p.path} depth={p.depth}", body)

    async def file_outline(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, FileParams)
        if p.file not in known_files:
            return _untrusted(f"tool=file_outline {p.file}", "(tệp không có trong phạm vi chỉ mục)")
        syms = list(index.outline(p.file))
        shown_syms = syms[: MAX_LINES - 2]
        body = "\n".join(
            f"{x.line_start:>6} {x.kind} {x.signature or x.name}  [{x.line_start}–{x.line_end}]" for x in shown_syms
        )
        if len(syms) > len(shown_syms):
            body += f"\n(còn {len(syms) - len(shown_syms)} ký hiệu; dùng search_symbol hoặc read_range)"
        return _untrusted(
            f"tool=file_outline {p.file}",
            body or "(không có ký hiệu)",
            frozenset((p.file, x.line_start) for x in shown_syms),
        )

    async def search_symbol(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, SymbolParams)
        hits = [x for x in index.lookup(p.name) if p.kind is None or x.kind == p.kind][:MAX_RESULTS]
        body = "\n".join(f"{x.file}:{x.line_start}: {x.kind} {x.signature or x.name}" for x in hits)
        return _untrusted(f"tool=search_symbol {p.name}", body or "(không có ký hiệu khớp)", located_lines(body, known))

    async def read_function(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, ReadFunctionParams)
        cands = sorted(
            (x for x in index.lookup(p.symbol) if p.file is None or x.file == p.file),
            key=lambda x: (x.kind not in FUNCTION_KINDS, x.kind in _DECLARATION_KINDS, x.file, x.line_start),
        )
        if not cands:
            return _untrusted(f"tool=read_function {p.symbol}", "(không tìm thấy ký hiệu)")
        sym = cands[0]
        pages = max(1, -(-(sym.line_end - sym.line_start + 1) // READ_WINDOW))
        if p.page > pages:
            return _untrusted(f"tool=read_function {sym.file} {sym.name}", f"(hàm chỉ có {pages} trang)")
        start = sym.line_start + (p.page - 1) * READ_WINDOW
        end = min(sym.line_end, start + READ_WINDOW - 1)
        notes: list[str] = []
        if len(cands) > 1:
            others = ", ".join(f"{c.file}:{c.line_start} {c.kind}" for c in cands[1:6])
            notes.append(f"cùng tên còn: {others} (dùng tham số file để chọn)")
        if pages > 1 and p.page == 1:
            notes.append(f"chữ ký: {sym.signature or sym.name}")
            blocks_of: Any = getattr(index, "blocks", None)
            blocks: Sequence[tuple[int, int, str]] = (
                blocks_of(sym.file, sym.line_start, sym.line_end) if blocks_of is not None else ()
            )
            if blocks:
                notes.append("khối lệnh cấp một:")
                notes += [f"  {a}–{b} {head}" for a, b, head in blocks[:MAX_BLOCKS]]
        budget = _BODY_BYTES - sum(len(n.encode("utf-8")) + 1 for n in notes)
        body, shown, last = _numbered(index, sym.file, start, end, budget)
        header = f"tool=read_function {sym.file} {sym.name} lines {start}–{last} page {p.page}/{pages}"
        if last < end:
            header += f" (cắt ở {last} vì dòng dài; đọc tiếp bằng read_range)"
        return _untrusted(header, "\n".join([*notes, body]), shown)

    async def read_range(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, ReadRangeParams)
        if p.file not in known_files:
            return _untrusted(f"tool=read_range {p.file}", "(tệp không có trong phạm vi chỉ mục)")
        end = min(p.end, p.start + READ_WINDOW - 1)
        body, shown, last = _numbered(index, p.file, p.start, end)
        if last < p.start:
            return _untrusted(f"tool=read_range {p.file} lines {p.start}–{end}", "(ngoài cuối tệp)")
        note = "" if last >= p.end else f" (tối đa {READ_WINDOW} dòng mỗi lần; đọc tiếp từ {last + 1})"
        return _untrusted(f"tool=read_range {p.file} lines {p.start}–{last}{note}", body, shown)

    async def get_definition(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, SymbolParams)
        defs = sorted(
            (x for x in index.lookup(p.name) if p.kind is None or x.kind == p.kind),
            key=lambda x: (x.kind in _DECLARATION_KINDS, x.kind in FUNCTION_KINDS, x.file, x.line_start),
        )
        if not defs:
            return _untrusted(f"tool=get_definition {p.name}", "(không có định nghĩa)")
        parts: list[str] = []
        shown: set[tuple[str, int]] = set()
        budget = _BODY_BYTES
        # Trùng tên (ví dụ macro định nghĩa khác nhau theo #ifdef): in tối đa 3 định nghĩa, còn lại liệt kê.
        for sym in defs[:3]:
            per = DEF_LINES if len(defs) == 1 else 15
            body, sh, last = _numbered(
                index, sym.file, sym.line_start, min(sym.line_end, sym.line_start + per - 1), budget // 3
            )
            more = "" if last >= sym.line_end else f" (còn tới dòng {sym.line_end}; đọc bằng read_range)"
            parts.append(f"{sym.file} {sym.kind} {sym.name} [{sym.line_start}–{sym.line_end}]{more}\n{body}")
            shown |= sh
        if len(defs) > 3:
            parts.append("định nghĩa khác: " + ", ".join(f"{x.file}:{x.line_start} {x.kind}" for x in defs[3:20]))
        return _untrusted(f"tool=get_definition {p.name} ({len(defs)} định nghĩa)", "\n".join(parts), frozenset(shown))

    async def find_references(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, SymbolParams)
        refs = [r for r in index.references(p.name) if p.kind is None or r.kind == p.kind]
        total = len(refs)
        refs = refs[:MAX_RESULTS]
        rows: list[str] = []
        for r in refs:
            text = index.lines(r.file, r.line, r.line)
            code = text[0].strip() if text else ""
            rows.append(f"{r.file}:{r.line}: [{r.kind} in {r.container or '<tệp>'}] {code}")
        body = "\n".join(rows) or "(không có tham chiếu)"
        if total > len(refs):
            body += f"\n(còn {total - len(refs)} tham chiếu; lọc bằng kind=call|read|write|fn_pointer)"
        edges = frozenset((r.container, p.name) for r in refs if r.kind in ("call", "fn_pointer") and r.container)
        return _untrusted(f"tool=find_references {p.name}", body, located_lines("\n".join(rows), known), edges)

    async def callees(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, SymbolParams)
        found = list(index.callees(p.name))[:MAX_CALLEES]
        body = (
            "\n".join(f"{line:>6} {name}" for name, line in found) or "(không gọi hàm nào, hoặc không có trong chỉ mục)"
        )
        return _untrusted(f"tool=callees {p.name}", body, edges=frozenset((p.name, n) for n, _ in found))

    async def search_text(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, SearchTextParams)
        argv = ["rg", "-n", "--no-heading", "--with-filename", "-C", "2", "-m", str(MAX_RESULTS), "-e", p.regex]
        if p.path_glob:
            argv += ["-g", p.path_glob]
        out = _strip_dot(await executor.run([[*argv, "."]], timeout_s=COMMAND_TIMEOUT_S))
        lines = out.splitlines()
        matches = [(m.group("file"), int(m.group("line"))) for line in lines if (m := _MATCH.match(line))]
        # Hàm chứa từng dòng khớp, gộp theo hàm để tiết kiệm dòng.
        by_fn: dict[tuple[str, str, int, int], list[int]] = {}
        for f, n in matches[:MAX_RESULTS]:
            sym = container_of(f, n) if known(f) else None
            if sym is not None:
                by_fn.setdefault((f, sym.name, sym.line_start, sym.line_end), []).append(n)
        trailer = [
            f"hàm chứa: {f} {name} [{a}–{b}] ← dòng {', '.join(map(str, ns[:10]))}"
            for (f, name, a, b), ns in list(by_fn.items())[:30]
        ]
        budget = MAX_LINES - 3 - len(trailer)
        kept: list[str] = []
        n_match = 0
        cut = False
        for line in lines:
            if _MATCH.match(line):
                n_match += 1
                if n_match > MAX_RESULTS:
                    cut = True
                    break
            if len(kept) >= budget:
                cut = True
                break
            kept.append(line)
        body = "\n".join(kept) or "(không có kết quả)"
        if cut:
            body += f"\n(đã cắt ở {min(n_match, MAX_RESULTS)} kết quả; thu hẹp regex hoặc path_glob)"
        if trailer:
            body += "\n-- \n" + "\n".join(trailer)
        return _untrusted(f"tool=search_text {p.regex!r}", body, located_lines("\n".join(kept), known))

    def annotate(segments: list[list[str]], out: str) -> tuple[str, frozenset[tuple[str, int]]]:
        """Lệnh đọc một tệp, không ống dẫn (sed -n 'A,Bp' f, head -n N f, tail -n N f, cat -n f): harness biết chính
        xác dòng nào được in, nên đánh số và tính vào tập dòng đã hiển thị. Lệnh khác chỉ tính dòng dạng tệp:dòng."""
        located = located_lines(out, known)
        if len(segments) != 1 or out.startswith(EXECUTOR_NOTE):
            return out, located
        argv = segments[0]
        name, args = argv[0], argv[1:]
        files = [a for a in args if known(a.removeprefix("./"))]
        if len(files) != 1:
            return out, located
        file = files[0].removeprefix("./")
        rows = out.split("\n")
        if rows and rows[-1] == "":
            rows.pop()
        first: int | None = None
        if name == "sed":
            script = next((a for a in args if re.fullmatch(r"\d+,\d+p", a)), None)
            first = int(script.split(",")[0]) if script else None
        elif name == "head":
            first = 1
        elif name == "tail":
            total = count_lines(file)
            first = None if total is None else max(1, total - len(rows) + 1)
        elif name == "cat" and "-n" in args:
            shown = {(file, int(m.group("line"))) for r in rows if (m := _CAT_N.match(r))}
            return out, located | frozenset(shown)
        if first is None or not rows:
            return out, located
        numbered = "\n".join(f"{first + i:>6} {r}" for i, r in enumerate(rows))
        return numbered, located | frozenset((file, first + i) for i in range(len(rows)))

    async def explore(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, ExploreParams)
        try:
            segments = explore_policy.validate(p.command, scope)
        except explore_policy.CommandRejected as exc:
            raise ToolDenied(DenyCode.COMMAND_REJECTED, exc.code) from exc
        out = _strip_dot(await executor.run(segments, timeout_s=COMMAND_TIMEOUT_S))
        text, shown = annotate(segments, out)
        return _untrusted(f"tool=explore cmd={p.command!r}", text, shown)

    handlers: list[tuple[str, type[BaseModel], Any]] = [
        ("code.list_dir", ListDirParams, list_dir),
        ("code.file_outline", FileParams, file_outline),
        ("code.search_symbol", SymbolParams, search_symbol),
        ("code.read_function", ReadFunctionParams, read_function),
        ("code.read_range", ReadRangeParams, read_range),
        ("code.get_definition", SymbolParams, get_definition),
        ("code.find_references", SymbolParams, find_references),
        ("code.callees", SymbolParams, callees),
        ("code.search_text", SearchTextParams, search_text),
        ("code.explore", ExploreParams, explore),
    ]
    return [
        ToolSpec(name, TOOL_DOCS[name], params, handler, title=_TITLES[name], read_only=True)
        for name, params, handler in handlers
    ]


_TITLES = {
    "code.list_dir": "Cây thư mục",
    "code.file_outline": "Dàn ý tệp",
    "code.search_symbol": "Tìm ký hiệu",
    "code.read_function": "Đọc hàm",
    "code.read_range": "Đọc khoảng dòng",
    "code.get_definition": "Tra định nghĩa",
    "code.find_references": "Tìm tham chiếu",
    "code.callees": "Hàm được gọi",
    "code.search_text": "Tìm văn bản",
    "code.explore": "Tự khám phá bằng lệnh đọc",
}


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

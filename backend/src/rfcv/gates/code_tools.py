"""Bộ công cụ đọc mã kiểu Claude Code: `grep`, `glob`, `read` và một công cụ tất định `eval`.

Thay cho 10 công cụ hẹp của `code_gate.build_code_tools` (đo trên 14 lần chạy thật: `read_range` 184 lần vì các công cụ khác
không đủ, `explore` bị cổng từ chối 26%, `callees` gần như rỗng, kết quả bị chặn cứng 200 dòng và bị TỪ CHỐI khi vượt). Nguyên tắc:
- Ít công cụ tổng quát, tham số có cấu trúc (không phải dòng lệnh tự do): cổng dựng argv của ripgrep, nên không còn bị từ chối
  vì "lệnh lạ" và không thể chèn cờ nguy hiểm.
- Đầu ra quá lớn thì CẮT kèm gợi ý đọc tiếp, không từ chối.
- Cửa sổ đọc lớn (mặc định 400 dòng, tối đa 1000) để đọc một hàm hay một khối `#if` trong một lượt.
- Vẫn giữ bất biến an ninh: chỉ thấy bản sao phạm vi (worker chỉ gắn phần đó), mọi đầu ra UNTRUSTED, chỉ dòng được trả về mới
  vào tập dòng đã hiển thị cho Schema gate.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rfcv.core.ifc import TrustLabel
from rfcv.gates import cexpr
from rfcv.gates.code_gate import (
    COMMAND_TIMEOUT_S,
    EXECUTOR_NOTE,
    FUNCTION_KINDS,
    CodeIndex,
    SandboxExecutor,
    SymbolInfo,
    _numbered,  # pyright: ignore[reportPrivateUsage]
    _strip_dot,  # pyright: ignore[reportPrivateUsage]
    located_lines,
)
from rfcv.gates.tool_gateway import ToolResult, ToolSession, ToolSpec
from rfcv.spi import Effect, ToolDescriptor

READ_DEFAULT = 400
READ_MAX = 1000
READ_BYTES = 48 * 1024
OUT_BYTES = 24 * 1024
GREP_DEFAULT = 100
GLOB_DEFAULT = 200
MAX_TRAILER = 40
_MATCH = re.compile(r"^(?P<file>[^:\s]+):(?P<line>\d+):")
_FLAG_D = re.compile(r"^-D(?P<n>\w+)(?:=(?P<v>.*))?$")


class _P(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _safe_rel(value: str | None) -> str | None:
    """Đường dẫn/glob tương đối trong phạm vi: không tuyệt đối, không `..`, không bắt đầu bằng '-', không NUL."""
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    if v.startswith(("/", "-", "~")) or "\x00" in v or any(part == ".." for part in re.split(r"[\\/]", v)):
        raise ValueError("đường dẫn phải tương đối, trong phạm vi, không chứa '..'")
    return v.removeprefix("./")


class GrepParams(_P):
    pattern: str = Field(
        min_length=1,
        max_length=300,
        description="Biểu thức chính quy cú pháp ripgrep (Rust regex).",
        examples=["record_overflow", r"MAX_MSG_EXTRA\s*\+", r"SendAlert\(.*record_overflow"],
    )
    path: str | None = Field(
        default=None, max_length=300, description="Tệp hoặc thư mục để tìm. Mặc định: toàn phạm vi."
    )
    glob: str | None = Field(
        default=None, max_length=200, description="Lọc tệp kiểu rg -g.", examples=["*.c", "src/*.h"]
    )
    type: str | None = Field(
        default=None, pattern=r"^[a-z]{1,12}$", description="Loại tệp của ripgrep (c, h là 'c'; cpp, py, rust...)."
    )
    output_mode: Literal["content", "files_with_matches", "count"] = Field(
        default="content",
        description="content: dòng khớp (mặc định); files_with_matches: chỉ tên tệp; count: số dòng khớp mỗi tệp.",
    )
    before: int = Field(default=0, ge=0, le=20, description="Số dòng ngữ cảnh TRƯỚC dòng khớp (rg -B).")
    after: int = Field(default=0, ge=0, le=20, description="Số dòng ngữ cảnh SAU dòng khớp (rg -A).")
    context: int = Field(default=0, ge=0, le=20, description="Số dòng ngữ cảnh hai phía (rg -C); thắng before/after.")
    ignore_case: bool = Field(default=False, description="Không phân biệt hoa thường (rg -i).")
    multiline: bool = Field(default=False, description="Cho mẫu trải nhiều dòng, '.' khớp cả xuống dòng (rg -U).")
    head_limit: int = Field(default=GREP_DEFAULT, ge=1, le=500, description="Số kết quả tối đa trong một lần trả về.")
    offset: int = Field(default=0, ge=0, description="Bỏ qua N nhóm kết quả đầu, để xem trang tiếp theo.")

    @field_validator("path", "glob", mode="before")
    @classmethod
    def _rel(cls, v: str | None) -> str | None:
        return _safe_rel(v)


class GlobParams(_P):
    pattern: str = Field(
        min_length=1, max_length=200, description="Mẫu glob, ví dụ '**/*.c' hoặc 'src/tls*.c'.", examples=["src/*.c"]
    )
    path: str | None = Field(default=None, max_length=300, description="Thư mục gốc để tìm. Mặc định: toàn phạm vi.")
    head_limit: int = Field(default=GLOB_DEFAULT, ge=1, le=1000, description="Số tệp tối đa trả về.")

    @field_validator("path", "pattern", mode="before")
    @classmethod
    def _rel(cls, v: str | None) -> str | None:
        return _safe_rel(v)


class ReadParams(_P):
    file: str | None = Field(
        default=None, max_length=300, description="Tệp cần đọc, đường dẫn tương đối từ gốc kho mã."
    )
    symbol: str | None = Field(
        default=None,
        max_length=200,
        description="Tên hàm cần đọc nguyên thân (thay cho file+offset). Nếu có `file` thì chỉ tìm trong tệp đó.",
    )
    offset: int = Field(
        default=1, ge=1, description="Dòng bắt đầu (tính từ 1); với `symbol` là dòng thứ mấy trong thân hàm."
    )
    limit: int = Field(default=READ_DEFAULT, ge=1, le=READ_MAX, description="Số dòng tối đa.")

    @field_validator("file", mode="before")
    @classmethod
    def _rel(cls, v: str | None) -> str | None:
        return _safe_rel(v)

    @model_validator(mode="after")
    def _needs_target(self) -> Self:
        if self.file is None and self.symbol is None:
            raise ValueError("cần `file` hoặc `symbol`")
        return self


class EvalParams(_P):
    expr: str = Field(
        min_length=1,
        max_length=200,
        description=(
            "Biểu thức hằng số nguyên của C gồm số, tên macro/enum, defined(TÊN) và + - * / % << >> & | ^ ~ ( )."
        ),
        examples=["MAX_RECORD_SIZE + MAX_MSG_EXTRA", "(1 << 14) + 256", "defined(HAVE_MAX_FRAGMENT)"],
    )


TOOL_DOCS: dict[str, str] = {
    "code.grep": (
        "Tìm văn bản bằng ripgrep trong phạm vi kiểm chứng, giống Grep của Claude Code, và chú thêm HÀM CHỨA mỗi dòng khớp.\n"
        "Khi dùng: tìm điểm vào theo thuật ngữ (mã lỗi, tên trường, hằng số, thông điệp lỗi), tìm mọi chỗ gọi/dùng một tên, "
        "tìm định nghĩa. Gọi NHIỀU lần song song trong một lượt khi cần nhiều mẫu.\n"
        "Trả về: content: '<tệp>:<dòng>:<mã>' (khớp), '<tệp>-<dòng>-<mã>' (ngữ cảnh), cuối cùng là danh sách 'hàm chứa'; "
        "files_with_matches: tên tệp; count: số khớp mỗi tệp. Quá nhiều thì cắt và nêu offset để xem tiếp.\n"
        'Ví dụ: {"pattern": "record_overflow", "type": "c", "context": 3}, '
        '{"pattern": "GetRecordHeader\\\\(", "output_mode": "files_with_matches"}'
    ),
    "code.glob": (
        "Liệt kê tệp theo mẫu glob trong phạm vi, giống Glob của Claude Code.\n"
        "Khi dùng: biết đúng tên/đường dẫn tệp trước khi đọc, thay vì đoán đường dẫn.\n"
        "Trả về: mỗi dòng một đường dẫn, sắp theo tên.\n"
        'Ví dụ: {"pattern": "src/tls*.c"}, {"pattern": "**/internal.h"}'
    ),
    "code.read": (
        "Đọc tệp có số dòng, giống Read của Claude Code, mặc định 400 dòng, tối đa 1000 dòng một lần; hoặc đọc nguyên một "
        "hàm theo tên.\n"
        "Khi dùng: đọc quanh dòng khớp của grep, đọc nguyên một hàm hoặc một khối #if. Dòng nào chưa hiện qua công cụ thì không "
        "được dẫn trong LocationClaim; hãy đọc lại đúng các dòng sẽ dẫn.\n"
        "Trả về: '<số dòng> <mã>'. Cắt thì nêu số dòng để đọc tiếp.\n"
        'Ví dụ: {"file": "src/internal.c", "offset": 12400, "limit": 200}, {"symbol": "GetRecordHeader"}'
    ),
    "code.eval": (
        "Tính giá trị một biểu thức hằng số nguyên của C theo cờ build của adapter, và cho biết mỗi tên lấy từ định nghĩa nào "
        "(dòng nào, có được biên dịch theo cờ build không).\n"
        "Khi dùng: LUÔN dùng để kết luận về ngưỡng, kích thước, hằng số thay vì tự cộng; macro định nghĩa khác nhau theo #ifdef.\n"
        "Trả về: giá trị, vết thay thế, tên chưa phân giải (không đoán), cảnh báo nếu nhiều định nghĩa cùng được biên dịch.\n"
        'Ví dụ: {"expr": "MAX_RECORD_SIZE + MAX_MSG_EXTRA"}'
    ),
}

_TITLES = {
    "code.grep": "Tìm văn bản (ripgrep)",
    "code.glob": "Liệt kê tệp theo mẫu",
    "code.read": "Đọc tệp hoặc hàm",
    "code.eval": "Tính hằng số C",
}

CC_TOOL_DESCRIPTORS: tuple[ToolDescriptor, ...] = (
    ToolDescriptor("code.grep", Effect.SANDBOXED_RUN, reads_untrusted=True),
    ToolDescriptor("code.glob", Effect.SANDBOXED_RUN, reads_untrusted=True),
    ToolDescriptor("code.read", Effect.READ, reads_untrusted=True),
    ToolDescriptor("code.eval", Effect.READ, reads_untrusted=True),
)


def _result(
    header: str, body: str, shown: frozenset[tuple[str, int]] = frozenset(), cap: int = OUT_BYTES
) -> ToolResult:
    """Kết quả không bao giờ bị từ chối vì kích thước: quá cỡ thì cắt ở ranh giới dòng và nói rõ."""
    text = f"[UNTRUSTED CODE] {header}\n{body}"
    raw = text.encode("utf-8")
    if len(raw) > cap:
        cut = raw[:cap].decode("utf-8", errors="ignore")
        cut = cut[: cut.rfind("\n")] if "\n" in cut else cut
        text = cut + "\n(đã cắt vì quá dài; thu hẹp mẫu hoặc đọc tiếp bằng offset)"
    return ToolResult(text, TrustLabel.UNTRUSTED, shown)


def build_cc_tools(
    index: CodeIndex, executor: SandboxExecutor, build_flags: Sequence[str] = (), closed_world: bool = False
) -> list[ToolSpec]:
    known_files = frozenset(index.files())
    defines = {m.group("n"): (m.group("v") or "1") for f in build_flags if (m := _FLAG_D.match(f))}

    def known(file: str) -> bool:
        return file in known_files

    def line_count(file: str) -> int | None:
        counter: Any = getattr(index, "line_count", None)
        return counter(file) if counter is not None else None

    def container_of(file: str, line: int) -> SymbolInfo | None:
        return index.containing_symbol(file, line) if known(file) else None

    def near_files(file: str) -> list[str]:
        base = file.rsplit("/", 1)[-1]
        return sorted(f for f in known_files if f.rsplit("/", 1)[-1] == base)[:5]

    # ---- grep -----------------------------------------------------------------------------------------------------

    async def grep(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, GrepParams)
        argv = ["rg", "--no-heading", "--with-filename"]
        if p.output_mode == "files_with_matches":
            argv.append("-l")
        elif p.output_mode == "count":
            argv.append("-c")
        else:
            argv.append("-n")
            ctx = p.context or 0
            if ctx:
                argv += ["-C", str(ctx)]
            else:
                if p.before:
                    argv += ["-B", str(p.before)]
                if p.after:
                    argv += ["-A", str(p.after)]
        if p.ignore_case:
            argv.append("-i")
        if p.multiline:
            argv += ["-U", "--multiline-dotall"]
        if p.glob:
            argv += ["-g", p.glob]
        if p.type:
            argv += ["-t", p.type]
        argv += ["-e", p.pattern, "--", p.path or "."]
        out = _strip_dot(await executor.run([argv], timeout_s=COMMAND_TIMEOUT_S))
        header = (
            f"tool=grep {p.pattern!r}" + (f" path={p.path}" if p.path else "") + (f" glob={p.glob}" if p.glob else "")
        )
        if out.startswith(EXECUTOR_NOTE):
            return _result(header, out)
        lines = out.splitlines()
        if not lines:
            return _result(header, "(không có kết quả)")
        if p.output_mode != "content":
            page = lines[p.offset : p.offset + p.head_limit]
            more = len(lines) - p.offset - len(page)
            note = f"\n(còn {more} dòng; dùng offset={p.offset + len(page)})" if more > 0 else ""
            return _result(header, "\n".join(page) + note)

        groups: list[list[str]] = [[]]
        for line in lines:
            if line == "--":
                groups.append([])
            else:
                groups[-1].append(line)
        groups = [g for g in groups if g]
        picked: list[list[str]] = []
        n_match = 0
        for g in groups[p.offset :]:
            picked.append(g)
            n_match += sum(1 for line in g if _MATCH.match(line))
            if n_match >= p.head_limit:
                break
        remaining = len(groups) - p.offset - len(picked)
        body_lines: list[str] = []
        for i, g in enumerate(picked):
            if i:
                body_lines.append("--")
            body_lines += g
        by_fn: dict[tuple[str, str, int, int], list[int]] = {}
        for line in body_lines:
            m = _MATCH.match(line)
            if m and (sym := container_of(m.group("file"), int(m.group("line")))) is not None:
                by_fn.setdefault((m.group("file"), sym.name, sym.line_start, sym.line_end), []).append(
                    int(m.group("line"))
                )
        trailer = [
            f"hàm chứa: {f} {name} [{a}–{b}] ← dòng {', '.join(map(str, ns[:10]))}"
            for (f, name, a, b), ns in list(by_fn.items())[:MAX_TRAILER]
        ]
        body = "\n".join(body_lines)
        if remaining > 0:
            body += f"\n(còn {remaining} nhóm kết quả; dùng offset={p.offset + len(picked)} hoặc thu hẹp mẫu)"
        if trailer:
            body += "\n-- \n" + "\n".join(trailer)
        return _result(header, body, located_lines("\n".join(body_lines), known))

    # ---- glob -----------------------------------------------------------------------------------------------------

    async def glob(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, GlobParams)
        argv = ["rg", "--files", "-g", p.pattern, "--", p.path or "."]
        out = _strip_dot(await executor.run([argv], timeout_s=COMMAND_TIMEOUT_S))
        header = f"tool=glob {p.pattern}" + (f" path={p.path}" if p.path else "")
        if out.startswith(EXECUTOR_NOTE):
            return _result(header, out)
        files = sorted(line for line in out.splitlines() if line)
        if not files:
            return _result(header, "(không có tệp khớp)")
        page = files[: p.head_limit]
        note = f"\n(còn {len(files) - len(page)} tệp; thu hẹp mẫu)" if len(files) > len(page) else ""
        return _result(header, "\n".join(page) + note)

    # ---- read -----------------------------------------------------------------------------------------------------

    async def locate_by_grep(name: str, file: str | None) -> tuple[str, int, int] | None:
        """Chỉ mục không có hàm này (đo: ~5% hàm C bị tree-sitter bỏ sót): tìm định nghĩa bằng ripgrep rồi dò tới `}` cột 0."""
        pattern = rf"^[A-Za-z_][^;{{}}=]*\b{re.escape(name)}\s*\("
        argv = [
            "rg",
            "--no-heading",
            "--with-filename",
            "-n",
            "-e",
            pattern,
            "-g",
            "*.c",
            "-g",
            "*.h",
            "--",
            file or ".",
        ]
        out = _strip_dot(await executor.run([argv], timeout_s=COMMAND_TIMEOUT_S))
        for line in out.splitlines():
            m = _MATCH.match(line)
            if m is None or not known(m.group("file")):
                continue
            f, start = m.group("file"), int(m.group("line"))
            rows = index.lines(f, start, start + 4000)
            for i, row in enumerate(rows):
                if row.rstrip() == "}":
                    return f, start, start + i
            return f, start, start + min(len(rows), READ_DEFAULT) - 1
        return None

    async def read(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, ReadParams)
        note = ""
        if p.symbol is not None:
            cands = sorted(
                (x for x in index.lookup(p.symbol) if p.file is None or x.file == p.file),
                key=lambda x: (x.kind not in FUNCTION_KINDS, x.kind == "prototype", x.file, x.line_start),
            )
            if cands:
                sym = cands[0]
                file, a, b = sym.file, sym.line_start, sym.line_end
                if len(cands) > 1:
                    note = "cùng tên còn: " + ", ".join(f"{c.file}:{c.line_start} {c.kind}" for c in cands[1:6]) + "\n"
            else:
                found = await locate_by_grep(p.symbol, p.file)
                if found is None:
                    return _result(f"tool=read symbol={p.symbol}", "(không tìm thấy hàm; dùng grep để tìm định nghĩa)")
                file, a, b = found
                note = "(chỉ mục không có ký hiệu này; định nghĩa tìm bằng ripgrep)\n"
            start = a + p.offset - 1
            end = min(b, start + p.limit - 1)
            limit_end, base = b, a
        else:
            assert p.file is not None
            file = p.file
            if not known(file):
                hint = near_files(file)
                tip = f" Tệp cùng tên: {', '.join(hint)}." if hint else " Dùng glob để tìm đúng đường dẫn."
                return _result(f"tool=read {file}", f"(tệp không có trong phạm vi chỉ mục.{tip})")
            start = p.offset
            end = start + p.limit - 1
            limit_end, base = line_count(file) or end, 1
        body, shown, last = _numbered(index, file, start, end, READ_BYTES)
        if last < start:
            total = line_count(file)
            return _result(f"tool=read {file}", f"(ngoài cuối tệp{f'; tệp có {total} dòng' if total else ''})")
        compiled_of: Any = getattr(index, "compiled_lines", None)
        disabled_seen = 0
        if compiled_of is not None:
            compiled: set[int] | None = compiled_of(file, tuple(build_flags), closed_world=closed_world)
            if compiled is not None:
                annotated: list[str] = []
                for idx_offset, raw_line in enumerate(body.splitlines()):
                    lineno = start + idx_offset
                    if lineno not in compiled:
                        disabled_seen += 1
                        prefix, sep, rest = raw_line.partition(" ")
                        annotated.append(f"{prefix} [DISABLED]{sep}{rest}" if sep else f"{raw_line} [DISABLED]")
                    else:
                        annotated.append(raw_line)
                body = "\n".join(annotated)
        total = line_count(file)
        disabled_note = f" ({disabled_seen} dòng [DISABLED] bị tắt bởi cờ build)" if disabled_seen else ""
        head = f"tool=read {file} lines {start}–{last}" + (f" of {total}" if total else "") + disabled_note
        more = ""
        nxt = last + 1 - base + 1
        if last < min(end, limit_end):
            more = f"\n(cắt ở dòng {last} vì dòng dài hoặc quá {READ_BYTES // 1024} KB; đọc tiếp offset={nxt})"
        elif last < limit_end:
            more = f"\n(còn tiếp tới dòng {limit_end}; đọc tiếp offset={nxt})"
        return _result(head, note + body + more, shown, cap=READ_BYTES + 4096)

    # ---- eval -----------------------------------------------------------------------------------------------------

    async def eval_expr(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, EvalParams)
        used: set[tuple[str, int]] = set()
        warnings: list[str] = []
        compiled_of: Any = getattr(index, "compiled_lines", None)

        def lookup(name: str) -> tuple[str, str] | None:
            if name.startswith("defined:"):
                target = name.removeprefix("defined:")
                if target in defines:
                    return "1", "cờ build -D"
                live = [x for x in index.lookup(target) if x.kind in ("macro", "enumerator")]
                if compiled_of is not None:
                    flags = tuple(build_flags)
                    live = [
                        x
                        for x in live
                        if (c := compiled_of(x.file, flags, closed_world=closed_world)) is None or x.line_start in c
                    ]
                if live:
                    return "1", f"#define ở {live[0].file}:{live[0].line_start}"
                return (
                    "0",
                    "không có -D và không có #define được biên dịch trong kho (cờ sinh lúc configure không nằm trong kho)",
                )
            if name in defines:
                return defines[name], "cờ build -D"
            cands = [x for x in index.lookup(name) if x.kind in ("macro", "enumerator", "const", "variable")]
            if not cands:
                return None
            live = cands
            if compiled_of is not None:
                flags = tuple(build_flags)
                live = [
                    x
                    for x in cands
                    if (c := compiled_of(x.file, flags, closed_world=closed_world)) is None or x.line_start in c
                ] or []
            if not live:
                warnings.append(f"{name}: có {len(cands)} định nghĩa nhưng không cái nào được biên dịch theo cờ build")
                return None
            if len(live) > 1:
                where = ", ".join(f"{x.file}:{x.line_start}" for x in live[:5])
                warnings.append(f"{name}: {len(live)} định nghĩa cùng được biên dịch ({where}); lấy cái đầu")
            sym = live[0]
            text = "\n".join(index.lines(sym.file, sym.line_start, sym.line_end))
            value = cexpr.strip_definition(text, sym.name)
            if value is None:
                return None
            used.update((sym.file, n) for n in range(sym.line_start, sym.line_end + 1))
            return value, f"{sym.file}:{sym.line_start}"

        try:
            res = cexpr.evaluate(p.expr, lookup)
        except cexpr.EvalError as exc:
            return _result(f"tool=eval {p.expr!r}", f"(không tính được: {exc})")
        rows = [f"giá trị: {res.value}" if res.value is not None else "giá trị: chưa xác định"]
        if res.trail:
            rows.append("vết thay thế:")
            rows += [f"  {t}" for t in res.trail]
        if res.unresolved:
            rows.append("chưa phân giải (không đoán): " + ", ".join(res.unresolved))
        rows += [f"cảnh báo: {w}" for w in warnings]
        return _result(f"tool=eval {p.expr!r}", "\n".join(rows), frozenset(used))

    handlers: list[tuple[str, type[BaseModel], Any]] = [
        ("code.grep", GrepParams, grep),
        ("code.glob", GlobParams, glob),
        ("code.read", ReadParams, read),
        ("code.eval", EvalParams, eval_expr),
    ]
    return [
        ToolSpec(name, TOOL_DOCS[name], params, handler, title=_TITLES[name], read_only=True)
        for name, params, handler in handlers
    ]

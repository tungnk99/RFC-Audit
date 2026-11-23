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

import fnmatch
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


class AlertSiteParams(_P):
    alert: str = Field(
        min_length=2,
        max_length=80,
        description="Tên mã cảnh báo cần quét toàn cục không phân biệt hoa thường (vd `illegal_parameter`, `decode_error`, `record_overflow`).",
        examples=["illegal_parameter", "decode_error", "record_overflow", "unexpected_message"],
    )
    keywords: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="Các từ khoá ngữ cảnh của yêu cầu (vd `['key_share', 'group']` hoặc `['content_type', 'record']`) để xếp hạng ứng viên.",
    )
    limit: int = Field(default=6, ge=1, le=12, description="Số ứng viên hàng đầu trả về (mặc định 6).")
    window: int = Field(default=4, ge=2, le=12, description="Số dòng ngữ cảnh trên/dưới mỗi điểm khớp (mặc định 4).")


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
    "code.find_alert_sites": (
        "Quét tĩnh toàn cục trên chỉ mục mã nguồn (loại bỏ thư mục test/example, không bị cắt cụt `head_limit`) để tìm và xếp hạng "
        "các điểm phát mã cảnh báo (`SendAlert`, `SSLfatal`, `RLAYERfatal`, `return ...`) không phân biệt hoa thường theo từ khoá yêu cầu.\n"
        "Khi dùng: khi kho mã tách nhiều tệp (vd OpenSSL `ssl/statem/`, `ssl/record/`) hoặc tệp rất dài (48k dòng) khiến `code.grep` bị cắt cụt "
        "hoặc có quá nhiều vị trí cùng phát một mã cảnh báo.\n"
        "Trả về: top ứng viên kèm tên hàm bao quanh `symbol (a–b)`, lát mã ±`window` dòng có đánh dấu `>>>` và `[DISABLED]` (mọi dòng đều tính là ĐÃ ĐỌC cho SchemaGate).\n"
        'Ví dụ: {"alert": "illegal_parameter", "keywords": ["key_share", "group", "client_hello"]}'
    ),
}

_TITLES = {
    "code.grep": "Tìm văn bản (ripgrep)",
    "code.glob": "Liệt kê tệp theo mẫu",
    "code.read": "Đọc tệp hoặc hàm",
    "code.eval": "Tính hằng số C",
    "code.find_alert_sites": "Quét & xếp hạng điểm phát cảnh báo",
}

CC_TOOL_DESCRIPTORS: tuple[ToolDescriptor, ...] = (
    ToolDescriptor("code.grep", Effect.SANDBOXED_RUN, reads_untrusted=True),
    ToolDescriptor("code.glob", Effect.SANDBOXED_RUN, reads_untrusted=True),
    ToolDescriptor("code.read", Effect.READ, reads_untrusted=True),
    ToolDescriptor("code.eval", Effect.READ, reads_untrusted=True),
    ToolDescriptor("code.find_alert_sites", Effect.READ, reads_untrusted=True),
)


def _result(
    header: str, body: str, shown: frozenset[tuple[str, int]] = frozenset(), cap: int = OUT_BYTES
) -> ToolResult:
    """Kết quả không bao giờ bị từ chối vì kích thước: quá cỡ thì cắt ở ranh giới dòng và nói rõ.
    Nếu bị cắt, loại bỏ các số dòng đã bị cắt khỏi `shown` để không cho phép dẫn dòng agent chưa thấy."""
    text = f"[UNTRUSTED CODE] {header}\n{body}"
    raw = text.encode("utf-8")
    if len(raw) > cap:
        cut = raw[:cap].decode("utf-8", errors="ignore")
        cut = cut[: cut.rfind("\n")] if "\n" in cut else cut
        if shown:
            kept_nums: set[int] = set()
            for line in cut.split("\n")[1:]:
                head = line[:6].strip()
                if head.isdigit():
                    kept_nums.add(int(head))
                elif (m := _MATCH.match(line)) is not None:
                    kept_nums.add(int(m.group("line")))
            shown = frozenset((f, n) for f, n in shown if n in kept_nums)
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
            # Fallback thuần Python trên CodeIndex khi môi trường không có ripgrep (vd NoExec ở e2e_hard/e2e_live).
            flags = re.IGNORECASE if p.ignore_case else 0
            if p.multiline:
                flags |= re.DOTALL | re.MULTILINE
            try:
                rx = re.compile(p.pattern, flags)
            except re.error:
                return _result(header, out)
            fallback_lines: list[str] = []
            for f in sorted(known_files):
                if p.path and not (f == p.path or f.startswith(p.path.rstrip("/") + "/")):
                    continue
                if p.glob and not fnmatch.fnmatch(f, p.glob) and not fnmatch.fnmatch(f.rsplit("/", 1)[-1], p.glob):
                    continue
                if p.type == "c" and not f.endswith((".c", ".h")):
                    continue
                total_f = line_count(f) or 0
                if total_f <= 0:
                    continue
                src_lines = list(index.lines(f, 1, total_f))
                matched_idx = [i for i, row in enumerate(src_lines) if rx.search(row)]
                if not matched_idx:
                    continue
                if p.output_mode == "files_with_matches":
                    fallback_lines.append(f)
                elif p.output_mode == "count":
                    fallback_lines.append(f"{f}:{len(matched_idx)}")
                else:
                    b_ctx = p.context or p.before
                    a_ctx = p.context or p.after
                    emitted: set[int] = set()
                    for mi in matched_idx:
                        lo = max(0, mi - b_ctx)
                        hi = min(len(src_lines) - 1, mi + a_ctx)
                        for j in range(lo, hi + 1):
                            if j in emitted:
                                continue
                            emitted.add(j)
                            sep = ":" if j in matched_idx else "-"
                            fallback_lines.append(f"{f}{sep}{j + 1}{sep}{src_lines[j]}")
            lines = fallback_lines
        else:
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
            # Fallback thuần Python trên CodeIndex khi không có ripgrep.
            pat = p.pattern
            files = sorted(
                f
                for f in known_files
                if (not p.path or f == p.path or f.startswith(p.path.rstrip("/") + "/"))
                and (
                    fnmatch.fnmatch(f, pat)
                    or fnmatch.fnmatch(f, pat.removeprefix("**/"))
                    or fnmatch.fnmatch(f.rsplit("/", 1)[-1], pat.removeprefix("**/"))
                )
            )
        else:
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
                for idx_offset, raw_line in enumerate(body.split("\n")):
                    lineno = start + idx_offset
                    if lineno not in compiled:
                        disabled_seen += 1
                        annotated.append(f"{raw_line[:6]} [DISABLED]{raw_line[6:]}")
                    else:
                        annotated.append(raw_line)
                body = "\n".join(annotated)
        total = line_count(file)
        enclosing = index.containing_symbol(file, (start + last) // 2) or index.containing_symbol(file, start)
        sym_note = (
            f" [symbol: {enclosing.name} ({enclosing.line_start}–{enclosing.line_end})]"
            if enclosing is not None
            else ""
        )
        disabled_note = f" ({disabled_seen} dòng [DISABLED] bị tắt bởi cờ build)" if disabled_seen else ""
        head = f"tool=read {file} lines {start}–{last}" + (f" of {total}" if total else "") + sym_note + disabled_note
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

    # ---- find_alert_sites (năng lực phân tích tĩnh toàn cục cho AI Agent tự gọi) ----------------------------------

    _noise_dir = re.compile(r"^(?:tests?|examples?|testsuite|fuzz|demos?|docs?|bench|benchmark|scripts?|apps?)/", re.I)
    _action_re = re.compile(
        r"\b(?:sendalert|sslfatal|rlayerfatal|alert_fatal|tls_alert|goaway|rst_stream|terminate_session|"
        r"rcode|formerr|badvers|servfail|refused|disconnect|connection_close|return|goto)\b",
        re.I,
    )
    _log_re = re.compile(r'^\s*(?:/\*|\*|//|WOLFSSL_MSG|printf|fprintf|ERR_raise|case\s+\w+:\s*return\s*")')
    _tok_re = re.compile(r"[A-Za-z0-9]+")

    async def find_alert_sites(p: BaseModel, s: ToolSession) -> ToolResult:
        assert isinstance(p, AlertSiteParams)
        term = p.alert.strip()
        pat = re.compile(rf"\b[A-Za-z0-9_]*{re.escape(term)}\b", re.IGNORECASE)
        stop = {"send", "receive", "respond", "close", "discard", "alert", "true", "false", "none", "valid"}
        atoms = tuple(
            dict.fromkeys(t for kw in p.keywords for t in _tok_re.findall(kw.lower()) if len(t) >= 3 and t not in stop)
        )
        compiled_of: Any = getattr(index, "compiled_lines", None)
        compiled_cache: dict[str, set[int] | None] = {}

        def _comp(f: str) -> set[int] | None:
            if f not in compiled_cache:
                compiled_cache[f] = (
                    compiled_of(f, tuple(build_flags), closed_world=closed_world) if compiled_of is not None else None
                )
            return compiled_cache[f]

        files = [
            f
            for f in index.files()
            if f.endswith((".c", ".cc", ".cpp", ".h")) and not _noise_dir.search(f.replace("\\", "/"))
        ]
        files.sort(key=lambda f: (not f.endswith(".c"), f))

        hits: list[tuple[int, str, int, Any]] = []
        for rel in files[:250]:
            total = line_count(rel) or 200_000
            src_lines = index.lines(rel, 1, total)
            if not src_lines:
                continue
            file_low = rel.replace("\\", "/").lower()
            for idx0, raw in enumerate(src_lines):
                if pat.search(raw) is None:
                    continue
                lineno = idx0 + 1
                sym = index.containing_symbol(rel, lineno)
                if sym is None or sym.kind not in FUNCTION_KINDS:
                    continue
                sym_low = sym.name.lower()
                lo = max(sym.line_start, lineno - 12)
                hi = min(sym.line_end, lineno + 12)
                ctx_text = "\n".join(src_lines[lo - 1 : hi]).lower()
                score = sum(3 for tok in atoms if tok in ctx_text or tok in sym_low or tok in file_low)
                if _action_re.search(raw):
                    score += 2
                if _log_re.search(raw):
                    score -= 5
                if "client" in atoms and "serverhello" in sym_low and "clienthello" not in sym_low:
                    score -= 8
                hits.append((score, rel, lineno, sym))

        if not hits:
            return _result(f"tool=find_alert_sites alert={term!r}", "(không tìm thấy vị trí phát cảnh báo nào)")

        hits.sort(key=lambda h: (-h[0], h[1], h[2]))
        selected: list[tuple[int, str, int, Any]] = []
        for h in hits:
            if any(x[1] == h[1] and abs(x[2] - h[2]) <= p.window for x in selected):
                continue
            selected.append(h)
            if len(selected) >= p.limit:
                break

        out_lines: list[str] = []
        shown: set[tuple[str, int]] = set()
        for rank, (score, rel, lineno, sym) in enumerate(selected, 1):
            lo = max(sym.line_start, lineno - p.window)
            hi = min(sym.line_end, lineno + p.window)
            snippet = index.lines(rel, lo, hi)
            comp = _comp(rel)
            out_lines.append(
                f"### #{rank} (score={score}): {rel}:{lineno} [symbol: {sym.name} ({sym.line_start}–{sym.line_end})]"
            )
            for off, line_text in enumerate(snippet):
                cur = lo + off
                shown.add((rel, cur))
                tag = "[DISABLED] " if (comp is not None and cur not in comp) else ""
                mark = ">>>" if cur == lineno else "   "
                out_lines.append(f"{rel}:{cur}:{mark} {tag}{line_text}")
        return _result(
            f"tool=find_alert_sites alert={term!r} ({len(selected)}/{len(hits)} khớp)",
            "\n".join(out_lines),
            frozenset(shown),
            cap=6144,
        )

    handlers: list[tuple[str, type[BaseModel], Any]] = [
        ("code.grep", GrepParams, grep),
        ("code.glob", GlobParams, glob),
        ("code.read", ReadParams, read),
        ("code.eval", EvalParams, eval_expr),
        ("code.find_alert_sites", AlertSiteParams, find_alert_sites),
    ]
    return [
        ToolSpec(name, TOOL_DOCS[name], params, handler, title=_TITLES[name], read_only=True)
        for name, params, handler in handlers
    ]

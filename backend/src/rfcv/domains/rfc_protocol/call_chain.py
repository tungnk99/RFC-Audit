"""Công cụ chủ động `code.call_chain`: truy vết chuỗi gọi và dòng dùng một định danh qua nhiều hàm (gen-50).

Chỉ dựa trên Protocol `CodeIndex` (không chạy lệnh, không đọc thẳng kho mã). Mọi kết quả mang nhãn UNTRUSTED.
Chỉ những cạnh gọi và dòng mã THẬT SỰ được in ra mới vào `shown_edges` / `shown_lines` để Schema gate chấp nhận.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rfcv.core.ifc import TrustLabel
from rfcv.gates.code_gate import FUNCTION_KINDS, CodeIndex, SymbolInfo
from rfcv.gates.tool_gateway import ToolResult, ToolSession, ToolSpec

MAX_FILTER_FUNCTIONS = 10
MAX_FILTER_LINES = 4
MAX_LINE_CHARS = 160
# Trần kích thước đầu ra, cùng mức với các công cụ đọc mã; chừa chỗ cho tiêu đề và ghi chú cắt bớt.
_MAX_ROWS = 190
_MAX_BODY_BYTES = 14 * 1024

# Dòng quyết định hành vi: rẽ nhánh, trả về, so sánh. `->`, `<<`, `>>` không phải phép so sánh.
_DECISION = re.compile(r"\b(?:if|switch|return)\b|==|!=|<=|>=|(?<![-<>])[<>](?![<>])")

Direction = Literal["callers", "callees"]


class CallChainParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=120, description="Tên hàm gốc cần truy vết chuỗi gọi.")
    direction: Literal["callers", "callees", "both"] = Field(
        default="both",
        description="Hướng truy vết: callers (ngược lên hàm gọi), callees (xuôi xuống hàm con), hoặc both.",
    )
    depth: int = Field(default=2, ge=1, le=3, description="Độ sâu BFS tối đa (1–3 bước).")
    filter_identifier: str = Field(
        default="",
        max_length=80,
        description="Tùy chọn: tên biến/trường/hằng cần soi dòng dùng trong từng hàm thuộc chuỗi gọi.",
    )
    max_nodes: int = Field(default=20, ge=1, le=40, description="Số cạnh tối đa mỗi chiều.")


def _definition(index: CodeIndex, name: str) -> list[SymbolInfo]:
    return [s for s in index.lookup(name) if s.kind in FUNCTION_KINDS]


def _neighbours(index: CodeIndex, fn: str, direction: Direction) -> Iterator[tuple[tuple[str, str], str, str]]:
    """(cạnh (hàm gọi, hàm được gọi), hàm kề, vị trí lời gọi) của `fn` theo một chiều."""
    if direction == "callees":
        for callee, line in index.callees(fn):
            # Bỏ hàm thư viện/ngoài kho: không có trong chỉ mục.
            if index.lookup(callee):
                yield (fn, callee), callee, f"dòng gọi {line}"
        return
    seen: set[str] = set()
    for ref in index.references(fn):
        caller = ref.container
        if caller in seen:
            continue
        seen.add(caller)
        if _definition(index, caller) and index.has_call_edge(caller, fn):
            yield (caller, fn), caller, f"tham chiếu tại {ref.file}:{ref.line}"


def _walk(
    index: CodeIndex, root: str, direction: Direction, depth: int, max_edges: int
) -> tuple[list[tuple[int, tuple[str, str], str, str]], bool]:
    """BFS một chiều. Trả danh sách (bước, cạnh, hàm kề, vị trí) và cờ báo đã cắt vì chạm trần số cạnh."""
    found: list[tuple[int, tuple[str, str], str, str]] = []
    visited = {root}
    frontier = [root]
    for level in range(1, depth + 1):
        next_frontier: list[str] = []
        for fn in frontier:
            for edge, other, where in _neighbours(index, fn, direction):
                if len(found) >= max_edges:
                    return found, True
                found.append((level, edge, other, where))
                if other not in visited:
                    visited.add(other)
                    next_frontier.append(other)
        frontier = next_frontier
    return found, False


def _matching_lines(index: CodeIndex, sym: SymbolInfo, identifier: str) -> list[tuple[int, str]]:
    """Tối đa `MAX_FILTER_LINES` dòng chứa `identifier`, ưu tiên dòng rẽ nhánh/so sánh, in theo thứ tự dòng."""
    hits = [
        (sym.line_start + i, text)
        for i, text in enumerate(index.lines(sym.file, sym.line_start, sym.line_end))
        if identifier in text
    ]
    hits.sort(key=lambda h: (_DECISION.search(h[1]) is None, h[0]))
    return sorted(hits[:MAX_FILTER_LINES])


class _Output:
    """Gom dòng đầu ra trong ngân sách; `add` trả False khi đã hết chỗ (khi đó không được tính là đã hiển thị)."""

    def __init__(self) -> None:
        self.rows: list[str] = []
        self.used = 0
        self.truncated = False

    def add(self, row: str) -> bool:
        size = len(row.encode("utf-8")) + 1
        if self.truncated or len(self.rows) >= _MAX_ROWS or self.used + size > _MAX_BODY_BYTES:
            self.truncated = True
            return False
        self.rows.append(row)
        self.used += size
        return True


def call_chain_tool_spec(rt: Any) -> ToolSpec:
    """Công cụ `code.call_chain` trên chỉ mục mã của lần chạy."""

    async def handler(p: BaseModel, session: ToolSession) -> ToolResult:
        params = CallChainParams.model_validate(p.model_dump())
        index: CodeIndex | None = getattr(getattr(rt, "providers", None), "code_index", None)
        if index is None:
            return ToolResult("tool=code.call_chain: không có chỉ mục mã cho lần chạy này.", TrustLabel.DERIVED)
        out = _Output()
        shown_lines: set[tuple[str, int]] = set()
        shown_edges: set[tuple[str, str]] = set()
        if not _definition(index, params.symbol):
            out.add(f"(chỉ mục không có định nghĩa hàm '{params.symbol}'; kiểm lại tên bằng code__grep)")

        directions: tuple[Direction, ...] = (
            ("callers", "callees") if params.direction == "both" else (params.direction,)
        )
        distance: dict[str, int] = {params.symbol: 0}  # hàm trong chuỗi -> số bước gần nhất tới hàm gốc
        for direction in directions:
            edges, capped = _walk(index, params.symbol, direction, params.depth, params.max_nodes)
            out.add(f"== {direction} ==")
            if not edges:
                out.add("  (không có cạnh gọi nào trong chỉ mục)")
            for level, edge, other, where in edges:
                if not out.add(f"  [bước {level}] {edge[0]} -> {edge[1]} ({where})"):
                    break
                shown_edges.add(edge)
                distance[other] = min(level, distance.get(other, level))
            if capped:
                out.add(f"  (đã cắt ở max_nodes={params.max_nodes} cạnh)")

        if params.filter_identifier:
            out.add(f"== dòng chứa '{params.filter_identifier}' ==")
            # Hàm gần gốc trước, để một chiều nhiều cạnh không chiếm hết suất của chiều kia.
            ordered = sorted(distance, key=lambda name: distance[name])
            functions = [(name, defs) for name in ordered if (defs := _definition(index, name))]
            matched = False
            for name, defs in functions[:MAX_FILTER_FUNCTIONS]:
                sym = defs[0]
                hits = _matching_lines(index, sym, params.filter_identifier)
                if not hits:
                    continue
                matched = True
                extra = f"; còn {len(defs) - 1} định nghĩa cùng tên chưa soi" if len(defs) > 1 else ""
                if not out.add(f"-- {name} ({sym.file}:{sym.line_start}-{sym.line_end}{extra})"):
                    break
                for number, text in hits:
                    if out.add(f"{sym.file}:{number}: {text.strip()[:MAX_LINE_CHARS]}"):
                        shown_lines.add((sym.file, number))
            if not matched:
                out.add("  (không dòng nào khớp trong các hàm đã soi)")
            if len(functions) > MAX_FILTER_FUNCTIONS:
                out.add(f"  (chỉ soi {MAX_FILTER_FUNCTIONS}/{len(functions)} hàm gần gốc nhất)")

        header = (
            f"[UNTRUSTED CODE] tool=code.call_chain symbol={params.symbol} "
            f"direction={params.direction} depth={params.depth}"
        )
        body = "\n".join(out.rows)
        if out.truncated:
            body += "\n(đầu ra đã cắt bớt; giảm depth hoặc max_nodes)"
        return ToolResult(
            f"{header}\n{body}",
            TrustLabel.UNTRUSTED,
            shown_lines=frozenset(shown_lines),
            shown_edges=frozenset(shown_edges),
        )

    return ToolSpec(
        "code.call_chain",
        "Truy vết chuỗi gọi nhiều bước (hàm gọi và/hoặc hàm con) từ một hàm, chỉ gồm cạnh có trong chỉ mục mã. "
        "Đặt `filter_identifier` để xem ngay các dòng if/switch/return/so sánh dùng một biến, trường hay hằng trong "
        "từng hàm của chuỗi. Gọi khi phép kiểm tra và phản ứng lỗi nằm ở các hàm khác nhau.",
        CallChainParams,
        handler,
        title="Chuỗi gọi hàm và dòng dùng định danh",
    )

"""Schema gate của miền RFC giao thức: đối chiếu LocationClaim với chỉ mục mã trước khi ghi T1.

Kiểm tra (tài liệu khám phá mã, Bảng 8; tài liệu khả thi, mục 6):
1. ký hiệu có trong chỉ mục; khoảng dòng nằm trong thân ký hiệu;
2. mọi dòng được dẫn thuộc tập dòng đã hiển thị cho agent trong phiên;
3. mỗi cạnh của call_path có trong chỉ mục lời gọi (hoặc công cụ cấu trúc đã hiển thị cạnh đó), hoặc là cạnh
   `textual`: một dòng đã hiển thị nằm trong thân ký hiệu gọi và nhắc tới tên ký hiệu được gọi (con trỏ hàm, bảng xử lý);
4. observed thuộc từ vựng adapter hoặc là số; THRESHOLD không tự mâu thuẫn (MISMATCH mà số đúng bằng ngưỡng của yêu cầu);
5. dòng được dẫn phải được biên dịch theo cờ build (nếu có dữ liệu tiền xử lý/độ phủ).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Literal

from rfcv.domains.rfc_protocol.payloads import AspectCheck, AspectName, AspectValue, Producer, T1Payload, Tier
from rfcv.domains.rfc_protocol.schemas import LocationClaim
from rfcv.evidence.models import EvidenceDraft
from rfcv.gates.code_gate import CodeIndex
from rfcv.gates.schema_gate import GateResult
from rfcv.gates.tool_gateway import ToolSession


def _cited_ranges(claim: LocationClaim) -> list[tuple[int, int]]:
    return [(claim.line_start, claim.line_end), *[a.lines for a in claim.aspects]]


class SchemaGate:
    def __init__(
        self,
        index: CodeIndex,
        vocabulary_terms: Iterable[str],
        compiled_lines: Callable[[str], set[int] | None] | None = None,
    ) -> None:
        self._index = index
        self._terms = frozenset(vocabulary_terms)
        self._compiled = compiled_lines

    def _textual_edge(self, caller: str, callee: str, session: ToolSession) -> bool:
        """Có dòng đã hiển thị thuộc thân `caller` mà nhắc tới `callee` như một từ riêng."""
        word = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(callee)}(?![A-Za-z0-9_])")
        spans = [(s.file, s.line_start, s.line_end) for s in self._index.lookup(caller)]
        for file, line in sorted(session.shown_lines):
            if not any(f == file and a <= line <= b for f, a, b in spans):
                continue
            sym = self._index.containing_symbol(file, line)
            if sym is None or sym.name != caller:
                continue
            text = self._index.lines(file, line, line)
            if text and word.search(text[0]):
                return True
        return False

    def check_location(
        self,
        claim: LocationClaim,
        session: ToolSession,
        *,
        run_id: str,
        requirement_id: str,
        msg_id: str,
        threshold: int | None = None,
    ) -> GateResult:
        """`threshold`: giá trị số trong `where` của yêu cầu, nếu có (để kiểm THRESHOLD không tự mâu thuẫn)."""
        errors: list[str] = []

        sym = self._index.symbol_in_file(claim.file, claim.symbol)
        if sym is None:
            errors.append("SYMBOL_NOT_IN_INDEX")
        elif not (sym.line_start <= claim.line_start <= claim.line_end <= sym.line_end):
            errors.append("LINES_OUTSIDE_SYMBOL")

        for start, end in _cited_ranges(claim):
            if start > end:
                errors.append("BAD_RANGE")
                continue
            if any((claim.file, n) not in session.shown_lines for n in range(start, end + 1)):
                errors.append("LINES_NOT_SHOWN")
                break

        edge_kinds: list[Literal["index", "textual"]] = []
        for a, b in zip(claim.call_path, claim.call_path[1:], strict=False):
            if self._index.has_call_edge(a, b) or (a, b) in session.shown_edges:
                edge_kinds.append("index")
            elif self._textual_edge(a, b, session):
                edge_kinds.append("textual")
            else:
                errors.append("CALL_EDGE_UNKNOWN")
                break

        for aspect in claim.aspects:
            if isinstance(aspect.observed, str) and aspect.observed not in self._terms:
                errors.append("OBSERVED_NOT_IN_VOCABULARY")
                break

        # Số đã tính đúng bằng ngưỡng của yêu cầu mà vẫn tuyên bố lệch là tự mâu thuẫn (đo: sau khi cấp kết quả trước,
        # Code Reader ghi THRESHOLD MISMATCH kèm "khớp đúng giá trị where" trong note, và nhãn rơi xuống NEEDS_REVIEW).
        # Hướng so sánh sai hay đại lượng sai thuộc khía cạnh CONDITION, không phải THRESHOLD.
        if threshold is not None and any(
            a.aspect is AspectName.THRESHOLD and a.value is AspectValue.MISMATCH and a.observed == threshold
            for a in claim.aspects
        ):
            errors.append("THRESHOLD_EQUALS_EXPECTED")

        if self._compiled is not None:
            compiled = self._compiled(claim.file)
            if compiled is not None:
                for start, end in (a.lines for a in claim.aspects):
                    if not any(n in compiled for n in range(start, end + 1)):
                        errors.append("LINES_NOT_COMPILED")
                        break

        if errors:
            return GateResult(False, tuple(dict.fromkeys(errors)))

        payload = T1Payload(
            file=claim.file,
            symbol=claim.symbol,
            line_start=claim.line_start,
            line_end=claim.line_end,
            finding=claim.finding,
            aspects=tuple(
                AspectCheck(aspect=a.aspect, value=a.value, observed=a.observed, lines=a.lines) for a in claim.aspects
            ),
            call_path=tuple(claim.call_path),
            call_edge_kinds=tuple(edge_kinds),
            unexplored=tuple(claim.unexplored),
        )
        draft = EvidenceDraft(
            run_id=run_id,
            requirement_id=requirement_id,
            tier=Tier.T1,
            payload=payload,
            produced_by=Producer.SCHEMA_GATE,
            requested_by={"role": session.role, "msg_id": msg_id},
        )
        return GateResult(True, (), draft)

"""Schema gate của miền RFC giao thức: đối chiếu LocationClaim với chỉ mục mã trước khi ghi T1.

Kiểm tra (tài liệu khám phá mã, Bảng 8; tài liệu khả thi, mục 6):
1. ký hiệu có trong chỉ mục; khoảng dòng nằm trong thân ký hiệu;
2. mọi dòng được dẫn thuộc tập dòng đã hiển thị cho agent trong phiên;
3. mỗi cạnh của call_path có trong chỉ mục lời gọi, hoặc đã hiển thị cho agent (cạnh textual);
4. observed thuộc từ vựng adapter hoặc là số;
5. dòng được dẫn phải được biên dịch theo cờ build (nếu có dữ liệu tiền xử lý/độ phủ).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from rfcv.domains.rfc_protocol.payloads import AspectCheck, Producer, T1Payload, Tier
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

    def check_location(
        self, claim: LocationClaim, session: ToolSession, *, run_id: str, requirement_id: str, msg_id: str
    ) -> GateResult:
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

        for a, b in zip(claim.call_path, claim.call_path[1:], strict=False):
            if not self._index.has_call_edge(a, b) and (a, b) not in session.shown_edges:
                errors.append("CALL_EDGE_UNKNOWN")
                break

        for aspect in claim.aspects:
            if isinstance(aspect.observed, str) and aspect.observed not in self._terms:
                errors.append("OBSERVED_NOT_IN_VOCABULARY")
                break

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

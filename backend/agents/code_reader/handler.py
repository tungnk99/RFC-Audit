"""Handler của Code Reader: LocationClaim → Schema gate → T1 → liên kết độ phủ → quét nhánh nghi vấn (T2).

Agent không ghi bằng chứng; cổng mới ghi. Bộ quét nhánh nghi vấn chạy sau khi T1 được nhận, trên đúng các hàm của đường xử lý."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from agents.code_reader.schema import LocationClaim
from rfcv.core.execution_loop import Investigation
from rfcv.domains.rfc_protocol.coverage_linker import link_pending
from rfcv.domains.rfc_protocol.payloads import Producer, T2SuspiciousPayload, Tier
from rfcv.domains.rfc_protocol.schema_gate import SchemaGate
from rfcv.domains.rfc_protocol.suspicious import canonical_values, scan_symbols
from rfcv.evidence.models import EvidenceDraft
from rfcv.gates.tool_gateway import ToolSession


def _threshold_of(inv: Investigation) -> int | None:
    """Giá trị số trong `where` của RBS (ví dụ 16640 của `record.length > 16640`), nếu yêu cầu có."""
    rbs: Any = inv.context.get("requirement.rbs")
    where: Any = rbs.value.get("where") if rbs is not None and isinstance(rbs.value, dict) else None  # type: ignore[union-attr]
    value: Any = where.get("value") if isinstance(where, dict) else None  # type: ignore[union-attr]
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class LocationHandler:
    """LOCATE, TRACE_PATHS, RECHECK."""

    def __init__(self, rt: Any, gate: SchemaGate) -> None:
        self._rt = rt
        self._gate = gate

    def precheck(self, inv: Investigation, output: BaseModel, session: ToolSession) -> Sequence[str]:
        """Chạy Schema gate (không ghi) khi agent vừa trả kết quả, để agent sửa trong ngân sách (tối đa hai lần)."""
        if not isinstance(output, LocationClaim):
            return ()
        req_id = inv.requirement.requirement_id
        return self._gate.check_location(
            output, session, run_id=self._rt.run_id, requirement_id=req_id, msg_id="", threshold=_threshold_of(inv)
        ).errors

    async def handle(
        self, inv: Investigation, task: Any, output: BaseModel | None, session: ToolSession, msg_id: str
    ) -> int:
        if not isinstance(output, LocationClaim):
            return 0
        req_id = inv.requirement.requirement_id
        result = self._gate.check_location(
            output, session, run_id=self._rt.run_id, requirement_id=req_id, msg_id=msg_id, threshold=_threshold_of(inv)
        )
        if not result.accepted or result.draft is None:
            self._rt.trace.append(
                self._rt.run_id,
                "gate_reject",
                {
                    "gate": "schema_gate",
                    "msg_id": msg_id,
                    "errors": list(result.errors),
                    "retries": session.output_rejections,
                },
                role=session.role,
                requirement_id=req_id,
            )
            return 0
        self._rt.store.append(result.draft)
        return (
            1 + link_pending(self._rt.store, self._rt.artifacts, self._rt.run_id, req_id) + self._scan(output, req_id)
        )

    def _scan(self, claim: LocationClaim, req_id: str) -> int:
        """Quét các hàm trên đường xử lý (hàm chứa vị trí và `call_path`) tìm nhánh nhận ra kiểm thử; ghi T2 cho mỗi chỗ mới."""
        index: Any = getattr(getattr(self._rt, "providers", None), "code_index", None)
        manifest: Any = getattr(self._rt, "manifest", None)
        if index is None or manifest is None:
            return 0
        symbols: list[Any] = []
        located = index.symbol_in_file(claim.file, claim.symbol)
        if located is not None:
            symbols.append(located)
        for name in claim.call_path:
            symbols += [s for s in index.lookup(name) if s.kind == "function"]
        findings = scan_symbols(index, symbols, canonical_values(manifest.field_domains))
        known = {
            (p.rule_id, p.file, p.line)
            for e in self._rt.store.for_requirement(req_id)
            if isinstance((p := e.payload), T2SuspiciousPayload)
        }
        written = 0
        for f in findings:
            if (f.rule_id, f.file, f.line) in known:
                continue
            self._rt.store.append(
                EvidenceDraft(
                    run_id=self._rt.run_id,
                    requirement_id=req_id,
                    tier=Tier.T2,
                    payload=T2SuspiciousPayload(rule_id=f.rule_id, file=f.file, line=f.line, on_path=True),
                    produced_by=Producer.CODE_GATE,
                )
            )
            written += 1
        self._rt.trace.append(
            self._rt.run_id,
            "suspicious_scan",
            {"symbols": len(symbols), "findings": len(findings), "new": written},
            requirement_id=req_id,
        )
        return written

"""Handler của Code Reader: LocationClaim → Schema gate → T1 → liên kết độ phủ → quét nhánh nghi vấn (T2).

Agent không ghi bằng chứng; cổng mới ghi. Bộ quét nhánh nghi vấn chạy sau khi T1 được nhận, trên đúng các hàm của đường xử lý."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel

from agents.code_reader.schema import LocationClaim
from agents.common import RBS_KEY
from rfcv.core.execution_loop import Investigation
from rfcv.core.ifc import Labeled, TrustLabel
from rfcv.domains.rfc_protocol.coverage_linker import link_pending
from rfcv.domains.rfc_protocol.diagnosis import (
    NO_CLOSE,
    NONE,
    REACTION_ABSENT,
    WRONG_ALERT,
    candidate_patterns,
    diagnose,
)
from rfcv.domains.rfc_protocol.payloads import Producer, T2SuspiciousPayload, T3Payload, Tier
from rfcv.domains.rfc_protocol.schema_gate import SchemaGate
from rfcv.domains.rfc_protocol.suspicious import canonical_values, scan_symbols
from rfcv.evidence.models import EvidenceDraft
from rfcv.gates.tool_gateway import ToolSession, ToolSpec


def _threshold_of(inv: Investigation) -> int | None:
    """Giá trị số trong `where` của RBS (ví dụ 16640 của `record.length > 16640`), nếu yêu cầu có."""
    rbs: Any = inv.context.get("requirement.rbs")
    where: Any = rbs.value.get("where") if rbs is not None and isinstance(rbs.value, dict) else None  # type: ignore[union-attr]
    value: Any = where.get("value") if isinstance(where, dict) else None  # type: ignore[union-attr]
    return value if isinstance(value, int) and not isinstance(value, bool) else None


_MACRO = re.compile(r"\b[A-Z][A-Z0-9_]{3,}\b")
_ROW = re.compile(r"^[^\s:]+?[:-]\d+[:-](?P<text>.*)$")  # dòng kết quả grep: tệp:dòng:mã hoặc tệp-dòng-mã
_GUARD = re.compile(r"^\s*#\s*(?:ifdef|ifndef|if|elif)\b(.*)$")
MAX_GUARD_MACROS = 6


def _expected_alert(inv: Investigation) -> str | None:
    """Mã cảnh báo mà RBS đòi (đối số của lời gọi `send_alert(...)` đầu tiên trong `expect`)."""
    rbs: Any = inv.domain_state.get(RBS_KEY)
    first = rbs.expect[0] if rbs is not None and rbs.expect else None
    return str(first.args[0]) if first is not None and first.name == "send_alert" and first.args else None


class LocationHandler:
    """LOCATE, TRACE_PATHS, RECHECK."""

    def __init__(self, rt: Any, gate: SchemaGate, code_tools: Mapping[str, ToolSpec] | None = None) -> None:
        self._rt = rt
        self._gate = gate
        self._tools = code_tools or {}

    async def enrich(self, inv: Investigation, task: Any) -> tuple[dict[str, Labeled[Any]], frozenset[tuple[str, int]]]:
        """Ngữ cảnh chuẩn bị bằng luật cho Code Reader (không tốn token LLM):

        - `behavior.diagnosis`: T3 cho biết lỗi kiểu gì (phản ứng thiếu, sai mã, không đóng...) và nên đọc gì, để agent kiểm chứng
          giả thuyết thay vì mò từ đầu;
        - `code.candidates`: khi phản ứng thiếu hay sai, mọi nơi phát mã cảnh báo kèm hàm chứa, và `defined()` của macro bảo vệ chúng
          (grep và eval cùng một công cụ agent dùng; dòng trả về tính là đã hiển thị cho Schema gate)."""
        req_id = inv.requirement.requirement_id
        t3s = [e.payload for e in self._rt.store.for_requirement(req_id) if isinstance(e.payload, T3Payload)]
        expected = _expected_alert(inv)
        diagnosis = diagnose(expected, t3s)
        context: dict[str, Labeled[Any]] = {}
        shown: frozenset[tuple[str, int]] = frozenset()
        if diagnosis.signature == NONE:
            return context, shown
        context["behavior.diagnosis"] = Labeled(diagnosis.to_json(), TrustLabel.DERIVED)
        if (
            diagnosis.signature in (REACTION_ABSENT, WRONG_ALERT, NO_CLOSE)
            and (expected or diagnosis.observed_alerts)
            and {"code.grep", "code.eval"} <= set(self._tools)
        ):
            text, shown = await self._candidates(expected, diagnosis.observed_alerts, req_id)
            if text:
                context["code.candidates"] = Labeled(text, TrustLabel.UNTRUSTED)
        self._rt.trace.append(
            self._rt.run_id,
            "enriched",
            {"signature": diagnosis.signature, "candidates": "code.candidates" in context, "shown": len(shown)},
            role="execution_loop",
            requirement_id=req_id,
        )
        return context, shown

    async def _candidates(
        self, expected: str | None, observed_alerts: Sequence[str], req_id: str
    ) -> tuple[str, frozenset[tuple[str, int]]]:
        from rfcv.gates.code_tools import EvalParams, GrepParams

        patterns = candidate_patterns(expected, observed_alerts)
        if not patterns:
            return "", frozenset()
        session = ToolSession(self._rt.run_id, "code_reader", req_id, max_tool_calls=0)
        parts: list[str] = []
        shown: set[tuple[str, int]] = set()
        guards: list[str] = []
        per_pattern_limit = 10 if len(patterns) > 1 else 15
        for pat in patterns:
            grep = await self._tools["code.grep"].handler(
                GrepParams(pattern=pat, type="c", context=2, head_limit=per_pattern_limit), session
            )
            parts.append(grep.text)
            shown |= set(grep.shown_lines)
            for line in grep.text.splitlines():
                row = _ROW.match(line)
                m = _GUARD.match(row.group("text")) if row else None
                if m:
                    guards += [n for n in _MACRO.findall(m.group(1)) if n not in ("defined",) and n not in guards]
        for name in guards[:MAX_GUARD_MACROS]:
            res = await self._tools["code.eval"].handler(EvalParams(expr=f"defined({name})"), session)
            parts.append(res.text)
            shown |= set(res.shown_lines)
        return "\n".join(parts), frozenset(shown)

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

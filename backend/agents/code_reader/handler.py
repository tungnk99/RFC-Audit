"""Handler của Code Reader: LocationClaim → Schema gate → T1 → liên kết độ phủ → quét nhánh nghi vấn (T2).

Agent không ghi bằng chứng; cổng mới ghi. Bộ quét nhánh nghi vấn chạy sau khi T1 được nhận, trên đúng các hàm của đường xử lý."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel

from agents.code_reader.schema import LocationClaim
from agents.common import RBS_KEY
from agents.locator.service import requirement_keywords
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
from rfcv.domains.rfc_protocol.multi_hypothesis import score_claim
from rfcv.domains.rfc_protocol.payloads import AspectName, AspectValue, Producer, T2SuspiciousPayload, T3Payload, Tier
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

    def branches(self, inv: Investigation, task: Any) -> Sequence[dict[str, Any]]:
        """Khi T3 đã chứng minh vi phạm, chạy song song các AI Agent chuyên biệt (Bottom-Up, Top-Down, và Error-to-Alert Mapper)."""
        if str(getattr(task, "task_type", "")) != "LOCATE":
            return ()
        req_id = inv.requirement.requirement_id
        t3s = [e.payload for e in self._rt.store.for_requirement(req_id) if isinstance(e.payload, T3Payload)]
        diag = diagnose(_expected_alert(inv), t3s)
        if diag.signature not in (REACTION_ABSENT, WRONG_ALERT, NO_CLOSE):
            return ()
        obs = ", ".join(a for a in diag.observed_alerts if a != "none") or str(_expected_alert(inv) or "")
        exp = str(_expected_alert(inv) or "")
        rbs = inv.domain_state.get(RBS_KEY)
        trig = (
            str(getattr(getattr(rbs, "trigger", None), "name", ""))
            + "("
            + ",".join(str(a) for a in getattr(getattr(rbs, "trigger", None), "args", ()))
            + ")"
        )
        dir_hint = (
            "Chú ý chiều giao thức: SUT là phía nhận `" + trig + "` (nếu là `client_hello`, SUT là SERVER — "
            "TUYỆT ĐỐI KHÔNG chọn hàm phía client như `DoServerHello`/`CompleteServerHello`). "
            "Đặt `call_path: [symbol]` (đúng tên hàm `symbol`) trừ khi bạn đã đọc trực tiếp lời gọi hàm cha để tránh `CALL_EDGE_UNKNOWN`."
        )
        out: list[dict[str, Any]] = [
            {
                "name": "bottom_up_alert_hunter",
                "max_tool_calls": 12,
                "max_tokens": 135_000,
                "instruction": (
                    f"Chiến lược NHÁNH A (Bottom-Up Alert Hunter): T3 đã chứng minh vi phạm `{diag.signature}` "
                    f"(quan sát `{obs}`, kỳ vọng `{exp}`). {dir_hint} "
                    f"Hãy dùng `code__grep` tìm trực tiếp lời gọi phát `{obs}` trong mã nguồn chính (loại `tests/`/`examples/` bằng `path`/`glob`), "
                    "đọc gọn 40–60 dòng quanh nhánh lỗi rồi trả `LocationClaim@1` với `REACTION = MISMATCH` trỏ đúng dòng gửi cảnh báo sai/thiếu."
                ),
            },
            {
                "name": "top_down_protocol_tracer",
                "max_tool_calls": 12,
                "max_tokens": 135_000,
                "instruction": (
                    f"Chiến lược NHÁNH B (Top-Down Protocol Tracer): T3 đã chứng minh vi phạm `{diag.signature}`. {dir_hint} "
                    "Hãy bắt đầu từ `locator__suggest` để tìm đúng hàm xử lý tầng giao thức tương ứng với `requirement.structured`, "
                    "đọc gọn 40–60 dòng theo luồng kiểm tra lỗi từ trên xuống (chú ý cả nhánh `default:` hoặc kiểm tra ranh giới bị thiếu `SendAlert`), "
                    "rồi trả `LocationClaim@1` với `REACTION = MISMATCH` trỏ đúng nhánh vi phạm."
                ),
            },
        ]
        if diag.signature == WRONG_ALERT:
            out.append(
                {
                    "name": "error_to_alert_mapper",
                    "max_tool_calls": 11,
                    "max_tokens": 115_000,
                    "instruction": (
                        f"Chiến lược NHÁNH C (Error-to-Alert Mapper Specialist): T3 quan sát cảnh báo sai `{obs}` thay vì `{exp}`. {dir_hint} "
                        "Nhiều thư viện TLS không gọi `SendAlert` ngay tại hàm kiểm tra, mà trả về mã lỗi nội bộ (vd `KEY_SHARE_ERROR`, `MATCH_SUITE_ERROR`, `BUFFER_ERROR`) "
                        "rồi một hàm ánh xạ lỗi→cảnh báo (switch/case lớn trả về mã alert) mới dịch mã lỗi đó thành cảnh báo TLS. "
                        f"Hãy tìm hàm ánh xạ lỗi→cảnh báo đó bằng `code__grep` (`return {obs}` hoặc `case.*ERROR` cùng tệp có nhiều mã alert), "
                        "đọc đúng các `case` liên quan tới `requirement.structured`, rồi trả `LocationClaim@1` với `symbol` là hàm ánh xạ đó và `line_start..line_end` + `REACTION = MISMATCH` trỏ chính xác dòng `case`/`return` gửi sai cảnh báo."
                    ),
                }
            )
        return tuple(out)

    def select_branch(
        self,
        inv: Investigation,
        task: Any,
        candidates: Sequence[tuple[str, BaseModel | None, ToolSession]],
    ) -> tuple[int, dict[str, Any]]:
        """Chấm điểm tất định các nhánh AI Agent: SchemaGate + đối chiếu T3 + phù hợp chiều giao thức & từ khoá yêu cầu."""
        req_id = inv.requirement.requirement_id
        t3s = [e.payload for e in self._rt.store.for_requirement(req_id) if isinstance(e.payload, T3Payload)]
        diag = diagnose(_expected_alert(inv), t3s)
        obs_alerts = {a for a in diag.observed_alerts if a and a != "none"}
        rbs = inv.domain_state.get(RBS_KEY)
        raw_kws = requirement_keywords(rbs) if rbs is not None else ()
        atoms = {
            tok
            for kw in raw_kws
            for tok in re.findall(r"[a-z0-9]+", kw.lower())
            if len(tok) >= 3 and tok not in {"send", "receive", "alert", "close", "valid", "none"}
        }
        trig_args = {str(a).lower() for a in getattr(getattr(rbs, "trigger", None), "args", ())}
        is_server_ch = "client_hello" in trig_args

        best_idx = 0
        best_key: tuple[int, ...] | None = None
        board: list[dict[str, Any]] = []
        for idx, (bname, output, session) in enumerate(candidates):
            if not isinstance(output, LocationClaim):
                board.append({"branch": bname, "accepted": False, "reason": "NO_OUTPUT"})
                continue
            res = self._gate.check_location(
                output, session, run_id=self._rt.run_id, requirement_id=req_id, msg_id="", threshold=_threshold_of(inv)
            )
            sc = score_claim(output, res.errors)
            has_mismatch = int(any(a.value is AspectValue.MISMATCH for a in output.aspects))
            matches_obs = int(
                any(
                    a.aspect is AspectName.REACTION
                    and a.observed is not None
                    and any(o in str(a.observed) for o in obs_alerts)
                    for a in output.aspects
                )
            )
            sym_low = output.symbol.lower()
            note_low = (output.note or "").lower()
            # Phạt nặng nếu yêu cầu phía SERVER (`receive(client_hello)`) nhưng nhánh lại trỏ nhầm hàm phía CLIENT (`ServerHello`).
            wrong_dir = int(is_server_ch and "serverhello" in sym_low and "clienthello" not in sym_low)
            # Thưởng mức phù hợp ngữ nghĩa giữa (symbol + note) và từ khoá RBS hoặc hàm dịch lỗi→cảnh báo.
            kw_hits = sum(1 for tok in atoms if tok in sym_low or tok in note_low)
            is_mapper = int(
                diag.signature == WRONG_ALERT
                and ("translate" in sym_low or ("alert" in sym_low and "send" not in sym_low))
            )
            sem_score = kw_hits + 3 * is_mapper - 5 * wrong_dir

            key: tuple[int, ...] = (
                int(res.accepted),
                -wrong_dir,
                matches_obs,
                has_mismatch,
                is_mapper,
                sem_score,
                *sc.rank_key,
            )
            board.append(
                {
                    "branch": bname,
                    "accepted": res.accepted,
                    "symbol": output.symbol,
                    "file": output.file,
                    "lines": [output.line_start, output.line_end],
                    "matches_obs": bool(matches_obs),
                    "has_mismatch": bool(has_mismatch),
                    "sem_score": sem_score,
                    "wrong_dir": bool(wrong_dir),
                    "errors": list(res.errors),
                }
            )
            if best_key is None or key > best_key:
                best_key = key
                best_idx = idx
        return best_idx, {"winner": candidates[best_idx][0], "branches": board}

    def precheck(self, inv: Investigation, output: BaseModel, session: ToolSession) -> Sequence[str]:
        """Chạy Schema gate (không ghi) khi agent vừa trả kết quả, để agent sửa trong ngân sách (tối đa hai lần)."""
        if not isinstance(output, LocationClaim):
            return ()
        req_id = inv.requirement.requirement_id
        errors = list(
            self._gate.check_location(
                output, session, run_id=self._rt.run_id, requirement_id=req_id, msg_id="", threshold=_threshold_of(inv)
            ).errors
        )
        if not errors and not any(a.value is AspectValue.MISMATCH for a in output.aspects):
            t3s = [e.payload for e in self._rt.store.for_requirement(req_id) if isinstance(e.payload, T3Payload)]
            diag = diagnose(_expected_alert(inv), t3s)
            if diag.signature in (REACTION_ABSENT, WRONG_ALERT, NO_CLOSE):
                errors.append(
                    f"MISMATCH_REQUIRED_ON_VIOLATION: T3 đã chứng minh vi phạm ({diag.signature}); "
                    "hãy đặt khía cạnh sai (vd REACTION) thành MISMATCH với `lines` trỏ đúng dòng gửi cảnh báo sai/thiếu."
                )
        return errors

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

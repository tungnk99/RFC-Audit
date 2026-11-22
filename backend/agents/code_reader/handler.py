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
        """Khi T3 đã chứng minh vi phạm, chạy song song 2 AI Agent chuyên biệt tối ưu theo chữ ký lỗi (tổng ~170k-200k token)."""
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
            "Đặt `call_path: [symbol]` trừ khi đã đọc trực tiếp hàm cha; kiểm tra kỹ tên `file` khớp chính xác với kết quả `code__grep`/`code__read`."
        )
        if diag.signature == WRONG_ALERT:
            return (
                {
                    "name": "bottom_up_alert_hunter",
                    "max_tool_calls": 11,
                    "max_tokens": 110_000,
                    "instruction": (
                        f"Chiến lược NHÁNH A (Bottom-Up Alert Hunter): T3 quan sát cảnh báo sai `{obs}` thay vì `{exp}`. {dir_hint} "
                        f"Hãy dùng `code__grep` tìm trực tiếp lời gọi gửi `{obs}` trong mã nguồn chính (loại `tests/`/`examples/` bằng `path`/`glob`), "
                        "đọc gọn 40–60 dòng quanh nhánh lỗi (nhớ đọc cả các nhánh `if`/`case` phía trên liền kề trong cùng hàm) "
                        "rồi trả `LocationClaim@1` với `REACTION = MISMATCH` trỏ đúng dòng gửi cảnh báo sai."
                    ),
                },
                {
                    "name": "error_to_alert_mapper",
                    "max_tool_calls": 11,
                    "max_tokens": 110_000,
                    "instruction": (
                        f"Chiến lược NHÁNH B (2-Step Error-to-Alert Mapper): T3 quan sát cảnh báo sai `{obs}` thay vì `{exp}`. {dir_hint} "
                        "Thực hiện đúng 2 bước: "
                        "(1) Dùng `code__grep` theo từ khoá của `requirement.structured` (vd `key_share`, `supported_group`, `content_type`, `record`) "
                        "để tìm mã lỗi nội bộ trả về khi kiểm tra thất bại (vd `KEY_SHARE_ERROR`, `MATCH_SUITE_ERROR`, `BUFFER_ERROR`) — "
                        "BỎ QUA các hàm không liên quan tới yêu cầu (như `Resumption`, `SendFatalAlertOnly`, hàm phía client). "
                        f"(2) Dùng `code__grep` tìm chính mã lỗi nội bộ đó (hoặc `return {obs}`) trong hàm có khối `switch`/`case` lớn ánh xạ mã lỗi sang cảnh báo TLS, "
                        "đọc trọn 60–80 dòng của khối `switch` để chọn ĐÚNG `case` tương ứng, rồi trả `LocationClaim@1` với `file`, `symbol`, `line_start..line_end` "
                        "và `REACTION = MISMATCH` trỏ chính xác dòng `case`/`return` gửi sai cảnh báo."
                    ),
                },
            )
        # REACTION_ABSENT hoặc NO_CLOSE: 2 nhánh bổ trợ (nhánh săn kiểm tra sớm / #ifdef [DISABLED] vs nhánh lần từ trên xuống).
        return (
            {
                "name": "early_check_ifdef_hunter",
                "max_tool_calls": 11,
                "max_tokens": 110_000,
                "instruction": (
                    f"Chiến lược NHÁNH A (Early-Check & #ifdef Hunter): T3 chứng minh `{diag.signature}` (SUT KHÔNG phát `{exp}`). {dir_hint} "
                    f"QUAN TRỌNG: một nhánh có `SendAlert({exp})` đang hoạt động (không bị `[DISABLED]`) KHÔNG PHẢI là chỗ lỗi! "
                    "Chỗ lỗi thực sự là một phép kiểm tra sớm hơn nằm phía trên trong cùng hàm (trước đó 40–100 dòng, nơi kiểm tra header/kích thước thô "
                    "và `return` mã lỗi nhưng `SendAlert` đã bị xoá mất hoặc bị tắt `[DISABLED]`). "
                    "BẮT BUỘC chọn dòng `SendAlert` có **số dòng NHỎ NHẤT** trong hàm xử lý, rồi gọi `code__read` với "
                    "`offset = (số dòng nhỏ nhất đó - 100), limit = 100` để đọc ngược lên đoạn phía trên, "
                    "tìm đúng nhánh kiểm tra sớm trả lỗi mà thiếu `SendAlert` (hoặc bị `[DISABLED]`), rồi trả `LocationClaim@1` với `REACTION = MISMATCH` trỏ chính xác dòng đó."
                ),
            },
            {
                "name": "top_down_protocol_tracer",
                "max_tool_calls": 11,
                "max_tokens": 110_000,
                "instruction": (
                    f"Chiến lược NHÁNH B (Top-Down Protocol Tracer): T3 chứng minh `{diag.signature}`. {dir_hint} "
                    "Bắt đầu từ `locator__suggest` để tìm đúng hàm xử lý tầng giao thức tương ứng với `requirement.structured`, "
                    "đọc gọn 50–70 dòng từ điểm phân loại loại bản ghi / kiểm tra ranh giới (chú ý cả nhánh `default:` và các dòng 10–20 dòng phía trên/dưới "
                    "nơi cảnh báo bị thiếu hoặc trả lỗi sớm trước khi gọi `SendAlert`), rồi trả `LocationClaim@1` với `REACTION = MISMATCH`."
                ),
            },
        )

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
            is_specialist = int(bname.startswith("error_to_alert_mapper"))
            sem_score = kw_hits + 3 * is_mapper - 5 * wrong_dir
            # Với REACTION_ABSENT: cùng hàm thì ưu tiên nhánh kiểm tra sớm hơn (số dòng nhỏ hơn) vì lỗi trả sớm nằm trước.
            earlier_bias = -output.line_start if diag.signature == REACTION_ABSENT else 0

            key: tuple[int, ...] = (
                int(res.accepted),
                -wrong_dir,
                matches_obs,
                has_mismatch,
                is_mapper,
                sem_score,
                is_specialist,
                earlier_bias,
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
        # Nếu agent gõ nhầm tên tệp hoặc tên hàm bao quanh (vd ghi `ProcessReply` thay vì `DoProcessReplyEx` cho dòng 25835),
        # bổ sung gợi ý tên tệp / tên hàm chính xác từ chỉ mục để agent tự sửa ngay trong vòng retry.
        index: Any = getattr(getattr(self._rt, "providers", None), "code_index", None)
        if index is not None and "SYMBOL_NOT_IN_INDEX" in errors:
            found = [s.file for s in index.lookup(output.symbol) if s.file != output.file]
            if found:
                errors.append(
                    f"HINT_SYMBOL_FILE: hàm `{output.symbol}` nằm trong tệp `{found[0]}`, không phải `{output.file}`."
                )
        if index is not None and ("LINES_OUTSIDE_SYMBOL" in errors or "SYMBOL_NOT_IN_INDEX" in errors):
            enclosing = index.containing_symbol(output.file, output.line_start)
            if enclosing is not None and enclosing.name != output.symbol:
                errors.append(
                    f"HINT_ENCLOSING_SYMBOL: các dòng {output.line_start}–{output.line_end} trong `{output.file}` "
                    f"thuộc thân hàm `{enclosing.name}` (không phải `{output.symbol}`). "
                    f"Hãy đổi `symbol` và `call_path` sang `{enclosing.name}`."
                )
        # Chặn sớm lỗi nhầm chiều giao thức (vd SUT là SERVER nhận ClientHello nhưng agent trỏ vào DoServerHello của client).
        rbs = inv.domain_state.get(RBS_KEY)
        trig_args = {str(a).lower() for a in getattr(getattr(rbs, "trigger", None), "args", ())}
        sym_low = output.symbol.lower()
        if not errors and "client_hello" in trig_args and "serverhello" in sym_low and "clienthello" not in sym_low:
            errors.append(
                f"WRONG_PROTOCOL_DIRECTION: yêu cầu là phía SERVER nhận `client_hello`, nhưng `{output.symbol}` là hàm phía CLIENT. "
                "Hãy tìm đúng hàm xử lý ClientHello / extension / ánh xạ lỗi→cảnh báo phía server."
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

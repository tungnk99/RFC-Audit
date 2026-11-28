"""Handler của Code Reader: LocationClaim → Schema gate → T1 → liên kết độ phủ → quét nhánh nghi vấn (T2).

Agent không ghi bằng chứng; cổng mới ghi. Bộ quét nhánh nghi vấn chạy sau khi T1 được nhận, trên đúng các hàm của đường xử lý."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from typing import Any, cast

from pydantic import BaseModel

from agents.code_reader.schema import LocationClaim
from agents.common import RBS_KEY
from agents.locator.service import requirement_keywords
from rfcv.core.execution_loop import Investigation
from rfcv.core.ifc import Labeled, TrustLabel
from rfcv.domains.rfc_protocol.coverage_linker import (
    LineCoverage,
    link_pending,
    ochiai_scores,
    parse_lcov,
    repo_rel_path,
)
from rfcv.domains.rfc_protocol.coverage_linker import (
    link as link_cov,
)
from rfcv.domains.rfc_protocol.diagnosis import (
    NO_CLOSE,
    NONE,
    REACTION_ABSENT,
    WRONG_ALERT,
    candidate_patterns,
    diagnose,
)
from rfcv.domains.rfc_protocol.multi_hypothesis import score_claim
from rfcv.domains.rfc_protocol.payloads import (
    AspectName,
    AspectValue,
    Outcome,
    Producer,
    T1Payload,
    T2SuspiciousPayload,
    T3Payload,
    Tier,
)
from rfcv.domains.rfc_protocol.schema_gate import SchemaGate
from rfcv.domains.rfc_protocol.suspicious import canonical_values, scan_symbols
from rfcv.evidence.models import EvidenceDraft
from rfcv.gates.tool_gateway import ToolSession, ToolSpec


def _threshold_of(inv: Investigation) -> int | None:
    """Giá trị số trong `where` của RBS (ví dụ 4096 của `frame.length > 4096`), nếu yêu cầu có."""
    rbs: Any = inv.context.get("requirement.rbs")
    where: Any = rbs.value.get("where") if rbs is not None and isinstance(rbs.value, dict) else None  # type: ignore[union-attr]
    value: Any = where.get("value") if isinstance(where, dict) else None  # type: ignore[union-attr]
    return value if isinstance(value, int) and not isinstance(value, bool) else None


_MACRO = re.compile(r"\b[A-Z][A-Z0-9_]{3,}\b")
_ROW = re.compile(r"^[^\s:]+?[:-]\d+[:-](?P<text>.*)$")  # dòng kết quả grep: tệp:dòng:mã hoặc tệp-dòng-mã
_GUARD = re.compile(r"^\s*#\s*(?:ifdef|ifndef|if|elif)\b(.*)$")
MAX_GUARD_MACROS = 6


_REACTION_CALLS = frozenset(
    {
        "send_alert",
        "send_goaway",
        "send_rst_stream",
        "respond",
        "send_disconnect",
        "send_connection_close",
        "send_error",
    }
)


def _expected_alert(inv: Investigation) -> str | None:
    """Mã phản ứng/cảnh báo/lỗi mà RBS đòi (đối số đầu tiên của lời gọi phản ứng trong `expect`, hỗ trợ mọi giao thức)."""
    rbs: Any = inv.domain_state.get(RBS_KEY)
    if rbs is None or not rbs.expect:
        return None
    for call in rbs.expect:
        if call.args and (call.name in _REACTION_CALLS or call.name.startswith(("send_", "respond"))):
            return str(call.args[0])
    return None


_CONSENSUS_LINE_SLACK = 10
# Gói đối chất mang nhãn DERIVED: chuỗi do mô hình vùng cách ly nộp chỉ qua khi là một token không khoảng trắng.
_PACKET_TOKEN = re.compile(r"[A-Za-z0-9_.:#=+\-/(),~*]{1,200}")


def _safe_token(value: str) -> str | None:
    return value if _PACKET_TOKEN.fullmatch(value) else None


def _candidate_packet(output: BaseModel | None) -> dict[str, Any]:
    """Phần cấu trúc của một ứng viên cho trọng tài: không `note`, `unexplored` hay chuỗi văn xuôi (bị thay bằng None)."""
    if not isinstance(output, LocationClaim):
        return {"status": "NO_OUTPUT"}
    return {
        "file": _safe_token(output.file),
        "symbol": _safe_token(output.symbol),
        "line_start": output.line_start,
        "line_end": output.line_end,
        "finding": output.finding.value,
        "aspects": [
            {
                "aspect": a.aspect.value,
                "value": a.value.value,
                "observed": _safe_token(a.observed) if isinstance(a.observed, str) else a.observed,
                "lines": list(a.lines),
            }
            for a in output.aspects
        ],
    }


def _claims_agree(a: BaseModel | None, b: BaseModel | None) -> bool:
    """Đồng thuận: cùng tệp và hai khoảng dòng chồng/cách nhau không quá 10 dòng.

    Cùng tên hàm chưa đủ: trong một hàm dài, hai nhận định ở xa nhau là hai giả thuyết khác nhau, để trọng tài phân xử."""
    if not isinstance(a, LocationClaim) or not isinstance(b, LocationClaim) or a.file != b.file:
        return False
    return a.line_start <= b.line_end + _CONSENSUS_LINE_SLACK and b.line_start <= a.line_end + _CONSENSUS_LINE_SLACK


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
        if os.environ.get("RFCV_ABLATION", "").strip().lower() == "no_diagnosis":
            return {}, frozenset()
        req_id = inv.requirement.requirement_id
        t3s = [e.payload for e in self._rt.store.for_requirement(req_id) if isinstance(e.payload, T3Payload)]
        expected = _expected_alert(inv)
        diagnosis = diagnose(expected, t3s)
        context: dict[str, Labeled[Any]] = {}
        shown: frozenset[tuple[str, int]] = frozenset()
        if diagnosis.signature == NONE:
            return context, shown
        context["behavior.diagnosis"] = Labeled(diagnosis.to_json(), TrustLabel.DERIVED)
        fail_covs, pass_covs = self._load_coverages(t3s)
        if fail_covs:
            hotspots = ochiai_scores(fail_covs, pass_covs, top_k=12)
            if hotspots:
                ci: Any = getattr(getattr(self._rt, "providers", None), "code_index", None)
                known_files: set[str] = {str(f) for f in ci.files()} if ci is not None else set()
                items_out: list[dict[str, Any]] = []
                for h in hotspots:
                    rel = repo_rel_path(h.file, known_files)
                    sym = ci.containing_symbol(rel, h.line) if (ci is not None and rel in known_files) else None
                    entry: dict[str, Any] = {
                        "file": rel,
                        "line": h.line,
                        "ochiai": h.score,
                        "fail_hits": h.fail_hits,
                        "pass_hits": h.pass_hits,
                    }
                    if sym is not None:
                        entry["symbol"] = sym.name
                    items_out.append(entry)
                context["code.coverage_hotspots"] = Labeled(items_out, TrustLabel.DERIVED)
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

    def _load_coverages(self, t3s: Sequence[T3Payload]) -> tuple[list[LineCoverage], list[LineCoverage]]:
        """Nạp LCOV thực thi từ ArtifactStore (nếu image SUT bật đo độ phủ, gen-43/44)."""
        artifacts: Any = getattr(self._rt, "artifacts", None)
        if artifacts is None:
            return [], []
        fail_covs: list[LineCoverage] = []
        pass_covs: list[LineCoverage] = []
        for t3 in t3s:
            lcov_id = t3.artifacts.get("lcov")
            if not lcov_id:
                continue
            try:
                blob = artifacts.get(lcov_id)
                cov = parse_lcov(blob.decode("utf-8", "replace"))
            except Exception:
                continue
            if t3.outcome is Outcome.FAIL:
                fail_covs.append(cov)
            elif t3.outcome is Outcome.PASS:
                pass_covs.append(cov)
        return fail_covs, pass_covs

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

    def peer_review_config(self, inv: Investigation, task: Any) -> dict[str, Any] | None:
        """Kích hoạt mô hình tổ chức Phản biện ngang hàng (gen-46 / L5 ADD_ORG_PATTERN) khi `RFCV_ORG_MODE=peer_review`.

        Mô phỏng quy trình kỹ thuật phần mềm thực tế:
        1) Investigator nộp bản nháp `LocationClaim` đầu tiên;
        2) Skeptic Reviewer nhận bản nháp + tín hiệu kiểm toán tất định (obs_in_source, executed_in_fail, errors)
           để soi lỗi và xác nhận hoặc hiệu đính sang vị trí nguyên nhân gốc chính xác hơn.
        """
        if os.environ.get("RFCV_ORG_MODE", "").strip().lower() != "peer_review":
            return None
        specs = list(self.branches(inv, task))
        if len(specs) < 2:
            return None
        inv_spec = {**specs[0], "name": "investigator"}
        alt_hint = str(specs[1].get("instruction", ""))

        def _build_reviewer(
            _inv: Investigation,
            _task: Any,
            draft_output: BaseModel | None,
            inv_audit: Mapping[str, Any],
        ) -> dict[str, Any]:
            draft_info: dict[str, Any]
            if isinstance(draft_output, LocationClaim):
                draft_info = {
                    "file": draft_output.file,
                    "symbol": draft_output.symbol,
                    "line_start": draft_output.line_start,
                    "line_end": draft_output.line_end,
                    "finding": draft_output.finding.value,
                    "aspects": [a.model_dump(mode="json") for a in draft_output.aspects],
                    "call_path": list(draft_output.call_path),
                }
            else:
                draft_info = {"status": "NO_OUTPUT"}
            branches_raw = inv_audit.get("branches")
            audit_flags: dict[str, Any] = {}
            if isinstance(branches_raw, list) and branches_raw:
                first_raw = cast("Any", branches_raw)[0]
                if isinstance(first_raw, Mapping):
                    audit_flags = dict(cast("Mapping[str, Any]", first_raw))
            return {
                "name": "skeptic_reviewer",
                "max_tool_calls": 10,
                "max_tokens": 100_000,
                "extra_focus": {
                    "peer_review_draft": draft_info,
                    "peer_review_audit_flags": audit_flags,
                },
                "instruction": (
                    "Vai trò PHẢN BIỆN NGANG HÀNG HOÀI NGHI (Skeptic Peer Reviewer): đồng nghiệp (Investigator) vừa nộp "
                    "bản nháp `peer_review_draft` kèm cờ kiểm toán `peer_review_audit_flags`. "
                    "Nhiệm vụ của bạn là phản biện nghiêm khắc: "
                    "(1) Đọc kỹ các dòng trong `peer_review_draft` bằng `code__read` (nếu có); "
                    "(2) Kiểm tra xem bản nháp có bỏ sót mã lỗi/cảnh báo quan sát được trong mã (`obs_in_source=false`), "
                    "chọn nhầm nhánh không chạy (`executed_in_fail=false`), nhầm chiều/giai đoạn, hoặc dừng ở hàm xử lý muộn thay vì điểm gốc; "
                    "(3) Đối chiếu theo góc nhìn bổ trợ: "
                    + alt_hint
                    + " (4) Nếu bản nháp đã hoàn toàn chính xác, xác nhận bằng `LocationClaim@1` tương ứng; "
                    "nếu phát hiện lỗi hoặc vị trí chính xác hơn, nộp `LocationClaim@1` đã hiệu đính."
                ),
            }

        return {"investigator": inv_spec, "build_reviewer": _build_reviewer}

    def debate_config(self, inv: Investigation, task: Any) -> dict[str, Any] | None:
        """Mô hình tổ chức Tranh biện (gen-49), mặc định từ gen-52: bật khi `RFCV_ORG_MODE` để trống hoặc bằng `debate`.

        Giá trị khác tắt Tranh biện (`tournament`, `peer_review` dùng để đối chứng). Khi `branches` không đưa ra đủ hai
        chuyên gia (kể cả do `RFCV_ABLATION`), trả None.

        Hai chuyên gia của `branches` điều tra độc lập (không neo vào nhau). Chỉ khi bất đồng mới gọi trọng tài; trọng tài
        thấy hai ứng viên ở dạng cấu trúc (không có `note` hay văn xuôi tự do) và phải tự đọc lại cả hai vị trí mã.
        """
        if os.environ.get("RFCV_ORG_MODE", "").strip().lower() not in ("", "debate"):
            return None
        specs = list(self.branches(inv, task))
        if len(specs) < 2:
            return None

        def _build_adjudicator(
            _inv: Investigation,
            _task: Any,
            results: Sequence[tuple[str, BaseModel | None]],
            pre_audit: Mapping[str, Any],
        ) -> dict[str, Any]:
            req_id = _inv.requirement.requirement_id
            t3s = [e.payload for e in self._rt.store.for_requirement(req_id) if isinstance(e.payload, T3Payload)]
            diag = diagnose(_expected_alert(_inv), t3s)
            # `select_branch` gán mặc định khi không đo được; trọng tài phải thấy null thay vì tưởng đó là kết quả đo.
            has_cov = bool(self._load_coverages(t3s)[0])
            has_source_check = getattr(getattr(self._rt, "providers", None), "code_index", None) is not None and any(
                a and a != "none" and a != _expected_alert(_inv) for a in diag.observed_alerts
            )
            raw_board = pre_audit.get("branches")
            board = cast("list[Any]", raw_board) if isinstance(raw_board, list) else []
            candidates: list[dict[str, Any]] = []
            flags: list[dict[str, Any]] = []
            for idx, (label, (bname, output)) in enumerate(zip(("A", "B"), results, strict=False)):
                candidates.append({"candidate": label, "branch": bname, **_candidate_packet(output)})
                row: Mapping[str, Any] = (
                    cast("Mapping[str, Any]", board[idx])
                    if idx < len(board) and isinstance(board[idx], Mapping)
                    else {}
                )
                errors = [str(e).split(":", 1)[0] for e in cast("Sequence[Any]", row.get("errors") or ())]
                flags.append(
                    {
                        "candidate": label,
                        "accepted": row.get("accepted"),
                        "obs_in_source": row.get("obs_in_source") if has_source_check else None,
                        "executed_in_fail": row.get("executed_in_fail") if has_cov else None,
                        "wrong_dir": row.get("wrong_dir"),
                        "wrong_stage": row.get("wrong_stage"),
                        "errors": [t for e in errors if (t := _safe_token(e)) is not None],
                    }
                )
            premise = (
                "hai điều tra viên làm việc độc lập đã chỉ cùng một vị trí NHƯNG kiểm toán tất định gắn cờ vị trí đó, "
                "nên đồng thuận này KHÔNG được chấp nhận. "
                if pre_audit.get("consensus_vetoed")
                else "hai điều tra viên làm việc độc lập đã KHÔNG đồng thuận. "
            )
            return {
                "name": "adjudicator",
                "max_tool_calls": 8,
                "max_tokens": 90_000,
                "extra_focus": {"debate_candidates": candidates, "debate_audit_flags": flags},
                "instruction": (
                    "Vai trò TRỌNG TÀI ĐỐI CHẤT (Blind Adjudicator): " + premise + "`debate_candidates` là hai ứng viên A và B, `debate_audit_flags` là cờ kiểm toán tất định của từng ứng viên "
                    "(giá trị null nghĩa là không đo được, không phải bằng chứng bác bỏ; `wrong_dir=true`: nghi hàm thuộc "
                    "chiều giao thức đối diện; `wrong_stage=true`: nghi hàm chỉ chạy ở giai đoạn muộn hơn yêu cầu). "
                    "Không mặc định ứng viên nào đúng. "
                    "(1) BẮT BUỘC dùng `code__read` đọc CẢ HAI vị trí mã đang tranh chấp (ứng viên có `status: NO_OUTPUT` thì bỏ qua); "
                    "nếu có LCOV, dùng `coverage__hotspots` để xem vị trí nào thực sự chạy trong ca FAIL; "
                    "(2) Đối chất: kiểm `obs_in_source`, `executed_in_fail`, `errors`, và phân biệt phép kiểm tra sớm với phép kiểm tra muộn "
                    "trên đường xử lý, để xác định vị trí nào là NGUYÊN NHÂN GỐC gây ra hành vi T3 quan sát được; "
                    "(3) Nộp `LocationClaim@1` cuối cùng: chọn A, chọn B, hoặc tổng hợp vị trí đúng hơn nếu cả hai sai. "
                    "Chỉ dẫn những dòng bạn đã đọc trong phiên này."
                ),
            }

        return {"investigators": specs[:2], "claims_agree": _claims_agree, "build_adjudicator": _build_adjudicator}

    def branches(self, inv: Investigation, task: Any) -> Sequence[dict[str, Any]]:
        """Khi T3 đã chứng minh vi phạm, chạy song song 2 AI Agent chuyên biệt tối ưu theo chữ ký lỗi (tổng ~170k-200k token)."""
        if str(getattr(task, "task_type", "")) != "LOCATE":
            return ()
        if os.environ.get("RFCV_ABLATION", "").strip().lower() in ("single_branch", "no_diagnosis"):
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
            "Chú ý chiều giao thức: SUT là phía nhận `" + trig + "` — "
            "TUYỆT ĐỐI KHÔNG chọn hàm thuộc vai trò đối diện (vd phía gửi/client khi SUT đang ở vai trò nhận/server). "
            "Đặt `call_path: [symbol]` trừ khi đã đọc trực tiếp hàm cha; kiểm tra kỹ tên `file` khớp chính xác với kết quả `code__grep`/`code__read`."
        )
        chain_hint = (
            " Khi nghi ngờ điều kiện kiểm tra và điểm phát phản ứng nằm ở hai hàm khác nhau, gọi ngay "
            '`code__call_chain(symbol=..., direction="both", depth=2, filter_identifier=...)` '
            "để truy vết chuỗi gọi và xác nhận `call_path`."
        )
        if diag.signature == WRONG_ALERT:
            obs_pat = "|".join(re.escape(a) for a in diag.observed_alerts if a and a != "none") or re.escape(obs)
            return (
                {
                    "name": "bottom_up_alert_hunter",
                    "max_tool_calls": 11,
                    "max_tokens": 130_000,
                    "instruction": (
                        f"Chiến lược NHÁNH A (Agentic Reaction-Site Hunter): T3 quan sát mã phản ứng sai `{obs}` thay vì `{exp}`. {dir_hint} "
                        f'BƯỚC 1: Gọi ngay công cụ `code__find_alert_sites(alert="{obs}", keywords=[...])` (truyền các từ khoá từ `requirement.structured`) '
                        "để quét & xếp hạng toàn bộ điểm phát mã lỗi/phản ứng sai trên toàn kho mã (không bị cắt cụt trên kho mã lớn đa tệp). "
                        "BƯỚC 2: Kiểm tra top ứng viên `#1..#8` (đọc thêm 40–60 dòng quanh ứng viên khớp yêu cầu bằng `code__read` nếu cần xác nhận điều kiện `if`/`switch`), "
                        f"KHÔNG dừng ở nhánh không phát `{obs}`. Trả `LocationClaim@1` với `REACTION = MISMATCH` và `observed` khớp mã lỗi sai."
                    ),
                },
                {
                    "name": "error_to_alert_mapper",
                    "max_tool_calls": 11,
                    "max_tokens": 130_000,
                    "instruction": (
                        f"Chiến lược NHÁNH B (2-Step Error-to-Reaction Mapper): T3 quan sát mã phản ứng sai `{obs}` thay vì `{exp}`. {dir_hint} "
                        "Thực hiện đúng 2 bước (dùng `head_limit=20` cho mỗi `code__grep` để không tràn ngữ cảnh): "
                        "(1) Dùng `code__grep` theo từ khoá của `requirement.structured` trong các thư mục mã nguồn giao thức (bỏ qua `tests/`, `examples/`, hàm thuộc chiều đối diện) "
                        f"để tìm đúng nhánh gọi trực tiếp hàm phát lỗi/phản ứng với `(?i){obs}` HOẶC trả mã lỗi nội bộ (`*_ERROR`, `*_ERR`, âm). "
                        f"(2) Nếu hàm kiểm tra chỉ trả mã lỗi nội bộ, dùng `code__grep` tìm mã lỗi đó hoặc `(?i)return\\s+.*({obs_pat})` "
                        "trong hàm `switch`/`case` ánh xạ mã lỗi nội bộ sang mã phản ứng giao thức, đọc trọn 60–80 dòng khối `switch` để chọn đúng `case`, "
                        "rồi trả `LocationClaim@1` với `REACTION = MISMATCH` và `observed` là mã phản ứng sai." + chain_hint
                    ),
                },
            )
        # REACTION_ABSENT hoặc NO_CLOSE: 2 nhánh bổ trợ (nhánh săn kiểm tra sớm / #ifdef [DISABLED] vs nhánh lần từ trên xuống).
        return (
            {
                "name": "early_check_ifdef_hunter",
                "max_tool_calls": 11,
                "max_tokens": 130_000,
                "instruction": (
                    f"Chiến lược NHÁNH A (Early-Check & #ifdef Hunter): T3 chứng minh `{diag.signature}` (SUT KHÔNG phát `{exp}`). {dir_hint} "
                    f"QUAN TRỌNG: một nhánh có lời gọi phát `{exp}` đang hoạt động (không bị `[DISABLED]`) KHÔNG PHẢI là chỗ lỗi! "
                    "Khi yêu cầu kiểm tra bản tin/bản ghi gửi ở giai đoạn khởi đầu (`state == initial`, chưa hoàn tất bắt tay/mã hoá), "
                    "TUYỆT ĐỐI KHÔNG dừng ở hàm chỉ chạy ở giai đoạn sau bắt tay hoặc sau mã hoá — hãy đọc trực tiếp hàm phân tách/đọc lớp khung/bản ghi ban đầu "
                    "để tìm nhánh xử lý bị xoá mất lời gọi phản ứng hoặc trả lỗi sớm! "
                    "BẮT BUỘC dùng `code__find_alert_sites` (hoặc `code__grep` `(?i)"
                    + re.escape(exp)
                    + "`) tìm vị trí phát mã phản ứng có số dòng NHỎ NHẤT trong hàm xử lý, "
                    "rồi gọi `code__read` với `offset = (số dòng nhỏ nhất đó - 100), limit = 100` để đọc ngược lên đoạn phía trên, "
                    "tìm đúng nhánh kiểm tra sớm trả lỗi mà thiếu phản ứng (hoặc bị `[DISABLED]`), rồi trả `LocationClaim@1` với `REACTION = MISMATCH`."
                ),
            },
            {
                "name": "top_down_protocol_tracer",
                "max_tool_calls": 11,
                "max_tokens": 110_000,
                "instruction": (
                    f"Chiến lược NHÁNH B (Top-Down Protocol Tracer): T3 chứng minh `{diag.signature}`. {dir_hint} "
                    "Bắt đầu từ `locator__suggest` để tìm đúng hàm xử lý tầng giao thức tương ứng với `requirement.structured`, "
                    "đọc gọn 50–70 dòng từ điểm phân loại loại bản tin / kiểm tra ranh giới (chú ý cả nhánh `default:` và các dòng 10–20 dòng phía trên/dưới "
                    "nơi phản ứng bị thiếu hoặc trả lỗi sớm trước khi gọi hàm gửi lỗi), rồi trả `LocationClaim@1` với `REACTION = MISMATCH`."
                    + chain_hint
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

        index: Any = getattr(getattr(self._rt, "providers", None), "code_index", None)
        fail_covs, _ = self._load_coverages(t3s)
        wrong_obs = [a for a in diag.observed_alerts if a and a != "none" and a != _expected_alert(inv)]
        checks = [
            self._gate.check_location(
                out_c, sess_c, run_id=self._rt.run_id, requirement_id=req_id, msg_id="", threshold=_threshold_of(inv)
            )
            if isinstance(out_c, LocationClaim)
            else None
            for _, out_c, sess_c in candidates
        ]
        # Chỉ đếm nhận định đã qua cổng: một nhánh hỏng thêm vào không được làm đổi thứ hạng giữa các nhánh hợp lệ.
        fn_counts: dict[tuple[str, str], int] = {}
        for (_, out_c, _), res_c in zip(candidates, checks, strict=True):
            if isinstance(out_c, LocationClaim) and res_c is not None and res_c.accepted:
                k = (out_c.file, out_c.symbol)
                fn_counts[k] = fn_counts.get(k, 0) + 1

        best_idx = 0
        best_key: tuple[int, ...] | None = None
        board: list[dict[str, Any]] = []
        for idx, ((bname, output, _), res) in enumerate(zip(candidates, checks, strict=True)):
            if not isinstance(output, LocationClaim) or res is None:
                board.append({"branch": bname, "accepted": False, "reason": "NO_OUTPUT"})
                continue
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
            # Kiểm chứng tất định: các dòng nguồn mà agent nộp có THỰC SỰ chứa tên cảnh báo sai T3 quan sát không
            # (chặn tình huống agent điền `observed: decode_error` cho một nhánh thực tế gửi `unexpected_message`).
            obs_in_source = 0
            if index is not None and wrong_obs:
                src_blob = "\n".join(index.lines(output.file, output.line_start, output.line_end)).lower()
                obs_in_source = int(any(o.lower() in src_blob for o in wrong_obs))
            # gen-44 (SBFL / Causal Coverage): nếu có LCOV ca FAIL, ưu tiên tuyệt đối nhánh có dòng thực sự chạy.
            executed_in_fail = 1
            if fail_covs:
                executed_in_fail = int(
                    any(
                        any(output.line_start <= ln <= output.line_end for ln in cov.executed(output.file))
                        for cov in fail_covs
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
            # Chỉ ưu tiên tiebreaker cho error_to_alert_mapper khi nó thực sự ở hàm ánh xạ cảnh báo (tránh đè kết quả
            # từ code__find_alert_sites của bottom_up_alert_hunter ở các ca rec_layer như OU2).
            is_specialist = int(bname.startswith("error_to_alert_mapper") and bool(is_mapper))
            # Với bản ghi gửi rõ lúc mới nối (trạng thái `initial`), phạt hàm chỉ chạy ở giai đoạn sau mã hoá / sau bắt tay.
            rbs_state = str(getattr(rbs, "state", "")).lower()
            where_field = str(getattr(getattr(rbs, "where", None), "field", "")).lower()
            variant_fields = {str(getattr(v, "field", "")).lower() for v in getattr(rbs, "variants", ())}
            is_plaintext_ct = (
                rbs_state == "initial"
                and (where_field == "record.content_type" or "record.content_type" in variant_fields)
            ) or ("content" in atoms and "type" in atoms)
            is_post_enc_header = (
                "validate" in sym_low and "header" in sym_low and any(k in sym_low for k in ("13", "enc", "cipher"))
            ) or "post_handshake" in sym_low
            enc_only_penalty = int(is_plaintext_ct and is_post_enc_header)
            sem_score = kw_hits + 3 * is_mapper - 5 * wrong_dir - 2 * enc_only_penalty
            # Cùng một (file, symbol) thì nhánh kiểm tra sớm hơn (số dòng nhỏ hơn) thực thi trước trong luồng C từ trên xuống.
            same_fn = fn_counts.get((output.file, output.symbol), 0) > 1
            earlier_bias = -output.line_start if (same_fn or diag.signature == REACTION_ABSENT) else 0

            key: tuple[int, ...] = (
                int(res.accepted),
                executed_in_fail,
                -wrong_dir,
                -enc_only_penalty,
                obs_in_source,
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
                    "executed_in_fail": bool(executed_in_fail),
                    "symbol": output.symbol,
                    "file": output.file,
                    "lines": [output.line_start, output.line_end],
                    "obs_in_source": bool(obs_in_source),
                    "matches_obs": bool(matches_obs),
                    "has_mismatch": bool(has_mismatch),
                    "sem_score": sem_score,
                    "wrong_dir": bool(wrong_dir),
                    "wrong_stage": bool(enc_only_penalty),
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
        # Nếu agent gõ nhầm tên tệp hoặc tên hàm bao quanh,
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
        if "THRESHOLD_EQUALS_EXPECTED" in errors:
            errors.append(
                "HINT_THRESHOLD_EQUALS_EXPECTED: giá trị `observed` ở khía cạnh `THRESHOLD` đang bằng đúng ngưỡng yêu cầu nên không thể đặt `MISMATCH`. "
                "Nếu phép kiểm tra đã bị xoá hoặc không có hằng ngưỡng sai rõ ràng, hãy đặt `THRESHOLD` thành `UNCLEAR` (`observed: null`) "
                "và đặt `CONDITION` hoặc `REACTION` thành `MISMATCH`."
            )
        # Chặn sớm lỗi nhầm chiều giao thức (vai trò nhận/server nhưng trỏ nhầm hàm phía gửi/client)
        # hoặc nhầm giai đoạn bản ghi (trạng thái `initial` gửi rõ nhưng trỏ vào hàm kiểm tra header sau mã hoá).
        rbs = inv.domain_state.get(RBS_KEY)
        trig_args = {str(a).lower() for a in getattr(getattr(rbs, "trigger", None), "args", ())}
        rbs_state = str(getattr(rbs, "state", "")).lower()
        where_field = str(getattr(getattr(rbs, "where", None), "field", "")).lower()
        variant_fields = {str(getattr(v, "field", "")).lower() for v in getattr(rbs, "variants", ())}
        is_plaintext_record = rbs_state == "initial" and (
            where_field == "record.content_type" or "record.content_type" in variant_fields
        )
        sym_low = output.symbol.lower()
        if not errors and "client_hello" in trig_args and "serverhello" in sym_low and "clienthello" not in sym_low:
            errors.append(
                f"WRONG_PROTOCOL_DIRECTION: yêu cầu thuộc vai trò nhận thông điệp phía client, nhưng `{output.symbol}` thuộc phía đối diện. "
                "Hãy tìm đúng hàm xử lý đầu vào / mở rộng / ánh xạ lỗi→phản ứng phía máy chủ."
            )
        is_post_enc_header = (
            "validate" in sym_low and "header" in sym_low and any(k in sym_low for k in ("13", "enc", "cipher"))
        ) or "post_handshake" in sym_low
        if not errors and is_plaintext_record and is_post_enc_header:
            errors.append(
                f"WRONG_RECORD_STAGE: yêu cầu ở trạng thái `initial` gửi bản ghi rõ (chưa mã hoá), "
                f"còn `{output.symbol}` chỉ chạy cho giai đoạn đã mã hoá/sau bắt tay. "
                "Hãy gọi `code__find_alert_sites` tìm hàm đọc bản ghi rõ ở lớp phân tách bản ghi ban đầu. "
                f'Có thể gọi `code__call_chain(symbol="{output.symbol}", direction="callers", depth=2)` '
                "để truy ngược lên hàm vào/hàm kiểm tra thật sự."
            )
        if not errors:
            t3s = [e.payload for e in self._rt.store.for_requirement(req_id) if isinstance(e.payload, T3Payload)]
            exp_alert = _expected_alert(inv)
            diag = diagnose(exp_alert, t3s)
            fail_covs, _ = self._load_coverages(t3s)
            if fail_covs:
                t1_probe = T1Payload(
                    file=output.file,
                    symbol=output.symbol,
                    line_start=output.line_start,
                    line_end=output.line_end,
                    finding=output.finding,
                    aspects=(),
                    call_path=tuple(output.call_path),
                )
                if not any(link_cov("_probe", t1_probe, cov).linked for cov in fail_covs):
                    errors.append(
                        f"UNEXECUTED_SITE: các dòng {output.line_start}–{output.line_end} trong `{output.file}` "
                        f"(`{output.symbol}`) KHÔNG chạy trong ca kiểm thử FAIL (độ phủ LCOV = 0). "
                        "Hãy gọi `coverage__hotspots` (hoặc xem `code.coverage_hotspots`) để định vị đúng hàm thực sự đã chạy trên đường dẫn lỗi."
                    )
            if not any(a.value is AspectValue.MISMATCH for a in output.aspects):
                if diag.signature in (REACTION_ABSENT, WRONG_ALERT, NO_CLOSE):
                    errors.append(
                        f"MISMATCH_REQUIRED_ON_VIOLATION: T3 đã chứng minh vi phạm ({diag.signature}); "
                        "hãy đặt khía cạnh sai (vd REACTION) thành MISMATCH với `lines` trỏ đúng dòng gửi cảnh báo sai/thiếu."
                    )
            elif diag.signature == WRONG_ALERT:
                wrong_obs = [a for a in diag.observed_alerts if a and a != "none" and a != exp_alert]
                if wrong_obs and not any(
                    a.aspect is AspectName.REACTION
                    and a.observed is not None
                    and any(o in str(a.observed) for o in wrong_obs)
                    for a in output.aspects
                ):
                    errors.append(
                        f"WRONG_OBSERVED_ALERT: T3 quan sát cảnh báo sai là `{', '.join(wrong_obs)}`, "
                        "nhưng `REACTION.observed` bạn nộp không khớp. Nhánh vừa đọc KHÔNG PHẢI là nhánh thực thi khi lỗi — "
                        f"hãy dùng `code__grep` tìm đúng dòng thực sự phát `(?i)({'|'.join(wrong_obs)})` trong tệp/hàm xử lý. "
                        f'Có thể gọi `code__call_chain(symbol="{output.symbol}", direction="callers", depth=2)` '
                        "để truy ngược lên hàm vào/hàm kiểm tra thật sự."
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
        self._post_location(inv, output, session)
        self._remember_location(inv, output, session)
        return (
            1 + link_pending(self._rt.store, self._rt.artifacts, self._rt.run_id, req_id) + self._scan(output, req_id)
        )

    def _post_location(self, inv: Investigation, claim: LocationClaim, session: ToolSession) -> None:
        """Đăng vị trí đã qua Schema gate lên war-room; chỉ trường cấu trúc, không kèm `note` tự do của agent."""
        entry = inv.blackboard.post(
            "code_reader",
            "location_hypothesis",
            file=claim.file,
            symbol=claim.symbol,
            line=claim.line_start,
            status="verified",
            note=f"T1 accepted {claim.line_start}-{claim.line_end}",
        )
        if entry is None:
            return
        self._rt.trace.append(
            self._rt.run_id,
            "blackboard_post",
            {"entries": [entry.model_dump(mode="json", exclude_none=True)]},
            role=session.role,
            requirement_id=inv.requirement.requirement_id,
        )

    def _remember_location(self, inv: Investigation, claim: LocationClaim, session: ToolSession) -> None:
        """Ghi vị trí đã qua Schema gate VÀ sạch cờ kiểm toán vào bộ nhớ xuyên yêu cầu (nếu hub có gắn); không kèm
        `note` hay văn xuôi. Qua cổng mới chỉ chứng minh dòng dẫn là có thật: vị trí bị cờ chiều/giai đoạn hoặc không chạy
        trong ca FAIL mà thành mốc sẽ dẫn lạc các yêu cầu sau (gen-55)."""
        mem: Any = inv.domain_state.get("_episodic_memory")
        if mem is None:
            return
        _, audit = self.select_branch(inv, None, [("final", claim, session)])
        row: Mapping[str, Any] = audit["branches"][0]
        reasons = [flag for flag in ("wrong_dir", "wrong_stage") if row.get(flag) is True]
        if row.get("executed_in_fail") is False:
            reasons.append("not_executed_in_fail")
        if reasons:
            self._rt.trace.append(
                self._rt.run_id,
                "episodic_memory_skipped",
                {
                    "recorded": False,
                    "file": claim.file,
                    "symbol": claim.symbol,
                    "line_start": claim.line_start,
                    "line_end": claim.line_end,
                    "reasons": reasons,
                },
                role=session.role,
                requirement_id=inv.requirement.requirement_id,
            )
            return
        landmark = mem.record(
            claim.file,
            claim.symbol,
            claim.line_start,
            claim.line_end,
            rtype=inv.requirement.rtype,
            finding=claim.finding.value,
        )
        if landmark is None:
            return
        self._rt.trace.append(
            self._rt.run_id,
            "episodic_memory_record",
            landmark.model_dump(mode="json"),
            role=session.role,
            requirement_id=inv.requirement.requirement_id,
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

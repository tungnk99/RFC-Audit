"""Cổng kiểm tra và đối chiếu cho đề xuất RBS của RFC Analyst (chạy trước vòng điều tra).

Agent chỉ đề xuất; ở đây các hàm tất định (không LLM) quyết định đề xuất có dùng được không:
cú pháp (`parse_rbs`), từ vựng adapter và biên dịch oracle (`compile_oracle`), định danh câu có thật trong RFC và modal khớp câu gốc.
Sau đó đối chiếu với RBS người đã duyệt cho cùng câu (`reconcile`). Kết quả chỉ để quan sát: không đổi RBS dùng cho kết luận.
"""

from __future__ import annotations

from typing import Any

from agents.rfc_analyst.schema import RbsProposal
from rfcv.domains.rfc_protocol.rfc_gate import RfcDocument, lookup_sentence
from rfcv.domains.rfc_protocol.spec.oracle_compiler import OracleCompileError, compile_oracle
from rfcv.domains.rfc_protocol.spec.rbs import RBS, RbsSyntaxError, parse_rbs
from rfcv.domains.rfc_protocol.spec.reconcile import reconcile
from rfcv.domains.rfc_protocol.spec.vocabulary import Vocabulary

# Trường mô tả ý của câu RFC; `variants` và `within_ms` là lựa chọn kiểm thử nên không tính vào "khớp ngữ nghĩa".
SEMANTIC_FIELDS = ("sentence_id", "modal", "rtype", "actor", "state", "trigger", "where", "expect", "forbid")
TEST_CHOICE_FIELDS = ("variants", "within_ms")


def _check(name: str, ok: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


def evaluate_proposal(
    proposal: RbsProposal | None,
    approved: RBS,
    docs: dict[int, RfcDocument],
    vocab: Vocabulary,
    *,
    aliased_to: str | None = None,
) -> dict[str, Any]:
    """Payload của sự kiện `rfc_proposal`: đề xuất, kết quả từng cổng, và so sánh với RBS đã duyệt."""
    if proposal is None:
        return {
            "produced": False,
            "checks": [_check("output", False, "agent không trả đề xuất dùng được")],
            "accepted": False,
        }
    out: dict[str, Any] = {
        "produced": True,
        "sentence_ids": list(proposal.sentence_ids),
        "rbs_text": proposal.rbs_text,
        "non_behavioral": proposal.non_behavioral,
        "non_behavioral_reason": proposal.non_behavioral_reason,
    }
    checks: list[dict[str, Any]] = []
    missing = [s for s in proposal.sentence_ids if lookup_sentence(docs, s) is None]
    checks.append(_check("sentence_ids", not missing, "không tìm thấy: " + ", ".join(missing) if missing else ""))
    if proposal.non_behavioral:
        out["checks"] = checks
        out["accepted"] = False
        out["compare"] = {
            "approved_text": approved.model_dump(mode="json"),
            "agree": False,
            "diffs": ["non_behavioral"],
            "note": "agent coi câu không kiểm chứng được, trong khi người đã viết RBS",
        }
        return out
    rbs: RBS | None = None
    try:
        rbs = parse_rbs(proposal.rbs_text)
        checks.append(_check("parse", True))
        out["rtype"] = rbs.rtype
        out["modal"] = rbs.modal
    except RbsSyntaxError as exc:
        checks.append(_check("parse", False, str(exc)[:300]))
    if rbs is not None:
        try:
            compile_oracle(rbs, vocab)
            checks.append(_check("oracle", True))
        except OracleCompileError as exc:
            checks.append(_check("oracle", False, "; ".join(exc.errors)[:400]))
        ctx = lookup_sentence(docs, rbs.sentence_id)
        if ctx is None:
            checks.append(_check("rbs_sentence", False, f"{rbs.sentence_id} không có trong RFC"))
        else:
            checks.append(_check("rbs_sentence", True))
    out["checks"] = checks
    out["accepted"] = bool(checks) and all(c["ok"] for c in checks)
    if rbs is not None:
        # Bản RFC đang đọc đánh số câu khác RBS viết tay (TXT vs RFCXML): so theo cùng một câu, nên không tính sentence_id là lệch.
        probe = rbs.model_copy(update={"sentence_id": approved.sentence_id}) if aliased_to else rbs
        agreement = reconcile(probe, approved)
        semantic = [d for d in agreement.diffs if d in SEMANTIC_FIELDS]
        out["compare"] = {
            "approved": approved.model_dump(mode="json"),
            "proposed": rbs.model_dump(mode="json"),
            "agree": agreement.agree,
            "diffs": list(agreement.diffs),
            "semantic_agree": not semantic,
            "semantic_diffs": semantic,
        }
    return out

"""`evidence.summary` gộp các T3 thường theo biến thể để không phình theo số lần thử (CT-03, BL-12)."""

from __future__ import annotations

import json
from typing import Any

from helpers import as_evidence, t1, t3
from rfcv.core.context_builder import summarize_evidence, to_jsonable
from rfcv.core.ifc import admissible_to_privileged
from rfcv.domains.rfc_protocol.payloads import Outcome
from rfcv.evidence.models import Evidence

TERMS = {"record_overflow", "send_alert(record_overflow)", "decode_error"}


def passing(n: int, **kw: Any) -> list[Evidence]:
    return [as_evidence(t3(variant=f"random:record.length={20000 + i}", **kw)) for i in range(n)]


def rows(evidence: list[Evidence], keep: set[str] | None = None) -> list[dict[str, Any]]:
    return summarize_evidence(evidence, TERMS, keep or ()).value


def test_routine_passes_collapse_into_one_row_that_still_cites_every_item() -> None:
    ev = passing(20)
    out = rows(ev)
    assert len(out) == 1
    row = out[0]
    assert row["count"] == 20 and row["outcome"] == Outcome.PASS and row["alert"] == "record_overflow"
    assert row["evidence_ids"] == [e.evidence_id for e in ev]
    assert row["variant"] == [f"random:record.length={20000 + i}" for i in range(20)]
    assert "evidence_id" not in row  # mã nằm trong `evidence_ids`


def test_the_folded_summary_is_much_smaller_and_still_admissible() -> None:
    ev = passing(60)
    folded = summarize_evidence(ev, TERMS)
    assert admissible_to_privileged(folded)
    unfolded = [
        {"evidence_id": e.evidence_id, "tier": str(e.tier), "polarity": e.polarity}
        | {"variant": e.payload.variant, "outcome": e.payload.outcome}  # type: ignore[attr-defined]
        for e in ev
    ]
    # Chỉ cần nhỏ hơn hẳn bản liệt kê từng hàng rút gọn (bản thật còn nhiều trường hơn mỗi hàng).
    assert len(json.dumps(to_jsonable(folded.value))) < len(json.dumps(to_jsonable(unfolded))) * 0.6


def test_notable_t3_rows_keep_their_own_row() -> None:
    ev = [
        *passing(5),
        as_evidence(t3(variant="boundary:record.length=16641", outcome=Outcome.FAIL, alert="decode_error")),
        as_evidence(t3(variant="max:record.length=65535", outcome=Outcome.ERROR)),
        as_evidence(t3(variant="at_limit:record.length=16640", consistent=False)),
        as_evidence(t3(variant="boundary:record.length=16642", trigger_reached=False)),
    ]
    out = rows(ev)
    assert [r.get("count") for r in out] == [5, None, None, None, None]
    assert [r["outcome"] for r in out[1:3]] == [Outcome.FAIL, Outcome.ERROR]


def test_cited_evidence_is_not_folded() -> None:
    ev = passing(4)
    cited = ev[2].evidence_id
    out = rows(ev, {cited})
    singles = [r for r in out if "count" not in r]
    assert [r["evidence_id"] for r in singles] == [cited]
    assert sum(r.get("count", 0) for r in out) == 3  # ba mục còn lại gộp; mục được trích đứng riêng


def test_rows_that_differ_in_more_than_the_variant_are_not_merged() -> None:
    ev = [*passing(3, variant_class="required"), *passing(3, variant_class="random", alert="decode_error")]
    out = rows(ev)
    assert len(out) == 2 and {r["count"] for r in out} == {3}
    assert {r["variant_class"] for r in out} == {"required", "random"}


def test_a_lone_routine_row_keeps_the_original_shape() -> None:
    (only,) = passing(1)
    (row,) = rows([only])
    assert row["evidence_id"] == only.evidence_id and "count" not in row and isinstance(row["variant"], str)


def test_other_tiers_are_untouched_and_order_is_kept() -> None:
    a, b, c = as_evidence(t1()), passing(1)[0], as_evidence(t1(lines=(900, 905)))
    out = rows([a, b, c, *passing(2, variant_class="random")])
    assert [r["tier"] for r in out] == ["T1", "T3", "T1", "T3"]

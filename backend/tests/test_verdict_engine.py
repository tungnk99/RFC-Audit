"""Kiểm thử Verdict engine: mỗi quy tắc V0–V9 có ít nhất một ca (điều kiện (c) của luận điểm đúng đắn)."""

from __future__ import annotations

import random

from hypothesis import given, settings
from hypothesis import strategies as st

from helpers import REQ, as_evidence, full_passing_set, link, suspicious, t1, t2, t3
from rfcv.domains.rfc_protocol.payloads import AspectValue, Finding, Outcome
from rfcv.domains.rfc_protocol.rules import Assurance, ProtocolRequirement
from rfcv.evidence.models import Evidence, EvidenceDraft
from rfcv.evidence.verdict_engine import Label, RequirementView, StopReason, assess, decide

REQ_B = ProtocolRequirement(
    REQ,
    "B",
    "MUST",
    required_variants=frozenset(
        {"at_limit:record.length=16640", "boundary:record.length=16641", "max:record.length=65535"}
    ),
    random_k=3,
)
REQ_C = ProtocolRequirement(REQ, "C", "MUST")
REQ_D = ProtocolRequirement(REQ, "D", "MUST")


def chain(drafts: list[EvidenceDraft]) -> list[Evidence]:
    out: list[Evidence] = []
    prev = "sha256:" + "0" * 64
    for d in drafts:
        e = as_evidence(d, prev)
        out.append(e)
        prev = e.evidence_id
    return out


def label(req: RequirementView, drafts: list[EvidenceDraft]) -> tuple[Label, str, Assurance | None]:
    v = decide(req, chain(drafts), StopReason.SUFFICIENT)
    return v.label, v.rule, v.assurance


def test_v9_no_evidence_is_unverifiable() -> None:
    assert label(REQ_B, []) == (Label.UNVERIFIABLE, "V9", None)
    report = assess(REQ_B, [])
    assert not report.decisive
    assert {m.variant for m in report.missing if m.need == "T3"} >= {"boundary:record.length=16641"}


def test_v0_inconsistent_t3_needs_review() -> None:
    assert label(REQ_B, [t3(outcome=Outcome.FAIL, consistent=False)])[:2] == (Label.NEEDS_REVIEW, "V0")


def test_v1_no_positive_witness_needs_review() -> None:
    drafts = [t3(outcome=Outcome.FAIL, refs=(Outcome.FAIL, Outcome.FAIL))]
    assert label(REQ_B, drafts)[:2] == (Label.NEEDS_REVIEW, "V1")


def test_v2_valid_fail_is_violation() -> None:
    assert label(REQ_B, [t3(outcome=Outcome.FAIL, alert="decode_error")])[:2] == (Label.VIOLATION, "V2")


def test_fail_without_any_reference_is_not_violation() -> None:
    # Không có bản tham chiếu nào: oracle chưa được chứng minh đạt được.
    assert label(REQ_B, [t3(outcome=Outcome.FAIL, refs=())])[0] is Label.UNVERIFIABLE


def test_error_and_trigger_not_reached_never_count() -> None:
    drafts = [t3(outcome=Outcome.ERROR), t3(outcome=Outcome.FAIL, trigger_reached=False)]
    assert label(REQ_B, drafts)[0] is Label.UNVERIFIABLE


def test_v3_state_learning_violation_for_type_c() -> None:
    drafts = [t3("seq#1", Outcome.FAIL, origin="state_learning", refs=())]
    assert label(REQ_C, drafts)[:2] == (Label.VIOLATION, "V3")


def test_v4_suspicious_branch_blocks_compliant() -> None:
    assert label(REQ_B, [*full_passing_set(), suspicious()])[:2] == (Label.NEEDS_REVIEW, "V4")


def test_v5_linked_compliant() -> None:
    drafts = [*full_passing_set(), t1()]
    ev = chain(drafts)
    t1_id = ev[-1].evidence_id
    boundary_id = ev[1].evidence_id
    drafts.append(link(boundary_id, t1_id))
    assert label(REQ_B, drafts) == (Label.COMPLIANT, "V5", Assurance.LINKED)


def test_v6_behavioral_when_no_t1() -> None:
    assert label(REQ_B, full_passing_set()) == (Label.COMPLIANT, "V6", Assurance.BEHAVIORAL)


def test_v7_pass_not_through_t1() -> None:
    drafts = [*full_passing_set(), t1()]
    ev = chain(drafts)
    drafts.append(link(ev[1].evidence_id, ev[-1].evidence_id, linked=False))
    assert label(REQ_B, drafts)[:2] == (Label.NEEDS_REVIEW, "V7")


def test_v7_t1_refutes() -> None:
    drafts = [*full_passing_set(), t1(reaction=AspectValue.MISMATCH, observed="send_alert(decode_error)")]
    assert label(REQ_B, drafts)[:2] == (Label.NEEDS_REVIEW, "V7")


def test_v7_control_variant_failed() -> None:
    drafts = [t3("at_limit:record.length=16640", Outcome.FAIL, variant_class="control")]
    assert label(REQ_B, drafts)[:2] == (Label.NEEDS_REVIEW, "V7")


def test_missing_random_variants_not_decisive() -> None:
    drafts = full_passing_set()[:3]
    report = assess(REQ_B, chain(drafts))
    assert not report.decisive
    assert any(m.variant == "random" for m in report.missing)


def test_v8_static_violation_and_compliance() -> None:
    assert label(REQ_D, [t2(violating=1), t1()])[:2] == (Label.VIOLATION, "V8")
    assert label(REQ_D, [t2(violating=0), t1()]) == (Label.COMPLIANT, "V8", Assurance.STATIC)


def test_type_d_needs_validated_query_and_t1() -> None:
    assert label(REQ_D, [t2(validated=False), t1()])[0] is Label.UNVERIFIABLE
    report = assess(REQ_D, chain([t1()]))
    assert any(m.need == "T2" for m in report.missing)


def test_type_d_conflict_is_not_compliant() -> None:
    drafts = [t2(violating=0), t1(finding=Finding.ABSENT)]
    report = assess(REQ_D, chain(drafts))
    assert not report.decisive and report.conflicts


def test_reaction_conflict_between_t1_and_t3() -> None:
    drafts = [t1(observed="send_alert(record_overflow)"), t3(outcome=Outcome.PASS, alert="decode_error")]
    report = assess(REQ_B, chain(drafts))
    assert any(c.kind == "T1_vs_T3" for c in report.conflicts)


def test_reaction_conflict_works_for_any_protocol_error_signal() -> None:
    """REACTION là lời gọi một tham số bất kỳ của từ vựng (RCODE DNS, mã lỗi HTTP/2...), không chỉ send_alert."""
    conflicting = [t1(observed="respond(formerr)"), t3(outcome=Outcome.PASS, alert="servfail")]
    assert any(c.kind == "T1_vs_T3" for c in assess(REQ_B, chain(conflicting)).conflicts)
    agreeing = [t1(observed="send_goaway(frame_size_error)"), t3(outcome=Outcome.PASS, alert="frame_size_error")]
    assert not assess(REQ_B, chain(agreeing)).conflicts
    no_code = [t1(observed="close"), t3(outcome=Outcome.PASS, alert="servfail")]
    assert not assess(REQ_B, chain(no_code)).conflicts


def test_other_requirements_evidence_ignored() -> None:
    assert label(REQ_B, [t3(outcome=Outcome.FAIL, requirement_id="OTHER-1")])[0] is Label.UNVERIFIABLE


_POOL = [
    t3(outcome=Outcome.FAIL),
    t3(outcome=Outcome.FAIL, consistent=False),
    t3(outcome=Outcome.FAIL, refs=(Outcome.FAIL,)),
    t3(outcome=Outcome.ERROR),
    *full_passing_set(),
    t1(),
    t1(reaction=AspectValue.MISMATCH, observed="send_alert(decode_error)"),
    suspicious(),
]


@settings(max_examples=200, deadline=None)
@given(st.lists(st.sampled_from(range(len(_POOL))), max_size=8, unique=True), st.integers(0, 2**31))
def test_label_is_independent_of_evidence_order(indices: list[int], seed: int) -> None:
    """Tái lập kết luận: cùng tập bằng chứng luôn cho cùng nhãn, bất kể thứ tự ghi."""
    drafts = [_POOL[i] for i in indices]
    shuffled = drafts[:]
    random.Random(seed).shuffle(shuffled)
    a = decide(REQ_B, chain(drafts), StopReason.BUDGET)
    b = decide(REQ_B, chain(shuffled), StopReason.BUDGET)
    assert (a.label, a.rule, a.assurance) == (b.label, b.rule, b.assurance)


@settings(max_examples=200, deadline=None)
@given(st.lists(st.sampled_from(range(len(_POOL))), max_size=8, unique=True))
def test_never_compliant_with_a_valid_fail(indices: list[int]) -> None:
    """Có một T3 FAIL hợp lệ (có nhân chứng) thì không bao giờ ra COMPLIANT."""
    drafts = [_POOL[i] for i in indices] + [t3(outcome=Outcome.FAIL)]
    assert decide(REQ_B, chain(drafts), StopReason.BUDGET).label is not Label.COMPLIANT


# ---------------------------------------------------------------- phía hợp lệ (biến thể lấy mẫu hợp lệ)

REQ_VALID = ProtocolRequirement(
    REQ,
    "B",
    "MUST",
    required_variants=REQ_B.required_variants,
    random_k=3,
    valid_random_k=2,
)


def _valid_passes(n: int) -> list[EvidenceDraft]:
    return [
        t3(f"valid_random:record.length@{v}", variant_class="valid_random", alert="none", side="valid")
        for v in range(n)
    ]


def test_valid_side_samples_are_required_when_declared() -> None:
    report = assess(REQ_VALID, chain(full_passing_set()))
    assert not report.decisive
    assert any(m.variant == "valid_random" for m in report.missing)
    assert label(REQ_VALID, [*full_passing_set(), *_valid_passes(2)]) == (Label.COMPLIANT, "V6", Assurance.BEHAVIORAL)


def test_valid_side_reaction_is_needs_review_never_violation() -> None:
    """SUT phản ứng với dữ liệu HỢP LỆ: có thể là chủ ý chặt hơn RFC, nên V7 chứ không phải V2."""
    bad = t3(
        "valid_random:record.length@8",
        Outcome.FAIL,
        variant_class="valid_random",
        alert="record_overflow",
        side="valid",
    )
    assert label(REQ_VALID, [*full_passing_set(), *_valid_passes(1), bad])[:2] == (Label.NEEDS_REVIEW, "V7")
    assert label(REQ_B, [bad])[:2] == (Label.NEEDS_REVIEW, "V7")


def test_trigger_side_fail_is_still_a_violation_even_with_valid_side_evidence() -> None:
    fail = t3("random:record.length@40000", Outcome.FAIL, variant_class="random", alert="none")
    assert label(REQ_VALID, [*full_passing_set(), *_valid_passes(2), fail])[:2] == (Label.VIOLATION, "V2")

"""Bảng nhãn "vàng": đặc trưng hoá hành vi của bộ quy tắc trên các bộ bằng chứng chuẩn.

Mọi quy tắc hoặc cấu hình mới phải im lặng khi thiếu đầu vào của nó (không đột biến, không probe,
không mẫu phía hợp lệ), nên bảng này KHÔNG được đổi khi thêm tính năng. Muốn đổi một dòng phải sửa tường minh ở đây và nêu lý do trong commit.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from helpers import REQ, chain, full_passing_set, link, suspicious, t1, t2, t3
from rfcv.domains.rfc_protocol.payloads import AspectValue, Finding, Outcome
from rfcv.domains.rfc_protocol.rules import RULE_SET, ProtocolRequirement
from rfcv.eval.replay import diff_labels, replay
from rfcv.evidence.models import EvidenceDraft
from rfcv.evidence.verdict_engine import StopReason, VerdictRecord

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


def _linked(linked: bool) -> list[EvidenceDraft]:
    base = [*full_passing_set(), t1()]
    ev = chain(base)
    return [*base, link(ev[1].evidence_id, ev[-1].evidence_id, linked=linked)]


# (tên, yêu cầu, bộ bằng chứng, (nhãn, quy tắc, assurance))
GOLDEN: list[tuple[str, ProtocolRequirement, Callable[[], list[EvidenceDraft]], tuple[str, str, str | None]]] = [
    ("không bằng chứng", REQ_B, list, ("UNVERIFIABLE", "V9", None)),
    ("T3 không nhất quán", REQ_B, lambda: [t3(outcome=Outcome.FAIL, consistent=False)], ("NEEDS_REVIEW", "V0", None)),
    (
        "mọi tham chiếu FAIL",
        REQ_B,
        lambda: [t3(outcome=Outcome.FAIL, refs=(Outcome.FAIL, Outcome.FAIL))],
        ("NEEDS_REVIEW", "V1", None),
    ),
    ("FAIL hợp lệ", REQ_B, lambda: [t3(outcome=Outcome.FAIL, alert="decode_error")], ("VIOLATION", "V2", None)),
    ("FAIL không tham chiếu", REQ_B, lambda: [t3(outcome=Outcome.FAIL, refs=())], ("UNVERIFIABLE", "V9", None)),
    (
        "ERROR và chưa tới trigger",
        REQ_B,
        lambda: [t3(outcome=Outcome.ERROR), t3(outcome=Outcome.FAIL, trigger_reached=False)],
        ("UNVERIFIABLE", "V9", None),
    ),
    (
        "máy trạng thái học được (C)",
        REQ_C,
        lambda: [t3("seq#1", Outcome.FAIL, origin="state_learning", refs=())],
        ("VIOLATION", "V3", None),
    ),
    ("nhánh nghi vấn", REQ_B, lambda: [*full_passing_set(), suspicious()], ("NEEDS_REVIEW", "V4", None)),
    ("COMPLIANT chỉ theo hành vi", REQ_B, full_passing_set, ("COMPLIANT", "V6", "BEHAVIORAL")),
    ("COMPLIANT liên kết độ phủ", REQ_B, lambda: _linked(True), ("COMPLIANT", "V5", "LINKED")),
    ("PASS nhưng độ phủ không qua T1", REQ_B, lambda: _linked(False), ("NEEDS_REVIEW", "V7", None)),
    (
        "T1 bác bỏ",
        REQ_B,
        lambda: [*full_passing_set(), t1(reaction=AspectValue.MISMATCH, observed="send_alert(decode_error)")],
        ("NEEDS_REVIEW", "V7", None),
    ),
    (
        "đối chứng FAIL",
        REQ_B,
        lambda: [t3("at_limit:record.length=16640", Outcome.FAIL, variant_class="control")],
        ("NEEDS_REVIEW", "V7", None),
    ),
    ("thiếu biến thể ngẫu nhiên", REQ_B, lambda: full_passing_set()[:3], ("UNVERIFIABLE", "V9", None)),
    ("loại D vi phạm", REQ_D, lambda: [t2(violating=1), t1()], ("VIOLATION", "V8", None)),
    ("loại D tuân thủ", REQ_D, lambda: [t2(violating=0), t1()], ("COMPLIANT", "V8", "STATIC")),
    ("loại D thiếu T2", REQ_D, lambda: [t1()], ("UNVERIFIABLE", "V9", None)),
    (
        "loại D T1 bác bỏ, T2 sạch",
        REQ_D,
        lambda: [
            t2(violating=0),
            t1(finding=Finding.ABSENT),
        ],
        ("UNVERIFIABLE", "V9", None),
    ),
]


@pytest.mark.parametrize(("name", "req", "build", "expected"), GOLDEN, ids=[g[0] for g in GOLDEN])
def test_golden_label(
    name: str, req: ProtocolRequirement, build: Callable[[], list[EvidenceDraft]], expected: tuple[str, str, str | None]
) -> None:
    v = replay(chain(build()), req, RULE_SET)
    got = (v.label.value, v.rule, str(v.assurance) if v.assurance else None)
    assert got == expected, f"{name}: bảng vàng đổi — {got} thay vì {expected}"


def test_diff_labels_reports_only_real_changes() -> None:
    def rec(label_rule: tuple[str, str]) -> VerdictRecord:
        from rfcv.evidence.verdict_engine import Label

        return VerdictRecord(REQ, Label(label_rule[0]), None, label_rule[1], "MUST", (), StopReason.SUFFICIENT, "v")

    old = {"R1": rec(("VIOLATION", "V2")), "R2": rec(("COMPLIANT", "V6"))}
    new = {"R1": rec(("VIOLATION", "V2")), "R2": rec(("NEEDS_REVIEW", "V10")), "R3": rec(("UNVERIFIABLE", "V9"))}
    changes = diff_labels(old, new)
    assert [(c.requirement_id, c.new_label, c.new_rule) for c in changes] == [
        ("R2", "NEEDS_REVIEW", "V10"),
        ("R3", "UNVERIFIABLE", "V9"),
    ]

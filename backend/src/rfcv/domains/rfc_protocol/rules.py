"""Bộ quy tắc V0–V9 của miền RFC giao thức (thiết kế chính, Bảng 7), profile `rfc-protocol`.

Thứ tự thể hiện hai nguyên tắc: hành vi chạy thực tế ưu tiên hơn đọc mã, và khi nghi ngờ thì không kết luận.
Loại yêu cầu: A, B, C quan sát được từ bên ngoài nên T3 quyết định; D là hành vi nội bộ nên dùng T2 kết hợp T1.
Trường assurance ghi mức bảo đảm của nhãn COMPLIANT: LINKED, BEHAVIORAL hoặc STATIC.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property

from rfcv.domains.rfc_protocol.payloads import (
    AspectName,
    Outcome,
    T1Payload,
    T2StaticPayload,
    T2SuspiciousPayload,
    T3LinkPayload,
    T3Payload,
)
from rfcv.evidence.models import Evidence
from rfcv.evidence.verdict_engine import Conflict, Decision, Label, Missing, RequirementView, Rule, RuleSet

PROFILE = "rfc-protocol"
OBSERVABLE = frozenset({"A", "B", "C"})
INTERNAL = frozenset({"D"})
_REACTION_CALL = re.compile(r"^[a-z_][a-z0-9_]*\(([a-z0-9_]+)\)$")


class Assurance(StrEnum):
    LINKED = "LINKED"
    BEHAVIORAL = "BEHAVIORAL"
    STATIC = "STATIC"


@dataclass(frozen=True)
class ProtocolRequirement(RequirementView):
    """Yêu cầu kèm tập biến thể bắt buộc lấy từ oracle đã biên dịch."""

    required_variants: frozenset[str] = frozenset()
    random_k: int = 0  # T3 PASS cần có từ biến thể lấy mẫu phía vi phạm (tầng + giá trị đặc biệt)
    valid_random_k: int = 0  # như trên, phía hợp lệ


class _View:
    """Dữ liệu dùng chung cho các quy tắc: phân loại bằng chứng và các tập dẫn xuất (tính lười, một lần)."""

    def __init__(self, req: RequirementView, evidence: Sequence[Evidence]) -> None:
        self.req = req
        self.required: frozenset[str] = getattr(req, "required_variants", frozenset())
        self.random_k: int = getattr(req, "random_k", 0)
        self.valid_random_k: int = getattr(req, "valid_random_k", 0)
        self.t1: list[tuple[Evidence, T1Payload]] = []
        self.t2: list[tuple[Evidence, T2StaticPayload]] = []
        self.suspicious: list[tuple[Evidence, T2SuspiciousPayload]] = []
        self.t3: list[tuple[Evidence, T3Payload]] = []
        # (t3_id, t1_id) đã liên kết qua độ phủ, từ bản ghi coverage_link hoặc trường coverage_link của T3
        self.links: set[tuple[str, str]] = set()
        for e in evidence:
            match e.payload:
                case T1Payload() as p1:
                    self.t1.append((e, p1))
                case T2StaticPayload() as p2:
                    self.t2.append((e, p2))
                case T2SuspiciousPayload() as ps:
                    self.suspicious.append((e, ps))
                case T3Payload() as p3:
                    self.t3.append((e, p3))
                    if p3.coverage_link is not None and p3.coverage_link.linked:
                        self.links.add((e.evidence_id, p3.coverage_link.t1))
                case T3LinkPayload() as link:
                    if link.linked:
                        self.links.add((link.t3, link.t1))
                case _:
                    pass

    @cached_property
    def valid(self) -> list[tuple[Evidence, T3Payload]]:
        return [(e, t) for e, t in self.t3 if t.valid]

    @cached_property
    def passes(self) -> list[tuple[Evidence, T3Payload]]:
        return [(e, t) for e, t in self.valid if t.outcome is Outcome.PASS and t.signature_matches]

    @cached_property
    def missing_variants(self) -> list[Missing]:
        passed = {t.variant for _, t in self.passes if t.variant_class in ("required", "control")}
        out = [Missing("T3", v, "biến thể bắt buộc chưa PASS") for v in sorted(self.required - passed)]
        random_passes = sum(1 for _, t in self.passes if t.variant_class == "random")
        if random_passes < self.random_k:
            out.append(Missing("T3", "random", f"cần {self.random_k} biến thể ngẫu nhiên, có {random_passes}"))
        valid_passes = sum(1 for _, t in self.passes if t.variant_class == "valid_random")
        if valid_passes < self.valid_random_k:
            out.append(Missing("T3", "valid_random", f"cần {self.valid_random_k} mẫu phía hợp lệ, có {valid_passes}"))
        return out

    @cached_property
    def complete(self) -> bool:
        return not self.missing_variants and bool(self.passes)

    @cached_property
    def t1_refuting(self) -> list[tuple[Evidence, T1Payload]]:
        return [(e, t) for e, t in self.t1 if t.refutes]

    @cached_property
    def t2_validated(self) -> list[tuple[Evidence, T2StaticPayload]]:
        return [(e, t) for e, t in self.t2 if t.validated]

    @cached_property
    def t2_refuting(self) -> list[tuple[Evidence, T2StaticPayload]]:
        return [(e, t) for e, t in self.t2_validated if t.violating_paths > 0]

    @cached_property
    def d_ready(self) -> bool:
        return bool(self.t2_validated) and bool(self.t1)


def _ids(items: Sequence[tuple[Evidence, object]]) -> tuple[str, ...]:
    return tuple(e.evidence_id for e, _ in items)


def _prepare(req: RequirementView, evidence: Sequence[Evidence]) -> _View:
    return _View(req, evidence)


# ---- các quy tắc ---------------------------------------------------------------------------------


def _v0(req: RequirementView, v: _View) -> Decision | None:
    """T3 không nhất quán giữa các lần chạy hoặc giữa các môi trường."""
    unstable = [(e, t) for e, t in v.t3 if not t.consistent or not t.environments_consistent]
    return Decision(Label.NEEDS_REVIEW, "V0", _ids(unstable)) if unstable else None


def _v1(req: RequirementView, v: _View) -> Decision | None:
    """Kịch bản chính không có nhân chứng dương (mọi bản tham chiếu FAIL): oracle có thể sai."""
    no_witness = [(e, t) for e, t in v.valid if t.witness.all_positive_fail]
    return Decision(Label.NEEDS_REVIEW, "V1", _ids(no_witness)) if no_witness else None


def _v2(req: RequirementView, v: _View) -> Decision | None:
    """T3 FAIL hợp lệ: chữ ký khớp, trigger đã xảy ra, có nhân chứng dương."""
    fails = [
        (e, t)
        for e, t in v.valid
        if t.outcome is Outcome.FAIL
        and t.origin == "scenario"
        and t.variant_class != "control"
        and t.side != "valid"  # phản ứng nhầm ở phía hợp lệ không phải bằng chứng vi phạm yêu cầu kích hoạt (xem V7)
        and t.signature_matches
        and t.witness.has_positive
    ]
    return Decision(Label.VIOLATION, "V2", _ids(fails)) if fails else None


def _v3(req: RequirementView, v: _View) -> Decision | None:
    """Loại C: chuỗi vi phạm tìm từ máy trạng thái học được, chạy lại trên SUT cho FAIL."""
    learned = [(e, t) for e, t in v.valid if t.origin == "state_learning" and t.outcome is Outcome.FAIL]
    return Decision(Label.VIOLATION, "V3", _ids(learned)) if learned else None


def _v4(req: RequirementView, v: _View) -> Decision | None:
    """Có nhánh nghi vấn trên đường xử lý của yêu cầu."""
    on_path = [(e, s) for e, s in v.suspicious if s.on_path]
    return Decision(Label.NEEDS_REVIEW, "V4", _ids(on_path)) if on_path else None


def _v7_control(req: RequirementView, v: _View) -> Decision | None:
    """SUT từ chối dữ liệu hợp lệ đúng ngưỡng: biến thể đối chứng at_limit thuộc tập bắt buộc (tài liệu adapter, mục
    6)."""
    failed = [
        (e, t) for e, t in v.valid if t.outcome is Outcome.FAIL and (t.variant_class == "control" or t.side == "valid")
    ]
    return Decision(Label.NEEDS_REVIEW, "V7", _ids(failed)) if failed else None


def _v7_refuted(req: RequirementView, v: _View) -> Decision | None:
    """Đủ biến thể PASS nhưng T1 hoặc T2 bác bỏ."""
    if v.complete and (v.t1_refuting or v.t2_refuting):
        return Decision(Label.NEEDS_REVIEW, "V7", _ids(v.t1_refuting) + _ids(v.t2_refuting))
    return None


def _v5(req: RequirementView, v: _View) -> Decision | None:
    """Đủ biến thể PASS, có T3 liên kết với T1 qua độ phủ, không có T1/T2 bác bỏ."""
    if not v.complete:
        return None
    pass_ids = {e.evidence_id for e, _ in v.passes}
    t1_ids = {e.evidence_id for e, _ in v.t1}
    pairs = sorted((t3, t1) for t3, t1 in v.links if t3 in pass_ids and t1 in t1_ids)
    if not pairs:
        return None
    linked_t1 = tuple(sorted({t1 for _, t1 in pairs}))
    return Decision(Label.COMPLIANT, "V5", _ids(v.passes) + linked_t1, Assurance.LINKED)


def _v6(req: RequirementView, v: _View) -> Decision | None:
    """Như V5 nhưng agent không định vị được T1."""
    if v.complete and not v.t1:
        return Decision(Label.COMPLIANT, "V6", _ids(v.passes), Assurance.BEHAVIORAL)
    return None


def _v7_unlinked(req: RequirementView, v: _View) -> Decision | None:
    """PASS nhưng độ phủ không đi qua T1."""
    if v.complete:
        return Decision(Label.NEEDS_REVIEW, "V7", _ids(v.passes) + _ids(v.t1))
    return None


def _v8_violation(req: RequirementView, v: _View) -> Decision | None:
    """Loại D: truy vấn tĩnh đã kiểm định chỉ ra đường vi phạm, kết hợp T1."""
    if v.d_ready and v.t2_refuting:
        return Decision(Label.VIOLATION, "V8", _ids(v.t2_refuting) + _ids(v.t1))
    return None


def _v8_compliant(req: RequirementView, v: _View) -> Decision | None:
    """Loại D: không có đường vi phạm và T1 không bác bỏ."""
    if v.d_ready and not v.t2_refuting and not v.t1_refuting:
        return Decision(Label.COMPLIANT, "V8", _ids(v.t2_validated) + _ids(v.t1), Assurance.STATIC)
    return None


# ---- còn thiếu gì, mâu thuẫn gì -----------------------------------------------------------------


def _reaction_conflicts(v: _View) -> list[Conflict]:
    """Phản ứng quan sát trong T3 ↔ REACTION.observed trong T1 (đối chiếu tất định, mục 7.2).

    REACTION.observed là một lời gọi một tham số của từ vựng adapter (`send_alert(record_overflow)`,
    `respond(formerr)`…); tham số là mã lỗi, so với trường `alert` của Observation@1 (mã lỗi SUT phát ra, mọi giao thức)."""
    conflicts: list[Conflict] = []
    for e1, t1 in v.t1:
        reaction = next((a for a in t1.aspects if a.aspect is AspectName.REACTION), None)
        if reaction is None or not isinstance(reaction.observed, str):
            continue
        call = _REACTION_CALL.match(reaction.observed)
        if call is None:
            continue
        claimed = call.group(1)
        for e3, t3 in v.t3:
            if not t3.valid or t3.variant_class == "control" or t3.side == "valid":
                continue
            seen = t3.observed.get("alert")
            if isinstance(seen, str) and seen not in ("none", claimed):
                conflicts.append(Conflict("T1_vs_T3", (e1.evidence_id, e3.evidence_id), "REACTION"))
    return conflicts


def _conflicts(req: RequirementView, v: _View) -> Sequence[Conflict]:
    return _reaction_conflicts(v) if req.rtype in OBSERVABLE else []


def _gaps(req: RequirementView, v: _View) -> tuple[Sequence[Missing], Sequence[Conflict]]:
    if req.rtype in INTERNAL:
        missing: list[Missing] = []
        if not v.t2_validated:
            missing.append(Missing("T2", None, "chưa có truy vấn tĩnh đã kiểm định đột biến"))
        if not v.t1:
            missing.append(Missing("T1", None, "loại D cần T1 kết hợp T2"))
        if missing:
            return missing, []
        # T2 không thấy đường vi phạm nhưng T1 bác bỏ: mâu thuẫn, không kết luận.
        return [], [Conflict("T1_vs_T2", _ids(v.t1_refuting) + _ids(v.t2_validated))]
    missing = list(v.missing_variants)
    if not v.t1:
        missing.append(Missing("T1", None, "chưa có vị trí mã để liên kết độ phủ"))
    return missing, []


RULE_SET = RuleSet(
    name=PROFILE + "@3",
    rules=(
        Rule("V0", _v0, OBSERVABLE, "T3 không nhất quán"),
        Rule("V1", _v1, OBSERVABLE, "không có nhân chứng dương"),
        Rule("V2", _v2, OBSERVABLE, "T3 FAIL hợp lệ"),
        Rule("V3", _v3, frozenset({"C"}), "vi phạm từ máy trạng thái học được"),
        Rule("V4", _v4, None, "nhánh nghi vấn trên đường xử lý"),
        Rule("V7-control", _v7_control, OBSERVABLE, "biến thể đối chứng FAIL"),
        Rule("V7-refuted", _v7_refuted, OBSERVABLE, "PASS nhưng T1/T2 bác bỏ"),
        Rule("V5", _v5, OBSERVABLE, "COMPLIANT liên kết độ phủ"),
        Rule("V6", _v6, OBSERVABLE, "COMPLIANT chỉ theo hành vi"),
        Rule("V7-unlinked", _v7_unlinked, OBSERVABLE, "PASS nhưng độ phủ không đi qua T1"),
        Rule("V8-violation", _v8_violation, INTERNAL, "loại D: có đường vi phạm"),
        Rule("V8-compliant", _v8_compliant, INTERNAL, "loại D: không có đường vi phạm"),
    ),
    prepare=_prepare,
    gaps=_gaps,
    conflicts=_conflicts,
    fallback_rule="V9",
)

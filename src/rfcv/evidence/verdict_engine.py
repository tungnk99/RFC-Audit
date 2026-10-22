"""Verdict engine: áp một bộ quy tắc (RuleSet) lên tập bằng chứng để ra nhãn (thiết kế chính, Bảng 7).

Engine này tổng quát và là hàm thuần: không gọi LLM, không đọc/ghi lưu trữ (import-linter ép điều này).
Quy tắc cụ thể (ví dụ V0–V9 của miền RFC giao thức) do domain pack cung cấp dưới dạng `RuleSet`.
Quy tắc xét theo thứ tự; quy tắc đầu tiên khớp quyết định nhãn. Hai nguyên tắc: hành vi chạy thực tế ưu tiên hơn
đọc mã, và khi nghi ngờ thì không kết luận (không quy tắc nào khớp thì UNVERIFIABLE).

Ngoài nhãn, engine trả "báo cáo độ đủ" cho Planner: đã đủ chưa, còn thiếu gì, có mâu thuẫn không
(tài liệu phối hợp agent, mục 8). `RuleSet.version` là hash nội dung bộ quy tắc, nên sửa một quy tắc luôn đổi phiên bản.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from rfcv.common.hashing import content_hash, text_hash
from rfcv.evidence.models import Evidence
from rfcv.plugins import current_registry


class Label(StrEnum):
    COMPLIANT = "COMPLIANT"
    VIOLATION = "VIOLATION"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    UNVERIFIABLE = "UNVERIFIABLE"


class StopReason(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    BUDGET = "BUDGET"
    LOOP = "LOOP"
    INFEASIBLE = "INFEASIBLE"


@dataclass(frozen=True)
class RequirementView:
    """Phần của yêu cầu mà engine cần. Miền mở rộng bằng lớp con (ví dụ thêm tập biến thể bắt buộc)."""

    requirement_id: str
    rtype: str
    modal: str


@dataclass(frozen=True)
class Decision:
    label: Label
    rule: str
    evidence_ids: tuple[str, ...]
    assurance: str | None = None


@dataclass(frozen=True)
class Missing:
    need: str
    variant: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class Conflict:
    kind: str
    evidence_ids: tuple[str, ...]
    aspect: str | None = None


@dataclass(frozen=True)
class SufficiencyReport:
    requirement_id: str
    provisional: Decision | None
    missing: tuple[Missing, ...] = ()
    conflicts: tuple[Conflict, ...] = ()

    @property
    def decisive(self) -> bool:
        return self.provisional is not None


@dataclass(frozen=True)
class Rule:
    """Một quy tắc: hàm thuần (yêu cầu, dữ liệu đã chuẩn bị) -> Decision | None.

    `applies_to` giới hạn theo loại yêu cầu (None là mọi loại). `id` chỉ để đọc; nhãn quy tắc ghi vào kết luận
    là `Decision.rule` do hàm trả về.
    """

    id: str
    decide: Callable[[Any, Any], Decision | None]
    applies_to: frozenset[str] | None = None
    description: str = ""


def _source_hash(fn: Callable[..., Any]) -> str:
    try:
        return text_hash(inspect.getsource(fn))
    except (OSError, TypeError):
        return text_hash(getattr(fn, "__qualname__", repr(fn)))


@dataclass(frozen=True)
class RuleSet:
    """Một bộ quy tắc hoàn chỉnh cho một miền.

    prepare   dựng dữ liệu dùng chung từ bằng chứng của một yêu cầu (một lần mỗi lần đánh giá);
    gaps      khi chưa có nhãn: còn thiếu gì, có mâu thuẫn gì;
    conflicts mâu thuẫn luôn báo cho Planner kể cả khi đã có nhãn tạm.
    """

    name: str
    rules: tuple[Rule, ...]
    prepare: Callable[[Any, Sequence[Evidence]], Any]
    gaps: Callable[[Any, Any], tuple[Sequence[Missing], Sequence[Conflict]]]
    conflicts: Callable[[Any, Any], Sequence[Conflict]] = lambda req, data: ()
    fallback_rule: str = "V9"
    version: str = field(init=False)

    def __post_init__(self) -> None:
        digest = content_hash(
            {
                "name": self.name,
                "fallback": self.fallback_rule,
                "rules": [
                    [r.id, sorted(r.applies_to) if r.applies_to else None, r.description, _source_hash(r.decide)]
                    for r in self.rules
                ],
                "hooks": [_source_hash(self.prepare), _source_hash(self.gaps), _source_hash(self.conflicts)],
            }
        )
        object.__setattr__(self, "version", digest)


@dataclass(frozen=True)
class VerdictRecord:
    requirement_id: str
    label: Label
    assurance: str | None
    rule: str
    modal: str
    evidence_ids: tuple[str, ...]
    stop_reason: StopReason
    rules_version: str
    conflicts: tuple[Conflict, ...] = field(default=())

    def to_json(self) -> dict[str, object]:
        return {
            "requirement_id": self.requirement_id,
            "label": self.label.value,
            "assurance": str(self.assurance) if self.assurance else None,
            "rule": self.rule,
            "rules_version": self.rules_version,
            "modal": self.modal,
            "evidence_ids": list(self.evidence_ids),
            "stop_reason": self.stop_reason.value,
        }


def assess(req: RequirementView, evidence: Sequence[Evidence], rules: RuleSet | None = None) -> SufficiencyReport:
    """Báo cáo độ đủ sau mỗi vòng: nhãn tạm (nếu một quy tắc áp dụng), còn thiếu gì, mâu thuẫn."""
    rs = rules or current_registry().default_rule_set()
    own = [e for e in evidence if e.requirement_id == req.requirement_id]
    data = rs.prepare(req, own)
    decision: Decision | None = None
    for rule in rs.rules:
        if rule.applies_to is not None and req.rtype not in rule.applies_to:
            continue
        decision = rule.decide(req, data)
        if decision is not None:
            break
    conflicts = list(rs.conflicts(req, data))
    missing: list[Missing] = []
    if decision is None:
        gap_missing, gap_conflicts = rs.gaps(req, data)
        missing, conflicts = list(gap_missing), conflicts + list(gap_conflicts)
    return SufficiencyReport(req.requirement_id, decision, tuple(missing), tuple(conflicts))


def decide(
    req: RequirementView, evidence: Sequence[Evidence], stop_reason: StopReason, rules: RuleSet | None = None
) -> VerdictRecord:
    """Nhãn cuối. Mọi trường hợp còn lại, kể cả chỉ có nhận định chưa đối chiếu, là UNVERIFIABLE."""
    rs = rules or current_registry().default_rule_set()
    report = assess(req, evidence, rs)
    d = report.provisional or Decision(Label.UNVERIFIABLE, rs.fallback_rule, ())
    return VerdictRecord(
        requirement_id=req.requirement_id,
        label=d.label,
        assurance=d.assurance,
        rule=d.rule,
        modal=req.modal,
        evidence_ids=d.evidence_ids,
        stop_reason=stop_reason,
        rules_version=rs.version,
        conflicts=report.conflicts,
    )

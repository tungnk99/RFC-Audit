"""Trích xuất tất định các điểm phân kỳ (divergence points) hỗ trợ Verifier khác họ mô hình.

Module này hoàn toàn tất định (không LLM, không I/O), chạy trên câu RFC (TRUSTED) và bằng chứng T1/T3
(UNTRUSTED) để rút ra các điểm có nguy cơ làm sai nhãn COMPLIANT:
- Lượng từ phổ quát trong câu RFC (`every`, `all`, `each`, `any`) đòi hỏi đúng trên mọi đường xử lý;
- Đường nhánh chưa khám phá (`unexplored` khác rỗng trên T1);
- Khối mã bị loại bỏ bởi macro biên dịch `#ifdef` (`disabled_by` khác rỗng trên T1);
- Mâu thuẫn T1 ↔ T3 (`REACTION`/`THRESHOLD` MISMATCH, cảnh báo lệch, hoặc T1 ABSENT trong khi T3 PASS);
- COMPLIANT chỉ dựa trên hành vi mà thiếu bằng chứng mã T1 hoặc chưa liên kết độ phủ.

Bất biến IFC (Bảng 8): mọi đầu ra cho agent đặc quyền chỉ mang giá trị thuộc miền hữu hạn (enum,
`VerifiedRef`, danh sách/từ điển của chúng); tuyệt đối không rò chuỗi tự do từ mã nguồn hay SUT.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from rfcv.core.ifc import Labeled, TrustLabel, VerifiedRef
from rfcv.domains.rfc_protocol.payloads import (
    UNVERIFIED,
    AspectName,
    AspectValue,
    Finding,
    Outcome,
    T1Payload,
    T3Payload,
)
from rfcv.evidence.models import Evidence

__all__ = [
    "DivergenceKind",
    "DivergencePoint",
    "collect_divergence_points",
    "extract_divergence_points",
]

_UNIVERSAL_QUANTIFIER = re.compile(r"\b(every|all|each|any)\b", re.IGNORECASE)
_REACTION_CALL = re.compile(r"^[a-z_][a-z0-9_]*\(([a-z0-9_]+)\)$")
_SAFE_MACRO = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.:,<>/+-]{1,128}$")
_ALLOWED_TASKS = frozenset({"LOCATE", "TRACE_PATHS", "RECHECK", "SELECT_TESTS", "STATIC_QUERY", "MAP_COMPONENTS"})


class DivergenceKind(StrEnum):
    QUANTIFIER_SCOPE = "QUANTIFIER_SCOPE"
    UNEXPLORED_PATHS = "UNEXPLORED_PATHS"
    IFDEF_DISABLED = "IFDEF_DISABLED"
    T1_T3_MISMATCH = "T1_T3_MISMATCH"
    NO_CODE_LINK = "NO_CODE_LINK"


@dataclass(frozen=True)
class DivergencePoint:
    """Một điểm phân kỳ có cấu trúc, chỉ chứa mã thuộc miền đóng hoặc `VerifiedRef` (an toàn IFC)."""

    kind: DivergenceKind
    severity: Literal["HIGH", "MEDIUM"]
    evidence_ids: tuple[VerifiedRef, ...]
    suggested_task: str
    code_token: str

    def __post_init__(self) -> None:
        if self.suggested_task not in _ALLOWED_TASKS:
            raise ValueError(f"suggested_task ngoài miền đóng: {self.suggested_task!r}")
        if not _SAFE_TOKEN.fullmatch(self.code_token):
            raise ValueError(f"code_token không thuộc miền mã an toàn IFC: {self.code_token!r}")

    def to_privileged_dict(self) -> dict[str, Any]:
        """Chuyển sang từ điển chỉ gồm enum và `VerifiedRef` để đi qua cổng IFC vào agent đặc quyền."""
        return {
            "kind": self.kind,
            "severity": VerifiedRef(self.severity),
            "evidence_ids": list(self.evidence_ids),
            "suggested_task": VerifiedRef(self.suggested_task),
            "code_token": VerifiedRef(self.code_token),
        }


def _is_waived(t3: T3Payload) -> bool:
    """Ca phía hợp lệ bị mọi bản tham chiếu từ chối (CT-26) đã được quy tắc loại trừ."""
    return (t3.variant_class == "control" or t3.side == "valid") and t3.witness.all_positive_fail


def _safe_macro_token(macros: Sequence[str]) -> VerifiedRef:
    cleaned: list[str] = []
    seen: set[str] = set()
    for macro in macros:
        token = macro if _SAFE_MACRO.fullmatch(macro) else str(UNVERIFIED)
        if token not in seen:
            seen.add(token)
            cleaned.append(token)
    joined = ",".join(cleaned[:4])
    if not _SAFE_TOKEN.fullmatch(joined):
        return UNVERIFIED
    return VerifiedRef(f"ifdef:{joined}")


def collect_divergence_points(
    rfc_sentence: str | None,
    t1_items: Sequence[Evidence],
    t3_items: Sequence[Evidence],
) -> tuple[DivergencePoint, ...]:
    """Thu thập danh sách `DivergencePoint` tất định từ câu RFC và các bằng chứng T1, T3."""
    t1_pairs: list[tuple[Evidence, T1Payload]] = [(e, e.payload) for e in t1_items if isinstance(e.payload, T1Payload)]
    t3_pairs: list[tuple[Evidence, T3Payload]] = [(e, e.payload) for e in t3_items if isinstance(e.payload, T3Payload)]
    passing_t3 = [(e, t3) for e, t3 in t3_pairs if t3.valid and t3.outcome is Outcome.PASS and not _is_waived(t3)]
    trigger_passing_t3 = [(e, t3) for e, t3 in passing_t3 if t3.side != "valid" and t3.variant_class != "control"]

    points: list[DivergencePoint] = []

    # 1. Lượng từ phổ quát trong câu RFC: mọi đường xử lý đều phải tuân thủ.
    quantifier_match = _UNIVERSAL_QUANTIFIER.search(rfc_sentence) if rfc_sentence else None
    if quantifier_match is not None:
        quantifier = quantifier_match.group(1).lower()
        points.append(
            DivergencePoint(
                kind=DivergenceKind.QUANTIFIER_SCOPE,
                severity="HIGH",
                evidence_ids=tuple(VerifiedRef(e.evidence_id) for e, _ in t1_pairs),
                suggested_task=VerifiedRef("TRACE_PATHS"),
                code_token=VerifiedRef(f"quantifier:{quantifier}"),
            )
        )

    # 2. Nhánh chưa khám phá (`unexplored` khác rỗng trên T1) — tuyệt đối không chép chuỗi tự do của `unexplored`.
    for e1, t1 in t1_pairs:
        if t1.unexplored:
            points.append(
                DivergencePoint(
                    kind=DivergenceKind.UNEXPLORED_PATHS,
                    severity="HIGH" if quantifier_match is not None else "MEDIUM",
                    evidence_ids=(VerifiedRef(e1.evidence_id),),
                    suggested_task=VerifiedRef("TRACE_PATHS"),
                    code_token=VerifiedRef(f"unexplored:{len(t1.unexplored)}"),
                )
            )

    # 3. Khối mã bị loại bỏ bởi `#ifdef` / cờ biên dịch (`disabled_by` khác rỗng trên T1).
    for e1, t1 in t1_pairs:
        if t1.disabled_by:
            points.append(
                DivergencePoint(
                    kind=DivergenceKind.IFDEF_DISABLED,
                    severity="HIGH",
                    evidence_ids=(VerifiedRef(e1.evidence_id),),
                    suggested_task=VerifiedRef("RECHECK"),
                    code_token=_safe_macro_token(t1.disabled_by),
                )
            )

    # 4. Mâu thuẫn giữa bằng chứng mã T1 (REACTION/THRESHOLD/ABSENT) và bằng chứng hành vi T3 PASS.
    if passing_t3:
        passing_t3_refs = tuple(VerifiedRef(e3.evidence_id) for e3, _ in passing_t3)
        for e1, t1 in t1_pairs:
            e1_ref = VerifiedRef(e1.evidence_id)
            emitted_reaction_mismatch = False
            emitted_any_mismatch = False
            for aspect in t1.aspects:
                if (
                    aspect.aspect in (AspectName.REACTION, AspectName.THRESHOLD)
                    and aspect.value is AspectValue.MISMATCH
                ):
                    points.append(
                        DivergencePoint(
                            kind=DivergenceKind.T1_T3_MISMATCH,
                            severity="HIGH",
                            evidence_ids=(e1_ref, *passing_t3_refs),
                            suggested_task=VerifiedRef("RECHECK"),
                            code_token=VerifiedRef(f"{aspect.aspect.value}:MISMATCH"),
                        )
                    )
                    emitted_any_mismatch = True
                    if aspect.aspect is AspectName.REACTION:
                        emitted_reaction_mismatch = True

            if not emitted_reaction_mismatch and trigger_passing_t3:
                reaction = next((a for a in t1.aspects if a.aspect is AspectName.REACTION), None)
                if reaction is not None and isinstance(reaction.observed, str):
                    call = _REACTION_CALL.match(reaction.observed)
                    if call is not None:
                        claimed_alert = call.group(1)
                        conflicting_t3 = [
                            VerifiedRef(e3.evidence_id)
                            for e3, t3 in trigger_passing_t3
                            if isinstance(seen := t3.observed.get("alert"), str)
                            and (
                                seen not in ("none", claimed_alert)
                                or (seen == "none" and reaction.value is AspectValue.MATCH)
                            )
                        ]
                        if conflicting_t3:
                            points.append(
                                DivergencePoint(
                                    kind=DivergenceKind.T1_T3_MISMATCH,
                                    severity="HIGH",
                                    evidence_ids=(e1_ref, *conflicting_t3),
                                    suggested_task=VerifiedRef("RECHECK"),
                                    code_token=VerifiedRef("REACTION:ALERT_DIFF"),
                                )
                            )
                            emitted_any_mismatch = True

            if t1.finding is Finding.ABSENT and not emitted_any_mismatch:
                points.append(
                    DivergencePoint(
                        kind=DivergenceKind.T1_T3_MISMATCH,
                        severity="HIGH",
                        evidence_ids=(e1_ref, *passing_t3_refs),
                        suggested_task=VerifiedRef("RECHECK"),
                        code_token=VerifiedRef("FINDING:ABSENT"),
                    )
                )

    # 5. COMPLIANT chỉ theo hành vi (có T3 PASS nhưng không có T1, hoặc độ phủ đã thu nhưng không liên kết T1).
    if passing_t3:
        if not t1_pairs:
            points.append(
                DivergencePoint(
                    kind=DivergenceKind.NO_CODE_LINK,
                    severity="MEDIUM",
                    evidence_ids=tuple(VerifiedRef(e3.evidence_id) for e3, _ in passing_t3),
                    suggested_task=VerifiedRef("LOCATE"),
                    code_token=VerifiedRef("behavioral_only:no_t1"),
                )
            )
        else:
            coverage_checked = any(t3.coverage_link is not None for _, t3 in t3_pairs)
            has_link = any(t3.coverage_link is not None and t3.coverage_link.linked for _, t3 in passing_t3)
            if coverage_checked and not has_link:
                points.append(
                    DivergencePoint(
                        kind=DivergenceKind.NO_CODE_LINK,
                        severity="MEDIUM",
                        evidence_ids=(
                            *(VerifiedRef(e1.evidence_id) for e1, _ in t1_pairs),
                            *(VerifiedRef(e3.evidence_id) for e3, _ in passing_t3),
                        ),
                        suggested_task=VerifiedRef("LOCATE"),
                        code_token=VerifiedRef("coverage:unlinked"),
                    )
                )

    return tuple(points)


def extract_divergence_points(
    rfc_sentence: str | None,
    t1_items: Sequence[Evidence],
    t3_items: Sequence[Evidence],
) -> Labeled[list[dict[str, Any]]]:
    """Trích xuất điểm phân kỳ dạng bản tóm tắt an toàn IFC (`admissible_to_privileged(...) == True`)."""
    points = collect_divergence_points(rfc_sentence, t1_items, t3_items)
    rows = [point.to_privileged_dict() for point in points]
    return Labeled(rows, TrustLabel.UNTRUSTED)

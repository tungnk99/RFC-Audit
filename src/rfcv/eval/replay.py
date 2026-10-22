"""Replay: tính lại nhãn từ bằng chứng đã lưu và so sánh giữa hai bộ quy tắc.

Dùng để (1) bảo đảm quy tắc mới không đổi nhãn cũ ngoài ý muốn, (2) đánh giá các cấu hình chỉ *lọc* bằng chứng
mà không phải chạy lại SUT (hiệu chỉnh, xem `rfcv.eval.calibration`). Quy tắc là hàm thuần nên replay luôn tái lập được.
Không so sánh nhãn giữa hai `rules_version` khác nhau trong cùng một bảng kết quả: hãy replay cả hai trên cùng bằng chứng.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from rfcv.evidence.models import Evidence
from rfcv.evidence.verdict_engine import RequirementView, RuleSet, StopReason, VerdictRecord, decide


@dataclass(frozen=True)
class LabelChange:
    requirement_id: str
    old_label: str
    old_rule: str
    new_label: str
    new_rule: str


def replay(
    evidence: Sequence[Evidence],
    req: RequirementView,
    rules: RuleSet,
    stop_reason: StopReason = StopReason.SUFFICIENT,
) -> VerdictRecord:
    return decide(req, evidence, stop_reason, rules)


def diff_labels(old: Mapping[str, VerdictRecord], new: Mapping[str, VerdictRecord]) -> list[LabelChange]:
    """Các yêu cầu có (nhãn, quy tắc) khác nhau giữa hai bảng; yêu cầu chỉ có ở một bên bị coi là khác."""
    changes: list[LabelChange] = []
    for rid in sorted(old.keys() | new.keys()):
        a, b = old.get(rid), new.get(rid)
        a_key = (a.label.value, a.rule) if a else ("<thiếu>", "")
        b_key = (b.label.value, b.rule) if b else ("<thiếu>", "")
        if a_key != b_key:
            changes.append(LabelChange(rid, a_key[0], a_key[1], b_key[0], b_key[1]))
    return changes

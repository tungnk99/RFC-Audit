"""Kiểm tra tiền điều kiện tham chiếu (Reference Sanity Pre-Check) cho đề xuất RBS của RFC Analyst.

Phát hiện sớm lỗi đặc tả trước khi chạy toàn bộ vòng điều tra trên SUT (đặc biệt CT-26):
- Nếu MỌI bản tham chiếu độc lập (OpenSSL, GnuTLS...) đều từ chối biến thể phía hợp lệ (`valid`/`at_limit`),
  khẳng định phía hợp lệ trong RBS có khả năng sai thực tế giao thức → `SUSPECT_VALID_SIDE`.
- Nếu MỌI bản tham chiếu độc lập đều thất bại trên biến thể phía kích hoạt (`trigger`), oracle kích hoạt
  không có nhân chứng dương → `SUSPECT_TRIGGER_SIDE`.
- Nếu các bản tham chiếu đồng thuận PASS trên cả hai phía `valid` và `trigger` → `ACCEPTED`.
- Nếu thiếu một phía hoặc các bản tham chiếu bất đồng nhau → `INCONCLUSIVE`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

__all__ = [
    "PrecheckResult",
    "PrecheckStatus",
    "ReferenceObservation",
    "sanity_precheck_rbs",
]


class PrecheckStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    SUSPECT_VALID_SIDE = "SUSPECT_VALID_SIDE"
    SUSPECT_TRIGGER_SIDE = "SUSPECT_TRIGGER_SIDE"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class ReferenceObservation:
    """Quan sát từ một triển khai tham chiếu độc lập trên một biến thể của RBS."""

    ref_name: str
    side: Literal["valid", "trigger"]
    variant: str
    passed: bool
    observed_alert: str | None = None


@dataclass(frozen=True)
class PrecheckResult:
    """Kết quả kiểm tra tiền điều kiện tham chiếu đối với một yêu cầu RBS."""

    requirement_id: str
    status: PrecheckStatus
    reason_code: str
    failed_refs: tuple[str, ...]
    details: tuple[str, ...]


def _group_by_variant(observations: Sequence[ReferenceObservation]) -> dict[str, list[ReferenceObservation]]:
    grouped: dict[str, list[ReferenceObservation]] = defaultdict(list)
    for obs in observations:
        grouped[obs.variant].append(obs)
    return dict(grouped)


def _format_ref_list(observations: Sequence[ReferenceObservation]) -> str:
    parts: list[str] = []
    for obs in sorted(observations, key=lambda item: item.ref_name):
        if obs.observed_alert:
            parts.append(f"{obs.ref_name}({obs.observed_alert})")
        else:
            parts.append(obs.ref_name)
    return ", ".join(parts)


def sanity_precheck_rbs(
    requirement_id: str,
    observations: Sequence[ReferenceObservation],
) -> PrecheckResult:
    """Đánh giá độ lành mạnh của đề xuất RBS dựa trên quan sát từ các triển khai tham chiếu độc lập."""
    if not observations:
        return PrecheckResult(
            requirement_id=requirement_id,
            status=PrecheckStatus.INCONCLUSIVE,
            reason_code="NO_OBSERVATIONS",
            failed_refs=(),
            details=("không có quan sát nào từ triển khai tham chiếu",),
        )

    valid_obs = [obs for obs in observations if obs.side == "valid"]
    trigger_obs = [obs for obs in observations if obs.side == "trigger"]

    # 1. Phía kích hoạt: nếu mọi tham chiếu đều FAIL trên ít nhất một biến thể trigger → oracle kích hoạt nghi ngờ.
    trigger_all_failed_details: list[str] = []
    trigger_failed_refs: set[str] = set()
    for variant, group in sorted(_group_by_variant(trigger_obs).items()):
        if all(not obs.passed for obs in group):
            trigger_failed_refs.update(obs.ref_name for obs in group)
            trigger_all_failed_details.append(
                f"trigger variant '{variant}' failed on all {len(group)} reference(s): {_format_ref_list(group)}"
            )
    if trigger_all_failed_details:
        return PrecheckResult(
            requirement_id=requirement_id,
            status=PrecheckStatus.SUSPECT_TRIGGER_SIDE,
            reason_code="ALL_REFS_FAIL_TRIGGER",
            failed_refs=tuple(sorted(trigger_failed_refs)),
            details=tuple(trigger_all_failed_details),
        )

    # 2. Phía hợp lệ (CT-26): nếu mọi tham chiếu độc lập đều từ chối biến thể valid/at_limit → phía hợp lệ sai.
    valid_all_rejected_details: list[str] = []
    valid_failed_refs: set[str] = set()
    for variant, group in sorted(_group_by_variant(valid_obs).items()):
        if all(not obs.passed for obs in group):
            valid_failed_refs.update(obs.ref_name for obs in group)
            valid_all_rejected_details.append(
                f"valid variant '{variant}' rejected by all {len(group)} reference(s): {_format_ref_list(group)}"
            )
    if valid_all_rejected_details:
        return PrecheckResult(
            requirement_id=requirement_id,
            status=PrecheckStatus.SUSPECT_VALID_SIDE,
            reason_code="CT26_ALL_REFS_REJECT_VALID",
            failed_refs=tuple(sorted(valid_failed_refs)),
            details=tuple(valid_all_rejected_details),
        )

    # 3. Cần đủ cả hai phía valid và trigger để kết luận ACCEPTED.
    if not valid_obs:
        return PrecheckResult(
            requirement_id=requirement_id,
            status=PrecheckStatus.INCONCLUSIVE,
            reason_code="MISSING_VALID_SIDE",
            failed_refs=tuple(sorted({obs.ref_name for obs in trigger_obs if not obs.passed})),
            details=("thiếu quan sát phía hợp lệ (valid/at_limit) từ triển khai tham chiếu",),
        )
    if not trigger_obs:
        return PrecheckResult(
            requirement_id=requirement_id,
            status=PrecheckStatus.INCONCLUSIVE,
            reason_code="MISSING_TRIGGER_SIDE",
            failed_refs=tuple(sorted({obs.ref_name for obs in valid_obs if not obs.passed})),
            details=("thiếu quan sát phía kích hoạt (trigger) từ triển khai tham chiếu",),
        )

    # 4. Bất đồng một phần giữa các bản tham chiếu (có bản PASS, có bản FAIL trên cùng một biến thể).
    disagreements: list[str] = []
    disagreed_refs: set[str] = set()
    for side, side_obs in (("trigger", trigger_obs), ("valid", valid_obs)):
        for variant, group in sorted(_group_by_variant(side_obs).items()):
            failed = [obs for obs in group if not obs.passed]
            if failed:
                disagreed_refs.update(obs.ref_name for obs in failed)
                disagreements.append(
                    f"{side} variant '{variant}' disagreed ({len(failed)}/{len(group)} failed): "
                    f"{_format_ref_list(failed)}"
                )
    if disagreements:
        return PrecheckResult(
            requirement_id=requirement_id,
            status=PrecheckStatus.INCONCLUSIVE,
            reason_code="REFERENCES_DISAGREE",
            failed_refs=tuple(sorted(disagreed_refs)),
            details=tuple(disagreements),
        )

    # 5. Mọi bản tham chiếu đều đồng thuận trên cả hai phía valid và trigger.
    agreed_refs = sorted({obs.ref_name for obs in observations})
    return PrecheckResult(
        requirement_id=requirement_id,
        status=PrecheckStatus.ACCEPTED,
        reason_code="REFERENCES_AGREE",
        failed_refs=(),
        details=(
            f"all {len(agreed_refs)} reference(s) ({', '.join(agreed_refs)}) agreed across "
            f"{len(valid_obs)} valid and {len(trigger_obs)} trigger observation(s)",
        ),
    )

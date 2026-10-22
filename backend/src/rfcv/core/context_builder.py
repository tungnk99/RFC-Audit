"""Context builder: dựng ngữ cảnh mỗi lần gọi agent theo hồ sơ vai trò (thiết kế chính, Bảng 17).

Bất biến:
- không đưa vào trường mà hồ sơ vai trò không khai báo;
- agent đặc quyền không bao giờ nhận chuỗi tự do mang nhãn UNTRUSTED (IFC, Bảng 8).
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterable, Mapping, Sequence
from enum import Enum
from typing import Any

from pydantic import BaseModel

from rfcv.core.envelope import Envelope
from rfcv.core.ifc import IFCViolation, Labeled, TrustLabel, VerifiedRef, admissible_to_privileged
from rfcv.core.policy import PolicyStore, Zone
from rfcv.evidence.models import Evidence
from rfcv.plugins import current_registry


def to_jsonable(value: Any) -> Any:
    match value:
        case BaseModel():
            return value.model_dump(mode="json")
        case Enum():
            return value.value
        case _ if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
        case Mapping():
            return {str(k): to_jsonable(v) for k, v in value.items()}  # type: ignore[union-attr]
        case list() | tuple() | set() | frozenset():
            return [to_jsonable(v) for v in value]  # type: ignore[union-attr]
        case _:
            return value


class ContextBuilder:
    def __init__(self, policy: PolicyStore) -> None:
        self._policy = policy

    def build(self, role: str, available: Mapping[str, Labeled[Any]]) -> dict[str, Any]:
        profile = self._policy.profile(role)
        out: dict[str, Any] = {}
        for name in profile.context_fields:
            item = available.get(name)
            if item is None:
                continue
            if profile.zone is Zone.PRIVILEGED and not admissible_to_privileged(item):
                raise IFCViolation(f"{role}: trường {name} mang chuỗi UNTRUSTED tự do")
            out[name] = {"label": item.label.name, "value": to_jsonable(item.value)}
        return out

    @staticmethod
    def render(envelope: Envelope, context: Mapping[str, Any]) -> str:
        return json.dumps(
            {
                "msg_id": envelope.msg_id,
                "requirement_id": envelope.requirement_id,
                "round": envelope.round,
                "task": envelope.body,
                "context": context,
                "budget_left": envelope.budget_left,
            },
            ensure_ascii=False,
            indent=1,
        )


def summarize_evidence(evidence: Sequence[Evidence], vocabulary_terms: Iterable[str]) -> Labeled[list[dict[str, Any]]]:
    """Bản tóm tắt bằng chứng cho agent đặc quyền: chỉ giá trị miền hữu hạn hoặc đã đối chiếu.

    Cách tóm tắt từng loại bằng chứng do chính loại đó khai báo (`EvidenceKind.summarize`), nên lõi không
    biết trường nào của miền là an toàn. Giá trị chuỗi chỉ qua được khi đã thành `VerifiedRef`
    (đối chiếu với chỉ mục hoặc từ vựng adapter); phần còn lại bị IFC chặn ở Context builder.
    """
    kinds = current_registry().kinds
    terms = frozenset(vocabulary_terms)
    rows = [
        {"evidence_id": VerifiedRef(e.evidence_id), "tier": VerifiedRef(str(e.tier)), "polarity": e.polarity}
        | kinds[str(getattr(e.payload, "kind", ""))].summarize(e, terms)
        for e in evidence
    ]
    return Labeled(rows, TrustLabel.UNTRUSTED)

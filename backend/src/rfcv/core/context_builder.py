"""Context builder: dựng ngữ cảnh mỗi lần gọi agent theo hồ sơ vai trò (thiết kế chính, Bảng 17).

Bất biến:
- không đưa vào trường mà hồ sơ vai trò không khai báo;
- agent đặc quyền không bao giờ nhận chuỗi tự do mang nhãn UNTRUSTED (IFC, Bảng 8).
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Collection, Iterable, Mapping, Sequence
from enum import Enum
from typing import Any

from pydantic import BaseModel

from rfcv.core.envelope import Envelope
from rfcv.core.ifc import IFCViolation, Labeled, TrustLabel, VerifiedRef, admissible_to_privileged
from rfcv.core.policy import PolicyStore, Zone
from rfcv.evidence.models import Evidence
from rfcv.plugins import current_registry
from rfcv.spi import EvidenceKind


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


def summarize_evidence(
    evidence: Sequence[Evidence], vocabulary_terms: Iterable[str], keep: Collection[str] = ()
) -> Labeled[list[dict[str, Any]]]:
    """Bản tóm tắt bằng chứng cho agent đặc quyền: chỉ giá trị miền hữu hạn hoặc đã đối chiếu.

    Cách tóm tắt từng loại bằng chứng do chính loại đó khai báo (`EvidenceKind.summarize`), nên lõi không
    biết trường nào của miền là an toàn. Giá trị chuỗi chỉ qua được khi đã thành `VerifiedRef`
    (đối chiếu với chỉ mục hoặc từ vựng adapter); phần còn lại bị IFC chặn ở Context builder.

    Hàng "thường" của loại có khai báo `is_routine` được gộp (xem `EvidenceKind.fold_fields`) để bản tóm tắt không
    tăng tuyến tính theo số biến thể thử. Bằng chứng trong `keep` (được nhãn tạm hay xung đột trích dẫn) không bị gộp.
    """
    kinds = current_registry().kinds
    terms = frozenset(vocabulary_terms)
    pinned = frozenset(keep)
    entries: list[tuple[dict[str, Any], EvidenceKind, str | None]] = []  # (hàng, loại, khoá nhóm; None = không gộp)
    groups: dict[str, list[dict[str, Any]]] = {}
    for e in evidence:
        kind = kinds[str(getattr(e.payload, "kind", ""))]
        row = {
            "evidence_id": VerifiedRef(e.evidence_id),
            "tier": VerifiedRef(str(e.tier)),
            "polarity": e.polarity,
        } | kind.summarize(e, terms)
        key: str | None = None
        if kind.is_routine is not None and kind.is_routine(e) and e.evidence_id not in pinned:
            shared = sorted((k, v) for k, v in row.items() if k != "evidence_id" and k not in kind.fold_fields)
            key = f"{kind.name}|{shared!r}"
            groups.setdefault(key, []).append(row)
        entries.append((row, kind, key))
    out: list[dict[str, Any]] = []
    emitted: set[str] = set()
    for row, kind, key in entries:
        if key is None:
            out.append(row)
        elif key not in emitted:
            emitted.add(key)
            members = groups[key]
            out.append(row if len(members) == 1 else _fold(members, kind.fold_fields))
    return Labeled(out, TrustLabel.UNTRUSTED)


def _fold(members: Sequence[dict[str, Any]], fold_fields: Sequence[str]) -> dict[str, Any]:
    """Một hàng thay cho nhiều hàng giống nhau trừ `fold_fields`: giữ phần chung, thêm `count`, `evidence_ids` và danh
    sách giá trị của từng trường gộp (vẫn trích dẫn được từng bằng chứng)."""
    first = members[0]
    folded = {k: v for k, v in first.items() if k != "evidence_id" and k not in fold_fields}
    folded["count"] = len(members)
    folded["evidence_ids"] = [m["evidence_id"] for m in members]
    for name in fold_fields:
        if name in first:
            folded[name] = [m[name] for m in members]
    return folded

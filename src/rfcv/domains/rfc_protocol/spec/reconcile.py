"""So khớp hai luồng RBS độc lập theo cấu trúc (M2). Lệch nhau thì chuyển cho Auditor duyệt."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rfcv.domains.rfc_protocol.spec.rbs import RBS

_IGNORED = {"requirement_id"}


@dataclass(frozen=True)
class Agreement:
    agree: bool
    diffs: tuple[str, ...]


def _normalize(rbs: RBS) -> dict[str, Any]:
    data = rbs.model_dump(mode="json")
    for key in _IGNORED:
        data.pop(key, None)
    # Thứ tự liệt kê biến thể và hành vi bị cấm không mang nghĩa.
    data["variants"] = sorted(data["variants"], key=repr)
    data["forbid"] = sorted(data["forbid"], key=repr)
    data["accept_alternatives"] = sorted(data["accept_alternatives"], key=repr)
    return data


def reconcile(a: RBS, b: RBS) -> Agreement:
    na, nb = _normalize(a), _normalize(b)
    diffs = tuple(sorted(k for k in na.keys() | nb.keys() if na.get(k) != nb.get(k)))
    return Agreement(agree=not diffs, diffs=diffs)

"""Schema gate (lõi): kiểm tra đầu ra agent theo schema đã đăng ký (giao diện I3).

Không "sửa hộ" dữ liệu sai schema: sai thì trả lỗi có cấu trúc để agent làm lại (tối đa hai lần).
Các kiểm tra đối chiếu với nguồn dữ liệu của từng miền (ví dụ vị trí mã với chỉ mục) do domain pack cài đặt
và dùng lại `GateResult`.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from rfcv.evidence.models import EvidenceDraft
from rfcv.plugins import current_registry


@dataclass(frozen=True)
class GateResult:
    accepted: bool
    errors: tuple[str, ...] = ()
    draft: EvidenceDraft | None = None


def validate_output(schema: str, raw: object) -> tuple[BaseModel | None, tuple[str, ...]]:
    model = current_registry().schemas[schema]
    try:
        return (raw if isinstance(raw, model) else model.model_validate(raw)), ()
    except ValidationError as exc:
        return None, tuple(f"{'.'.join(map(str, e['loc']))}: {e['type']}" for e in exc.errors())

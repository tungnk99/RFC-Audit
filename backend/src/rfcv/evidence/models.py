"""Bằng chứng bất biến: lớp vỏ tổng quát. Loại bằng chứng cụ thể do domain pack đăng ký (rfcv.spi.EvidenceKind).

Bất biến lõi (không phụ thuộc miền):
- một bằng chứng thuộc đúng một loại đã đăng ký; tầng phải khớp loại;
- chỉ thành phần tất định khai trong loại đó (`producers`) mới được ghi;
- chiều (SUPPORTS/REFUTES/NEUTRAL) tính tất định từ payload, không do agent khai.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny, field_validator, model_validator

from rfcv.plugins import current_registry
from rfcv.spi import Polarity

__all__ = ["Evidence", "EvidenceDraft", "Polarity", "polarity_of"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def polarity_of(payload: BaseModel) -> Polarity:
    return current_registry().kinds[_kind_name(payload)].polarity(payload)


def _kind_name(payload: BaseModel) -> str:
    name: object = getattr(payload, "kind", None)
    if not isinstance(name, str):
        raise ValueError("payload thiếu trường 'kind' dạng chuỗi")
    return name


class EvidenceDraft(_Frozen):
    """Bằng chứng trước khi vào chuỗi hash."""

    run_id: str
    requirement_id: str
    tier: str
    payload: SerializeAsAny[BaseModel]
    produced_by: str
    requested_by: dict[str, str] | None = None
    provenance: dict[str, str] = Field(default_factory=dict)
    ifc: Literal["TRUSTED", "DERIVED", "UNTRUSTED"] = "UNTRUSTED"

    @field_validator("payload", mode="before")
    @classmethod
    def _resolve_payload(cls, value: Any) -> Any:
        if isinstance(value, dict):
            data = cast(dict[str, Any], value)
            kinds = current_registry().kinds
            name = str(data.get("kind"))
            if name not in kinds:
                raise ValueError(f"loại bằng chứng '{name}' chưa đăng ký")
            return kinds[name].model.model_validate(data)
        return value

    @model_validator(mode="after")
    def _check_kind(self) -> EvidenceDraft:
        name = _kind_name(self.payload)
        kinds = current_registry().kinds
        if name not in kinds:
            raise ValueError(f"loại bằng chứng '{name}' chưa đăng ký")
        kind = kinds[name]
        if not isinstance(self.payload, kind.model):
            raise ValueError(f"payload '{name}' phải là {kind.model.__name__}")
        if str(self.tier) != str(kind.tier):
            raise ValueError(f"payload {name} thuộc {kind.tier}, không phải {self.tier}")
        if self.produced_by not in kind.producers:
            raise ValueError(f"'{self.produced_by}' không được phép ghi bằng chứng loại '{name}'")
        return self


class Evidence(EvidenceDraft):
    evidence_id: str
    prev_hash: str
    polarity: Polarity
    kind_schema: str = ""  # "<loại>@<phiên bản>" tại thời điểm ghi; dùng để nâng cấp dữ liệu cũ khi đọc

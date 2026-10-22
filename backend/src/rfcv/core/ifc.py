"""Kiểm soát luồng thông tin: nhãn tin cậy và lan truyền (thiết kế chính, Bảng 8; mẫu Dual LLM của CaMeL).

- TRUSTED: đầu vào của người kiểm chứng (RFC, adapter đã kiểm định, cấu hình).
- DERIVED: đầu ra đã qua Schema gate của agent đặc quyền, tạo từ TRUSTED/DERIVED.
- UNTRUSTED: mọi thứ từ kho mã, từ SUT, mọi đầu ra của vùng cách ly.

Giá trị tính từ ít nhất một giá trị UNTRUSTED mang nhãn UNTRUSTED (join lấy nhãn xấu nhất).
Giá trị UNTRUSTED chỉ vào ngữ cảnh agent đặc quyền khi thuộc miền hữu hạn hoặc đã đối chiếu
(VerifiedRef); chuỗi tự do thì không bao giờ.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Any

from pydantic import BaseModel


class TrustLabel(IntEnum):
    TRUSTED = 0
    DERIVED = 1
    UNTRUSTED = 2


def join(*labels: TrustLabel) -> TrustLabel:
    return max(labels, default=TrustLabel.TRUSTED)


class VerifiedRef(str):
    """Chuỗi từ vùng không tin cậy đã được đối chiếu với một miền đóng
    (ký hiệu và đường dẫn có trong chỉ mục, giá trị có trong từ vựng adapter)."""

    __slots__ = ()


@dataclass(frozen=True)
class Labeled[T]:
    value: T
    label: TrustLabel

    def derive[U](self, value: U, *others: Labeled[Any]) -> Labeled[U]:
        """Kết quả tính từ self (và others) không bao giờ đáng tin hơn đầu vào."""
        return Labeled(value, join(self.label, *(o.label for o in others)))


class IFCViolation(PermissionError):
    pass


def finite_domain(value: Any) -> bool:
    """True nếu giá trị không thể chở chỉ thị: số, bool, enum, VerifiedRef, hoặc cấu trúc chỉ gồm chúng."""
    match value:
        case None | bool() | int() | float() | Enum() | VerifiedRef():
            return True
        case str():
            return False
        case BaseModel():
            return finite_domain(value.model_dump())
        case Mapping():
            return all(isinstance(k, str | Enum) and finite_domain(v) for k, v in value.items())  # type: ignore[union-attr]
        case list() | tuple() | set() | frozenset():
            return all(finite_domain(v) for v in value)  # type: ignore[union-attr]
        case _:
            return False


def admissible_to_privileged(v: Labeled[Any]) -> bool:
    return v.label is not TrustLabel.UNTRUSTED or finite_domain(v.value)

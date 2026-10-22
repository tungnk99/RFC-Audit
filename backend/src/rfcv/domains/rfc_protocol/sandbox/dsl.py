"""DSL kịch bản dùng chung cho mọi giao thức (tài liệu adapter, Bảng 4) và phần kiểm tra chung của backend.

Thao tác là chung; mỗi backend khai báo thao tác nào nó dịch được, tham số hợp lệ của từng thao tác và miền giá trị của
các tham số có miền hữu hạn. Không có lệnh hệ thống, không có biểu thức tuỳ ý: mọi chuỗi bắt đầu bằng `$` phải là biến đã
gắn vào giá trị biến thể.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from rfcv.domains.rfc_protocol.sandbox.backend import ValidationResult
from rfcv.domains.rfc_protocol.schemas import ScenarioProposal

# Thao tác của DSL (Bảng 4). `send_raw_record` là đơn vị thô của giao thức: bản ghi TLS, khung HTTP/2, gói QUIC,
# thông điệp DNS, gói nhị phân SSH.
OPS = ("connect", "complete_handshake", "send_msg", "send_raw_record", "mutate", "reorder", "repeat", "expect")


@dataclass(frozen=True)
class DslSpec:
    """Phần DSL một backend dịch được: thao tác → tham số hợp lệ, và tham số → giá trị được phép (nếu hữu hạn)."""

    ops: Mapping[str, frozenset[str]]
    values: Mapping[str, frozenset[str]] = field(default_factory=dict[str, frozenset[str]])
    notes: Mapping[str, str] = field(default_factory=dict[str, str])  # ý nghĩa thao tác với giao thức này

    def __post_init__(self) -> None:
        unknown = set(self.ops) - set(OPS)
        if unknown:
            raise ValueError(f"thao tác ngoài DSL: {sorted(unknown)}")

    def validate(self, scenario: ScenarioProposal) -> ValidationResult:
        errors: list[str] = []
        bound = set(scenario.bindings)
        for i, step in enumerate(scenario.steps):
            allowed = self.ops.get(step.op)
            if allowed is None:
                errors.append(
                    f"bước {i}: thao tác {step.op} không có trong DSL của backend này ({', '.join(self.ops)})"
                )
                continue
            for key, value in step.args.items():
                if key not in allowed:
                    errors.append(f"bước {i}: tham số {key} không hợp lệ cho {step.op} (có: {sorted(allowed)})")
                    continue
                if isinstance(value, str) and value.startswith("$"):
                    if value[1:] not in bound:
                        errors.append(f"bước {i}: biến {value} không được gắn (bindings)")
                elif isinstance(value, str) and key in self.values and value not in self.values[key]:
                    errors.append(f"bước {i}: {key} phải thuộc {sorted(self.values[key])}")
        if not any(s.op == "expect" for s in scenario.steps):
            errors.append("kịch bản phải kết thúc bằng một bước expect")
        return ValidationResult(not errors, tuple(errors))

    def describe(self) -> dict[str, Any]:
        """Dạng gửi cho Test Agent: thao tác, tham số, giá trị được phép, ý nghĩa."""
        return {
            "ops": {op: sorted(args) for op, args in self.ops.items()},
            "values": {k: sorted(v) for k, v in self.values.items()},
            "notes": dict(self.notes),
        }

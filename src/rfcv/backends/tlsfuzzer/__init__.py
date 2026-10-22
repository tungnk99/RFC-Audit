"""Backend TLS dựa trên tlsfuzzer + tlslite-ng (backend chính cho tầng 1).

Kịch bản trừu tượng (ScenarioProposal) được dịch sang đồ thị hội thoại của tlsfuzzer
(ClientHelloGenerator, ExpectServerHello, ExpectAlert…); đồ thị này bản thân đã là một DSL giới hạn.
Quan sát được chuẩn hoá thành Observation@1 với các trường miền hữu hạn.

Trạng thái: validate() đã cài đặt; run() và sanity() dựng ở tuần 1 tháng 11 (tài liệu adapter, Bảng 12),
chạy trong container test-driver, phiên bản tlsfuzzer/tlslite-ng cố định theo commit.
"""

from __future__ import annotations

from rfcv.domains.rfc_protocol.sandbox.backend import Endpoint, EventTrace, ValidationResult
from rfcv.domains.rfc_protocol.schemas import ScenarioProposal

# Thao tác DSL được phép (tài liệu adapter, Bảng 4). Không có lệnh hệ thống, không có biểu thức tuỳ ý.
ALLOWED_OPS = {
    "connect": set[str](),
    "complete_handshake": {"version", "cipher"},
    "send_msg": {"type", "fields"},
    "send_raw_record": {"content_type", "type", "length", "body", "encrypted"},
    "mutate": {"field", "op", "value"},
    "reorder": {"msgs"},
    "repeat": {"msg"},
    "expect": {"within_ms", "until", "timeout_ms"},
}
_BODIES = {"zeros", "random", "valid"}


class TlsfuzzerBackend:
    name = "tlsfuzzer"

    def validate(self, scenario: ScenarioProposal) -> ValidationResult:
        errors: list[str] = []
        bound = set(scenario.bindings)
        for i, step in enumerate(scenario.steps):
            allowed = ALLOWED_OPS.get(step.op)
            if allowed is None:
                errors.append(f"bước {i}: thao tác {step.op} không có trong DSL")
                continue
            for key, value in step.args.items():
                if key not in allowed:
                    errors.append(f"bước {i}: tham số {key} không hợp lệ cho {step.op}")
                if isinstance(value, str) and value.startswith("$") and value[1:] not in bound:
                    errors.append(f"bước {i}: biến {value} không được gắn (bindings)")
            body = step.args.get("body")
            if isinstance(body, str) and body not in _BODIES:
                errors.append(f"bước {i}: body phải thuộc {sorted(_BODIES)}")
        if not any(s.op == "expect" for s in scenario.steps):
            errors.append("kịch bản phải kết thúc bằng một bước expect")
        return ValidationResult(not errors, tuple(errors))

    async def sanity(self, endpoint: Endpoint) -> bool:
        raise NotImplementedError("chạy ca sanity của tlsfuzzer trong container test-driver")

    async def run(
        self, scenario: ScenarioProposal, params: dict[str, int | str], endpoint: Endpoint, seed: int
    ) -> EventTrace:
        raise NotImplementedError("dịch ScenarioProposal sang đồ thị hội thoại tlsfuzzer và chuẩn hoá quan sát")

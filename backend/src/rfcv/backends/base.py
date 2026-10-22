"""Khung chung cho backend dịch DSL kịch bản sang thư viện kiểm thử của một giao thức.

Phần kiểm tra kịch bản (validate) là dữ liệu khai báo (`DslSpec`) nên cài đặt được ngay. `sanity` và `run` chạy trong
container test-driver cạnh SUT (tài liệu adapter, Bảng 12); chưa có Docker thì báo NotImplementedError, Test driver
ghi lỗi môi trường chứ không ghi FAIL cho SUT.
"""

from __future__ import annotations

from rfcv.domains.rfc_protocol.sandbox.backend import Endpoint, EventTrace, ValidationResult
from rfcv.domains.rfc_protocol.sandbox.dsl import DslSpec
from rfcv.domains.rfc_protocol.schemas import ScenarioProposal

BODIES = frozenset({"zeros", "random", "valid"})
MUTATIONS = frozenset({"set", "truncate", "append_bytes", "duplicate"})  # Bảng 4: mutate(field, op)
EXPECT_ARGS = frozenset({"within_ms", "until", "timeout_ms"})


class DslBackend:
    name: str
    dsl: DslSpec
    runner: str  # thư viện mà run() dịch kịch bản sang

    def validate(self, scenario: ScenarioProposal) -> ValidationResult:
        return self.dsl.validate(scenario)

    async def sanity(self, endpoint: Endpoint) -> bool:
        raise NotImplementedError(f"chạy ca sanity của {self.name} trong container test-driver")

    async def run(
        self, scenario: ScenarioProposal, params: dict[str, int | str], endpoint: Endpoint, seed: int
    ) -> EventTrace:
        raise NotImplementedError(f"dịch ScenarioProposal sang {self.runner} và chuẩn hoá quan sát (Observation@1)")

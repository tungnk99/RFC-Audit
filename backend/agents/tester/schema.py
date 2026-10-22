"""Đầu ra của Test: kịch bản trừu tượng trong DSL giới hạn (backend dịch sang dạng gốc của công cụ)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from agents.common import Out


class ScenarioStep(Out):
    op: Literal[
        "connect",
        "complete_handshake",
        "send_msg",
        "send_raw_record",
        "mutate",
        "reorder",
        "repeat",
        "expect",
    ]
    args: dict[str, str | int | bool] = Field(default_factory=dict)


class ScenarioProposal(Out):
    requirement_id: str
    reach_state: str
    steps: list[ScenarioStep] = Field(min_length=1)
    bindings: dict[str, Literal["from_variant"]] = Field(default_factory=dict)
    example_id: str | None = Field(default=None, description="Mẫu trong thư viện ví dụ của adapter, nếu dựa trên mẫu.")

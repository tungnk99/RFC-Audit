"""Hợp đồng giữa hub và thành phần chạy agent. Hub chỉ biết Protocol này, không biết framework agent nào."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from rfcv.core.envelope import Envelope
from rfcv.gates.tool_gateway import ToolSession


@dataclass(frozen=True)
class RoleOutcome:
    output: BaseModel | None
    tokens: int
    failure: str | None = None


class RoleRunner(Protocol):
    async def run(self, envelope: Envelope, context: dict[str, Any], session: ToolSession) -> RoleOutcome: ...

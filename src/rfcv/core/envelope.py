"""Phong bì thông điệp (giao diện I1; thiết kế chính, mục 4.2).

Agent chỉ điền body. Mọi trường khác do Execution loop gán, nên agent không giả danh được vai trò khác.
"""

from __future__ import annotations

import itertools
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class MessageKind(StrEnum):
    DISPATCH = "dispatch"
    RESULT = "result"
    TOOL_CALL = "tool_call"
    STOP = "stop"


class Envelope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    msg_id: str
    run_id: str
    requirement_id: str
    from_role: str
    to_role: str
    kind: MessageKind
    round: int
    body: dict[str, Any]
    budget_left: dict[str, int]


class EnvelopeFactory:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._counter = itertools.count(1)

    def make(
        self,
        *,
        requirement_id: str,
        from_role: str,
        to_role: str,
        kind: MessageKind,
        round: int,
        body: dict[str, Any],
        budget_left: dict[str, int],
    ) -> Envelope:
        return Envelope(
            msg_id=f"m-{next(self._counter):06d}",
            run_id=self.run_id,
            requirement_id=requirement_id,
            from_role=from_role,
            to_role=to_role,
            kind=kind,
            round=round,
            body=body,
            budget_left=budget_left,
        )

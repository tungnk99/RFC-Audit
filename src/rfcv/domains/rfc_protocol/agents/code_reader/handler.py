"""Handler của Code Reader: LocationClaim → Schema gate → T1 → liên kết độ phủ. Agent không ghi bằng chứng; cổng mới ghi."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from rfcv.core.execution_loop import Investigation
from rfcv.domains.rfc_protocol.agents.code_reader.schema import LocationClaim
from rfcv.domains.rfc_protocol.coverage_linker import link_pending
from rfcv.domains.rfc_protocol.schema_gate import SchemaGate
from rfcv.gates.tool_gateway import ToolSession


class LocationHandler:
    """LOCATE, TRACE_PATHS, RECHECK."""

    def __init__(self, rt: Any, gate: SchemaGate) -> None:
        self._rt = rt
        self._gate = gate

    async def handle(
        self, inv: Investigation, task: Any, output: BaseModel | None, session: ToolSession, msg_id: str
    ) -> int:
        if not isinstance(output, LocationClaim):
            return 0
        req_id = inv.requirement.requirement_id
        result = self._gate.check_location(
            output, session, run_id=self._rt.run_id, requirement_id=req_id, msg_id=msg_id
        )
        if not result.accepted or result.draft is None:
            self._rt.trace.append(
                self._rt.run_id,
                "gate_reject",
                {"gate": "schema_gate", "msg_id": msg_id, "errors": list(result.errors)},
                role=session.role,
                requirement_id=req_id,
            )
            return 0
        self._rt.store.append(result.draft)
        return 1 + link_pending(self._rt.store, self._rt.artifacts, self._rt.run_id, req_id)

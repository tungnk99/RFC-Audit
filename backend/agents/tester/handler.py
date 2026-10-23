"""Handler của Test: ScenarioProposal → Test driver (nhân chứng, chạy lại) → T3 → liên kết độ phủ."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agents.common import ORACLE_KEY, RBS_KEY
from agents.tester.schema import ScenarioProposal
from rfcv.core.execution_loop import Investigation
from rfcv.domains.rfc_protocol.coverage_linker import link_pending
from rfcv.domains.rfc_protocol.sandbox.driver import ScenarioRejected, TestDriver
from rfcv.domains.rfc_protocol.scenario_synth import synthesize
from rfcv.domains.rfc_protocol.spec.oracle_compiler import CompiledOracle
from rfcv.gates.tool_gateway import ToolSession


class ScenarioHandler:
    """SELECT_TESTS."""

    def __init__(self, rt: Any, driver: TestDriver, templates_dir: Path | None = None) -> None:
        self._rt = rt
        self._driver = driver
        self._templates = templates_dir

    def synthesize(self, inv: Investigation, task: Any) -> ScenarioProposal | None:
        """Kịch bản dựng tất định từ mẫu adapter khi RBS khớp; hub bỏ qua Tester LLM nếu có. None: để Tester viết."""
        rbs = inv.domain_state.get(RBS_KEY)
        return synthesize(rbs, self._templates) if rbs is not None else None

    async def handle(
        self, inv: Investigation, task: Any, output: BaseModel | None, session: ToolSession, msg_id: str
    ) -> int:
        if not isinstance(output, ScenarioProposal):
            return 0
        req_id = inv.requirement.requirement_id
        oracle: CompiledOracle = inv.domain_state[ORACLE_KEY]
        try:
            evidence = await self._driver.run_requirement(
                run_id=self._rt.run_id,
                oracle=oracle,
                scenario=output,
                seed=self._rt.seed,
                requested_by={"role": session.role, "msg_id": msg_id},
            )
        except ScenarioRejected as exc:
            self._rt.trace.append(
                self._rt.run_id,
                "gate_reject",
                {"gate": "tool_gateway", "msg_id": msg_id, "errors": [str(exc)]},
                role=session.role,
                requirement_id=req_id,
            )
            return 0
        return len(evidence) + link_pending(self._rt.store, self._rt.artifacts, self._rt.run_id, req_id)

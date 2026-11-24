"""Handler của Test: ScenarioProposal → Test driver (nhân chứng, chạy lại) → T3 → liên kết độ phủ."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agents.common import ORACLE_KEY, RBS_KEY
from agents.tester.schema import ScenarioProposal
from rfcv.core.execution_loop import Investigation
from rfcv.domains.rfc_protocol.code_probe import extract_branch_candidates
from rfcv.domains.rfc_protocol.coverage_linker import link_pending
from rfcv.domains.rfc_protocol.payloads import Outcome, T3Payload
from rfcv.domains.rfc_protocol.sandbox.driver import ScenarioRejected, TestDriver
from rfcv.domains.rfc_protocol.scenario_synth import synthesize
from rfcv.domains.rfc_protocol.spec.oracle_compiler import CompiledOracle, ConcreteVariant
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
        total = len(evidence)
        # gen-38 (L5 ADD_STRATEGY — Code-First → Targeted Dynamic Verify):
        # Khi toàn bộ ca kích hoạt hộp đen PASS (chưa phát hiện lỗi), quét hằng số nhánh quanh vị trí phát phản ứng
        # trong kho mã nguồn để sinh biến thể mục tiêu và xác minh lại bằng T3 + bản tham chiếu (bắt lỗi cửa sổ hẹp như U5).
        t3_triggers = [
            e.payload for e in evidence if isinstance(e.payload, T3Payload) and e.payload.side == "trigger"
        ]
        if t3_triggers and all(p.outcome is Outcome.PASS for p in t3_triggers):
            total += await self._run_code_first_probe(inv, oracle, output, session, msg_id)
        return total + link_pending(self._rt.store, self._rt.artifacts, self._rt.run_id, req_id)

    async def _run_code_first_probe(
        self,
        inv: Investigation,
        oracle: CompiledOracle,
        scenario: ScenarioProposal,
        session: ToolSession,
        msg_id: str,
    ) -> int:
        index: Any = getattr(getattr(self._rt, "providers", None), "code_index", None)
        manifest: Any = getattr(self._rt, "manifest", None)
        if index is None or manifest is None or not oracle.expect:
            return 0
        expected_alert = str(oracle.expect[0].args[0]) if oracle.expect[0].args else ""
        field = oracle.where.field if oracle.where is not None else (oracle.variants[0].field if oracle.variants else "")
        if not expected_alert or not field:
            return 0
        existing = [v.value for v in oracle.variants if v.value is not None]
        candidates = extract_branch_candidates(
            index,
            expected_alert=expected_alert,
            field=field,
            existing_values=existing,
            field_domain=manifest.field_domains.get(field),
        )
        if not candidates:
            return 0
        probe_variants = tuple(
            ConcreteVariant(
                name=f"code_probe:{c.field}={c.value}",
                variant_class="required",
                field=c.field,
                value=c.value,
                side=oracle.side_of(c.field, c.value),
            )
            for c in candidates
        )
        probe_oracle = oracle.model_copy(update={"variants": probe_variants})
        try:
            probe_ev = await self._driver.run_requirement(
                run_id=self._rt.run_id,
                oracle=probe_oracle,
                scenario=scenario,
                seed=self._rt.seed,
                requested_by={"role": session.role, "msg_id": msg_id},
            )
        except ScenarioRejected:
            return 0
        fails = sum(
            1 for e in probe_ev if isinstance(e.payload, T3Payload) and e.payload.outcome is Outcome.FAIL
        )
        self._rt.trace.append(
            self._rt.run_id,
            "code_first_probe",
            {
                "field": field,
                "expected_alert": expected_alert,
                "candidates": [
                    {"value": c.value, "file": c.file, "line": c.line, "snippet": c.snippet} for c in candidates
                ],
                "probed": len(probe_ev),
                "fails_found": fails,
            },
            role="execution_loop",
            requirement_id=inv.requirement.requirement_id,
        )
        return len(probe_ev)

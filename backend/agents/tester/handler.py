"""Handler của Test: ScenarioProposal → Test driver (nhân chứng, chạy lại) → T3 → liên kết độ phủ."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agents.common import ORACLE_KEY, RBS_KEY
from agents.tester.schema import ScenarioProposal
from rfcv.core.blackboard import HypothesisEntry
from rfcv.core.execution_loop import Investigation
from rfcv.domains.rfc_protocol.code_probe import CodeProbeCandidate, extract_branch_candidates
from rfcv.domains.rfc_protocol.coverage_linker import (
    LineCoverage,
    link_pending,
    ochiai_scores,
    parse_lcov,
    repo_rel_path,
)
from rfcv.domains.rfc_protocol.payloads import Outcome, T3Payload
from rfcv.domains.rfc_protocol.sandbox.driver import ScenarioRejected, TestDriver
from rfcv.domains.rfc_protocol.scenario_synth import synthesize
from rfcv.domains.rfc_protocol.spec.oracle_compiler import CompiledOracle, ConcreteVariant
from rfcv.gates.tool_gateway import ToolSession

MAX_BOARD_HOTSPOTS = 5


def _probe_name(c: CodeProbeCandidate) -> str:
    return f"code_probe:{c.field}={c.value}"


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
        t3s = [e.payload for e in evidence if isinstance(e.payload, T3Payload)]
        self._publish(inv, session, [*self._post_signals(inv, t3s), *self._post_hotspots(inv, t3s)])
        # gen-38 (L5 ADD_STRATEGY — Code-First → Targeted Dynamic Verify):
        # Khi toàn bộ ca kích hoạt hộp đen PASS (chưa phát hiện lỗi), quét hằng số nhánh quanh vị trí phát phản ứng
        # trong kho mã nguồn để sinh biến thể mục tiêu và xác minh lại bằng T3 + bản tham chiếu (bắt lỗi cửa sổ hẹp như U5).
        t3_triggers = [
            e.payload for e in evidence if isinstance(e.payload, T3Payload) and e.payload.side == "trigger"
        ]
        if t3_triggers and all(p.outcome is Outcome.PASS for p in t3_triggers):
            total += await self._run_code_first_probe(inv, oracle, output, session, msg_id)
        return total + link_pending(self._rt.store, self._rt.artifacts, self._rt.run_id, req_id)

    def _publish(self, inv: Investigation, session: ToolSession, entries: Sequence[HypothesisEntry]) -> None:
        """Ghi vào trace các mục war-room vừa đăng hoặc vừa đổi trạng thái."""
        if not entries:
            return
        self._rt.trace.append(
            self._rt.run_id,
            "blackboard_post",
            {"entries": [e.model_dump(mode="json", exclude_none=True) for e in entries]},
            role=session.role,
            requirement_id=inv.requirement.requirement_id,
        )

    def _post_signals(self, inv: Investigation, t3s: Sequence[T3Payload]) -> list[HypothesisEntry]:
        posted: list[HypothesisEntry] = []
        # `observed` đến từ SUT (không tin cậy): chỉ giá trị thuộc từ vựng adapter được lên bảng, như `summarize_evidence`.
        known = inv.vocabulary_terms | {"none"}
        for t3 in t3s:
            if t3.outcome is not Outcome.FAIL:
                continue
            alert = str(t3.observed.get("alert", "none"))
            entry = inv.blackboard.post(
                "tester",
                "behavioral_signal",
                field=t3.variant,
                value=alert if alert in known else None,
                status="verified",
                note=f"T3 FAIL on {t3.scenario}",
            )
            if entry is not None:
                posted.append(entry)
        return posted

    def _post_hotspots(self, inv: Investigation, t3s: Sequence[T3Payload]) -> list[HypothesisEntry]:
        """Điểm nóng SBFL Ochiai từ LCOV của đợt T3 này (chỉ có khi image SUT bật đo độ phủ)."""
        artifacts: Any = getattr(self._rt, "artifacts", None)
        if artifacts is None:
            return []
        fail_covs: list[LineCoverage] = []
        pass_covs: list[LineCoverage] = []
        for t3 in t3s:
            lcov_id = t3.artifacts.get("lcov")
            if not lcov_id:
                continue
            try:
                cov = parse_lcov(artifacts.get(lcov_id).decode("utf-8", "replace"))
            except Exception:
                continue
            if t3.outcome is Outcome.FAIL:
                fail_covs.append(cov)
            elif t3.outcome is Outcome.PASS:
                pass_covs.append(cov)
        if not fail_covs:
            return []
        index: Any = getattr(getattr(self._rt, "providers", None), "code_index", None)
        known_files: set[str] = {str(f) for f in index.files()} if index is not None else set()
        posted: list[HypothesisEntry] = []
        for spot in ochiai_scores(fail_covs, pass_covs, top_k=MAX_BOARD_HOTSPOTS):
            entry = inv.blackboard.post(
                "tester",
                "coverage_hotspot",
                file=repo_rel_path(spot.file, known_files) if index is not None else spot.file,
                line=spot.line,
                score=spot.score,
            )
            if entry is not None:
                posted.append(entry)
        return posted

    def _post_candidates(
        self, inv: Investigation, session: ToolSession, candidates: Sequence[CodeProbeCandidate]
    ) -> dict[str, str]:
        """Đăng ứng viên nhánh trước khi chạy thử; trả ánh xạ tên biến thể probe → `entry_id`."""
        posted: list[HypothesisEntry] = []
        ids: dict[str, str] = {}
        for c in candidates:
            entry = inv.blackboard.post(
                "tester", "branch_candidate", file=c.file, line=c.line, field=c.field, value=c.value
            )
            if entry is not None:
                posted.append(entry)
            else:  # đã đăng ở lượt trước: cập nhật trạng thái trên đúng mục cũ
                entry = next(
                    (
                        e
                        for e in inv.blackboard.entries(kind="branch_candidate")
                        if (e.file, e.line, e.field, e.value) == (c.file, c.line, c.field, c.value)
                    ),
                    None,
                )
            if entry is not None:
                ids[_probe_name(c)] = entry.entry_id
        self._publish(inv, session, posted)
        return ids

    def _resolve_candidates(
        self,
        inv: Investigation,
        session: ToolSession,
        candidates: Sequence[CodeProbeCandidate],
        entry_ids: dict[str, str],
        results: Sequence[T3Payload],
    ) -> None:
        failed = [p for p in results if p.outcome is Outcome.FAIL]
        failed_variants = {p.variant for p in failed}
        for name, entry_id in entry_ids.items():
            inv.blackboard.update_status(entry_id, "verified" if name in failed_variants else "refuted")
        changed_ids = set(entry_ids.values())
        changed = [e for e in inv.blackboard.entries(kind="branch_candidate") if e.entry_id in changed_ids]
        hit = next((c for c in candidates if _probe_name(c) in failed_variants), None)
        if hit is not None:
            summary = inv.blackboard.post(
                "tester",
                "probe_result",
                file=hit.file,
                line=hit.line,
                field=hit.field,
                value=hit.value,
                status="verified",
                note=f"{len(failed)}/{len(results)} probe runs FAIL",
            )
            if summary is not None:
                changed.append(summary)
        self._publish(inv, session, changed)

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
                name=_probe_name(c),
                variant_class="required",
                field=c.field,
                value=c.value,
                side=oracle.side_of(c.field, c.value),
            )
            for c in candidates
        )
        probe_oracle = oracle.model_copy(update={"variants": probe_variants})
        entry_ids = self._post_candidates(inv, session, candidates)
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
        results = [e.payload for e in probe_ev if isinstance(e.payload, T3Payload)]
        fails = sum(1 for p in results if p.outcome is Outcome.FAIL)
        self._resolve_candidates(inv, session, candidates, entry_ids, results)
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

"""Kiểm thử tích hợp nối dây thật cho 4 cơ chế thế hệ mới trong Runtime, ExecutionLoop và ProtocolRuntime:
1. Map-Reduce Audit Fleet qua `Runtime.run_all(..., max_concurrency=3)`
2. Divergence Verifier (`divergence.points`) cấp qua `ExecutionLoop` + `ProtocolRuntime.shared_context`
3. Reference Sanity Pre-Check (`precheck_spec`) chặn sớm CT-26 và ghi log `rbs_precheck`
4. Adaptive Best-of-K (`locate_best_of_k`) qua `SchemaGate` và ghi log `best_of_k_tournament`
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.code_reader.schema import AspectClaim, CheckKind, LocationClaim
from conftest import ADAPTER_DIR
from fakes import FakeBackend, FakeExecutor, FakeLauncher, make_index
from helpers import t1, t3
from rfcv.agents.schemas import Critique, PlanAction, TaskSpec
from rfcv.assembly import Providers, RuntimeConfig, build_runtime
from rfcv.core.ifc import admissible_to_privileged
from rfcv.core.runner import RoleOutcome
from rfcv.domains.rfc_protocol.multi_hypothesis import HypothesisSpec
from rfcv.domains.rfc_protocol.payloads import AspectName, AspectValue, Finding, Outcome
from rfcv.domains.rfc_protocol.rbs_precheck import PrecheckStatus, ReferenceObservation
from rfcv.domains.rfc_protocol.runtime import ProtocolRuntime
from rfcv.evidence.verdict_engine import Label, SufficiencyReport
from rfcv.gates.tool_gateway import ToolSession


class _StopRunner:
    async def run(self, envelope: Any, context: dict[str, Any], session: ToolSession) -> RoleOutcome:
        return RoleOutcome(PlanAction(action="stop", rationale_code="INFEASIBLE", tasks=[]), 1)


def _make_runtime(tmp_path: Path, *, max_concurrency: int = 1, parallel_hypotheses: int = 1, runner: Any = None) -> Any:
    cfg = RuntimeConfig(
        adapter_dir=ADAPTER_DIR,
        run_dir=tmp_path / "runs",
        run_id="run-wiring",
        max_concurrency=max_concurrency,
        parallel_hypotheses=parallel_hypotheses,
        scripted_plans=False,
    )
    return build_runtime(
        cfg,
        Providers(
            code_index=make_index(),
            executor=FakeExecutor(),
            backend=FakeBackend(),
            sut_launcher=FakeLauncher(),
            role_runner=runner or _StopRunner(),
        ),
    )


async def test_runtime_run_all_uses_audit_fleet_when_max_concurrency_gt_1(tmp_path: Path) -> None:
    src_dir = tmp_path / "specs"
    src_dir.mkdir()
    sample_rbs = next(sorted((ADAPTER_DIR / "examples").glob("*.rbs")).__iter__()).read_text(encoding="utf-8")
    for idx in range(1, 4):
        (src_dir / f"req_{idx}.rbs").write_text(
            sample_rbs.replace("TLS13-0042", f"TLS13-900{idx}"),
            encoding="utf-8",
        )
    rt = _make_runtime(tmp_path, max_concurrency=3)
    try:
        verdicts = await rt.run_all(src_dir, max_concurrency=3)
        assert [v.requirement_id for v in verdicts] == ["TLS13-9001", "TLS13-9002", "TLS13-9003"]
        assert all(v.label is Label.UNVERIFIABLE for v in verdicts)
        fleet_events = list(rt.trace.events("fleet_summary"))
        assert len(fleet_events) == 1
        assert fleet_events[0]["payload"]["total"] == 3
        assert fleet_events[0]["payload"]["succeeded"] == 3
        assert fleet_events[0]["payload"]["max_concurrency"] == 3
    finally:
        rt.close()


async def test_execution_loop_supplies_ifc_safe_divergence_points_to_verifier(tmp_path: Path) -> None:
    seen_contexts: list[dict[str, Any]] = []

    class _CapturingRunner:
        async def run(self, envelope: Any, context: dict[str, Any], session: ToolSession) -> Any:
            from rfcv.core.runner import RoleOutcome

            if envelope.to_role == "verifier":
                seen_contexts.append(context)
                return RoleOutcome(Critique(issues=[]), 10)
            if not seen_contexts:
                return RoleOutcome(
                    PlanAction(
                        action="dispatch",
                        rationale_code="INITIAL_TYPE_B",
                        tasks=[TaskSpec(task_type="CRITIQUE", target_role="verifier")],
                    ),
                    10,
                )
            return RoleOutcome(PlanAction(action="stop", rationale_code="INFEASIBLE", tasks=[]), 10)

    rt = _make_runtime(tmp_path, runner=_CapturingRunner())
    try:
        invs = rt.pack.runtime.investigations(rt, ADAPTER_DIR / "examples")
        inv = invs[0]
        # Gắn bằng chứng T1 có unexplored + T3 PASS để kích hoạt điểm rẽ nhánh
        t1_draft = t1(requirement_id=inv.requirement.requirement_id)
        t1_draft = t1_draft.model_copy(
            update={"payload": t1_draft.payload.model_copy(update={"unexplored": ("alt_entry",)})}
        )
        rt.store.append(t1_draft)
        rt.store.append(t3(requirement_id=inv.requirement.requirement_id, outcome=Outcome.PASS))

        # Kiểm tra trực tiếp hàm shared_context của ProtocolRuntime an toàn IFC
        pr = ProtocolRuntime()
        extra = pr.shared_context(
            SufficiencyReport(inv.requirement.requirement_id, None),
            rt.store.for_requirement(inv.requirement.requirement_id),
            inv,
        )
        assert "divergence.points" in extra
        assert admissible_to_privileged(extra["divergence.points"])

        # Chạy thật vòng điều tra để xác nhận Verifier nhận được `divergence.points`
        await rt.loop.investigate(inv)
        assert len(seen_contexts) == 1
        assert "divergence.points" in seen_contexts[0]
        kinds = {item["kind"] for item in seen_contexts[0]["divergence.points"]["value"]}
        assert "UNEXPLORED_PATHS" in kinds
    finally:
        rt.close()


def test_protocol_runtime_precheck_spec_catches_ct26_and_logs_event(tmp_path: Path) -> None:
    rt = _make_runtime(tmp_path)
    try:
        inv = rt.pack.runtime.investigations(rt, ADAPTER_DIR / "examples")[0]
        obs = [
            ReferenceObservation("openssl", "valid", "at_limit:16640", passed=False, observed_alert="record_overflow"),
            ReferenceObservation("gnutls", "valid", "at_limit:16640", passed=False, observed_alert="record_overflow"),
            ReferenceObservation("openssl", "trigger", "boundary:16641", passed=True, observed_alert="record_overflow"),
            ReferenceObservation("gnutls", "trigger", "boundary:16641", passed=True, observed_alert="record_overflow"),
        ]
        res = rt.pack.runtime.precheck_spec(rt, inv, obs)
        assert res.status is PrecheckStatus.SUSPECT_VALID_SIDE
        events = list(rt.trace.events("rbs_precheck"))
        assert len(events) == 1
        assert events[0]["payload"]["status"] == "SUSPECT_VALID_SIDE"
    finally:
        rt.close()


async def test_protocol_runtime_locate_best_of_k_runs_through_schema_gate(tmp_path: Path) -> None:
    rt = _make_runtime(tmp_path, parallel_hypotheses=3)
    try:
        inv = rt.pack.runtime.investigations(rt, ADAPTER_DIR / "examples")[0]

        async def _run_one(hyp: HypothesisSpec, session: ToolSession) -> LocationClaim | None:
            # Đánh dấu các dòng thật trong make_index() (GetRecordHeader: 800–830) là đã hiển thị
            for ln in range(810, 820):
                session.shown_lines.add(("src/internal.c", ln))
            if hyp.strategy == "diagnosis_first":
                # Nhánh 1 trả UNCLEAR kèm unexplored
                return LocationClaim(
                    file="src/internal.c",
                    symbol="GetRecordHeader",
                    line_start=812,
                    line_end=816,
                    check_kind=CheckKind.LENGTH_BOUND,
                    finding=Finding.UNCLEAR,
                    aspects=[AspectClaim(aspect=AspectName.CONDITION, value=AspectValue.UNCLEAR, lines=(812, 813))],
                    unexplored=["macro_x", "caller_y"],
                )
            if hyp.strategy == "alert_and_reaction":
                # Nhánh 2 dẫn dòng chưa hiển thị -> bị SchemaGate loại
                return LocationClaim(
                    file="src/internal.c",
                    symbol="GetRecordHeader",
                    line_start=825,
                    line_end=828,
                    check_kind=CheckKind.LENGTH_BOUND,
                    finding=Finding.PRESENT,
                    aspects=[AspectClaim(aspect=AspectName.CONDITION, value=AspectValue.MATCH, lines=(825, 825))],
                )
            # Nhánh 3 (macro_and_ifdef) hợp lệ và dứt khoát nhất -> thắng tournament
            return LocationClaim(
                file="src/internal.c",
                symbol="GetRecordHeader",
                line_start=812,
                line_end=816,
                check_kind=CheckKind.LENGTH_BOUND,
                finding=Finding.PRESENT,
                aspects=[
                    AspectClaim(aspect=AspectName.CONDITION, value=AspectValue.MATCH, lines=(812, 813)),
                    AspectClaim(
                        aspect=AspectName.REACTION,
                        value=AspectValue.MATCH,
                        observed="send_alert(record_overflow)",
                        lines=(815, 816),
                    ),
                ],
                call_path=["ProcessReply", "GetRecordHeader"],
            )

        tournament = await rt.pack.runtime.locate_best_of_k(rt, inv, {"aspects": ["CONDITION", "REACTION"]}, _run_one)
        assert tournament.winner is not None
        assert tournament.winner.finding is Finding.PRESENT
        assert tournament.winner_hypothesis is not None
        assert "macro" in tournament.winner_hypothesis
        events = list(rt.trace.events("best_of_k_tournament"))
        assert len(events) == 1
        assert events[0]["payload"]["winner_hypothesis"] == tournament.winner_hypothesis
    finally:
        rt.close()

"""Execution loop: hub điều phối vòng điều tra cho một yêu cầu (thiết kế chính, Hình 4; tài liệu phối hợp agent).

Hub này không biết miền: kiểu nhiệm vụ, đích, vai trò Planner, quy ước phản biện và bộ quy tắc kết luận đều lấy từ
registry (domain pack) hoặc được truyền vào lúc dựng.

Bất biến:
- không tự sinh nhiệm vụ: chỉ chuyển nhiệm vụ Planner chọn từ danh mục đã đăng ký;
- ghi Trace log trước khi chuyển; agent không gọi nhau, mọi giao việc đi qua đây;
- không agent nào ghi bằng chứng: TaskHandler (thành phần tất định) đưa đầu ra qua cổng rồi mới ghi;
- quyết định "đủ chưa" đến từ Verdict engine; nhãn tạm thuộc `critique_before` (mặc định COMPLIANT) phải qua một lần
  phản biện sạch;
- dừng khi hết ngân sách (BUDGET) hoặc cùng nhiệm vụ lặp lần thứ ba không có bằng chứng mới (LOOP).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel

from rfcv.agents.schemas import Critique, PlanAction, TaskSpec
from rfcv.core.budget import BudgetTracker, LoopDetector, RequirementBudget
from rfcv.core.context_builder import ContextBuilder, summarize_evidence, to_jsonable
from rfcv.core.envelope import Envelope, EnvelopeFactory, MessageKind
from rfcv.core.ifc import Labeled, TrustLabel
from rfcv.core.policy import PolicyStore
from rfcv.core.runner import RoleOutcome, RoleRunner
from rfcv.evidence.models import Evidence
from rfcv.evidence.repository import EvidenceRepository, TraceSink
from rfcv.evidence.verdict_engine import (
    RequirementView,
    RuleSet,
    StopReason,
    SufficiencyReport,
    VerdictRecord,
    assess,
    decide,
)
from rfcv.gates.tool_gateway import ToolSession
from rfcv.plugins import current_registry
from rfcv.spi import LoopPolicy, TaskDefinition

HUB = "execution_loop"


def _evidence_count(_report: SufficiencyReport, count: int) -> Hashable:
    return count


@dataclass
class Investigation:
    requirement: RequirementView
    # Trường ngữ cảnh đã gắn nhãn (requirement.structured, rfc.sentence, adapter.vocabulary…)
    context: dict[str, Labeled[Any]]
    vocabulary_terms: frozenset[str] = frozenset()
    # Adapter có mẫu kiểm thử / truy vấn phù hợp không (Verdict engine: feasible)
    feasible: dict[str, bool] = field(default_factory=lambda: {"T1": True, "T2": True, "T3": True})
    # Trạng thái riêng của miền cho handler (ví dụ oracle đã biên dịch); lõi không đọc.
    domain_state: dict[str, Any] = field(default_factory=dict[str, Any])


class TaskHandler(Protocol):
    """Biến đầu ra của agent thành bằng chứng qua cổng tất định; trả số bằng chứng mới."""

    async def handle(
        self, inv: Investigation, task: TaskSpec, output: BaseModel | None, session: ToolSession, msg_id: str
    ) -> int: ...


def report_json(report: SufficiencyReport) -> dict[str, Any]:
    return to_jsonable(
        {
            "provisional": report.provisional,
            "decisive": report.decisive,
            "missing": report.missing,
            "conflicts": report.conflicts,
        }
    )


class ExecutionLoop:
    def __init__(
        self,
        *,
        run_id: str,
        runner: RoleRunner,
        policy: PolicyStore,
        store: EvidenceRepository,
        trace: TraceSink,
        handlers: Mapping[str, TaskHandler],
        budget: RequirementBudget | None = None,
        tasks: Mapping[str, TaskDefinition] | None = None,
        loop: LoopPolicy | None = None,
        rules: RuleSet | None = None,
        loop_detector: Callable[[], LoopDetector] | None = None,
        progress_of: Callable[[SufficiencyReport, int], Hashable] | None = None,
    ) -> None:
        reg = current_registry()
        self.run_id = run_id
        self._runner = runner
        self._policy = policy
        self._ctx = ContextBuilder(policy)
        self._store = store
        self._trace = trace
        self._handlers = handlers
        self._budget = budget or RequirementBudget()
        self._envelopes = EnvelopeFactory(run_id)
        self._tasks = tasks if tasks is not None else reg.tasks
        self._loop = loop if loop is not None else reg.loop_policy()
        self._rules = rules if rules is not None else reg.default_rule_set()
        self._new_loop_detector = loop_detector or LoopDetector
        self._progress_of: Callable[[SufficiencyReport, int], Hashable] = progress_of or _evidence_count

    async def investigate(self, inv: Investigation) -> VerdictRecord:
        req = inv.requirement
        tracker = BudgetTracker(self._budget)
        loops = self._new_loop_detector()
        history: list[dict[str, Any]] = []
        critique: Critique | None = None
        critiqued_clean = False
        stop: StopReason

        while True:
            evidence = self._store.for_requirement(req.requirement_id)
            report = assess(req, evidence, self._rules)
            self._log("sufficiency", report_json(report), req.requirement_id, round=tracker.rounds)

            needs_critique = (
                report.provisional is not None
                and self._loop.critique_task is not None
                and report.provisional.label.value in self._loop.critique_before
            )
            if report.provisional is not None and (not needs_critique or critiqued_clean):
                stop = StopReason.SUFFICIENT
                break
            if tracker.exhausted():
                stop = StopReason.BUDGET
                break
            tracker.charge_round()

            plan = await self._plan(
                inv, report, evidence_count=len(evidence), critique=critique, history=history, tracker=tracker
            )
            if plan is None:
                continue
            if plan.action == "stop":
                if report.missing and all(not inv.feasible.get(m.need, True) for m in report.missing):
                    stop = StopReason.INFEASIBLE
                    break
                self._log(
                    "stop_rejected", {"rationale": str(plan.rationale_code)}, req.requirement_id, round=tracker.rounds
                )
                continue

            tasks = [t for t in plan.tasks if self._task_valid(t, req.requirement_id, tracker.rounds)]
            looped = False
            for t in tasks:
                key = loops.key(t.task_type, t.target_role, t.params.model_dump(mode="json"))
                looped |= loops.observe(key, self._progress_of(report, len(evidence)))
            if looped:
                stop = StopReason.LOOP
                break

            shared = self._shared_context(report, evidence, inv.vocabulary_terms)
            results = await asyncio.gather(*(self._dispatch(inv, t, tracker, shared) for t in tasks))
            for t, (outcome, _new) in zip(tasks, results, strict=True):
                history.append(
                    {
                        "round": tracker.rounds,
                        "task_type": t.task_type,
                        "target": t.target_role,
                        "ok": outcome is None or outcome.output is not None,
                    }
                )
                if (
                    t.task_type == self._loop.critique_task
                    and outcome is not None
                    and isinstance(outcome.output, Critique)
                ):
                    critique = outcome.output
                    if needs_critique and not critique.issues:
                        critiqued_clean = True

        final = decide(req, self._store.for_requirement(req.requirement_id), stop, self._rules)
        self._store.record_verdict(req.requirement_id, final.to_json())
        self._log("verdict", final.to_json(), req.requirement_id, round=tracker.rounds)
        return final

    # ------------------------------------------------------------------

    async def _plan(
        self,
        inv: Investigation,
        report: SufficiencyReport,
        *,
        evidence_count: int,
        critique: Critique | None,
        history: list[dict[str, Any]],
        tracker: BudgetTracker,
    ) -> PlanAction | None:
        req = inv.requirement
        evidence = self._store.for_requirement(req.requirement_id)
        available: dict[str, Labeled[Any]] = {
            **inv.context,
            **self._shared_context(report, evidence, inv.vocabulary_terms),
            "requirement.rtype": Labeled(req.rtype, TrustLabel.TRUSTED),
            "tasks.history": Labeled(to_jsonable(history), TrustLabel.DERIVED),
            "budget.left": Labeled(tracker.remaining(), TrustLabel.TRUSTED),
        }
        if critique is not None:
            available["critique.latest"] = Labeled(critique.model_dump(mode="json"), TrustLabel.DERIVED)
        outcome, _ = await self._run_role(
            self._loop.planner_role, inv, {"evidence_count": evidence_count}, available, tracker
        )
        if outcome.output is None or not isinstance(outcome.output, PlanAction):
            return None
        self._log("plan", outcome.output.model_dump(mode="json"), req.requirement_id, round=tracker.rounds)
        return outcome.output

    @staticmethod
    def _shared_context(
        report: SufficiencyReport, evidence: Sequence[Evidence], vocabulary_terms: Iterable[str]
    ) -> dict[str, Labeled[Any]]:
        """Trạng thái điều tra mà mọi vai trò cần để làm việc ăn khớp: bằng chứng đã có (đã tóm tắt an toàn) và độ đủ."""
        return {
            "evidence.summary": summarize_evidence(evidence, vocabulary_terms),
            "verdict.sufficiency": Labeled(report_json(report), TrustLabel.DERIVED),
        }

    def _task_valid(self, task: TaskSpec, requirement_id: str, round: int) -> bool:
        definition = self._tasks.get(task.task_type)
        ok = definition is not None and definition.target_role == task.target_role and task.task_type in self._handlers
        if not ok:
            self._log("task_rejected", task.model_dump(mode="json"), requirement_id, round=round)
        return ok

    async def _dispatch(
        self, inv: Investigation, task: TaskSpec, tracker: BudgetTracker, shared: Mapping[str, Labeled[Any]]
    ) -> tuple[RoleOutcome | None, int]:
        role = task.target_role
        handler = self._handlers[task.task_type]
        body = task.model_dump(mode="json")
        if self._tasks[task.task_type].deterministic:  # thành phần tất định, không gọi LLM
            env = self._envelope(inv, role, body, tracker)
            session = ToolSession(self.run_id, role, inv.requirement.requirement_id, max_tool_calls=0)
            self._trace_envelope(env)
            new = await handler.handle(inv, task, None, session, env.msg_id)
            self._log_task_result(inv, task, new, round=tracker.rounds, msg_id=env.msg_id)
            return None, new

        available = {
            **inv.context,
            **shared,
            "task.focus": Labeled(to_jsonable(task.params), TrustLabel.DERIVED),
        }
        outcome, new = await self._run_role(role, inv, body, available, tracker, handler=handler, task=task)
        return outcome, new

    async def _run_role(
        self,
        role: str,
        inv: Investigation,
        body: dict[str, Any],
        available: Mapping[str, Labeled[Any]],
        tracker: BudgetTracker,
        *,
        handler: TaskHandler | None = None,
        task: TaskSpec | None = None,
    ) -> tuple[RoleOutcome, int]:
        env = self._envelope(inv, role, body, tracker)
        self._trace_envelope(env)
        context = self._ctx.build(role, available)
        profile = self._policy.profile(role)
        session = ToolSession(
            self.run_id, role, inv.requirement.requirement_id, max_tool_calls=profile.budget_per_task.tool_calls
        )
        outcome = await self._runner.run(env, context, session)
        tracker.charge_tokens(outcome.tokens)
        tracker.charge_tool_calls(session.tool_calls)
        if outcome.failure is not None or outcome.output is None:
            self._log_role_failure(inv, role, outcome, env.msg_id, round=tracker.rounds)
        new = 0
        if handler is not None and task is not None:
            new = await handler.handle(inv, task, outcome.output, session, env.msg_id)
            self._log_task_result(inv, task, new, round=tracker.rounds, msg_id=env.msg_id)
        return outcome, new

    def _log_role_failure(
        self, inv: Investigation, role: str, outcome: RoleOutcome, msg_id: str, *, round: int
    ) -> None:
        """Vai trò không trả đầu ra dùng được (lỗi mô hình, hết lượt thử, sai schema): để lại dấu vết, không đổi luồng."""
        self._log(
            "role_failure",
            {"role": role, "msg_id": msg_id, "failure": outcome.failure or "NO_OUTPUT"},
            inv.requirement.requirement_id,
            round=round,
        )

    def _log_task_result(self, inv: Investigation, task: TaskSpec, new: int, *, round: int, msg_id: str) -> None:
        self._log(
            "task_result",
            {"task_type": task.task_type, "target": task.target_role, "msg_id": msg_id, "new_evidence": new},
            inv.requirement.requirement_id,
            round=round,
        )

    def _envelope(self, inv: Investigation, to_role: str, body: dict[str, Any], tracker: BudgetTracker) -> Envelope:
        return self._envelopes.make(
            requirement_id=inv.requirement.requirement_id,
            from_role=HUB,
            to_role=to_role,
            kind=MessageKind.DISPATCH,
            round=tracker.rounds,
            body=body,
            budget_left=tracker.remaining(),
        )

    def _trace_envelope(self, env: Envelope) -> None:
        self._trace.append(
            self.run_id, "message", env.model_dump(mode="json"), role=env.to_role, requirement_id=env.requirement_id
        )

    def _log(self, kind: str, payload: dict[str, Any], requirement_id: str, *, round: int) -> None:
        self._trace.append(self.run_id, kind, {"round": round, **payload}, role=HUB, requirement_id=requirement_id)

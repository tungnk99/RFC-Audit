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
import dataclasses
import json
import time
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel

from rfcv.agents.schemas import Critique, PlanAction, TaskSpec
from rfcv.core.advisor import adherence, advise, situation_from_context
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
MAX_LOGGED_OUTPUT_CHARS = 6000


def _clip(value: Any) -> Any:
    """Đầu ra agent đưa vào trace; cắt nếu quá dài (trường `note` tự do có thể rất dài)."""
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= MAX_LOGGED_OUTPUT_CHARS:
        return value
    return {"truncated": True, "chars": len(text), "head": text[:MAX_LOGGED_OUTPUT_CHARS]}


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


def report_json(report: SufficiencyReport, feasible: Mapping[str, bool] | None = None) -> dict[str, Any]:
    """Báo cáo độ đủ dạng JSON (tài liệu phối hợp agent, mục 8). `feasible`: adapter có làm được từng loại bằng chứng
    không; Planner chỉ được dừng INFEASIBLE khi mọi mục còn thiếu đều không làm được."""
    data: dict[str, Any] = {
        "provisional": report.provisional,
        "decisive": report.decisive,
        "missing": report.missing,
        "conflicts": report.conflicts,
    }
    if feasible is not None:
        data["feasible"] = dict(feasible)
    return to_jsonable(data)


def missing_json(report: SufficiencyReport, feasible: Mapping[str, bool]) -> list[dict[str, Any]]:
    """Chỉ phần còn thiếu của báo cáo độ đủ, kèm làm được hay không: cho vai trò cần biết thiếu gì nhưng không được thấy
    bằng chứng đã có hay nhãn tạm (ví dụ Test không được thấy T1, Bảng 11)."""
    return [
        {"need": m.need, "variant": m.variant, "reason": m.reason, "feasible": feasible.get(m.need, True)}
        for m in report.missing
    ]


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
        stop_detail: dict[str, Any] = {}

        self._log(
            "requirement_start",
            {
                "rtype": req.rtype,
                "modal": req.modal,
                "budget": dataclasses.asdict(self._budget),
                "feasible": dict(inv.feasible),
                "rules_version": self._rules.version,
                "playbook_version": current_registry().playbook_version,
            },
            req.requirement_id,
            round=0,
        )

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
                stop_detail = {
                    "label": report.provisional.label.value,
                    "rule": report.provisional.rule,
                    "critiqued_clean": needs_critique and critiqued_clean,
                }
                break
            if tracker.exhausted():
                stop = StopReason.BUDGET
                stop_detail = {"exhausted_by": tracker.exhausted_by()}
                break
            tracker.charge_round()
            self._log(
                "round_start",
                {"used": tracker.used(), "left": tracker.remaining()},
                req.requirement_id,
                round=tracker.rounds,
            )

            plan = await self._plan(
                inv, report, evidence_count=len(evidence), critique=critique, history=history, tracker=tracker
            )
            if plan is None:
                continue
            if plan.action == "stop":
                if report.missing and all(not inv.feasible.get(m.need, True) for m in report.missing):
                    stop = StopReason.INFEASIBLE
                    stop_detail = {"missing": [{"need": m.need, "variant": m.variant} for m in report.missing]}
                    break
                self._log(
                    "stop_rejected", {"rationale": str(plan.rationale_code)}, req.requirement_id, round=tracker.rounds
                )
                continue

            tasks = [t for t in plan.tasks if self._task_valid(t, req.requirement_id, tracker.rounds)]
            looped_tasks: list[dict[str, Any]] = []
            for t in tasks:
                params = t.params.model_dump(mode="json")
                key = loops.key(t.task_type, t.target_role, params)
                if loops.observe(key, self._progress_of(report, len(evidence))):
                    looped_tasks.append({"task_type": t.task_type, "target": t.target_role, "params": params})
            if looped_tasks:
                stop = StopReason.LOOP
                stop_detail = {"repeated": looped_tasks, "evidence_count": len(evidence)}
                break

            shared = self._shared_context(report, evidence, inv)
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
                    # Verifier chỉ được dẫn bằng chứng có thật (VF-6): mã không có trong kho là bịa, ghi lại để đo.
                    known_ids = {e.evidence_id for e in evidence}
                    self._log(
                        "critique_result",
                        {
                            "issues": [i.model_dump(mode="json") for i in critique.issues],
                            "unknown_evidence_ids": sorted(
                                {
                                    i.evidence_id
                                    for i in critique.issues
                                    if i.evidence_id and i.evidence_id not in known_ids
                                }
                            ),
                            "clean": not critique.issues,
                            "gating": needs_critique,
                            "accepted_as_clean": critiqued_clean,
                        },
                        req.requirement_id,
                        round=tracker.rounds,
                    )

        self._log(
            "stop",
            {"reason": stop.value, "used": tracker.used(), **stop_detail},
            req.requirement_id,
            round=tracker.rounds,
        )
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
            **self._shared_context(report, evidence, inv),
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
        self._log_plan_context(available, outcome.output, req.requirement_id, round=tracker.rounds)
        return outcome.output

    def _log_plan_context(
        self, available: Mapping[str, Labeled[Any]], plan: PlanAction, requirement_id: str, *, round: int
    ) -> None:
        """Tình huống Planner thấy, lời khuyên của sổ tay ở đúng tình huống đó, và Planner đi theo hay chệch.

        Chỉ để quan sát: lỗi dựng tình huống không được làm hỏng vòng điều tra.
        """
        try:
            sit = situation_from_context(self._ctx.build(self._loop.planner_role, available), self._loop.critique_task)
            advice = advise(sit, current_registry().playbook, self._tasks, frozenset(self._handlers))
        except (KeyError, TypeError, ValueError) as exc:
            self._log("plan_context_error", {"error": type(exc).__name__}, requirement_id, round=round)
            return
        rationale = str(plan.rationale_code)
        self._log(
            "plan_context",
            {
                "situation": sit.signature(),
                "rtype": sit.rtype,
                "provisional": sit.provisional,
                "needs": sorted(sit.needs),
                "conflicts": [list(c) for c in sit.conflicts],
                "critique": sit.critique,
                "critique_kinds": list(sit.critique_kinds),
                "rounds_so_far": sit.rounds,
                "action": plan.action,
                "planned": [t.task_type for t in plan.tasks],
                "rationale": rationale,
                "advice": None
                if advice is None
                else {
                    "rule": advice.rule_id,
                    "stop": advice.stop,
                    "tasks": [t.task_type for t in advice.tasks],
                    "rationale": advice.rationale_code,
                },
                "adherence": adherence(advice, plan.action, plan.tasks, rationale, self._loop.deviation_code or ""),
            },
            requirement_id,
            round=round,
        )

    @staticmethod
    def _shared_context(
        report: SufficiencyReport, evidence: Sequence[Evidence], inv: Investigation
    ) -> dict[str, Labeled[Any]]:
        """Trạng thái điều tra hub cấp; mỗi vai trò chỉ nhận trường nó khai báo trong role.yaml.

        evidence.summary     bằng chứng đã có, đã tóm tắt an toàn (Planner, Verifier);
        verdict.sufficiency  báo cáo độ đủ đầy đủ, kèm feasible (Planner, Verifier);
        verdict.missing      chỉ phần còn thiếu, không lộ bằng chứng hay nhãn tạm (Test).
        """
        # Bằng chứng được nhãn tạm hay xung đột trích dẫn giữ hàng riêng; phần còn lại có thể được gộp (BL-12).
        cited = {i for c in report.conflicts for i in c.evidence_ids}
        if report.provisional is not None:
            cited |= set(report.provisional.evidence_ids)
        return {
            "evidence.summary": summarize_evidence(evidence, inv.vocabulary_terms, cited),
            "verdict.sufficiency": Labeled(report_json(report, inv.feasible), TrustLabel.DERIVED),
            "verdict.missing": Labeled(missing_json(report, inv.feasible), TrustLabel.DERIVED),
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
        precheck: Any = getattr(handler, "precheck", None)
        if precheck is not None:
            # Handler có cổng kiểm tra thuần (không ghi): runtime agent dùng để cho agent làm lại trước khi trả kết quả.
            session.output_check = lambda out: precheck(inv, out, session)
        started = time.monotonic()
        outcome = await self._runner.run(env, context, session)
        duration_ms = int((time.monotonic() - started) * 1000)
        tracker.charge_tokens(outcome.tokens)
        tracker.charge_tool_calls(session.tool_calls)
        output = outcome.output
        self._log(
            "role_run",
            {
                "msg_id": env.msg_id,
                "role": role,
                "task_type": body.get("task_type"),
                "duration_ms": duration_ms,
                "tokens": outcome.tokens,
                "tool_calls": session.tool_calls,
                "output_retries": session.output_rejections,
                "ok": output is not None,
                "failure": outcome.failure,
                "schema": type(output).__name__ if output is not None else None,
                # Kế hoạch đã có sự kiện `plan`; vai trò khác thì lưu đầu ra có cấu trúc để phân tích sau.
                "output": _clip(output.model_dump(mode="json"))
                if output is not None and role != self._loop.planner_role
                else None,
            },
            inv.requirement.requirement_id,
            round=tracker.rounds,
        )
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

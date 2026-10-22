"""Execution loop với runner và handler giả: điều phối, dừng, ngân sách, phát hiện lặp (Hình 3, Hình 4)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from helpers import REQ, as_evidence, full_passing_set, link, t1, t3
from rfcv.agents.schemas import Critique, PlanAction, TaskSpec
from rfcv.core.budget import RequirementBudget
from rfcv.core.envelope import Envelope
from rfcv.core.execution_loop import ExecutionLoop, Investigation
from rfcv.core.ifc import Labeled, TrustLabel
from rfcv.core.policy import PolicyStore
from rfcv.core.runner import RoleOutcome
from rfcv.core.trace import TraceLog
from rfcv.domains.rfc_protocol.payloads import AspectName, AspectValue, Outcome
from rfcv.domains.rfc_protocol.rules import Assurance, ProtocolRequirement
from rfcv.domains.rfc_protocol.schemas import (
    LocationClaim,
    RationaleCode,
    ScenarioProposal,
    TargetRole,
    TaskParams,
    TaskType,
)
from rfcv.evidence.models import EvidenceDraft
from rfcv.evidence.store import EvidenceStore
from rfcv.evidence.verdict_engine import Label, StopReason
from rfcv.gates.tool_gateway import ToolSession

REQ_B = ProtocolRequirement(
    REQ,
    "B",
    "MUST",
    required_variants=frozenset(
        {"at_limit:record.length=16640", "boundary:record.length=16641", "max:record.length=65535"}
    ),
    random_k=3,
)

LOCATE = TaskSpec(
    task_type=TaskType.LOCATE,
    target_role=TargetRole.CODE_READER,
    params=TaskParams(aspects=[AspectName.CONDITION, AspectName.THRESHOLD, AspectName.REACTION]),
)
SELECT = TaskSpec(task_type=TaskType.SELECT_TESTS, target_role=TargetRole.TESTER)
CRITIQUE = TaskSpec(task_type=TaskType.CRITIQUE, target_role=TargetRole.VERIFIER)


def plan(*tasks: TaskSpec, action: str = "dispatch") -> PlanAction:
    return PlanAction(action=action, tasks=list(tasks), rationale_code=RationaleCode.INITIAL_TYPE_B)  # type: ignore[arg-type]


class FakeRunner:
    def __init__(self, plans: Callable[[int], PlanAction], outputs: dict[str, BaseModel]) -> None:
        self.plans = plans
        self.outputs = outputs
        self.calls: list[Envelope] = []
        self.contexts: list[dict[str, Any]] = []

    async def run(self, envelope: Envelope, context: dict[str, Any], session: ToolSession) -> RoleOutcome:
        self.calls.append(envelope)
        self.contexts.append(context)
        if envelope.to_role == "planner":
            return RoleOutcome(self.plans(sum(c.to_role == "planner" for c in self.calls)), 100)
        return RoleOutcome(self.outputs.get(envelope.to_role), 50)


class WriteOnce:
    """Handler giả: lần đầu được gọi thì ghi các bằng chứng cho trước (như cổng thật sẽ ghi)."""

    def __init__(self, store: EvidenceStore, drafts: Callable[[], list[EvidenceDraft]]) -> None:
        self.store = store
        self.drafts = drafts
        self.calls = 0

    async def handle(
        self, inv: Investigation, task: TaskSpec, output: BaseModel | None, session: ToolSession, msg_id: str
    ) -> int:
        self.calls += 1
        if self.calls > 1:
            return 0
        drafts = self.drafts()
        for d in drafts:
            self.store.append(d)
        return len(drafts)


class Noop:
    async def handle(self, *args: object) -> int:
        return 0


OUTPUTS: dict[str, BaseModel] = {
    "tester": ScenarioProposal(
        requirement_id=REQ, reach_state="connected", steps=[{"op": "complete_handshake"}, {"op": "expect"}]
    ),  # type: ignore[list-item]
    "code_reader": LocationClaim.model_validate(
        {
            "file": "src/internal.c",
            "symbol": "GetRecordHeader",
            "line_start": 812,
            "line_end": 816,
            "check_kind": "LENGTH_BOUND",
            "finding": "PRESENT",
        }
    ),
    "verifier": Critique(issues=[]),
}


def make_loop(
    store: EvidenceStore,
    trace: TraceLog,
    policy: PolicyStore,
    runner: FakeRunner,
    handlers: dict[TaskType, Any],
    budget: RequirementBudget | None = None,
) -> ExecutionLoop:
    return ExecutionLoop(
        run_id="run-test", runner=runner, policy=policy, store=store, trace=trace, handlers=handlers, budget=budget
    )


def inv(feasible: dict[str, bool] | None = None) -> Investigation:
    i = Investigation(
        requirement=REQ_B,
        context={"requirement.structured": Labeled({"id": REQ, "type": "B"}, TrustLabel.TRUSTED)},
        vocabulary_terms=frozenset({"record_overflow", "decode_error", "send_alert(decode_error)"}),
    )
    if feasible is not None:
        i.feasible = feasible
    return i


async def test_k3_violation_in_one_round(store: EvidenceStore, trace: TraceLog, policy: PolicyStore) -> None:
    """Ca K3: mã có kiểm tra độ dài nhưng gửi decode_error thay vì record_overflow → V2."""
    runner = FakeRunner(lambda n: plan(SELECT, LOCATE), OUTPUTS)
    handlers = {
        TaskType.SELECT_TESTS: WriteOnce(store, lambda: [t3(outcome=Outcome.FAIL, alert="decode_error")]),
        TaskType.LOCATE: WriteOnce(
            store, lambda: [t1(reaction=AspectValue.MISMATCH, observed="send_alert(decode_error)")]
        ),
    }
    verdict = await make_loop(store, trace, policy, runner, handlers).investigate(inv())
    assert (verdict.label, verdict.rule, verdict.stop_reason) == (Label.VIOLATION, "V2", StopReason.SUFFICIENT)
    assert [c.to_role for c in runner.calls] == ["planner", "tester", "code_reader"]
    # Mọi thông điệp do hub gán người gửi
    assert all(c.from_role == "execution_loop" for c in runner.calls)
    assert store.latest_verdicts()[REQ]["label"] == "VIOLATION"
    # Planner chỉ thấy bản tóm tắt có cấu trúc, không thấy chuỗi tự do của vùng cách ly
    assert "evidence.summary" in runner.contexts[0]


async def test_compliant_requires_one_clean_critique(
    store: EvidenceStore, trace: TraceLog, policy: PolicyStore
) -> None:
    """Nhãn tạm COMPLIANT không dừng ngay: hub chỉ dừng sau khi Verifier phản biện không nêu vấn đề."""
    runner = FakeRunner(lambda n: plan(SELECT, LOCATE) if n == 1 else plan(CRITIQUE), OUTPUTS)
    handlers = {
        TaskType.SELECT_TESTS: WriteOnce(store, full_passing_set),
        TaskType.LOCATE: Noop(),  # agent không định vị được → COMPLIANT · BEHAVIORAL (V6)
        TaskType.CRITIQUE: Noop(),
    }
    verdict = await make_loop(store, trace, policy, runner, handlers).investigate(inv())
    assert (verdict.label, verdict.rule) == (Label.COMPLIANT, "V6")
    roles = [c.to_role for c in runner.calls]
    assert roles.count("verifier") == 1 and roles[-1] == "verifier"


async def test_linked_compliant_after_coverage_link(store: EvidenceStore, trace: TraceLog, policy: PolicyStore) -> None:
    def t1_then_link() -> list[EvidenceDraft]:
        ids = [e.evidence_id for e in store.for_requirement(REQ)]
        t1_draft = t1()
        t1_id = as_evidence(t1_draft, prev=ids[-1]).evidence_id
        return [t1_draft, link(ids[1], t1_id)]

    runner = FakeRunner(lambda n: plan(SELECT) if n == 1 else (plan(LOCATE) if n == 2 else plan(CRITIQUE)), OUTPUTS)
    handlers = {
        TaskType.SELECT_TESTS: WriteOnce(store, full_passing_set),
        TaskType.LOCATE: WriteOnce(store, t1_then_link),
        TaskType.CRITIQUE: Noop(),
    }
    verdict = await make_loop(store, trace, policy, runner, handlers).investigate(inv())
    assert (verdict.label, verdict.rule, verdict.assurance) == (Label.COMPLIANT, "V5", Assurance.LINKED)


async def test_loop_detection(store: EvidenceStore, trace: TraceLog, policy: PolicyStore) -> None:
    runner = FakeRunner(lambda n: plan(LOCATE), OUTPUTS)
    verdict = await make_loop(store, trace, policy, runner, {TaskType.LOCATE: Noop()}).investigate(inv())
    assert (verdict.label, verdict.stop_reason) == (Label.UNVERIFIABLE, StopReason.LOOP)
    assert sum(c.to_role == "code_reader" for c in runner.calls) == 2  # lần thứ ba bị chặn trước khi gọi


async def test_budget_exhaustion(store: EvidenceStore, trace: TraceLog, policy: PolicyStore) -> None:
    def varied(n: int) -> PlanAction:
        aspects = [AspectName.CONDITION, AspectName.THRESHOLD, AspectName.REACTION]
        return plan(
            TaskSpec(
                task_type=TaskType.LOCATE,
                target_role=TargetRole.CODE_READER,
                params=TaskParams(aspects=aspects[: 1 + n % 3], target_symbol=f"f{n}"),
            )
        )

    runner = FakeRunner(varied, OUTPUTS)
    loop = make_loop(store, trace, policy, runner, {TaskType.LOCATE: Noop()}, RequirementBudget(rounds=3))
    verdict = await loop.investigate(inv())
    assert (verdict.label, verdict.stop_reason) == (Label.UNVERIFIABLE, StopReason.BUDGET)
    assert sum(c.to_role == "planner" for c in runner.calls) == 3


async def test_task_with_wrong_target_is_rejected(store: EvidenceStore, trace: TraceLog, policy: PolicyStore) -> None:
    bad = TaskSpec(task_type=TaskType.LOCATE, target_role=TargetRole.TESTER)
    runner = FakeRunner(lambda n: plan(bad), OUTPUTS)
    loop = make_loop(store, trace, policy, runner, {TaskType.LOCATE: Noop()}, RequirementBudget(rounds=2))
    await loop.investigate(inv())
    assert all(c.to_role == "planner" for c in runner.calls)
    assert list(trace.events("task_rejected"))


async def test_premature_stop_rejected_then_infeasible(
    store: EvidenceStore, trace: TraceLog, policy: PolicyStore
) -> None:
    runner = FakeRunner(lambda n: plan(action="stop"), OUTPUTS)
    v1 = await make_loop(store, trace, policy, runner, {}, RequirementBudget(rounds=2)).investigate(inv())
    assert v1.stop_reason is StopReason.BUDGET and list(trace.events("stop_rejected"))
    v2 = await make_loop(store, trace, policy, runner, {}).investigate(inv({"T1": False, "T2": False, "T3": False}))
    assert v2.stop_reason is StopReason.INFEASIBLE and v2.label is Label.UNVERIFIABLE


# ---------------------------------------------------------------- dấu vết để phân tích sau


def kinds(trace: TraceLog) -> list[str]:
    return [e["kind"] for e in trace.events()]


def payloads(trace: TraceLog, kind: str) -> list[dict[str, Any]]:
    return [e["payload"] for e in trace.events(kind)]


async def test_trace_follows_one_investigation_from_start_to_stop(
    store: EvidenceStore, trace: TraceLog, policy: PolicyStore
) -> None:
    """Một lượt điều tra phải đọc lại được: bắt đầu thế nào, mỗi vòng ra sao, ai chạy bao lâu, vì sao dừng."""
    runner = FakeRunner(lambda n: plan(SELECT, LOCATE), OUTPUTS)
    handlers = {
        TaskType.SELECT_TESTS: WriteOnce(store, lambda: [t3(outcome=Outcome.FAIL, alert="decode_error")]),
        TaskType.LOCATE: WriteOnce(
            store, lambda: [t1(reaction=AspectValue.MISMATCH, observed="send_alert(decode_error)")]
        ),
    }
    await make_loop(store, trace, policy, runner, handlers).investigate(inv())

    order = kinds(trace)
    assert order[0] == "requirement_start" and order.index("round_start") < order.index("plan")
    assert order.index("stop") < order.index("verdict") == len(order) - 1

    start = payloads(trace, "requirement_start")[0]
    assert start["rtype"] == "B" and start["budget"]["rounds"] == 8 and "rules_version" in start

    runs = {p["role"]: p for p in payloads(trace, "role_run")}
    assert set(runs) == {"planner", "tester", "code_reader"}
    assert all(p["ok"] and p["duration_ms"] >= 0 for p in runs.values())
    assert runs["planner"]["output"] is None  # kế hoạch đã có sự kiện `plan`
    assert runs["code_reader"]["schema"] == "LocationClaim"
    assert runs["code_reader"]["output"]["symbol"] == "GetRecordHeader"

    stop = payloads(trace, "stop")[0]
    assert stop["reason"] == "SUFFICIENT" and stop["label"] == "VIOLATION" and stop["rule"] == "V2"


async def test_stop_event_names_what_ran_out_or_what_repeated(
    store: EvidenceStore, trace: TraceLog, policy: PolicyStore
) -> None:
    loop_runner = FakeRunner(lambda n: plan(LOCATE), OUTPUTS)
    await make_loop(store, trace, policy, loop_runner, {TaskType.LOCATE: Noop()}).investigate(inv())
    stop = payloads(trace, "stop")[-1]
    assert stop["reason"] == "LOOP" and stop["repeated"][0]["task_type"] == "LOCATE"

    budget_runner = FakeRunner(lambda n: plan(action="stop"), OUTPUTS)
    await make_loop(store, trace, policy, budget_runner, {}, RequirementBudget(rounds=2)).investigate(inv())
    stop = payloads(trace, "stop")[-1]
    assert stop["reason"] == "BUDGET" and stop["exhausted_by"] == ["rounds"] and stop["used"]["rounds"] == 2


async def test_critique_content_and_gating_are_traced(
    store: EvidenceStore, trace: TraceLog, policy: PolicyStore
) -> None:
    """Nội dung phản biện trước đây không vào trace nên không phân tích được Planner có làm theo hay bỏ qua."""
    runner = FakeRunner(lambda n: plan(SELECT, LOCATE) if n == 1 else plan(CRITIQUE), OUTPUTS)
    handlers = {
        TaskType.SELECT_TESTS: WriteOnce(store, full_passing_set),
        TaskType.LOCATE: Noop(),
        TaskType.CRITIQUE: Noop(),
    }
    await make_loop(store, trace, policy, runner, handlers).investigate(inv())
    (critique,) = payloads(trace, "critique_result")
    assert critique["clean"] is True and critique["gating"] is True and critique["accepted_as_clean"] is True
    assert payloads(trace, "stop")[0]["critiqued_clean"] is True


async def test_plan_context_records_what_the_playbook_would_have_advised(
    store: EvidenceStore, trace: TraceLog, policy: PolicyStore
) -> None:
    """Để đo Planner đi theo hay chệch sổ tay: tình huống, lời khuyên và kết luận so sánh nằm cạnh kế hoạch."""
    runner = FakeRunner(lambda n: plan(SELECT, LOCATE), OUTPUTS)
    handlers = {TaskType.SELECT_TESTS: Noop(), TaskType.LOCATE: Noop()}
    await make_loop(store, trace, policy, runner, handlers, RequirementBudget(rounds=1)).investigate(inv())
    (ctx,) = payloads(trace, "plan_context")
    assert ctx["rtype"] == "B" and ctx["planned"] == ["SELECT_TESTS", "LOCATE"]
    assert ctx["advice"]["rule"] == "R1-B" and sorted(ctx["advice"]["tasks"]) == ["LOCATE", "SELECT_TESTS"]
    assert ctx["adherence"] == "followed"


# ---------------------------------------------------------------- phối hợp: ngữ cảnh worker, dấu vết lỗi, khe đo


async def test_workers_and_critic_receive_the_evidence_state(
    store: EvidenceStore, trace: TraceLog, policy: PolicyStore
) -> None:
    """Phản biện thấy bằng chứng đã có và độ đủ (kèm feasible); Test chỉ thấy phần còn thiếu, không thấy T1 (Bảng 11)."""
    runner = FakeRunner(lambda n: plan(SELECT, LOCATE) if n == 1 else plan(CRITIQUE), OUTPUTS)
    handlers = {
        TaskType.SELECT_TESTS: WriteOnce(store, full_passing_set),
        TaskType.LOCATE: Noop(),
        TaskType.CRITIQUE: Noop(),
    }
    await make_loop(store, trace, policy, runner, handlers).investigate(inv())
    by_role = {c.to_role: ctx for c, ctx in zip(runner.calls, runner.contexts, strict=True)}
    assert {"evidence.summary", "verdict.sufficiency"} <= set(by_role["verifier"])
    assert "feasible" in by_role["verifier"]["verdict.sufficiency"]["value"]
    assert {"task.focus", "verdict.missing"} <= set(by_role["tester"])
    assert not {"evidence.summary", "verdict.sufficiency"} & set(by_role["tester"])
    # Vùng cách ly chỉ nhận trường nó khai báo: code_reader không khai báo nên không được cấp thêm.
    assert "evidence.summary" not in by_role["code_reader"]


async def test_planner_failure_leaves_a_trace_and_does_not_change_the_flow(
    store: EvidenceStore, trace: TraceLog, policy: PolicyStore
) -> None:
    class Failing(FakeRunner):
        async def run(self, envelope: Envelope, context: dict[str, Any], session: ToolSession) -> RoleOutcome:
            self.calls.append(envelope)
            return RoleOutcome(None, 10, "UnexpectedModelBehavior")

    runner = Failing(lambda n: plan(), {})
    verdict = await make_loop(store, trace, policy, runner, {}, RequirementBudget(rounds=2)).investigate(inv())
    assert verdict.stop_reason is StopReason.BUDGET  # luồng không đổi
    failures = [e["payload"] for e in trace.events("role_failure")]
    assert [f["role"] for f in failures] == ["planner", "planner"]
    assert all(f["failure"] == "UnexpectedModelBehavior" and f["msg_id"] for f in failures)


async def test_task_result_records_new_evidence_per_dispatch(
    store: EvidenceStore, trace: TraceLog, policy: PolicyStore
) -> None:
    runner = FakeRunner(lambda n: plan(SELECT, LOCATE) if n == 1 else plan(CRITIQUE), OUTPUTS)
    handlers = {
        TaskType.SELECT_TESTS: WriteOnce(store, full_passing_set),
        TaskType.LOCATE: Noop(),
        TaskType.CRITIQUE: Noop(),
    }
    await make_loop(store, trace, policy, runner, handlers).investigate(inv())
    results = {e["payload"]["task_type"]: e["payload"]["new_evidence"] for e in trace.events("task_result")}
    assert results == {"SELECT_TESTS": len(full_passing_set()), "LOCATE": 0, "CRITIQUE": 0}


async def test_loop_detector_can_be_injected_for_measurement(
    store: EvidenceStore, trace: TraceLog, policy: PolicyStore
) -> None:
    from rfcv.core.budget import LoopDetector

    made: list[LoopDetector] = []

    def factory() -> LoopDetector:
        made.append(LoopDetector(limit=2))
        return made[-1]

    runner = FakeRunner(lambda n: plan(LOCATE), OUTPUTS)
    loop = ExecutionLoop(
        run_id="run-test",
        runner=runner,
        policy=policy,
        store=store,
        trace=trace,
        handlers={TaskType.LOCATE: Noop()},
        loop_detector=factory,
    )
    verdict = await loop.investigate(inv())
    assert verdict.stop_reason is StopReason.LOOP and len(made) == 1
    assert sum(c.to_role == "code_reader" for c in runner.calls) == 1  # limit=2 chặn sớm hơn mặc định

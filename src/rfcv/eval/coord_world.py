"""Thế giới mô phỏng phối hợp: chạy vòng điều tra THẬT (hub, cổng, handler, Verdict engine), chỉ thay agent bằng kịch bản có lỗi.

KẾT QUẢ LÀ SYNTHETIC. Lỗi của worker và chính sách của Planner do ta cài, nên bộ đo này chỉ khẳng định được:
cận thông tin (một Planner thấy ít hơn thì kém bao nhiêu), cơ chế của hub (phát hiện lặp, dừng sớm), và an toàn (thất bại phối hợp
không bao giờ đảo chiều nhãn). Nó không đo mức phổ biến lỗi của LLM thật.

Worker mô phỏng (hồ sơ lỗi):
- W0 sạch;  W1 cổng từ chối tạm thời (dòng chưa hiển thị) k lần đầu;  W2 sai tên ký hiệu trừ khi nhiệm vụ mang gợi ý;
- W3 báo vị trí hợp lệ nhưng không nằm trên đường thực thi (gợi ý mới sửa được);  W4 kịch bản DSL sai ở lần đầu;
- W5 không trả đầu ra với xác suất p;  W6 Verifier nêu vấn đề giả với xác suất p.
"""

from __future__ import annotations

import dataclasses
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol, cast

from rfcv.adapters.manifest import load_manifest
from rfcv.agents.schemas import Critique, CritiqueIssue, PlanAction
from rfcv.common.prng import hash_randint
from rfcv.core.budget import LoopDetector, RequirementBudget
from rfcv.core.envelope import Envelope
from rfcv.core.execution_loop import ExecutionLoop, Investigation
from rfcv.core.ifc import Labeled, TrustLabel
from rfcv.core.policy import PolicyStore
from rfcv.core.runner import RoleOutcome
from rfcv.core.trace import TraceLog
from rfcv.domains.rfc_protocol.adapter_view import to_vocabulary, vocabulary_terms
from rfcv.domains.rfc_protocol.rules import ProtocolRequirement
from rfcv.domains.rfc_protocol.runtime import ORACLE_KEY, LocationHandler, NoopHandler, ScenarioHandler
from rfcv.domains.rfc_protocol.sandbox.backend import EventTrace
from rfcv.domains.rfc_protocol.sandbox.driver import TestDriver
from rfcv.domains.rfc_protocol.schema_gate import SchemaGate
from rfcv.domains.rfc_protocol.schemas import LocationClaim, ScenarioProposal
from rfcv.domains.rfc_protocol.spec.oracle_compiler import compile_oracle
from rfcv.domains.rfc_protocol.spec.rbs import parse_rbs
from rfcv.eval.coord_mast import classify_trace
from rfcv.eval.faults import LIMIT, SimImpl, correct_behaviour, references
from rfcv.eval.sim import SCENARIO, SimBackend, SimLauncher
from rfcv.eval.strategies import S0
from rfcv.evidence.artifacts import ArtifactStore
from rfcv.evidence.store import EvidenceStore
from rfcv.gates.code_gate import InMemoryCodeIndex, SymbolInfo
from rfcv.gates.tool_gateway import ToolSession
from rfcv.plugins import Registry, current_registry

FILE = "src/internal.c"
SYMBOL = "GetRecordHeader"
LCOV = b"SF:/work/src/internal.c\nDA:812,5\nDA:813,5\nDA:815,5\nDA:816,5\nDA:900,0\nend_of_record\n"
REQ_ID = "SIM-0001"
ACCEPTED_ALERTS = ("record_overflow", "decode_error")
READER_POINTS = (0, 100, LIMIT, LIMIT + 1, 30000, 65535)


@dataclass(frozen=True)
class WorkerProfile:
    name: str
    gate_fail_times: int = 0  # W1
    wrong_symbol: bool = False  # W2
    wrong_location: bool = False  # W3
    dsl_error_first: bool = False  # W4
    no_output_p: float = 0.0  # W5
    verifier_false_issue_p: float = 0.0  # W6


PROFILES: dict[str, WorkerProfile] = {
    p.name: p
    for p in (
        WorkerProfile("W0"),
        WorkerProfile("W1", gate_fail_times=2),
        WorkerProfile("W2", wrong_symbol=True),
        WorkerProfile("W3", wrong_location=True),
        WorkerProfile("W4", dsl_error_first=True),
        WorkerProfile("W5", no_output_p=0.3),
        WorkerProfile("W6", verifier_false_issue_p=0.5),
    )
}


class CoordBackend(SimBackend):
    """SimBackend có dữ liệu độ phủ: khi kích hoạt đạt tới, các dòng kiểm tra 812–816 được thực thi (để V5 đạt được)."""

    async def run(  # type: ignore[override]
        self, scenario: ScenarioProposal, params: dict[str, int | str], endpoint: Any, seed: int
    ) -> EventTrace:
        trace = await super().run(scenario, params, endpoint, seed)
        return dataclasses.replace(trace, lcov=LCOV)


def code_index() -> InMemoryCodeIndex:
    source = [f"/* line {i} */" for i in range(1, 900)]
    source[811] = "    if (*size > MAX_RECORD_SIZE + MAX_MSG_EXTRA) {"
    source[814] = "        SendAlert(ssl, alert_fatal, record_overflow);"
    return InMemoryCodeIndex(
        sources={FILE: source},
        symbols=[SymbolInfo(FILE, SYMBOL, "function", 800, 830, "static int GetRecordHeader(...)")],
        calls=set(),
    )


class WorldView(Protocol):
    """Kênh quan sát chỉ có trong mô phỏng, cho các chính sách 'thấy thế giới' để đo cận thông tin."""

    profile: WorkerProfile
    impl: SimImpl

    def gate_errors(self, task_type: str) -> list[str]: ...


Plan = tuple[str, Sequence[Mapping[str, Any]], str]  # (action, tasks, rationale)


class Policy(Protocol):
    name: str

    def plan(self, ctx: Mapping[str, Any], view: WorldView) -> Plan | None: ...


def _compliant_without_code_evidence(context: Mapping[str, Any]) -> bool:
    """Verifier có năng lực: nhãn tạm COMPLIANT mà trong bản tóm tắt bằng chứng chưa có T1 nào thì nêu MISSING_EVIDENCE."""
    report = cast("dict[str, Any]", (context.get("verdict.sufficiency") or {}).get("value") or {})
    rows = cast("list[dict[str, Any]]", (context.get("evidence.summary") or {}).get("value") or [])
    provisional = cast("dict[str, Any]", report.get("provisional") or {})
    return provisional.get("label") == "COMPLIANT" and not any("T1" in str(r.get("tier")) for r in rows)


class CoordRunner:
    """RoleRunner của mô phỏng: Planner do chính sách, worker do hồ sơ lỗi. Không agent nào ghi bằng chứng."""

    def __init__(self, policy: Policy, view: _View, seed: int) -> None:
        self.policy = policy
        self.view = view
        self.seed = seed
        self.calls: dict[str, int] = {}
        self.planner_contexts: list[dict[str, Any]] = []

    def _n(self, role: str) -> int:
        self.calls[role] = self.calls.get(role, 0) + 1
        return self.calls[role]

    def _drop(self, role: str, p: float, n: int) -> bool:
        return p > 0 and hash_randint(0, 999, "drop", self.seed, role, n) < int(p * 1000)

    async def run(self, envelope: Envelope, context: dict[str, Any], session: ToolSession) -> RoleOutcome:
        role = envelope.to_role
        n = self._n(role)
        prof = self.view.profile
        if role == "planner":
            self.planner_contexts.append(context)
            plan = self.policy.plan(context, self.view)
            if plan is None:
                return RoleOutcome(None, 1, "NO_PLAN")
            action, tasks, rationale = plan
            model: type[PlanAction] = current_registry().schemas["PlanAction@1"]  # type: ignore[assignment]
            return RoleOutcome(
                model.model_validate({"action": action, "tasks": list(tasks), "rationale_code": rationale}), 1
            )
        if self._drop(role, prof.no_output_p, n):
            return RoleOutcome(None, 1, "NO_OUTPUT")
        if role == "test":
            if prof.dsl_error_first and n == 1:
                bad = ScenarioProposal.model_validate(
                    {"requirement_id": REQ_ID, "reach_state": "connected", "steps": [{"op": "complete_handshake"}]}
                )
                return RoleOutcome(bad, 1)
            return RoleOutcome(SCENARIO, 1)
        if role == "code_reader":
            return RoleOutcome(self._claim(envelope, session, n), 1)
        if role == "verifier":
            false_issue = prof.verifier_false_issue_p > 0 and self._drop(
                "verifier", prof.verifier_false_issue_p, n
            )
            issues = [CritiqueIssue(kind="MISSING_PATH", evidence_id=None, suggested_task="TRACE_PATHS")]
            if _compliant_without_code_evidence(context):
                issues = [CritiqueIssue(kind="MISSING_EVIDENCE", evidence_id=None, suggested_task="LOCATE")]
                return RoleOutcome(Critique(issues=issues), 1)
            return RoleOutcome(Critique(issues=issues if false_issue else []), 1)
        return RoleOutcome(None, 0, "UNKNOWN_ROLE")

    def _claim(self, envelope: Envelope, session: ToolSession, n: int) -> LocationClaim:
        prof = self.view.profile
        params = envelope.body.get("params", {})
        hinted = params.get("start_hints") == "locator" or bool(params.get("target_symbol"))
        symbol = "GetRecordHdr" if prof.wrong_symbol and not hinted else SYMBOL
        lines = (900, 904) if prof.wrong_location and params.get("start_hints") != "locator" else (812, 816)
        if not (prof.gate_fail_times and n <= prof.gate_fail_times):
            session.shown_lines |= {(FILE, i) for i in range(800, 831)}
        impl = self.view.impl.behaviour(16641 + 4000, 0)
        match = impl.alert in ACCEPTED_ALERTS and impl.closed  # RBS có accept_alternatives send_alert(decode_error)
        # Người đọc mã lý tưởng nhưng hữu hạn: nhìn điều kiện ở các điểm đặc trưng, độc lập với các giá trị kiểm thử T3 chọn.
        deviates = any(self.view.impl.behaviour(v, 0) != correct_behaviour(v, 0) for v in READER_POINTS)
        reaction = {"aspect": "REACTION", "value": "MATCH" if match else "MISMATCH", "lines": [815, 815]}
        if not match and impl.alert not in ("none", *ACCEPTED_ALERTS):
            reaction["observed"] = f"send_alert({impl.alert})"
        return LocationClaim.model_validate(
            {
                "file": FILE,
                "symbol": symbol,
                "line_start": lines[0],
                "line_end": lines[1],
                "check_kind": "LENGTH_BOUND",
                "finding": "PRESENT",
                "aspects": [{"aspect": "CONDITION", "value": "MISMATCH" if deviates else "MATCH", "observed": None, "lines": [812, 812]}, reaction],
            }
        )


@dataclass
class _View:
    profile: WorkerProfile
    impl: SimImpl
    trace: TraceLog | None = None

    def gate_errors(self, task_type: str) -> list[str]:
        """Mã lỗi cổng của lần giao gần nhất (kênh quan sát riêng của mô phỏng, KHÔNG có trong ngữ cảnh Planner)."""
        if self.trace is None:
            return []
        rejects = [e["payload"] for e in self.trace.events("gate_reject")]
        errors = [str(x) for r in rejects[-1:] for x in r.get("errors", [])]
        return errors if task_type in ("LOCATE", "SELECT_TESTS", "RECHECK", "TRACE_PATHS") else []


@dataclass(frozen=True)
class CellResult:
    label: str
    rule: str
    assurance: str | None
    stop_reason: str
    planner_calls: int
    dispatches: int
    wasted: int  # số vòng mà báo cáo độ đủ không đổi so với vòng trước (việc đã giao không làm tiến triển gì)
    idle_dispatches: int  # số lần giao không tạo bằng chứng mới
    task_rejected: int
    stop_rejected: int
    role_failures: int
    gate_rejects: int
    chain_ok: bool
    tags: tuple[str, ...] = field(default=())


def _stalled_rounds(reports: Sequence[Mapping[str, Any]]) -> int:
    """Vòng i (>0) mà báo cáo độ đủ giống hệt vòng i-1: vòng trước không làm tiến triển."""
    body = [{k: v for k, v in r.items() if k != "round"} for r in reports]
    return sum(1 for a, b in pairwise(body) if a == b)


async def run_cell(
    adapter_dir: Path,
    impl: SimImpl,
    profile: WorkerProfile,
    policy: Policy,
    *,
    seed: int,
    loop_detector: Any = None,
    progress_of: Any = None,
    budget: RequirementBudget | None = None,
    registry: Registry | None = None,
) -> CellResult:
    reg = registry or current_registry()
    manifest = load_manifest(adapter_dir)
    vocab = to_vocabulary(manifest)
    terms = vocabulary_terms(manifest)
    oracle = compile_oracle(parse_rbs(S0.rbs()), vocab)
    refs = references()
    store, trace = EvidenceStore(":memory:"), TraceLog(":memory:")
    view = _View(profile, impl, trace)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            rt = SimpleNamespace(
                run_id="coord", trace=trace, store=store, artifacts=ArtifactStore(Path(tmp) / "a"), seed=seed
            )
            driver = TestDriver(
                CoordBackend([impl, *refs]),
                SimLauncher(),
                store,
                rt.artifacts,
                trace,
                sut_impl=impl.name,
                references=[r.name for r in refs],
            )
            handlers: dict[str, Any] = {
                "LOCATE": LocationHandler(rt, SchemaGate(code_index(), terms)),
                "SELECT_TESTS": ScenarioHandler(rt, driver),
                "CRITIQUE": NoopHandler(),
            }
            handlers["TRACE_PATHS"] = handlers["RECHECK"] = handlers["LOCATE"]
            runner = CoordRunner(policy, view, seed)
            req = ProtocolRequirement(
                REQ_ID,
                oracle.rtype,
                "MUST",
                required_variants=oracle.required_variant_names,
                random_k=oracle.random_k,
                valid_random_k=oracle.valid_random_k,
            )
            inv = Investigation(
                requirement=req,
                context={
                    "requirement.structured": Labeled({"id": REQ_ID, "rtype": oracle.rtype}, TrustLabel.TRUSTED),
                    "adapter.vocabulary": Labeled(sorted(terms), TrustLabel.TRUSTED),
                },
                vocabulary_terms=terms,
                domain_state={ORACLE_KEY: oracle},
            )
            loop = ExecutionLoop(
                run_id="coord",
                runner=runner,
                policy=PolicyStore.load(None, reg, "rfc_protocol"),
                store=store,
                trace=trace,
                handlers=handlers,
                budget=budget or RequirementBudget(),
                loop_detector=loop_detector or LoopDetector,
                progress_of=progress_of,
            )
            verdict = await loop.investigate(inv)
            kinds = [e["kind"] for e in trace.events()]
            results = [e["payload"] for e in trace.events("task_result")]
            return CellResult(
                label=verdict.label.value,
                rule=verdict.rule,
                assurance=str(verdict.assurance) if verdict.assurance else None,
                stop_reason=verdict.stop_reason.value,
                planner_calls=runner.calls.get("planner", 0),
                dispatches=len(results),
                wasted=_stalled_rounds([e["payload"] for e in trace.events("sufficiency")]),
                idle_dispatches=sum(1 for r in results if r["new_evidence"] == 0 and r["task_type"] != "CRITIQUE"),
                task_rejected=kinds.count("task_rejected"),
                stop_rejected=kinds.count("stop_rejected"),
                role_failures=kinds.count("role_failure"),
                gate_rejects=kinds.count("gate_reject"),
                chain_ok=store.verify_chain().ok,
                tags=tuple(sorted(classify_trace(trace.events(), unavailable_tasks=("MAP_COMPONENTS", "STATIC_QUERY")))),
            )
    finally:
        store.close()

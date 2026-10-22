"""Sáu bất biến từng chưa có kiểm thử riêng (CT-21, BL-61): SG-6, TG-4, EL-7, SK-1, QS-07, VF-6.

Dùng mô hình giả và đồng hồ giả: không gọi LLM thật, không cần Docker.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel
from pydantic_ai import ModelRetry
from pydantic_ai.models.test import TestModel

from helpers import full_passing_set
from rfcv.agents.schemas import Critique, CritiqueIssue
from rfcv.core.budget import BudgetTracker, RequirementBudget
from rfcv.core.llm_gateway import LLMGateway, ModelsConfig
from rfcv.core.policy import PolicyStore
from rfcv.core.skills import validate_library
from rfcv.core.trace import TraceLog
from rfcv.domains.rfc_protocol.schemas import TaskType
from rfcv.evidence.store import EvidenceStore
from rfcv.evidence.verdict_engine import Label, StopReason
from rfcv.gates.code_gate import InMemoryCodeIndex, build_code_tools
from rfcv.gates.explore_policy import CodeScope
from rfcv.gates.tool_gateway import MAX_OUTPUT_RETRIES, DenyCode, ToolDenied, ToolGateway, ToolSession
from rfcv.runtime.pydantic_ai import PydanticAIRoleRunner
from test_execution_loop import CRITIQUE, LOCATE, OUTPUTS, SELECT, FakeRunner, Noop, WriteOnce, inv, make_loop, plan
from test_skills import TASKS, write_skill

# ---------------------------------------------------------------- SG-6: vòng làm lại của Schema gate


def _runner(policy: PolicyStore, trace: TraceLog) -> PydanticAIRoleRunner:
    llm = LLMGateway(ModelsConfig(), env={}, overrides={"code_reader": TestModel()})
    return PydanticAIRoleRunner(policy, ToolGateway(policy, trace), llm, trace)


def _ctx(session: ToolSession) -> Any:
    return SimpleNamespace(deps=session)


class _Out(BaseModel):
    x: int = 1


def test_output_rejection_lets_the_agent_retry_a_bounded_number_of_times(policy: PolicyStore, trace: TraceLog) -> None:
    runner = _runner(policy, trace)
    session = ToolSession("run-test", "code_reader", "TLS13-0042", max_tool_calls=5)
    session.output_check = lambda out: ["LINE_NOT_SHOWN", "SYMBOL_UNKNOWN"]
    out = _Out()
    for attempt in range(1, MAX_OUTPUT_RETRIES + 1):
        with pytest.raises(ModelRetry) as exc:
            runner._check_output(_ctx(session), out)  # pyright: ignore[reportPrivateUsage]
        assert session.output_rejections == attempt
        # Chỉ mã lỗi liệt kê trả về cho agent, không kèm giải thích hay chi tiết cổng.
        assert "LINE_NOT_SHOWN" in str(exc.value) and "SYMBOL_UNKNOWN" in str(exc.value)
    # Hết lượt làm lại: trả đầu ra nguyên vẹn để handler kiểm tra và ghi gate_reject, không lặp vô hạn.
    assert runner._check_output(_ctx(session), out) is out  # pyright: ignore[reportPrivateUsage]
    assert session.output_rejections == MAX_OUTPUT_RETRIES
    retries = [e["payload"] for e in trace.events("output_retry")]
    assert [r["attempt"] for r in retries] == list(range(1, MAX_OUTPUT_RETRIES + 1))
    assert all(r["errors"] == ["LINE_NOT_SHOWN", "SYMBOL_UNKNOWN"] for r in retries)


def test_output_passing_the_gate_is_returned_without_retry(policy: PolicyStore, trace: TraceLog) -> None:
    runner = _runner(policy, trace)
    session = ToolSession("run-test", "code_reader", "TLS13-0042", max_tool_calls=5)
    session.output_check = lambda out: []
    out = _Out()
    assert runner._check_output(_ctx(session), out) is out  # pyright: ignore[reportPrivateUsage]
    assert session.output_rejections == 0 and not list(trace.events("output_retry"))


# ---------------------------------------------------------------- TG-4: từ chối không lộ chi tiết chính sách


@pytest.fixture
def code_gateway(policy: PolicyStore, trace: TraceLog, tmp_path: Path) -> ToolGateway:
    (tmp_path / "src").mkdir()
    (tmp_path / "certs").mkdir()
    (tmp_path / "certs" / "server.key").write_text("SECRET\n")
    scope = CodeScope(root=tmp_path, include=("src/**", "src"), exclude=("**/*.key", "certs/**"))

    class Executor:
        async def run(self, segments: list[list[str]], timeout_s: float) -> str:
            return ""

    gw = ToolGateway(policy, trace)
    for spec in build_code_tools(InMemoryCodeIndex({}), Executor(), scope):
        gw.register(spec)
    return gw


async def test_denial_returns_only_the_enumerated_code(code_gateway: ToolGateway, trace: TraceLog) -> None:
    session = ToolSession("run-test", "code_reader", "TLS13-0042", max_tool_calls=10)
    with pytest.raises(ToolDenied) as exc:
        await code_gateway.call(session, "code.explore", {"command": "cat certs/server.key"})
    # Agent chỉ nhận mã liệt kê; lý do chi tiết (đường dẫn ngoài phạm vi, cờ bị chặn...) chỉ nằm trong trace.
    assert exc.value.code is DenyCode.COMMAND_REJECTED
    assert exc.value.args == ("COMMAND_REJECTED",) and str(exc.value) == "COMMAND_REJECTED"
    assert "PATH_OUT_OF_SCOPE" not in repr(exc.value) and "server.key" not in str(exc.value)
    reasons = [e["payload"].get("reason") for e in trace.events("tool_denied")]
    assert reasons == ["PATH_OUT_OF_SCOPE"]


async def test_role_denial_does_not_reveal_the_policy(code_gateway: ToolGateway) -> None:
    session = ToolSession("run-test", "planner", "TLS13-0042", max_tool_calls=10)
    with pytest.raises(ToolDenied) as exc:
        await code_gateway.call(session, "code.explore", {"command": "rg x src"})
    assert str(exc.value) == "ROLE_NOT_ALLOWED"
    # Không nêu vai trò nào được phép, công cụ nào có, hay tên tệp chính sách.
    for leak in ("code_reader", "allow", "policy", "role.yaml"):
        assert leak not in str(exc.value).lower().replace("role_not_allowed", "")


# ---------------------------------------------------------------- EL-7: ngân sách thời gian


def test_seconds_budget_is_exhausted_by_the_clock() -> None:
    now = [100.0]
    tracker = BudgetTracker(RequirementBudget(seconds=30.0), clock=lambda: now[0])
    assert tracker.exhausted_by() == []
    now[0] = 129.9
    assert not tracker.exhausted()
    now[0] = 130.0
    assert tracker.exhausted_by() == ["seconds"]
    assert tracker.remaining()["seconds"] == 0


async def test_loop_stops_with_budget_reason_when_time_runs_out(
    store: EvidenceStore, trace: TraceLog, policy: PolicyStore
) -> None:
    runner = FakeRunner(lambda n: plan(LOCATE), OUTPUTS)
    loop = make_loop(store, trace, policy, runner, {TaskType.LOCATE: Noop()}, RequirementBudget(seconds=0.0))
    verdict = await loop.investigate(inv())
    assert (verdict.label, verdict.stop_reason) == (Label.UNVERIFIABLE, StopReason.BUDGET)
    stop = next(iter(trace.events("stop")))["payload"]
    assert stop["exhausted_by"] == ["seconds"]
    assert not runner.calls  # hết giờ thì không giao thêm việc nào


# ---------------------------------------------------------------- SK-1: skill chứa symlink bị từ chối


def _make_symlink(link: Path, target: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tạo symlink thật. Windows thường không cấp quyền này: khi đó giả lập `is_symlink` cho đúng đường dẫn, để kiểm tra
    của validate_library vẫn được chạy thay vì bị bỏ qua."""
    try:
        link.symlink_to(target)
    except OSError:
        link.write_text("giả lập symlink", encoding="utf-8")
        real = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda self: self == link or real(self))


def test_skill_with_a_symlink_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lib = tmp_path / "lib"
    skill = write_skill(lib, "alpha")
    secret = tmp_path / "outside.md"
    secret.write_text("bí mật ngoài thư viện", encoding="utf-8")
    _make_symlink(skill / "notes.md", secret, monkeypatch)
    result = validate_library(lib, TASKS)
    assert not result.skills and any("symlink" in e for e in result.errors), result.errors


def test_skill_with_a_symlink_in_references_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lib = tmp_path / "lib"
    skill = write_skill(lib, "alpha", extra={"references/ok.md": "ok"})
    secret = tmp_path / "outside.md"
    secret.write_text("bí mật ngoài thư viện", encoding="utf-8")
    _make_symlink(skill / "references" / "evil.md", secret, monkeypatch)
    result = validate_library(lib, TASKS)
    assert not result.skills and result.errors, result.errors


def test_a_skill_without_symlinks_is_accepted(tmp_path: Path) -> None:
    """Đối chứng: cùng thư viện, không có symlink thì hợp lệ (để hai test trên không đỏ vì lý do khác)."""
    lib = tmp_path / "lib"
    write_skill(lib, "alpha", extra={"references/ok.md": "ok"})
    result = validate_library(lib, TASKS)
    assert [s.name for s in result.skills] == ["alpha"] and not result.errors, result.errors


# ---------------------------------------------------------------- QS-07: khoá API không xuất hiện trong dữ liệu lần chạy

SECRET = "sk-test-KHOA-BI-MAT-0123456789"


def secret_hits(root: Path, secret: str) -> list[str]:
    """Quét mọi tệp dưới `root` (kể cả nội dung các bảng SQLite) tìm `secret`; trả về tên tệp có chứa."""
    needle = secret.encode()
    hits: list[str] = []
    for f in sorted(p for p in root.rglob("*") if p.is_file()):
        if needle in f.read_bytes():
            hits.append(f.name)
            continue
        if f.suffix == ".db":
            con = sqlite3.connect(f)
            try:
                tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
                for t in tables:
                    if any(secret in str(v) for row in con.execute(f'select * from "{t}"') for v in row):
                        hits.append(f.name)
                        break
            finally:
                con.close()
    return hits


def test_the_scanner_finds_a_planted_secret(tmp_path: Path) -> None:
    """Chứng minh bộ quét không bị mù: một khoá cố tình nhét vào trace phải bị phát hiện."""
    log = TraceLog(tmp_path / "trace.db")
    log.append("run-test", "oops", {"header": f"Authorization: Bearer {SECRET}"})
    assert secret_hits(tmp_path, SECRET) == ["trace.db"]


async def test_run_data_does_not_contain_the_api_key(
    tmp_path: Path, store: EvidenceStore, trace: TraceLog, policy: PolicyStore
) -> None:
    cfg = ModelsConfig.model_validate(
        {
            "models": {"m": {"provider": "openai", "model": "x", "api_key_env": "RFCV_TEST_KEY"}},
            "agents": {r: "m" for r in policy.roles},
        }
    )
    llm = LLMGateway(cfg, env={"RFCV_TEST_KEY": SECRET})
    # Hash cấu hình và mô tả mô hình cũng không được mang khoá.
    assert SECRET not in llm.digest and SECRET not in repr(cfg)
    runner = FakeRunner(lambda n: plan(SELECT, LOCATE) if n == 1 else plan(CRITIQUE), OUTPUTS)
    handlers = {
        TaskType.SELECT_TESTS: WriteOnce(store, full_passing_set),
        TaskType.LOCATE: Noop(),
        TaskType.CRITIQUE: Noop(),
    }
    await make_loop(store, trace, policy, runner, handlers).investigate(inv())
    assert list(trace.events()) and store.for_requirement(inv().requirement.requirement_id)
    assert secret_hits(tmp_path, SECRET) == []


# ---------------------------------------------------------------- VF-6: Verifier không được bịa evidence_id


REAL = "<mã bằng chứng thật trong kho>"


class _WriteThenCite(WriteOnce):
    """Ghi bằng chứng rồi cho Verifier giả dẫn đúng mã đầu tiên trong kho (bằng chứng thật)."""

    def __init__(self, store: EvidenceStore, outputs: dict[str, BaseModel]) -> None:
        super().__init__(store, full_passing_set)
        self.outputs = outputs

    async def handle(self, inv: Any, task: Any, output: Any, session: Any, msg_id: str) -> int:
        n = await super().handle(inv, task, output, session, msg_id)
        real_id = self.store.for_requirement(inv.requirement.requirement_id)[0].evidence_id
        issue = CritiqueIssue(kind="WEAK_EVIDENCE", evidence_id=real_id, suggested_task="SELECT_TESTS")
        self.outputs["verifier"] = Critique(issues=[issue])
        return n


async def _critique_with(
    evidence_id: str | None, store: EvidenceStore, trace: TraceLog, policy: PolicyStore
) -> list[str]:
    issue = CritiqueIssue(kind="WEAK_EVIDENCE", evidence_id=evidence_id, suggested_task="SELECT_TESTS")
    outputs: dict[str, BaseModel] = {**OUTPUTS, "verifier": Critique(issues=[issue])}
    runner = FakeRunner(lambda n: plan(SELECT, LOCATE) if n == 1 else plan(CRITIQUE), outputs)
    select: WriteOnce = _WriteThenCite(store, outputs) if evidence_id == REAL else WriteOnce(store, full_passing_set)
    handlers = {
        TaskType.SELECT_TESTS: select,
        TaskType.LOCATE: Noop(),
        TaskType.CRITIQUE: Noop(),
    }
    await make_loop(store, trace, policy, runner, handlers).investigate(inv())
    result = next(iter(trace.events("critique_result")))["payload"]
    return result["unknown_evidence_ids"]


async def test_fabricated_evidence_id_in_a_critique_is_flagged(
    store: EvidenceStore, trace: TraceLog, policy: PolicyStore
) -> None:
    assert await _critique_with("sha256:bia-ra", store, trace, policy) == ["sha256:bia-ra"]


async def test_real_or_absent_evidence_id_in_a_critique_is_not_flagged(
    store: EvidenceStore, trace: TraceLog, policy: PolicyStore
) -> None:
    assert await _critique_with(None, store, trace, policy) == []


async def test_a_real_evidence_id_in_a_critique_is_not_flagged(
    store: EvidenceStore, trace: TraceLog, policy: PolicyStore
) -> None:
    assert await _critique_with(REAL, store, trace, policy) == []
    issues = next(iter(trace.events("critique_result")))["payload"]["issues"]
    assert issues and issues[0]["evidence_id"]  # Verifier thật sự đã dẫn một mã, và mã đó có trong kho

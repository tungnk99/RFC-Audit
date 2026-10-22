"""Runtime PydanticAI: đúng schema đầu ra, công cụ chỉ đi qua Tool gateway, ghi Trace log. Không gọi LLM thật."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from rfcv.agents.schemas import PlanAction
from rfcv.core.envelope import EnvelopeFactory, MessageKind
from rfcv.core.llm_gateway import LLMGateway, ModelsConfig, ModelSpec, UnknownProviderError
from rfcv.core.policy import PolicyStore
from rfcv.core.prompts import prompts_digest
from rfcv.core.trace import TraceLog
from rfcv.domains.rfc_protocol.schemas import LocationClaim
from rfcv.gates.code_gate import InMemoryCodeIndex, SymbolInfo, build_code_tools
from rfcv.gates.explore_policy import CodeScope
from rfcv.gates.tool_gateway import ToolGateway, ToolSession
from rfcv.runtime.pydantic_ai import PydanticAIRoleRunner


class NoExec:
    async def run(self, segments: list[list[str]], timeout_s: float) -> str:
        return ""


def make_runner(policy: PolicyStore, trace: TraceLog, tmp_path: Path, models: dict[str, Any]) -> PydanticAIRoleRunner:
    gw = ToolGateway(policy, trace)
    index = InMemoryCodeIndex(
        sources={"src/internal.c": [f"line {i}" for i in range(1, 50)]},
        symbols=[SymbolInfo("src/internal.c", "GetRecordHeader", "function", 10, 20)],
    )
    for spec in build_code_tools(index, NoExec(), CodeScope(tmp_path)):
        gw.register(spec)
    llm = LLMGateway(ModelsConfig(), env={}, overrides=models)
    return PydanticAIRoleRunner(policy, gw, llm, trace)


def envelope(role: str):
    return EnvelopeFactory("run-test").make(
        requirement_id="TLS13-0042",
        from_role="execution_loop",
        to_role=role,
        kind=MessageKind.DISPATCH,
        round=1,
        body={"task_type": "LOCATE"},
        budget_left={"rounds": 7},
    )


async def test_code_reader_tools_go_through_gateway(policy: PolicyStore, trace: TraceLog, tmp_path: Path) -> None:
    runner = make_runner(policy, trace, tmp_path, {"code_reader": TestModel(call_tools=["code__read_function"])})
    session = ToolSession("run-test", "code_reader", "TLS13-0042", max_tool_calls=30)
    outcome = await runner.run(envelope("code_reader"), {}, session)
    assert isinstance(outcome.output, LocationClaim)
    calls = list(trace.events("tool_call")) + list(trace.events("tool_denied"))
    assert calls and all(e["role"] == "code_reader" for e in calls)
    assert any(e["payload"]["tool"] == "code.read_function" for e in calls)
    runs = list(trace.events("llm_run"))
    assert runs and runs[0]["payload"]["messages"]


async def test_failed_llm_run_keeps_the_conversation_and_the_tokens_spent(
    policy: PolicyStore, trace: TraceLog, tmp_path: Path
) -> None:
    """Hỏng giữa chừng là lúc cần xem mô hình đã thấy và làm gì; token đã tiêu vẫn tính vào ngân sách."""
    calls = 0

    def model_fn(messages: list[Any], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(parts=[ToolCallPart("code__read_function", {"name": "GetRecordHeader"})])
        raise UnexpectedModelBehavior("mô hình trả lời sai định dạng")

    runner = make_runner(policy, trace, tmp_path, {"code_reader": FunctionModel(model_fn)})
    session = ToolSession("run-test", "code_reader", "TLS13-0042", max_tool_calls=30)
    outcome = await runner.run(envelope("code_reader"), {}, session)

    assert outcome.output is None and outcome.failure == "UnexpectedModelBehavior"
    assert outcome.tokens > 0
    failure = next(iter(trace.events("llm_failure")))["payload"]
    assert failure["error"] == "UnexpectedModelBehavior" and failure["tokens"] == outcome.tokens
    assert failure["duration_ms"] >= 0 and failure["tool_calls"] == session.tool_calls
    parts = [p for msg in failure["messages"] for p in msg.get("parts", [])]
    assert any(p.get("tool_name") == "code__read_function" for p in parts), "lời gọi công cụ trước khi hỏng phải còn"


async def test_provider_http_error_is_a_traced_role_failure_not_a_crash(
    policy: PolicyStore, trace: TraceLog, tmp_path: Path
) -> None:
    def model_fn(messages: list[Any], info: AgentInfo) -> ModelResponse:
        raise ModelHTTPError(503, "model-x")

    runner = make_runner(policy, trace, tmp_path, {"planner": FunctionModel(model_fn)})
    outcome = await runner.run(envelope("planner"), {}, ToolSession("run-test", "planner", "TLS13-0042", 4))
    assert outcome.output is None and outcome.failure == "ModelHTTPError"
    assert next(iter(trace.events("llm_failure")))["payload"]["messages"]


async def test_planner_has_no_code_tools(policy: PolicyStore, trace: TraceLog, tmp_path: Path) -> None:
    runner = make_runner(policy, trace, tmp_path, {"planner": TestModel()})
    tool_names = {t.name for t in runner.agent("planner")._function_toolset.tools.values()}  # pyright: ignore
    assert not any(n.startswith("code__") for n in tool_names)
    outcome = await runner.run(envelope("planner"), {}, ToolSession("run-test", "planner", "TLS13-0042", 4))
    assert isinstance(outcome.output, PlanAction)
    assert not list(trace.events("tool_call"))


def test_tool_names_have_no_dots(policy: PolicyStore, trace: TraceLog, tmp_path: Path) -> None:
    runner = make_runner(policy, trace, tmp_path, {"code_reader": TestModel()})
    names = runner.agent("code_reader")._function_toolset.tools  # pyright: ignore
    assert names and all("." not in n for n in names)


def one_model(provider: str = "anthropic", key_env: str = "ANTHROPIC_API_KEY", **agents: str) -> ModelsConfig:
    return ModelsConfig(
        models={"m1": ModelSpec(provider=provider, model="some-model", api_key_env=key_env)},
        agents=agents or {"planner": "m1"},
    )


def test_gateway_requires_key_and_never_exposes_it() -> None:
    config = one_model()
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        LLMGateway(config, env={}).model_for("planner")
    assert "sk-" not in LLMGateway(config, env={"ANTHROPIC_API_KEY": "sk-secret"}).digest


def test_models_config_loads_and_prompts_hash(policy: PolicyStore) -> None:
    root = Path(__file__).resolve().parents[1]
    gw = LLMGateway.load(root / "config" / "models.yaml", env={})
    assert gw.digest.startswith("sha256:")
    assert prompts_digest(policy, ["planner", "code_reader"]).startswith("sha256:")


def test_every_agent_of_the_project_is_assigned_a_declared_model(policy: PolicyStore) -> None:
    """Khai báo mô hình một lần, gán cho agent ở mục riêng; mọi agent phải có mô hình và mô hình phải có khai báo."""
    root = Path(__file__).resolve().parents[1]
    gw = LLMGateway.load(root / "config" / "models.yaml", env={})
    assert gw.uncovered(policy.roles) == []
    gw.validate()


def test_an_agent_can_only_use_a_model_declared_in_the_catalog() -> None:
    with pytest.raises(ValueError, match="chưa khai báo"):
        ModelsConfig(models={}, agents={"planner": "ghost-model"})


def test_agents_sharing_a_model_share_its_handle_and_each_can_be_switched_alone() -> None:
    config = ModelsConfig(
        models={
            "fast": ModelSpec(provider="p", model="a", api_key_env="K"),
            "deep": ModelSpec(provider="p", model="b", api_key_env="K"),
        },
        agents={"planner": "fast", "tester": "fast", "verifier": "deep", "rfc_analyst.b": "deep"},
    )
    built: list[str] = []

    def factory(spec: ModelSpec, api_key: str) -> object:
        built.append(spec.model)
        return object()

    gw = LLMGateway(config, env={"K": "v"}, providers={"p": factory})
    assert gw.model_for("planner") is gw.model_for("tester")  # cùng một mô hình thì dùng chung một handle
    assert gw.model_for("verifier") is not gw.model_for("planner")
    assert gw.model_for("rfc_analyst.b") is gw.model_for("verifier")
    assert sorted(built) == ["a", "b"]  # mỗi mô hình dựng đúng một lần
    assert gw.uncovered(["planner", "rfc_analyst", "report"]) == ["report"]  # gán theo luồng (rfc_analyst.b) cũng tính


def test_unknown_provider_is_rejected_before_any_call() -> None:
    config = one_model(provider="mystery-cloud", key_env="K")
    gw = LLMGateway(config, env={"K": "v"})
    with pytest.raises(UnknownProviderError):
        gw.validate()
    with pytest.raises(UnknownProviderError):
        gw.model_for("planner")


def test_an_unassigned_agent_is_reported_by_name() -> None:
    with pytest.raises(KeyError, match="verifier"):
        LLMGateway(one_model(), env={"ANTHROPIC_API_KEY": "k"}).model_for("verifier")


def test_every_tool_result_tells_the_agent_how_much_tool_budget_is_left() -> None:
    """Agent không thấy bộ đếm thì không thể "dừng khi còn khoảng 20%": Code Reader từng chạm giới hạn 30 lời gọi và hỏng."""
    from rfcv.runtime.pydantic_ai.runner import budget_note

    s = ToolSession("run-test", "code_reader", "TLS13-0042", max_tool_calls=30)
    s.tool_calls = 10
    assert budget_note(s) == "\n[ngân sách công cụ: đã dùng 10/30, còn 20]"
    s.tool_calls = 25
    assert "còn 5]" in budget_note(s) and "Sắp hết" in budget_note(s)
    assert budget_note(ToolSession("run-test", "planner", None, max_tool_calls=0)) == ""

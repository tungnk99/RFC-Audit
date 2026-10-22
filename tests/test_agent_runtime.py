"""Runtime PydanticAI: đúng schema đầu ra, công cụ chỉ đi qua Tool gateway, ghi Trace log. Không gọi LLM thật."""

from __future__ import annotations

from pathlib import Path

import pytest
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


def make_runner(
    policy: PolicyStore, trace: TraceLog, tmp_path: Path, models: dict[str, TestModel]
) -> PydanticAIRoleRunner:
    gw = ToolGateway(policy, trace)
    index = InMemoryCodeIndex(
        sources={"src/internal.c": [f"line {i}" for i in range(1, 50)]},
        symbols=[SymbolInfo("src/internal.c", "GetRecordHeader", "function", 10, 20)],
    )
    for spec in build_code_tools(index, NoExec(), CodeScope(tmp_path)):
        gw.register(spec)
    llm = LLMGateway(ModelsConfig(roles={}), env={}, overrides=models)
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


def test_gateway_requires_key_and_never_exposes_it() -> None:
    config = ModelsConfig(
        roles={"planner": ModelSpec(provider="anthropic", model="claude-sonnet-5-5", api_key_env="ANTHROPIC_API_KEY")}
    )
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        LLMGateway(config, env={}).model_for("planner")
    assert "sk-" not in LLMGateway(config, env={"ANTHROPIC_API_KEY": "sk-secret"}).digest


def test_models_config_loads_and_prompts_hash(policy: PolicyStore) -> None:
    root = Path(__file__).resolve().parents[1]
    gw = LLMGateway.load(root / "config" / "models.yaml", env={})
    assert gw.digest.startswith("sha256:")
    assert prompts_digest(policy, ["planner", "code_reader"]).startswith("sha256:")


def test_unknown_provider_is_rejected_before_any_call() -> None:
    config = ModelsConfig(roles={"planner": ModelSpec(provider="mystery-cloud", model="x", api_key_env="K")})
    gw = LLMGateway(config, env={"K": "v"})
    with pytest.raises(UnknownProviderError):
        gw.validate()
    with pytest.raises(UnknownProviderError):
        gw.model_for("planner")

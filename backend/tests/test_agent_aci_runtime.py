"""Kiểm thử Unified ACI & Runtime: static skills, đa output_mode, JSON coercion, nén lịch sử, inline #ifdef và nén Report."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agents.code_reader.schema import AspectClaim, CheckKind, LocationClaim
from conftest import ROOT
from helpers import as_evidence, t1, t3
from rfcv.agents.schemas import PlanAction
from rfcv.core.context_builder import summarize_evidence, to_jsonable
from rfcv.core.envelope import EnvelopeFactory, MessageKind
from rfcv.core.llm_gateway import LLMGateway, ModelsConfig, ModelSpec
from rfcv.core.policy import PolicyStore
from rfcv.core.skills import default_registry
from rfcv.core.trace import TraceLog
from rfcv.domains.rfc_protocol.payloads import AspectName, AspectValue, Finding, Outcome
from rfcv.gates.code_gate import InMemoryCodeIndex, SymbolInfo
from rfcv.gates.code_tools import ReadParams, build_cc_tools
from rfcv.gates.tool_gateway import ToolGateway, ToolSession
from rfcv.runtime.pydantic_ai.runner import (
    KEEP_TOOL_RESULTS,
    READ_KEEP_CHARS,
    WRAP_UP_SHARE,
    PydanticAIRoleRunner,
    _coerce_model,  # pyright: ignore[reportPrivateUsage]
    _coerce_output_payload,  # pyright: ignore[reportPrivateUsage]
    _output_spec,  # pyright: ignore[reportPrivateUsage]
    salvage,
    thin_history,
)


def test_model_spec_defaults_to_static_skills_and_tool_output_mode() -> None:
    spec = ModelSpec(provider="openai_compatible", model="glm-4.5-flash")
    assert spec.output_mode == "tool"
    assert spec.static_skills is True

    cfg = ModelsConfig.model_validate(
        {
            "models": {
                "glm": {
                    "provider": "openai_compatible",
                    "model": "glm-4.5-flash",
                    "output_mode": "prompted",
                    "static_skills": True,
                }
            },
            "agents": {"verifier": "glm"},
        }
    )
    gw = LLMGateway(cfg, env={})
    assert gw.output_mode_for("verifier") == "prompted"
    assert gw.static_skills_for("verifier") is True


def test_output_spec_supports_tool_native_and_prompted() -> None:
    from pydantic_ai import NativeOutput, PromptedOutput

    assert _output_spec(PlanAction, "tool") is PlanAction
    assert isinstance(_output_spec(PlanAction, "native"), NativeOutput)
    assert isinstance(_output_spec(PlanAction, "prompted"), PromptedOutput)


async def test_static_skills_injects_body_into_instructions_without_load_capability(
    policy: PolicyStore, trace: TraceLog
) -> None:
    reg = default_registry(ROOT / "skills", "tls13")
    seen: dict[str, Any] = {}

    def fn(messages: list[Any], info: AgentInfo) -> ModelResponse:
        seen["instructions"] = info.instructions or ""
        seen["tools"] = [t.name for t in info.function_tools]
        return ModelResponse(
            parts=[ToolCallPart("final_result", {"action": "stop", "rationale_code": "INFEASIBLE", "tasks": []})]
        )

    llm = LLMGateway(ModelsConfig(), env={}, overrides={"planner": FunctionModel(fn)})
    runner = PydanticAIRoleRunner(policy, ToolGateway(policy, trace), llm, trace, skills=reg, static_skills=True)
    env = EnvelopeFactory("run-static").make(
        requirement_id="TLS13-0042",
        from_role="execution_loop",
        to_role="planner",
        kind=MessageKind.DISPATCH,
        round=1,
        body={},
        budget_left={},
    )
    outcome = await runner.run(env, {}, ToolSession("run-static", "planner", "TLS13-0042", 4))
    assert isinstance(outcome.output, PlanAction)
    assert "load_capability" not in seen["tools"]
    assert "Skill: summarize-evidence-for-planner" in seen["instructions"]
    run = next(iter(trace.events("llm_run")))["payload"]
    assert run["skills_mode"] == "static"
    assert run["skills_offered"] == ["summarize-evidence-for-planner"]
    assert run["skills_loaded"] == ["summarize-evidence-for-planner"]


def test_coercion_fixes_string_threshold_and_salvages_fenced_json() -> None:
    raw = {
        "file": "src/internal.c",
        "symbol": "GetRecordHeader",
        "line_start": 10,
        "line_end": 15,
        "check_kind": "LENGTH_BOUND",
        "finding": "PRESENT",
        "aspects": [
            {"aspect": "THRESHOLD", "value": "MISMATCH", "observed": "16486", "lines": [12, 12]},
        ],
    }
    coerced = _coerce_output_payload(raw)
    assert coerced["aspects"][0]["observed"] == 16486

    claim = LocationClaim(
        file="src/internal.c",
        symbol="GetRecordHeader",
        line_start=10,
        line_end=15,
        check_kind=CheckKind.LENGTH_BOUND,
        finding=Finding.PRESENT,
        aspects=[
            AspectClaim(aspect=AspectName.THRESHOLD, value=AspectValue.MISMATCH, observed="16486", lines=(12, 12))
        ],
    )
    fixed = _coerce_model(claim)
    assert isinstance(fixed, LocationClaim)
    assert fixed.aspects[0].observed == 16486

    fenced = f"Đây là kết quả:\n```json\n{json.dumps(raw)}\n```"
    # Mặc định (tool/native mode) KHÔNG salvage JSON từ TextPart để tránh bản nháp lọt qua cổng
    assert salvage([ModelResponse(parts=[TextPart(fenced)])], LocationClaim) is None
    # Chỉ cho phép salvage TextPart ở prompted mode
    salvaged = salvage([ModelResponse(parts=[TextPart(fenced)])], LocationClaim, allow_text_json=True)
    assert isinstance(salvaged, LocationClaim)
    assert salvaged.aspects[0].observed == 16486

    # Chuỗi số siêu dài (>18 chữ số) không gây ValueError DoS
    huge_raw = dict(raw)
    huge_raw["aspects"] = [{"aspect": "THRESHOLD", "value": "MISMATCH", "observed": "9" * 5000, "lines": [12, 12]}]
    assert _coerce_output_payload(huge_raw)["aspects"][0]["observed"] == "9" * 5000


def test_thin_history_uses_compact_defaults() -> None:
    assert KEEP_TOOL_RESULTS == 2
    assert READ_KEEP_CHARS == 20_000
    assert WRAP_UP_SHARE == 0.65

    @dataclass
    class _FakeUsage:
        total_tokens: int = 0

    @dataclass
    class _FakeCtx:
        deps: ToolSession
        usage: _FakeUsage

    session = ToolSession("run-thin", "code_reader", "TLS13-0042", 10, max_tokens=100_000)
    msgs: list[Any] = [
        ModelRequest(parts=[ToolReturnPart(tool_name="code__grep", content="A" * 1000, tool_call_id="1")]),
        ModelRequest(parts=[ToolReturnPart(tool_name="code__grep", content="B" * 1000, tool_call_id="2")]),
        ModelRequest(parts=[ToolReturnPart(tool_name="code__grep", content="C" * 1000, tool_call_id="3")]),
    ]
    thinned = thin_history(_FakeCtx(session, _FakeUsage(70_000)), msgs)  # type: ignore[arg-type]
    first_part = thinned[0].parts[0]
    assert isinstance(first_part, ToolReturnPart)
    assert str(first_part.content).startswith("[đã lược")
    # Quá WRAP_UP_SHARE (65%) → gắn lời nhắc trả kết quả ngay
    assert any("NGÂN SÁCH TOKEN" in str(p.content) for p in thinned[-1].parts)


class _IfdefCodeIndex(InMemoryCodeIndex):
    def __init__(self, sources: dict[str, list[str]], compiled: set[int]) -> None:
        super().__init__(sources=sources, symbols=[SymbolInfo("src/tls.c", "DoReply", "function", 1, 6)])
        self._compiled = compiled

    def compiled_lines(self, file: str, flags: tuple[str, ...], *, closed_world: bool = False) -> set[int] | None:
        return self._compiled if file == "src/tls.c" else None


class _DummyExecutor:
    async def run(self, segments: list[list[str]], timeout_s: float) -> str:
        return ""


async def test_code_read_marks_ifdef_disabled_lines_inline() -> None:
    src = [
        "void DoReply(void) {",
        "#ifdef HAVE_MAX_FRAGMENT",
        "    SendAlert(record_overflow);",
        "#endif",
        "    return;",
        "}",
    ]
    index = _IfdefCodeIndex({"src/tls.c": src}, compiled={1, 5, 6})
    tools = {t.name: t for t in build_cc_tools(index, _DummyExecutor(), build_flags=("-DWOLFSSL_TLS13",))}
    read_spec = tools["code.read"]
    session = ToolSession("run-ifdef", "code_reader", "TLS13-0042", 5)
    res = await read_spec.handler(ReadParams(file="src/tls.c", offset=1, limit=10), session)
    assert "3 dòng [DISABLED]" in res.text
    assert "[DISABLED]" in res.text
    assert "SendAlert(record_overflow);" in res.text
    # Dòng 5 được biên dịch nên không có nhãn [DISABLED]
    line5 = next(line for line in res.text.splitlines() if "return;" in line)
    assert "[DISABLED]" not in line5
    # Dòng 3 bị tắt nên có nhãn [DISABLED] ngay sau số dòng 6 ký tự (không lệch cột)
    line3 = next(line for line in res.text.splitlines() if "SendAlert" in line)
    assert line3.startswith("     3 [DISABLED] ")


def test_report_evidence_cited_folds_routine_t3_passes_and_keeps_fail_and_t1() -> None:
    terms = {"record_overflow", "send_alert(record_overflow)", "decode_error"}
    ev = [
        *[as_evidence(t3(variant=f"random:record.length={20000 + i}", outcome=Outcome.PASS)) for i in range(40)],
        as_evidence(t3(variant="boundary:record.length=16641", outcome=Outcome.FAIL, alert="decode_error")),
        as_evidence(t1()),
    ]
    folded = summarize_evidence(ev, terms, max_folded_items=3)
    rows = folded.value
    # 40 ca PASS gộp thành 1 hàng (giữ 3 ID đại diện) + 1 ca FAIL + 1 T1 = 3 hàng
    assert len(rows) == 3
    pass_row = rows[0]
    assert pass_row["count"] == 40
    assert len(pass_row["evidence_ids"]) == 3
    assert len(json.dumps(to_jsonable(rows))) < 2000

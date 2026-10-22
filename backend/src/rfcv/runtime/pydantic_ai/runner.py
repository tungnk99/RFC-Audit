"""Agent runtime: chạy một nhiệm vụ của một vai trò bằng PydanticAI.

PydanticAI chỉ lo vòng LLM ↔ tool và ép đầu ra theo schema. Mọi công cụ agent thấy là
hàm mỏng chuyển lời gọi sang Tool gateway; framework được coi là không đáng tin
(tài liệu PydanticAI: cơ chế duyệt tool "không phải ranh giới phân quyền").
Không dùng tool có sẵn, MCP, web UI hay durable execution của framework.

Đây là gói duy nhất được phép nhập `pydantic_ai*` (hợp đồng import-linter), nên mọi thay đổi API của framework
chỉ ảnh hưởng thư mục này.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Any, cast

from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, RunContext, Tool, UsageLimits, capture_run_messages
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.settings import ModelSettings

from rfcv.core.context_builder import ContextBuilder
from rfcv.core.envelope import Envelope
from rfcv.core.llm_gateway import LLMGateway
from rfcv.core.policy import PolicyStore
from rfcv.core.prompts import role_prompt
from rfcv.core.runner import RoleOutcome
from rfcv.core.skills import SkillRegistry
from rfcv.evidence.repository import TraceSink
from rfcv.gates.tool_gateway import MAX_OUTPUT_RETRIES, ToolDenied, ToolGateway, ToolSession, ToolSpec
from rfcv.plugins import current_registry
from rfcv.runtime.pydantic_ai.skills import skills_capability

LOAD_TOOL = "load_capability"  # tên công cụ nạp skill của harness; chỉ nơi này được biết


def _dump(messages: Sequence[ModelMessage]) -> list[dict[str, Any]]:
    """Hội thoại của framework dạng JSON thuần, để ghi vào trace."""
    return json.loads(ModelMessagesTypeAdapter.dump_json(list(messages)))


def _tokens(messages: Sequence[ModelMessage]) -> int:
    """Token đã tiêu, cộng từ các phản hồi đã nhận (lần chạy lỗi không trả `result.usage`)."""
    return sum(
        (m.usage.input_tokens or 0) + (m.usage.output_tokens or 0) for m in messages if isinstance(m, ModelResponse)
    )


def _tool_args(part: dict[str, Any]) -> dict[str, Any]:
    """Tham số của một lời gọi công cụ trong lịch sử: nhà cung cấp thật trả chuỗi JSON, mô hình giả trả dict."""
    args: Any = part.get("args")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return {}
    return cast("dict[str, Any]", args) if isinstance(args, dict) else {}


def loaded_skills(messages: list[dict[str, Any]]) -> list[str]:
    """Skill mô hình thực sự đã nạp, trích từ lịch sử tin nhắn của framework."""
    return sorted(
        {
            str(_tool_args(part)["id"])
            for msg in messages
            for part in msg.get("parts", [])
            if part.get("part_kind") == "tool-call" and part.get("tool_name") == LOAD_TOOL and "id" in _tool_args(part)
        }
    )


LOW_BUDGET_SHARE = 0.2


def budget_note(session: ToolSession) -> str:
    """Dòng ngân sách gắn sau mỗi kết quả công cụ (chỉ agent thấy, không vào trace): agent biết mình đã tiêu bao nhiêu để tự
    dừng đúng lúc, thay vì chạm giới hạn rồi hỏng mà không trả được gì."""
    used, limit = session.tool_calls, session.max_tool_calls
    if limit <= 0:
        return ""
    left = max(0, limit - used)
    note = f"\n[ngân sách công cụ: đã dùng {used}/{limit}, còn {left}]"
    if left <= max(1, int(limit * LOW_BUDGET_SHARE)):
        note += " Sắp hết: trả kết quả tốt nhất ngay, ghi phần chưa kiểm vào chỗ dành cho nó."
    return note


class PydanticAIRoleRunner:
    def __init__(
        self,
        policy: PolicyStore,
        gateway: ToolGateway,
        llm: LLMGateway,
        trace: TraceSink,
        skills: SkillRegistry | None = None,
    ) -> None:
        self._policy = policy
        self._gateway = gateway
        self._llm = llm
        self._trace = trace
        self._skills = skills
        self._agents: dict[str, Agent[ToolSession, Any]] = {}

    def _wrap(self, spec: ToolSpec) -> Tool[ToolSession]:
        gateway = self._gateway

        async def call(ctx: RunContext[ToolSession], **kwargs: Any) -> str:
            try:
                text = (await gateway.call(ctx.deps, spec.name, kwargs)).text
            except ToolDenied as denied:
                # Mã lỗi liệt kê, không kèm chi tiết chính sách.
                text = f"DENIED: {denied.code.value}"
            return text + budget_note(ctx.deps)

        return Tool[ToolSession].from_schema(
            call,
            name=spec.llm_name,
            description=spec.description,
            json_schema=spec.input_schema(),
            takes_ctx=True,
        )

    def _check_output(self, ctx: RunContext[ToolSession], output: Any) -> Any:
        """Cổng tất định chạy trên đầu ra trước khi nhiệm vụ kết thúc (ví dụ Schema gate với LocationClaim). Không qua
        thì agent được làm lại tối đa MAX_OUTPUT_RETRIES lần trong ngân sách; chỉ mã lỗi liệt kê được trả về agent."""
        session = ctx.deps
        check = session.output_check
        if check is None or not isinstance(output, BaseModel):
            return output
        errors = list(check(output))
        if not errors or session.output_rejections >= MAX_OUTPUT_RETRIES:
            return output  # hết lượt làm lại: handler vẫn kiểm tra và ghi gate_reject
        session.output_rejections += 1
        self._trace.append(
            session.run_id,
            "output_retry",
            {"attempt": session.output_rejections, "errors": errors},
            role=session.role,
            requirement_id=session.requirement_id,
        )
        raise ModelRetry(
            "Cổng kiểm tra từ chối đầu ra: "
            + ", ".join(errors)
            + ". Đọc lại (read_range) đúng các dòng sẽ dẫn, sửa vị trí/đường gọi rồi trả lại."
        )

    def agent(self, role: str, model_key: str | None = None) -> Agent[ToolSession, Any]:
        key = model_key or role
        if key not in self._agents:
            profile = self._policy.profile(role)
            settings = self._llm.settings_for(key)
            agent = Agent(
                self._llm.model_for(key),
                output_type=current_registry().schemas[profile.output_schema],
                system_prompt=role_prompt(self._policy, role),
                deps_type=ToolSession,
                tools=[self._wrap(s) for s in self._gateway.specs_for(role)],
                model_settings=ModelSettings(**settings) if settings else None,  # type: ignore[typeddict-item]
                retries={"tools": 2, "output": MAX_OUTPUT_RETRIES + 1},
                name=key,
                defer_model_check=True,
            )
            agent.output_validator(self._check_output)
            self._agents[key] = agent
        return self._agents[key]

    async def run(
        self, envelope: Envelope, context: dict[str, Any], session: ToolSession, model_key: str | None = None
    ) -> RoleOutcome:
        role = envelope.to_role
        budget = self._policy.profile(role).budget_per_task
        agent = self.agent(role, model_key)
        # Chỉ skill agent khai báo trong role.yaml, lọc tất định theo kiểu nhiệm vụ; mô hình chỉ quyết định nạp skill nào
        # trong số đó.
        task_type = envelope.body.get("task_type")
        task = str(task_type) if task_type else None
        offered = self._skills.select(self._policy.profile(role).skills, task) if self._skills else []
        capability = skills_capability(self._skills, offered) if self._skills else None
        started = time.monotonic()
        # `capture_run_messages` giữ hội thoại kể cả khi lần chạy ném lỗi: đúng lúc hỏng mới cần xem mô hình đã thấy và
        # trả lời gì. Mỗi nhiệm vụ một ngữ cảnh riêng nên chạy song song không lẫn.
        with capture_run_messages() as captured:
            try:
                result = await agent.run(
                    ContextBuilder.render(envelope, context),
                    deps=session,
                    capabilities=[capability] if capability is not None else None,
                    usage_limits=UsageLimits(
                        request_limit=budget.llm_calls,
                        tool_calls_limit=budget.tool_calls,
                        total_tokens_limit=budget.tokens,
                    ),
                )
            except (UsageLimitExceeded, UnexpectedModelBehavior, ModelAPIError) as exc:
                transcript = _dump(captured)
                spent = _tokens(captured)
                self._trace.append(
                    envelope.run_id,
                    "llm_failure",
                    {
                        "msg_id": envelope.msg_id,
                        "model": model_key or role,
                        "error": type(exc).__name__,
                        "detail": str(exc)[:500],
                        "duration_ms": int((time.monotonic() - started) * 1000),
                        "skills_offered": offered,
                        "skills_loaded": loaded_skills(transcript),
                        "tokens": spent,
                        "tool_calls": session.tool_calls,
                        "messages": transcript,
                    },
                    role=role,
                    requirement_id=envelope.requirement_id,
                )
                # Token đã tiêu trước khi hỏng vẫn tính vào ngân sách của yêu cầu.
                return RoleOutcome(None, spent, type(exc).__name__)

        usage = result.usage
        tokens = int((usage.input_tokens or 0) + (usage.output_tokens or 0))
        messages = json.loads(result.all_messages_json())
        self._trace.append(
            envelope.run_id,
            "llm_run",
            {
                "msg_id": envelope.msg_id,
                "model": model_key or role,
                "skills_offered": offered,
                "skills_loaded": loaded_skills(messages),
                "skills_digest": self._skills.digest if self._skills else None,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "requests": usage.requests,
                "messages": messages,
            },
            role=role,
            requirement_id=envelope.requirement_id,
        )
        return RoleOutcome(result.output, tokens)

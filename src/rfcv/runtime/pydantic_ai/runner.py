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
from typing import Any

from pydantic_ai import Agent, RunContext, Tool, UsageLimits
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.settings import ModelSettings

from rfcv.core.context_builder import ContextBuilder
from rfcv.core.envelope import Envelope
from rfcv.core.llm_gateway import LLMGateway
from rfcv.core.policy import PolicyStore
from rfcv.core.prompts import role_prompt
from rfcv.core.runner import RoleOutcome
from rfcv.core.skills import SkillRegistry
from rfcv.evidence.repository import TraceSink
from rfcv.gates.tool_gateway import ToolDenied, ToolGateway, ToolSession, ToolSpec
from rfcv.plugins import current_registry
from rfcv.runtime.pydantic_ai.skills import skills_capability

LOAD_TOOL = "load_capability"  # tên công cụ nạp skill của harness; chỉ nơi này được biết


def loaded_skills(messages: list[dict[str, Any]]) -> list[str]:
    """Skill mô hình thực sự đã nạp, trích từ lịch sử tin nhắn của framework."""
    return sorted(
        {
            str(part["args"].get("id"))
            for msg in messages
            for part in msg.get("parts", [])
            if part.get("part_kind") == "tool-call"
            and part.get("tool_name") == LOAD_TOOL
            and isinstance(part.get("args"), dict)
        }
    )


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
                return (await gateway.call(ctx.deps, spec.name, kwargs)).text
            except ToolDenied as denied:
                # Mã lỗi liệt kê, không kèm chi tiết chính sách.
                return f"DENIED: {denied.code.value}"

        return Tool[ToolSession].from_schema(
            call,
            name=spec.llm_name,
            description=spec.description,
            json_schema=spec.params.model_json_schema(),
            takes_ctx=True,
        )

    def agent(self, role: str, model_key: str | None = None) -> Agent[ToolSession, Any]:
        key = model_key or role
        if key not in self._agents:
            profile = self._policy.profile(role)
            settings = self._llm.settings_for(key)
            self._agents[key] = Agent(
                self._llm.model_for(key),
                output_type=current_registry().schemas[profile.output_schema],
                system_prompt=role_prompt(self._policy, role),
                deps_type=ToolSession,
                tools=[self._wrap(s) for s in self._gateway.specs_for(role)],
                model_settings=ModelSettings(**settings) if settings else None,  # type: ignore[typeddict-item]
                retries=2,
                name=key,
                defer_model_check=True,
            )
        return self._agents[key]

    async def run(
        self, envelope: Envelope, context: dict[str, Any], session: ToolSession, model_key: str | None = None
    ) -> RoleOutcome:
        role = envelope.to_role
        budget = self._policy.profile(role).budget_per_task
        agent = self.agent(role, model_key)
        # Hub chọn skill tất định từ vai trò và kiểu nhiệm vụ; mô hình chỉ quyết định nạp skill nào trong số đó.
        task_type = envelope.body.get("task_type")
        task = str(task_type) if task_type else None
        offered = self._skills.select(role, task) if self._skills else []
        capability = skills_capability(self._skills, role, task) if self._skills else None
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
        except (UsageLimitExceeded, UnexpectedModelBehavior) as exc:
            self._trace.append(
                envelope.run_id,
                "llm_failure",
                {"msg_id": envelope.msg_id, "error": type(exc).__name__, "detail": str(exc)[:500]},
                role=role,
                requirement_id=envelope.requirement_id,
            )
            return RoleOutcome(None, 0, type(exc).__name__)

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
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "requests": usage.requests,
                "messages": messages,
            },
            role=role,
            requirement_id=envelope.requirement_id,
        )
        return RoleOutcome(result.output, tokens)

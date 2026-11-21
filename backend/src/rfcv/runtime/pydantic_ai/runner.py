"""Agent runtime: chạy một nhiệm vụ của một vai trò bằng PydanticAI.

PydanticAI chỉ lo vòng LLM ↔ tool và ép đầu ra theo schema. Mọi công cụ agent thấy là
hàm mỏng chuyển lời gọi sang Tool gateway; framework được coi là không đáng tin
(tài liệu PydanticAI: cơ chế duyệt tool "không phải ranh giới phân quyền").
Không dùng tool có sẵn, MCP, web UI hay durable execution của framework.

Đây là gói duy nhất được phép nhập `pydantic_ai*` (hợp đồng import-linter), nên mọi thay đổi API của framework
chỉ ảnh hưởng thư mục này.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Sequence
from typing import Any, cast

from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic_ai import (
    Agent,
    ModelRetry,
    NativeOutput,
    PromptedOutput,
    RunContext,
    Tool,
    UsageLimits,
    capture_run_messages,
)
from pydantic_ai.capabilities import ProcessHistory
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.settings import ModelSettings

from rfcv.core.context_builder import ContextBuilder
from rfcv.core.envelope import Envelope
from rfcv.core.llm_gateway import LLMGateway, OutputMode
from rfcv.core.policy import PolicyStore
from rfcv.core.prompts import role_prompt
from rfcv.core.runner import RoleOutcome
from rfcv.core.skills import SkillRegistry
from rfcv.evidence.repository import TraceSink
from rfcv.gates.tool_gateway import MAX_OUTPUT_RETRIES, ToolDenied, ToolGateway, ToolSession, ToolSpec
from rfcv.plugins import current_registry
from rfcv.runtime.pydantic_ai.skills import skills_capability

LOAD_TOOL = "load_capability"  # tên công cụ nạp skill của harness; chỉ nơi này được biết
KEEP_TOOL_RESULTS = (
    2  # số kết quả công cụ gần nhất giữ nguyên văn; cũ hơn bị lược (đo: mỗi lượt gửi lại toàn bộ lịch sử)
)
KEEP_TOOLS = frozenset({"code__read", "code__eval"})  # kết quả đọc/tính được giữ lâu hơn kết quả tìm kiếm
READ_KEEP_CHARS = 20_000  # tối đa ~5k token kết quả đọc cũ được giữ nguyên văn (gọn cho mọi cỡ mô hình)
CLEARED_HEAD = 160  # ký tự đầu của kết quả cũ còn lại sau khi lược
CLEAR_ABOVE = 600  # kết quả ngắn hơn mức này không đáng lược
WRAP_UP_SHARE = 0.65  # quá tỉ lệ ngân sách token này thì nhắc agent trả kết quả ngay
HARD_WRAP_SHARE = (
    0.78  # quá tỉ lệ ngân sách token này thì khoá gọi thêm công cụ để ép agent nộp đầu ra trước UsageLimitExceeded
)
HARD_TOOL_WRAP_SHARE = (
    0.78  # quá tỉ lệ số lời gọi công cụ này (vd 23/30) thì khoá gọi thêm, giữ đủ headroom cho M5/R14 và final_result
)
OUTPUT_TOOL_PREFIX = "final_result"  # tên công cụ đầu ra của PydanticAI
_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.S)
_INT_STR = re.compile(r"^[+-]?\d{1,18}$")


REPEAT_NOTE = (
    "\n[LẶP LẠI: bạn đã gọi đúng lệnh này, kết quả y hệt và đã nằm trong lịch sử. Đừng gọi lại. Dùng kết quả đã có và gọi NGAY "
    "công cụ final_result để trả kết quả.]"
)
LIVE_POLL_S = 0.4  # chu kỳ đọc hội thoại đang diễn ra để phát sự kiện agent_step
LIVE_TEXT_CHARS = 4000  # mỗi bước trực tiếp chỉ mang tối đa chừng này ký tự; bản đầy đủ nằm ở llm_run khi lượt kết thúc


def _live_steps(messages: Sequence[ModelMessage], start: int) -> list[dict[str, Any]]:
    """Các bước mới của mô hình từ vị trí `start`: lời nói, suy nghĩ, lời gọi công cụ (trước khi công cụ chạy xong), lần bị cổng bắt làm lại."""
    out: list[dict[str, Any]] = []
    for msg in messages[start:]:
        for part in msg.parts:
            if isinstance(part, ThinkingPart) and part.content:
                out.append({"step": "thinking", "text": part.content[:LIVE_TEXT_CHARS]})
            elif isinstance(part, TextPart) and part.content:
                out.append({"step": "text", "text": part.content[:LIVE_TEXT_CHARS]})
            elif isinstance(part, ToolCallPart):
                try:
                    args: Any = part.args_as_dict()
                except Exception:
                    args = str(part.args)
                out.append({"step": "call", "tool": part.tool_name, "args": args, "call_id": part.tool_call_id})
            elif isinstance(part, RetryPromptPart):
                out.append({"step": "retry", "text": str(part.content)[:LIVE_TEXT_CHARS]})
    return out


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


def thin_history(ctx: RunContext[ToolSession], messages: list[ModelMessage]) -> list[ModelMessage]:
    """Bộ xử lý lịch sử trước mỗi lượt gọi mô hình. Đo trên wolfSSL: lượt thứ 1 vào 11,8k token, lượt thứ 17 vào 28,6k vì
    mỗi lượt gửi lại mọi kết quả công cụ cũ; tổng token tính luỹ thừa nên Code Reader cạn 400k trước khi trả lời.
    1. Lược kết quả công cụ cũ (giữ KEEP_TOOL_RESULTS cái gần nhất và các kết quả đọc/tính mới nhất trong hạn READ_KEEP_CHARS): dòng đã hiển thị vẫn được ghi ở phiên (cổng kiểm tra
       dựa vào đó, không dựa vào ngữ cảnh), agent cần thì đọc lại.
    2. Quá WRAP_UP_SHARE ngân sách token thì thêm lời nhắc trả kết quả tốt nhất ngay."""
    returns = [
        (i, j)
        for i, m in enumerate(messages)
        if isinstance(m, ModelRequest)
        for j, part in enumerate(m.parts)
        if isinstance(part, ToolReturnPart)
    ]
    # Duyệt từ mới tới cũ. Kết quả đọc mã và tính hằng là thứ agent cần giữ trước mắt để lập luận: lược chúng thì nó đọc lại
    # (đo: cùng một đoạn bị đọc 4 lần). Chỉ lược khi tổng phần đọc được giữ vượt READ_KEEP_CHARS; kết quả tìm kiếm cũ lược sớm.
    kept_reads = 0
    for rank, (i, j) in enumerate(reversed(returns)):
        request = cast("ModelRequest", messages[i])
        part = cast("ToolReturnPart", request.parts[j])
        text = part.content if isinstance(part.content, str) else json.dumps(part.content, ensure_ascii=False)
        if rank < KEEP_TOOL_RESULTS or len(text) <= CLEAR_ABOVE or text.startswith("[đã lược"):
            continue
        if part.tool_name in KEEP_TOOLS and kept_reads + len(text) <= READ_KEEP_CHARS:
            kept_reads += len(text)
            continue
        part.content = f"[đã lược {len(text)} ký tự kết quả cũ] " + text[:CLEARED_HEAD]
    limit = ctx.deps.max_tokens
    used = ctx.usage.total_tokens or 0
    limit_tools = ctx.deps.max_tool_calls
    used_tools = max(ctx.deps.tool_calls, int(getattr(ctx.usage, "tool_calls", 0) or 0))
    near_tok = limit > 0 and used >= limit * WRAP_UP_SHARE
    near_tools = limit_tools > 0 and used_tools >= max(1, int(limit_tools * HARD_TOOL_WRAP_SHARE))
    if (near_tok or near_tools) and messages and isinstance(messages[-1], ModelRequest):
        last = messages[-1]
        left = max(0, limit - used)
        left_tools = max(0, limit_tools - used_tools)
        marker = "[NGÂN SÁCH TOKEN"
        if not any(isinstance(p, UserPromptPart) and marker in str(p.content) for p in last.parts):
            last.parts = [
                *last.parts,
                UserPromptPart(
                    f"{marker}: đã dùng {used}/{limit} (còn {left}), công cụ {used_tools}/{limit_tools} (còn {left_tools})] "
                    "Trả kết quả có cấu trúc NGAY BÂY GIỜ bằng các dòng đã đọc; "
                    "ghi phần chưa kiểm vào chỗ dành cho nó. KHÔNG GỌI THÊM CÔNG CỤ."
                ),
            ]
    return messages


def _coerce_output_payload(data: Any) -> Any:
    """Chuẩn hoá nhẹ đầu ra có cấu trúc của mô hình trước khi kiểm chứng (ví dụ `"16486"` → `16486` cho THRESHOLD.observed)."""
    if not isinstance(data, dict):
        return data
    out = dict(cast("dict[str, Any]", data))
    aspects = out.get("aspects")
    if isinstance(aspects, list):
        fixed: list[Any] = []
        for item in cast("list[Any]", aspects):
            if isinstance(item, dict):
                row = dict(cast("dict[str, Any]", item))
                obs = row.get("observed")
                if (
                    str(row.get("aspect", "")).upper() == "THRESHOLD"
                    and isinstance(obs, str)
                    and _INT_STR.match(obs.strip())
                ):
                    row["observed"] = int(obs.strip())
                fixed.append(row)
            else:
                fixed.append(item)
        out["aspects"] = fixed
    return out


def _coerce_model(output: BaseModel) -> BaseModel:
    """Chuẩn hoá nhẹ một BaseModel đã parse (vd THRESHOLD.observed dạng chuỗi số) mà không đổi các trường khác."""
    raw = output.model_dump()
    coerced = _coerce_output_payload(raw)
    if coerced == raw:
        return output
    try:
        return type(output).model_validate(coerced)
    except ValidationError:
        return output


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Trích đối tượng JSON từ chuỗi văn bản hoặc khối markdown ```json ... ``` (dùng cho salvage ở prompted mode)."""
    s = text.strip()
    m = _JSON_FENCE.search(s)
    cand = m.group(1) if m else s
    if not (cand.startswith("{") and cand.endswith("}")):
        return None
    try:
        parsed = json.loads(cand)
    except ValueError:
        return None
    return cast("dict[str, Any]", parsed) if isinstance(parsed, dict) else None


def _output_spec(schema: Any, mode: OutputMode) -> Any:
    if mode == "native":
        return NativeOutput(schema)
    if mode == "prompted":
        return PromptedOutput(schema)
    return schema


def salvage(messages: Sequence[ModelMessage], output_type: Any, *, allow_text_json: bool = False) -> BaseModel | None:
    """Đầu ra gần nhất mà agent đã đề nghị (lời gọi công cụ đầu ra; chỉ đọc JSON trong TextPart khi `allow_text_json=True`
    ở prompted mode để không nhầm bản nháp trong TextPart ở tool/native mode). Chưa được tin: handler vẫn chạy cổng kiểm tra tất định."""
    adapter = TypeAdapter(output_type)
    for m in reversed(messages):
        if not isinstance(m, ModelResponse):
            continue
        for part in reversed(m.parts):
            payload: dict[str, Any] | None = None
            if isinstance(part, ToolCallPart) and part.tool_name.startswith(OUTPUT_TOOL_PREFIX):
                try:
                    payload = part.args_as_dict()
                except ValueError:
                    continue
            elif allow_text_json and isinstance(part, TextPart) and part.content:
                payload = _extract_json_object(part.content)
            if payload is None:
                continue
            try:
                out = adapter.validate_python(_coerce_output_payload(payload))
            except (ValidationError, ValueError):
                continue
            if isinstance(out, BaseModel):
                return out
    return None


class PydanticAIRoleRunner:
    def __init__(
        self,
        policy: PolicyStore,
        gateway: ToolGateway,
        llm: LLMGateway,
        trace: TraceSink,
        skills: SkillRegistry | None = None,
        *,
        static_skills: bool | None = None,
    ) -> None:
        self._policy = policy
        self._gateway = gateway
        self._llm = llm
        self._trace = trace
        self._skills = skills
        self._static_skills = static_skills
        self._agents: dict[tuple[str, str], Agent[ToolSession, Any]] = {}

    def _wrap(self, spec: ToolSpec) -> Tool[ToolSession]:
        gateway = self._gateway

        async def call(ctx: RunContext[ToolSession], **kwargs: Any) -> str:
            # Khi đã chạm ngưỡng dừng cứng theo token hoặc số lời gọi công cụ, khoá đọc thêm công cụ để agent nộp kết quả
            # có cấu trúc trước khi chạm UsageLimitExceeded (tránh mất trắng ngân sách và bỏ lỡ định vị T1).
            limit_tok = ctx.deps.max_tokens
            used_tok = ctx.usage.total_tokens or 0
            limit_tools = ctx.deps.max_tool_calls
            used_tools = max(ctx.deps.tool_calls, int(getattr(ctx.usage, "tool_calls", 0) or 0))
            tok_hit = limit_tok > 0 and used_tok >= limit_tok * HARD_WRAP_SHARE
            tool_hit = limit_tools > 0 and used_tools >= max(1, int(limit_tools * HARD_TOOL_WRAP_SHARE))
            if tok_hit or tool_hit:
                return (
                    f"[NGÂN SÁCH ĐÃ CHẠM NGƯỠNG DỪNG (token {used_tok}/{limit_tok}, công cụ {used_tools}/{limit_tools})] "
                    "KHÔNG GỌI THÊM CÔNG CỤ NỮA. Hãy trả kết quả có cấu trúc NGAY BÂY GIỜ "
                    "dựa trên các dòng mã đã đọc (ghi phần chưa kiểm vào chỗ dành cho nó)."
                )
            # Mô hình nhỏ hay gọi lại y hệt một lệnh cho tới khi hết ngân sách (đo: RFC Analyst gọi rfc.get_definition 9 lần cùng
            # tham số rồi hỏng). Gọi lại đúng lệnh cũ thì trả kết quả đã có, không tốn ngân sách, kèm lời nhắc dừng.
            key = spec.name + json.dumps(kwargs, sort_keys=True, default=str)
            if (prior := ctx.deps.call_cache.get(key)) is not None:
                return prior + REPEAT_NOTE
            try:
                text = (await gateway.call(ctx.deps, spec.name, kwargs)).text
            except ToolDenied as denied:
                # Mã lỗi liệt kê, không kèm chi tiết chính sách.
                text = f"DENIED: {denied.code.value}"
            ctx.deps.call_cache[key] = text
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
        if isinstance(output, BaseModel):
            output = _coerce_model(output)
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
            "Cổng kiểm tra từ chối đầu ra: " + "; ".join(errors) + ". Hãy sửa đúng các lỗi trên rồi trả kết quả lại."
        )

    def agent(self, role: str, model_key: str | None = None) -> Agent[ToolSession, Any]:
        key = model_key or role
        cache_key = (role, key)
        if cache_key not in self._agents:
            profile = self._policy.profile(role)
            settings = self._llm.settings_for(key)
            schema = current_registry().schemas[profile.output_schema]
            out_spec = _output_spec(schema, self._llm.output_mode_for(key))
            agent = Agent(
                self._llm.model_for(key),
                output_type=out_spec,
                system_prompt=role_prompt(self._policy, role),
                deps_type=ToolSession,
                tools=[self._wrap(s) for s in self._gateway.specs_for(role)],
                model_settings=ModelSettings(**settings) if settings else None,  # type: ignore[typeddict-item]
                retries={"tools": 2, "output": MAX_OUTPUT_RETRIES + 1},
                name=key,
                defer_model_check=True,
            )
            agent.output_validator(self._check_output)
            self._agents[cache_key] = agent
        return self._agents[cache_key]

    def _use_static_skills(self, key: str) -> bool:
        if self._static_skills is not None:
            return self._static_skills
        return self._llm.static_skills_for(key)

    async def run(
        self, envelope: Envelope, context: dict[str, Any], session: ToolSession, model_key: str | None = None
    ) -> RoleOutcome:
        role = envelope.to_role
        budget = self._policy.profile(role).budget_per_task
        model_key = model_key or session.model_key
        key = model_key or role
        agent = self.agent(role, model_key)
        if session.max_tokens <= 0:
            session.max_tokens = budget.tokens
        effective_tools = session.max_tool_calls if session.max_tool_calls > 0 else budget.tool_calls
        effective_tokens = session.max_tokens
        # Chỉ skill agent khai báo trong role.yaml, lọc tất định theo kiểu nhiệm vụ.
        task_type = envelope.body.get("task_type")
        task = str(task_type) if task_type else None
        offered = self._skills.select(self._policy.profile(role).skills, task) if self._skills else []
        use_static = self._use_static_skills(key)
        static_instructions = self._skills.render_static(offered) if (self._skills and offered and use_static) else None
        capability = skills_capability(self._skills, offered) if (self._skills and not use_static) else None
        started = time.monotonic()

        # `capture_run_messages` giữ hội thoại kể cả khi lần chạy ném lỗi: đúng lúc hỏng mới cần xem mô hình đã thấy và
        # trả lời gì. Mỗi nhiệm vụ một ngữ cảnh riêng nên chạy song song không lẫn.
        async def stream_steps() -> None:
            """Phát từng bước của mô hình ra trace NGAY khi nó xuất hiện (mô hình thường im lặng cả chục giây giữa hai sự kiện công cụ).
            Chỉ để quan sát: lỗi ở đây không được làm hỏng nhiệm vụ."""
            seen = 0
            try:
                while True:
                    steps = _live_steps(captured, seen)
                    seen = len(captured)
                    for step in steps:
                        self._trace.append(
                            envelope.run_id,
                            "agent_step",
                            {"msg_id": envelope.msg_id, **step},
                            role=role,
                            requirement_id=envelope.requirement_id,
                        )
                    await asyncio.sleep(LIVE_POLL_S)
            except asyncio.CancelledError:
                raise
            except Exception:
                return

        with capture_run_messages() as captured:
            streamer = asyncio.create_task(stream_steps())
            try:
                result: Any = None
                for attempt in range(3):
                    try:
                        result = await agent.run(
                            ContextBuilder.render(envelope, context),
                            deps=session,
                            instructions=static_instructions,
                            capabilities=[
                                ProcessHistory(thin_history),
                                *([capability] if capability is not None else []),
                            ],
                            usage_limits=UsageLimits(
                                request_limit=budget.llm_calls,
                                tool_calls_limit=effective_tools,
                                total_tokens_limit=effective_tokens,
                            ),
                        )
                        break
                    except ModelAPIError as api_exc:
                        # Lỗi mạng/kết nối tạm thời của API (vd ModelConnectionError): thử lại tối đa 2 lần trước khi bỏ cuộc.
                        if attempt < 2 and "Connection" in type(api_exc).__name__:
                            await asyncio.sleep(1.5 * (attempt + 1))
                            continue
                        raise
            except (UsageLimitExceeded, UnexpectedModelBehavior, ModelAPIError) as exc:
                transcript = _dump(captured)
                spent = _tokens(captured)
                self._trace.append(
                    envelope.run_id,
                    "llm_failure",
                    {
                        "msg_id": envelope.msg_id,
                        "model": key,
                        "error": type(exc).__name__,
                        "detail": str(exc)[:500],
                        "duration_ms": int((time.monotonic() - started) * 1000),
                        "skills_offered": offered,
                        "skills_loaded": list(offered) if use_static else loaded_skills(transcript),
                        "skills_mode": "static" if use_static else "dynamic",
                        "tokens": spent,
                        "tool_calls": session.tool_calls,
                        "messages": transcript,
                    },
                    role=role,
                    requirement_id=envelope.requirement_id,
                )
                # Token đã tiêu trước khi hỏng vẫn tính vào ngân sách của yêu cầu.
                partial = salvage(
                    captured,
                    current_registry().schemas[self._policy.profile(role).output_schema],
                    allow_text_json=self._llm.output_mode_for(key) == "prompted",
                )
                if partial is not None:
                    self._trace.append(
                        envelope.run_id,
                        "output_salvaged",
                        {"msg_id": envelope.msg_id, "after": type(exc).__name__},
                        role=role,
                        requirement_id=envelope.requirement_id,
                    )
                return RoleOutcome(partial, spent, type(exc).__name__)
            finally:
                streamer.cancel()

        usage = result.usage
        tokens = int((usage.input_tokens or 0) + (usage.output_tokens or 0))
        messages = json.loads(result.all_messages_json())
        self._trace.append(
            envelope.run_id,
            "llm_run",
            {
                "msg_id": envelope.msg_id,
                "model": key,
                "skills_offered": offered,
                "skills_loaded": list(offered) if use_static else loaded_skills(messages),
                "skills_mode": "static" if use_static else "dynamic",
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

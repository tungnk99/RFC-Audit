"""Tool gateway: điểm kiểm soát duy nhất cho mọi lời gọi công cụ của agent (giao diện I4, rủi ro A3).

Từ chối mặc định. Mỗi lời gọi đi qua: công cụ có đăng ký → vai trò được phép (Policy store)
→ tham số đúng kiểu và miền (pydantic) → handler. Lời gọi bị từ chối được ghi Trace log và trả
mã lỗi liệt kê, không kèm chi tiết chính sách (thiết kế chính, Bảng 13).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, NoReturn

from pydantic import BaseModel, ValidationError

from rfcv.core.ifc import TrustLabel
from rfcv.core.policy import PolicyStore
from rfcv.evidence.repository import TraceSink
from rfcv.plugins import current_registry
from rfcv.spi import ToolDescriptor


class DenyCode(StrEnum):
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    ROLE_NOT_ALLOWED = "ROLE_NOT_ALLOWED"
    BAD_PARAMS = "BAD_PARAMS"
    COMMAND_REJECTED = "COMMAND_REJECTED"
    OUTPUT_TOO_LARGE = "OUTPUT_TOO_LARGE"
    BUDGET = "BUDGET"


class ToolDenied(PermissionError):
    def __init__(self, code: DenyCode, detail: str | None = None) -> None:
        super().__init__(code.value)
        self.code = code
        # Lý do chi tiết (ví dụ FLAG_BLOCKED, PATH_OUT_OF_SCOPE): chỉ ghi Trace log để đo, không trả cho agent.
        self.detail = detail


# Kiểm tra đầu ra của agent trước khi kết thúc nhiệm vụ (ví dụ Schema gate với LocationClaim): trả danh sách mã lỗi
# liệt kê; rỗng là qua. Runtime agent dùng nó để cho agent làm lại trong ngân sách.
OutputCheck = Callable[[BaseModel], Sequence[str]]
MAX_OUTPUT_RETRIES = 2


@dataclass
class ToolSession:
    """Trạng thái của một lần giao nhiệm vụ cho một agent: dùng cho Schema gate và ngân sách."""

    run_id: str
    role: str
    requirement_id: str | None
    max_tool_calls: int
    tool_calls: int = 0
    shown_lines: set[tuple[str, int]] = field(default_factory=set[tuple[str, int]])
    shown_edges: set[tuple[str, str]] = field(default_factory=set[tuple[str, str]])
    output_check: OutputCheck | None = None
    output_rejections: int = 0


@dataclass(frozen=True)
class ToolResult:
    text: str
    label: TrustLabel
    shown_lines: frozenset[tuple[str, int]] = frozenset()
    shown_edges: frozenset[tuple[str, str]] = frozenset()


Handler = Callable[[BaseModel, ToolSession], Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolSpec:
    """Một công cụ, mô tả theo đúng khuôn của MCP (`tools/list`): tên, tiêu đề, mô tả cho mô hình, JSON Schema tham số
    và annotations. Mô hình chỉ thấy phần mô tả này; mọi lời gọi vẫn đi qua ToolGateway."""

    name: str
    description: str
    params: type[BaseModel]
    handler: Handler
    title: str | None = None
    read_only: bool = True

    @property
    def llm_name(self) -> str:
        """Tên gửi cho LLM: API của các nhà cung cấp không cho phép dấu chấm."""
        return self.name.replace(".", "__")

    def input_schema(self) -> dict[str, Any]:
        schema = self.params.model_json_schema()
        schema.pop("title", None)
        return schema

    def mcp_descriptor(self) -> dict[str, Any]:
        """Mô tả công cụ dạng MCP Tool (name, title, description, inputSchema, annotations)."""
        return {
            "name": self.llm_name,
            "title": self.title or self.name,
            "description": self.description,
            "inputSchema": self.input_schema(),
            "annotations": {
                "title": self.title or self.name,
                "readOnlyHint": self.read_only,
                "destructiveHint": False,
                "idempotentHint": self.read_only,
                "openWorldHint": False,
            },
        }


class ToolGateway:
    def __init__(
        self, policy: PolicyStore, trace: TraceSink, catalog: Mapping[str, ToolDescriptor] | None = None
    ) -> None:
        self._policy = policy
        self._trace = trace
        self._catalog = catalog if catalog is not None else current_registry().tools
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        """Chỉ nhận công cụ đã có khai báo trong danh mục (nơi kiểm tác động của công cụ)."""
        if spec.name not in self._catalog:
            raise ValueError(f"công cụ {spec.name} chưa có trong danh mục (registry.tools)")
        if spec.name in self._tools:
            raise ValueError(f"công cụ {spec.name} đã đăng ký")
        self._tools[spec.name] = spec

    def specs_for(self, role: str) -> list[ToolSpec]:
        return [s for name, s in sorted(self._tools.items()) if self._policy.allows(role, name)]

    def tools_list(self, role: str) -> dict[str, Any]:
        """Danh mục công cụ của một vai trò đúng khuôn kết quả `tools/list` của MCP (để xem, kiểm thử, hoặc phục vụ
        qua một máy chủ MCP đặt sau gateway)."""
        return {"tools": [s.mcp_descriptor() for s in self.specs_for(role)]}

    async def call(self, session: ToolSession, tool: str, raw_args: dict[str, object]) -> ToolResult:
        spec = self._tools.get(tool)
        if spec is None:
            self._deny(session, tool, DenyCode.UNKNOWN_TOOL)
        if not self._policy.allows(session.role, tool):
            self._deny(session, tool, DenyCode.ROLE_NOT_ALLOWED)
        if session.tool_calls >= session.max_tool_calls:
            self._deny(session, tool, DenyCode.BUDGET)
        try:
            params = spec.params.model_validate(raw_args)
        except ValidationError:
            self._deny(session, tool, DenyCode.BAD_PARAMS)
        session.tool_calls += 1
        try:
            result = await spec.handler(params, session)
        except ToolDenied as denied:
            self._deny(session, tool, denied.code, denied.detail, params.model_dump(mode="json"))
        session.shown_lines |= result.shown_lines
        session.shown_edges |= result.shown_edges
        self._trace.append(
            session.run_id,
            "tool_call",
            {"tool": tool, "args": params.model_dump(mode="json"), "output": result.text, "label": result.label.name},
            role=session.role,
            requirement_id=session.requirement_id,
        )
        return result

    def _deny(
        self,
        session: ToolSession,
        tool: str,
        code: DenyCode,
        detail: str | None = None,
        args: dict[str, Any] | None = None,
    ) -> NoReturn:
        payload: dict[str, Any] = {"tool": tool, "code": code.value}
        if detail is not None:
            payload["reason"] = detail
        if args is not None:
            payload["args"] = args
        self._trace.append(
            session.run_id,
            "tool_denied",
            payload,
            role=session.role,
            requirement_id=session.requirement_id,
        )
        raise ToolDenied(code)

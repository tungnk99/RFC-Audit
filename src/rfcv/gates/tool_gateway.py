"""Tool gateway: điểm kiểm soát duy nhất cho mọi lời gọi công cụ của agent (giao diện I4, rủi ro A3).

Từ chối mặc định. Mỗi lời gọi đi qua: công cụ có đăng ký → vai trò được phép (Policy store)
→ tham số đúng kiểu và miền (pydantic) → handler. Lời gọi bị từ chối được ghi Trace log và trả
mã lỗi liệt kê, không kèm chi tiết chính sách (thiết kế chính, Bảng 13).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import NoReturn

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
    def __init__(self, code: DenyCode) -> None:
        super().__init__(code.value)
        self.code = code


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


@dataclass(frozen=True)
class ToolResult:
    text: str
    label: TrustLabel
    shown_lines: frozenset[tuple[str, int]] = frozenset()
    shown_edges: frozenset[tuple[str, str]] = frozenset()


Handler = Callable[[BaseModel, ToolSession], Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    params: type[BaseModel]
    handler: Handler

    @property
    def llm_name(self) -> str:
        """Tên gửi cho LLM: API của các nhà cung cấp không cho phép dấu chấm."""
        return self.name.replace(".", "__")


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
            self._deny(session, tool, denied.code)
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

    def _deny(self, session: ToolSession, tool: str, code: DenyCode) -> NoReturn:
        self._trace.append(
            session.run_id,
            "tool_denied",
            {"tool": tool, "code": code.value},
            role=session.role,
            requirement_id=session.requirement_id,
        )
        raise ToolDenied(code)

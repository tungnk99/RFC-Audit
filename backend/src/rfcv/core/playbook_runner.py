"""Planner cố định: trả lời vai Planner bằng sổ tay điều tra, các vai khác uỷ quyền cho runner bên trong.

Đây là cấu hình "Planner cố định" của kế hoạch đánh giá: cùng vòng điều tra, cùng cổng, cùng Verdict engine, chỉ thay Planner
LLM bằng kinh nghiệm dạng dữ liệu. Có hai công dụng: đường cơ sở để đo Planner LLM đi chệch sổ tay bao nhiêu, và phương án
dự phòng tất định (bật tường minh ở nơi dựng runner; mặc định không bao giờ tự bật).
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from rfcv.agents.schemas import PlanAction
from rfcv.core.advisor import advise, situation_from_context
from rfcv.core.envelope import Envelope
from rfcv.core.runner import RoleOutcome, RoleRunner
from rfcv.gates.tool_gateway import ToolSession
from rfcv.plugins import Registry, current_registry


class PlaybookRunner:
    def __init__(
        self,
        inner: RoleRunner | None,
        *,
        handled: Collection[str],
        stop_rationale: str,
        planner_role: str = "planner",
        registry: Registry | None = None,
    ) -> None:
        self._inner = inner
        self._handled = frozenset(handled)
        self._stop_rationale = stop_rationale
        self._planner_role = planner_role
        self._registry = registry

    @property
    def registry(self) -> Registry:
        return self._registry or current_registry()

    def plan(self, context: dict[str, Any]) -> PlanAction:
        reg = self.registry
        advice = advise(situation_from_context(context), reg.playbook, reg.tasks, self._handled)
        model: type[PlanAction] = reg.schemas["PlanAction@1"]  # type: ignore[assignment]
        if advice is None or advice.stop:
            rationale = advice.rationale_code if advice is not None else self._stop_rationale
            return model.model_validate({"action": "stop", "tasks": [], "rationale_code": rationale})
        return model.model_validate(
            {
                "action": "dispatch",
                "tasks": [t.model_dump(mode="json") for t in advice.tasks],
                "rationale_code": advice.rationale_code,
            }
        )

    async def run(self, envelope: Envelope, context: dict[str, Any], session: ToolSession) -> RoleOutcome:
        if envelope.to_role == self._planner_role:
            return RoleOutcome(self.plan(context), 0)
        if self._inner is None:
            return RoleOutcome(None, 0, "NO_RUNNER")
        return await self._inner.run(envelope, context, session)

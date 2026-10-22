"""Handler của Code Indexer: ComponentMap → đối chiếu chỉ mục và danh mục thành phần → bản đồ thành phần của Locator.

Bản đồ thành phần chỉ dùng để xếp hạng gợi ý (comp(f) trong công thức Locator), không phải bằng chứng, nên không ghi
Evidence store. Mục nào ký hiệu không có trong chỉ mục hoặc thành phần ngoài danh mục của adapter bị loại.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from agents.code_indexer.schema import ComponentMap
from agents.locator.service import Locator
from rfcv.core.execution_loop import Investigation
from rfcv.gates.tool_gateway import ToolSession


class ComponentMapHandler:
    """MAP_COMPONENTS."""

    def __init__(self, rt: Any, locator: Callable[[], Locator | None]) -> None:
        self._rt = rt
        self._locator = locator

    async def handle(
        self, inv: Investigation, task: Any, output: BaseModel | None, session: ToolSession, msg_id: str
    ) -> int:
        locator = self._locator()
        if not isinstance(output, ComponentMap) or locator is None:
            return 0
        index = self._rt.providers.code_index
        accepted = 0
        rejected: dict[str, int] = {}
        for e in output.entries:
            if locator.taxonomy and e.component not in locator.taxonomy:
                rejected["COMPONENT_NOT_IN_TAXONOMY"] = rejected.get("COMPONENT_NOT_IN_TAXONOMY", 0) + 1
            elif index.symbol_in_file(e.file, e.symbol) is None:
                rejected["SYMBOL_NOT_IN_INDEX"] = rejected.get("SYMBOL_NOT_IN_INDEX", 0) + 1
            else:
                locator.set_component(e.file, e.symbol, e.component)
                accepted += 1
        self._rt.trace.append(
            self._rt.run_id,
            "component_map",
            {"msg_id": msg_id, "accepted": accepted, "rejected": rejected},
            role=session.role,
            requirement_id=inv.requirement.requirement_id,
        )
        return 0

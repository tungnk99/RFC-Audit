"""Schema đầu ra tổng quát của agent (giao diện I3): kế hoạch, phản biện, giải thích.

Đây là dữ liệu khai báo, không có mã thực thi. Schema đặc thù miền (đặc tả, kịch bản, vị trí mã…) nằm trong
domain pack. Registry đóng băng sẽ dựng `PlanAction@1` chặt từ các kiểu nhiệm vụ đã đăng ký, nên Planner chỉ
có thể giao nhiệm vụ có thật, đúng đích, đúng kiểu tham số (tài liệu phối hợp agent, mục 5).
Trường văn bản tự do mang nhãn UNTRUSTED hoặc không bao giờ tới agent đặc quyền.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny, create_model, model_validator

from rfcv.plugins import current_registry
from rfcv.spi import TaskDefinition

_create: Any = create_model  # kiểu động: pydantic không mô tả được chữ ký create_model theo từng lời gọi


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoParams(_Out):
    """Tham số rỗng, cho nhiệm vụ không có tham số."""


class TaskSpec(_Out):
    task_type: str
    target_role: str
    params: SerializeAsAny[BaseModel] = Field(default_factory=NoParams)

    @model_validator(mode="before")
    @classmethod
    def _resolve_params(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        fields: dict[str, Any] = dict(cast(dict[str, Any], data))
        if isinstance(fields.get("params"), dict):
            definition = current_registry().tasks.get(str(fields.get("task_type")))
            if definition is not None:
                fields["params"] = definition.params_model.model_validate(fields["params"])
        return fields


class PlanAction(_Out):
    action: Literal["dispatch", "stop"]
    tasks: Annotated[list[TaskSpec], Field(max_length=2)] = Field(default_factory=list[TaskSpec])
    rationale_code: str


class CritiqueIssue(_Out):
    kind: str
    evidence_id: str | None = None
    suggested_task: str


class Critique(_Out):
    issues: list[CritiqueIssue] = Field(default_factory=list[CritiqueIssue])


class Explanation(_Out):
    requirement_id: str
    text: str
    cited_evidence_ids: list[str] = Field(default_factory=list[str])


CORE_SCHEMAS: dict[str, type[BaseModel]] = {
    "PlanAction@1": PlanAction,
    "Critique@1": Critique,
    "Explanation@1": Explanation,
}


def _union(types: Sequence[Any]) -> Any:
    """Hợp các lớp bằng `|` (không dùng typing.Union để ruff không đổi nghĩa)."""
    out: Any = types[0]
    for t in types[1:]:
        out = out | t
    return out


def build_plan_action_model(tasks: Mapping[str, TaskDefinition], rationale_codes: Sequence[str]) -> type[PlanAction]:
    """Dựng schema chặt cho Planner từ các kiểu nhiệm vụ đã đăng ký.

    Mỗi nhiệm vụ là một biến thể phân biệt theo `task_type`, kèm đích cố định và mô hình tham số riêng;
    `rationale_code` là tập hữu hạn. Kết quả vẫn là lớp con của PlanAction nên hub xử lý như nhau.
    """
    if not tasks:
        return PlanAction
    variants: list[Any] = []
    for name, definition in sorted(tasks.items()):
        variants.append(
            _create(
                f"Task_{name}",
                __base__=TaskSpec,
                task_type=(Literal[name], name),
                target_role=(Literal[definition.target_role], definition.target_role),
                params=(definition.params_model, Field(default_factory=definition.params_model)),
            )
        )
    # Phân biệt các biến thể theo task_type.
    task_union: Any = (
        variants[0] if len(variants) == 1 else Annotated[_union(variants), Field(discriminator="task_type")]
    )
    task_list: Any = Annotated[list[task_union], Field(max_length=2)]
    fields: dict[str, Any] = {"tasks": (task_list, Field(default_factory=list))}
    if rationale_codes:
        fields["rationale_code"] = (Literal[tuple(rationale_codes)], ...)
    return cast(type[PlanAction], _create("PlanAction", __base__=PlanAction, **fields))

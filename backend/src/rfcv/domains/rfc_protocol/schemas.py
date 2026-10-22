"""Mặt tiền schema của miền RFC giao thức (thiết kế chính, Bảng 23; tài liệu phối hợp agent, Bảng 4).

Định nghĩa thật nằm trong thư mục từng agent (`agents/<tên>/schema.py`) và `agents/common.py`; module này chỉ gom lại để mã
dùng chung và test giữ nguyên đường nhập `rfcv.domains.rfc_protocol.schemas`. Danh mục nhiệm vụ và schema đăng ký được suy ra
từ khai báo của từng agent, nên thêm agent là thêm một thư mục, không sửa ở đây.
"""

from __future__ import annotations

from pydantic import BaseModel

from agents.code_indexer.schema import ComponentEntry, ComponentMap
from agents.code_reader.schema import AspectClaim, CheckKind, LocationClaim
from agents.common import (
    NoTaskParams,
    Out,
    RationaleCode,
    TargetRole,
    TaskParams,
    TaskType,
)
from agents.locator.schema import QueryProposal
from agents.registry import AGENTS
from agents.rfc_analyst.schema import RbsProposal
from agents.tester.schema import ScenarioProposal, ScenarioStep
from agents.verifier.schema import CritiqueKind
from rfcv.spi import TaskDefinition

# Suy ra từ khai báo của từng agent.
TASKS: tuple[TaskDefinition, ...] = tuple(t for agent in AGENTS for t in agent.tasks)
DOMAIN_SCHEMAS: dict[str, type[BaseModel]] = {name: model for agent in AGENTS for name, model in agent.schemas.items()}

__all__ = [
    "DOMAIN_SCHEMAS",
    "TASKS",
    "AspectClaim",
    "CheckKind",
    "ComponentEntry",
    "ComponentMap",
    "CritiqueKind",
    "LocationClaim",
    "NoTaskParams",
    "Out",
    "QueryProposal",
    "RationaleCode",
    "RbsProposal",
    "ScenarioProposal",
    "ScenarioStep",
    "TargetRole",
    "TaskParams",
    "TaskType",
]

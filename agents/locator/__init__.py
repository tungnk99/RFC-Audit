"""Locator: thành phần TẤT ĐỊNH (không LLM, không có role.yaml) chạy truy vấn tĩnh từ mẫu do adapter cung cấp.

CHƯA NỐI: nhiệm vụ STATIC_QUERY có trong danh mục nhưng chưa có handler (cần CodeQL/Semgrep và kiểm định đột biến truy vấn).
"""

from agents.common import TargetRole, TaskParams, TaskType
from agents.locator.schema import QueryProposal
from rfcv.spi import AgentSpec, TaskDefinition

SPEC = AgentSpec(
    "locator",
    stage="deterministic",
    wired=False,
    tasks=(TaskDefinition(TaskType.STATIC_QUERY.value, TargetRole.LOCATOR.value, TaskParams, deterministic=True),),
    schemas={"QueryProposal@1": QueryProposal},
    summary="Chưa nối. Cần: handler STATIC_QUERY và bộ chạy truy vấn tĩnh.",
)

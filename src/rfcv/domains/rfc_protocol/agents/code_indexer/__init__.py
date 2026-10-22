"""Code Indexer (cách ly): lập bản đồ ký hiệu → thành phần của kho mã.

CHƯA NỐI: nhiệm vụ MAP_COMPONENTS có trong danh mục nhưng chưa có handler, nên mọi lần giao đều bị hub từ chối.
"""

from rfcv.domains.rfc_protocol.agents.code_indexer.schema import ComponentMap
from rfcv.domains.rfc_protocol.agents.common import TargetRole, TaskParams, TaskType
from rfcv.spi import AgentSpec, TaskDefinition

SPEC = AgentSpec(
    "code_indexer",
    zone="quarantine",
    output_schema="ComponentMap@1",
    stage="investigation",
    wired=False,
    tasks=(TaskDefinition(TaskType.MAP_COMPONENTS.value, TargetRole.CODE_INDEXER.value, TaskParams),),
    schemas={"ComponentMap@1": ComponentMap},
    summary="Chưa nối. Cần: handler MAP_COMPONENTS (ComponentMap → cổng đối chiếu chỉ mục → bản đồ thành phần).",
)

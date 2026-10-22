"""Code Indexer (cách ly): lập bản đồ ký hiệu → thành phần của kho mã.

Handler MAP_COMPONENTS đối chiếu từng mục với chỉ mục mã và danh mục thành phần của adapter rồi nạp vào Locator
(comp(f) trong công thức xếp hạng). Không ghi bằng chứng.
"""

from agents.code_indexer.schema import ComponentMap
from agents.common import TargetRole, TaskParams, TaskType
from rfcv.spi import AgentSpec, TaskDefinition

SPEC = AgentSpec(
    "code_indexer",
    zone="quarantine",
    output_schema="ComponentMap@1",
    stage="investigation",
    wired=True,
    tasks=(TaskDefinition(TaskType.MAP_COMPONENTS.value, TargetRole.CODE_INDEXER.value, TaskParams),),
    schemas={"ComponentMap@1": ComponentMap},
    summary="MAP_COMPONENTS: ComponentMap → đối chiếu chỉ mục và danh mục thành phần → Locator.",
)

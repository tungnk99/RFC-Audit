"""Code Reader (cách ly): đọc mã không tin cậy, trả vị trí có cấu trúc; Schema gate đối chiếu chỉ mục rồi mới ghi T1."""

from rfcv.domains.rfc_protocol.agents.code_reader.schema import LocationClaim
from rfcv.domains.rfc_protocol.agents.common import TargetRole, TaskParams, TaskType
from rfcv.spi import AgentSpec, TaskDefinition

SPEC = AgentSpec(
    "code_reader",
    zone="quarantine",
    output_schema="LocationClaim@1",
    stage="investigation",
    wired=True,
    tasks=tuple(
        TaskDefinition(t.value, TargetRole.CODE_READER.value, TaskParams)
        for t in (TaskType.LOCATE, TaskType.TRACE_PATHS, TaskType.RECHECK)
    ),
    schemas={"LocationClaim@1": LocationClaim},
    summary="LocationClaim → Schema gate (tệp, dòng, ký hiệu, đường gọi có thật) → T1 → liên kết độ phủ.",
)

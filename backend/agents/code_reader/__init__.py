"""Code Reader (cách ly): đọc mã không tin cậy, trả vị trí có cấu trúc; Schema gate đối chiếu chỉ mục rồi mới ghi T1."""

from agents.code_reader.schema import LocationClaim
from agents.common import TargetRole, TaskParams, TaskType
from rfcv.spi import AgentSpec, TaskDefinition

SPEC = AgentSpec(
    "code_reader",
    zone="quarantine",
    output_schema="LocationClaim@1",
    stage="investigation",
    wired=True,
    tasks=(
        # Lần LOCATE và TRACE_PATHS sau nhận tóm tắt vị trí đã tìm được ("location"), để làm tiếp thay vì tìm lại từ đầu.
        TaskDefinition(TaskType.LOCATE.value, TargetRole.CODE_READER.value, TaskParams, prior_kinds=("location",)),
        TaskDefinition(TaskType.TRACE_PATHS.value, TargetRole.CODE_READER.value, TaskParams, prior_kinds=("location",)),
        TaskDefinition(TaskType.RECHECK.value, TargetRole.CODE_READER.value, TaskParams),
    ),
    schemas={"LocationClaim@1": LocationClaim},
    summary="LocationClaim → Schema gate (tệp, dòng, ký hiệu, đường gọi có thật) → T1 → liên kết độ phủ.",
)

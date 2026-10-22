"""Verifier (đặc quyền): phản biện độc lập trên bằng chứng có cấu trúc; không đọc mã, không kết luận nhãn."""

from agents.common import NoTaskParams, TargetRole, TaskType
from rfcv.spi import AgentSpec, TaskDefinition

SPEC = AgentSpec(
    "verifier",
    zone="privileged",
    output_schema="Critique@1",
    stage="investigation",
    wired=True,
    tasks=(TaskDefinition(TaskType.CRITIQUE.value, TargetRole.VERIFIER.value, NoTaskParams),),
    summary="Critique@1 → hub đọc trực tiếp; nhãn COMPLIANT phải qua một lần phản biện sạch trước khi dừng.",
)

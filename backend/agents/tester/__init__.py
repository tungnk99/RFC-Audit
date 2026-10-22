"""Test (đặc quyền): tổng hợp kịch bản trong DSL giới hạn; Test driver chạy nó và ghi T3."""

from agents.common import TargetRole, TaskParams, TaskType
from agents.tester.schema import ScenarioProposal
from rfcv.spi import AgentSpec, TaskDefinition

SPEC = AgentSpec(
    "tester",
    zone="privileged",
    output_schema="ScenarioProposal@1",
    stage="investigation",
    wired=True,
    tasks=(TaskDefinition(TaskType.SELECT_TESTS.value, TargetRole.TESTER.value, TaskParams),),
    schemas={"ScenarioProposal@1": ScenarioProposal},
    summary="Kịch bản → Tool gateway → Test driver (nhân chứng, chạy lại) → T3.",
)

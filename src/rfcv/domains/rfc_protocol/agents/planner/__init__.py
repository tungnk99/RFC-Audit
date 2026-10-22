"""Planner (đặc quyền): quyết định giao việc gì cho ai ở vòng tiếp theo; không gán nhãn. Hub gọi trực tiếp, không qua nhiệm vụ."""

from rfcv.spi import AgentSpec

SPEC = AgentSpec(
    "planner",
    zone="privileged",
    output_schema="PlanAction@1",
    stage="planning",
    wired=True,
    summary="Đọc báo cáo độ đủ và phản biện, chọn tối đa hai nhiệm vụ hoặc dừng. Sổ tay kinh nghiệm ở playbook.py.",
)

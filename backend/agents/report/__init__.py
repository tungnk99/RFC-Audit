"""Report (đặc quyền): viết giải thích cho nhãn đã có; Output gate kiểm mọi tham chiếu bằng chứng trước khi xuất.

Chạy sau `ExecutionLoop.investigate` (`ExecutionLoop.explain`): nhãn đã chốt, Report không thấy và không đổi nó. Giải thích không
qua Output gate (`rfcv.gates.output_gate`) bị bỏ chứ không làm đổi kết luận. Hồ sơ `report` được nạp chung với các agent khác.
"""

from rfcv.spi import AgentSpec

SPEC = AgentSpec(
    "report",
    zone="privileged",
    output_schema="Explanation@1",
    stage="post",
    wired=True,
    summary="Giải thích nhãn đã có → Output gate (bằng chứng có thật, đúng nhãn, đủ các tầng) → trace; HTML/JSON/SARIF do lệnh report.",
)

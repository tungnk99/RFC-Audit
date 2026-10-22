"""Report (đặc quyền): viết giải thích cho nhãn đã có; Output gate kiểm mọi tham chiếu bằng chứng trước khi xuất.

CHƯA NỐI: có hồ sơ, lời nhắc và `Explanation@1` (schema lõi), nhưng chưa có Output gate và chưa ai gọi sau khi có nhãn.
"""

from rfcv.spi import AgentSpec

SPEC = AgentSpec(
    "report",
    zone="privileged",
    output_schema="Explanation@1",
    stage="post",
    wired=False,
    summary="Chưa nối. Cần: Output gate, bước gọi sau kết luận, xuất HTML/JSON/SARIF.",
)

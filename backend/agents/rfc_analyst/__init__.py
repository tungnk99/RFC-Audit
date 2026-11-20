"""RFC Analyst (đặc quyền): dịch câu RFC thành RBS (hai luồng độc lập, đối chiếu bằng spec/reconcile.py).

Nối MỘT PHẦN: bước phân tích đặc tả (`RuntimeConfig.spec_analysis`) cho nó dịch lại câu RFC của từng yêu cầu, MÙ với bản người viết,
rồi cổng tất định kiểm và đối chiếu với RBS đã duyệt (`handler.py`). Chỉ để quan sát: kết luận vẫn dùng RBS đã duyệt, chưa dùng RBS của agent (BL-99).
"""

from agents.rfc_analyst.schema import RbsProposal
from rfcv.spi import AgentSpec

SPEC = AgentSpec(
    "rfc_analyst",
    zone="privileged",
    output_schema="RbsProposal@1",
    stage="pre",
    wired=True,
    schemas={"RbsProposal@1": RbsProposal},
    summary="RFC → RBS: dịch câu RFC (mù với bản viết tay), cổng parse/oracle/câu RFC, đối chiếu với RBS đã duyệt. Còn thiếu: hai luồng khác họ, lệnh `rfcv specs`.",
)

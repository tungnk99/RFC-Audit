"""RFC Analyst (đặc quyền): dịch câu RFC thành RBS (hai luồng độc lập, đối chiếu bằng spec/reconcile.py).

CHƯA NỐI: có hồ sơ, lời nhắc và schema, nhưng chưa có bước nào gọi nó; `runtime.py` đang đọc thẳng các tệp `*.rbs` đã duyệt.
"""

from rfcv.domains.rfc_protocol.agents.rfc_analyst.schema import RbsProposal
from rfcv.spi import AgentSpec

SPEC = AgentSpec(
    "rfc_analyst",
    zone="privileged",
    output_schema="RbsProposal@1",
    stage="pre",
    wired=False,
    schemas={"RbsProposal@1": RbsProposal},
    summary="Chưa nối. Cần: luồng hai bản dịch, reconcile, bộ vàng RBS, lệnh `rfcv specs`.",
)

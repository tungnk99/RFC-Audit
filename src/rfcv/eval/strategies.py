"""Chiến lược kiểm thử so sánh trong bộ mô phỏng. Mỗi chiến lược là một cấu hình (RBS + cờ của Test driver), không phải mã riêng.

Siêu tham số chỉ được chỉnh trên họ lỗi `train`; sau đó đóng băng vào cấu hình có hash (`config_hash`) rồi mới chấm trên `test`.
"""

from __future__ import annotations

from dataclasses import dataclass

from rfcv.common.hashing import content_hash

RBS_TEMPLATE = """requirement SIM-0001 from RFC8446§5.2#p4s3 modal MUST type B
actor server
state connected
trigger receive(record) where record.length > 16640
expect send_alert(record_overflow) then close within 2000ms
accept_alternatives send_alert(decode_error)
variants {variants}
"""


@dataclass(frozen=True)
class Strategy:
    name: str
    description: str
    variants: str  # phần sau "variants" trong RBS
    rerun_pass: bool = False  # chạy lại PASS ở môi trường khác
    use_mutants: bool = False  # chạy cổng đột biến
    probe_budget: int = 0  # >0: dò ngưỡng với ngân sách này

    def rbs(self) -> str:
        return RBS_TEMPLATE.format(variants=self.variants)


S0 = Strategy(
    "S0",
    "hiện tại: control, biên +1, max, ngẫu nhiên đều ở phía vi phạm",
    "boundary(record.length, 16641), max(record.length), random(record.length, k=3)",
)

S1 = Strategy(
    "S1",
    "S0 + lấy mẫu phân tầng phía vi phạm (có giá trị đặc biệt, loại giá trị kiểm thử chuẩn) + lấy mẫu phía hợp lệ",
    "boundary(record.length, 16641), max(record.length), random(record.length, k=8, stratified), "
    "valid_random(record.length, k=8)",
)

STRATEGIES: tuple[Strategy, ...] = (S0, S1)


def config_hash(strategies: tuple[Strategy, ...] = STRATEGIES) -> str:
    """Hash cấu hình đã đóng băng; ghi vào báo cáo để biết kết quả ứng với cấu hình nào."""
    return content_hash([s.__dict__ for s in strategies])

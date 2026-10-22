"""Backend DNS: dnspython dựng và gửi thông điệp; ca có sẵn lấy từ ISC genreport (EDNS, cờ).

Không có bắt tay: `connect` chỉ chọn giao vận (UDP hay TCP). `send_msg(type=query)` dựng một truy vấn hợp lệ (có OPT RR
EDNS(0) trừ khi mutate bỏ đi); `mutate` sửa thông điệp kế tiếp, ví dụ `duplicate` OPT RR hay `set` trường `opt.version`.
Quan sát Observation@1: `alert` là RCODE đầy đủ (gồm phần mở rộng trong OPT, ví dụ badvers), `closed` là TCP bị đóng.
"""

from __future__ import annotations

from rfcv.backends.base import BODIES, EXPECT_ARGS, MUTATIONS, DslBackend
from rfcv.domains.rfc_protocol.sandbox.dsl import DslSpec

DSL = DslSpec(
    ops={
        "connect": frozenset({"transport"}),
        "send_msg": frozenset({"type", "qname", "qtype"}),
        "send_raw_record": frozenset({"length", "body", "transport"}),
        "mutate": frozenset({"field", "op", "value"}),
        "repeat": frozenset({"msg"}),
        "expect": EXPECT_ARGS,
    },
    values={
        "transport": frozenset({"udp", "tcp"}),
        "type": frozenset({"query", "notify"}),
        "body": BODIES,
        "op": MUTATIONS,
    },
    notes={
        "connect": "chọn giao vận; DNS không có bắt tay, trạng thái sau bước này là ready",
        "send_msg": "dựng thông điệp hợp lệ (truy vấn có OPT RR EDNS(0)); trường cần đổi thì dùng mutate ngay trước",
        "mutate": "sửa thông điệp kế tiếp: field như opt.version, opt.count, header.opcode, header.flags.rd",
        "send_raw_record": "gửi nguyên một thông điệp DNS thô với độ dài cho trước",
    },
)


class DnspythonBackend(DslBackend):
    name = "dnspython"
    dsl = DSL
    runner = "dnspython"

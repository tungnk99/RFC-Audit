"""Backend SSH: mẫu DSL tự viết, dịch sang asyncssh (chưa có bộ kiểm thử tuân thủ SSH phù hợp để bọc).

`connect` mở TCP và trao đổi chuỗi định danh (trạng thái `version_exchanged`). `complete_handshake(until)` đi tiếp tới
`kex` (trao đổi khoá xong, trạng thái `authenticating`) hoặc `userauth` (đã xác thực, trạng thái `authenticated`).
`send_raw_record` gửi một gói nhị phân với số thông điệp `msg_number` cho trước. Observation@1: `alert` là mã lý do của
SSH_MSG_DISCONNECT (none nếu đóng không kèm thông điệp), `closed` là kết nối TCP bị đóng.
"""

from __future__ import annotations

from rfcv.backends.base import BODIES, EXPECT_ARGS, MUTATIONS, DslBackend
from rfcv.domains.rfc_protocol.sandbox.dsl import DslSpec

DSL = DslSpec(
    ops={
        "connect": frozenset({"ident"}),
        "complete_handshake": frozenset({"until"}),
        "send_msg": frozenset({"type"}),
        "send_raw_record": frozenset({"msg_number", "length", "padding_length", "body", "encrypted"}),
        "mutate": frozenset({"field", "op", "value"}),
        "reorder": frozenset({"msgs"}),
        "repeat": frozenset({"msg"}),
        "expect": EXPECT_ARGS,
    },
    values={
        "until": frozenset({"kex", "userauth"}),
        "type": frozenset({"kexinit", "service_request", "userauth_request", "channel_open", "ignore", "debug"}),
        "body": BODIES,
        "op": MUTATIONS,
    },
    notes={
        "connect": "TCP và trao đổi chuỗi định danh; trạng thái sau bước này là version_exchanged",
        "complete_handshake": "until=kex: trao đổi khoá xong (authenticating); until=userauth: đã xác thực (authenticated)",
        "send_raw_record": "một gói nhị phân SSH với số thông điệp msg_number; encrypted=true sau khi trao đổi khoá xong",
        "mutate": "sửa thông điệp kế tiếp, ví dụ field kexinit.common_kex_count (số thuật toán kex chung với SUT)",
    },
)


class AsyncsshBackend(DslBackend):
    name = "asyncssh"
    dsl = DSL
    runner = "asyncssh"

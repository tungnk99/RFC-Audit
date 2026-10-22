"""Backend HTTP/2: ca có sẵn của h2spec (đánh số theo mục RFC 9113), mẫu DSL dịch sang hyperframe/h2.

`complete_handshake` gửi lời mở đầu kết nối (connection preface) và SETTINGS, chờ SETTINGS của SUT và trao đổi ACK; sau
bước này trạng thái là `connected`. `send_raw_record` là một khung HTTP/2 thô: tiêu đề 9 byte với `length` cho trước,
có thể khác độ dài thân thật. Observation@1: `alert` là mã lỗi trong GOAWAY hoặc RST_STREAM, `closed` là kết nối bị đóng.
"""

from __future__ import annotations

from rfcv.backends.base import BODIES, EXPECT_ARGS, MUTATIONS, DslBackend
from rfcv.domains.rfc_protocol.sandbox.dsl import DslSpec

FRAME_TYPES = frozenset(
    {
        "data",
        "headers",
        "priority",
        "rst_stream",
        "settings",
        "push_promise",
        "ping",
        "goaway",
        "window_update",
        "continuation",
    }
)

DSL = DslSpec(
    ops={
        "connect": frozenset({"tls"}),
        "complete_handshake": frozenset({"settings"}),
        "send_msg": frozenset({"type", "stream_id", "flags"}),
        "send_raw_record": frozenset({"type", "flags", "stream_id", "length", "body"}),
        "mutate": frozenset({"field", "op", "value"}),
        "reorder": frozenset({"msgs"}),
        "repeat": frozenset({"msg"}),
        "expect": EXPECT_ARGS,
    },
    values={"type": FRAME_TYPES, "body": BODIES, "op": MUTATIONS},
    notes={
        "complete_handshake": "lời mở đầu, SETTINGS hai chiều và ACK; trạng thái sau bước này là connected",
        "send_raw_record": "một khung thô; length là giá trị trường Length trong tiêu đề khung (uint24)",
        "send_msg": "một khung hợp lệ của loại type; khung HEADERS mở luồng mới (stream_id lẻ, tăng dần)",
    },
)


class H2specBackend(DslBackend):
    name = "h2spec"
    dsl = DSL
    runner = "hyperframe/h2 (DSL) hoặc ca h2spec (mẫu bọc)"

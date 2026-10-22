"""Backend QUIC: mẫu DSL dịch sang aioquic; QUIC Interop Runner chỉ dùng để dựng SUT và làm ca sanity.

`connect` chưa gửi gì; `complete_handshake` chạy bắt tay QUIC + TLS 1.3 tới khi xác nhận xong (trạng thái `connected`).
`send_raw_record` gửi một datagram UDP chứa một gói loại `packet_type`, độn tới `datagram_length` byte tải UDP.
`send_msg` gửi một khung (frame) trong gói 1-RTT. Observation@1: `alert` là mã lỗi trong CONNECTION_CLOSE, `closed` là
kết nối kết thúc; không có phản hồi nào trong khoảng chờ thì backend ghi sự kiện `discard`.
"""

from __future__ import annotations

from rfcv.backends.base import BODIES, EXPECT_ARGS, MUTATIONS, DslBackend
from rfcv.domains.rfc_protocol.sandbox.dsl import DslSpec

DSL = DslSpec(
    ops={
        "connect": frozenset({"version"}),
        "complete_handshake": frozenset({"alpn"}),
        "send_msg": frozenset({"type", "stream_id"}),
        "send_raw_record": frozenset({"packet_type", "datagram_length", "length", "body", "encrypted"}),
        "mutate": frozenset({"field", "op", "value"}),
        "reorder": frozenset({"msgs"}),
        "repeat": frozenset({"msg"}),
        "expect": EXPECT_ARGS,
    },
    values={
        "packet_type": frozenset({"initial", "zero_rtt", "handshake", "retry", "one_rtt"}),
        "type": frozenset(
            {
                "padding",
                "ping",
                "ack",
                "reset_stream",
                "stop_sending",
                "crypto",
                "new_token",
                "stream",
                "max_data",
                "max_stream_data",
                "max_streams",
                "data_blocked",
                "new_connection_id",
                "retire_connection_id",
                "path_challenge",
                "path_response",
                "handshake_done",
            }
        ),
        "body": BODIES,
        "op": MUTATIONS,
    },
    notes={
        "send_raw_record": "một datagram UDP chứa một gói packet_type; datagram_length là kích thước tải UDP sau khi độn",
        "send_msg": "một khung hợp lệ loại type trong gói 1-RTT; trường cần đổi thì dùng mutate ngay trước",
        "mutate": "sửa khung hay gói kế tiếp, ví dụ field new_connection_id.length",
    },
)


class AioquicBackend(DslBackend):
    name = "aioquic"
    dsl = DSL
    runner = "aioquic"

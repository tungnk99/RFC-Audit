"""Backend TLS dựa trên tlsfuzzer + tlslite-ng (backend chính cho tầng 1).

Kịch bản trừu tượng (ScenarioProposal) được dịch sang đồ thị hội thoại của tlsfuzzer
(ClientHelloGenerator, ExpectServerHello, ExpectAlert…); đồ thị này bản thân đã là một DSL giới hạn.
Quan sát được chuẩn hoá thành Observation@1 với các trường miền hữu hạn.

Trạng thái: validate() đã cài đặt; run() và sanity() dựng ở tuần 1 tháng 11 (tài liệu adapter, Bảng 12),
chạy trong container test-driver, phiên bản tlsfuzzer/tlslite-ng cố định theo commit.
"""

from __future__ import annotations

from rfcv.backends.base import BODIES, EXPECT_ARGS, MUTATIONS, DslBackend
from rfcv.domains.rfc_protocol.sandbox.dsl import DslSpec

DSL = DslSpec(
    ops={
        "connect": frozenset(),
        "complete_handshake": frozenset({"version", "cipher"}),
        "send_msg": frozenset({"type", "fields"}),
        "send_raw_record": frozenset({"content_type", "type", "length", "body", "encrypted"}),
        "mutate": frozenset({"field", "op", "value"}),
        "reorder": frozenset({"msgs"}),
        "repeat": frozenset({"msg"}),
        "expect": EXPECT_ARGS,
    },
    values={
        "body": BODIES,
        "op": MUTATIONS,
        "content_type": frozenset({"change_cipher_spec", "alert", "handshake", "application_data"}),
    },
    notes={
        "complete_handshake": "bắt tay TLS đầy đủ; sau bước này trạng thái là connected",
        "send_raw_record": "một bản ghi TLS thô; encrypted=true để gửi bản ghi đã bảo vệ (TLSCiphertext) sau bắt tay",
    },
)


class TlsfuzzerBackend(DslBackend):
    name = "tlsfuzzer"
    dsl = DSL
    runner = "đồ thị hội thoại tlsfuzzer"

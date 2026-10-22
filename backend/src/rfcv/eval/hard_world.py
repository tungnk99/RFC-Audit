"""Thế giới giả "khó" cho khía cạnh REACTION: phản ứng không nằm cạnh phép kiểm tra (đo skill và prompt, BL-41, BL-74).

Thế giới đơn giản của `demo_providers` đặt `SendAlert` ngay dưới phép so sánh, nên recall REACTION luôn bằng 100% và không đo
được cải thiện nào. Ở đây phép kiểm tra chỉ trả mã lỗi `LENGTH_ERROR`; hàm gọi chuyển nó cho `HandleError`, nơi một `switch` ánh xạ
mã lỗi sang cảnh báo (có nhánh `default` và một mã lỗi khác dễ nhầm), rồi mới đến dòng đóng kết nối. Ba biến thể mã khớp với ba
cài đặt giả của `rfcv.eval.faults` (đúng, gửi sai cảnh báo, gửi đúng cảnh báo nhưng không đóng):

    hard-correct      LENGTH_ERROR → record_overflow, đóng kết nối            → COMPLIANT
    hard-wrong-alert  LENGTH_ERROR → handshake_failure, đóng kết nối          → VIOLATION (REACTION MISMATCH, sai loại)
    hard-no-close     LENGTH_ERROR → record_overflow, KHÔNG đóng kết nối      → VIOLATION (REACTION MISMATCH, thiếu đóng)

KẾT QUẢ trên thế giới này vẫn là mô phỏng (mã giả một tệp), chỉ đo khả năng lần theo mã lỗi của agent, không đo độ chính xác
trên mã thật.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from rfcv.domains.rfc_protocol.sandbox.backend import EventTrace
from rfcv.domains.rfc_protocol.schemas import ScenarioProposal
from rfcv.eval.coord_world import CoordBackend
from rfcv.eval.faults import FAMILIES, SimImpl, correct_behaviour
from rfcv.gates.code_gate import InMemoryCodeIndex, Reference, SymbolInfo

FILE = "src/internal.c"
HardCase = Literal["hard-correct", "hard-wrong-alert", "hard-no-close"]
HARD_CASES: tuple[HardCase, ...] = ("hard-correct", "hard-wrong-alert", "hard-no-close")


@dataclass(frozen=True)
class HardWorld:
    """Một biến thể: mã (chỉ mục), cài đặt SUT giả, và đáp án của khía cạnh REACTION để chấm."""

    case: HardCase
    alert: str  # cảnh báo mà `HandleError` gửi cho LENGTH_ERROR
    closes: bool  # `HandleError` có đánh dấu đóng kết nối không
    expected_reaction: Literal["MATCH", "MISMATCH"]
    expected_label: Literal["COMPLIANT", "VIOLATION"]


WORLDS: dict[HardCase, HardWorld] = {
    "hard-correct": HardWorld("hard-correct", "record_overflow", True, "MATCH", "COMPLIANT"),
    "hard-wrong-alert": HardWorld("hard-wrong-alert", "handshake_failure", True, "MISMATCH", "VIOLATION"),
    "hard-no-close": HardWorld("hard-no-close", "record_overflow", False, "MISMATCH", "VIOLATION"),
}


def sim_impl(case: HardCase) -> SimImpl:
    if case == "hard-correct":
        return SimImpl("correct-0", "correct", correct_behaviour)
    family = "wrong_alert" if case == "hard-wrong-alert" else "no_close"
    return next(f for f in FAMILIES if f.name == family).make(0)


def hard_index(case: HardCase) -> InMemoryCodeIndex:
    world = WORLDS[case]
    src = [f"/* line {i} */" for i in range(1, 900)]

    def put(n: int, text: str) -> None:
        src[n - 1] = text

    put(20, "#define MAX_RECORD_SIZE 16384")
    put(21, "#define MAX_MSG_EXTRA   256   /* MAC + padding + AEAD expansion */")
    put(30, "enum WOLFSSL_ERRORS { DECODE_ERROR = -202, LENGTH_ERROR = -203, BUFFER_ERROR = -204 };")
    put(300, "int ProcessReply(WOLFSSL* ssl)")
    put(349, "        word32 size = 0;")
    put(350, "        ret = GetRecordHeader(ssl, &size);")
    put(351, "        if (ret != 0) {")
    put(352, "            return HandleError(ssl, ret);")
    put(353, "        }")
    put(420, "}")
    put(800, "static int GetRecordHeader(WOLFSSL* ssl, word32* size)")
    put(801, "{")
    put(810, "    /* read the 5-byte record header */")
    put(811, "    GetRecordLength(ssl, size);")
    put(812, "    if (*size > MAX_RECORD_SIZE + MAX_MSG_EXTRA) {")
    put(813, '        WOLFSSL_MSG("record too long");')
    put(814, "        return LENGTH_ERROR;")
    put(815, "    }")
    put(816, "    return 0;")
    put(830, "}")
    put(840, "static int HandleError(WOLFSSL* ssl, int err)")
    put(841, "{")
    put(842, "    switch (err) {")
    put(843, "        case DECODE_ERROR:")
    put(844, "            SendAlert(ssl, alert_fatal, decode_error);")
    put(845, "            break;")
    put(846, "        case LENGTH_ERROR:")
    put(847, f"            SendAlert(ssl, alert_fatal, {world.alert});")
    put(848, "            break;")
    put(849, "        default:")
    put(850, "            SendAlert(ssl, alert_fatal, internal_error);")
    put(851, "            break;")
    put(852, "    }")
    put(
        853,
        "    ssl->options.isClosed = 1;"
        if world.closes
        else "    /* keep the connection open so the peer can retry */",
    )
    put(854, "    return err;")
    put(855, "}")
    return InMemoryCodeIndex(
        sources={FILE: src},
        symbols=[
            SymbolInfo(FILE, "ProcessReply", "function", 300, 420, "int ProcessReply(WOLFSSL* ssl)"),
            SymbolInfo(
                FILE, "GetRecordHeader", "function", 800, 830, "static int GetRecordHeader(WOLFSSL* ssl, word32* size)"
            ),
            SymbolInfo(FILE, "HandleError", "function", 840, 855, "static int HandleError(WOLFSSL* ssl, int err)"),
            SymbolInfo(FILE, "MAX_RECORD_SIZE", "macro", 20, 20, "#define MAX_RECORD_SIZE 16384"),
            SymbolInfo(FILE, "MAX_MSG_EXTRA", "macro", 21, 21, "#define MAX_MSG_EXTRA 256"),
            SymbolInfo(FILE, "LENGTH_ERROR", "enumerator", 30, 30, "LENGTH_ERROR = -203"),
            SymbolInfo(FILE, "DECODE_ERROR", "enumerator", 30, 30, "DECODE_ERROR = -202"),
        ],
        calls={("ProcessReply", "GetRecordHeader"), ("ProcessReply", "HandleError")},
        refs=[
            Reference(FILE, 350, "ProcessReply", "call"),
            Reference(FILE, 352, "ProcessReply", "call"),
            Reference(FILE, 814, "GetRecordHeader", "read"),
            Reference(FILE, 846, "HandleError", "read"),
        ],
    )


def lcov(world: HardWorld) -> bytes:
    """Dòng được thực thi khi kích hoạt đạt tới: đường kiểm tra, chuyển mã lỗi, nhánh `LENGTH_ERROR` của `HandleError`, và dòng đóng
    kết nối nếu mã có (dòng chú thích không có bản ghi DA)."""
    hit = [350, 351, 352, 811, 812, 814, 842, 846, 847, 848, 852, 854]
    if world.closes:
        hit.append(853)
    rows = "".join(f"DA:{n},5\n" for n in sorted(hit))
    return f"SF:/work/{FILE}\n{rows}DA:900,0\nend_of_record\n".encode()


class HardBackend(CoordBackend):
    """Backend giả có dữ liệu độ phủ khớp bố cục mã của thế giới khó (CoordBackend gắn cứng bố cục của thế giới đơn giản)."""

    def __init__(self, impls: Sequence[SimImpl], world: HardWorld) -> None:
        super().__init__(impls)
        self._lcov = lcov(world)

    async def run(  # type: ignore[override]
        self, scenario: ScenarioProposal, params: dict[str, int | str], endpoint: Any, seed: int
    ) -> EventTrace:
        trace = await super().run(scenario, params, endpoint, seed)
        return dataclasses.replace(trace, lcov=self._lcov)

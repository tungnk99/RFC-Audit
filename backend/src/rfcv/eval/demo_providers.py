"""Nhà cung cấp mô phỏng cho chế độ demo của giao diện web và cho `scripts/e2e_live.py`.

SUT, backend kiểm thử và mã nguồn đều GIẢ (bộ mô phỏng của `rfcv.eval`, một tệp C nhỏ trong bộ nhớ nhất quán với lỗi
gieo sẵn); agent và LLM là THẬT. Nên kết quả cho thấy cơ chế phối hợp giữa các agent, KHÔNG cho thấy độ chính xác trên
mã nguồn thật. Chỉ dùng được với yêu cầu về độ dài bản ghi TLS (TLS13-0042).
"""

from __future__ import annotations

import dataclasses
from typing import Literal

from rfcv.assembly import Providers
from rfcv.eval.coord_world import CoordBackend
from rfcv.eval.faults import FAMILIES, SimImpl, correct_behaviour, references
from rfcv.eval.sim import SimLauncher
from rfcv.gates.code_gate import InMemoryCodeIndex, SymbolInfo

FILE = "src/internal.c"
DemoCase = Literal["faulty", "correct"]
DEMO_CASES: tuple[DemoCase, ...] = ("faulty", "correct")


class NoExec:
    """Bộ chạy lệnh rỗng: chế độ demo chỉ có công cụ cấu trúc trên chỉ mục trong bộ nhớ, không có shell."""

    async def run(self, segments: list[list[str]], timeout_s: float) -> str:
        return ""


def code_index(alert: str) -> InMemoryCodeIndex:
    """Một tệp C nhỏ: macro ngưỡng ở dòng 20-21, kiểm tra độ dài ở 812, phản ứng ở 815 (khớp dữ liệu độ phủ của mô phỏng)."""
    src = [f"/* line {i} */" for i in range(1, 900)]

    def put(n: int, text: str) -> None:
        src[n - 1] = text

    put(20, "#define MAX_RECORD_SIZE 16384")
    put(21, "#define MAX_MSG_EXTRA   256   /* MAC + padding + AEAD expansion */")
    put(350, "        ret = GetRecordHeader(ssl, &size);")
    put(800, "static int GetRecordHeader(WOLFSSL* ssl, word32* size)")
    put(801, "{")
    put(810, "    /* read the 5-byte record header */")
    put(811, "    GetRecordLength(ssl, size);")
    put(812, "    if (*size > MAX_RECORD_SIZE + MAX_MSG_EXTRA) {")
    put(813, '        WOLFSSL_MSG("record too long");')
    put(814, "        /* reject over-long record */")
    put(815, f"        SendAlert(ssl, alert_fatal, {alert});")
    put(816, "        return LENGTH_ERROR;")
    put(817, "    }")
    put(830, "}")
    sig = "static int GetRecordHeader(WOLFSSL* ssl, word32* size)"
    return InMemoryCodeIndex(
        sources={FILE: src},
        symbols=[
            SymbolInfo(FILE, "GetRecordHeader", "function", 800, 830, sig),
            SymbolInfo(FILE, "ProcessReply", "function", 300, 420, "int ProcessReply(WOLFSSL* ssl)"),
            SymbolInfo(FILE, "MAX_RECORD_SIZE", "macro", 20, 20, "#define MAX_RECORD_SIZE 16384"),
            SymbolInfo(FILE, "MAX_MSG_EXTRA", "macro", 21, 21, "#define MAX_MSG_EXTRA 256"),
        ],
        calls={("ProcessReply", "GetRecordHeader")},
    )


def sim_impl(case: DemoCase) -> tuple[SimImpl, str]:
    """(cài đặt giả, cảnh báo mà dòng mã giả gửi): bản lỗi gửi sai cảnh báo, bản đúng gửi record_overflow."""
    if case == "faulty":
        return next(f for f in FAMILIES if f.name == "wrong_alert").make(0), "handshake_failure"
    return SimImpl("correct-0", "correct", correct_behaviour), "record_overflow"


def demo_providers(case: DemoCase, *, sut_name: str = "wolfssl") -> Providers:
    """Providers cho `build_runtime`. Tên cài đặt giả khớp adapter: SUT lấy theo tên kho, tham chiếu theo `references`."""
    impl, alert = sim_impl(case)
    refs = references()
    named = [
        dataclasses.replace(impl, name=sut_name),
        *(dataclasses.replace(r, name=n) for r, n in zip(refs, ("rustls", "openssl"), strict=True)),
    ]
    return Providers(
        backend=CoordBackend(named),
        code_index=code_index(alert),
        executor=NoExec(),
        sut_launcher=SimLauncher(),
    )

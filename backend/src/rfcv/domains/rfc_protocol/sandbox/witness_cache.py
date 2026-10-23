"""Bộ nhớ đệm kết quả của bản tham chiếu độc lập (nhân chứng dương).

Bản tham chiếu (OpenSSL, GnuTLS...) không phụ thuộc commit của SUT: cùng ảnh, cùng kịch bản, cùng oracle, cùng tham số thì cho cùng
kết quả. Đo: bug/fix/head chạy lại y hệt 2 bản tham chiếu cho mỗi biến thể, chiếm 2/3 số container của T3. Chạy một lần rồi dùng
chung cho mọi phiên bản SUT và mọi lần chạy lại.

Chỉ lưu PASS/FAIL (không lưu ERROR). Khoá gồm định danh ảnh (id ảnh docker), nên đổi ảnh tham chiếu thì tự bỏ cache. Bằng chứng T3 vẫn
ghi đủ `witness` như khi chạy thật; trace có `cache_hit` kèm lần chạy gốc để truy vết. Tắt bằng RFCV_WITNESS_CACHE=off.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import time
from pathlib import Path

from rfcv.common.hashing import content_hash
from rfcv.domains.rfc_protocol.payloads import Outcome

ENV_SWITCH = "RFCV_WITNESS_CACHE"


def enabled() -> bool:
    return os.environ.get(ENV_SWITCH, "on").lower() not in ("off", "0", "false")


def cache_key(**parts: object) -> str:
    return content_hash(parts)


class WitnessCache:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS witness(key TEXT PRIMARY KEY, outcome TEXT NOT NULL, origin_run TEXT, ts REAL)"
        )
        self._conn.commit()

    def get(self, key: str) -> tuple[Outcome, str | None] | None:
        row = self._conn.execute("SELECT outcome, origin_run FROM witness WHERE key=?", (key,)).fetchone()
        return (Outcome(row[0]), row[1]) if row else None

    def put(self, key: str, outcome: Outcome, origin_run: str) -> None:
        if outcome not in (Outcome.PASS, Outcome.FAIL):
            return
        with contextlib.suppress(sqlite3.Error):
            self._conn.execute(
                "INSERT OR REPLACE INTO witness(key, outcome, origin_run, ts) VALUES (?,?,?,?)",
                (key, outcome.value, origin_run, time.time()),
            )
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

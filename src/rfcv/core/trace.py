"""Trace log: ghi tuần tự mọi thông điệp, lời gọi, quyết định từ chối, số token. Chỉ ghi thêm.

Bộ công cụ đánh giá (eval/) đọc dữ liệu chi phí, số vòng, lời gọi bị từ chối từ đây.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from rfcv.common.hashing import canonical_json


class TraceLog:
    def __init__(self, path: Path | str) -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._lock = threading.Lock()
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ns INTEGER NOT NULL,
                run_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                role TEXT,
                requirement_id TEXT,
                payload TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
            BEGIN SELECT RAISE(ABORT, 'trace is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
            BEGIN SELECT RAISE(ABORT, 'trace is append-only'); END;
            """
        )

    def append(
        self,
        run_id: str,
        kind: str,
        payload: dict[str, Any],
        *,
        role: str | None = None,
        requirement_id: str | None = None,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO events(ts_ns, run_id, kind, role, requirement_id, payload) VALUES (?,?,?,?,?,?)",
                (time.time_ns(), run_id, kind, role, requirement_id, canonical_json(payload).decode()),
            )
            return int(cur.lastrowid or 0)

    def events(self, kind: str | None = None) -> Iterator[dict[str, Any]]:
        sql = "SELECT seq, ts_ns, run_id, kind, role, requirement_id, payload FROM events"
        args: tuple[str, ...] = ()
        if kind is not None:
            sql += " WHERE kind = ?"
            args = (kind,)
        for seq, ts, run_id, k, role, req, payload in self._conn.execute(sql + " ORDER BY seq", args):
            yield {
                "seq": seq,
                "ts_ns": ts,
                "run_id": run_id,
                "kind": k,
                "role": role,
                "requirement_id": req,
                "payload": json.loads(payload),
            }

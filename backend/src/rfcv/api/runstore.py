"""Đọc một thư mục lần chạy (`runs/<run_id>`) để hiển thị. Chỉ đọc, mở SQLite ở chế độ `mode=ro`, nên xem được cả lần
chạy đang diễn ra mà không chen vào bộ ghi. Không dùng TraceLog/EvidenceStore vì hai lớp đó tạo bảng khi mở."""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


@contextmanager
def _ro(path: Path) -> Generator[sqlite3.Connection]:
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        yield conn
    finally:
        conn.close()


def _event(row: tuple[Any, ...]) -> dict[str, Any]:
    seq, ts, run_id, kind, role, req, payload = row
    return {
        "seq": seq,
        "ts_ns": ts,
        "run_id": run_id,
        "kind": kind,
        "role": role,
        "requirement_id": req,
        "payload": json.loads(payload),
    }


_COLS = "seq, ts_ns, run_id, kind, role, requirement_id, payload"


def has_trace(run_dir: Path) -> bool:
    return (run_dir / "trace.db").is_file()


def events_after(run_dir: Path, after: int = 0, limit: int = 500) -> list[dict[str, Any]]:
    if not has_trace(run_dir):
        return []
    with _ro(run_dir / "trace.db") as c:
        rows = c.execute(f"SELECT {_COLS} FROM events WHERE seq > ? ORDER BY seq LIMIT ?", (after, limit)).fetchall()
    return [_event(r) for r in rows]


def get_event(run_dir: Path, seq: int) -> dict[str, Any] | None:
    if not has_trace(run_dir):
        return None
    with _ro(run_dir / "trace.db") as c:
        row = c.execute(f"SELECT {_COLS} FROM events WHERE seq = ?", (seq,)).fetchone()
    return _event(row) if row else None


def kind_events(run_dir: Path, *kinds: str) -> list[dict[str, Any]]:
    if not has_trace(run_dir):
        return []
    marks = ",".join("?" * len(kinds))
    with _ro(run_dir / "trace.db") as c:
        rows = c.execute(f"SELECT {_COLS} FROM events WHERE kind IN ({marks}) ORDER BY seq", kinds).fetchall()
    return [_event(r) for r in rows]


def time_span(run_dir: Path) -> tuple[int, int]:
    """(ts_ns đầu, ts_ns cuối) của trace; (0, 0) khi chưa có."""
    if not has_trace(run_dir):
        return 0, 0
    with _ro(run_dir / "trace.db") as c:
        lo, hi = c.execute("SELECT MIN(ts_ns), MAX(ts_ns) FROM events").fetchone()
    return int(lo or 0), int(hi or 0)


ro = _ro


def summary(run_dir: Path) -> dict[str, Any]:
    """Tổng quan để vẽ đầu trang: từng yêu cầu (nhãn nếu đã có), mức dùng token theo agent, số sự kiện."""
    reqs: dict[str, dict[str, Any]] = {}
    for e in kind_events(run_dir, "requirement_start", "stop", "verdict"):
        r = reqs.setdefault(str(e["requirement_id"]), {"id": e["requirement_id"], "label": None})
        p = e["payload"]
        if e["kind"] == "requirement_start":
            r.update(rtype=p.get("rtype"), modal=p.get("modal"), budget=p.get("budget"), started_seq=e["seq"])
        elif e["kind"] == "stop":
            r.update(stop_reason=p.get("reason"), used=p.get("used"), rounds=p.get("round"))
        else:
            r.update(label=p.get("label"), rule=p.get("rule"), assurance=p.get("assurance"), decided_seq=e["seq"])
    usage: dict[str, dict[str, int]] = defaultdict(lambda: {"runs": 0, "tokens": 0, "tool_calls": 0, "duration_ms": 0})
    for e in kind_events(run_dir, "role_run"):
        p = e["payload"]
        u = usage[str(p.get("role"))]
        u["runs"] += 1
        u["tokens"] += int(p.get("tokens") or 0)
        u["tool_calls"] += int(p.get("tool_calls") or 0)
        u["duration_ms"] += int(p.get("duration_ms") or 0)
    n = 0
    if has_trace(run_dir):
        with _ro(run_dir / "trace.db") as c:
            n = int(c.execute("SELECT COUNT(*) FROM events").fetchone()[0])
    return {"requirements": list(reqs.values()), "usage_by_role": dict(usage), "events": n}


def _brief(payload: dict[str, Any]) -> dict[str, Any]:
    """Trường vô hướng hoặc danh sách ngắn của payload bằng chứng, đủ để đọc lướt mà không phải mở bản ghi."""
    out: dict[str, Any] = {}
    for k, v in payload.items():
        if k in ("kind", "artifacts") or v is None:
            continue
        if (isinstance(v, str | int | float | bool) and len(str(v)) <= 90) or (
            isinstance(v, dict | list) and len(json.dumps(v, ensure_ascii=False, default=str)) <= 90
        ):
            out[k] = v
    return out


def _evidence_row(seq: int, eid: str, body: str, *, full: bool) -> dict[str, Any]:
    rec: dict[str, Any] = json.loads(body)
    payload: dict[str, Any] = rec.get("payload") or {}
    item: dict[str, Any] = {
        "seq": seq,
        "evidence_id": eid,
        "tier": rec.get("tier"),
        "kind": payload.get("kind"),
        "polarity": rec.get("polarity"),
        "produced_by": rec.get("produced_by"),
        "requested_by": rec.get("requested_by"),
        "requirement_id": rec.get("requirement_id"),
        "ifc": rec.get("ifc"),
        "brief": _brief(payload),
    }
    if full:
        item["record"] = rec
    return item


def evidence(run_dir: Path, requirement: str | None = None) -> list[dict[str, Any]]:
    db = run_dir / "evidence.db"
    if not db.is_file():
        return []
    sql, args = "SELECT seq, evidence_id, body FROM evidence", ()
    if requirement:
        sql, args = sql + " WHERE requirement_id = ?", (requirement,)
    with _ro(db) as c:
        return [_evidence_row(s, i, b, full=False) for s, i, b in c.execute(sql + " ORDER BY seq", args)]


def evidence_item(run_dir: Path, evidence_id: str) -> dict[str, Any] | None:
    db = run_dir / "evidence.db"
    if not db.is_file():
        return None
    with _ro(db) as c:
        row = c.execute("SELECT seq, evidence_id, body FROM evidence WHERE evidence_id = ?", (evidence_id,)).fetchone()
    return _evidence_row(row[0], row[1], row[2], full=True) if row else None


def manifest(run_dir: Path) -> dict[str, Any] | None:
    f = run_dir / "manifest.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None

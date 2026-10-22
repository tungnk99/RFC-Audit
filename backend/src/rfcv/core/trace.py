"""Trace log: ghi tuần tự mọi thông điệp, lời gọi, quyết định từ chối, số token. Chỉ ghi thêm.

Bộ công cụ đánh giá (eval/) đọc dữ liệu chi phí, số vòng, lời gọi bị từ chối từ đây.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, cast

from rfcv.common.hashing import canonical_json


def _rows(value: Any) -> list[Mapping[str, Any]]:
    """Danh sách bản ghi trong payload (bỏ phần tử không phải ánh xạ); payload đọc từ JSON nên kiểu là Any."""
    return [cast("Mapping[str, Any]", r) for r in cast("list[Any]", value or []) if isinstance(r, Mapping)]


def _missing_text(items: Any) -> str:
    return ",".join(f"{m.get('need')}:{m.get('variant') or '*'}" for m in _rows(items)) or "-"


def describe(event: Mapping[str, Any]) -> str:
    """Một dòng mô tả sự kiện cho `rfcv trace`. Chỉ trích trường chính; đầy đủ vẫn nằm trong payload."""
    p: Mapping[str, Any] = event.get("payload") or {}
    match event["kind"]:
        case "requirement_start":
            return f"loại {p.get('rtype')}; ngân sách {p.get('budget')}"
        case "round_start":
            return f"đã dùng {p.get('used')}"
        case "sufficiency":
            prov = p.get("provisional")
            label = f"{prov['label']}({prov['rule']})" if isinstance(prov, Mapping) else "chưa có"
            return (
                f"nhãn tạm {label}; thiếu {_missing_text(p.get('missing'))}; mâu thuẫn {len(_rows(p.get('conflicts')))}"
            )
        case "plan":
            tasks = [str(t.get("task_type")) for t in _rows(p.get("tasks"))]
            return f"{p.get('action')} {tasks} ({p.get('rationale_code')})"
        case "plan_context":
            advice = cast("Mapping[str, Any]", p.get("advice") or {})
            return f"{p.get('adherence')}; sổ tay gợi ý {advice.get('rule', '-')} {advice.get('tasks', [])}; {p.get('situation')}"
        case "plan_context_error":
            return f"không dựng được tình huống: {p.get('error')}"
        case "message":
            body = cast("Mapping[str, Any]", p.get("body") or {})
            return f"giao {body.get('task_type', '-')} → {p.get('to_role')}"
        case "role_run":
            out = f"; ra {p.get('schema')}" if p.get("ok") else f"; HỎNG {p.get('failure')}"
            return f"{p.get('duration_ms')}ms, {p.get('tokens')} token, {p.get('tool_calls')} công cụ, làm lại {p.get('output_retries')}{out}"
        case "task_result":
            return f"{p.get('task_type')} → {p.get('new_evidence')} bằng chứng mới"
        case "critique_result":
            kinds = [str(i.get("kind")) for i in _rows(p.get("issues"))]
            return f"{'sạch' if p.get('clean') else kinds}; gating={p.get('gating')}"
        case "stop":
            detail = {k: v for k, v in p.items() if k not in ("round", "reason", "used")}
            return f"{p.get('reason')} {detail or ''}".strip()
        case "verdict":
            return f"{p.get('label')} theo {p.get('rule')} (dừng: {p.get('stop_reason')})"
        case "gate_reject":
            return f"{p.get('gate')}: {p.get('errors')}"
        case "role_failure":
            return f"{p.get('role')}: {p.get('failure')}"
        case "task_rejected" | "stop_rejected":
            return str({k: v for k, v in p.items() if k != "round"})
        case "tool_call":
            return f"{p.get('tool')} {p.get('args')}"
        case "tool_denied":
            return f"{p.get('tool')}: {p.get('code')}"
        case "llm_run":
            return (
                f"{p.get('duration_ms')}ms, vào {p.get('input_tokens')} ra {p.get('output_tokens')}; "
                f"skill nạp {p.get('skills_loaded')}/{p.get('skills_offered')}"
            )
        case "llm_failure":
            return f"{p.get('error')} sau {p.get('duration_ms')}ms"
        case "output_retry":
            return f"lần {p.get('attempt')}: {p.get('errors')}"
        case "t3":
            return f"{p.get('variant')}: {p.get('outcome')}"
        case "t3_case":
            why = f" ({p.get('reason')}: {p.get('detail')})" if p.get("reason") else ""
            return f"{p.get('variant')} · {p.get('role')} {p.get('impl')} môi trường {p.get('environment')}: {p.get('outcome')}{why}"
        case _:
            return ""


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

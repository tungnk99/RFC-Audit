"""Requirement registry: yêu cầu, RBS và vòng đời (thiết kế chính, Hình 3, Bảng 17).

Bất biến: chỉ Verdict engine được đưa yêu cầu sang DECIDED. Lịch sử trạng thái chỉ ghi thêm.
"""

from __future__ import annotations

import sqlite3
from enum import StrEnum
from pathlib import Path

from rfcv.common.hashing import canonical_json


class State(StrEnum):
    EXTRACTED = "EXTRACTED"
    SPECIFIED = "SPECIFIED"
    INVESTIGATING = "INVESTIGATING"
    DECIDED = "DECIDED"
    REPORTED = "REPORTED"


_TRANSITIONS: dict[State, frozenset[State]] = {
    State.EXTRACTED: frozenset({State.SPECIFIED}),
    State.SPECIFIED: frozenset({State.INVESTIGATING}),
    State.INVESTIGATING: frozenset({State.DECIDED}),
    State.DECIDED: frozenset({State.REPORTED, State.INVESTIGATING}),  # kiểm chứng lại (M6)
    State.REPORTED: frozenset({State.INVESTIGATING}),
}

VERDICT_ENGINE = "verdict_engine"


class TransitionError(RuntimeError):
    pass


class RequirementRegistry:
    def __init__(self, path: Path | str) -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS requirements (
                requirement_id TEXT PRIMARY KEY,
                body TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS state_log (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                requirement_id TEXT NOT NULL,
                state TEXT NOT NULL,
                actor TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS state_log_no_update BEFORE UPDATE ON state_log
            BEGIN SELECT RAISE(ABORT, 'state_log is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS state_log_no_delete BEFORE DELETE ON state_log
            BEGIN SELECT RAISE(ABORT, 'state_log is append-only'); END;
            """
        )

    def add(self, requirement_id: str, body: dict[str, object], actor: str) -> None:
        self._conn.execute(
            "INSERT INTO requirements(requirement_id, body) VALUES (?, ?)",
            (requirement_id, canonical_json(body).decode()),
        )
        self._log(requirement_id, State.EXTRACTED, actor)

    def state(self, requirement_id: str) -> State:
        row = self._conn.execute(
            "SELECT state FROM state_log WHERE requirement_id = ? ORDER BY seq DESC LIMIT 1",
            (requirement_id,),
        ).fetchone()
        if row is None:
            raise KeyError(requirement_id)
        return State(row[0])

    def transition(self, requirement_id: str, new: State, actor: str) -> None:
        current = self.state(requirement_id)
        if new not in _TRANSITIONS[current]:
            raise TransitionError(f"{requirement_id}: {current} → {new} không hợp lệ")
        if new is State.DECIDED and actor != VERDICT_ENGINE:
            raise TransitionError("chỉ Verdict engine được chuyển yêu cầu sang DECIDED")
        self._log(requirement_id, new, actor)

    def _log(self, requirement_id: str, state: State, actor: str) -> None:
        self._conn.execute(
            "INSERT INTO state_log(requirement_id, state, actor) VALUES (?, ?, ?)",
            (requirement_id, state.value, actor),
        )

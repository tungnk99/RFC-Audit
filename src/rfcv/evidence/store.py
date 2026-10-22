"""Evidence store: lưu bằng chứng bất biến, nối chuỗi hash (thiết kế chính, Bảng 17, rủi ro A5).

Bất biến:
- chỉ ghi thêm: trigger SQLite chặn UPDATE và DELETE;
- mỗi bằng chứng định danh bằng hash nội dung (JCS), nối với bằng chứng trước qua prev_hash;
- verify_chain() phát hiện mọi sửa đổi sau khi ghi.
Kết luận (Verdict) và nhận định của Reviewer cũng lưu ở đây, cùng tính chất chỉ ghi thêm (BR3).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rfcv.common.hashing import GENESIS, canonical_json, content_hash
from rfcv.evidence.models import Evidence, EvidenceDraft, polarity_of
from rfcv.plugins import current_registry

# Phiên bản bố cục bảng của kho. Tăng khi đổi bảng; kho mới hơn bản mã đang chạy sẽ bị từ chối thay vì đọc sai.
STORE_SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_id TEXT NOT NULL UNIQUE,
    prev_hash TEXT NOT NULL,
    requirement_id TEXT NOT NULL,
    tier TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS evidence_req ON evidence(requirement_id);
CREATE TABLE IF NOT EXISTS verdicts (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    requirement_id TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    requirement_id TEXT NOT NULL,
    body TEXT NOT NULL
);
"""

_APPEND_ONLY_TABLES = ("evidence", "verdicts", "reviews")


def _append_only_triggers(table: str) -> str:
    return f"""
CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table}
BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;
CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table}
BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;
"""


def seal(draft: EvidenceDraft, prev_hash: str) -> tuple[str, dict[str, Any]]:
    """Dựng bản ghi bất biến từ bản nháp: thêm prev_hash, chiều, phiên bản schema; trả (evidence_id, bản ghi).

    Là cách duy nhất tạo `evidence_id`; mọi nơi cần dự đoán id (kể cả kiểm thử) phải dùng hàm này.
    """
    record: dict[str, Any] = draft.model_dump(mode="json")
    record["prev_hash"] = prev_hash
    record["polarity"] = polarity_of(draft.payload).value
    kind = current_registry().kinds[str(record["payload"]["kind"])]
    record["kind_schema"] = f"{kind.name}@{kind.version}"
    return content_hash(record), record


def _upgrade(record: dict[str, Any]) -> dict[str, Any]:
    """Nâng payload của bản ghi cũ lên phiên bản hiện hành của loại bằng chứng khi đọc.

    Bản ghi trên đĩa không bao giờ bị sửa (chuỗi hash giữ nguyên); chỉ bản trong bộ nhớ được nâng.
    """
    kind = current_registry().kinds.get(str(record.get("payload", {}).get("kind")))
    if kind is None:
        return record
    stored = str(record.get("kind_schema", f"{kind.name}@1"))
    version = int(stored.rpartition("@")[2] or 1)
    if version >= kind.version:
        return record
    payload = dict(record["payload"])
    for v in range(version, kind.version):
        payload = kind.upgrades[v](payload)
    return {**record, "payload": payload, "kind_schema": f"{kind.name}@{kind.version}"}


@dataclass(frozen=True)
class ChainReport:
    ok: bool
    count: int
    head: str
    broken_at: int | None = None
    reason: str | None = None


class StoreVersionError(RuntimeError):
    pass


class EvidenceStore:
    """Cài đặt SQLite của `EvidenceRepository`. Một kho thuộc đúng một tenant."""

    def __init__(self, path: Path | str, *, tenant: str = "default") -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self._conn.executescript(_SCHEMA + "".join(_append_only_triggers(t) for t in _APPEND_ONLY_TABLES))
        self.tenant = tenant
        self._check_meta()

    def _check_meta(self) -> None:
        meta = dict(self._conn.execute("SELECT key, value FROM meta").fetchall())
        if not meta:
            self._conn.executemany(
                "INSERT INTO meta(key, value) VALUES (?, ?)",
                [("schema_version", str(STORE_SCHEMA_VERSION)), ("tenant", self.tenant)],
            )
            return
        if int(meta.get("schema_version", "0")) > STORE_SCHEMA_VERSION:
            raise StoreVersionError(
                f"kho có schema_version {meta['schema_version']} mới hơn bản mã ({STORE_SCHEMA_VERSION}); hãy nâng rfcv"
            )
        if meta.get("tenant", "default") != self.tenant:
            raise StoreVersionError(f"kho thuộc tenant '{meta.get('tenant')}', không phải '{self.tenant}'")

    def close(self) -> None:
        self._conn.close()

    # ---- bằng chứng ---------------------------------------------------------

    def head(self) -> str:
        row = self._conn.execute("SELECT evidence_id FROM evidence ORDER BY seq DESC LIMIT 1").fetchone()
        return row[0] if row else GENESIS

    def append(self, draft: EvidenceDraft) -> Evidence:
        with self._lock:
            prev = self.head()
            evidence_id, record = seal(draft, prev)
            self._conn.execute(
                "INSERT INTO evidence(evidence_id, prev_hash, requirement_id, tier, body) VALUES (?,?,?,?,?)",
                (evidence_id, prev, draft.requirement_id, str(draft.tier), canonical_json(record).decode()),
            )
        return Evidence.model_validate({**record, "evidence_id": evidence_id})

    def get(self, evidence_id: str) -> Evidence | None:
        row = self._conn.execute(
            "SELECT evidence_id, body FROM evidence WHERE evidence_id = ?", (evidence_id,)
        ).fetchone()
        return self._row_to_evidence(row) if row else None

    def for_requirement(self, requirement_id: str) -> list[Evidence]:
        rows = self._conn.execute(
            "SELECT evidence_id, body FROM evidence WHERE requirement_id = ? ORDER BY seq",
            (requirement_id,),
        ).fetchall()
        return [self._row_to_evidence(r) for r in rows]

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0])

    def verify_chain(self) -> ChainReport:
        """Tính lại hash từng bản ghi và kiểm tra liên kết prev_hash (rfcv verify)."""
        expected_prev = GENESIS
        count = 0
        for seq, evidence_id, prev_hash, body in self._conn.execute(
            "SELECT seq, evidence_id, prev_hash, body FROM evidence ORDER BY seq"
        ):
            record = json.loads(body)
            if prev_hash != expected_prev or record.get("prev_hash") != expected_prev:
                return ChainReport(False, count, expected_prev, seq, "prev_hash không khớp")
            if content_hash(record) != evidence_id:
                return ChainReport(False, count, expected_prev, seq, "nội dung không khớp hash")
            expected_prev = evidence_id
            count += 1
        return ChainReport(True, count, expected_prev)

    @staticmethod
    def _row_to_evidence(row: Sequence[Any]) -> Evidence:
        record = _upgrade(json.loads(row[1]))
        return Evidence.model_validate({**record, "evidence_id": row[0]})

    # ---- kết luận và nhận định ---------------------------------------------

    def record_verdict(self, requirement_id: str, verdict: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO verdicts(requirement_id, body) VALUES (?, ?)",
                (requirement_id, canonical_json(verdict).decode()),
            )

    def latest_verdicts(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for req, body in self._conn.execute("SELECT requirement_id, body FROM verdicts ORDER BY seq"):
            out[req] = json.loads(body)
        return out

    def record_review(self, requirement_id: str, review: dict[str, Any]) -> None:
        """Nhận định của Reviewer là bản ghi riêng, không ghi đè nhãn (BR3)."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO reviews(requirement_id, body) VALUES (?, ?)",
                (requirement_id, canonical_json(review).decode()),
            )

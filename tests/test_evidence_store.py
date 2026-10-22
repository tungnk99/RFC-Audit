"""Evidence store: chỉ ghi thêm, chuỗi hash phát hiện sửa đổi (rủi ro A5)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from helpers import REQ, t1, t3
from rfcv.common.hashing import GENESIS
from rfcv.domains.rfc_protocol.payloads import Outcome, Producer, Tier
from rfcv.evidence.models import EvidenceDraft, Polarity
from rfcv.evidence.store import EvidenceStore


def test_append_links_hash_chain(store: EvidenceStore) -> None:
    a = store.append(t3(outcome=Outcome.FAIL))
    b = store.append(t1())
    assert a.prev_hash == GENESIS
    assert b.prev_hash == a.evidence_id
    assert a.polarity is Polarity.REFUTES and b.polarity is Polarity.SUPPORTS
    assert [e.evidence_id for e in store.for_requirement(REQ)] == [a.evidence_id, b.evidence_id]
    assert store.get(a.evidence_id) == a
    report = store.verify_chain()
    assert report.ok and report.count == 2 and report.head == b.evidence_id


def test_update_and_delete_are_blocked(store: EvidenceStore) -> None:
    store.append(t3())
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("UPDATE evidence SET body = '{}'")  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("DELETE FROM evidence")  # pyright: ignore[reportPrivateUsage]


def test_tampering_detected_by_chain(tmp_path: Path) -> None:
    path = tmp_path / "evidence.db"
    s = EvidenceStore(path)
    s.append(t3(outcome=Outcome.FAIL))
    s.append(t1())
    s.close()
    # Kẻ tấn công có quyền ghi tệp: gỡ trigger và sửa kết quả FAIL thành PASS.
    raw = sqlite3.connect(path)
    raw.execute("DROP TRIGGER evidence_no_update")
    body = raw.execute("SELECT body FROM evidence WHERE seq = 1").fetchone()[0]
    raw.execute("UPDATE evidence SET body = ? WHERE seq = 1", (body.replace('"FAIL"', '"PASS"'),))
    raw.commit()
    raw.close()
    report = EvidenceStore(path).verify_chain()
    assert not report.ok and report.broken_at == 1


def test_tier_must_match_payload() -> None:
    draft = t3()
    with pytest.raises(ValidationError):
        EvidenceDraft(
            run_id="r", requirement_id=REQ, tier=Tier.T1, payload=draft.payload, produced_by=Producer.TEST_DRIVER
        )


def test_verdicts_and_reviews_are_separate_append_only(store: EvidenceStore) -> None:
    store.record_verdict(REQ, {"label": "VIOLATION", "rule": "V2"})
    store.record_verdict(REQ, {"label": "VIOLATION", "rule": "V2", "round": 2})
    store.record_review(REQ, {"human_label": "COMPLIANT", "reason": "x"})
    assert store.latest_verdicts()[REQ]["round"] == 2
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("DELETE FROM reviews")  # pyright: ignore[reportPrivateUsage]

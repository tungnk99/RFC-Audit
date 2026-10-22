"""Phiên bản hoá: dữ liệu bằng chứng cũ vẫn đọc được sau khi mô hình đổi; kho từ chối tenant/phiên bản lạ;
rules_version."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from helpers import REQ, t3
from rfcv.domains.rfc_protocol.payloads import Outcome, T3Payload
from rfcv.domains.rfc_protocol.rules import RULE_SET
from rfcv.evidence.models import EvidenceDraft
from rfcv.evidence.store import STORE_SCHEMA_VERSION, EvidenceStore, StoreVersionError, seal
from rfcv.evidence.verdict_engine import Decision, Label, Rule
from rfcv.plugins import Registry, use_registry
from rfcv.spi import EvidenceKind


def test_evidence_record_carries_its_schema_version(store: EvidenceStore) -> None:
    e = store.append(t3())
    row = store._conn.execute("SELECT body FROM evidence").fetchone()  # pyright: ignore[reportPrivateUsage]
    assert json.loads(row[0])["kind_schema"] == "scenario_result@2"
    assert e.kind_schema == "scenario_result@2"


def test_old_records_are_upgraded_on_read_without_touching_the_chain(tmp_path: Path) -> None:
    """Giả lập: bản 1 của loại bằng chứng gọi trường `outcome`, bản 2 đổi thành `verdict`. Dữ liệu cũ vẫn đọc được."""
    path = tmp_path / "evidence.db"
    old = EvidenceStore(path)
    first = old.append(t3(outcome=Outcome.FAIL))
    old.close()

    base = Registry.build(builtin=True, third_party=False, freeze=False)
    kind = base.kinds["scenario_result"]

    class T3V2(T3Payload):
        """Bản 2 thêm trường mới có mặc định; payload cũ thiếu trường này."""

        note: str = "nâng cấp"

    upgraded = EvidenceKind(
        kind.name,
        kind.tier,
        T3V2,
        kind.producers,
        kind.polarity,
        kind.summarize,
        version=3,
        upgrades={2: lambda payload: {**payload, "note": "đã nâng từ v2"}},
    )
    reg = Registry(allow_effects=base.allow_effects)
    reg.kinds.update({**base.kinds, "scenario_result": upgraded})
    reg.schemas.update(base.schemas)
    reg.tasks.update(base.tasks)
    reg.domains.update(base.domains)
    reg.rule_sets.update(base.rule_sets)
    reg.tools.update(base.tools)
    reg.freeze()

    with use_registry(reg):
        again = EvidenceStore(path)
        (read,) = again.for_requirement(REQ)
        assert isinstance(read.payload, T3V2) and read.payload.note == "đã nâng từ v2"
        assert read.kind_schema == "scenario_result@3"
        assert read.evidence_id == first.evidence_id  # id gốc giữ nguyên
        assert again.verify_chain().ok  # chuỗi hash tính trên bản gốc trên đĩa, không bị ảnh hưởng
        # bản ghi mới ghi theo phiên bản mới (payload phải đúng lớp của phiên bản hiện hành)
        new = EvidenceDraft(
            run_id="run-test",
            requirement_id=REQ,
            tier="T3",
            payload=T3V2(
                scenario="sha256:s",
                oracle="sha256:o",
                variant="boundary:record.length=16641",
                variant_class="required",
                trigger_reached=True,
                outcome=Outcome.PASS,
            ),
            produced_by="test_driver",
        )
        nxt = again.append(new)
        assert nxt.kind_schema == "scenario_result@3"
        again.close()


def test_store_refuses_a_database_written_by_a_newer_version(tmp_path: Path) -> None:
    path = tmp_path / "evidence.db"
    EvidenceStore(path).close()
    raw = sqlite3.connect(path)
    raw.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(STORE_SCHEMA_VERSION + 1),))
    raw.commit()
    raw.close()
    with pytest.raises(StoreVersionError, match="mới hơn"):
        EvidenceStore(path)


def test_store_belongs_to_one_tenant(tmp_path: Path) -> None:
    path = tmp_path / "evidence.db"
    EvidenceStore(path, tenant="acme").close()
    EvidenceStore(path, tenant="acme").close()  # cùng tenant mở lại được
    with pytest.raises(StoreVersionError, match="tenant"):
        EvidenceStore(path, tenant="globex")


def test_seal_is_the_single_source_of_evidence_ids(store: EvidenceStore) -> None:
    draft = t3()
    predicted, _ = seal(draft, store.head())
    assert store.append(draft).evidence_id == predicted


# ---------------------------------------------------------------- rules_version


def test_rules_version_is_a_content_hash_and_is_stable() -> None:
    assert RULE_SET.version.startswith("sha256:")
    assert RULE_SET.version == replace(RULE_SET).version  # dựng lại cùng nội dung thì cùng phiên bản


def test_changing_any_rule_changes_the_rules_version() -> None:
    extra = Rule("X", lambda req, data: Decision(Label.NEEDS_REVIEW, "X", ()), None, "quy tắc thêm")
    assert replace(RULE_SET, rules=(*RULE_SET.rules, extra)).version != RULE_SET.version
    assert replace(RULE_SET, rules=RULE_SET.rules[:-1]).version != RULE_SET.version  # bỏ một quy tắc
    assert replace(RULE_SET, rules=tuple(reversed(RULE_SET.rules))).version != RULE_SET.version  # đổi thứ tự
    first = RULE_SET.rules[0]
    reworded = replace(first, description=first.description + " (sửa)")
    assert replace(RULE_SET, rules=(reworded, *RULE_SET.rules[1:])).version != RULE_SET.version


def test_changing_a_rule_body_changes_the_rules_version() -> None:
    def loose(req: object, data: object) -> Decision | None:
        return None

    other = replace(RULE_SET, rules=(replace(RULE_SET.rules[0], decide=loose), *RULE_SET.rules[1:]))
    assert other.version != RULE_SET.version


def test_a_genuine_version_1_record_is_still_readable(tmp_path: Path) -> None:
    """Dữ liệu ghi trước khi thêm trường `side` (scenario_result@1) vẫn đọc được, chuỗi hash giữ nguyên."""
    from rfcv.common.hashing import canonical_json, content_hash

    path = tmp_path / "evidence.db"
    store = EvidenceStore(path)
    _, record = seal(t3(outcome=Outcome.FAIL), store.head())
    record["kind_schema"] = "scenario_result@1"
    record["payload"].pop("side")  # bản v1 chưa có trường này
    evidence_id = content_hash(record)
    store._conn.execute(  # pyright: ignore[reportPrivateUsage]
        "INSERT INTO evidence(evidence_id, prev_hash, requirement_id, tier, body) VALUES (?,?,?,?,?)",
        (evidence_id, record["prev_hash"], REQ, "T3", canonical_json(record).decode()),
    )
    (read,) = store.for_requirement(REQ)
    assert read.evidence_id == evidence_id and read.kind_schema == "scenario_result@2"
    assert isinstance(read.payload, T3Payload) and read.payload.side == "trigger"
    assert store.verify_chain().ok

"""Hợp đồng phối hợp: mọi thứ một vai trò khai báo cần phải được cấp, mọi nhiệm vụ trong danh mục phải có người xử lý.

Những chỗ đã biết là chưa nối được ghi tường minh trong hai danh sách bên dưới. Danh sách chỉ được rút ngắn: thêm một mục
mới vào đây nghĩa là cố ý chấp nhận một khoảng trống năng lực và phải có lý do.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from conftest import ADAPTER_DIR, AGENTS_DIR
from rfcv.adapters.manifest import AdapterManifest
from rfcv.domains.rfc_protocol.rules import RULE_SET
from rfcv.domains.rfc_protocol.runtime import ProtocolRuntime
from rfcv.domains.rfc_protocol.schemas import TASKS

# Trường do hub cấp cho mọi vai trò (execution_loop._shared_context và _dispatch) hoặc riêng cho Planner (_plan).
HUB_FIELDS = {
    "task.focus",
    "requirement.rtype",
    "evidence.summary",
    "verdict.sufficiency",
    "critique.latest",
    "tasks.history",
    "budget.left",
}

# Khoảng trống năng lực đã biết: vai trò khai báo nhưng chưa có nguồn cung cấp.
KNOWN_UNSUPPLIED = {
    "rfc.sentence",  # chưa có nguồn RFC cho từng yêu cầu (RFC Analyst chưa cài)
    "rfc.paragraph",
    "rfc.context_pack",
    "rfc.sentence_group",
    "rfc.definitions",
    "rfc.errata",
    "rfc.version_diff",
    "examples.similar_scenarios",
    "task.recheck_location",  # RECHECK chưa mang vị trí cần xem lại
    "task.scope",
    "adapter.component_taxonomy",
    "adapter.locator_hints",
    "adapter.dsl_reference",
    "adapter.rbs_grammar_ref",
    "verdict.record",
    "evidence.cited",
}

UNAVAILABLE_TASKS = {"MAP_COMPONENTS", "STATIC_QUERY"}  # có trong danh mục nhưng chưa có handler

PINNED_RULES_VERSION = "sha256:e723d7809280ea66b9d05f4698c1f56beb78ce503bd143e8748f9235374ad9ea"


def _domain_fields(manifest: AdapterManifest) -> set[str]:
    rt = SimpleNamespace(manifest=manifest)
    invs = ProtocolRuntime().investigations(rt, ADAPTER_DIR / "examples")
    assert invs
    return set(invs[0].context)


def _profiles() -> dict[str, dict[str, Any]]:
    return {p.parent.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(AGENTS_DIR.glob("*/role.yaml"))}


@pytest.mark.parametrize("role", sorted(_profiles()))
def test_every_declared_context_field_is_supplied_or_knowingly_missing(role: str, manifest: AdapterManifest) -> None:
    declared = set(_profiles()[role]["context_fields"])
    supplied = HUB_FIELDS | _domain_fields(manifest)
    unexplained = declared - supplied - KNOWN_UNSUPPLIED
    assert not unexplained, f"{role} khai báo trường không ai cấp: {sorted(unexplained)}"


def test_known_unsupplied_list_has_no_stale_entries(manifest: AdapterManifest) -> None:
    """Một trường đã được cấp rồi thì phải bị gỡ khỏi danh sách khoảng trống."""
    supplied = HUB_FIELDS | _domain_fields(manifest)
    assert not (KNOWN_UNSUPPLIED & supplied)
    declared = {f for p in _profiles().values() for f in p["context_fields"]}
    assert declared >= KNOWN_UNSUPPLIED, "mục thừa trong KNOWN_UNSUPPLIED: không vai trò nào khai báo"


def test_critic_and_test_agent_see_the_evidence_state() -> None:
    """Phản biện mà không thấy bằng chứng, hay Test không biết còn thiếu biến thể nào, thì không phối hợp được."""
    profiles = _profiles()
    for role in ("verifier", "test"):
        assert {"evidence.summary", "verdict.sufficiency"} <= set(profiles[role]["context_fields"]), role
    assert "task.focus" in profiles["test"]["context_fields"]


def test_every_catalog_task_has_a_handler_or_is_a_known_gap(manifest: AdapterManifest) -> None:
    rt = SimpleNamespace(
        manifest=manifest,
        run_id="r",
        trace=None,
        store=None,
        artifacts=None,
        seed=0,
        providers=SimpleNamespace(code_index=None, backend=None, sut_launcher=None, executor=None),
    )
    handled = set(ProtocolRuntime().handlers(rt))
    missing = {t.name for t in TASKS} - handled
    assert missing == UNAVAILABLE_TASKS, f"khoảng trống năng lực đã đổi: {sorted(missing)}"


def test_rule_set_version_is_pinned() -> None:
    """Bước phối hợp không được đổi bộ quy tắc. Đổi quy tắc là có chủ đích: cập nhật hash này cùng bảng vàng nhãn."""
    assert RULE_SET.version == PINNED_RULES_VERSION

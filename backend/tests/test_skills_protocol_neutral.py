"""Skill lõi không được phụ thuộc giao thức: tri thức riêng của TLS, DNS, QUIC... nằm trong skills/<adapter>/.

Skill trong skills/core được cấp cho agent ở MỌI adapter, nên một ví dụ hay con số của một giao thức ở đây sẽ dạy sai agent khi
kiểm giao thức khác. Agent nhận skill giao thức qua khai báo "@adapter" trong role.yaml, không gọi tên skill của giao thức nào.
"""

from __future__ import annotations

import re

import pytest
import yaml

from conftest import AGENTS_DIR, ROOT
from rfcv.core.skills import ADAPTER_SKILLS, default_registry

PROTOCOL_WORDS = re.compile(
    r"\b(TLS|DTLS|SSL|DNS|EDNS|QUIC|HTTP/?[23]?|HPACK|SSH|wolfSSL|OpenSSL|BoringSSL|rustls|record_overflow|"
    r"ClientHello|ServerHello|RFC\s?\d{3,5})\b",
    re.IGNORECASE,
)
CORE = sorted((ROOT / "skills" / "core").rglob("*.md"))


@pytest.mark.parametrize("path", CORE, ids=lambda p: p.parent.name + "/" + p.name)
def test_core_skills_do_not_depend_on_a_protocol(path) -> None:  # type: ignore[no-untyped-def]
    hits = sorted({m.group(0) for m in PROTOCOL_WORDS.finditer(path.read_text(encoding="utf-8"))})
    assert not hits, f"{path.parent.name}: nhắc giao thức {hits}; chuyển nội dung này sang skills/<adapter>/"


def test_agent_profiles_do_not_name_protocol_skills() -> None:
    """role.yaml chỉ gọi tên skill lõi; skill của giao thức đến qua "@adapter", nên thêm giao thức không phải sửa agent."""
    core_names = {p.parent.name for p in (ROOT / "skills" / "core").glob("*/SKILL.md")}
    for role_yaml in sorted(AGENTS_DIR.glob("*/role.yaml")):
        skills = yaml.safe_load(role_yaml.read_text(encoding="utf-8")).get("skills", [])
        named = [s for s in skills if s != ADAPTER_SKILLS]
        assert set(named) <= core_names, f"{role_yaml.parent.name} gọi tên skill ngoài core: {set(named) - core_names}"


def test_adapter_skills_reach_agents_by_task_type_only() -> None:
    reg = default_registry(ROOT / "skills", "tls13")
    reader = reg.select(["resolve-c-macro-thresholds", ADAPTER_SKILLS], "LOCATE")
    tester = reg.select([ADAPTER_SKILLS], "SELECT_TESTS")
    assert "tls-record-length-bounds" in reader and "write-tlsfuzzer-scenarios" not in reader
    assert tester == ["write-tlsfuzzer-scenarios"]
    assert reg.select([ADAPTER_SKILLS], "LOCATE") and not default_registry(ROOT / "skills", None).select(
        [ADAPTER_SKILLS], "LOCATE"
    )  # không có adapter thì "@adapter" không mang lại gì

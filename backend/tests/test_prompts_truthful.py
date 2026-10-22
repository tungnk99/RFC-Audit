"""Lời nhắc và skill chỉ được nói về những gì agent thật sự có (công cụ, trường ngữ cảnh), và ví dụ trong đó phải đúng.

Lỗi từng gặp: năm lời nhắc hứa những công cụ không có mã cài đặt và những trường ngữ cảnh không ai cấp, nên agent được dạy một
quy trình không thể làm. Test này đối chiếu chữ trong lời nhắc với hồ sơ vai trò.
"""

from __future__ import annotations

import re

import pytest
import yaml

from conftest import AGENTS_DIR, ROOT
from rfcv.domains.rfc_protocol.spec.rbs import parse_rbs

TOOL_MENTION = re.compile(r"`([a-z]+__[a-z_]+)")
ROLES = sorted(p.parent.name for p in AGENTS_DIR.glob("*/role.yaml"))


def profile(role: str) -> dict:  # type: ignore[type-arg]
    return yaml.safe_load((AGENTS_DIR / role / "role.yaml").read_text(encoding="utf-8"))


def prompt(role: str) -> str:
    return (AGENTS_DIR / role / "prompt.md").read_text(encoding="utf-8")


ALL_FIELDS = {f for r in ROLES for f in profile(r)["context_fields"]}


@pytest.mark.parametrize("role", ROLES)
def test_a_prompt_names_only_tools_its_role_may_call(role: str) -> None:
    allowed = {t.replace(".", "__") for t in profile(role)["tools"]}
    named = set(TOOL_MENTION.findall(prompt(role)))
    assert named <= allowed, f"{role} nhắc công cụ không có trong role.yaml: {sorted(named - allowed)}"


@pytest.mark.parametrize("role", ROLES)
def test_a_prompt_names_only_context_fields_its_role_receives(role: str) -> None:
    """Một trường ngữ cảnh mà vai trò khác có nhưng vai trò này không khai báo thì không được nói tới như đầu vào."""
    declared = set(profile(role)["context_fields"])
    named = {f for f in ALL_FIELDS if f"`{f}`" in prompt(role)}
    assert named <= declared, f"{role} nhắc trường không được cấp: {sorted(named - declared)}"


def test_a_skill_names_only_tools_of_the_roles_that_load_it() -> None:
    users: dict[str, set[str]] = {}
    adapter_skills = {p.parent.name for p in (ROOT / "skills").glob("*/*/SKILL.md") if p.parent.parent.name != "core"}
    for role in ROLES:
        declared = set(profile(role).get("skills", []))
        reached = (declared - {"@adapter"}) | (adapter_skills if "@adapter" in declared else set())
        for skill in reached:
            users.setdefault(skill, set()).update(t.replace(".", "__") for t in profile(role)["tools"])
    for skill_md in sorted((ROOT / "skills").rglob("SKILL.md")):
        name = skill_md.parent.name
        named = set(TOOL_MENTION.findall(skill_md.read_text(encoding="utf-8")))
        allowed = users.get(name, set())
        assert named <= allowed, f"skill {name} nhắc công cụ mà vai trò dùng nó không có: {sorted(named - allowed)}"


def test_the_rbs_example_in_the_rfc_analyst_prompt_is_valid_rbs() -> None:
    text = prompt("rfc_analyst").split("# 7. Ví dụ", 1)[1]
    block = text.split("```", 2)[1]
    rbs = parse_rbs(block.strip())
    assert (rbs.requirement_id, rbs.rtype, rbs.modal) == ("TLS13-0042", "B", "MUST")


def test_the_planner_prompt_still_carries_the_generated_playbook() -> None:
    text = prompt("planner")
    assert "<!-- playbook:begin -->" in text and "<!-- playbook:end -->" in text

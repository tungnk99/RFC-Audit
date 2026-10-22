"""Hồ sơ và lời nhắc agent là DỮ LIỆU ngoài mã nguồn (`agents/`). Dữ liệu không đổi được kiến trúc và không bao giờ chạy như mã."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from conftest import AGENTS_DIR, ROOT
from rfcv.core.policy import AGENTS_ENV, PolicyError, PolicyStore, find_agents_root
from rfcv.core.prompts import prompts_digest, role_prompt
from rfcv.plugins import current_registry

REAL = ROOT / "agents"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Bản sao của agents/ để sửa thử mà không đụng bản thật."""
    dst = tmp_path / "agents"
    shutil.copytree(REAL, dst, ignore=shutil.ignore_patterns("README.md"))
    return dst


def load(path: Path | None = None) -> PolicyStore:
    return PolicyStore.load(None, current_registry(), "rfc_protocol", path)


def edit_role(root: Path, name: str, **changes: object) -> Path:
    file = root / name / "role.yaml"
    data = yaml.safe_load(file.read_text(encoding="utf-8"))
    data.update(changes)
    file.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return file


def test_the_repository_agents_directory_holds_all_seven_llm_roles() -> None:
    store = load(REAL)
    assert set(store.roles) == {"rfc_analyst", "planner", "tester", "verifier", "report", "code_indexer", "code_reader"}
    for role in store.roles:
        assert role_prompt(store, role).strip()


def test_default_lookup_finds_the_repository_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(AGENTS_ENV, raising=False)
    assert find_agents_root().resolve() == REAL.resolve()
    assert load().roles == load(REAL).roles


def test_environment_variable_selects_the_directory(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setenv(AGENTS_ENV, str(root))
    assert find_agents_root() == root


def test_editing_a_prompt_changes_the_agent_and_the_digests(root: Path) -> None:
    base = load(root)
    before = prompts_digest(base, base.roles)
    (root / "planner" / "prompt.md").write_text("Lời nhắc Planner tuỳ chỉnh 2.", encoding="utf-8")
    custom = load(root)
    assert role_prompt(custom, "planner") == "Lời nhắc Planner tuỳ chỉnh 2."
    assert role_prompt(custom, "verifier") == role_prompt(base, "verifier")
    assert prompts_digest(custom, custom.roles) != before


def test_editing_a_profile_changes_the_policy_digest(root: Path) -> None:
    base = load(root)
    edit_role(root, "code_reader", budget_per_task={"llm_calls": 5, "tool_calls": 9, "tokens": 50000, "seconds": 90})
    custom = load(root)
    assert custom.profile("code_reader").budget_per_task.tool_calls == 9
    assert custom.digest != base.digest


def test_data_cannot_change_the_trust_zone(root: Path) -> None:
    edit_role(root, "code_reader", zone="privileged")
    with pytest.raises(PolicyError, match="vùng tin cậy"):
        load(root)


def test_data_cannot_change_the_output_schema(root: Path) -> None:
    edit_role(root, "planner", output_schema="Critique@1")
    with pytest.raises(PolicyError, match="schema đầu ra"):
        load(root)


def test_zone_rules_still_apply_to_tools(root: Path) -> None:
    """Agent đặc quyền không được mượn công cụ đọc dữ liệu không tin cậy qua dữ liệu cấu hình."""
    edit_role(root, "planner", tools=["registry.read", "locator.suggest"])
    with pytest.raises(PolicyError, match="không tin cậy"):
        load(root)


def test_unknown_tools_are_rejected(root: Path) -> None:
    edit_role(root, "tester", tools=["shell.exec"])
    with pytest.raises(PolicyError, match="không có trong danh mục"):
        load(root)


def test_folder_name_must_match_the_role(root: Path) -> None:
    edit_role(root, "planner", role="verifier")
    with pytest.raises(PolicyError, match="trùng tên thư mục"):
        load(root)


def test_a_missing_agent_profile_is_an_error(root: Path) -> None:
    shutil.rmtree(root / "report")
    with pytest.raises(PolicyError, match="thiếu"):
        load(root)


def test_a_missing_prompt_file_is_an_error(root: Path) -> None:
    (root / "verifier" / "prompt.md").unlink()
    with pytest.raises(PolicyError, match="thiếu lời nhắc"):
        load(root)


def test_a_folder_without_a_profile_is_an_error(root: Path) -> None:
    (root / "stranger").mkdir()
    with pytest.raises(PolicyError, match=r"thiếu role\.yaml"):
        load(root)


def test_python_files_in_the_data_directory_are_never_loaded(root: Path) -> None:
    marker = root.parent / "executed"
    for name in ("handler.py", "__init__.py", "schema.py"):
        (root / "planner" / name).write_text(f"open(r'{marker}', 'w').write('x')\n", encoding="utf-8")
    load(root)
    assert not marker.exists()


def test_no_agent_limits_the_number_of_llm_calls_but_every_other_budget_stays() -> None:
    """Không giới hạn lượt gọi LLM (`llm_calls` bỏ trống = None): một lần Code Reader dính giới hạn 20 lượt làm mất vị trí mã
    và hạ mức bảo đảm. Token, công cụ và thời gian vẫn chặn chạy lan man, nên mọi vai trò vẫn có ba giới hạn đó."""
    from rfcv.core.policy import TaskBudget

    assert TaskBudget(tool_calls=1, tokens=1, seconds=1).llm_calls is None
    profiles = {
        d.name: yaml.safe_load((d / "role.yaml").read_text(encoding="utf-8"))
        for d in AGENTS_DIR.iterdir()
        if (d / "role.yaml").is_file()
    }
    assert len(profiles) == 7
    for role, profile in profiles.items():
        budget = profile["budget_per_task"]
        assert "llm_calls" not in budget, role
        assert all(isinstance(budget[k], int) and budget[k] > 0 for k in ("tool_calls", "tokens", "seconds")), role

"""Bố cục theo agent: mỗi agent một thư mục, khai báo `wired` phải khớp với thực tế, không có agent nào chỉ nằm trên giấy mà không ai biết."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import yaml
from typer.testing import CliRunner

from agents.registry import AGENTS
from conftest import AGENTS_DIR
from rfcv.adapters.manifest import AdapterManifest
from rfcv.domains.rfc_protocol import REQUIRED_ROLES
from rfcv.domains.rfc_protocol.runtime import ProtocolRuntime
from rfcv.domains.rfc_protocol.schemas import DOMAIN_SCHEMAS, TASKS
from rfcv.plugins import current_registry
from rfcv.ui.cli import app

DOMAIN_DIR = Path(__file__).resolve().parents[1] / "src" / "rfcv" / "domains" / "rfc_protocol"
EXPECTED = {
    "rfc_analyst",
    "planner",
    "test",
    "verifier",
    "report",
    "code_indexer",
    "code_reader",
}  # bảy agent + locator


def by_name() -> dict[str, object]:
    return {a.name: a for a in AGENTS}


def test_the_seven_documented_agents_plus_the_deterministic_locator_are_declared() -> None:
    assert {a.name for a in AGENTS} == EXPECTED | {"locator"}
    assert set(REQUIRED_ROLES) == EXPECTED


def test_every_agent_is_one_folder_holding_its_code_and_its_data() -> None:
    """Mỗi agent một thư mục ở agents/: mã (schema, handler, SPEC) cùng hồ sơ và lời nhắc."""
    for a in AGENTS:
        folder = AGENTS_DIR / a.name
        assert (folder / "__init__.py").is_file(), a.name
        if not a.has_role:
            assert a.name == "locator" and not (folder / "role.yaml").exists()  # tất định, không LLM
            continue
        role = yaml.safe_load((folder / "role.yaml").read_text(encoding="utf-8"))
        assert (role["role"], role["zone"], role["output_schema"]) == (a.name, a.zone, a.output_schema)
        assert (AGENTS_DIR / a.name / role["prompt"]).is_file()


def test_the_old_flat_role_and_prompt_directories_are_gone() -> None:
    assert not (DOMAIN_DIR / "roles").exists() and not (DOMAIN_DIR / "prompts").exists()


def test_every_task_is_owned_by_exactly_the_agent_it_targets() -> None:
    seen: set[str] = set()
    for a in AGENTS:
        for t in a.tasks:
            assert t.target_role == a.name, (a.name, t.name)
            assert t.name not in seen
            seen.add(t.name)
    assert seen == {t.name for t in TASKS} == set(current_registry().tasks)


def test_declared_output_schemas_are_registered() -> None:
    reg = current_registry()
    for a in AGENTS:
        for name, model in a.schemas.items():
            assert reg.schemas[name] is model
    assert set(DOMAIN_SCHEMAS) <= set(reg.schemas)


def test_wired_flag_matches_the_handlers_that_really_exist(manifest: AdapterManifest) -> None:
    """Agent nhận nhiệm vụ mà wired=True thì mọi nhiệm vụ của nó phải có handler, và ngược lại wired=False thì ít nhất một nhiệm vụ không có."""
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
    for a in AGENTS:
        if not a.tasks:
            continue
        have = all(t.name in handled for t in a.tasks)
        assert a.wired == have, f"{a.name}: wired={a.wired} nhưng handler đủ={have}"


def test_agents_outside_the_task_flow_are_declared_as_such() -> None:
    specs = {a.name: a for a in AGENTS}
    assert specs["planner"].wired and specs["planner"].stage == "planning"
    assert not specs["rfc_analyst"].wired and specs["rfc_analyst"].stage == "pre"
    assert not specs["report"].wired and specs["report"].stage == "post"


def test_agents_command_lists_every_agent_and_names_the_unwired_ones() -> None:
    result = CliRunner().invoke(app, ["agents"])
    assert result.exit_code == 0
    for name in EXPECTED | {"locator"}:
        assert name in result.output
    assert "Chưa nối vào luồng chạy" in result.output and "rfc_analyst" in result.output
    data = json.loads(CliRunner().invoke(app, ["agents", "--json"]).output)
    assert {r["agent"]: r["wired"] for r in data}["code_reader"] is True

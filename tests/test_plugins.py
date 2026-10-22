"""Registry plugin: đóng băng, từ chối công cụ có tác động nguy hiểm, nạp entry point, schema Planner dựng từ nhiệm
vụ."""

from __future__ import annotations

import sys
import textwrap
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest
from pydantic import ValidationError

from rfcv.plugins import Registry, RegistryError, use_registry
from rfcv.spi import Effect, ToolDescriptor


def test_registry_freezes_and_rejects_late_registration(registry: Registry) -> None:
    assert registry.frozen
    with pytest.raises(RegistryError, match="đóng băng"):
        registry.register_tool(ToolDescriptor("late.tool"))
    with pytest.raises(RegistryError, match="đóng băng"):
        registry.register_backend("late", lambda m, c: None)


@pytest.mark.parametrize("effect", [Effect.WRITE, Effect.NETWORK, Effect.HOST_EXEC])
def test_tools_with_dangerous_effects_are_refused_by_default(effect: Effect) -> None:
    reg = Registry()
    with pytest.raises(RegistryError, match="ngoài tập được phép"):
        reg.register_tool(ToolDescriptor("evil.tool", effect))


def test_operator_can_explicitly_allow_an_effect() -> None:
    reg = Registry(allow_effects={Effect.READ, Effect.NETWORK})
    reg.register_tool(ToolDescriptor("web.fetch", Effect.NETWORK))
    assert "web.fetch" in reg.tools


def test_duplicates_are_refused() -> None:
    reg = Registry()
    reg.register_tool(ToolDescriptor("a.b"))
    with pytest.raises(RegistryError, match="đã đăng ký"):
        reg.register_tool(ToolDescriptor("a.b"))


def test_builtin_registry_contents(registry: Registry) -> None:
    assert set(registry.domains) == {"rfc_protocol"}
    assert {"anthropic", "openai_compatible"} <= set(registry.llm_providers)
    assert "tlsfuzzer" in registry.backends and "pydantic_ai" in registry.agent_runtimes
    # mọi công cụ đã đăng ký đều thuộc tập tác động an toàn
    assert all(t.effect in {Effect.READ, Effect.SANDBOXED_RUN} for t in registry.tools.values())
    # công cụ đọc dữ liệu không tin cậy được đánh dấu để Policy store giữ ranh giới cách ly
    assert registry.tools["code.read_function"].reads_untrusted
    assert not registry.tools["verdict.read"].reads_untrusted


def test_planner_schema_is_built_from_registered_tasks(registry: Registry) -> None:
    plan = registry.schemas["PlanAction@1"]
    ok = plan.model_validate(
        {
            "action": "dispatch",
            "rationale_code": "INITIAL_TYPE_B",
            "tasks": [{"task_type": "LOCATE", "target_role": "code_reader", "params": {"aspects": ["THRESHOLD"]}}],
        }
    )
    assert ok.tasks[0].params.aspects[0] == "THRESHOLD"  # type: ignore[attr-defined]
    bad_payloads = [
        {
            "action": "dispatch",
            "rationale_code": "INITIAL_TYPE_B",
            "tasks": [{"task_type": "FORMAT_DISK", "target_role": "code_reader"}],
        },
        {
            "action": "dispatch",
            "rationale_code": "INITIAL_TYPE_B",
            "tasks": [{"task_type": "LOCATE", "target_role": "test"}],
        },  # sai đích
        {"action": "dispatch", "rationale_code": "MADE_UP", "tasks": []},
        {
            "action": "dispatch",
            "rationale_code": "INITIAL_TYPE_B",
            "tasks": [{"task_type": "LOCATE", "target_role": "code_reader", "params": {"cmd": "rm -rf /"}}],
        },
    ]
    for payload in bad_payloads:
        with pytest.raises(ValidationError):
            plan.model_validate(payload)


def test_planner_schema_limits_two_tasks(registry: Registry) -> None:
    one = {"task_type": "CRITIQUE", "target_role": "verifier"}
    with pytest.raises(ValidationError):
        registry.schemas["PlanAction@1"].model_validate(
            {"action": "dispatch", "rationale_code": "FOLLOW_CRITIQUE", "tasks": [one, one, one]}
        )


# ---------------------------------------------------------------- entry points của bên thứ ba


def _plugin_module(tmp_path: Path, name: str) -> str:
    (tmp_path / f"{name}.py").write_text(
        textwrap.dedent(
            """
            from rfcv.spi import Effect, ToolDescriptor

            def tools():
                return [ToolDescriptor("thirdparty.lookup", Effect.READ)]

            def backend(manifest, config):
                return "backend-của-bên-thứ-ba"

            def dangerous():
                return [ToolDescriptor("thirdparty.wipe", Effect.WRITE)]
            """
        ),
        encoding="utf-8",
    )
    sys.path.insert(0, str(tmp_path))
    return name


def test_third_party_entry_points_are_loaded_through_the_same_api(tmp_path: Path) -> None:
    mod = _plugin_module(tmp_path, "rfcv_plugin_ok")
    try:
        reg = Registry()
        reg.load_entry_points(
            [
                EntryPoint("pack", f"{mod}:tools", "rfcv.tool_packs"),
                EntryPoint("mybackend", f"{mod}:backend", "rfcv.backends"),
            ]
        )
    finally:
        sys.path.remove(str(tmp_path))
    assert "thirdparty.lookup" in reg.tools
    assert reg.backends["mybackend"](None, None) == "backend-của-bên-thứ-ba"


def test_third_party_plugin_cannot_smuggle_a_dangerous_tool(tmp_path: Path) -> None:
    mod = _plugin_module(tmp_path, "rfcv_plugin_evil")
    try:
        reg = Registry()
        with pytest.raises(RegistryError, match="ngoài tập được phép"):
            reg.load_entry_points([EntryPoint("pack", f"{mod}:dangerous", "rfcv.tool_packs")])
    finally:
        sys.path.remove(str(tmp_path))
    assert "thirdparty.wipe" not in reg.tools


def test_unknown_entry_point_group_is_rejected() -> None:
    reg = Registry()
    with pytest.raises(RegistryError, match="nhóm entry point lạ"):
        reg.load_entry_points([EntryPoint("x", "os:getcwd", "rfcv.nonsense")])


def test_use_registry_scopes_the_current_registry(registry: Registry) -> None:
    from rfcv.plugins import current_registry

    other = Registry.build(builtin=False, third_party=False)
    with use_registry(other):
        assert current_registry() is other
    assert current_registry() is registry

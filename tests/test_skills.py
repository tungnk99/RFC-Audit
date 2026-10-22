"""Agent Skills theo chuẩn agentskills.io: kiểm định, giam đường dẫn, chọn tất định, nạp dần trong runtime."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.workspaces import WorkspaceReadOnlyError

from conftest import ROOT
from rfcv.agents.schemas import PlanAction
from rfcv.core.envelope import EnvelopeFactory, MessageKind
from rfcv.core.llm_gateway import LLMGateway, ModelsConfig
from rfcv.core.policy import PolicyStore
from rfcv.core.skills import SkillRegistry, default_registry, validate_library
from rfcv.core.trace import TraceLog
from rfcv.gates.tool_gateway import ToolGateway, ToolSession
from rfcv.runtime.pydantic_ai import PydanticAIRoleRunner, SkillLibraryWorkspace, skills_capability

ROLES = ["code_reader", "planner", "verifier", "test"]
TASKS = ["LOCATE", "RECHECK", "CRITIQUE", "SELECT_TESTS"]


def write_skill(
    lib: Path, name: str, *, front: str | None = None, body: str = "Hello.", extra: dict[str, str] | None = None
) -> Path:
    d = lib / name
    d.mkdir(parents=True)
    fm = (
        front
        if front is not None
        else f"name: {name}\ndescription: Does a thing. Use when testing.\nmetadata:\n  rfcv-roles: code_reader\n"
    )
    (d / "SKILL.md").write_text(f"---\n{fm}---\n{body}\n", encoding="utf-8")
    for rel, content in (extra or {}).items():
        f = d / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")
    return d


# ------------------------------------------------------------ thư viện thật của dự án


def test_project_skills_are_valid_and_scoped() -> None:
    reg = default_registry(ROOT / "skills", "tls13")
    assert {"resolve-c-macro-thresholds", "check-ifdef-compiled-lines", "tls-record-length-bounds"} <= set(reg.skills)
    # Agent đặc quyền không thấy skill đọc mã của vùng cách ly
    assert reg.select("planner") == ["summarize-evidence-for-planner"]
    assert "resolve-c-macro-thresholds" not in reg.select("verifier")
    assert "write-tlsfuzzer-scenarios" in reg.select("test")
    # Chọn theo kiểu nhiệm vụ
    assert "trace-all-entry-paths" in reg.select("code_reader", "TRACE_PATHS")
    assert "resolve-c-macro-thresholds" not in reg.select("code_reader", "TRACE_PATHS")  # chỉ LOCATE, RECHECK
    assert "resolve-c-macro-thresholds" in reg.select("code_reader", "RECHECK")
    assert reg.select("code_reader", "LOCATE") == reg.select("code_reader", "LOCATE")  # tất định


def test_digest_changes_when_a_skill_changes(tmp_path: Path) -> None:
    write_skill(tmp_path / "core", "alpha")
    d1 = SkillRegistry({"core": tmp_path / "core"}, ROLES, TASKS).digest
    skill_md = tmp_path / "core" / "alpha" / "SKILL.md"
    skill_md.write_text(skill_md.read_text(encoding="utf-8") + "\nNew rule.\n", encoding="utf-8")
    assert SkillRegistry({"core": tmp_path / "core"}, ROLES, TASKS).digest != d1


# ------------------------------------------------------------ kiểm định theo chuẩn và ràng buộc rfcv


@pytest.mark.parametrize(
    ("front", "needle"),
    [
        ("name: Alpha\ndescription: d\nmetadata:\n  rfcv-roles: code_reader\n", "name"),
        ("name: a--b\ndescription: d\nmetadata:\n  rfcv-roles: code_reader\n", "name"),
        ("name: other\ndescription: d\nmetadata:\n  rfcv-roles: code_reader\n", "trùng tên thư mục"),
        ("name: alpha\nmetadata:\n  rfcv-roles: code_reader\n", "description"),
        ("name: alpha\ndescription: ''\nmetadata:\n  rfcv-roles: code_reader\n", "description"),
        ("name: alpha\ndescription: d\n", "rfcv-roles"),
        ("name: alpha\ndescription: d\nmetadata:\n  rfcv-roles: hacker\n", "vai trò lạ"),
        (
            "name: alpha\ndescription: d\nmetadata:\n  rfcv-roles: code_reader\n  rfcv-task-types: DROP_TABLE\n",
            "nhiệm vụ lạ",
        ),
        (
            "name: alpha\ndescription: d\nallowed-tools: Bash(rm:*)\nmetadata:\n  rfcv-roles: code_reader\n",
            "allowed-tools",
        ),
        ("name: alpha\ndescription: d\nmetadata:\n  rfcv-roles: 1\n", "metadata"),
    ],
)
def test_invalid_frontmatter_is_rejected(tmp_path: Path, front: str, needle: str) -> None:
    write_skill(tmp_path, "alpha", front=front)
    result = validate_library(tmp_path, ROLES, TASKS)
    assert not result.skills and any(needle in e for e in result.errors), result.errors


def test_scripts_directory_is_forbidden(tmp_path: Path) -> None:
    """Rủi ro A3: skill chỉ là hướng dẫn, không có mã chạy được."""
    write_skill(tmp_path, "alpha", extra={"scripts/run.sh": "rm -rf /"})
    result = validate_library(tmp_path, ROLES, TASKS)
    assert not result.skills and any("scripts" in e for e in result.errors)


def test_body_length_and_references_shape(tmp_path: Path) -> None:
    write_skill(tmp_path, "long", body="\n".join(["line"] * 600))
    write_skill(tmp_path, "deep", extra={"references/sub/x.md": "x"})
    write_skill(tmp_path, "badref", extra={"references/run.py": "print(1)"})
    errors = validate_library(tmp_path, ROLES, TASKS).errors
    assert any("vượt 500" in e for e in errors)
    assert any("references/sub" in e for e in errors)
    assert any("run.py" in e for e in errors)


def test_registry_rejects_duplicates_across_libraries(tmp_path: Path) -> None:
    write_skill(tmp_path / "core", "alpha")
    write_skill(tmp_path / "tls", "alpha")
    with pytest.raises(ValueError, match="trùng tên"):
        SkillRegistry({"core": tmp_path / "core", "tls": tmp_path / "tls"}, ROLES, TASKS)


# ------------------------------------------------------------ workspace chỉ đọc, giam đường dẫn


async def test_workspace_is_read_only_and_jailed(tmp_path: Path) -> None:
    lib = tmp_path / "core"
    write_skill(lib, "alpha")
    (tmp_path / "secret.txt").write_text("TOP SECRET", encoding="utf-8")
    ws = SkillLibraryWorkspace({"core": lib})
    assert b"Hello." in await ws.read_bytes("/skills/core/alpha/SKILL.md")
    for escape in (
        "/skills/core/../secret.txt",
        "/skills/core/alpha/../../secret.txt",
        "/etc/passwd",
        "/skills/nope/x",
    ):
        with pytest.raises(FileNotFoundError):
            await ws.read_bytes(escape)
    with pytest.raises(WorkspaceReadOnlyError):
        await ws.write_bytes("/skills/core/alpha/SKILL.md", b"pwned")
    with pytest.raises(WorkspaceReadOnlyError):
        await ws.remove("/skills/core/alpha")
    assert not hasattr(ws, "run"), "workspace của skill không được có khả năng chạy lệnh"
    assert {e.name for e in await ws.list_dir("/skills")} == {"core"}


def test_read_reference_is_one_level_and_confined(tmp_path: Path) -> None:
    write_skill(tmp_path / "core", "alpha", extra={"references/guide.md": "GUIDE"})
    (tmp_path / "core" / "outside.md").write_text("OUT", encoding="utf-8")
    reg = SkillRegistry({"core": tmp_path / "core"}, ROLES, TASKS)
    assert reg.read_reference("alpha", "references/guide.md") == "GUIDE"
    for bad in ("references/../SKILL.md", "../outside.md", "SKILL.md", "references/sub/x.md"):
        with pytest.raises(FileNotFoundError):
            reg.read_reference("alpha", bad)


# ------------------------------------------------------------ chạy trong agent (nạp dần)


def test_progressive_disclosure_in_agent(tmp_path: Path) -> None:
    import asyncio

    write_skill(tmp_path / "core", "alpha", body="BODY_ONLY_AFTER_LOAD")
    reg = SkillRegistry({"core": tmp_path / "core"}, ROLES, TASKS)
    seen: dict[str, str] = {}

    def fn(messages: list, info: AgentInfo) -> ModelResponse:  # type: ignore[type-arg]
        last = messages[-1].parts[-1]
        if isinstance(last, ToolReturnPart):
            seen["loaded"] = str(last.content)
            return ModelResponse(parts=[TextPart("done")])
        seen["catalog"] = info.instructions or ""
        return ModelResponse(parts=[ToolCallPart("load_capability", {"id": "alpha"})])

    asyncio.run(Agent(FunctionModel(fn)).run("go", capabilities=[skills_capability(reg, "code_reader", "LOCATE")]))
    assert "alpha: Does a thing" in seen["catalog"]  # chỉ tên và mô tả lúc đầu
    assert "BODY_ONLY_AFTER_LOAD" not in seen["catalog"]
    assert "BODY_ONLY_AFTER_LOAD" in seen["loaded"]  # thân chỉ vào ngữ cảnh sau khi nạp


def test_role_without_matching_skill_gets_no_capability(tmp_path: Path) -> None:
    write_skill(tmp_path / "core", "alpha")
    reg = SkillRegistry({"core": tmp_path / "core"}, ROLES, TASKS)
    assert skills_capability(reg, "planner") is None
    assert skills_capability(reg, "code_reader") is not None


async def test_runner_logs_offered_and_loaded_skills(policy: PolicyStore, trace: TraceLog, tmp_path: Path) -> None:
    reg = default_registry(ROOT / "skills", "tls13")

    def fn(messages: list, info: AgentInfo) -> ModelResponse:  # type: ignore[type-arg]
        last = messages[-1].parts[-1]
        if isinstance(last, ToolReturnPart) and last.tool_name == "load_capability":
            return ModelResponse(
                parts=[ToolCallPart("final_result", {"action": "stop", "rationale_code": "INFEASIBLE", "tasks": []})]
            )
        return ModelResponse(parts=[ToolCallPart("load_capability", {"id": "summarize-evidence-for-planner"})])

    llm = LLMGateway(ModelsConfig(roles={}), env={}, overrides={"planner": FunctionModel(fn)})
    runner = PydanticAIRoleRunner(policy, ToolGateway(policy, trace), llm, trace, skills=reg)
    env = EnvelopeFactory("run-test").make(
        requirement_id="TLS13-0042",
        from_role="execution_loop",
        to_role="planner",
        kind=MessageKind.DISPATCH,
        round=1,
        body={},
        budget_left={},
    )
    outcome = await runner.run(env, {}, ToolSession("run-test", "planner", "TLS13-0042", 4))
    assert isinstance(outcome.output, PlanAction)
    run = next(iter(trace.events("llm_run")))["payload"]
    assert run["skills_offered"] == ["summarize-evidence-for-planner"]
    assert run["skills_loaded"] == ["summarize-evidence-for-planner"]
    assert run["skills_digest"] == reg.digest


async def test_runner_without_skills_is_unchanged(policy: PolicyStore, trace: TraceLog) -> None:
    llm = LLMGateway(ModelsConfig(roles={}), env={}, overrides={"planner": TestModel()})
    runner = PydanticAIRoleRunner(policy, ToolGateway(policy, trace), llm, trace)
    env = EnvelopeFactory("run-test").make(
        requirement_id="TLS13-0042",
        from_role="execution_loop",
        to_role="planner",
        kind=MessageKind.DISPATCH,
        round=1,
        body={},
        budget_left={},
    )
    await runner.run(env, {}, ToolSession("run-test", "planner", "TLS13-0042", 4))
    run = next(iter(trace.events("llm_run")))["payload"]
    assert run["skills_offered"] == [] and run["skills_digest"] is None

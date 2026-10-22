"""Composition root: lắp ráp từ cấu hình và chạy ca K3 trọn luồng qua các cổng thật, chỉ thay LLM bằng kịch bản.

Agent giả gọi công cụ đọc mã qua Tool gateway thật (nên Schema gate thấy "dòng đã hiển thị"), trả đầu ra có cấu trúc,
rồi
handler của miền đưa qua Schema gate / Test driver / Coverage linker để ra bằng chứng và Verdict engine kết luận.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from conftest import ADAPTER_DIR, ROOT
from fakes import SCENARIO, FakeBackend, FakeExecutor, FakeLauncher, make_index
from rfcv.agents.schemas import Critique, PlanAction, TaskSpec
from rfcv.assembly import MissingProviderError, Providers, RuntimeConfig, build_runtime
from rfcv.core.envelope import Envelope
from rfcv.core.runner import RoleOutcome
from rfcv.domains.rfc_protocol.schemas import LocationClaim, TaskParams
from rfcv.evidence.verdict_engine import Label, StopReason
from rfcv.gates.tool_gateway import ToolSession
from rfcv.manifest import diff
from rfcv.plugins import Registry, use_registry

LOCATE = TaskSpec(task_type="LOCATE", target_role="code_reader", params=TaskParams(aspects=["CONDITION", "REACTION"]))  # type: ignore[list-item]
SELECT = TaskSpec(task_type="SELECT_TESTS", target_role="test")


class ScriptedRunner:
    """Thay LLM: mỗi vai trò làm đúng việc của nó, nhưng mọi công cụ vẫn đi qua Tool gateway thật."""

    def __init__(self) -> None:
        self.gateway: Any = None
        self.calls: list[str] = []

    async def run(self, envelope: Envelope, context: dict[str, Any], session: ToolSession) -> RoleOutcome:
        role = envelope.to_role
        self.calls.append(role)
        if role == "planner":
            # vòng 1: kiểm thử và định vị; sau đó dừng để hub kết luận
            first = self.calls.count("planner") == 1
            action = PlanAction(
                action="dispatch" if first else "stop",
                tasks=[SELECT, LOCATE] if first else [],
                rationale_code="INITIAL_TYPE_B" if first else "DECISIVE_VIOLATION",
            )
            return RoleOutcome(action, 10)
        if role == "test":
            return RoleOutcome(SCENARIO, 10)
        if role == "code_reader":
            await self.gateway.call(session, "code.read_range", {"file": "src/internal.c", "start": 810, "end": 830})
            claim = LocationClaim.model_validate(
                {
                    "file": "src/internal.c",
                    "symbol": "GetRecordHeader",
                    "line_start": 812,
                    "line_end": 816,
                    "check_kind": "LENGTH_BOUND",
                    "finding": "PRESENT",
                    "aspects": [
                        {"aspect": "CONDITION", "value": "MATCH", "observed": None, "lines": [812, 812]},
                        {
                            "aspect": "REACTION",
                            "value": "MISMATCH",
                            "observed": "send_alert(decode_error)",
                            "lines": [815, 815],
                        },
                    ],
                    "call_path": ["ProcessReply", "GetRecordHeader"],
                }
            )
            return RoleOutcome(claim, 10)
        if role == "verifier":
            return RoleOutcome(Critique(issues=[]), 5)
        raise AssertionError(f"vai trò không mong đợi: {role}")


def make_config(tmp_path: Path, **kw: Any) -> RuntimeConfig:
    return RuntimeConfig(
        adapter_dir=ADAPTER_DIR,
        run_dir=tmp_path / "runs",
        skills_root=ROOT / "skills",
        models_path=None,
        code_root=tmp_path / "repo",
        run_id="run-e2e",
        **kw,
    )


def make_providers(runner: ScriptedRunner, **overrides: Any) -> Providers:
    base: dict[str, Any] = {
        "backend": FakeBackend(buggy_impl="wolfssl"),
        "code_index": make_index(),
        "executor": FakeExecutor(),
        "sut_launcher": FakeLauncher(),
        "role_runner": runner,
    }
    return Providers(**{**base, **overrides})


async def test_k3_runs_end_to_end_to_violation(tmp_path: Path) -> None:
    runner = ScriptedRunner()
    rt = build_runtime(make_config(tmp_path), make_providers(runner))
    runner.gateway = rt.gateway
    try:
        verdicts = await rt.run_all(ADAPTER_DIR / "examples")
        # T3 (nhân chứng, chạy lại) và T1 (đã qua Schema gate) đều là bằng chứng thật trong kho, chuỗi hash nguyên vẹn
        kinds = [getattr(e.payload, "kind", "") for e in rt.store.for_requirement("TLS13-0042")]
        chain_ok = rt.store.verify_chain().ok
        stored = rt.store.latest_verdicts()["TLS13-0042"]["label"]
    finally:
        rt.close()

    assert len(verdicts) == 1
    v = verdicts[0]
    assert (v.label, v.rule, v.stop_reason) == (Label.VIOLATION, "V2", StopReason.SUFFICIENT)
    assert v.rules_version == rt.rules.version
    assert "scenario_result" in kinds and "location" in kinds
    assert chain_ok and stored == "VIOLATION"
    assert runner.calls[0] == "planner" and "test" in runner.calls and "code_reader" in runner.calls


def test_run_manifest_records_every_input_digest(tmp_path: Path) -> None:
    runner = ScriptedRunner()
    rt = build_runtime(make_config(tmp_path, seed=7), make_providers(runner))
    rt.close()
    written = json.loads((tmp_path / "runs" / "run-e2e" / "manifest.json").read_text(encoding="utf-8"))
    assert {"policy", "prompts", "models", "skills", "adapter", "rules", "registry"} <= set(written["digests"])
    assert written["domain"]["name"] == "rfc_protocol" and written["config"]["seed"] == 7
    assert written["inputs_digest"] == rt.run_manifest.inputs_digest
    assert written["digests"]["rules"] == rt.rules.version
    assert "pydantic-ai-slim" in written["packages"]


def test_manifest_inputs_digest_is_stable_and_diff_names_what_changed(tmp_path: Path) -> None:
    a = build_runtime(make_config(tmp_path / "a"), make_providers(ScriptedRunner()))
    b = build_runtime(make_config(tmp_path / "b"), make_providers(ScriptedRunner()))
    c = build_runtime(make_config(tmp_path / "c", enable_skills=False), make_providers(ScriptedRunner()))
    for rt in (a, b, c):
        rt.close()
    assert a.run_manifest.inputs_digest == b.run_manifest.inputs_digest
    assert a.run_manifest.inputs_digest != c.run_manifest.inputs_digest
    assert diff(a.run_manifest.to_json(), c.run_manifest.to_json()) == ["skills"]


def test_missing_providers_are_named_not_silently_skipped(tmp_path: Path) -> None:
    with pytest.raises(MissingProviderError) as exc:
        build_runtime(make_config(tmp_path), Providers(role_runner=ScriptedRunner()))
    assert set(exc.value.missing) == {"code_index", "executor", "sut_launcher"}  # backend tlsfuzzer có sẵn


def test_unknown_domain_in_adapter_is_rejected(tmp_path: Path) -> None:
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    text = (ADAPTER_DIR / "adapter.yaml").read_text(encoding="utf-8").replace("domain: rfc_protocol", "domain: nope")
    (adapter / "adapter.yaml").write_text(text, encoding="utf-8")
    cfg = RuntimeConfig(adapter_dir=adapter, run_dir=tmp_path / "runs")
    with pytest.raises(Exception, match="nope"):
        build_runtime(cfg, make_providers(ScriptedRunner()))


def test_gateway_refuses_tool_without_catalog_entry(tmp_path: Path) -> None:
    from rfcv.gates.code_gate import ListDirParams
    from rfcv.gates.tool_gateway import ToolResult, ToolSpec

    rt = build_runtime(make_config(tmp_path), make_providers(ScriptedRunner()))
    rt.close()

    async def handler(p: Any, s: ToolSession) -> ToolResult:
        raise AssertionError("không được chạy")

    with pytest.raises(ValueError, match="chưa có trong danh mục"):
        rt.gateway.register(ToolSpec("shell.exec", "chạy lệnh tuỳ ý", ListDirParams, handler))


def test_registry_override_isolates_runtime_from_global_registry(tmp_path: Path) -> None:
    reg = Registry.build()
    with use_registry(reg):
        rt = build_runtime(make_config(tmp_path), make_providers(ScriptedRunner()), registry=reg)
    rt.close()
    assert rt.registry is reg


async def test_agent_claim_contradicting_passing_tests_is_not_concluded(tmp_path: Path) -> None:
    """SUT thực sự đúng (mọi T3 PASS) nhưng agent đọc mã báo REACTION sai: hệ thống không ra COMPLIANT lẫn VIOLATION."""
    runner = ScriptedRunner()
    providers = make_providers(runner, backend=FakeBackend(sut_alert="record_overflow", buggy_impl="wolfssl"))
    rt = build_runtime(make_config(tmp_path), providers)
    runner.gateway = rt.gateway
    try:
        (verdict,) = await rt.run_all(ADAPTER_DIR / "examples")
    finally:
        rt.close()
    assert verdict.label is Label.NEEDS_REVIEW and verdict.rule == "V7"
    assert any(c.kind == "T1_vs_T3" for c in verdict.conflicts)

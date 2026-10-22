"""Phép thử tổng quát: một miền hoàn toàn khác (kiểm chứng chính sách nội bộ) chạy trọn vòng điều tra mà KHÔNG sửa lõi.

Miền mẫu nằm ngoài `src/` và chỉ dùng SPI công khai. Nếu lõi còn giữ giả định về RFC, TLS hay mã nguồn thì test này vỡ.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

import toy_domain as toy
from helpers import RUN
from rfcv.agents.schemas import PlanAction, TaskSpec
from rfcv.assembly import Providers, RuntimeConfig, build_runtime
from rfcv.core.envelope import Envelope
from rfcv.core.runner import RoleOutcome
from rfcv.evidence.verdict_engine import Label, StopReason
from rfcv.gates.tool_gateway import ToolSession
from rfcv.plugins import Registry, RegistryError, use_registry


@pytest.fixture
def toy_registry(tmp_path: Path) -> Registry:
    reg = Registry.build(
        builtin=False, third_party=False, freeze=False
    )  # lõi trần: không RFC, không TLS, không PydanticAI
    reg.register_domain(toy.pack(tmp_path / "pack"))
    return reg.freeze()


def adapter_dir(tmp_path: Path, clauses: list[str]) -> Path:
    d = tmp_path / "adapter"
    d.mkdir()
    (d / "adapter.yaml").write_text(
        yaml.safe_dump(
            {
                "adapter": "handbook",
                "version": "1",
                "domain": "policy_compliance",
                "backend": "none",
                "specs": [{"doc": "POLICY-7"}],
                "sut": {"repo": "internal/handbook", "recipe": "none.yaml"},
                "code_scope": {"include": ["**"]},
            }
        ),
        encoding="utf-8",
    )
    src = d / "examples"
    src.mkdir()
    (src / "POL-1.yaml").write_text(yaml.safe_dump({"id": "POL-1", "clauses": clauses}), encoding="utf-8")
    return d


class Scripted:
    """Planner giao kiểm tra từng điều khoản chưa kiểm; checker trả kết quả định sẵn theo điều khoản."""

    def __init__(self, truth: dict[str, bool]) -> None:
        self.truth = truth
        self.checked: list[str] = []

    async def run(self, envelope: Envelope, context: dict[str, Any], session: ToolSession) -> RoleOutcome:
        if envelope.to_role == "planner":
            missing = context["verdict.sufficiency"]["value"]["missing"]
            todo = [m["variant"] for m in missing]
            if not todo:
                return RoleOutcome(PlanAction(action="stop", rationale_code="ALL_CHECKED"), 1)
            return RoleOutcome(
                PlanAction(
                    action="dispatch",
                    tasks=[
                        TaskSpec(
                            task_type="CHECK_CLAUSE", target_role="checker", params=toy.ClauseParams(clause_id=todo[0])
                        )
                    ],
                    rationale_code="NEXT_CLAUSE",
                ),
                1,
            )
        clause = envelope.body["params"]["clause_id"]
        self.checked.append(clause)
        return RoleOutcome(toy.ClauseCheck(clause_id=clause, satisfied=self.truth[clause]), 1)


async def run_policy(tmp_path: Path, reg: Registry, truth: dict[str, bool]) -> tuple[Any, Scripted]:
    runner = Scripted(truth)
    cfg = RuntimeConfig(
        adapter_dir=adapter_dir(tmp_path, sorted(truth)), run_dir=tmp_path / "runs", run_id="run-policy"
    )
    with use_registry(reg):
        rt = build_runtime(cfg, Providers(role_runner=runner), registry=reg)
        try:
            (verdict,) = await rt.run_all(cfg.adapter_dir / "examples")
            chain_ok = rt.store.verify_chain().ok
        finally:
            rt.close()
    assert chain_ok
    return verdict, runner


async def test_second_domain_runs_to_compliant_without_touching_core(tmp_path: Path, toy_registry: Registry) -> None:
    verdict, runner = await run_policy(tmp_path, toy_registry, {"c1": True, "c2": True, "c3": True})
    assert (verdict.label, verdict.rule, verdict.assurance) == (Label.COMPLIANT, "P2", "COVERED")
    assert sorted(runner.checked) == ["c1", "c2", "c3"]
    assert verdict.rules_version == toy.POLICY_RULES.version


async def test_second_domain_finds_violation_and_stops_early(tmp_path: Path, toy_registry: Registry) -> None:
    verdict, runner = await run_policy(tmp_path, toy_registry, {"c1": True, "c2": False, "c3": True})
    assert (verdict.label, verdict.rule, verdict.stop_reason) == (Label.VIOLATION, "P1", StopReason.SUFFICIENT)
    assert runner.checked == ["c1", "c2"]  # dừng ngay khi có bằng chứng bác bỏ, không kiểm hết


def test_core_registry_without_domains_knows_nothing_domain_specific() -> None:
    bare = Registry.build(builtin=False, third_party=False)
    assert not bare.kinds and not bare.tasks and not bare.tools and not bare.rule_sets
    assert set(bare.schemas) == {"PlanAction@1", "Critique@1", "Explanation@1"}  # chỉ schema tổng quát của lõi


def test_evidence_kind_tier_and_producer_are_enforced_for_any_domain(toy_registry: Registry) -> None:
    from rfcv.evidence.models import EvidenceDraft

    with use_registry(toy_registry):
        ok = EvidenceDraft(
            run_id=RUN,
            requirement_id="POL-1",
            tier=toy.TIER,
            payload=toy.ClausePayload(clause_id="c1", satisfied=True),
            produced_by=toy.PRODUCER,
        )
        assert ok.payload.kind == "clause_check"  # type: ignore[attr-defined]
        with pytest.raises(ValueError, match="không được phép ghi"):
            EvidenceDraft(  # agent không phải thành phần tất định được ghi loại này
                run_id=RUN,
                requirement_id="POL-1",
                tier=toy.TIER,
                payload=toy.ClausePayload(clause_id="c1", satisfied=True),
                produced_by="some_agent",
            )
        with pytest.raises(ValueError, match="thuộc"):
            EvidenceDraft(
                run_id=RUN,
                requirement_id="POL-1",
                tier="T9",
                payload=toy.ClausePayload(clause_id="c1", satisfied=True),
                produced_by=toy.PRODUCER,
            )


def test_two_domains_can_coexist_but_must_not_collide(tmp_path: Path) -> None:
    reg = Registry.build(builtin=True, third_party=False, freeze=False)
    pack = toy.pack(tmp_path / "pack")
    reg.register_domain(pack)
    assert set(reg.domains) == {"rfc_protocol", "policy_compliance"}
    with pytest.raises(RegistryError, match="đã đăng ký"):
        reg.register_domain(pack)  # trùng tên miền, loại bằng chứng, nhiệm vụ
    with pytest.raises(RegistryError, match="cần chỉ rõ"):
        reg.domain()  # nhiều miền thì không được đoán

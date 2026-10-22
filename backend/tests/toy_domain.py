"""Domain pack mẫu thứ hai: kiểm chứng tuân thủ một chính sách nội bộ bằng bằng chứng tĩnh.

Không chứa RFC, TLS, mã nguồn hay sandbox: chỉ dùng SPI công khai (rfcv.spi) và lõi. Test dùng nó để chứng minh lõi đủ
tổng quát (thêm một miền không sửa lõi), và là bản mẫu cho người viết domain pack.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

from rfcv.core.ifc import Labeled, TrustLabel
from rfcv.evidence.models import Evidence, EvidenceDraft
from rfcv.evidence.verdict_engine import Conflict, Decision, Label, Missing, RequirementView, Rule, RuleSet
from rfcv.spi import DomainPack, EvidenceKind, LoopPolicy, PlaybookRule, Polarity, Suggest, TaskDefinition, When

TIER = "D1"
PRODUCER = "clause_checker"


class ClausePayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["clause_check"] = "clause_check"
    clause_id: str
    satisfied: bool


class ClauseParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause_id: str


class ClauseCheck(BaseModel):
    """Đầu ra có cấu trúc của agent kiểm tra điều khoản."""

    model_config = ConfigDict(extra="forbid")

    clause_id: str
    satisfied: bool


@dataclass(frozen=True)
class PolicyRequirement(RequirementView):
    clauses: frozenset[str] = frozenset()


def _polarity(p: ClausePayload) -> Polarity:
    return Polarity.SUPPORTS if p.satisfied else Polarity.REFUTES


def _summarize(e: Any, terms: frozenset[str]) -> dict[str, Any]:
    return {"satisfied": e.payload.satisfied}


def _prepare(req: RequirementView, evidence: Sequence[Evidence]) -> dict[str, bool]:
    """clause_id -> đã thoả (bằng chứng cuối cùng của mỗi điều khoản thắng)."""
    out: dict[str, bool] = {}
    for e in evidence:
        if isinstance(e.payload, ClausePayload):
            out[e.payload.clause_id] = e.payload.satisfied
    return out


def _violation(req: RequirementView, data: dict[str, bool]) -> Decision | None:
    bad = sorted(c for c, ok in data.items() if not ok)
    return Decision(Label.VIOLATION, "P1", tuple(bad)) if bad else None


def _compliant(req: RequirementView, data: dict[str, bool]) -> Decision | None:
    clauses = getattr(req, "clauses", frozenset())
    if clauses and set(clauses) <= set(data):
        return Decision(Label.COMPLIANT, "P2", tuple(sorted(clauses)), "COVERED")
    return None


def _gaps(req: RequirementView, data: dict[str, bool]) -> tuple[Sequence[Missing], Sequence[Conflict]]:
    clauses = getattr(req, "clauses", frozenset())
    return [Missing("D1", c, "điều khoản chưa kiểm") for c in sorted(set(clauses) - set(data))], []


POLICY_RULES = RuleSet(
    name="policy@1",
    rules=(
        Rule("P1", _violation, None, "một điều khoản không thoả"),
        Rule("P2", _compliant, None, "mọi điều khoản thoả"),
    ),
    prepare=_prepare,
    gaps=_gaps,
    fallback_rule="P9",
)


class ClauseHandler:
    """Biến đầu ra của agent thành bằng chứng, sau khi kiểm tra điều khoản có thuộc yêu cầu."""

    def __init__(self, rt: Any) -> None:
        self.rt = rt

    async def handle(self, inv: Any, task: Any, output: BaseModel | None, session: Any, msg_id: str) -> int:
        if not isinstance(output, ClauseCheck):
            return 0
        if output.clause_id not in getattr(inv.requirement, "clauses", frozenset()):
            return 0  # điều khoản lạ: bị loại, không thành bằng chứng
        self.rt.store.append(
            EvidenceDraft(
                run_id=self.rt.run_id,
                requirement_id=inv.requirement.requirement_id,
                tier=TIER,
                payload=ClausePayload(clause_id=output.clause_id, satisfied=output.satisfied),
                produced_by=PRODUCER,
            )
        )
        return 1


class PolicyRuntime:
    def required_providers(self) -> Sequence[str]:
        return ()

    def handlers(self, rt: Any) -> Mapping[str, Any]:
        return {"CHECK_CLAUSE": ClauseHandler(rt)}

    def investigations(self, rt: Any, source: Path) -> Sequence[Any]:
        from rfcv.core.execution_loop import Investigation

        out = []
        for f in sorted(source.glob("*.yaml")):
            spec = yaml.safe_load(f.read_text(encoding="utf-8"))
            req = PolicyRequirement(spec["id"], "policy", "MUST", frozenset(spec["clauses"]))
            out.append(
                Investigation(
                    requirement=req,
                    context={"requirement.structured": Labeled({"id": req.requirement_id}, TrustLabel.TRUSTED)},
                )
            )
        return out


PLAYBOOK = (
    PlaybookRule(
        "next-clause",
        When(need="D1"),
        (Suggest("CHECK_CLAUSE", bind={"clause_id": "missing.first_variant"}),),
        "NEXT_CLAUSE",
        note="Kiểm từng điều khoản còn thiếu.",
    ),
    PlaybookRule("all-checked", When(missing=False), (), "ALL_CHECKED", stop=True),
)


def write_pack_files(root: Path) -> tuple[Path, Path]:
    """Hồ sơ vai trò và lời nhắc của miền (do chính miền cung cấp, lõi không có sẵn)."""
    roles, prompts = root / "roles", root / "prompts"
    roles.mkdir(parents=True)
    prompts.mkdir(parents=True)
    (prompts / "planner.md").write_text("Bạn là Planner của miền chính sách.", encoding="utf-8")
    (prompts / "checker.md").write_text("Bạn kiểm tra một điều khoản.", encoding="utf-8")
    budget = {"llm_calls": 3, "tool_calls": 0, "tokens": 10000, "seconds": 60}
    (roles / "planner.yaml").write_text(
        yaml.safe_dump(
            {
                "role": "planner",
                "zone": "privileged",
                "context_fields": ["requirement.structured", "verdict.sufficiency"],
                "tools": [],
                "output_schema": "PlanAction@1",
                "prompt": "planner.md",
                "budget_per_task": budget,
            }
        ),
        encoding="utf-8",
    )
    (roles / "checker.yaml").write_text(
        yaml.safe_dump(
            {
                "role": "checker",
                "zone": "privileged",
                "context_fields": ["requirement.structured"],
                "tools": [],
                "output_schema": "ClauseCheck@1",
                "prompt": "checker.md",
                "budget_per_task": budget,
            }
        ),
        encoding="utf-8",
    )
    return roles, prompts


def pack(root: Path) -> DomainPack:
    roles, prompts = write_pack_files(root)
    return DomainPack(
        name="policy_compliance",
        version="1.0.0",
        evidence_kinds=[
            EvidenceKind("clause_check", TIER, ClausePayload, frozenset({PRODUCER}), _polarity, _summarize)
        ],
        schemas={"ClauseCheck@1": ClauseCheck},
        tasks=[TaskDefinition("CHECK_CLAUSE", "checker", ClauseParams)],
        rationale_codes=["NEXT_CLAUSE", "ALL_CHECKED"],
        rule_sets=[POLICY_RULES],
        tools=[],
        required_roles=("planner", "checker"),
        roles_dir=roles,
        prompts_dir=prompts,
        loop=LoopPolicy(planner_role="planner", critique_task=None),
        runtime=PolicyRuntime(),
        playbook=PLAYBOOK,
    )

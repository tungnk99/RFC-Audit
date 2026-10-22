"""Bộ gợi ý và sổ tay điều tra: hàm thuần, kiểm lúc đóng băng, in thành lời nhắc, và chạy được ở một miền khác."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import toy_domain as toy
from agents.planner.playbook import PLAYBOOK, sync_prompt
from rfcv.agents.schemas import PlanAction
from rfcv.assembly import Providers, RuntimeConfig, build_runtime
from rfcv.core.advisor import (
    Advice,
    adherence,
    advise,
    playbook_version,
    render_playbook,
    situation_from_context,
    validate_playbook,
)
from rfcv.core.envelope import Envelope, EnvelopeFactory, MessageKind
from rfcv.core.playbook_runner import PlaybookRunner
from rfcv.core.runner import RoleOutcome
from rfcv.evidence.verdict_engine import Label
from rfcv.plugins import Registry, RegistryError, current_registry, use_registry
from rfcv.spi import PlaybookRule, Suggest, When

HANDLED = {"LOCATE", "TRACE_PATHS", "RECHECK", "SELECT_TESTS", "CRITIQUE"}  # chưa có STATIC_QUERY, MAP_COMPONENTS
ONE_ROUND = [{"round": 1, "task_type": "LOCATE", "target": "code_reader", "ok": True}]


def ctx(
    rtype: str = "B",
    *,
    provisional: str | None = None,
    missing: list[dict[str, Any]] | None = None,
    conflicts: list[dict[str, Any]] | None = None,
    critique: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    report = {
        "provisional": {"label": provisional, "rule": "x", "evidence_ids": [], "assurance": None}
        if provisional
        else None,
        "decisive": provisional is not None,
        "missing": missing or [],
        "conflicts": conflicts or [],
    }
    out: dict[str, Any] = {
        "requirement.rtype": {"label": "TRUSTED", "value": rtype},
        "verdict.sufficiency": {"label": "DERIVED", "value": report},
        "tasks.history": {"label": "DERIVED", "value": history or []},
    }
    if critique is not None:
        out["critique.latest"] = {"label": "DERIVED", "value": critique}
    return out


def advice(**kw: Any) -> Advice | None:
    reg = current_registry()
    sit = situation_from_context(ctx(**kw), reg.loop_policy().critique_task)
    return advise(sit, reg.playbook, reg.tasks, HANDLED)


def names(a: Advice | None) -> list[str]:
    assert a is not None
    return [t.task_type for t in a.tasks]


def test_round_one_follows_table_10_per_type() -> None:
    assert names(advice(rtype="A")) == ["SELECT_TESTS", "LOCATE"]
    b = advice(rtype="B")
    assert b is not None and b.rationale_code == "INITIAL_TYPE_B"
    assert [a.value for a in b.tasks[1].params.aspects] == ["CONDITION", "THRESHOLD", "REACTION"]  # type: ignore[attr-defined]
    assert names(advice(rtype="C")) == ["SELECT_TESTS", "LOCATE"]
    assert names(advice(rtype="D")) == ["LOCATE"]  # STATIC_QUERY chưa có handler: bị bỏ, không gợi ý suông


def test_never_suggests_a_task_without_a_handler() -> None:
    reg = current_registry()
    sit = situation_from_context(ctx("A"))
    assert names(advise(sit, reg.playbook, reg.tasks, {"LOCATE"})) == ["LOCATE"]
    assert advise(sit, reg.playbook, reg.tasks, set()) is None


def test_provisional_compliant_is_critiqued_once_then_left_alone() -> None:
    rows = [{"round": 1, "task_type": "SELECT_TESTS", "target": "tester", "ok": True}]
    assert names(advice(provisional="COMPLIANT", history=rows)) == ["CRITIQUE"]
    assert advice(provisional="COMPLIANT", history=rows, critique={"issues": []}) is None  # không bịa thêm việc


def test_conflict_goes_critique_then_recheck_on_the_named_aspect() -> None:
    conflict = [{"kind": "T1_vs_T3", "evidence_ids": ["e1", "e2"], "aspect": "REACTION"}]
    assert names(advice(conflicts=conflict, history=ONE_ROUND)) == ["CRITIQUE"]
    issue = {"kind": "CONTRADICTION", "evidence_id": "sha256:aa", "suggested_task": "RECHECK"}
    a = advice(conflicts=conflict, history=ONE_ROUND, critique={"issues": [issue]})
    assert names(a) == ["RECHECK"] and a is not None and a.rationale_code == "FOLLOW_CRITIQUE"
    p = a.tasks[0].params
    assert (p.aspect.value, p.evidence_id) == ("REACTION", "sha256:aa")  # type: ignore[attr-defined]
    b = advice(conflicts=conflict, history=ONE_ROUND, critique={"issues": []})
    assert names(b) == ["RECHECK"] and b is not None and b.tasks[0].params.evidence_id is None  # type: ignore[attr-defined]


def test_critique_kinds_map_to_tasks() -> None:
    def follow(kind: str) -> list[str]:
        issue = {"kind": kind, "evidence_id": "sha256:aa", "suggested_task": "X"}
        return names(advice(history=ONE_ROUND, critique={"issues": [issue]}))

    assert follow("MISSING_PATH") == ["TRACE_PATHS"]
    assert follow("WRONG_LOCATION") == ["LOCATE"]


def test_missing_items_are_filled_with_their_own_parameters() -> None:
    miss = [
        {"need": "T3", "variant": "boundary:record.length=16641", "reason": "x"},
        {"need": "T1", "variant": None, "reason": "y"},
    ]
    a = advice(missing=miss, history=ONE_ROUND)
    assert names(a) == ["SELECT_TESTS"] and a is not None
    assert a.tasks[0].params.missing_variants == ["boundary:record.length=16641"]  # type: ignore[attr-defined]
    assert names(advice(missing=[miss[1]], history=ONE_ROUND)) == ["LOCATE"]


def test_advice_is_pure_and_its_signature_carries_only_codes() -> None:
    a1, a2 = advice(rtype="B"), advice(rtype="B")
    assert a1 == a2 and a1 is not None
    assert a1.signature == "B|NONE|need:-|conf:-|crit:none:-"


def test_adherence_is_classified() -> None:
    a = advice(rtype="A")
    assert a is not None
    assert adherence(a, "dispatch", a.tasks, "INITIAL_TYPE_A", "DEVIATE_PLAYBOOK") == "followed"
    assert adherence(a, "dispatch", a.tasks[:1], "DEVIATE_PLAYBOOK", "DEVIATE_PLAYBOOK") == "deviated_declared"
    assert adherence(a, "stop", (), "INFEASIBLE", "DEVIATE_PLAYBOOK") == "deviated_unannounced"
    assert adherence(None, "stop", (), "INFEASIBLE", "DEVIATE_PLAYBOOK") == "no_advice"


def test_a_plan_that_contains_all_advised_tasks_is_followed_even_with_extras() -> None:
    """CT-04: sổ tay gợi ý SELECT_TESTS, Planner giao SELECT_TESTS + LOCATE (cả hai cùng thiếu) vẫn là bám sổ tay."""
    miss = [
        {"need": "T3", "variant": "boundary:record.length=16641", "reason": "x"},
        {"need": "T1", "variant": None, "reason": "y"},
    ]
    a = advice(missing=miss, history=ONE_ROUND)
    extra = advice(missing=[miss[1]], history=ONE_ROUND)
    assert a is not None and extra is not None and names(a) == ["SELECT_TESTS"] and names(extra) == ["LOCATE"]
    superset = [*a.tasks, *extra.tasks]
    assert adherence(a, "dispatch", superset, "INITIAL_TYPE_B", "DEVIATE_PLAYBOOK") == "followed"
    # Thiếu một nhiệm vụ được gợi ý thì vẫn là chệch; đổi sang việc khác hoàn toàn cũng vậy.
    both = advice(rtype="A")
    assert both is not None and len(both.tasks) > 1
    assert adherence(both, "dispatch", both.tasks[:1], "INITIAL_TYPE_B", "DEVIATE_PLAYBOOK") == "deviated_unannounced"
    assert adherence(a, "dispatch", extra.tasks, "INITIAL_TYPE_B", "DEVIATE_PLAYBOOK") == "deviated_unannounced"


def test_playbook_version_follows_content_not_order() -> None:
    assert playbook_version(PLAYBOOK) == playbook_version(tuple(reversed(PLAYBOOK)))
    extra = PlaybookRule("R9", When(rtypes=frozenset({"A"})), (Suggest("LOCATE"),), "INITIAL_TYPE_A")
    assert playbook_version((*PLAYBOOK, extra)) != playbook_version(PLAYBOOK)
    assert current_registry().playbook_version == playbook_version(PLAYBOOK)


def test_freeze_rejects_a_bad_playbook(tmp_path: Path) -> None:
    good = Suggest("CHECK_CLAUSE", bind={"clause_id": "missing.first_variant"})
    bad = {
        "unknown-task": PlaybookRule("a", When(), (Suggest("NOPE"),), "NEXT_CLAUSE"),
        "unknown-rationale": PlaybookRule("b", When(), (good,), "WHY_NOT"),
        "bad-bind-source": PlaybookRule(
            "c", When(), (Suggest("CHECK_CLAUSE", bind={"clause_id": "free.text"}),), "NEXT_CLAUSE"
        ),
        "bad-bind-target": PlaybookRule(
            "d", When(), (Suggest("CHECK_CLAUSE", bind={"nope": "missing.first_variant"}),), "NEXT_CLAUSE"
        ),
        "bad-static-params": PlaybookRule(
            "e", When(), (Suggest("CHECK_CLAUSE", {"clause_id": 3, "zzz": 1}),), "NEXT_CLAUSE"
        ),
        "empty": PlaybookRule("f", When(), (), "NEXT_CLAUSE"),
        "stop-and-suggest": PlaybookRule("g", When(), (good,), "ALL_CHECKED", stop=True),
        "bad-label": PlaybookRule("h", When(provisional=frozenset({"MAYBE"})), (good,), "NEXT_CLAUSE"),
    }
    for name, rule in bad.items():
        reg = Registry.build(builtin=False, third_party=False, freeze=False)
        reg.register_domain(replace(toy.pack(tmp_path / name), playbook=(rule,)))
        with pytest.raises(RegistryError, match="sổ tay"):
            reg.freeze()


def test_validate_playbook_accepts_the_shipped_one() -> None:
    reg = current_registry()
    assert validate_playbook(PLAYBOOK, reg.tasks, reg.rationale_codes, [lab.value for lab in Label]) == []


def test_prompt_playbook_section_is_generated_from_the_data() -> None:
    path = Path(__file__).resolve().parents[1] / "agents/planner/prompt.md"
    text = path.read_text(encoding="utf-8")
    assert sync_prompt(text) == text, "sổ tay trong planner.md lệch dữ liệu: chạy sync_prompt và ghi lại tệp"
    assert render_playbook(PLAYBOOK) in text


# ---------------------------------------------------------------- PlaybookRunner


def _env(role: str) -> Envelope:
    return EnvelopeFactory("r").make(
        requirement_id="X",
        from_role="execution_loop",
        to_role=role,
        kind=MessageKind.DISPATCH,
        round=1,
        body={},
        budget_left={},
    )


async def test_toy_domain_completes_with_the_playbook_planner_and_no_core_edit(tmp_path: Path) -> None:
    from test_generality import Scripted, adapter_dir

    reg = Registry.build(builtin=False, third_party=False, freeze=False)
    reg.register_domain(toy.pack(tmp_path / "pack"))
    reg.freeze()
    truth = {"c1": True, "c2": True, "c3": True}
    worker = Scripted(truth)
    runner = PlaybookRunner(worker, handled={"CHECK_CLAUSE"}, stop_rationale="ALL_CHECKED", registry=reg)
    cfg = RuntimeConfig(adapter_dir=adapter_dir(tmp_path, sorted(truth)), run_dir=tmp_path / "runs", run_id="run-pb")
    with use_registry(reg):
        rt = build_runtime(cfg, Providers(role_runner=runner), registry=reg)
        try:
            (verdict,) = await rt.run_all(cfg.adapter_dir / "examples")
        finally:
            rt.close()
    assert (verdict.label, verdict.rule) == (Label.COMPLIANT, "P2")
    assert sorted(worker.checked) == ["c1", "c2", "c3"]


async def test_playbook_runner_delegates_other_roles_and_builds_valid_plans() -> None:
    class Inner:
        async def run(self, envelope: Envelope, context: dict[str, Any], session: Any) -> RoleOutcome:
            return RoleOutcome(None, 7)

    runner = PlaybookRunner(Inner(), handled=HANDLED, stop_rationale="INFEASIBLE")
    out = await runner.run(_env("code_reader"), {}, None)  # type: ignore[arg-type]
    assert out.tokens == 7
    plan = runner.plan(ctx("A"))
    assert isinstance(plan, PlanAction) and [t.task_type for t in plan.tasks] == ["SELECT_TESTS", "LOCATE"]
    stop = runner.plan(ctx("A", history=ONE_ROUND))
    assert stop.action == "stop" and stop.rationale_code == "INFEASIBLE"


def row(round: int, task_type: str, *, ok: bool = True) -> dict[str, Any]:
    return {"round": round, "task_type": task_type, "target": "x", "ok": ok}


MISSING_PATH = {"issues": [{"kind": "MISSING_PATH", "evidence_id": None, "suggested_task": "TRACE_PATHS"}]}
AFTER_FIRST_CRITIQUE = [row(1, "SELECT_TESTS"), row(1, "LOCATE"), row(2, "CRITIQUE")]


def test_a_critique_issue_is_followed_once_and_then_the_critique_is_repeated_not_the_fix() -> None:
    """Ca thật: Verifier nêu MISSING_PATH một lần, Planner giao TRACE_PATHS bốn vòng liền (1,18 triệu token) mà không
    phản biện lại. Sau khi nhiệm vụ đề xuất đã chạy xong, sổ tay phải gợi ý phản biện lại."""
    first = advice(provisional="COMPLIANT", critique=MISSING_PATH, history=AFTER_FIRST_CRITIQUE)
    assert names(first) == ["TRACE_PATHS"] and first is not None and first.rule_id == "R4-follow-missing_path"
    fixed = advice(
        provisional="COMPLIANT", critique=MISSING_PATH, history=[*AFTER_FIRST_CRITIQUE, row(3, "TRACE_PATHS")]
    )
    assert names(fixed) == ["CRITIQUE"] and fixed is not None and fixed.rule_id == "R2-recritique-after-fix"


def test_a_fix_that_failed_is_retried_and_a_new_critique_reopens_the_issue() -> None:
    failed = [*AFTER_FIRST_CRITIQUE, row(3, "TRACE_PATHS", ok=False)]
    assert names(advice(provisional="COMPLIANT", critique=MISSING_PATH, history=failed)) == ["TRACE_PATHS"]
    again = [*AFTER_FIRST_CRITIQUE, row(3, "TRACE_PATHS"), row(4, "CRITIQUE")]  # phản biện mới vẫn nêu vấn đề
    assert names(advice(provisional="COMPLIANT", critique=MISSING_PATH, history=again)) == ["TRACE_PATHS"]


def test_only_the_addressed_issues_are_dropped() -> None:
    both = {
        "issues": [
            {"kind": "MISSING_PATH", "evidence_id": None, "suggested_task": "TRACE_PATHS"},
            {"kind": "MISSING_VARIANT", "evidence_id": None, "suggested_task": "SELECT_TESTS"},
        ]
    }
    miss = [{"need": "T3", "variant": "boundary:record.length=16641", "reason": "x"}]
    a = advice(
        provisional="COMPLIANT", critique=both, history=[*AFTER_FIRST_CRITIQUE, row(3, "TRACE_PATHS")], missing=miss
    )
    assert names(a) == ["SELECT_TESTS"]  # MISSING_PATH đã xử lý; MISSING_VARIANT còn nguyên


def test_situation_distinguishes_stale_from_clean_and_none() -> None:
    reg = current_registry()
    task = reg.loop_policy().critique_task

    def kind(**kw: Any) -> str:
        return situation_from_context(ctx(**kw), task).critique

    assert kind(provisional="COMPLIANT") == "none"
    assert kind(provisional="COMPLIANT", critique={"issues": []}) == "clean"
    assert kind(provisional="COMPLIANT", critique=MISSING_PATH, history=AFTER_FIRST_CRITIQUE) == "issues"
    done = [*AFTER_FIRST_CRITIQUE, row(3, "TRACE_PATHS")]
    assert kind(provisional="COMPLIANT", critique=MISSING_PATH, history=done) == "stale"
    # không biết tên nhiệm vụ phản biện thì giữ hành vi cũ (vấn đề luôn còn)
    assert (
        situation_from_context(ctx(provisional="COMPLIANT", critique=MISSING_PATH, history=done)).critique == "issues"
    )

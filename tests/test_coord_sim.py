"""Bộ đo phối hợp (SYNTHETIC): chạy vòng điều tra thật. Tiêu chí nghiệm thu là cấu trúc (an toàn, tất định, bất biến),
KHÔNG phải con số quyết định: những con số đó chỉ được in ra và đọc bởi `decisions()`."""

from __future__ import annotations

import pytest

from conftest import ADAPTER_DIR
from rfcv.eval import coord_prereg as prereg
from rfcv.eval.coord_mast import TAGS, classify_trace
from rfcv.eval.coord_sim import CoordReport, render, run_coord

SEEDS = 1


@pytest.fixture(scope="module")
def report() -> CoordReport:
    return run_coord(ADAPTER_DIR, seeds=SEEDS)


def test_report_is_labelled_synthetic_and_names_its_registration(report: CoordReport) -> None:
    text = render(report)
    assert report.synthetic and "SYNTHETIC" in text
    assert f"phiên bản {prereg.PREREG_VERSION}" in text and report.config_hash in text
    assert "KHÔNG đo mức phổ biến lỗi của LLM thật" in text


def test_the_matrix_runs_every_registered_cell(report: CoordReport) -> None:
    for exp in prereg.EXPERIMENTS:
        for spec in exp.policies:
            for profile in exp.profiles:
                for arm in exp.arms:
                    assert report.by(exp.exp, spec, profile, arm), (exp.exp, spec, profile, arm)


def test_no_coordination_failure_flips_a_label(report: CoordReport) -> None:
    """H0: mọi chính sách × mọi hồ sơ lỗi. Phối hợp kém chỉ hạ độ phủ/bảo đảm, không bao giờ đổi chiều nhãn."""
    d = prereg.safety(report)
    assert d.passed, d.evidence


def test_evidence_chain_is_intact_in_every_cell(report: CoordReport) -> None:
    assert all(c.r.chain_ok for c in report.cells)


def test_a_loop_of_varied_params_burns_the_budget_instead_of_tripping_the_detector(report: CoordReport) -> None:
    """Cấu trúc đã biết của bộ phát hiện lặp gốc: khoá theo tham số, nên đổi `target_symbol` là né được."""
    cells = report.by("E3", "REPEATER", "W2", "base")
    assert cells and all(c.r.stop_reason == "BUDGET" and c.r.planner_calls == 8 for c in cells)
    assert all("FM_STEP_REPETITION" in c.r.tags for c in cells)


def test_a_progress_keyed_detector_stops_the_same_loop_earlier(report: CoordReport) -> None:
    base = report.by("E3", "REPEATER", "W2", "base")
    prog = report.by("E3", "REPEATER", "W2", "progress")
    assert all(c.r.stop_reason == "LOOP" for c in prog)
    assert sum(c.r.planner_calls for c in prog) < sum(c.r.planner_calls for c in base)
    assert all(c.r.label == "UNVERIFIABLE" for c in prog)  # dừng sớm không bịa nhãn


def test_premature_stop_is_rejected_every_round_and_never_concludes(report: CoordReport) -> None:
    cells = report.by("E1", "PREMATURE", "W0")
    assert cells and all(c.r.stop_rejected == 8 and c.r.label == "UNVERIFIABLE" for c in cells)
    assert all({"FM_PREMATURE_STOP", "FM_UNAWARE_TERMINATION"} <= set(c.r.tags) for c in cells)


def test_clean_workers_with_the_playbook_match_the_full_information_policy(report: CoordReport) -> None:
    d = prereg.playbook_completeness(report)
    assert d.passed, d.evidence


def test_the_critic_to_planner_to_reader_chain_recovers_code_evidence_after_a_failed_locate(
    report: CoordReport,
) -> None:
    """Với worker W2, LOCATE đầu bị cổng từ chối; nhãn tạm COMPLIANT·BEHAVIORAL → Verifier nêu MISSING_EVIDENCE → LOCATE lại."""
    good = [c for c in report.by("E2", "ORACLE-OBS-bool", "W2") if c.kind == "correct"]
    assert good and all(c.r.label == "COMPLIANT" and c.r.gate_rejects >= 1 for c in good)
    assert all(c.r.assurance == "LINKED" for c in good)  # sau khi thử lại, T1 vào được và liên kết với độ phủ


def test_correct_implementations_are_never_called_violations_under_any_policy(report: CoordReport) -> None:
    assert all(c.r.label != "VIOLATION" for c in report.cells if c.kind in ("correct", "alt_valid"))


def test_the_simulation_is_byte_for_byte_reproducible(report: CoordReport) -> None:
    again = run_coord(ADAPTER_DIR, seeds=SEEDS)
    assert [(c.exp, c.policy, c.profile, c.arm, c.impl, c.r) for c in again.cells] == [
        (c.exp, c.policy, c.profile, c.arm, c.impl, c.r) for c in report.cells
    ]
    assert again.config_hash == report.config_hash


def test_decisions_are_pure_functions_of_the_report(report: CoordReport) -> None:
    assert prereg.decisions(report) == prereg.decisions(report)
    assert {d.id for d in prereg.decisions(report)} == {"H0", "D-PB", "D1", "D1b", "D4", "D5"}


def test_config_hash_changes_with_the_registration() -> None:
    assert prereg.config_hash(1) != prereg.config_hash(2)


# ---------------------------------------------------------------- MAST


def ev(kind: str, **payload: object) -> dict[str, object]:
    return {"kind": kind, "payload": payload}


def suff(**body: object) -> dict[str, object]:
    return ev("sufficiency", round=1, provisional=None, missing=[{"need": "T3"}], conflicts=[], **body)


def test_mast_is_silent_on_a_clean_trace() -> None:
    trace = [suff(), ev("plan", tasks=[{"task_type": "SELECT_TESTS"}]), ev("verdict", stop_reason="SUFFICIENT")]
    assert classify_trace(trace) == frozenset()


def test_mast_tags_each_failure_mode() -> None:
    assert "FM_PREMATURE_STOP" in classify_trace([ev("stop_rejected")])
    assert "FM_TASK_SPEC_VIOLATION" in classify_trace([ev("task_rejected", task_type="NOPE")])
    assert "CAPABILITY_GAP" in classify_trace(
        [ev("task_rejected", task_type="STATIC_QUERY")], unavailable_tasks={"STATIC_QUERY"}
    )
    assert "FM_PLANNER_FAILURE" in classify_trace([ev("role_failure", role="planner")])
    assert "FM_WORKER_FAILURE" in classify_trace([ev("role_failure", role="code_reader")])
    assert "FM_GATE_REJECTED" in classify_trace([ev("gate_reject", gate="schema_gate")])


def test_mast_detects_repetition_only_when_the_report_does_not_move() -> None:
    plan = ev("plan", tasks=[{"task_type": "LOCATE"}])
    stuck = [suff(), plan, suff(), plan, suff()]
    assert "FM_STEP_REPETITION" in classify_trace(stuck)
    moving = [suff(), plan, ev("sufficiency", round=2, provisional=None, missing=[], conflicts=[]), plan]
    assert "FM_STEP_REPETITION" not in classify_trace(moving)


def test_mast_unaware_termination_needs_three_identical_reports_and_a_forced_stop() -> None:
    reports = [suff(), suff(), suff()]
    assert "FM_UNAWARE_TERMINATION" in classify_trace([*reports, ev("verdict", stop_reason="BUDGET")])
    assert "FM_UNAWARE_TERMINATION" not in classify_trace([*reports, ev("verdict", stop_reason="SUFFICIENT")])


def critique(*suggested: str) -> dict[str, object]:
    issues = [{"kind": "MISSING_PATH", "evidence_id": None, "suggested_task": t} for t in suggested]
    return ev("critique_result", round=1, issues=issues, clean=not issues, gating=True, accepted_as_clean=not issues)


def test_mast_flags_a_plan_that_ignores_the_critique() -> None:
    ignored = [critique("TRACE_PATHS"), ev("plan", tasks=[{"task_type": "SELECT_TESTS"}])]
    assert "FM_CRITIQUE_IGNORED" in classify_trace(ignored)
    stop = [critique("TRACE_PATHS"), ev("plan", tasks=[], action="stop")]
    assert "FM_CRITIQUE_IGNORED" in classify_trace(stop)


def test_mast_accepts_a_plan_that_follows_the_critique_or_cannot_follow_it() -> None:
    both = [{"task_type": "TRACE_PATHS"}, {"task_type": "SELECT_TESTS"}]
    assert "FM_CRITIQUE_IGNORED" not in classify_trace([critique("TRACE_PATHS"), ev("plan", tasks=both)])
    # Verifier đề xuất việc chưa có handler: Planner không làm theo được, không phải lỗi của Planner.
    impossible = [critique("STATIC_QUERY"), ev("plan", tasks=[{"task_type": "SELECT_TESTS"}])]
    assert "FM_CRITIQUE_IGNORED" not in classify_trace(impossible, unavailable_tasks={"STATIC_QUERY"})
    # Phản biện sạch không đòi hỏi gì; và chỉ kế hoạch ngay sau đó bị xét.
    assert "FM_CRITIQUE_IGNORED" not in classify_trace([critique(), ev("plan", tasks=[{"task_type": "LOCATE"}])])
    later = [critique("TRACE_PATHS"), ev("plan", tasks=[{"task_type": "TRACE_PATHS"}]), ev("plan", tasks=[])]
    assert "FM_CRITIQUE_IGNORED" not in classify_trace(later)


def test_every_tag_is_documented() -> None:
    assert len(set(TAGS)) == len(TAGS)

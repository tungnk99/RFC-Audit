"""Thế giới giả khó cho REACTION (BL-41): mã, đáp án và độ phủ phải nhất quán với nhau, nếu không số đo vô nghĩa."""

from __future__ import annotations

import pytest

from rfcv.domains.rfc_protocol.coverage_linker import parse_lcov
from rfcv.eval.hard_world import FILE, HARD_CASES, WORLDS, hard_index, lcov, sim_impl


@pytest.mark.parametrize("case", HARD_CASES)
def test_the_reaction_is_far_from_the_check_and_matches_the_expected_answer(case: str) -> None:
    world, index = WORLDS[case], hard_index(case)  # type: ignore[index]
    check, mapping = index.lines(FILE, 812, 814), index.lines(FILE, 846, 853)
    assert "LENGTH_ERROR" in " ".join(check) and "SendAlert" not in " ".join(check)  # kiểm tra chỉ trả mã lỗi
    assert f"SendAlert(ssl, alert_fatal, {world.alert})" in " ".join(mapping)
    closes = any("isClosed = 1" in line for line in mapping)
    assert closes is world.closes
    assert (world.expected_reaction == "MATCH") is (world.alert == "record_overflow" and world.closes)
    assert index.has_call_edge("ProcessReply", "HandleError") and index.has_call_edge("ProcessReply", "GetRecordHeader")


@pytest.mark.parametrize("case", HARD_CASES)
def test_coverage_reaches_the_reaction_lines_so_a_correct_answer_can_be_linked(case: str) -> None:
    """Độ phủ cũ chỉ có dòng 812-816: V5 không đạt được ở thế giới khó và ca đúng ra NEEDS_REVIEW vì lý do của bộ mô phỏng."""
    world = WORLDS[case]  # type: ignore[index]
    executed = parse_lcov(lcov(world).decode()).executed(FILE)
    assert {811, 812, 846, 847} <= executed and (853 in executed) is world.closes


def test_simulated_suts_behave_as_the_code_says() -> None:
    assert sim_impl("hard-correct").kind == "correct"
    assert sim_impl("hard-wrong-alert").family == "wrong_alert" and sim_impl("hard-no-close").family == "no_close"

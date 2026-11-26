"""Kiểm thử đơn vị cho Causal Coverage Diff & T3 FAIL linking (gen-43 / E4 & D8)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from agents.code_reader.handler import LocationHandler
from agents.code_reader.schema import AspectClaim, CheckKind, LocationClaim
from agents.common import RBS_KEY
from rfcv.core.execution_loop import Investigation
from rfcv.domains.rfc_protocol.coverage_linker import causal_diff, link, ochiai_scores, parse_lcov
from rfcv.domains.rfc_protocol.payloads import (
    AspectName,
    AspectValue,
    Finding,
    Outcome,
    T1Payload,
    T3Payload,
    Witness,
    WitnessRun,
)
from rfcv.gates.tool_gateway import ToolSession


def test_causal_diff_distinguishes_executed_accept_from_unexecuted_conn_recv() -> None:
    lcov_fail = parse_lcov(
        "SF:/src/ngtcp2/lib/ngtcp2_conn.c\n"
        "DA:6109,0\n"
        "DA:10230,1\n"
        "DA:10232,1\n"
        "end_of_record\n"
    )
    lcov_pass = parse_lcov(
        "SF:/src/ngtcp2/lib/ngtcp2_conn.c\n"
        "DA:6109,0\n"
        "DA:10230,1\n"
        "DA:10232,0\n"
        "end_of_record\n"
    )
    diff = causal_diff([lcov_fail], [lcov_pass])
    entry = diff["/src/ngtcp2/lib/ngtcp2_conn.c"]
    assert entry["fail_executed"] == [10230, 10232]
    assert entry["fail_only"] == [10232]

    t1_accept = T1Payload(
        file="lib/ngtcp2_conn.c",
        symbol="ngtcp2_accept",
        line_start=10230,
        line_end=10233,
        finding=Finding.PRESENT,
        aspects=(),
        call_path=("ngtcp2_accept",),
    )
    t1_recv = T1Payload(
        file="lib/ngtcp2_conn.c",
        symbol="conn_recv_pkt",
        line_start=6108,
        line_end=6116,
        finding=Finding.PRESENT,
        aspects=(),
        call_path=("conn_recv_pkt",),
    )
    assert link("t1-a", t1_accept, lcov_fail).linked is True
    assert link("t1-r", t1_recv, lcov_fail).linked is False


def test_ochiai_sbfl_ranks_fail_only_lines_first_and_guides_select_branch() -> None:
    lcov_fail_text = (
        "SF:/src/ngtcp2/lib/ngtcp2_conn.c\n"
        "DA:6109,0\n"
        "DA:10230,1\n"
        "DA:10232,1\n"
        "end_of_record\n"
    )
    lcov_pass_text = (
        "SF:/src/ngtcp2/lib/ngtcp2_conn.c\n"
        "DA:6109,0\n"
        "DA:10230,1\n"
        "DA:10232,0\n"
        "end_of_record\n"
    )
    scores = ochiai_scores([parse_lcov(lcov_fail_text)], [parse_lcov(lcov_pass_text)], top_k=5)
    assert [(s.line, s.score) for s in scores] == [(10232, 1.0), (10230, 0.7071)]

    # Kiểm chứng select_branch ưu tiên nhánh thực sự chạy (ngtcp2_accept:10230) thay vì nhánh dòng nhỏ hơn nhưng không chạy (conn_recv_pkt:6108).
    t3_fail = T3Payload(
        scenario="sc",
        oracle="o",
        variant="boundary:1199",
        variant_class="required",
        side="trigger",
        trigger_reached=True,
        consistent=True,
        outcome=Outcome.FAIL,
        observed={"alert": "none"},
        witness=Witness(positive=(WitnessRun(impl="ngtcp2-ref", outcome=Outcome.PASS),)),
        artifacts={"lcov": "sha256:fail"},
    )
    def _get_art(_k: str) -> bytes:
        return lcov_fail_text.encode("utf-8")

    def _for_req(_r: str) -> list[Any]:
        return [SimpleNamespace(payload=t3_fail)]

    def _check_loc(*_a: Any, **_kw: Any) -> Any:
        return SimpleNamespace(accepted=True, errors=(), draft=None)

    fake_artifacts = SimpleNamespace(get=_get_art)
    fake_store = SimpleNamespace(for_requirement=_for_req)
    fake_gate = SimpleNamespace(check_location=_check_loc)
    rt = SimpleNamespace(store=fake_store, artifacts=fake_artifacts, run_id="r1", providers=None)
    handler = LocationHandler(rt, fake_gate)  # type: ignore[arg-type]

    rbs = SimpleNamespace(
        trigger=SimpleNamespace(name="receive", args=("packet",)),
        expect=(SimpleNamespace(name="discard", args=()),),
        forbid=(),
        accept_alternatives=(),
        where=SimpleNamespace(field="datagram.payload_length"),
        variants=(),
    )
    inv = Investigation(
        requirement=SimpleNamespace(requirement_id="QUIC-0001"),  # type: ignore[arg-type]
        context={},
        vocabulary_terms=frozenset(),
        domain_state={RBS_KEY: rbs},
    )
    sess = ToolSession("r1", "code_reader", "QUIC-0001", max_tool_calls=10)
    c_unexec = LocationClaim(
        file="lib/ngtcp2_conn.c",
        symbol="conn_recv_pkt",
        line_start=6108,
        line_end=6116,
        check_kind=CheckKind.VALUE_CHECK,
        finding=Finding.PRESENT,
        aspects=[AspectClaim(aspect=AspectName.REACTION, value=AspectValue.MISMATCH, observed=None, lines=(6109, 6114))],
        call_path=["conn_recv_pkt"],
    )
    c_exec = LocationClaim(
        file="lib/ngtcp2_conn.c",
        symbol="ngtcp2_accept",
        line_start=10230,
        line_end=10233,
        check_kind=CheckKind.VALUE_CHECK,
        finding=Finding.PRESENT,
        aspects=[AspectClaim(aspect=AspectName.REACTION, value=AspectValue.MISMATCH, observed=None, lines=(10230, 10232))],
        call_path=["ngtcp2_accept"],
    )
    win_idx, summary = handler.select_branch(
        inv,
        SimpleNamespace(task_type="LOCATE"),
        [("branch_a", c_unexec, sess), ("branch_b", c_exec, sess)],
    )
    assert win_idx == 1
    assert summary["winner"] == "branch_b"
    assert summary["branches"][0]["executed_in_fail"] is False
    assert summary["branches"][1]["executed_in_fail"] is True

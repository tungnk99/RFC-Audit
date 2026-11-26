"""Kiểm thử đơn vị cho Causal Coverage Diff & T3 FAIL linking (gen-43 / E4 & D8)."""

from __future__ import annotations

from rfcv.domains.rfc_protocol.coverage_linker import causal_diff, link, parse_lcov
from rfcv.domains.rfc_protocol.payloads import Finding, T1Payload


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

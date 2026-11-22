"""Kiểm thử đơn vị cho Giải đấu Đa Chuyên gia Thuần AI Agent (`branches`, `select_branch`, `precheck` guards)."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from agents.code_reader.handler import LocationHandler
from agents.code_reader.schema import AspectClaim, CheckKind, LocationClaim
from agents.common import RBS_KEY
from rfcv.core.execution_loop import Investigation
from rfcv.domains.rfc_protocol.payloads import (
    AspectName,
    AspectValue,
    Finding,
    Outcome,
    T3Payload,
    Witness,
    WitnessRun,
)
from rfcv.gates.code_gate import InMemoryCodeIndex, SymbolInfo
from rfcv.gates.tool_gateway import ToolSession


@dataclass
class _FakeStore:
    items: list[Any] = field(default_factory=list[Any])

    def for_requirement(self, req_id: str) -> list[Any]:
        return list(self.items)


class _FakeGate:
    def __init__(self, errors_by_symbol: dict[str, tuple[str, ...]] | None = None) -> None:
        self._errors = errors_by_symbol or {}

    def check_location(self, claim: LocationClaim, session: ToolSession, **kwargs: Any) -> Any:
        errs = self._errors.get(claim.symbol, ())
        return SimpleNamespace(accepted=not errs, errors=errs, draft=None)


def _make_t3_fail(alert: str) -> Any:
    payload = T3Payload(
        scenario="sc-1",
        oracle="o-1",
        variant="v-1",
        variant_class="required",
        side="trigger",
        trigger_reached=True,
        consistent=True,
        outcome=Outcome.FAIL,
        observed={"alert": alert},
        witness=Witness(positive=(WitnessRun(impl="openssl", outcome=Outcome.PASS),)),
    )
    return SimpleNamespace(payload=payload)


def _make_inv(trigger_arg: str = "client_hello", expected_alert: str = "handshake_failure") -> Investigation:
    rbs = SimpleNamespace(
        trigger=SimpleNamespace(name="receive", args=(trigger_arg,)),
        expect=(SimpleNamespace(name="send_alert", args=(expected_alert,)),),
        forbid=(),
        accept_alternatives=(),
        where=SimpleNamespace(field="client_hello.groups"),
    )
    req = SimpleNamespace(requirement_id="TLS13-TEST")
    return Investigation(
        requirement=req,  # type: ignore[arg-type]
        context={},
        vocabulary_terms=frozenset(),
        domain_state={RBS_KEY: rbs},
    )


def _claim(
    symbol: str,
    file: str = "src/internal.c",
    *,
    reaction: AspectValue = AspectValue.MISMATCH,
    observed: str | None = "illegal_parameter",
) -> LocationClaim:
    return LocationClaim(
        file=file,
        symbol=symbol,
        line_start=100,
        line_end=110,
        check_kind=CheckKind.VALUE_CHECK,
        finding=Finding.PRESENT,
        aspects=[AspectClaim(aspect=AspectName.REACTION, value=reaction, observed=observed, lines=(102, 104))],
        call_path=[symbol],
    )


def test_branches_routes_by_signature_wrong_alert_vs_reaction_absent() -> None:
    inv = _make_inv()
    task = SimpleNamespace(task_type="LOCATE")

    rt_wrong = SimpleNamespace(store=_FakeStore([_make_t3_fail("illegal_parameter")]), run_id="r1")
    h_wrong = LocationHandler(rt_wrong, _FakeGate())  # type: ignore[arg-type]
    names_wrong = [b["name"] for b in h_wrong.branches(inv, task)]
    assert names_wrong == ["bottom_up_alert_hunter", "error_to_alert_mapper"]

    rt_absent = SimpleNamespace(store=_FakeStore([_make_t3_fail("none")]), run_id="r2")
    h_absent = LocationHandler(rt_absent, _FakeGate())  # type: ignore[arg-type]
    names_absent = [b["name"] for b in h_absent.branches(inv, task)]
    assert names_absent == ["early_check_ifdef_hunter", "top_down_protocol_tracer"]


def test_select_branch_penalizes_client_side_and_prefers_alert_mapper() -> None:
    inv = _make_inv(trigger_arg="client_hello", expected_alert="handshake_failure")
    rt = SimpleNamespace(store=_FakeStore([_make_t3_fail("illegal_parameter")]), run_id="r1")
    handler = LocationHandler(rt, _FakeGate())  # type: ignore[arg-type]
    sess = ToolSession("r1", "code_reader", "TLS13-TEST", max_tool_calls=12)

    win_idx, summary = handler.select_branch(
        inv,
        SimpleNamespace(task_type="LOCATE"),
        [
            ("bottom_up_alert_hunter", _claim("DoServerHello"), sess),
            ("error_to_alert_mapper", _claim("TranslateErrorToAlert"), sess),
        ],
    )
    assert win_idx == 1
    assert summary["winner"] == "error_to_alert_mapper"
    assert summary["branches"][0]["wrong_dir"] is True
    assert summary["branches"][1]["wrong_dir"] is False


def test_precheck_catches_wrong_direction_missing_mismatch_and_file_typo() -> None:
    inv = _make_inv(trigger_arg="client_hello", expected_alert="handshake_failure")
    index = InMemoryCodeIndex(
        sources={"src/internal.c": ["int TranslateErrorToAlert() { return 0; }"]},
        symbols=[SymbolInfo("src/internal.c", "TranslateErrorToAlert", "function", 1, 1)],
    )
    rt = SimpleNamespace(
        store=_FakeStore([_make_t3_fail("illegal_parameter")]),
        run_id="r1",
        providers=SimpleNamespace(code_index=index),
    )
    sess = ToolSession("r1", "code_reader", "TLS13-TEST", max_tool_calls=12)

    # 1. Sai chiều giao thức (DoServerHello cho server nhận ClientHello)
    h1 = LocationHandler(rt, _FakeGate())  # type: ignore[arg-type]
    errs_dir = h1.precheck(inv, _claim("DoServerHello"), sess)
    assert any("WRONG_PROTOCOL_DIRECTION" in e for e in errs_dir)

    # 2. Thiếu MISMATCH khi T3 đã chứng minh vi phạm
    errs_mis = h1.precheck(inv, _claim("TranslateErrorToAlert", reaction=AspectValue.MATCH), sess)
    assert any("MISMATCH_REQUIRED_ON_VIOLATION" in e for e in errs_mis)

    # 3. Gõ nhầm tên tệp cho hàm có thật -> trả HINT_SYMBOL_FILE
    h2 = LocationHandler(rt, _FakeGate({"TranslateErrorToAlert": ("SYMBOL_NOT_IN_INDEX",)}))  # type: ignore[arg-type]
    errs_file = h2.precheck(inv, _claim("TranslateErrorToAlert", file="src/tls13.c"), sess)
    assert any("HINT_SYMBOL_FILE" in e and "src/internal.c" in e for e in errs_file)

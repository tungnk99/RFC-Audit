"""Bộ kiểm thử hợp đồng plugin: chạy trên cài đặt có sẵn VÀ trên cài đặt cố tình hỏng (để chứng minh nó bắt được
lỗi)."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import replace

from fakes import SCENARIO, FakeBackend, FakeLauncher, make_index
from helpers import REQ, as_evidence, full_passing_set, t1, t3
from rfcv.domains.rfc_protocol.payloads import AspectValue, Outcome
from rfcv.domains.rfc_protocol.rules import RULE_SET, ProtocolRequirement
from rfcv.domains.rfc_protocol.sandbox.backend import Endpoint, EventTrace, ValidationResult
from rfcv.domains.rfc_protocol.testing import check_backend_contract, check_sut_launcher_contract
from rfcv.evidence.models import Evidence
from rfcv.evidence.verdict_engine import Decision, Label, Rule
from rfcv.testing import check_code_index_contract, check_rule_set_contract

REQ_B = ProtocolRequirement(
    REQ,
    "B",
    "MUST",
    required_variants=frozenset(
        {"at_limit:record.length=16640", "boundary:record.length=16641", "max:record.length=65535"}
    ),
    random_k=3,
)


def chain(drafts: list) -> list[Evidence]:  # type: ignore[type-arg]
    out: list[Evidence] = []
    prev = "sha256:" + "0" * 64
    for d in drafts:
        e = as_evidence(d, prev)
        out.append(e)
        prev = e.evidence_id
    return out


CASES = [
    (REQ_B, chain(full_passing_set())),
    (REQ_B, chain([t3(outcome=Outcome.FAIL)])),
    (REQ_B, chain([t1(reaction=AspectValue.MISMATCH, observed="send_alert(decode_error)")])),
    (ProtocolRequirement(REQ, "D", "MUST"), chain([t1()])),
]


# ---------------------------------------------------------------- bộ quy tắc


def test_builtin_rule_set_meets_contract() -> None:
    assert check_rule_set_contract(RULE_SET, CASES) == []


def test_contract_catches_rule_that_concludes_without_evidence() -> None:
    always_violation = Rule("X", lambda req, data: Decision(Label.VIOLATION, "X", ()))
    broken = replace(RULE_SET, rules=(always_violation, *RULE_SET.rules))
    problems = check_rule_set_contract(broken, CASES)
    assert any("chưa có bằng chứng" in p for p in problems)


def test_contract_catches_nondeterministic_rule() -> None:
    def flaky(req: object, data: object) -> Decision | None:
        return Decision(Label.NEEDS_REVIEW, "X", ()) if random.random() < 0.5 else None

    broken = replace(RULE_SET, rules=(Rule("flaky", flaky), *RULE_SET.rules))
    # xác suất cả 40 lần ngẫu nhiên đều trùng khớp là không đáng kể
    problems = [p for _ in range(40) for p in check_rule_set_contract(broken, CASES[:1])]
    assert any("không tất định" in p or "chưa có bằng chứng" in p or "thứ tự" in p for p in problems)


def test_contract_catches_cited_evidence_that_does_not_exist() -> None:
    cites_ghost = Rule("G", lambda req, data: Decision(Label.NEEDS_REVIEW, "G", ("sha256:ghost",)), None)
    broken = replace(RULE_SET, rules=(*RULE_SET.rules, cites_ghost))
    problems = check_rule_set_contract(
        broken, [(ProtocolRequirement(REQ, "A", "MUST"), chain([t3(outcome=Outcome.ERROR)]))]
    )
    assert any("không có trong đầu vào" in p or "chưa có bằng chứng" in p for p in problems)


# ---------------------------------------------------------------- chỉ mục mã


def test_builtin_code_index_meets_contract() -> None:
    assert check_code_index_contract(make_index(), "src/internal.c") == []


def test_contract_catches_index_that_returns_too_many_lines() -> None:
    class Greedy:
        def __init__(self) -> None:
            self._inner = make_index()

        def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
            return getattr(self._inner, name)

        def lines(self, file: str, start: int, end: int) -> Sequence[str]:
            return self._inner.lines(file, 1, 500)

    problems = check_code_index_contract(Greedy(), "src/internal.c")  # type: ignore[arg-type]
    assert any("quá 5 dòng" in p for p in problems)


# ---------------------------------------------------------------- backend và bộ chạy SUT


async def test_builtin_fakes_meet_backend_and_launcher_contracts() -> None:
    assert await check_backend_contract(FakeBackend(), FakeLauncher(), SCENARIO, "sut") == []
    assert await check_sut_launcher_contract(FakeLauncher(), "sut") == []


async def test_contract_catches_backend_that_accepts_everything() -> None:
    class Gullible(FakeBackend):
        def validate(self, scenario: object) -> ValidationResult:
            return ValidationResult(True, ())

    problems = await check_backend_contract(Gullible(), FakeLauncher(), SCENARIO, "sut")
    assert any("không có bước expect" in p for p in problems)


async def test_contract_catches_backend_that_raises_or_returns_raw_events() -> None:
    class Raises(FakeBackend):
        async def run(  # type: ignore[override]
            self, scenario: object, params: dict[str, object], endpoint: Endpoint, seed: int
        ) -> EventTrace:
            raise RuntimeError("boom")

    problems = await check_backend_contract(Raises(), FakeLauncher(), SCENARIO, "sut")
    assert any("ném ngoại lệ" in p for p in problems)

    class RawEvents(FakeBackend):
        async def run(  # type: ignore[override]
            self, scenario: object, params: dict[str, object], endpoint: Endpoint, seed: int
        ) -> EventTrace:
            return EventTrace(events=("alert=record_overflow",), trigger_reached=True)  # type: ignore[arg-type]

    problems = await check_backend_contract(RawEvents(), FakeLauncher(), SCENARIO, "sut")
    assert any("chuẩn hoá" in p for p in problems)

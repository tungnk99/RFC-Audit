"""Bộ mô phỏng và đo: chạy ĐƯỜNG ỐNG THẬT (compile_oracle, TestDriver, decide) trên cài đặt giao thức giả có lỗi gieo sẵn.

KẾT QUẢ LÀ SYNTHETIC: đo cơ chế phát hiện của từng chiến lược kiểm thử trên các họ lỗi do chúng ta thiết kế, không phải độ chính xác
trên cài đặt thật. Báo cáo luôn kèm khoảng tin cậy Wilson, trần "quét vét cạn" và hash cấu hình đã đóng băng.

Không nhập từ lõi ngoài những thứ công khai; không thành phần nào khác nhập mô-đun này (import-linter).
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from rfcv.adapters.manifest import load_manifest
from rfcv.core.trace import TraceLog
from rfcv.domains.rfc_protocol.adapter_view import to_vocabulary
from rfcv.domains.rfc_protocol.rules import RULE_SET, ProtocolRequirement
from rfcv.domains.rfc_protocol.sandbox.backend import Endpoint, EventTrace, ValidationResult
from rfcv.domains.rfc_protocol.sandbox.driver import TestDriver
from rfcv.domains.rfc_protocol.schemas import ScenarioProposal
from rfcv.domains.rfc_protocol.spec.oracle_compiler import ObservedEvent, compile_oracle
from rfcv.domains.rfc_protocol.spec.rbs import parse_rbs
from rfcv.domains.rfc_protocol.spec.vocabulary import Vocabulary
from rfcv.eval.faults import (
    FAMILIES,
    FaultFamily,
    SimImpl,
    alt_valid_impl,
    correct_impl,
    references,
)
from rfcv.eval.metrics import mcnemar_exact, wilson_interval
from rfcv.eval.strategies import STRATEGIES, Strategy, config_hash
from rfcv.evidence.artifacts import ArtifactStore
from rfcv.evidence.store import EvidenceStore
from rfcv.evidence.verdict_engine import Label, StopReason, decide

SCENARIO = ScenarioProposal.model_validate(
    {
        "requirement_id": "SIM-0001",
        "reach_state": "connected",
        "steps": [
            {"op": "complete_handshake"},
            {"op": "send_raw_record", "args": {"length": "$record.length"}},
            {"op": "expect", "args": {"within_ms": 2000}},
        ],
        "bindings": {"record.length": "from_variant"},
    }
)
FIELD = "record.length"


class SimBackend:
    """Backend giả: ánh xạ độ dài bản ghi sang phản ứng của cài đặt tương ứng (theo tên endpoint, môi trường theo host)."""

    name = "sim"

    def __init__(self, impls: Sequence[SimImpl]) -> None:
        self._impls = {i.name: i for i in impls}
        self.runs = 0

    def validate(self, scenario: ScenarioProposal) -> ValidationResult:
        return ValidationResult(scenario.steps[-1].op == "expect", ())

    async def sanity(self, endpoint: Endpoint) -> bool:
        return True

    async def run(
        self, scenario: ScenarioProposal, params: dict[str, int | str], endpoint: Endpoint, seed: int
    ) -> EventTrace:
        self.runs += 1
        env = int(endpoint.host.removeprefix("env"))
        resp = self._impls[endpoint.impl].behaviour(int(params[FIELD]), env)
        events: list[ObservedEvent] = []
        if resp.alert != "none":
            events.append(ObservedEvent(name="send_alert", args=(resp.alert,), t_ms=5))
        if resp.closed:
            events.append(ObservedEvent(name="close", t_ms=6))
        return EventTrace(
            events=tuple(events),
            trigger_reached=True,
            sut_alive_after=not resp.crashed,
            observation={"alert": resp.alert, "closed": resp.closed},
        )


class SimLauncher:
    def start(self, impl: str, *, coverage: bool, environment: int):
        @asynccontextmanager
        async def ctx() -> AsyncGenerator[Endpoint]:
            yield Endpoint(impl, f"env{environment}", 0)

        return ctx()


@dataclass(frozen=True)
class Cell:
    strategy: str
    family: str
    impl: str
    kind: Literal["correct", "alt_valid", "faulty"]
    seed: int
    label: str
    rule: str
    runs: int
    scan_deviates: bool


@dataclass
class Report:
    cells: list[Cell]
    config_hash: str
    seeds: int
    synthetic: bool = True
    notes: list[str] = field(default_factory=list[str])

    def select(self, *, strategy: str | None = None, family: str | None = None, kind: str | None = None) -> list[Cell]:
        return [
            c
            for c in self.cells
            if (strategy is None or c.strategy == strategy)
            and (family is None or c.family == family)
            and (kind is None or c.kind == kind)
        ]

    def summary(self, strategy: str, family: str) -> dict[str, object]:
        cells = self.select(strategy=strategy, family=family)
        n = len(cells)
        flagged = sum(c.label in (Label.VIOLATION.value, Label.NEEDS_REVIEW.value) for c in cells)
        violation = sum(c.label == Label.VIOLATION.value for c in cells)
        false_compliant = sum(c.label == Label.COMPLIANT.value for c in cells)
        return {
            "strategy": strategy,
            "family": family,
            "n": n,
            "flagged": flagged,
            "flagged_ci": wilson_interval(flagged, n),
            "violation": violation,
            "false_compliant": false_compliant,
            "false_compliant_ci": wilson_interval(false_compliant, n),
            "mean_runs": (sum(c.runs for c in cells) / n) if n else 0.0,
            "scan_detectable_fraction": (sum(c.scan_deviates for c in cells) / n) if n else 0.0,
        }

    def false_violation(self, strategy: str) -> dict[str, tuple[int, int]]:
        """(số nhãn VIOLATION, n) trên cài đặt đúng và hợp lệ-thay-thế; phải bằng 0."""
        out: dict[str, tuple[int, int]] = {}
        for kind in ("correct", "alt_valid"):
            cells = self.select(strategy=strategy, kind=kind)
            out[kind] = (sum(c.label == Label.VIOLATION.value for c in cells), len(cells))
        return out

    def decisive_rate(self, strategy: str, kind: str) -> tuple[int, int]:
        """(số nhãn COMPLIANT/VIOLATION, n): độ phủ quyết định, cặp bắt buộc với tỉ lệ COMPLIANT sai."""
        cells = self.select(strategy=strategy, kind=kind)
        return sum(c.label in (Label.COMPLIANT.value, Label.VIOLATION.value) for c in cells), len(cells)

    def paired(self, a: str, b: str, family: str | None = None) -> tuple[int, int, float]:
        """So cặp trên cùng (cài đặt, seed): b = a bắt mà b không, c = b bắt mà a không; p McNemar chính xác."""
        flagged = (Label.VIOLATION.value, Label.NEEDS_REVIEW.value)
        index_b = {(c.impl, c.seed): c.label in flagged for c in self.select(strategy=b, family=family, kind="faulty")}
        only_a = only_b = 0
        for c in self.select(strategy=a, family=family, kind="faulty"):
            fa, fb = c.label in flagged, index_b.get((c.impl, c.seed), False)
            only_a += fa and not fb
            only_b += fb and not fa
        return only_a, only_b, mcnemar_exact(only_a, only_b)


async def _run_cell(
    strategy: Strategy,
    impl: SimImpl,
    seed: int,
    vocab: Vocabulary,
    workdir: Path,
) -> tuple[str, str, int]:
    oracle = compile_oracle(parse_rbs(strategy.rbs()), vocab)
    refs = references()
    backend = SimBackend([impl, *refs])
    store = EvidenceStore(":memory:")
    trace = TraceLog(":memory:")
    try:
        driver = TestDriver(
            backend,
            SimLauncher(),
            store,
            ArtifactStore(workdir / "artifacts"),
            trace,
            sut_impl=impl.name,
            references=[r.name for r in refs],
        )
        await driver.run_requirement(run_id="sim", oracle=oracle, scenario=SCENARIO, seed=seed)
        req = ProtocolRequirement(
            "SIM-0001",
            oracle.rtype,
            "MUST",
            required_variants=oracle.required_variant_names,
            random_k=oracle.random_k,
            valid_random_k=oracle.valid_random_k,
        )
        verdict = decide(req, store.for_requirement("SIM-0001"), StopReason.SUFFICIENT, RULE_SET)
        sut_runs = backend.runs
    finally:
        store.close()
    return verdict.label.value, verdict.rule, sut_runs


def run_benchmark(
    adapter_dir: Path,
    *,
    seeds: int = 8,
    families: Sequence[FaultFamily] = FAMILIES,
    strategies: Sequence[Strategy] = STRATEGIES,
    split: Literal["train", "test", "all"] = "all",
) -> Report:
    """Chạy mọi (chiến lược × cài đặt × seed). Cùng đầu vào cho cùng báo cáo từng byte."""
    impls: list[SimImpl] = [correct_impl(), alt_valid_impl()]
    for fam in families:
        if split in ("all", fam.split):
            impls += [fam.make(s) for s in range(seeds)]
    ceiling = {i.name: i.deviates_from_correct() for i in impls}
    vocab = to_vocabulary(load_manifest(adapter_dir))

    async def main(workdir: Path) -> list[Cell]:
        out: list[Cell] = []
        for strategy in strategies:
            for impl in impls:
                for seed in [impl.seed] if impl.kind == "faulty" else range(seeds):
                    label, rule, runs = await _run_cell(strategy, impl, seed, vocab, workdir)
                    out.append(
                        Cell(
                            strategy.name,
                            impl.family or impl.kind,
                            impl.name,
                            impl.kind,
                            seed,
                            label,
                            rule,
                            runs,
                            ceiling[impl.name],
                        )
                    )
        return out

    with tempfile.TemporaryDirectory() as tmp:
        cells = asyncio.run(main(Path(tmp)))
    return Report(
        cells, config_hash(tuple(strategies)), seeds, notes=["SYNTHETIC: đo cơ chế, không phải độ chính xác ngoài đời"]
    )

"""Bộ mô phỏng SYNTHETIC: chạy đường ống thật. Tiêu chí nghiệm thu là cấu trúc (đúng/sai, bằng 0, tất định);
con số phát hiện của từng chiến lược chỉ in ra như giả thuyết đo được, không bị ép trong test."""

from __future__ import annotations

import pytest

from conftest import ADAPTER_DIR
from rfcv.eval.faults import FAMILIES, alt_valid_impl, correct_behaviour, correct_impl
from rfcv.eval.sim import Cell, Report, run_benchmark
from rfcv.eval.strategies import STRATEGIES

SEEDS = 4


@pytest.fixture(scope="module")
def report() -> Report:
    return run_benchmark(ADAPTER_DIR, seeds=SEEDS)


def test_families_are_split_into_train_and_test_without_overlap() -> None:
    train = {f.name for f in FAMILIES if f.split == "train"}
    test = {f.name for f in FAMILIES if f.split == "test"}
    assert train and test and not (train & test)
    assert len({f.name for f in FAMILIES}) == len(FAMILIES)


def test_every_fault_instance_really_deviates_from_the_correct_behaviour() -> None:
    for fam in FAMILIES:
        for seed in range(3):
            impl = fam.make(seed)
            assert impl.kind == "faulty" and impl.seed == seed
            assert impl.deviates_from_correct(), f"{fam.name}-{seed} không khác bản đúng: lỗi gieo vô nghĩa"
    assert not correct_impl().deviates_from_correct()
    assert alt_valid_impl().deviates_from_correct()  # khác bản đúng nhưng được RBS chấp nhận


def test_instances_are_deterministic_in_the_seed() -> None:
    for fam in FAMILIES:
        a, b = fam.make(5), fam.make(5)
        assert a.params == b.params
        assert [a.behaviour(v, 0) for v in (0, 100, 16640, 16641, 40000, 65535)] == [
            b.behaviour(v, 0) for v in (0, 100, 16640, 16641, 40000, 65535)
        ]


def test_correct_and_alternative_valid_implementations_are_never_called_violations(report: Report) -> None:
    for s in STRATEGIES:
        fv = report.false_violation(s.name)
        assert fv["correct"][0] == 0 and fv["alt_valid"][0] == 0, f"{s.name}: false-VIOLATION phải đúng bằng 0"
        assert fv["correct"][1] == SEEDS and fv["alt_valid"][1] == SEEDS


def test_correct_implementation_gets_compliant_under_every_strategy(report: Report) -> None:
    for s in STRATEGIES:
        decisive, n = report.decisive_rate(s.name, "correct")
        assert (decisive, n) == (SEEDS, SEEDS)
        assert {c.label for c in report.select(strategy=s.name, kind="correct")} == {"COMPLIANT"}


def test_baseline_catches_monotone_threshold_shifts_by_design(report: Report) -> None:
    """Control = ngưỡng RFC và biên = ngưỡng+1 nên mọi dịch ngưỡng đơn điệu bị bắt. Đây là tính chất cấu trúc, không phải may mắn."""
    for fam in ("threshold", "wrong_alert", "no_close"):
        r = report.summary("S0", fam)
        assert r["flagged"] == r["n"] == SEEDS and r["false_compliant"] == 0, fam


def test_the_simulation_is_byte_for_byte_reproducible(report: Report) -> None:
    again = run_benchmark(ADAPTER_DIR, seeds=SEEDS)
    assert [c.__dict__ for c in again.cells] == [c.__dict__ for c in report.cells]
    assert again.config_hash == report.config_hash


def test_report_is_labelled_synthetic(report: Report) -> None:
    assert report.synthetic and any("SYNTHETIC" in n for n in report.notes)


def test_paired_comparison_counts_discordant_pairs() -> None:
    def cell(strategy: str, impl: str, label: str) -> Cell:
        return Cell(strategy, "f", impl, "faulty", 0, label, "V2", 10, True)

    cells = [
        cell("A", "i1", "VIOLATION"),
        cell("B", "i1", "COMPLIANT"),  # chỉ A bắt
        cell("A", "i2", "VIOLATION"),
        cell("B", "i2", "COMPLIANT"),  # chỉ A bắt
        cell("A", "i3", "COMPLIANT"),
        cell("B", "i3", "NEEDS_REVIEW"),  # chỉ B bắt
        cell("A", "i4", "VIOLATION"),
        cell("B", "i4", "VIOLATION"),  # cùng bắt
    ]
    only_a, only_b, p = Report(cells, "h", 1).paired("A", "B")
    assert (only_a, only_b) == (2, 1) and 0.0 < p <= 1.0


def test_correct_behaviour_matches_the_rfc_rule() -> None:
    assert correct_behaviour(16640, 0).alert == "none" and not correct_behaviour(16640, 0).closed
    assert correct_behaviour(16641, 0).alert == "record_overflow" and correct_behaviour(16641, 0).closed

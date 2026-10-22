"""Thống kê của bộ đánh giá: khoảng Wilson, McNemar, Cohen kappa."""

from __future__ import annotations

from rfcv.eval.metrics import cohen_kappa, mcnemar_exact, wilson_interval


def test_statistics() -> None:
    lo, hi = wilson_interval(19, 20)
    assert round(lo, 4) == 0.7639 and round(hi, 4) == 0.9911  # giá trị tham chiếu Wilson cho 19/20
    assert wilson_interval(0, 0) == (0.0, 1.0)
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(0, 10) < 0.01
    assert cohen_kappa(["V", "C", "V"], ["V", "C", "V"]) == 1.0

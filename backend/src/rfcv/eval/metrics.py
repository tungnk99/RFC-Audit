"""Thống kê cho thực nghiệm (thiết kế chính, mục 5.3; tài liệu đánh giá, mục 8).

Lõi không được nhập mô-đun này (import-linter).
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def wilson_interval(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Khoảng tin cậy Wilson 95% cho một tỉ lệ; phù hợp cỡ mẫu nhỏ."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar_exact(b: int, c: int) -> float:
    """p-value hai phía của kiểm định McNemar chính xác; b, c là số cặp bất đồng theo hai chiều."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("hai dãy nhãn phải cùng độ dài và khác rỗng")
    n = len(a)
    labels = set(a) | set(b)
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pe = sum((a.count(lbl) / n) * (b.count(lbl) / n) for lbl in labels)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)

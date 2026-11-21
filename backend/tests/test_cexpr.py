"""Kiểm thử hồi quy cho bộ tính biểu thức hằng C (`rfcv.gates.cexpr`)."""

from __future__ import annotations

import pytest

from rfcv.gates.cexpr import EvalError, evaluate


def _const(mapping: dict[str, str]):
    def lookup(name: str) -> tuple[str, str] | None:
        return (mapping[name], "test.h:1") if name in mapping else None

    return lookup


def test_apply_zero_rhs_does_not_divide_by_zero() -> None:
    """Lỗi thực tế trên M5: dict literal đánh giá sẵn `a // b` gây ZeroDivisionError khi `b == 0` với `+`, `-`, `|`, `<<`."""
    assert evaluate("X + 0", _const({"X": "16384"})).value == 16384
    assert evaluate("X - 0", _const({"X": "16384"})).value == 16384
    assert evaluate("X * 0", _const({"X": "16384"})).value == 0
    assert evaluate("X | 0", _const({"X": "7"})).value == 7
    assert evaluate("X << 0", _const({"X": "7"})).value == 7
    assert evaluate("X >> 0", _const({"X": "7"})).value == 7


def test_apply_division_by_zero_and_negative_shift_raise_eval_error() -> None:
    with pytest.raises(EvalError):
        evaluate("X / 0", _const({"X": "10"}))
    with pytest.raises(EvalError):
        evaluate("X % 0", _const({"X": "10"}))
    with pytest.raises(EvalError):
        evaluate("X << -1", _const({"X": "10"}))

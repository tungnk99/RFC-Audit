"""Ngân sách theo yêu cầu và phát hiện lặp (rủi ro A6; tài liệu phối hợp agent, mục 4 và 8)."""

from __future__ import annotations

import time
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from typing import Any

from rfcv.common.hashing import content_hash


@dataclass(frozen=True)
class RequirementBudget:
    rounds: int = 8
    tool_calls: int = 120
    tokens: int = 1_500_000
    seconds: float = 1800.0


class BudgetTracker:
    def __init__(self, budget: RequirementBudget, clock: Callable[[], float] = time.monotonic) -> None:
        self.budget = budget
        self._clock = clock
        self._start = clock()
        self.rounds = 0
        self.tool_calls = 0
        self.tokens = 0

    def charge_round(self) -> None:
        self.rounds += 1

    def charge_tool_calls(self, n: int = 1) -> None:
        self.tool_calls += n

    def charge_tokens(self, n: int) -> None:
        self.tokens += n

    def elapsed(self) -> float:
        return self._clock() - self._start

    def exhausted(self) -> bool:
        return (
            self.rounds >= self.budget.rounds
            or self.tool_calls >= self.budget.tool_calls
            or self.tokens >= self.budget.tokens
            or self.elapsed() >= self.budget.seconds
        )

    def remaining(self) -> dict[str, int]:
        return {
            "rounds": max(0, self.budget.rounds - self.rounds),
            "tool_calls": max(0, self.budget.tool_calls - self.tool_calls),
            "tokens": max(0, self.budget.tokens - self.tokens),
            "seconds": max(0, int(self.budget.seconds - self.elapsed())),
        }


@dataclass
class LoopDetector:
    """Cùng một nhiệm vụ được giao lần thứ ba mà không có bằng chứng mới thì coi là lặp."""

    limit: int = 3
    _last_evidence_count: dict[str, Hashable] = field(default_factory=dict[str, Hashable])
    _repeats: dict[str, int] = field(default_factory=dict[str, int])

    @staticmethod
    def key(task_type: str, target_role: str, params: dict[str, Any]) -> str:
        return content_hash({"t": task_type, "r": target_role, "p": params})

    def observe(self, key: str, evidence_count: Hashable) -> bool:
        """Ghi nhận một lần giao việc; True nếu đây là lần lặp thứ `limit`.

        `evidence_count` là dấu hiệu tiến triển: mặc định số bằng chứng; có thể thay bằng giá trị băm hữu hạn khác.
        """
        if self._last_evidence_count.get(key) == evidence_count:
            self._repeats[key] = self._repeats.get(key, 1) + 1
        else:
            self._repeats[key] = 1
        self._last_evidence_count[key] = evidence_count
        return self._repeats[key] >= self.limit

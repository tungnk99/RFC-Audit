"""Map-Reduce Async Audit Fleet: concurrent sharded execution of requirements with bounded concurrency.

100% domain-agnostic: operates only on requirement IDs, an async worker callback, and `VerdictRecord`.
Guarantees:
- Bounded concurrency via `asyncio.Semaphore(config.max_concurrency)`.
- Per-requirement fault isolation by default (`fail_fast=False`), or prompt sibling cancellation when `fail_fast=True`.
- Deterministic output order in `FleetReport.items` matching exact input `requirement_ids` order regardless of completion order.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from rfcv.evidence.verdict_engine import VerdictRecord


@dataclass(frozen=True)
class FleetConfig:
    """Configuration for bounded concurrent requirement auditing."""

    max_concurrency: int = 4
    fail_fast: bool = False

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError(f"max_concurrency must be >= 1, got {self.max_concurrency}")


@dataclass(frozen=True)
class FleetItemResult:
    """Outcome for a single requirement executed by the audit fleet."""

    requirement_id: str
    verdict: VerdictRecord | None
    tokens: int = 0
    duration_s: float = 0.0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.verdict is not None and self.error is None


@dataclass(frozen=True)
class FleetReport:
    """Aggregated map-reduce report across all requirements in a fleet run."""

    items: tuple[FleetItemResult, ...]
    total: int
    succeeded: int
    failed: int
    by_label: dict[str, int]
    total_tokens: int
    wall_s: float


async def run_audit_fleet(
    requirement_ids: Sequence[str],
    worker: Callable[[str], Awaitable[tuple[VerdictRecord, int]]],
    config: FleetConfig | None = None,
) -> FleetReport:
    """Run an async audit worker over `requirement_ids` with bounded concurrency and deterministic ordering.

    Each worker invocation receives a `requirement_id` and returns `(VerdictRecord, tokens)`.
    Exceptions are isolated per requirement unless `config.fail_fast` is `True`, in which case
    in-flight sibling tasks are cancelled and the original exception is re-raised.
    """
    cfg = config or FleetConfig()
    wall_start = time.monotonic()

    if not requirement_ids:
        return FleetReport(
            items=(),
            total=0,
            succeeded=0,
            failed=0,
            by_label={},
            total_tokens=0,
            wall_s=time.monotonic() - wall_start,
        )

    sem = asyncio.Semaphore(cfg.max_concurrency)

    async def _run_one(req_id: str) -> FleetItemResult:
        async with sem:
            started = time.monotonic()
            try:
                verdict, tokens = await worker(req_id)
            except Exception as exc:
                if cfg.fail_fast:
                    raise
                return FleetItemResult(
                    requirement_id=req_id,
                    verdict=None,
                    tokens=0,
                    duration_s=time.monotonic() - started,
                    error=f"{type(exc).__name__}: {exc}",
                )
            return FleetItemResult(
                requirement_id=req_id,
                verdict=verdict,
                tokens=tokens,
                duration_s=time.monotonic() - started,
                error=None,
            )

    tasks = [asyncio.create_task(_run_one(req_id)) for req_id in requirement_ids]
    try:
        results = tuple(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    by_label: dict[str, int] = {}
    succeeded = 0
    failed = 0
    total_tokens = 0
    for item in results:
        total_tokens += item.tokens
        if item.verdict is not None and item.error is None:
            succeeded += 1
            label_key = item.verdict.label.value
            by_label[label_key] = by_label.get(label_key, 0) + 1
        else:
            failed += 1

    return FleetReport(
        items=results,
        total=len(results),
        succeeded=succeeded,
        failed=failed,
        by_label=by_label,
        total_tokens=total_tokens,
        wall_s=time.monotonic() - wall_start,
    )

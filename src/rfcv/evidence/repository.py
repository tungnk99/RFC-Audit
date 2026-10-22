"""Hợp đồng lưu trữ (repository): lõi chỉ biết các Protocol này, không biết SQLite.

Cài đặt mặc định là SQLite chỉ-ghi-thêm (`EvidenceStore`, `RequirementRegistry`, `TraceLog`). Triển khai doanh nghiệp
có thể
thay bằng Postgres hay kho bất biến khác miễn giữ các bất biến: chỉ ghi thêm, chuỗi hash, một kho một tenant.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol

from rfcv.evidence.models import Evidence, EvidenceDraft


class ChainStatus(Protocol):
    @property
    def ok(self) -> bool: ...

    @property
    def count(self) -> int: ...

    @property
    def head(self) -> str: ...


class EvidenceRepository(Protocol):
    tenant: str

    def append(self, draft: EvidenceDraft) -> Evidence: ...

    def get(self, evidence_id: str) -> Evidence | None: ...

    def for_requirement(self, requirement_id: str) -> list[Evidence]: ...

    def count(self) -> int: ...

    def head(self) -> str: ...

    def verify_chain(self) -> ChainStatus: ...

    def record_verdict(self, requirement_id: str, verdict: dict[str, Any]) -> None: ...

    def latest_verdicts(self) -> dict[str, dict[str, Any]]: ...

    def record_review(self, requirement_id: str, review: dict[str, Any]) -> None: ...

    def close(self) -> None: ...


class TraceSink(Protocol):
    """Nhật ký chỉ ghi thêm. Bộ xuất OpenTelemetry hay SIEM là một TraceSink bọc ngoài."""

    def append(
        self,
        run_id: str,
        kind: str,
        payload: dict[str, Any],
        *,
        role: str | None = None,
        requirement_id: str | None = None,
    ) -> int: ...

    def events(self, kind: str | None = None) -> Iterator[dict[str, Any]]: ...


class RequirementRepository(Protocol):
    def add(self, requirement_id: str, body: dict[str, object], actor: str) -> None: ...

    def state(self, requirement_id: str) -> Any: ...

    def transition(self, requirement_id: str, new: Any, actor: str) -> None: ...

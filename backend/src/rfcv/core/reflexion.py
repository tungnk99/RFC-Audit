"""IFC-Safe Structured Reflexion Memory: bounded per-requirement failure memory for privileged agents.

100% domain-agnostic and strictly compliant with Information Flow Control (IFC):
- Only finite-domain values (integers, `FailureKind` enum, and validated `VerifiedRef` code tokens) are stored and emitted.
- Arbitrary untrusted free-form text (spaces, newlines, prompt injections, non-ASCII, overlong strings, or out-of-vocabulary
  tokens when an allowlist is configured) is sanitized to a constant finite-domain sentinel token so IFC can never be bypassed.
- Emitted context carries `TrustLabel.DERIVED` AND passes `finite_domain(...)` (admissible even under `TrustLabel.UNTRUSTED`).
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, overload

from rfcv.core.ifc import IFCViolation, Labeled, TrustLabel, VerifiedRef, finite_domain

UNVERIFIED_CODE = "UNVERIFIED_CODE"
UNVERIFIED_ROLE = "UNVERIFIED_ROLE"
UNVERIFIED_TASK = "UNVERIFIED_TASK"

# Strict ASCII identifier/code token: no whitespace, no newlines, no quotes/brackets, max 64 chars.
_SAFE_CODE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}", re.ASCII)


class FailureKind(StrEnum):
    """Finite taxonomy of operational failures recorded for structured reflexion."""

    SCHEMA_REJECT = "SCHEMA_REJECT"
    TOOL_DENIED = "TOOL_DENIED"
    CRITIQUE_ISSUE = "CRITIQUE_ISSUE"
    BUDGET_PRESSURE = "BUDGET_PRESSURE"
    LOOP_WARNING = "LOOP_WARNING"


def is_safe_code_token(value: str) -> bool:
    """Return True iff `value` is a strict finite-domain ASCII code token."""
    return bool(_SAFE_CODE_RE.fullmatch(value))


def sanitize_code_token(
    value: object,
    *,
    fallback: str = UNVERIFIED_CODE,
    allowed: Collection[str] | None = None,
) -> VerifiedRef:
    """Validate `value` as a safe code token (and optional allowlist member), else replace with `fallback`."""
    if not is_safe_code_token(fallback):
        raise ValueError(f"fallback must be a safe code token, got {fallback!r}")
    if isinstance(value, str) and is_safe_code_token(value) and (allowed is None or value in allowed):
        return VerifiedRef(value)
    return VerifiedRef(fallback)


@dataclass(frozen=True)
class ReflectionEntry:
    """Single immutable, IFC-sanitized reflexion record for one failed or warned step."""

    round: int
    role: str
    task_type: str
    kind: FailureKind
    codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.round, bool) or self.round < 0:
            raise ValueError(f"round must be a non-negative int, got {self.round!r}")
        kind = FailureKind(self.kind)
        safe_role = sanitize_code_token(self.role, fallback=UNVERIFIED_ROLE)
        safe_task = sanitize_code_token(self.task_type, fallback=UNVERIFIED_TASK)
        deduped: list[VerifiedRef] = []
        seen: set[str] = set()
        for raw_code in self.codes:
            token = sanitize_code_token(raw_code, fallback=UNVERIFIED_CODE)
            if token not in seen:
                seen.add(token)
                deduped.append(token)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "role", safe_role)
        object.__setattr__(self, "task_type", safe_task)
        object.__setattr__(self, "codes", tuple(deduped))

    def to_finite_dict(self) -> dict[str, Any]:
        """Serialize to a strictly finite-domain dict admissible to privileged roles."""
        return {
            "round": self.round,
            "role": VerifiedRef(self.role),
            "task_type": VerifiedRef(self.task_type),
            "kind": self.kind,
            "codes": [VerifiedRef(code) for code in self.codes],
        }


class ReflexionMemory:
    """Bounded per-requirement structured reflexion memory with strict IFC enforcement."""

    def __init__(
        self,
        max_entries: int = 8,
        *,
        max_codes_per_entry: int = 8,
        allowed_roles: Collection[str] | None = None,
        allowed_tasks: Collection[str] | None = None,
        allowed_codes: Collection[str] | None = None,
    ) -> None:
        if max_entries < 1:
            raise ValueError(f"max_entries must be >= 1, got {max_entries}")
        if max_codes_per_entry < 1:
            raise ValueError(f"max_codes_per_entry must be >= 1, got {max_codes_per_entry}")
        self._max_entries = max_entries
        self._max_codes_per_entry = max_codes_per_entry
        self._allowed_roles = frozenset(allowed_roles) if allowed_roles is not None else None
        self._allowed_tasks = frozenset(allowed_tasks) if allowed_tasks is not None else None
        self._allowed_codes = frozenset(allowed_codes) if allowed_codes is not None else None
        self._entries: dict[str, deque[ReflectionEntry]] = {}

    @property
    def max_entries(self) -> int:
        return self._max_entries

    @overload
    def record(self, requirement_id: str, entry: ReflectionEntry) -> ReflectionEntry: ...

    @overload
    def record(
        self,
        requirement_id: str,
        *,
        round: int,
        role: str,
        task_type: str,
        kind: FailureKind,
        codes: Sequence[str] = (),
    ) -> ReflectionEntry: ...

    def record(
        self,
        requirement_id: str,
        entry: ReflectionEntry | None = None,
        *,
        round: int | None = None,
        role: str | None = None,
        task_type: str | None = None,
        kind: FailureKind | None = None,
        codes: Sequence[str] = (),
    ) -> ReflectionEntry:
        """Record a sanitized reflection entry for `requirement_id`, evicting oldest beyond `max_entries`."""
        if entry is not None:
            if any(arg is not None for arg in (round, role, task_type, kind)) or codes:
                raise TypeError("Pass either a ReflectionEntry or keyword fields, not both")
            raw_round = entry.round
            raw_role = entry.role
            raw_task = entry.task_type
            raw_kind = entry.kind
            raw_codes: Sequence[str] = entry.codes
        else:
            if round is None or role is None or task_type is None or kind is None:
                raise TypeError("record() requires either `entry` or (`round`, `role`, `task_type`, `kind`)")
            raw_round = round
            raw_role = role
            raw_task = task_type
            raw_kind = kind
            raw_codes = codes

        safe_role = sanitize_code_token(raw_role, fallback=UNVERIFIED_ROLE, allowed=self._allowed_roles)
        safe_task = sanitize_code_token(raw_task, fallback=UNVERIFIED_TASK, allowed=self._allowed_tasks)
        safe_codes: list[VerifiedRef] = []
        seen: set[str] = set()
        for raw_code in raw_codes:
            token = sanitize_code_token(raw_code, fallback=UNVERIFIED_CODE, allowed=self._allowed_codes)
            if token not in seen:
                seen.add(token)
                safe_codes.append(token)
                if len(safe_codes) >= self._max_codes_per_entry:
                    break

        sanitized = ReflectionEntry(
            round=raw_round,
            role=safe_role,
            task_type=safe_task,
            kind=raw_kind,
            codes=tuple(safe_codes),
        )
        bucket = self._entries.get(requirement_id)
        if bucket is None:
            bucket = deque[ReflectionEntry](maxlen=self._max_entries)
            self._entries[requirement_id] = bucket
        bucket.append(sanitized)
        return sanitized

    def for_requirement(self, requirement_id: str) -> tuple[ReflectionEntry, ...]:
        """Return bounded reflection entries for `requirement_id` in chronological order."""
        bucket = self._entries.get(requirement_id)
        return tuple(bucket) if bucket is not None else ()

    def as_labeled_context(self, requirement_id: str) -> Labeled[list[dict[str, Any]]]:
        """Return IFC-safe `Labeled` context (`TrustLabel.DERIVED`) strictly composed of finite-domain values."""
        rows: list[dict[str, Any]] = [entry.to_finite_dict() for entry in self.for_requirement(requirement_id)]
        if not finite_domain(rows):
            raise IFCViolation(f"reflexion memory for {requirement_id} violated finite-domain invariant")
        return Labeled(rows, TrustLabel.DERIVED)

    def clear(self, requirement_id: str | None = None) -> None:
        """Clear reflection entries for one requirement or all requirements."""
        if requirement_id is None:
            self._entries.clear()
        else:
            self._entries.pop(requirement_id, None)

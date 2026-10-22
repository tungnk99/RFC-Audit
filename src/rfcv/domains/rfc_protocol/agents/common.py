"""Thứ dùng chung giữa các agent của miền: kiểu nhiệm vụ, đích giao việc, mã lý do, tham số nhiệm vụ, khoá trạng thái miền."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rfcv.domains.rfc_protocol.payloads import AspectName

ORACLE_KEY = "oracle"  # khoá trong `Investigation.domain_state` giữ oracle đã biên dịch


class Out(BaseModel):
    """Gốc của mọi schema đầu ra agent: cấm trường thừa."""

    model_config = ConfigDict(extra="forbid")


class TaskType(StrEnum):
    LOCATE = "LOCATE"
    TRACE_PATHS = "TRACE_PATHS"
    RECHECK = "RECHECK"
    MAP_COMPONENTS = "MAP_COMPONENTS"
    SELECT_TESTS = "SELECT_TESTS"
    STATIC_QUERY = "STATIC_QUERY"
    CRITIQUE = "CRITIQUE"


class TargetRole(StrEnum):
    CODE_READER = "code_reader"
    CODE_INDEXER = "code_indexer"
    TEST = "test"
    LOCATOR = "locator"
    VERIFIER = "verifier"


class RationaleCode(StrEnum):
    INITIAL_TYPE_A = "INITIAL_TYPE_A"
    INITIAL_TYPE_B = "INITIAL_TYPE_B"
    INITIAL_TYPE_C = "INITIAL_TYPE_C"
    INITIAL_TYPE_D = "INITIAL_TYPE_D"
    FILL_MISSING_VARIANT = "FILL_MISSING_VARIANT"
    RESOLVE_CONFLICT = "RESOLVE_CONFLICT"
    CRITIQUE_BEFORE_COMPLIANT = "CRITIQUE_BEFORE_COMPLIANT"
    FOLLOW_CRITIQUE = "FOLLOW_CRITIQUE"
    DECISIVE_VIOLATION = "DECISIVE_VIOLATION"
    DECISIVE_COMPLIANT = "DECISIVE_COMPLIANT"
    INFEASIBLE = "INFEASIBLE"
    DEVIATE_PLAYBOOK = "DEVIATE_PLAYBOOK"


class TaskParams(Out):
    aspects: list[AspectName] = Field(default_factory=list[AspectName])
    start_hints: Literal["locator", "none"] = "none"
    evidence_id: str | None = None
    aspect: AspectName | None = None
    target_symbol: str | None = None
    component: str | None = None
    missing_variants: list[str] = Field(default_factory=list[str])
    query_id: str | None = None


class NoTaskParams(Out):
    pass

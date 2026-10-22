"""Đầu ra của Code Reader (vùng cách ly): vị trí mã và nhận định có cấu trúc. Trường `note` tự do mang nhãn UNTRUSTED."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from rfcv.domains.rfc_protocol.agents.common import Out
from rfcv.domains.rfc_protocol.payloads import AspectName, AspectValue, Finding


class CheckKind(StrEnum):
    LENGTH_BOUND = "LENGTH_BOUND"
    VALUE_CHECK = "VALUE_CHECK"
    STATE_CHECK = "STATE_CHECK"
    PRESENCE_CHECK = "PRESENCE_CHECK"
    EFFECT = "EFFECT"
    OTHER = "OTHER"


class AspectClaim(Out):
    aspect: AspectName
    value: AspectValue
    observed: str | int | None = None
    lines: tuple[int, int]


class LocationClaim(Out):
    file: str
    symbol: str
    line_start: int
    line_end: int
    check_kind: CheckKind
    finding: Finding
    aspects: list[AspectClaim] = Field(default_factory=list[AspectClaim])
    call_path: list[str] = Field(default_factory=list[str])
    unexplored: list[str] = Field(default_factory=list[str])
    note: str | None = Field(default=None, description="Ghi chú tự do; mang nhãn UNTRUSTED, không tới agent đặc quyền.")

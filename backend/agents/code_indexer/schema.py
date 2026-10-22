"""Đầu ra của Code Indexer (vùng cách ly): bản đồ ký hiệu → thành phần."""

from __future__ import annotations

from pydantic import Field

from agents.common import Out


class ComponentEntry(Out):
    file: str
    symbol: str
    component: str


class ComponentMap(Out):
    entries: list[ComponentEntry] = Field(default_factory=list[ComponentEntry])

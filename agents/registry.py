"""Danh sách agent của miền theo thứ tự trong tài liệu thiết kế (đặc quyền trước, cách ly sau, rồi thành phần tất định).

Nhập muộn (không ở `agents/__init__.py`) để tránh vòng nhập: `schemas.py` nhập schema của từng agent.
"""

from __future__ import annotations

from agents import (
    code_indexer,
    code_reader,
    locator,
    planner,
    report,
    rfc_analyst,
    test,
    verifier,
)
from rfcv.spi import AgentSpec

AGENTS: tuple[AgentSpec, ...] = (
    rfc_analyst.SPEC,
    planner.SPEC,
    test.SPEC,
    verifier.SPEC,
    report.SPEC,
    code_indexer.SPEC,
    code_reader.SPEC,
    locator.SPEC,
)

"""Locator là thành phần tất định (không phải LLM): nhận truy vấn từ mẫu do adapter cung cấp."""

from __future__ import annotations

from pydantic import Field

from rfcv.domains.rfc_protocol.agents.common import Out


class QueryProposal(Out):
    """Agent chỉ chọn mẫu truy vấn do adapter cung cấp và điền tham số (không viết QL tự do)."""

    query_template_id: str
    params: dict[str, str] = Field(default_factory=dict)

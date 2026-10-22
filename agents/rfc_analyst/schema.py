"""Đầu ra của RFC Analyst: đề xuất một khối RBS cho nhóm câu RFC."""

from __future__ import annotations

from pydantic import Field

from agents.common import Out


class RbsProposal(Out):
    sentence_ids: list[str] = Field(min_length=1)
    rbs_text: str = Field(description="Một khối RBS đúng ngữ pháp, chỉ dùng từ vựng adapter.")
    non_behavioral: bool = Field(default=False, description="Câu không mô tả hành vi kiểm chứng được.")

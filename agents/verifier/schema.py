"""Verifier trả `Critique@1` (schema tổng quát của lõi); ở đây chỉ có danh mục loại vấn đề của miền (Bảng 8)."""

from __future__ import annotations

from enum import StrEnum


class CritiqueKind(StrEnum):
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    CONTRADICTION = "CONTRADICTION"
    WRONG_LOCATION = "WRONG_LOCATION"
    MISSING_PATH = "MISSING_PATH"
    MISSING_VARIANT = "MISSING_VARIANT"

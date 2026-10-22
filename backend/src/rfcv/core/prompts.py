"""Lời nhắc hệ thống của các vai trò: nạp từ thư mục của domain pack, băm để ghi vào bản kê lần chạy (K6)."""

from __future__ import annotations

from collections.abc import Iterable
from functools import cache
from pathlib import Path

from rfcv.common.hashing import content_hash
from rfcv.core.policy import PolicyStore


@cache
def _read(path: Path, mtime_ns: int) -> str:
    return path.read_text(encoding="utf-8")


def load_prompt(path: Path) -> str:
    """Đọc lời nhắc; nhớ đệm theo (đường dẫn, thời điểm sửa) nên sửa tệp là có hiệu lực ngay, kể cả trong tiến trình sống lâu."""
    return _read(path, path.stat().st_mtime_ns)


def role_prompt(policy: PolicyStore, role: str) -> str:
    return load_prompt(policy.prompt_path(role))


def prompts_digest(policy: PolicyStore, roles: Iterable[str]) -> str:
    return content_hash({r: role_prompt(policy, r) for r in sorted(roles)})

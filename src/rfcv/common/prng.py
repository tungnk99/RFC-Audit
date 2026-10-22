"""Số ngẫu nhiên tất định dựa trên hash, tái lập được giữa mọi bản Python và nền tảng.

`random.Random.randint` không được bảo đảm cho cùng một dòng số giữa các phiên bản CPython, nên không dùng cho
bất cứ thứ gì phải replay được (biến thể kiểm thử, họ lỗi mô phỏng). Ở đây mọi giá trị là hàm thuần của các thành phần khoá.
"""

from __future__ import annotations

import hashlib


def hash_uint(*parts: object) -> int:
    """Số nguyên 256 bit tất định từ các thành phần khoá (thứ tự có nghĩa)."""
    digest = hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).digest()
    return int.from_bytes(digest, "big")


def hash_randint(lo: int, hi: int, *parts: object) -> int:
    """Số nguyên đều trong [lo, hi]; độ lệch do phép chia dư không đáng kể vì dùng 256 bit."""
    if hi < lo:
        raise ValueError(f"khoảng rỗng: [{lo}, {hi}]")
    return lo + hash_uint(*parts) % (hi - lo + 1)


def hash_unit(*parts: object) -> float:
    """Số thực trong [0, 1)."""
    return (hash_uint(*parts) >> 192) / float(1 << 64)

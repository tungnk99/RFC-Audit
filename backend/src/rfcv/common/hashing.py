"""Băm nội dung tất định.

Mọi hash trong hệ thống (bằng chứng, bản kê, lời nhắc, oracle) đi qua mô-đun này.
JSON được chuẩn hoá theo RFC 8785 (JCS), nên cùng nội dung luôn cho cùng hash
trên mọi máy, đây là điều kiện để chuỗi bằng chứng tái lập được (mục 2.4).
"""

from __future__ import annotations

import hashlib
from typing import Any

import rfc8785

PREFIX = "sha256:"
GENESIS = PREFIX + "0" * 64


def canonical_json(obj: Any) -> bytes:
    return rfc8785.dumps(obj)


def sha256_bytes(data: bytes) -> str:
    return PREFIX + hashlib.sha256(data).hexdigest()


def content_hash(obj: Any) -> str:
    return sha256_bytes(canonical_json(obj))


def text_hash(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))

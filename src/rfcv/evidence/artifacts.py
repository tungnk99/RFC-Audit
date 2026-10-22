"""Artifact store: kịch bản DSL, gói tin, nhật ký SUT, dữ liệu độ phủ, truy vấn đã cố định.

Định danh theo hash nội dung; ghi một lần. Nhật ký và gói tin thô chỉ cho người kiểm chứng
và các thành phần tất định (oracle, Coverage linker) đọc, không bao giờ tới agent (rủi ro A2).
"""

from __future__ import annotations

from pathlib import Path

from rfcv.common.hashing import sha256_bytes


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, digest: str) -> Path:
        hexd = digest.removeprefix("sha256:")
        if len(hexd) != 64 or not all(c in "0123456789abcdef" for c in hexd):
            raise ValueError(f"định danh artifact không hợp lệ: {digest}")
        return self.root / hexd[:2] / hexd

    def put(self, data: bytes) -> str:
        digest = sha256_bytes(data)
        path = self._path(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        return digest

    def get(self, digest: str) -> bytes:
        data = self._path(digest).read_bytes()
        if sha256_bytes(data) != digest:
            raise ValueError(f"artifact {digest} bị sửa đổi")
        return data

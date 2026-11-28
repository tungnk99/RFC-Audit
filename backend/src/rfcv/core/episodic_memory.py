"""`EpisodicMemory` (gen-51 / L5 ADD_MEMORY): bản đồ mốc mã nguồn tích luỹ qua nhiều yêu cầu trên cùng một kho mã.

Hoàn toàn không biết miền. Handler tất định chỉ ghi vị trí đã qua cổng kiểm chứng; hub cấp ảnh chụp qua trường ngữ cảnh
`memory.codebase_map` với nhãn DERIVED. Ràng buộc IFC được ép ngay tại kiểu dữ liệu: mọi trường chuỗi (`file`, `symbol`,
`rtype`, `finding`) phải là một token định danh ASCII, không khoảng trắng, tối đa 200 ký tự. Chuỗi khác dạng (mã nguồn,
văn xuôi, chỉ thị) làm cả mốc bị bỏ, không cắt gọt rồi giữ lại. Điều này áp dụng cả với mốc đọc lại từ tệp.
Mốc là gợi ý điều tra, không phải bằng chứng: Verdict engine không đọc bộ nhớ này, và agent vẫn phải tự đọc lại mã
trước khi dẫn dòng.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Self, cast

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

MAX_TOKEN_CHARS = 200
DEFAULT_SNAPSHOT_LIMIT = 16

# Đủ cho đường dẫn và ký hiệu (`ns::fn`, `~Dtor`, `Type.method`); không có ký tự dựng biểu thức, thẻ, khối mã hay JSON.
_TOKEN = re.compile(r"[A-Za-z0-9_.:#+\-/@~]+", re.ASCII)

_Key = tuple[str, str, str]  # (file, symbol, rtype)


class CodebaseLandmark(BaseModel, frozen=True):
    file: str
    symbol: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    rtype: str = ""
    finding: str = ""
    hits: int = Field(default=1, ge=1)

    @field_validator("file", "symbol", "rtype", "finding")
    @classmethod
    def _require_token(cls, v: str) -> str:
        # Chuỗi rỗng chỉ hợp lệ cho hai trường tuỳ chọn (kiểm ở `_check_shape`).
        if v and (len(v) > MAX_TOKEN_CHARS or _TOKEN.fullmatch(v) is None):
            raise ValueError("trường chuỗi phải là một token định danh")
        return v

    @model_validator(mode="after")
    def _check_shape(self) -> Self:
        if not self.file or not self.symbol:
            raise ValueError("file và symbol không được rỗng")
        if self.line_end < self.line_start:
            raise ValueError("line_end phải không nhỏ hơn line_start")
        return self


class EpisodicMemory:
    """Mốc theo khoá `(file, symbol, rtype)`; thấy lại thì tăng `hits` và nới khoảng dòng."""

    def __init__(self) -> None:
        self._landmarks: dict[_Key, CodebaseLandmark] = {}

    def record(
        self, file: str, symbol: str, line_start: int, line_end: int, *, rtype: str = "", finding: str = ""
    ) -> CodebaseLandmark | None:
        """Ghi một lần thấy đã kiểm chứng; trả None (không đổi gì) nếu mốc không qua được kiểm tra hình dạng."""
        try:
            seen = CodebaseLandmark(
                file=file,
                symbol=symbol,
                line_start=line_start,
                line_end=line_end,
                rtype=rtype,
                finding=finding,
            )
        except ValidationError:
            return None
        key: _Key = (seen.file, seen.symbol, seen.rtype)
        old = self._landmarks.get(key)
        if old is not None:
            seen = seen.model_copy(
                update={
                    "line_start": min(old.line_start, seen.line_start),
                    "line_end": max(old.line_end, seen.line_end),
                    "finding": seen.finding or old.finding,
                    "hits": old.hits + 1,
                }
            )
        self._landmarks[key] = seen
        return seen

    def snapshot(self, rtype: str | None = None, limit: int = DEFAULT_SNAPSHOT_LIMIT) -> list[dict[str, Any]]:
        """Tối đa `limit` mốc: cùng `rtype` đứng trước, rồi theo `hits` giảm dần (hoà thì theo khoá, để tất định)."""
        ranked = sorted(
            self._landmarks.values(),
            key=lambda m: (rtype is None or m.rtype != rtype, -m.hits, m.file, m.symbol, m.rtype),
        )
        return [m.model_dump(mode="json") for m in ranked[: max(limit, 0)]]

    def load(self, path: Path) -> None:
        """Nạp mốc từ tệp JSON. Tệp thiếu hay hỏng thì bỏ qua; từng mục không hợp lệ bị loại riêng."""
        try:
            data: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError):
            return
        if not isinstance(data, list):
            return
        for raw in cast("list[Any]", data):
            try:
                landmark = CodebaseLandmark.model_validate(raw)
            except ValidationError:
                continue
            self._landmarks[(landmark.file, landmark.symbol, landmark.rtype)] = landmark

    def save(self, path: Path) -> None:
        """Ghi toàn bộ mốc ra JSON, thay tệp một lần để lần chạy bị ngắt không để lại tệp dở. Lỗi I/O ném `OSError`."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        rows = [m.model_dump(mode="json") for m in self._landmarks.values()]
        tmp.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        os.replace(tmp, path)

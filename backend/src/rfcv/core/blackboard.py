"""War-room `HypothesisBoard` (gen-47 / L5 ADD_COMM_PATTERN): bảng giả thuyết dùng chung trong một `Investigation`.

Hoàn toàn không biết miền. Các vai trò không gọi nhau: handler tất định đăng mục lên bảng, hub cấp ảnh chụp bảng qua trường
ngữ cảnh `warroom.blackboard` với nhãn DERIVED. Bảng chỉ chở siêu dữ liệu có cấu trúc, nên ràng buộc IFC được ép ngay
tại kiểu dữ liệu:
- trường định danh (`author`, `file`, `symbol`, `field`, `value` dạng chuỗi) chỉ nhận một token không khoảng trắng; chuỗi
  khác dạng (mã nguồn, văn xuôi, chỉ thị) bị bỏ cả trường, không cắt gọt rồi giữ lại;
- `note` là một dòng ngắn đã loại ký tự điều khiển và ký tự cấu trúc.
Mục trên bảng là gợi ý điều tra, không phải bằng chứng: Verdict engine không đọc bảng.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, field_validator

HypothesisKind = Literal[
    "behavioral_signal", "coverage_hotspot", "branch_candidate", "location_hypothesis", "probe_result"
]
HypothesisStatus = Literal["open", "verified", "refuted"]

MAX_NOTE_CHARS = 120
MAX_TOKEN_CHARS = 200
DEFAULT_SNAPSHOT_LIMIT = 24

# Đủ cho đường dẫn, ký hiệu C/C++ (`ns::fn`, `~Dtor`), tên trường và tên biến thể (`code_probe:a.b=type_77`).
_TOKEN = re.compile(r"[A-Za-z0-9_.:#=+\-/\\()\[\],@~*]+")
# Ký tự dựng thẻ, khối mã, JSON hay mẫu chỉ thị trong prompt.
_SUSPICIOUS = frozenset("<>{}[]`\"'\\|#$")

_DedupKey = tuple[str, str, str | None, int | None, str | None, str | int | None]


def _is_token(text: str) -> bool:
    return len(text) <= MAX_TOKEN_CHARS and _TOKEN.fullmatch(text) is not None


class HypothesisEntry(BaseModel, frozen=True):
    entry_id: str
    author: str
    kind: HypothesisKind
    file: str | None = None
    symbol: str | None = None
    line: int | None = None
    field: str | None = None
    value: str | int | None = None
    score: float | None = None
    status: HypothesisStatus = "open"
    note: str = ""

    @field_validator("author")
    @classmethod
    def _check_author(cls, v: str) -> str:
        if not _is_token(v):
            raise ValueError("author phải là tên vai trò")
        return v

    @field_validator("file", "symbol", "field")
    @classmethod
    def _keep_token(cls, v: str | None) -> str | None:
        return v if v is None or _is_token(v) else None

    @field_validator("value")
    @classmethod
    def _keep_token_value(cls, v: str | int | None) -> str | int | None:
        return None if isinstance(v, str) and not _is_token(v) else v

    @field_validator("note")
    @classmethod
    def _sanitize_note(cls, v: str) -> str:
        # Gộp khoảng trắng (gồm xuống dòng, tab) trước, rồi bỏ ký tự điều khiển/định dạng (nhóm Unicode C*: ESC,
        # zero-width, đảo chiều bidi) và ký tự cấu trúc.
        flat = " ".join(v.split())
        kept = "".join(c for c in flat if c not in _SUSPICIOUS and not unicodedata.category(c).startswith("C"))
        return " ".join(kept.split())[:MAX_NOTE_CHARS].rstrip()


class HypothesisBoard:
    """Chỉ thêm mục; thao tác sửa duy nhất là đổi `status`."""

    def __init__(self) -> None:
        self._entries: list[HypothesisEntry] = []
        self._seen: set[_DedupKey] = set()

    def post(
        self,
        author: str,
        kind: HypothesisKind,
        *,
        file: str | None = None,
        symbol: str | None = None,
        line: int | None = None,
        field: str | None = None,
        value: str | int | None = None,
        score: float | None = None,
        status: HypothesisStatus = "open",
        note: str = "",
    ) -> HypothesisEntry | None:
        """Thêm một mục; trả None nếu trùng `(author, kind, file, line, field, value)` sau khi làm sạch."""
        entry = HypothesisEntry(
            entry_id=f"hb-{len(self._entries) + 1:03d}",
            author=author,
            kind=kind,
            file=file,
            symbol=symbol,
            line=line,
            field=field,
            value=value,
            score=score,
            status=status,
            note=note,
        )
        key: _DedupKey = (entry.author, entry.kind, entry.file, entry.line, entry.field, entry.value)
        if key in self._seen:
            return None
        self._seen.add(key)
        self._entries.append(entry)
        return entry

    def update_status(self, entry_id: str, status: HypothesisStatus) -> bool:
        for i, entry in enumerate(self._entries):
            if entry.entry_id == entry_id:
                self._entries[i] = entry.model_copy(update={"status": status})
                return True
        return False

    def entries(
        self, kind: HypothesisKind | None = None, status: HypothesisStatus | None = None
    ) -> tuple[HypothesisEntry, ...]:
        return tuple(
            e for e in self._entries if (kind is None or e.kind == kind) and (status is None or e.status == status)
        )

    def snapshot(self, limit: int = DEFAULT_SNAPSHOT_LIMIT) -> list[dict[str, Any]]:
        """`limit` mục mới nhất, dạng JSON gọn (bỏ trường None)."""
        latest = self._entries[-limit:] if limit > 0 else []
        return [e.model_dump(mode="json", exclude_none=True) for e in latest]

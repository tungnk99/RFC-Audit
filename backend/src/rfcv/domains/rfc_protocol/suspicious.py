"""Bộ quét nhánh nghi vấn (T2 `suspicious_branch`, CG-6, YD-25, QS-11): mã nhận ra kiểm thử và đổi hành vi (tấn công A7).

Hoàn toàn tất định, không LLM, chạy trên các hàm nằm trên đường xử lý của vị trí Code Reader đã định (hàm chứa vị trí và
các hàm trong `call_path`). Ba mức tinh vi của A7:

- Mức 1, nhận ra giá trị kiểm thử thông dụng: so sánh BẰNG (`==`, `!=`, `case`) với đúng giá trị mà bộ kiểm thử hay dùng
  (adapter khai báo trong `field_domains.*.canonical`, ví dụ 16641 và 65535 cho độ dài bản ghi). So sánh `>` hay `<` với ngưỡng
  là việc bình thường nên không bị báo; hằng dùng làm mặt nạ hay `#define` cũng không.
- Mức 2, nhận ra môi trường kiểm thử: đọc biến môi trường, tên máy hay định danh môi trường (`getenv`, `gethostname`, `uname`...),
  hoặc so khớp chuỗi với tên công cụ kiểm thử.
- Mức 3, đối thủ thích nghi (che giấu giá trị, tính hằng lúc chạy, gián tiếp qua nhiều hàm): bộ quét KHÔNG phát hiện được và
  không hứa phát hiện. Tuyên bố của đề tài là báo cáo trung thực tỉ lệ này (thiết kế, Bảng 30), không phải chống mọi gian lận.

Kết quả là bằng chứng trung lập: nó chỉ làm Verdict engine (quy tắc V4) chuyển nhãn sang NEEDS_REVIEW để người xem lại, không
bao giờ tự kết luận VIOLATION. Báo nhầm vì thế tốn công duyệt chứ không làm sai nhãn.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

RULE_CANONICAL = "S1-canonical-equality"
RULE_ENVIRONMENT = "S2-environment-read"

_ENV_CALLS = re.compile(
    r"\b(?:getenv|secure_getenv|gethostname|gethostbyname|uname|getlogin|getlogin_r|gethostid)\s*\("
)
_TOOL_NAMES = re.compile(r"\"[^\"\n]*(?:tlsfuzzer|tlslite|tls-anvil|tlsanvil|fuzz|valgrind)[^\"\n]*\"", re.IGNORECASE)
_STRING_COMPARE = re.compile(r"\b(?:strcmp|strncmp|strcasecmp|strncasecmp|strstr|memcmp|XSTRCMP|XSTRNCMP|XSTRSTR)\s*\(")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"//[^\n]*")
_STRING = re.compile(r"\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])'")
_INT = re.compile(r"\b(0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*\b")


class _Index(Protocol):
    def lines(self, file: str, start: int, end: int) -> Sequence[str]: ...


class _Symbol(Protocol):
    file: str
    line_start: int
    line_end: int


@dataclass(frozen=True)
class SuspiciousFinding:
    rule_id: str
    file: str
    line: int


def canonical_values(field_domains: Mapping[str, Any]) -> frozenset[int]:
    """Giá trị kiểm thử thông dụng mà adapter khai báo (`field_domains.<trường>.canonical`)."""
    out: set[int] = set()
    for domain in field_domains.values():
        if isinstance(domain, Mapping):
            for v in domain.get("canonical", ()) or ():  # type: ignore[union-attr]
                if isinstance(v, int):
                    out.add(v)
    return frozenset(out)


def _blank(match: re.Match[str]) -> str:
    """Thay chú thích bằng khoảng trắng cùng số dòng, để số dòng của phần còn lại không lệch."""
    return re.sub(r"[^\n]", " ", match.group(0))


def strip_comments(source: str) -> str:
    return _LINE_COMMENT.sub(_blank, _BLOCK_COMMENT.sub(_blank, source))


def _blank_strings(source: str) -> str:
    return _STRING.sub(lambda m: " " * len(m.group(0)), source)


def _equality_with(code: str, values: frozenset[int]) -> bool:
    """Dòng có so sánh bằng/khác, hay `case`, với một trong `values` (thập phân hay thập lục phân)."""
    if not values:
        return False
    for m in _INT.finditer(code):
        try:
            number = int(m.group(1), 0)
        except ValueError:
            continue
        if number not in values:
            continue
        before = code[: m.start()].rstrip()
        after = code[m.end() :].lstrip()
        compared = before.endswith(("==", "!=")) or after.startswith(("==", "!="))
        in_case = re.search(r"\bcase\s*$", before) is not None
        if compared or in_case:
            return True
    return False


def scan_source(file: str, first_line: int, source: str, canonical: frozenset[int]) -> list[SuspiciousFinding]:
    """Quét một đoạn mã bắt đầu ở dòng `first_line` của `file`."""
    findings: list[SuspiciousFinding] = []
    no_comments = strip_comments(source)
    for offset, raw in enumerate(no_comments.split("\n")):
        stripped = raw.strip()
        if not stripped or stripped.startswith(("#define", "#include", "# define", "# include")):
            continue
        line = first_line + offset
        if _equality_with(_blank_strings(raw), canonical):
            findings.append(SuspiciousFinding(RULE_CANONICAL, file, line))
        if _ENV_CALLS.search(raw) or (_STRING_COMPARE.search(raw) and _TOOL_NAMES.search(raw)):
            findings.append(SuspiciousFinding(RULE_ENVIRONMENT, file, line))
    return findings


def scan_symbols(index: _Index, symbols: Iterable[_Symbol], canonical: frozenset[int]) -> list[SuspiciousFinding]:
    """Quét thân các hàm đã cho (mỗi hàm một lần, không báo trùng cùng quy tắc và dòng)."""
    seen: set[tuple[str, str, int]] = set()
    out: list[SuspiciousFinding] = []
    done: set[tuple[str, int, int]] = set()
    for sym in symbols:
        key = (sym.file, sym.line_start, sym.line_end)
        if key in done:
            continue
        done.add(key)
        body = "\n".join(index.lines(sym.file, sym.line_start, sym.line_end))
        for f in scan_source(sym.file, sym.line_start, body, canonical):
            k = (f.rule_id, f.file, f.line)
            if k not in seen:
                seen.add(k)
                out.append(f)
    return out

"""gen-38 (L5 ADD_STRATEGY — Code-First → Targeted Dynamic Verify): trích xuất hằng số nhánh từ mã nguồn để kiểm chứng bằng T3.

Hoàn toàn tất định, không LLM, không vi phạm IFC:
- Khi kiểm thử hộp đen mặc định (`Test-First`) cho tất cả ca PASS (nguy cơ bỏ sót lỗi cửa sổ hẹp / magic value như `U5`:
  `if (ssl->curRL.type != 77)` hoặc nhánh ngoại lệ), mô-đun này quét trực tiếp các vị trí phát mã phản ứng kỳ vọng trong kho mã,
  trích các hằng số nguyên trong điều kiện `if`/`switch`/`case` lân cận, rồi trả về danh sách ứng viên (`CodeProbeCandidate`) để
  `TestDriver` chạy thực thi thật trên cả SUT lẫn bản tham chiếu (`witness_positive`).
- Verdict Engine vẫn chỉ chốt `VIOLATION` khi `T3` chạy thật xác nhận FAIL và bản tham chiếu PASS -> 0% báo động giả.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

from rfcv.domains.rfc_protocol.suspicious import strip_comments

_COMPARE_LIT = re.compile(
    r"(?:(?:==|!=|<=|>=|<|>)\s*(0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*\b"
    r"|\b(0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*\s*(?:==|!=|<=|>=|<|>)"
    r"|\bcase\s+(0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*\s*:)"
)
_GUARD_LINE = re.compile(r"\b(?:if|else\s+if|switch|case)\b")
_STD_TLS_CONTENT_TYPES = frozenset({20, 21, 22, 23, 24})
_SKIP_DIR_PARTS = ("test", "tests", "example", "examples", "doc", "docs", "fuzz", "bench")


class _CodeIndex(Protocol):
    def files(self) -> Sequence[str]: ...
    def lines(self, file: str, start: int, end: int) -> Sequence[str]: ...
    def line_count(self, file: str) -> int | None: ...


@dataclass(frozen=True)
class CodeProbeCandidate:
    """Một giá trị nghi vấn trích tất định từ nhánh mã quanh điểm phát phản ứng."""

    field: str
    value: int | str
    file: str
    line: int
    snippet: str


def _parse_int(token: str) -> int | None:
    try:
        return int(token, 0)
    except ValueError:
        return None


def _is_prod_c_file(path: str) -> bool:
    low = path.replace("\\", "/").lower()
    if not low.endswith((".c", ".h", ".cc", ".cpp", ".hpp")):
        return False
    parts = low.split("/")
    return not any(p in _SKIP_DIR_PARTS for p in parts[:-1])


def _alert_regex(expected_alert: str) -> re.Pattern[str]:
    clean = re.sub(r"[^a-zA-Z0-9]+", "_", expected_alert.strip()).strip("_")
    return re.compile(re.escape(clean), re.IGNORECASE)


def _format_candidate(
    num: int,
    field: str,
    domain: Mapping[str, Any] | None,
    existing: frozenset[str],
) -> int | str | None:
    if not isinstance(domain, Mapping):
        return None
    raw_values = domain.get("values")
    if isinstance(raw_values, Sequence) and not isinstance(raw_values, (str, bytes)):
        vals = [str(v) for v in cast("Sequence[Any]", raw_values)]
        # Dạng tiền tố `type_<N>` (ví dụ `record.content_type: [type_0, type_99, type_255]`)
        if vals and all(v.startswith("type_") and v[5:].isdigit() for v in vals):
            if not (0 <= num <= 255):
                return None
            if field == "record.content_type" and num in _STD_TLS_CONTENT_TYPES:
                return None
            formatted = f"type_{num}"
            return None if formatted in existing else formatted
        return None
    lo = domain.get("min")
    hi = domain.get("max")
    if isinstance(lo, int) and isinstance(hi, int) and lo <= num <= hi and str(num) not in existing:
        return num
    return None


def extract_branch_candidates(
    index: _CodeIndex,
    *,
    expected_alert: str,
    field: str,
    existing_values: Sequence[int | str],
    field_domain: Mapping[str, Any] | None,
    window_before: int = 5,
    window_after: int = 2,
    max_candidates: int = 4,
) -> list[CodeProbeCandidate]:
    """Quét các vị trí phát `expected_alert` trong kho mã, rút ra tối đa `max_candidates` hằng số nhánh bất thường."""
    if not expected_alert or not field or field_domain is None:
        return []
    pat = _alert_regex(expected_alert)
    existing = frozenset(str(v) for v in existing_values)
    seen_vals: set[str] = set()
    candidates: list[CodeProbeCandidate] = []

    for fpath in index.files():
        if not _is_prod_c_file(fpath):
            continue
        total = index.line_count(fpath)
        if not total or total <= 0:
            continue
        all_lines = index.lines(fpath, 1, total)
        for idx, line in enumerate(all_lines):
            if not pat.search(line):
                continue
            lo = max(0, idx - window_before)
            hi = min(len(all_lines), idx + window_after + 1)
            chunk = strip_comments("\n".join(all_lines[lo:hi])).split("\n")
            for rel, code_line in enumerate(chunk):
                if not _GUARD_LINE.search(code_line):
                    continue
                for m in _COMPARE_LIT.finditer(code_line):
                    tok = m.group(1) or m.group(2) or m.group(3)
                    if not tok:
                        continue
                    num = _parse_int(tok)
                    if num is None or num in (0, 1):
                        continue
                    formatted = _format_candidate(num, field, field_domain, existing)
                    if formatted is None or str(formatted) in seen_vals:
                        continue
                    seen_vals.add(str(formatted))
                    candidates.append(
                        CodeProbeCandidate(
                            field=field,
                            value=formatted,
                            file=fpath,
                            line=lo + rel + 1,
                            snippet=all_lines[lo + rel].strip()[:120],
                        )
                    )
                    if len(candidates) >= max_candidates:
                        return candidates
    return candidates

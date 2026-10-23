"""Tính biểu thức hằng số nguyên của C (macro, enum) một cách tất định, không `eval`.

Dùng cho `code.eval`: agent hỏi "`MAX_RECORD_SIZE + MAX_MSG_EXTRA` bằng bao nhiêu theo cờ build này" thay vì tự cộng và tự
giả định (đo: Code Reader ghi "giả định WC_MAX_DIGEST_SIZE = 64"). Chỉ hỗ trợ số nguyên, `+ - * / % << >> & | ^ ~ ( )`, so sánh
và `?:` không có; tên chưa biết trả về danh sách chưa phân giải, không đoán.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

_TOKEN = re.compile(r"\s*(?:(?P<num>0[xX][0-9a-fA-F]+|\d+)[uUlL]*|(?P<id>[A-Za-z_]\w*)|(?P<op><<|>>|[-+*/%&|^~()]))")
_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_CAST = re.compile(r"\(\s*(?:unsigned|signed|int|long|short|word16|word32|byte|size_t)(?:\s+\w+)*\s*\)")
_PRECEDENCE = {"|": 1, "^": 2, "&": 3, "<<": 4, ">>": 4, "+": 5, "-": 5, "*": 6, "/": 6, "%": 6}


class EvalError(ValueError):
    pass


@dataclass
class Resolution:
    """Kết quả tính: giá trị (hoặc None), vết thay thế từng tên, tên chưa phân giải."""

    value: int | None
    trail: list[str] = field(default_factory=list[str])
    unresolved: list[str] = field(default_factory=list[str])
    note: str = ""


# tên -> (biểu thức, nơi định nghĩa) hoặc None; `defined:TÊN` -> ("1" | "0", lý do) cho toán tử `defined(TÊN)` của #if
Lookup = Callable[[str], "tuple[str, str] | None"]


def strip_definition(text: str, name: str) -> str | None:
    """Phần giá trị của `#define NAME value` hoặc `NAME = value,` (enum). None nếu không nhận ra."""
    body = _COMMENT.sub(" ", text.replace("\\\n", " "))
    m = re.search(rf"#\s*define\s+{re.escape(name)}\b(?!\()\s*(?P<v>[^\n]*)", body)
    if m:
        return m.group("v").strip() or None
    m = re.search(rf"\b{re.escape(name)}\s*=\s*(?P<v>[^,}}\n]+)", body)
    return m.group("v").strip() if m else None


def _tokens(expr: str) -> list[tuple[str, str]]:
    expr = _CAST.sub(" ", _COMMENT.sub(" ", expr)).strip()
    out: list[tuple[str, str]] = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN.match(expr, pos)
        if m is None or m.end() == pos:
            raise EvalError(f"không đọc được '{expr[pos : pos + 12]}'")
        kind = next(k for k in ("num", "id", "op") if m.group(k) is not None)
        out.append((kind, m.group(kind)))
        pos = m.end()
    return out


def evaluate(expr: str, lookup: Lookup, *, depth: int = 0, res: Resolution | None = None) -> Resolution:
    res = res or Resolution(None)
    if depth > 12:
        raise EvalError("macro lồng quá sâu")
    toks = _tokens(expr)
    idx = 0

    def peek() -> tuple[str, str] | None:
        return toks[idx] if idx < len(toks) else None

    def atom() -> int | None:
        nonlocal idx
        t = peek()
        if t is None:
            raise EvalError("biểu thức cụt")
        idx += 1
        kind, val = t
        if kind == "num":
            return int(val, 0)
        if kind == "id" and val == "defined":
            paren = peek() == ("op", "(")
            if paren:
                idx += 1
            ident = peek()
            if ident is None or ident[0] != "id":
                raise EvalError("defined cần một tên")
            idx += 1
            if paren:
                if peek() != ("op", ")"):
                    raise EvalError("thiếu ')'")
                idx += 1
            found = lookup(f"defined:{ident[1]}")
            res.trail.append(
                f"defined({ident[1]}) -> {found[0] if found else 'chưa biết'} [{found[1] if found else ''}]"
            )
            return int(found[0]) if found else None
        if kind == "id":
            found = lookup(val)
            if found is None:
                if val not in res.unresolved:
                    res.unresolved.append(val)
                return None
            sub, where = found
            inner = evaluate(sub, lookup, depth=depth + 1, res=res)
            res.trail.append(
                f"{val} = {sub.strip()} [{where}]" + (f" -> {inner.value}" if inner.value is not None else "")
            )
            return inner.value
        if val == "(":
            v = binary(0)
            t2 = peek()
            if t2 != ("op", ")"):
                raise EvalError("thiếu ')'")
            idx += 1
            return v
        if val in "-+~":
            v = atom()
            if v is None:
                return None
            return -v if val == "-" else (~v if val == "~" else v)
        raise EvalError(f"toán tử '{val}' không hợp lệ ở đây")

    def binary(min_prec: int) -> int | None:
        nonlocal idx
        left = atom()
        while True:
            t = peek()
            if t is None or t[0] != "op" or t[1] not in _PRECEDENCE or _PRECEDENCE[t[1]] < min_prec:
                return left
            op = t[1]
            idx += 1
            right = binary(_PRECEDENCE[op] + 1)
            if left is None or right is None:
                left = None
                continue
            left = _apply(op, left, right)

    value = binary(0)
    if idx != len(toks):
        raise EvalError(f"thừa '{toks[idx][1]}'")
    res.value = value
    return res


def _apply(op: str, a: int, b: int) -> int:
    if op in ("/", "%") and b == 0:
        raise EvalError("chia cho 0")
    return {
        "+": a + b,
        "-": a - b,
        "*": a * b,
        "/": a // b,
        "%": a % b,
        "<<": a << b,
        ">>": a >> b,
        "&": a & b,
        "|": a | b,
        "^": a ^ b,
    }[op]

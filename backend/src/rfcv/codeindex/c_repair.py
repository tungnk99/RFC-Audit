"""Đường lui cho tệp C mà tree-sitter phân tích sai khi gặp macro và `#if` lồng nhau.

Đo trên wolfSSL (`src/internal.c`): `GetRecordHeader` (dòng 12402) không có trong chỉ mục và `ProcessReplyEx` bị cắt còn 22
dòng, kéo theo biến cục bộ bị ghi nhầm là biến phạm vi tệp. Khi đó câu trả lời đúng của Code Reader bị Schema gate từ chối
(`SYMBOL_NOT_IN_INDEX`/`LINES_OUTSIDE_SYMBOL`) và nhiệm vụ cạn ngân sách.

Quy ước tìm hàm: đầu hàm bắt đầu ở cột 0, dấu `{` mở thân đứng một mình ở cột 0 và dấu `}` đóng thân đứng một mình ở cột 0
(kiểu định dạng của wolfSSL, OpenSSL, GnuTLS). Cũng nhận kiểu K&R `kiểu tên(...) {` (dấu `{` cùng dòng với `)`, kiểu của
Dropbear), với điều kiện chặt hơn vì mẫu này dễ nhầm. Chỉ BỔ SUNG hoặc KÉO DÀI ký hiệu; không bao giờ thu hẹp hay xoá ký hiệu
hàm của tree-sitter. Tất định: chỉ phụ thuộc nội dung tệp.
"""

from __future__ import annotations

import re
from typing import Any

_NAME = re.compile(r"([A-Za-z_]\w*)\s*\(")
_NOT_FUNCTIONS = frozenset({"if", "while", "for", "switch", "return", "sizeof", "defined", "typedef", "struct", "enum"})
Symbol = tuple[str, str, str, int, int, str]
MAX_HEAD_LINES = 16  # đầu hàm K&R dài nhất được nhận (tên và danh sách tham số)


def _start_line(lines: list[str], j: int) -> int:
    """Dòng đầu (tính từ 1) của hàm có đầu hàm ở chỉ số `j`."""
    if j > 0 and _NAME.match(lines[j]):
        prev = lines[j - 1]
        if prev and prev[0] not in " \t#/*}{;)" and "(" not in prev and not prev.rstrip().endswith((";", ",")):
            return j  # kiểu "static int\nName(...)": kiểu trả về nằm ở dòng trên
    return j + 1


def _same_line_head(lines: list[str], i: int) -> tuple[int, str] | None:
    """Kiểu K&R: dòng `i` kết thúc bằng `) {`. Trả (chỉ số dòng đầu hàm ở cột 0, tên), hoặc None nếu không phải đầu hàm."""
    code = _strip_comments(lines[i])
    if not code.endswith("{") or not code[:-1].rstrip().endswith(")"):
        return None
    j = i
    # Tham số xuống dòng, thụt lề. Chặn độ dài đầu hàm: nếu không, mỗi `\tif (...) {` trong thân lại lùi ngược cả thân (O(n²)).
    while j >= 0 and i - j < MAX_HEAD_LINES and lines[j].strip() and lines[j][0] in " \t":
        j -= 1
    if j < 0 or not (lines[j][:1].isalpha() or lines[j][:1] == "_"):
        return None
    header = " ".join(_strip_comments(x) for x in lines[j : i + 1])[:-1]
    if any(c in header for c in ";={}#") or header.count("(") != header.count(")"):
        return None
    m = _NAME.search(lines[j])
    return (j, m.group(1)) if m is not None and m.group(1) not in _NOT_FUNCTIONS else None


def _same_line_function(lines: list[str], i: int) -> tuple[str, int, int, str] | None:
    """Hàm K&R có `{` mở thân ở dòng `i`. Mơ hồ thì trả None (thà không sửa còn hơn kéo nhầm khoảng dòng): gặp dòng cột 0
    khác bắt đầu bằng `}` (`};`, `} else {`), hoặc đầu của một hàm KHÁC tên, trước khi thấy `}` đóng thân.
    Đầu hàm cùng tên được bỏ qua: đó là các biến thể chữ ký trong `#ifdef`/`#else`."""
    head = _same_line_head(lines, i)
    if head is None:
        return None
    j, name = head
    for k in range(i + 1, len(lines)):
        if lines[k].startswith("}"):
            if _strip_comments(lines[k]) != "}":
                return None
            sig = " ".join(" ".join(x.strip() for x in lines[j : i + 1]).split()).rstrip("{ ")[:200]
            return name, _start_line(lines, j), k + 1, sig
        other = _same_line_head(lines, k)
        if other is not None and other[1] != name:
            return None
    return None


def find_functions(lines: list[str]) -> list[tuple[str, int, int, str]]:
    """(tên, dòng đầu, dòng cuối, chữ ký) của các hàm theo quy ước cột 0; số dòng tính từ 1."""
    found: list[tuple[str, int, int, str]] = []
    n = len(lines)
    i = 0
    while i < n:
        if lines[i].rstrip() != "{":
            knr = _same_line_function(lines, i)
            if knr is None:
                i += 1
            else:
                found.append(knr)
                i = knr[2]
            continue
        # Lùi qua các dòng tham số thụt lề tới dòng đầu ở cột 0 có dấu mở ngoặc.
        j = i - 1
        while j >= 0 and (not lines[j].strip() or lines[j][0] in " \t"):
            j -= 1
        if j < 0 or lines[j][0] in "#/*})" or "(" not in "".join(lines[j:i]):
            i += 1
            continue
        head = lines[j]
        if "(" not in head and j + 1 < i:
            i += 1
            continue
        m = _NAME.search(head)
        if m is None or m.group(1) in _NOT_FUNCTIONS:
            i += 1
            continue
        start = _start_line(lines, j)
        k = i + 1
        while k < n and lines[k].rstrip() != "}":
            k += 1
        if k >= n:
            break
        sig = " ".join(" ".join(x.strip() for x in lines[j:i]).split())[:200]
        found.append((m.group(1), start, k + 1, sig))
        i = k + 1
    return found


def repair_symbols(file: str, lines: list[str], symbols: list[Symbol]) -> list[Symbol]:
    """Bổ sung hàm bị bỏ sót, kéo dài hàm bị cắt ngắn, bỏ biến 'phạm vi tệp' nằm trong thân hàm đã sửa."""
    repaired: list[tuple[int, int]] = []
    out = list(symbols)
    for name, start, end, sig in find_functions(lines):
        idx = next(
            (
                n
                for n, s in enumerate(out)
                if s[0] == file and s[1] == name and s[2] in ("function", "method") and abs(s[3] - start) <= 1
            ),
            None,
        )
        if idx is None:
            if any(s[1] == name and s[2] == "function" and s[3] <= start <= s[4] for s in out if s[0] == file):
                continue  # đã nằm trong một hàm khác: không phải định nghĩa độc lập
            out.append((file, name, "function", start, end, sig))
            repaired.append((start, end))
        elif out[idx][4] < end:
            old = out[idx]
            out[idx] = (old[0], old[1], old[2], old[3], end, old[5])
            repaired.append((start, end))
    if not repaired:
        return symbols
    return [s for s in out if not (s[2] == "variable" and any(a < s[3] <= b for a, b in repaired))]


# ---------------------------------------------------------------- tiền xử lý theo dòng
# tree-sitter dựng sai cây khi `#ifdef` cắt ngang một câu lệnh (rất thường gặp trong wolfSSL): đo ở `src/internal.c` dòng 12463,
# nhánh `#ifndef WOLFSSL_TLS13 … #else` bị ghi kéo dài tới dòng 13416, kéo theo cả hàm bị coi là "không biên dịch". Cấu trúc chỉ thị
# `#if/#elif/#else/#endif` chỉ cần quét theo dòng, nên dựng lại độc lập với cây cú pháp.

_DIRECTIVE = re.compile(r"^\s*#\s*(?P<d>ifdef|ifndef|if|elif|else|endif)\b(?P<rest>.*)$")
_PP_TOKEN = re.compile(
    r"\s*(?:(?P<num>0[xX][0-9a-fA-F]+|\d+)[uUlL]*|(?P<id>[A-Za-z_]\w*)|(?P<op>&&|\|\||==|!=|<=|>=|[!<>()]))"
)
Cond = dict[str, Any]


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/|//.*$", " ", text).strip()


def parse_pp_condition(expr: str) -> Cond:
    """Điều kiện #if/#elif thành cây JSON cùng khuôn với `builder.cond_json`; biểu thức lạ thành {"op": "unknown"}."""
    toks: list[tuple[str, str]] = []
    pos = 0
    expr = _strip_comments(expr)
    while pos < len(expr):
        m = _PP_TOKEN.match(expr, pos)
        if m is None:
            return {"op": "unknown"}
        kind = next(k for k in ("num", "id", "op") if m.group(k) is not None)
        toks.append((kind, m.group(kind)))
        pos = m.end()
    idx = 0

    def peek() -> tuple[str, str] | None:
        return toks[idx] if idx < len(toks) else None

    def take() -> tuple[str, str]:
        nonlocal idx
        t = toks[idx]
        idx += 1
        return t

    def primary() -> Cond:
        t = peek()
        if t is None:
            raise ValueError
        take()
        if t == ("op", "("):
            inner = disjunction()
            if peek() != ("op", ")"):
                raise ValueError
            take()
            return inner
        if t == ("op", "!"):
            return {"op": "not", "a": primary()}
        if t[0] == "num":
            return {"op": "num", "v": int(t[1], 0)}
        if t[0] == "id" and t[1] == "defined":
            paren = peek() == ("op", "(")
            if paren:
                take()
            name = peek()
            if name is None or name[0] != "id":
                raise ValueError
            take()
            if paren:
                if peek() != ("op", ")"):
                    raise ValueError
                take()
            return {"op": "defined", "name": name[1]}
        if t[0] == "id":
            return {"op": "ident", "name": t[1]}
        raise ValueError

    def comparison() -> Cond:
        left = primary()
        t = peek()
        if t is not None and t[0] == "op" and t[1] in ("==", "!=", "<", ">", "<=", ">="):
            take()
            return {"op": "cmp", "o": t[1], "a": left, "b": primary()}
        return left

    def conjunction() -> Cond:
        left = comparison()
        while peek() == ("op", "&&"):
            take()
            left = {"op": "and", "a": left, "b": comparison()}
        return left

    def disjunction() -> Cond:
        left = conjunction()
        while peek() == ("op", "||"):
            take()
            left = {"op": "or", "a": left, "b": conjunction()}
        return left

    try:
        out = disjunction()
    except (ValueError, IndexError):
        return {"op": "unknown"}
    return out if idx == len(toks) else {"op": "unknown"}


def preproc_branches(lines: list[str]) -> list[tuple[int, int, int, int, Cond]]:
    """(chain, idx, dòng đầu, dòng cuối, điều kiện) của mọi nhánh #if/#ifdef/#ifndef/#elif/#else, số dòng từ 1.

    Nhánh kết thúc ở dòng liền trước chỉ thị kế tiếp (#elif/#else), nhánh cuối kết thúc ở chính dòng #endif."""
    out: list[tuple[int, int, int, int, Cond]] = []
    stack: list[tuple[int, int, int, Cond]] = []  # (chain, idx, start, cond)
    chain = 0
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        first = i + 1
        if raw.lstrip().startswith("#"):
            text = raw
            while text.rstrip().endswith("\\") and i + 1 < n:
                i += 1
                text = text.rstrip()[:-1] + " " + lines[i]
            m = _DIRECTIVE.match(text)
            if m:
                d, rest = m.group("d"), _strip_comments(m.group("rest"))
                if d in ("if", "ifdef", "ifndef"):
                    chain += 1
                    if d == "if":
                        cond = parse_pp_condition(rest)
                    else:
                        name = rest.split()[0] if rest.split() else ""
                        base: Cond = {"op": "defined", "name": name} if name else {"op": "unknown"}
                        cond = {"op": "not", "a": base} if d == "ifndef" else base
                    stack.append((chain, 0, first, cond))
                elif d in ("elif", "else") and stack:
                    c, k, start, cond = stack[-1]
                    out.append((c, k, start, first - 1, cond))
                    stack[-1] = (c, k + 1, first, parse_pp_condition(rest) if d == "elif" else {"op": "else"})
                elif d == "endif" and stack:
                    c, k, start, cond = stack.pop()
                    out.append((c, k, start, first, cond))
        i += 1
    return sorted(out, key=lambda b: (b[0], b[1]))

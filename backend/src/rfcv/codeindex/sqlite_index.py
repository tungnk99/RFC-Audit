"""`SqliteCodeIndex`: cài Protocol CodeIndex trên chỉ mục do `builder` dựng. Mở chỉ đọc; nội dung tệp lấy từ chỉ mục,
nên harness không phải đọc thẳng kho mã và mọi dòng trả cho agent khớp đúng bản sao đã băm."""

from __future__ import annotations

import json
import sqlite3
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from rfcv.gates.code_gate import Reference, SymbolInfo

_FUNCTION_KINDS = ("function", "method")


def parse_build_flags(flags: Iterable[str]) -> tuple[dict[str, str], frozenset[str]]:
    """-DX, -DX=V → định nghĩa; -UX → bỏ định nghĩa. Cờ configure (--enable-…) không suy ra được macro nên bỏ qua."""
    defines: dict[str, str] = {}
    undefs: set[str] = set()
    for f in flags:
        if f.startswith("-D") and len(f) > 2:
            name, _, value = f[2:].partition("=")
            defines[name] = value or "1"
            undefs.discard(name)
        elif f.startswith("-U") and len(f) > 2:
            undefs.add(f[2:])
            defines.pop(f[2:], None)
    return defines, frozenset(undefs)


def eval_cond(c: dict[str, Any], defines: dict[str, str], undefs: frozenset[str]) -> int | bool | None:
    """Đánh giá ba trạng thái: True/False chắc chắn, None nếu phụ thuộc macro chưa biết."""
    op = c.get("op")
    if op == "else":
        return True
    if op == "defined":
        name = str(c.get("name"))
        return True if name in defines else (False if name in undefs else None)
    if op == "num":
        return int(c["v"])
    if op == "ident":
        name = str(c.get("name"))
        if name in defines:
            try:
                return int(defines[name], 0)
            except ValueError:
                return None
        return 0 if name in undefs else None
    if op == "not":
        a = eval_cond(c["a"], defines, undefs)
        return None if a is None else not bool(a)
    if op in ("and", "or"):
        a, b = eval_cond(c["a"], defines, undefs), eval_cond(c["b"], defines, undefs)
        vals = [None if v is None else bool(v) for v in (a, b)]
        if op == "and":
            return False if False in vals else (True if all(v is True for v in vals) else None)
        return True if True in vals else (False if all(v is False for v in vals) else None)
    if op == "cmp":
        a, b = eval_cond(c["a"], defines, undefs), eval_cond(c["b"], defines, undefs)
        if a is None or b is None:
            return None
        x, y = int(a), int(b)
        return {"==": x == y, "!=": x != y, ">": x > y, ">=": x >= y, "<": x < y, "<=": x <= y}[str(c["o"])]
    return None


class SqliteCodeIndex:
    def __init__(self, path: Path, *, cache_files: int = 64) -> None:
        self.path = path
        uri = f"file:{path.resolve().as_posix()}?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self._files: list[str] | None = None
        self._cache: OrderedDict[str, list[str]] = OrderedDict()
        self._cache_size = cache_files

    # ---- Protocol CodeIndex ------------------------------------------------------------------

    def files(self) -> Sequence[str]:
        if self._files is None:
            self._files = [r[0] for r in self._conn.execute("SELECT path FROM files ORDER BY path")]
        return self._files

    @staticmethod
    def _sym(row: tuple[Any, ...]) -> SymbolInfo:
        return SymbolInfo(str(row[0]), str(row[1]), str(row[2]), int(row[3]), int(row[4]), str(row[5]))

    def outline(self, file: str) -> Sequence[SymbolInfo]:
        rows = self._conn.execute(
            "SELECT file,name,kind,line_start,line_end,signature FROM symbols WHERE file=? "
            "ORDER BY line_start, line_end DESC",
            (file,),
        )
        return [self._sym(r) for r in rows]

    def lookup(self, name: str) -> Sequence[SymbolInfo]:
        rows = self._conn.execute(
            "SELECT file,name,kind,line_start,line_end,signature FROM symbols WHERE name=? "
            "ORDER BY file, line_start LIMIT 200",
            (name,),
        )
        return [self._sym(r) for r in rows]

    def symbol_in_file(self, file: str, name: str) -> SymbolInfo | None:
        row = self._conn.execute(
            "SELECT file,name,kind,line_start,line_end,signature FROM symbols WHERE file=? AND name=? "
            "ORDER BY kind='prototype', (line_end-line_start) DESC LIMIT 1",
            (file, name),
        ).fetchone()
        return self._sym(row) if row else None

    def containing_symbol(self, file: str, line: int) -> SymbolInfo | None:
        row = self._conn.execute(
            "SELECT file,name,kind,line_start,line_end,signature FROM symbols "
            "WHERE file=? AND line_start<=? AND line_end>=? AND kind NOT IN ('prototype','enumerator') "
            "ORDER BY (line_end-line_start) LIMIT 1",
            (file, line, line),
        ).fetchone()
        return self._sym(row) if row else None

    def _content(self, file: str) -> list[str]:
        if file in self._cache:
            self._cache.move_to_end(file)
            return self._cache[file]
        row = self._conn.execute("SELECT content FROM files WHERE path=?", (file,)).fetchone()
        lines: list[str] = str(row[0]).split("\n") if row and row[0] else []
        self._cache[file] = lines
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return lines

    def lines(self, file: str, start: int, end: int) -> Sequence[str]:
        src = self._content(file)
        return src[max(0, start - 1) : min(len(src), max(0, end))]

    def references(self, name: str) -> Sequence[Reference]:
        rows = self._conn.execute(
            "SELECT file,line,container,kind FROM refs WHERE name=? AND container!=? ORDER BY file, line LIMIT 1000",
            (name, name),
        )
        return [Reference(str(f), int(n), str(c), str(k)) for f, n, c, k in rows]

    def callees(self, function: str) -> Sequence[tuple[str, int]]:
        rows = self._conn.execute(
            "SELECT callee, MIN(line) AS l FROM calls WHERE caller=? GROUP BY callee ORDER BY l, callee",
            (function,),
        )
        return [(str(c), int(n)) for c, n in rows]

    def has_call_edge(self, caller: str, callee: str) -> bool:
        return (
            self._conn.execute("SELECT 1 FROM calls WHERE caller=? AND callee=? LIMIT 1", (caller, callee)).fetchone()
            is not None
        )

    # ---- khả năng tuỳ chọn -----------------------------------------------------------------------

    def line_count(self, file: str) -> int | None:
        row = self._conn.execute("SELECT nlines FROM files WHERE path=?", (file,)).fetchone()
        return int(row[0]) if row else None

    def blocks(self, file: str, line_start: int, line_end: int) -> Sequence[tuple[int, int, str]]:
        rows = self._conn.execute(
            "SELECT line_start,line_end,head FROM blocks WHERE file=? AND line_start>=? AND line_end<=? "
            "ORDER BY line_start",
            (file, line_start, line_end),
        )
        return [(int(a), int(b), str(h)) for a, b, h in rows]

    def functions(self) -> Sequence[SymbolInfo]:
        rows = self._conn.execute(
            "SELECT file,name,kind,line_start,line_end,signature FROM symbols WHERE kind IN ('function','method') "
            "ORDER BY file, line_start"
        )
        return [self._sym(r) for r in rows]

    def compiled_lines(self, file: str, flags: Iterable[str]) -> set[int] | None:
        """Dòng được biên dịch theo cờ build. None khi không có nhánh nào chắc chắn bị tắt (không đủ căn cứ để loại)."""
        defines, undefs = parse_build_flags(flags)
        rows = self._conn.execute(
            "SELECT chain,idx,line_start,line_end,cond FROM pp_branches WHERE file=? ORDER BY chain, idx", (file,)
        ).fetchall()
        disabled: set[int] = set()
        current = None
        taken = False  # đã có nhánh trước chắc chắn đúng
        all_false = True  # mọi nhánh trước chắc chắn sai
        for chain, _idx, a, b, cond in rows:
            if chain != current:
                current, taken, all_false = chain, False, True
            value = eval_cond(json.loads(cond), defines, undefs)
            truth = None if value is None else bool(value)
            if taken or truth is False:
                disabled.update(range(int(a), int(b) + 1))
            elif truth is True and all_false:
                taken = True
            if truth is not False:
                all_false = False
        if not disabled:
            return None
        total = self.line_count(file) or 0
        return set(range(1, total + 1)) - disabled

    def meta(self) -> dict[str, str]:
        return {str(k): str(v) for k, v in self._conn.execute("SELECT key, value FROM meta")}

    def manifest_entries(self) -> dict[str, str]:
        m = self.meta()
        out = {"code:index_format": m.get("format", "?"), "code:snapshot": m.get("snapshot", "?")}
        out.update({f"code:{k}": v for k, v in m.items() if k.startswith("version:")})
        return out

    def close(self) -> None:
        self._conn.close()

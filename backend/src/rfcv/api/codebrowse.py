"""Duyệt mã nguồn của một lần chạy kiểu kho Git: cây thư mục, mở tệp (có chú thích bằng chứng), tìm kiếm, nhảy tới định nghĩa.

Nguồn nội dung theo thứ tự ưu tiên: chỉ mục mã của lần chạy (`code/index.db`, đã chứa nội dung tệp, ký hiệu, tham chiếu, đồ thị gọi),
bản sao phạm vi (`code/repo`), cuối cùng là các dòng agent đã đọc trong trace. Chỉ mở tệp nằm trong phạm vi đó, không bao giờ một
đường dẫn tuỳ ý trên máy. Nội dung mã là dữ liệu KHÔNG TIN CẬY: chỉ trả về để hiển thị.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from rfcv.api import runstore
from rfcv.api.findings import analyze, build_annotations, code_lines

MAX_FILE_BYTES = 2_000_000
MAX_FILES = 50_000
WINDOW = 3000
SEARCH_BUDGET_S = 4.0
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,100}$")


class _Source:
    """Một nơi đọc mã của lần chạy: chỉ mục SQLite, thư mục sao, hoặc dòng trong trace."""

    def __init__(self, run_dir: Path, known: dict[str, dict[int, str]]) -> None:
        self.index = run_dir / "code" / "index.db"
        self.ws = (run_dir / "code" / "repo").resolve()
        self.known = known
        self.kind = "index" if self.index.is_file() else "workspace" if self.ws.is_dir() else "trace"

    def files(self) -> list[dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        if self.kind == "index":
            with runstore.ro(self.index) as c:
                for path, lang, n in c.execute(
                    "SELECT path, lang, nlines FROM files ORDER BY path LIMIT ?", (MAX_FILES,)
                ):
                    out[str(path)] = {"path": str(path), "lang": lang, "lines": int(n)}
        elif self.kind == "workspace":
            for p in sorted(self.ws.rglob("*")):
                if p.is_file() and len(out) < MAX_FILES:
                    rel = p.relative_to(self.ws).as_posix()
                    out[rel] = {"path": rel, "lang": p.suffix.lstrip("."), "lines": None}
        for path, lines in self.known.items():
            out.setdefault(
                path, {"path": path, "lang": Path(path).suffix.lstrip("."), "lines": max(lines) if lines else None}
            )
        return list(out.values())

    def text(self, path: str) -> list[str] | None:
        if self.kind == "index":
            with runstore.ro(self.index) as c:
                row = c.execute("SELECT content FROM files WHERE path=?", (path,)).fetchone()
            if row:
                return str(row[0] or "").split("\n")
        if self.kind == "workspace":
            target = (self.ws / path).resolve()
            if self.ws in target.parents and target.is_file() and target.stat().st_size <= MAX_FILE_BYTES:
                return target.read_text(encoding="utf-8", errors="replace").splitlines()
        return None

    def iter_text(self) -> Iterator[tuple[str, list[str]]]:
        for f in self.files():
            t = self.text(f["path"])
            if t is not None:
                yield f["path"], t


def _context(run_dir: Path, adapters_dir: Path | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], _Source]:
    findings = analyze(run_dir, adapters_dir)
    known = code_lines(run_dir)
    for f in findings:
        if f.get("location"):
            known.setdefault(str(f["location"]["file"]), {})
    return findings, build_annotations(findings), _Source(run_dir, known)


def tree(run_dir: Path, adapters_dir: Path | None = None) -> dict[str, Any]:
    _, anns, src = _context(run_dir, adapters_dir)
    out: list[dict[str, Any]] = []
    for f in src.files():
        mine = [a for a in anns if a["file"] == f["path"]]
        out.append(
            {
                **f,
                "annotations": len(mine),
                "bad": sum(a["severity"] == "bad" for a in mine),
                "read": len(src.known.get(f["path"], {})),
                "full": src.kind != "trace",
            }
        )
    out.sort(key=lambda x: (-x["bad"], -x["annotations"], -x["read"], x["path"]))
    return {"source": src.kind, "files": out}


def file(
    run_dir: Path,
    path: str,
    adapters_dir: Path | None = None,
    start: int | None = None,
    end: int | None = None,
    around: int | None = None,
) -> dict[str, Any] | None:
    findings, anns, src = _context(run_dir, adapters_dir)
    if path not in {f["path"] for f in src.files()}:
        return None
    text = src.text(path)
    read = sorted(src.known.get(path, {}))
    if text is None:  # chỉ có dòng agent đã đọc
        all_lines = [{"n": n, "text": t} for n, t in sorted(src.known.get(path, {}).items())]
        total = len(all_lines)
        win = all_lines
        lo, hi = (win[0]["n"], win[-1]["n"]) if win else (1, 0)
        source = "trace"
    else:
        total = len(text)
        if around is not None and start is None:
            start = max(1, around - WINDOW // 2)
        lo = max(1, start or 1)
        hi = min(total, end if end is not None else lo + WINDOW - 1)
        win = [{"n": i, "text": text[i - 1]} for i in range(lo, hi + 1)]
        source = src.kind
    hits: set[int] = set()
    for f in findings:
        if f.get("location") and f["location"]["file"] == path:
            hits |= set(f["coverage"]["lines_hit"])
    symbols: list[dict[str, Any]] = []
    if src.kind == "index":
        with runstore.ro(src.index) as c:
            for name, kind, ls, le, sig in c.execute(
                "SELECT name, kind, line_start, line_end, signature FROM symbols WHERE file=? AND kind NOT IN ('enumerator') ORDER BY line_start LIMIT 800",
                (path,),
            ):
                symbols.append({"name": name, "kind": kind, "line_start": ls, "line_end": le, "signature": sig})
    return {
        "path": path,
        "source": source,
        "total": total,
        "start": lo,
        "end": hi,
        "lines": win,
        "hits": sorted(hits),
        "read": read,
        "symbols": symbols,
        "annotations": [a for a in anns if a["file"] == path],
    }


def search(run_dir: Path, q: str, adapters_dir: Path | None = None) -> dict[str, Any]:
    """Tìm tên tệp và nội dung (không phân biệt hoa thường, chuỗi con). Có giới hạn thời gian và số kết quả."""
    q = q.strip()
    if len(q) < 2:
        return {"files": [], "matches": [], "truncated": False}
    _, _, src = _context(run_dir, adapters_dir)
    low = q.lower()
    names = [f["path"] for f in src.files() if low in f["path"].lower()][:100]
    matches: list[dict[str, Any]] = []
    t0, truncated = time.monotonic(), False
    for path, lines in src.iter_text():
        for i, line in enumerate(lines, 1):
            if low in line.lower():
                matches.append({"path": path, "line": i, "text": line.strip()[:200]})
        if len(matches) >= 300 or time.monotonic() - t0 > SEARCH_BUDGET_S:
            truncated = True
            break
    return {"files": names, "matches": matches[:300], "truncated": truncated}


def symbol(run_dir: Path, name: str, adapters_dir: Path | None = None) -> dict[str, Any]:
    """Định nghĩa, tham chiếu, nơi gọi và hàm được gọi của một ký hiệu, từ chỉ mục mã của lần chạy."""
    out: dict[str, Any] = {
        "name": name,
        "definitions": [],
        "references": [],
        "callers": [],
        "callees": [],
        "indexed": False,
    }
    index = run_dir / "code" / "index.db"
    if not _IDENT.match(name) or not index.is_file():
        return out
    out["indexed"] = True
    with runstore.ro(index) as c:
        out["definitions"] = [
            {"file": f, "kind": k, "line_start": a, "line_end": b, "signature": s}
            for f, k, a, b, s in c.execute(
                "SELECT file, kind, line_start, line_end, signature FROM symbols WHERE name=? ORDER BY kind='prototype', file, line_start LIMIT 50",
                (name,),
            )
        ]
        out["references"] = [
            {"file": f, "line": n, "container": ct, "kind": k}
            for f, n, ct, k in c.execute(
                "SELECT file, line, container, kind FROM refs WHERE name=? ORDER BY file, line LIMIT 100", (name,)
            )
        ]
        out["callers"] = [
            {"caller": a, "file": f, "line": n}
            for a, f, n in c.execute(
                "SELECT caller, file, line FROM calls WHERE callee=? ORDER BY file, line LIMIT 100", (name,)
            )
        ]
        out["callees"] = [
            {"callee": b, "line": n}
            for b, n in c.execute(
                "SELECT callee, MIN(line) FROM calls WHERE caller=? GROUP BY callee ORDER BY 2 LIMIT 100", (name,)
            )
        ]
    return out

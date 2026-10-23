"""Chấm độ đúng của vị trí lỗi mà hệ thống chỉ ra, so với hunk của bản vá thật (nhãn chuẩn độc lập).

    uv run python scripts/eval_locate_score.py <run_dir> --repo eval/work/wolfssl --fix c18833f52

Nhãn chuẩn: các khoảng dòng PHÍA CŨ (bản lỗi) bị bản vá sửa trong từng tệp (`git diff -U0 <fix>^ <fix>`). Một T1 "trúng" khi
- tiêu đề (`file`, `line_start`–`line_end`) giao với hunk, hoặc
- ít nhất một khía cạnh có `lines` giao với hunk (vị trí chính nằm ở nơi khác nhưng khía cạnh chỉ đúng chỗ lỗi).
Tách hai mức vì người đọc báo cáo cần chỗ lỗi, không chỉ chỗ có liên quan.
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

_HUNK = re.compile(r"^@@ -(?P<a>\d+)(?:,(?P<n>\d+))? \+")


def hunks(repo: Path, fix: str) -> dict[str, list[tuple[int, int]]]:
    out = subprocess.run(
        ["git", "-C", str(repo), "diff", "-U0", f"{fix}^", fix],
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    ).stdout
    result: dict[str, list[tuple[int, int]]] = {}
    current: str | None = None
    for line in out.splitlines():
        if line.startswith("--- a/"):
            current = line[6:]
        elif (m := _HUNK.match(line)) and current is not None:
            start, count = int(m.group("a")), int(m.group("n") or 1)
            result.setdefault(current, []).append((start, start + max(count, 1) - 1))
    return result


def overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def score(run_dir: Path, truth: dict[str, list[tuple[int, int]]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    conn = sqlite3.connect(run_dir / "evidence.db")
    for (body,) in conn.execute("SELECT body FROM evidence WHERE tier='T1'"):
        p = json.loads(body).get("payload", {})
        file = p.get("file")
        spans = truth.get(str(file), [])
        head = (p["line_start"], p["line_end"])
        aspects = [(a["aspect"], tuple(a["lines"])) for a in p.get("aspects", [])]
        defect = tuple(p["defect_lines"]) if p.get("defect_lines") else None
        rows.append(
            {
                "file": file,
                "symbol": p.get("symbol"),
                "headline": head,
                "headline_hit": any(overlaps(head, s) for s in spans),
                "defect_symbol": p.get("defect_symbol"),
                "defect_hit": defect is not None and any(overlaps(defect, s) for s in spans),
                "aspect_hits": [name for name, ln in aspects if any(overlaps(ln, s) for s in spans)],
                "disabled_by": p.get("disabled_by", []),
                "truth": spans,
            }
        )
    return rows


def main(argv: list[str]) -> int:
    if len(argv) < 6 or argv[2] != "--repo" or argv[4] != "--fix":
        print(__doc__)
        return 2
    truth = hunks(Path(argv[3]), argv[5])
    for row in score(Path(argv[1]), truth):
        print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

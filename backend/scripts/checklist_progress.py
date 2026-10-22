"""Đếm tiến độ các checklist deliverable trong docs/05_project/ (xem docs/05_project/README.md).

    uv run python scripts/checklist_progress.py            # bảng tiến độ từng checklist và tổng
    uv run python scripts/checklist_progress.py --open     # liệt kê cả các hạng mục chưa xong

Đếm các dòng dạng `- [x]` (xong) và `- [ ]` (chưa xong) ở mọi cấp thụt lề. Chỉ đọc tệp, không sửa gì.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ITEM = re.compile(r"^\s*- \[([ xX])\] (.*)$")


def main() -> None:
    show_open = "--open" in sys.argv
    rows: list[tuple[str, int, int]] = []
    pending: list[tuple[str, str]] = []
    for md in sorted((ROOT.parent / "docs" / "05_project").glob("checklist_*.md")):
        done = total = 0
        in_code = False
        for line in md.read_text(encoding="utf-8").splitlines():
            if line.startswith("```"):
                in_code = not in_code
            m = None if in_code else ITEM.match(line)
            if not m:
                continue
            total += 1
            if m.group(1) in "xX":
                done += 1
            else:
                pending.append((md.stem, re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", m.group(2))[:110]))
        rows.append((md.stem, done, total))
    print(f"{'checklist':<34} {'xong':>5} {'tổng':>5} {'tỉ lệ':>6}")
    for name, done, total in rows:
        print(f"{name:<34} {done:>5} {total:>5} {done / total:>6.0%}" if total else f"{name:<34} {'-':>5} {'-':>5}")
    d, t = sum(r[1] for r in rows), sum(r[2] for r in rows)
    print(f"{'TỔNG':<34} {d:>5} {t:>5} {d / t:>6.0%}" if t else "không có hạng mục nào")
    if show_open:
        print("\nChưa xong:")
        for name, text in pending:
            print(f"  [{name.removeprefix('checklist_')}] {text}")


if __name__ == "__main__":
    main()

"""Tiến độ backlog công việc (docs/management/theo_doi_backlog.md): đếm việc theo trạng thái, giai đoạn và nhóm.

    uv run python scripts/backlog_progress.py              # bảng tổng hợp
    uv run python scripts/backlog_progress.py --next       # các việc nên làm kế tiếp: chưa làm, mọi phụ thuộc đã Xong, giai đoạn sớm nhất

Chỉ đọc tệp, không sửa gì.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKLOG = ROOT / "docs" / "management" / "theo_doi_backlog.md"
PHASE_ORDER = ["Ngay", "G1", "G2", "DNS", "G3", "LV", "T2"]
STATUS_ORDER = ["Xong", "Đang làm", "Chặn", "Chưa làm"]
PIPE = re.compile(r"(?<!\\)\|")


def load() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    epic = ""
    for line in BACKLOG.read_text(encoding="utf-8").splitlines():
        if line.startswith("## EP-"):
            epic = line.removeprefix("## ").split(".", 1)[0]
        m = re.match(r"^\| (BL-\d+) \|", line)
        if m:
            c = [x.strip() for x in PIPE.split(line.strip().strip("|"))]
            items.append(
                {"id": c[0], "task": c[1], "needs": c[3], "size": c[4], "phase": c[5], "status": c[7], "epic": epic}
            )
    return items


def main() -> None:
    items = load()
    done = {i["id"] for i in items if i["status"] == "Xong"}
    if "--next" in sys.argv:
        ready = [
            i
            for i in items
            if i["status"] == "Chưa làm"
            and i["phase"] != "T2"  # tầng 2 và 3 chỉ làm khi G2 đạt sớm, không phải việc "bắt đầu ngay"
            and all(d in done for d in re.findall(r"BL-\d+", i["needs"]))
        ]
        ready.sort(key=lambda i: (PHASE_ORDER.index(i["phase"]), i["id"]))
        print(
            "Việc có thể bắt đầu ngay (chưa làm, phụ thuộc đã xong, không tính giai đoạn T2 có điều kiện), theo giai đoạn:"
        )
        for i in ready:
            print(f"  {i['phase']:<5} {i['id']}  [{i['size']}]  {i['task'][:90]}")
        return
    by_status = Counter(i["status"] for i in items)
    print("Theo trạng thái:", ", ".join(f"{s} {by_status.get(s, 0)}" for s in STATUS_ORDER), f"| tổng {len(items)}")
    print(f"\n{'giai đoạn':<10} " + " ".join(f"{s:>9}" for s in STATUS_ORDER) + f" {'tổng':>6}")
    for ph in PHASE_ORDER:
        sub = [i for i in items if i["phase"] == ph]
        c = Counter(i["status"] for i in sub)
        print(f"{ph:<10} " + " ".join(f"{c.get(s, 0):>9}" for s in STATUS_ORDER) + f" {len(sub):>6}")
    print(f"\n{'nhóm':<8} {'xong / tổng':>12}")
    for epic in sorted({i["epic"] for i in items}, key=lambda e: int(e.split("-")[1])):
        sub = [i for i in items if i["epic"] == epic]
        print(f"{epic:<8} {sum(i['status'] == 'Xong' for i in sub):>5} / {len(sub):<5}")


if __name__ == "__main__":
    main()

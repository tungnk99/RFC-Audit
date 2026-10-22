"""Lọc lịch sử commit wolfSSL thành danh sách ứng viên lỗi thật (tài liệu khả thi mục 3, thiết kế đánh giá 4.2).

Chỉ dùng thư viện chuẩn + git. Đầu ra là CSV để người lọc tay; script KHÔNG quyết định commit nào là lỗi tuân thủ.

    python scripts/eval_collect_wolfssl_commits.py --repo eval/work/wolfssl --out eval/dataset/real/wolfssl_commit_ung_vien.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parents[1] / "eval" / "config" / "eval.yaml"
FIELDS = [
    "sha", "parent", "date", "split", "subject", "keywords", "files", "touches_src", "touches_tests",
    "type", "keep", "requirement", "notes",
]
SRC_RE = re.compile(r"^(src|wolfssl)/")
TEST_RE = re.compile(r"(^|/)(tests?|scripts)/|(^|/)test[^/]*\.[ch]$|unit\.test", re.IGNORECASE)
SEP, REC = "\x1f", "\x1e"


def git(repo: Path, *args: str) -> str:
    exe = os.environ.get("RFCV_GIT", "git")
    out = subprocess.run([exe, "-C", str(repo), *args], capture_output=True, check=True)
    return out.stdout.decode("utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--rev", default="HEAD")
    a = ap.parse_args()

    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    cutoff = date.fromisoformat(cfg["knowledge_cutoff"])
    kws = [k.lower() for k in cfg["commit_keywords"]]

    fmt = SEP.join(["%H", "%P", "%cs", "%s", "%B"]) + REC
    raw = git(a.repo, "log", a.rev, "--no-merges", f"--since={cfg['window']['since']}",
              f"--until={cfg['window']['until']}", f"--format={fmt}")
    rows: list[dict[str, object]] = []
    for rec in filter(None, (r.strip("\n") for r in raw.split(REC))):
        sha, parents, day, subject, body = rec.split(SEP, 4)
        hits = sorted({k for k in kws if k in f"{subject}\n{body}".lower()})
        if not hits:
            continue
        files = [f for f in git(a.repo, "show", "--no-renames", "--name-only", "--format=", sha).splitlines() if f]
        rows.append({
            "sha": sha, "parent": parents.split()[0] if parents else "", "date": day,
            "split": "eval" if date.fromisoformat(day) >= cutoff else "dev",
            "subject": subject, "keywords": ";".join(hits), "files": len(files),
            "touches_src": int(any(SRC_RE.match(f) for f in files)),
            "touches_tests": int(any(TEST_RE.search(f) for f in files)),
            "type": "", "keep": "", "requirement": "", "notes": "",
        })

    rows.sort(key=lambda r: str(r["date"]))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    n_eval = sum(r["split"] == "eval" for r in rows)
    n_test = sum(bool(r["touches_tests"]) for r in rows)
    print(f"{len(rows)} commit ứng viên; {n_test} có test; {n_eval} thuộc tập đánh giá (>= {cutoff}) -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

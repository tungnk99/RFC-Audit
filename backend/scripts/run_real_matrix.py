"""Chạy tuần tự bug → fix → head trên SUT thật và ghi bảng so sánh giữa các đợt (thay các `go.sh` tạm).

    uv run python scripts/run_real_matrix.py --out runs/real/out10 [--suffix ""] [--versions bug fix head]

Mỗi phiên bản: `rfcv run` (RBS của adapter `eval/adapters/tls13-<v><suffix>`), rồi đọc kết quả từ thư mục lần chạy:
nhãn, quy tắc, assurance, số vòng, token, lần gọi công cụ, token Code Reader, T1 có trúng hunk bản vá không (`eval_locate_score`).
Ghi `matrix.csv` và in bảng. Không sửa tay kết quả. Nhớ tắt chế độ ngủ của máy trước khi chạy dài.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import eval_locate_score

BACKEND = Path(__file__).resolve().parent.parent
FIX_COMMIT = "c18833f52"
EXPECTED = {"bug": "VIOLATION", "fix": "COMPLIANT", "head": "COMPLIANT"}


def run_one(version: str, suffix: str, out: Path) -> dict[str, object]:
    cmd = [
        "uv", "run", "--env-file", ".env", "rfcv", "run",
        "--adapter", f"eval/adapters/tls13-{version}{suffix}",
        "--code-root", f"runs/real/src/wolfssl-{version}",
        "--code-index", "treesitter", "--executor", "docker", "--sut-launcher", "docker",
        "--models", "config/models.yaml", "--run-dir", str(out),
    ]  # fmt: skip
    proc = subprocess.run(
        cmd, cwd=BACKEND, capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"}
    )
    (out / f"{version}.json").write_text(proc.stdout, encoding="utf-8")
    (out / f"{version}.err").write_text(proc.stderr, encoding="utf-8")
    try:
        result = json.loads(proc.stdout)
    except ValueError:
        return {"version": version, "error": f"rfcv thoát mã {proc.returncode}, không có JSON"}
    verdict = result["verdicts"][0]
    run_dir = out / result["run_id"]
    row: dict[str, object] = {
        "version": version,
        "run_id": result["run_id"],
        "label": verdict["label"],
        "rule": verdict["rule"],
        "assurance": verdict.get("assurance") or "",
        "expected": EXPECTED[version],
        "correct": verdict["label"] == EXPECTED[version],
    }
    row.update(trace_metrics(run_dir))
    if version == "bug":
        truth = eval_locate_score.hunks(BACKEND / "eval" / "work" / "wolfssl", FIX_COMMIT)
        scored = eval_locate_score.score(run_dir, truth)
        row["defect_hit"] = any(bool(s["defect_hit"]) for s in scored)
        row["headline_hit"] = any(bool(s["headline_hit"]) for s in scored)
    return row


def trace_metrics(run_dir: Path) -> dict[str, object]:
    conn = sqlite3.connect(run_dir / "trace.db")
    metrics: dict[str, object] = {"rounds": "", "tokens": "", "tool_calls": "", "code_reader_tokens": 0}
    for (payload,) in conn.execute("SELECT payload FROM events WHERE kind='stop'"):
        used = json.loads(payload).get("used", {})
        metrics.update(rounds=used.get("rounds"), tokens=used.get("tokens"), tool_calls=used.get("tool_calls"))
    for (payload,) in conn.execute("SELECT payload FROM events WHERE kind='role_run'"):
        d = json.loads(payload)
        if d.get("role") == "code_reader":
            metrics["code_reader_tokens"] = int(str(metrics["code_reader_tokens"])) + int(d.get("tokens") or 0)
    return metrics


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--suffix", default="", help='"" (RBS gốc) hoặc "-b" (RBS tinh chỉnh)')
    ap.add_argument("--versions", nargs="+", default=["bug", "fix", "head"], choices=sorted(EXPECTED))
    args = ap.parse_args()
    out = BACKEND / args.out
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for version in args.versions:
        row = run_one(version, args.suffix, out)
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    fields = sorted({k for r in rows for k in r}, key=lambda k: (k != "version", k))
    with (out / "matrix.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return 0 if all(r.get("correct") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())

"""Thí nghiệm đối chứng Ablation (Chặng A — gen-40, xử lý mục D5 🔴 trong han_che_he_thong.md).

So sánh định lượng 3 cấu hình trên cùng 6 ca VIOLATION khó của OpenSSL (`OU2, OU3, OG1, OG2, OG4, OR1`)
cùng mô hình `DeepSeek-V4-Flash` và cùng hạ tầng Docker:
  - `C0` (`full`):         T3 + Chẩn đoán hành vi (`behavior.diagnosis`/`code.candidates`) + Giải đấu 2 nhánh + Chấm điểm `obs_in_source`
  - `A1` (`single_branch`): T3 + Chẩn đoán hành vi + **1 tác tử Code Reader đơn** (bỏ giải đấu 2 nhánh & chấm điểm nhánh)
  - `A2` (`no_diagnosis`):  T3 + **1 tác tử Code Reader đơn mù** (bỏ cả chẩn đoán hành vi, `code.candidates`, lẫn giải đấu 2 nhánh)

Cách dùng:
    uv run python scripts/run_ablation_d5.py --modes single_branch no_diagnosis
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
ITEMS = ["OU2", "OU3", "OG1", "OG2", "OG4", "OR1"]
YAML_PATH = BACKEND / "eval" / "dataset" / "mutants" / "mutants_openssl.yaml"


def run_mode(mode: str, out_root: Path) -> dict[str, object]:
    out_dir = out_root / f"ablation_{mode}"
    env = os.environ.copy()
    env["RFCV_ABLATION"] = "" if mode == "full" else mode
    cmd = [
        sys.executable,
        str(BACKEND / "scripts" / "run_protocol_matrix.py"),
        "--yaml",
        str(YAML_PATH),
        "--out",
        str(out_dir),
        "--items",
        *ITEMS,
    ]
    print(f"\n=== Running Ablation Mode: {mode} ({len(ITEMS)} OpenSSL cases) ===", flush=True)
    subprocess.run(cmd, cwd=BACKEND, env=env, check=True)
    summary_txt = (out_dir / "summary.txt").read_text(encoding="utf-8") if (out_dir / "summary.txt").exists() else ""
    return {"mode": mode, "out_dir": str(out_dir), "summary": summary_txt}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", nargs="+", default=["single_branch", "no_diagnosis"])
    ap.add_argument("--out", default="runs/real/ablation_d5_gen40")
    args = ap.parse_args()
    out_root = BACKEND / args.out
    out_root.mkdir(parents=True, exist_ok=True)
    results = [run_mode(m, out_root) for m in args.modes]
    (out_root / "ablation_report.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n=== ABLATION D5 COMPLETE ===", flush=True)
    for r in results:
        print(f"\n--- {r['mode']} ---\n{r['summary']}", flush=True)


if __name__ == "__main__":
    main()

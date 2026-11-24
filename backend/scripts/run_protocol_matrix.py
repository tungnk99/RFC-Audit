"""Chạy ma trận đánh giá đa giao thức (HTTP/2, DNS, SSH, QUIC) từ tệp mutants_<proto>.yaml.

Cách dùng:
    uv run python scripts/run_protocol_matrix.py --yaml eval/dataset/mutants/mutants_http2.yaml --out runs/real/proto_http2_mgen1
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import run_real_matrix as rrm

from rfcv.eval.metrics import wilson_interval

BACKEND = Path(__file__).resolve().parent.parent


def load_items(yaml_path: Path) -> list[rrm.Item]:
    data: dict[str, Any] = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    out: list[rrm.Item] = []
    for m in data["items"]:
        if m.get("excluded"):
            continue
        loc = m.get("fix_location") or {}
        files = loc.get("files", {})
        truth = (
            {f: [(int(a), int(b)) for a, b in spans] for f, spans in files.items()}
            if m["expected"] == "VIOLATION" and files
            else None
        )
        out.append(rrm.Item(m["id"], m["adapter"], m["code_root"], m["expected"], truth, m.get("family", "P")))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaml", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--items", nargs="*")
    ap.add_argument("--effort", default="efficient", choices=("efficient", "thorough"))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    items = load_items(Path(args.yaml))
    if args.items:
        want = set(args.items)
        items = [it for it in items if it.id in want]

    rows: list[dict[str, object]] = []
    for it in items:
        row = rrm.run_one(it, out, args.effort)
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    fields = [
        "item", "family", "run_id", "expected", "label", "rule", "assurance", "correct",
        "effort", "rounds", "tokens", "tool_calls", "all_role_tokens", "seconds",
        "defect_hit", "defect_hit_strict", "error",
    ]  # fmt: skip
    with (out / "matrix.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    viols = [r for r in rows if r["expected"] == "VIOLATION"]
    comps = [r for r in rows if r["expected"] == "COMPLIANT"]
    fc = sum(1 for r in viols if r["label"] == "COMPLIANT")
    fv = sum(1 for r in comps if r["label"] == "VIOLATION")
    tp = sum(1 for r in viols if r["label"] == "VIOLATION")
    tn = sum(1 for r in comps if r["label"] == "COMPLIANT")
    hits = sum(1 for r in viols if r.get("defect_hit"))
    strict = sum(1 for r in viols if r.get("defect_hit_strict"))

    def fmt(k: int, d: int) -> str:
        if d == 0:
            return "n/a"
        lo, hi = wilson_interval(k, d)
        return f"{k}/{d} = {k / d:.1%} (Wilson 95%: {lo:.0%}-{hi:.0%})"

    summary = "\n".join(
        [
            f"=== {Path(args.yaml).stem} (n={len(rows)}, VIOLATION={len(viols)}, COMPLIANT={len(comps)}) ===",
            f"  Verdict accuracy:   {fmt(tp + tn, len(rows))}",
            f"  False COMPLIANT:    {fmt(fc, len(viols))}",
            f"  False VIOLATION:    {fmt(fv, len(comps))}",
            f"  Recall VIOLATION:   {fmt(tp, len(viols))}",
            f"  COMPLIANT correct:  {fmt(tn, len(comps))}",
            f"  Defect hit:         {fmt(hits, len(viols))}",
            f"  Defect hit STRICT:  {fmt(strict, len(viols))}",
        ]
    )
    (out / "summary.txt").write_text(summary + "\n", encoding="utf-8")
    print("\n" + summary, flush=True)


if __name__ == "__main__":
    main()

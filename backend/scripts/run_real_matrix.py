"""Chạy tuần tự các mục đánh giá trên SUT thật, ghi bảng kết quả và tổng hợp chỉ số (CH1) kèm khoảng tin cậy Wilson.

    uv run python scripts/run_real_matrix.py --out runs/real/out20                      # bug fix head + mọi mutant
    uv run python scripts/run_real_matrix.py --out runs/real/out20 --items M1 M2 --effort thorough

Mục gồm ba phiên bản thật (bug, fix, head) và các mutant trong `eval/dataset/mutants/mutants.yaml` (nhãn chuẩn chốt trước khi chạy,
xem `scripts/eval_make_mutants.py`). Mỗi mục: `rfcv run`, rồi đọc nhãn, quy tắc, token, vòng, thời gian, và với mục VIOLATION: T1 có trúng
vị trí sửa không (`defect_hit` theo hunk bản vá hoặc dòng bị đột biến). Ghi `matrix.csv`; không sửa tay kết quả. Tắt chế độ ngủ của máy
trước khi chạy dài.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import eval_locate_score

from rfcv.eval.metrics import wilson_interval

BACKEND = Path(__file__).resolve().parent.parent
MUTANT_FILES = {
    "0042": BACKEND / "eval" / "dataset" / "mutants" / "mutants.yaml",
    "multi": BACKEND / "eval" / "dataset" / "mutants" / "mutants_multi.yaml",
    "openssl": BACKEND / "eval" / "dataset" / "mutants" / "mutants_openssl.yaml",
}
FIX_COMMIT = "c18833f52"


@dataclass(frozen=True)
class Item:
    id: str
    adapter: str
    code_root: str
    expected: str
    truth: dict[str, list[tuple[int, int]]] | None  # nơi sửa (nhãn chuẩn định vị) cho mục VIOLATION
    family: str = "R"  # họ yêu cầu: R (độ dài bản ghi), U (loại bản ghi lạ), G (không có nhóm chung)


def real_items(suffix: str) -> list[Item]:
    hunks = eval_locate_score.hunks(BACKEND / "eval" / "work" / "wolfssl", FIX_COMMIT)
    return [
        Item("bug", f"eval/adapters/tls13-bug{suffix}", "runs/real/src/wolfssl-bug", "VIOLATION", hunks),
        Item("fix", f"eval/adapters/tls13-fix{suffix}", "runs/real/src/wolfssl-fix", "COMPLIANT", None),
        Item("head", f"eval/adapters/tls13-head{suffix}", "runs/real/src/wolfssl-head", "COMPLIANT", None),
    ]


# Cặp lỗi thật đã chốt nhãn (cha = VIOLATION, bản vá = COMPLIANT): (họ, sha ngắn của bản vá, 12 ký tự đầu của cha, 12 ký tự đầu của bản vá)
REAL_PAIRS = (
    ("P1", "U", "4b30475a4", "24f0f95f5f2b", "4b30475a4934"),
    ("P3", "G", "d3abc288e", "9e0d3894d285", "d3abc288e68c"),
)


def pair_items() -> list[Item]:
    out: list[Item] = []
    for name, fam, fix, parent12, fix12 in REAL_PAIRS:
        hunks = eval_locate_score.hunks(BACKEND / "eval" / "work" / "wolfssl", fix)
        out.append(Item(f"{name}-parent", f"eval/adapters/tls13-{parent12}", f"runs/real/src/wolfssl-{parent12}", "VIOLATION", hunks, fam))
        out.append(Item(f"{name}-fix", f"eval/adapters/tls13-{fix12}", f"runs/real/src/wolfssl-{fix12}", "COMPLIANT", None, fam))
    return out


def mutant_items(sets: tuple[str, ...] = ("0042", "multi", "openssl")) -> list[Item]:
    out: list[Item] = []
    for name in sets:
        path = MUTANT_FILES[name]
        if not path.is_file():
            continue
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
        for m in data["items"]:
            if m.get("excluded"):  # mutant có thêm mã mới: không thuộc bộ đánh giá
                continue
            loc = m["fix_location"]
            files = loc["files"] if "files" in loc else {loc["file"]: loc["lines"]}
            truth = {f: [(int(a), int(b)) for a, b in spans] for f, spans in files.items()} if m["expected"] == "VIOLATION" else None
            out.append(Item(m["id"], m["adapter"], m["code_root"], m["expected"], truth, m.get("family", "R")))
    return out


def run_one(item: Item, out: Path, effort: str) -> dict[str, object]:
    cmd = [
        "uv", "run", "--env-file", ".env", "rfcv", "run",
        "--adapter", item.adapter, "--code-root", item.code_root,
        "--code-index", "treesitter", "--executor", "docker", "--sut-launcher", "docker",
        "--models", "config/models.yaml", "--run-dir", str(out), "--effort", effort, "--rfc-dir", "inputs/rfc",
    ]  # fmt: skip
    proc = subprocess.run(
        cmd, cwd=BACKEND, capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"}
    )
    (out / f"{item.id}.json").write_text(proc.stdout, encoding="utf-8")
    (out / f"{item.id}.err").write_text(proc.stderr, encoding="utf-8")
    try:
        result = json.loads(proc.stdout)
    except ValueError:
        return {
            "item": item.id,
            "family": item.family,
            "expected": item.expected,
            "label": "ERROR",
            "correct": False,
            "error": f"rfcv thoát mã {proc.returncode}",
        }
    verdict = result["verdicts"][0]
    run_dir = out / result["run_id"]
    row: dict[str, object] = {
        "item": item.id,
        "family": item.family,
        "run_id": result["run_id"],
        "expected": item.expected,
        "label": verdict["label"],
        "rule": verdict["rule"],
        "assurance": verdict.get("assurance") or "",
        "correct": verdict["label"] == item.expected,
        "effort": effort,
    }
    row.update(trace_metrics(run_dir))
    if item.truth is not None:
        scored = eval_locate_score.score(run_dir, item.truth)
        row["defect_hit"] = any(
            bool(s["defect_hit"]) or bool(s["headline_hit"]) or bool(s["aspect_hits"]) for s in scored
        )
        row["defect_hit_strict"] = any(bool(s["defect_hit"]) for s in scored)
    return row


def trace_metrics(run_dir: Path) -> dict[str, object]:
    conn = sqlite3.connect(run_dir / "trace.db")
    metrics: dict[str, object] = {"rounds": "", "tokens": "", "tool_calls": "", "all_role_tokens": 0, "seconds": ""}
    for (payload,) in conn.execute("SELECT payload FROM events WHERE kind='stop'"):
        used = json.loads(payload).get("used", {})
        metrics.update(rounds=used.get("rounds"), tokens=used.get("tokens"), tool_calls=used.get("tool_calls"))
    total = 0
    for (payload,) in conn.execute("SELECT payload FROM events WHERE kind='role_run'"):
        total += int(json.loads(payload).get("tokens") or 0)
    metrics["all_role_tokens"] = total
    ts = [r[0] for r in conn.execute("SELECT ts_ns FROM events ORDER BY seq")]
    if ts:
        metrics["seconds"] = round((ts[-1] - ts[0]) / 1e9)
    return metrics


def summarize(rows: list[dict[str, object]]) -> str:
    """Chỉ số CH1 (bảng 8 của tài liệu đánh giá) trên các mục đã chạy."""
    pos = [r for r in rows if r["expected"] == "VIOLATION"]
    neg = [r for r in rows if r["expected"] == "COMPLIANT"]
    decided = [r for r in rows if r["label"] in ("VIOLATION", "COMPLIANT")]
    tp = sum(1 for r in pos if r["label"] == "VIOLATION")
    false_compliant = sum(1 for r in pos if r["label"] == "COMPLIANT")
    false_violation = sum(1 for r in neg if r["label"] == "VIOLATION")
    right_neg = sum(1 for r in neg if r["label"] == "COMPLIANT")
    hits = sum(1 for r in pos if r["label"] == "VIOLATION" and r.get("defect_hit"))

    def ci(k: int, n: int) -> str:
        if n == 0:
            return "n/a"
        lo, hi = wilson_interval(k, n)
        return f"{k}/{n} = {k / n:.0%} (Wilson 95%: {lo:.0%}-{hi:.0%})"

    by_family: list[str] = []
    for fam in sorted({str(r.get("family", "R")) for r in rows}):
        sub = [r for r in rows if str(r.get("family", "R")) == fam]
        ok = sum(1 for r in sub if r.get("correct"))
        by_family.append(f"  họ {fam}: đúng {ok}/{len(sub)}")
    return "\n".join(
        [
            "Theo họ yêu cầu:",
            *by_family,
            f"Số mục: {len(rows)} (VIOLATION chuẩn {len(pos)}, COMPLIANT chuẩn {len(neg)})",
            f"COMPLIANT sai (bỏ sót lỗi): {ci(false_compliant, len(pos))}",
            f"VIOLATION sai (báo nhầm):   {ci(false_violation, len(neg))}",
            f"Recall VIOLATION:          {ci(tp, len(pos))}",
            f"Precision VIOLATION:       {ci(tp, tp + false_violation)}",
            f"COMPLIANT đúng:            {ci(right_neg, len(neg))}",
            f"Kết luận được (C hoặc V):  {ci(len(decided), len(rows))}",
            f"Định vị trúng chỗ sửa (trong VIOLATION đã phát hiện): {ci(hits, tp)}",
        ]
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--suffix", default="", help='"" (RBS gốc) hoặc "-b" (RBS tinh chỉnh) cho bug/fix/head')
    ap.add_argument("--items", nargs="*", default=None, help="id mục; mặc định tất cả")
    ap.add_argument("--effort", default="efficient", choices=["efficient", "thorough"])
    ap.add_argument(
        "--set", default="all", choices=["all", "0042", "multi", "openssl", "pairs"],
        help="all: bug/fix/head + mutant TLS13-0042 + mutant đa họ; 0042: bộ cũ; multi: chỉ mutant đa họ (U/G/R9+)",
    )  # fmt: skip
    args = ap.parse_args()
    out = BACKEND / args.out
    out.mkdir(parents=True, exist_ok=True)
    if args.set in ("multi", "openssl"):
        items = mutant_items((args.set,))
    elif args.set == "pairs":
        items = pair_items()
    elif args.set == "0042":
        items = [*real_items(args.suffix), *mutant_items(("0042",))]
    else:
        items = [*real_items(args.suffix), *pair_items(), *mutant_items()]
    if args.items:
        by_id = {i.id: i for i in items}
        picked: list[Item] = []
        for wanted in args.items:
            base = wanted.removesuffix("-b")
            if wanted in by_id:
                picked.append(by_id[wanted])
            elif wanted.endswith("-b") and base in by_id:  # RBS tinh chỉnh của mutant: adapter `<id>-b`
                picked.append(replace(by_id[base], id=wanted, adapter=by_id[base].adapter + "-b"))
        items = picked
    rows: list[dict[str, object]] = []
    for item in items:
        row = run_one(item, out, args.effort)
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    fields = sorted({k for r in rows for k in r}, key=lambda k: (k != "item", k))
    with (out / "matrix.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    report = summarize(rows)
    (out / "summary.txt").write_text(report + "\n", encoding="utf-8")
    print("\n" + report)
    return 0 if all(r.get("correct") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())

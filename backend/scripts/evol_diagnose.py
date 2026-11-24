"""Bộ chẩn đoán triệu chứng & phát hiện gen lặn tự động từ nhật ký `trace.db` (Mục 3.0.1 & 3.7 của evolution_mutation_design.md).

Đọc toàn bộ `run-*/trace.db` trong một thư mục chạy (ví dụ `runs/real/tier_heldout_gen33_final`),
rút ra triệu chứng có bằng chứng định lượng, chấm điểm ứng viên đột biến L0–L6 theo công thức:
    priority = (impact * success_prob) / cost + novelty_bonus
và liệt kê các ứng viên gen lặn (thành phần trả rỗng / không đóng góp / tốn token).

Cách dùng:
    uv run python scripts/evol_diagnose.py --run-dir runs/real/tier_heldout_gen33_final
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CandidateOp:
    level: str
    op: str
    cost: float
    default_prob: float
    note: str


SYMPTOM_CANDIDATES: dict[str, list[CandidateOp]] = {
    "AGENT_NULL_OUTPUT": [
        CandidateOp("L1", "EDIT_PROMPT", 1.0, 0.45, "Sửa lời nhắc/lược đồ để tác tử không trả null"),
        CandidateOp("L4", "REMOVE_AGENT", 2.5, 0.75, "Loại bỏ tác tử lặn (gen lặn), thay bằng luật tất định + lưu ngân hàng gen"),
    ],
    "REPEATED_OUTPUT_RETRY": [
        CandidateOp("L1", "EDIT_PROMPT", 1.0, 0.55, "Thêm ví dụ định dạng & quy tắc xử lý mã lỗi lặp"),
        CandidateOp("L2", "MODIFY_TOOL", 1.8, 0.70, "Công cụ trả sẵn metadata cần trích (vd [symbol], [DISABLED])"),
    ],
    "USAGE_LIMIT_EXCEEDED": [
        CandidateOp("L0", "TUNE", 0.8, 0.50, "Điều chỉnh ngân sách nhánh & cap đầu ra công cụ"),
        CandidateOp("L2", "MODIFY_TOOL", 1.8, 0.70, "Nén gọn đầu ra công cụ tránh tràn ngữ cảnh"),
    ],
    "BRANCH_DUPLICATION": [
        CandidateOp("L5", "CHANGE_SELECTION", 2.0, 0.60, "Đổi tiêu chí chọn nhánh & dừng sớm"),
        CandidateOp("L4", "MERGE_AGENTS", 2.5, 0.50, "Gộp nhánh trùng lặp khi không tăng độ phủ"),
    ],
    "REPORT_ALERT_MISMATCH": [
        CandidateOp("L1", "EDIT_PROMPT", 1.0, 0.40, "Nhắc Report Agent đối chiếu đúng cảnh báo kỳ vọng và quan sát"),
        CandidateOp("L3", "ADD_STEP", 2.0, 0.85, "Thêm kiểm chứng tất định (precheck) cho Report Agent đối chiếu T3"),
    ],
    "HARDCODED_LIBRARY_HINTS": [
        CandidateOp("L1", "REWRITE_SKILL", 1.2, 0.80, "Gỡ tên hàm/tệp riêng từng thư viện khỏi handler/prompt chuyển sang adapter"),
    ],
}


def diagnose_run_dir(run_dir: Path) -> dict[str, Any]:
    run_dirs = sorted(p for p in run_dir.glob("run-*") if (p / "trace.db").is_file())
    role_calls: Counter[str] = Counter()
    role_nulls: Counter[str] = Counter()
    retry_codes: Counter[str] = Counter()
    llm_failures: Counter[str] = Counter()
    dup_branches = 0
    total_tournaments = 0
    null_examples: dict[str, list[str]] = {}
    high_token_runs: list[tuple[str, int]] = []

    for rdir in run_dirs:
        con = sqlite3.connect(rdir / "trace.db")
        run_tokens = 0
        for kind, role, payload_str in con.execute("SELECT kind, role, payload FROM events"):
            try:
                p = json.loads(payload_str)
            except Exception:
                continue
            if kind == "role_run":
                r = str(p.get("role") or role or "unknown")
                role_calls[r] += 1
                run_tokens += int(p.get("tokens") or 0)
                if p.get("output") is None:
                    role_nulls[r] += 1
                    null_examples.setdefault(r, []).append(rdir.name)
            elif kind == "output_retry":
                for err in p.get("errors", []):
                    code = str(err).split(":", 1)[0].strip()
                    retry_codes[code] += 1
            elif kind == "llm_failure":
                llm_failures[str(p.get("error") or "unknown")] += 1
            elif kind == "tournament":
                total_tournaments += 1
                branches = p.get("branches") or []
                sigs = {
                    (b.get("file"), b.get("symbol"), tuple(b.get("lines") or ()))
                    for b in branches
                    if isinstance(b, dict) and b.get("file")
                }
                if len(branches) >= 2 and len(sigs) == 1:
                    dup_branches += 1
        con.close()
        if run_tokens > 350_000:
            high_token_runs.append((rdir.name, run_tokens))

    symptoms: list[dict[str, Any]] = []
    for r, nulls in role_nulls.items():
        total = role_calls[r]
        if nulls > 0 and nulls / max(1, total) >= 0.5:
            symptoms.append(
                {
                    "code": "AGENT_NULL_OUTPUT",
                    "impact": nulls,
                    "evidence": f"Vai trò `{r}` trả output=null {nulls}/{total} lần ({nulls / total:.0%}) ở {null_examples[r][:4]}",
                    "recessive_gene_candidate": r,
                }
            )
    for err_code, cnt in retry_codes.most_common(3):
        if cnt >= 2:
            symptoms.append(
                {
                    "code": "REPEATED_OUTPUT_RETRY",
                    "impact": cnt,
                    "evidence": f"Mã lỗi `{err_code}` gây output_retry {cnt} lần",
                }
            )
    if llm_failures.get("UsageLimitExceeded", 0) > 0:
        cnt = llm_failures["UsageLimitExceeded"]
        symptoms.append(
            {
                "code": "USAGE_LIMIT_EXCEEDED",
                "impact": cnt,
                "evidence": f"Gặp UsageLimitExceeded {cnt} lần",
            }
        )
    if dup_branches > 0:
        symptoms.append(
            {
                "code": "BRANCH_DUPLICATION",
                "impact": dup_branches,
                "evidence": f"{dup_branches}/{total_tournaments} giải đấu có 2 nhánh nộp trùng hệt (file, symbol, lines)",
            }
        )

    # Chấm điểm ứng viên đột biến theo công thức Mục 3.0.3
    ranked_candidates: list[dict[str, Any]] = []
    for sym in symptoms:
        for cand in SYMPTOM_CANDIDATES.get(sym["code"], []):
            score = round((float(sym["impact"]) * cand.default_prob) / cand.cost + 0.1, 3)
            ranked_candidates.append(
                {
                    "symptom": sym["code"],
                    "level": cand.level,
                    "op": cand.op,
                    "score": score,
                    "note": cand.note,
                }
            )
    ranked_candidates.sort(key=lambda x: -x["score"])

    return {
        "run_dir": str(run_dir),
        "runs_scanned": len(run_dirs),
        "role_calls": dict(role_calls),
        "role_nulls": dict(role_nulls),
        "llm_failures": dict(llm_failures),
        "high_token_runs": high_token_runs,
        "symptoms": symptoms,
        "ranked_candidates": ranked_candidates,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out-json")
    args = ap.parse_args()
    report = diagnose_run_dir(Path(args.run_dir))
    txt = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out_json:
        Path(args.out_json).write_text(txt + "\n", encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()

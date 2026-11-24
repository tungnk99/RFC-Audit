"""Harness kiểm tra Phiếu tiến hoá (Mục 4 & 8.2 của evolution_mutation_design.md).

Kiểm tra tự động:
1. Bất biến (Invariants): tuyệt đối không chạm `verdict_engine.py`, `rules.py`, `schema_gate.py`, `ifc.py`, `tool_gateway.py`, `output_gate.py`, hoặc tập dữ liệu chuẩn.
2. `declared_matches_diff`: mức đột biến (`L0`–`L6`) khai trong phiếu phải khớp với vùng tệp thực sự bị sửa trong `git diff`.
3. Ghi nhận phiếu hợp lệ vào Nhật ký đổi mới (`backend/eval/evolution/innovation_log.md`).

Cách dùng:
    uv run python scripts/evol_check_ticket.py --ticket backend/eval/evolution/tickets/gen-34.yaml --base HEAD
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parent.parent.parent

INVARIANT_PATHS = (
    "backend/src/rfcv/core/verdict_engine.py",
    "backend/src/rfcv/domains/rfc_protocol/rules.py",
    "backend/src/rfcv/gates/schema_gate.py",
    "backend/src/rfcv/core/ifc.py",
    "backend/src/rfcv/gates/tool_gateway.py",
    "backend/src/rfcv/gates/output_gate.py",
    "backend/eval/dataset/",
)

LEVEL_ALLOWED_PREFIXES: dict[str, tuple[str, ...]] = {
    "L0": ("backend/agents/", "backend/config/", "backend/src/rfcv/runtime/"),
    "L1": ("backend/agents/", "backend/skills/"),
    "L2": ("backend/src/rfcv/gates/code_tools.py", "backend/agents/", "backend/skills/", "backend/tests/"),
    "L3": ("backend/agents/", "backend/src/rfcv/core/execution_loop.py", "backend/src/rfcv/domains/", "backend/tests/"),
    "L4": ("backend/agents/", "backend/src/rfcv/core/execution_loop.py", "backend/config/", "backend/tests/"),
    "L5": ("backend/agents/", "backend/src/rfcv/core/execution_loop.py", "backend/tests/"),
    "L6": ("backend/agents/", "backend/src/rfcv/", "backend/skills/", "backend/tests/"),
}


def git_changed_files(base: str) -> list[str]:
    out = subprocess.check_output(["git", "diff", "--name-only", base], cwd=REPO, text=True)
    return [line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()]


def check_ticket(ticket: dict[str, Any], changed: list[str]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    # 1. Kiểm tra bất biến
    touched_inv = [f for f in changed if any(f.startswith(inv) for inv in INVARIANT_PATHS)]
    if touched_inv:
        errors.append(f"INVARIANT_VIOLATION: chạm vùng bất biến {touched_inv}")
    if ticket.get("invariants_touched"):
        errors.append(f"INVARIANT_DECLARED_NONEMPTY: {ticket['invariants_touched']}")

    # 2. Kiểm tra mức khai báo khớp với diff thực tế
    level = str(ticket.get("level", "")).upper()
    if level not in LEVEL_ALLOWED_PREFIXES:
        errors.append(f"INVALID_LEVEL: `{level}` không thuộc L0..L6")
    else:
        allowed = LEVEL_ALLOWED_PREFIXES[level]
        code_changed = [
            f for f in changed if not f.startswith(("docs/", "backend/eval/evolution/", "backend/eval/results.tsv"))
        ]
        bad_files = [f for f in code_changed if not any(f.startswith(pref) for pref in allowed)]
        if bad_files:
            errors.append(f"DECLARED_LEVEL_MISMATCH: khai `{level}` nhưng sửa tệp ngoài phạm vi: {bad_files}")

    # 3. Kiểm tra các trường bắt buộc của phiếu
    for req_field in ("generation", "level", "operator", "target", "summary", "motivation"):
        if not ticket.get(req_field):
            errors.append(f"MISSING_FIELD: thiếu `{req_field}` trong phiếu tiến hoá")

    return not errors, errors


def append_innovation_log(ticket: dict[str, Any], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not log_path.exists():
        log_path.write_text(
            "# Nhật ký Đổi mới Tiến hoá (RFC-Audit)\n\n"
            "| Thế hệ | Mức & Phép | Loại đóng góp | Tóm tắt & Kết quả | Bậc năng lực |\n"
            "|---|---|---|---|---|\n",
            encoding="utf-8",
        )
    gen = ticket.get("generation", "gen-?")
    lvl_op = f"`{ticket.get('level')} {ticket.get('operator')}`"
    contrib = ticket.get("contribution_type", "Cải thiện thật")
    summary = str(ticket.get("summary", "")).replace("|", "/")
    tier = ticket.get("capability_rung", "bậc 1")
    row = f"| **{gen}** | {lvl_op} | {contrib} | {summary} | {tier} |\n"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(row)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticket", required=True)
    ap.add_argument("--base", default="HEAD")
    ap.add_argument("--record", action="store_true", help="Ghi vào innovation_log.md nếu qua hết cổng kiểm tra.")
    args = ap.parse_args()

    ticket_path = Path(args.ticket)
    ticket: dict[str, Any] = yaml.safe_load(ticket_path.read_text(encoding="utf-8"))
    changed = git_changed_files(args.base)
    ok, errors = check_ticket(ticket, changed)
    out = {"ticket": str(ticket_path), "declared_matches_diff": ok, "changed_files": changed, "errors": errors}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not ok:
        sys.exit(1)
    if args.record:
        append_innovation_log(ticket, REPO / "backend" / "eval" / "evolution" / "innovation_log.md")


if __name__ == "__main__":
    main()

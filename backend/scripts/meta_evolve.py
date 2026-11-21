r"""Meta-Agent Evolution Harness cho RFC-Audit: Trace Mining, Policy Whitelist Gate & Kho Tri thức Luận văn.

Chức năng:
  1. `--mine <run_dir>...`      : Đọc `trace.db` các lần chạy, gom chính xác chữ ký lỗi (gate_reject, output_retry,
                                  tool_denied, llm_failure, token cao) làm đầu vào cho bước sinh giả thuyết.
  2. `--check-policy`           : Kiểm tra `git diff --name-only` chỉ chạm `allowed_paths` và 0 `forbidden_paths`
                                  trong `eval/meta_policy.yaml` (chặn tuyệt đối Reward Hacking).
  3. `--record`                 : Ghi toàn bộ hồ sơ một thế hệ tiến hoá (giả thuyết, bằng chứng trace, diff,
                                  số đo trước/sau, quyết định KEEP/REVERT, bài học rút ra) vào:
                                    - `backend/eval/evolution/evolution_log.jsonl` (máy đọc, append-only)
                                    - `backend/eval/evolution/knowledge_base.md` (người đọc, dùng viết luận văn)
"""

from __future__ import annotations

import argparse
import datetime
import fnmatch
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
POLICY_PATH = ROOT / "eval" / "meta_policy.yaml"
EVO_DIR = ROOT / "eval" / "evolution"
EVO_JSONL = EVO_DIR / "evolution_log.jsonl"
KNOWLEDGE_MD = EVO_DIR / "knowledge_base.md"

KB_HEADER = """# Kho Tri thức & Nhật ký Tiến hoá Meta-Agent (RFC-Audit)

Tài liệu này được sinh và cập nhật tự động sau mỗi vòng lặp tự cải tiến (`scripts/meta_evolve.py`), lưu lại đầy đủ:
**vết lỗi khai phá từ `trace.db` → giả thuyết cải tiến → tệp sửa (qua kiểm soát Whitelist) → số đo trước/sau → quyết định KEEP/REVERT → bài học rút ra cho luận văn.**

---
"""


def _load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    return cast("dict[str, Any]", yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def _match_any(rel_posix: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(rel_posix, pat):
            return True
        if pat.endswith("/**") and rel_posix.startswith(pat[:-3] + "/"):
            return True
    return False


def check_paths_policy(changed_paths: list[str], policy: dict[str, Any] | None = None) -> tuple[bool, list[str]]:
    """Kiểm tra danh sách tệp sửa (đường dẫn tương đối từ gốc repo, dạng POSIX) có tuân thủ Whitelist/Blacklist."""
    pol = policy or _load_policy()
    allowed = [str(p) for p in pol.get("allowed_paths", [])]
    forbidden = [str(p) for p in pol.get("forbidden_paths", [])]
    violations: list[str] = []
    for raw in changed_paths:
        p = raw.replace("\\", "/").strip()
        if not p:
            continue
        if _match_any(p, forbidden):
            violations.append(f"FORBIDDEN: {p}")
        elif not _match_any(p, allowed):
            violations.append(f"OUTSIDE_WHITELIST: {p}")
    return not violations, violations


def git_changed_files() -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def git_head_short() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.stdout.strip() or "unknown"


def mine_traces(run_dirs: list[Path]) -> dict[str, Any]:
    """Đọc `trace.db` các thư mục lần chạy để trích xuất chữ ký lỗi lặp lại cho Meta-Agent."""
    from rfcv.core.trace import TraceLog

    per_run: list[dict[str, Any]] = []
    gate_errors: Counter[str] = Counter()
    tool_denials: Counter[str] = Counter()
    llm_errors: Counter[str] = Counter()

    for rdir in run_dirs:
        tdb = rdir / "trace.db"
        if not tdb.is_file():
            per_run.append({"run": rdir.name, "error": "missing trace.db"})
            continue
        events = list(TraceLog(tdb).events())
        verdict_ev = next((e["payload"] for e in reversed(events) if e["kind"] == "verdict"), {})
        run_gate: list[str] = []
        run_denials: list[str] = []
        run_failures: list[str] = []
        for ev in events:
            kind = ev["kind"]
            pl = ev["payload"]
            if kind == "gate_reject":
                for err in pl.get("errors", []):
                    key = f"{ev.get('role')}:{err}"
                    gate_errors[key] += 1
                    run_gate.append(key)
            elif kind == "tool_denied":
                key = f"{ev.get('role')}:{pl.get('tool')}:{pl.get('code')}"
                tool_denials[key] += 1
                run_denials.append(key)
            elif kind == "llm_failure":
                key = f"{ev.get('role')}:{pl.get('error')}"
                llm_errors[key] += 1
                run_failures.append(key)
        per_run.append(
            {
                "run": rdir.name,
                "label": verdict_ev.get("label"),
                "rule": verdict_ev.get("rule"),
                "gate_rejects": run_gate,
                "tool_denials": run_denials,
                "llm_failures": run_failures,
            }
        )

    return {
        "runs_mined": len(run_dirs),
        "top_gate_errors": gate_errors.most_common(10),
        "top_tool_denials": tool_denials.most_common(10),
        "top_llm_failures": llm_errors.most_common(10),
        "per_run": per_run,
    }


def record_generation(entry: dict[str, Any], *, evo_dir: Path = EVO_DIR) -> tuple[Path, Path]:
    """Ghi bền vững một thế hệ tiến hoá vào cả `evolution_log.jsonl` (máy đọc) và `knowledge_base.md` (luận văn)."""
    evo_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = evo_dir / "evolution_log.jsonl"
    kb_path = evo_dir / "knowledge_base.md"

    with jsonl_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    if not kb_path.exists():
        kb_path.write_text(KB_HEADER, encoding="utf-8")

    files_md = ", ".join(f"`{f}`" for f in entry.get("files_changed", [])) or "*(không đổi tệp)*"
    md_block = "\n".join(
        [
            f"## Gen-{entry['generation']} · `{entry['tier']}` · **{entry['decision']}** (`{entry['timestamp']}`)",
            "",
            f"- **Commit nền:** `{entry.get('commit', 'unknown')}` | **Tệp thay đổi:** {files_md}",
            f"- **Dấu vết lỗi khai phá (Trace Mining):** {entry.get('root_cause_mined', '-')}",
            f"- **Giả thuyết cải tiến:** {entry.get('hypothesis', '-')}",
            f"- **Số đo trước:** `{json.dumps(entry.get('before_metrics', {}), ensure_ascii=False)}`",
            f"- **Số đo sau:** `{json.dumps(entry.get('after_metrics', {}), ensure_ascii=False)}`",
            f"- **Tri thức & Bài học rút ra (cho luận văn):** {entry.get('lesson_learned', '-')}",
            "",
            "---",
            "",
        ]
    )
    with kb_path.open("a", encoding="utf-8") as fh:
        fh.write(md_block)
    return jsonl_path, kb_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Meta-Agent Evolution Harness cho RFC-Audit.")
    parser.add_argument("--mine", nargs="+", type=Path, help="Khai phá chữ ký lỗi từ các thư mục run")
    parser.add_argument("--check-policy", action="store_true", help="Kiểm tra git diff có thuộc Whitelist")
    parser.add_argument(
        "--record", action="store_true", help="Ghi một thế hệ vào evolution_log.jsonl & knowledge_base.md"
    )
    parser.add_argument("--gen", type=int, default=1)
    parser.add_argument("--tier", default="basic")
    parser.add_argument("--decision", choices=["KEEP", "REVERT", "REJECTED_POLICY"], default="KEEP")
    parser.add_argument("--root-cause", default="")
    parser.add_argument("--hypothesis", default="")
    parser.add_argument("--before", default="{}")
    parser.add_argument("--after", default="{}")
    parser.add_argument("--lesson", default="")
    args = parser.parse_args()

    if args.mine:
        print(json.dumps(mine_traces(args.mine), ensure_ascii=False, indent=2))
        return 0

    if args.check_policy:
        changed = git_changed_files()
        ok, violations = check_paths_policy(changed)
        print(json.dumps({"ok": ok, "changed": changed, "violations": violations}, ensure_ascii=False, indent=2))
        return 0 if ok else 2

    if args.record:
        changed = git_changed_files()
        ok, violations = check_paths_policy(changed)
        decision = args.decision if ok else "REJECTED_POLICY"
        entry = {
            "generation": args.gen,
            "timestamp": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "commit": git_head_short(),
            "tier": args.tier,
            "decision": decision,
            "policy_ok": ok,
            "policy_violations": violations,
            "files_changed": changed,
            "root_cause_mined": args.root_cause,
            "hypothesis": args.hypothesis,
            "before_metrics": json.loads(args.before),
            "after_metrics": json.loads(args.after),
            "lesson_learned": args.lesson,
        }
        jsonl_p, kb_p = record_generation(entry)
        print(
            json.dumps(
                {"recorded": True, "decision": decision, "jsonl": str(jsonl_p), "kb": str(kb_p)}, ensure_ascii=False
            )
        )
        return 0 if ok else 2

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

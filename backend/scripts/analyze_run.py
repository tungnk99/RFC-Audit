"""Tóm tắt số đo của một hay nhiều lần chạy từ trace, để điền vào bảng "Nhật ký đo" ở docs/05_project/improvement_log.md.

    uv run python scripts/analyze_run.py runs/e2e-faulty runs/e2e-correct
    uv run python scripts/analyze_run.py runs/e2e-faulty --json     # mỗi lần chạy một dòng JSON

Chỉ đọc trace.db; không gọi LLM. Các chỉ số có tên cố định để so sánh giữa các lần đo.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src")]

from rfcv.core.trace import TraceLog  # noqa: E402
from rfcv.runtime.pydantic_ai.runner import LOAD_TOOL, _tool_args, loaded_skills  # noqa: E402

WORKERS = ("code_reader", "tester", "verifier", "code_indexer")


def skill_usage(events: list[dict[str, Any]]) -> tuple[list[str], int, int]:
    """(skill đã nạp, tổng số lời gọi nạp, số lần nạp LẠI cùng một skill trong một lần chạy agent).

    Tính lại từ hội thoại trong trace, không dựa vào trường `skills_loaded` đã ghi: trace cũ ghi sai (luôn rỗng) vì không
    đọc được tham số dạng chuỗi JSON của nhà cung cấp thật.
    """
    loaded: set[str] = set()
    calls = reloads = 0
    for e in events:
        if e["kind"] not in ("llm_run", "llm_failure"):
            continue
        messages = e["payload"].get("messages", [])
        loaded.update(loaded_skills(messages))
        ids = [
            str(_tool_args(p).get("id"))
            for m in messages
            for p in m.get("parts", [])
            if p.get("part_kind") == "tool-call" and p.get("tool_name") == LOAD_TOOL
        ]
        calls += len(ids)
        reloads += len(ids) - len(set(ids))
    return sorted(loaded), calls, reloads


def metrics(run_dir: Path) -> dict[str, Any]:
    events = list(TraceLog(run_dir / "trace.db").events())
    runs = [e["payload"] for e in events if e["kind"] == "role_run"]
    per_role: dict[str, dict[str, int]] = defaultdict(lambda: {"runs": 0, "failed": 0, "tokens": 0, "ms": 0, "tools": 0})
    for p in runs:
        d = per_role[p["role"]]
        d["runs"] += 1
        d["failed"] += 0 if p["ok"] else 1
        d["tokens"] += p["tokens"]
        d["ms"] += p["duration_ms"]
        d["tools"] += p["tool_calls"]
    total = sum(p["tokens"] for p in runs)
    wasted = sum(p["tokens"] for p in runs if not p["ok"])
    worker_runs = [p for p in runs if p["role"] in WORKERS]
    verdict = next((e["payload"] for e in events if e["kind"] == "verdict"), {})
    stop = next((e["payload"] for e in events if e["kind"] == "stop"), {})
    failures = [e["payload"] for e in events if e["kind"] == "llm_failure"]
    skills, skill_calls, skill_reloads = skill_usage(events)
    return {
        "run": run_dir.name,
        "label": verdict.get("label"),
        "rule": verdict.get("rule"),
        "stop": stop.get("reason"),
        "rounds": max((e["payload"].get("round", 0) for e in events if e["kind"] == "round_start"), default=0),
        "seconds": round((events[-1]["ts_ns"] - events[0]["ts_ns"]) / 1e9, 1) if events else 0,
        "tokens_total": total,
        "tokens_wasted_in_failed_runs": wasted,
        "wasted_share": round(wasted / total, 2) if total else 0,
        "worker_runs": len(worker_runs),
        "worker_first_failures": sum(1 for p in worker_runs if not p["ok"]),
        "llm_failures": dict(Counter(f["error"] for f in failures)),
        "output_retries": sum(p["output_retries"] for p in runs),
        "gate_rejects": sum(1 for e in events if e["kind"] == "gate_reject"),
        "skills_loaded": skills,
        "skill_load_calls": skill_calls,
        "skill_reloads": skill_reloads,  # nạp lại skill đã nạp: dấu hiệu vòng lặp (xem CT-01)
        "plan_adherence": dict(Counter(e["payload"]["adherence"] for e in events if e["kind"] == "plan_context")),
        "critique_issues": sum(len(e["payload"]["issues"]) for e in events if e["kind"] == "critique_result"),
        "by_role": dict(per_role),
    }


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    for arg in args:
        m = metrics(Path(arg))
        if "--json" in sys.argv:
            print(json.dumps(m, ensure_ascii=False))
            continue
        print(f"\n=== {m.pop('run')} ===")
        by_role = m.pop("by_role")
        for key, value in m.items():
            print(f"{key:<32} {value}")
        for role, d in sorted(by_role.items()):
            print(f"  {role:<14} chạy {d['runs']}, hỏng {d['failed']}, {d['tokens']} token, {d['ms']}ms, {d['tools']} công cụ")

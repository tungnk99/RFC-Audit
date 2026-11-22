"""Chạy đối chứng B2 (Single-Agent LLM tự gán nhãn, không VerdictEngine / không SchemaGate / không T3 / không Tournament).

Thiết kế theo Bảng 7 (`docs/04_evaluation/evaluation_design.md`):
- Cùng mô hình `DeepSeek-V4-Flash` (`fpt-deepseek-flash`, temperature=0) từ `config/models.yaml`.
- Cùng yêu cầu RFC (`.rbs` của adapter) và cùng kho mã nguồn (`code_root`).
- Chỉ trang bị 3 công cụ đọc mã tổng quát (`list_files`, `grep`, `read_file`) tương đương coding agent / RFCAudit thuần tĩnh.
- Tự kết luận `COMPLIANT` / `VIOLATION` và vị trí mã lỗi (`file`, `line_start`, `line_end`) không qua kiểm chứng tất định.

Cách dùng:
    uv run --env-file .env python scripts/run_b2_baseline.py --out runs/real/b2_baseline_adv_heldout
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import fnmatch
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, PromptedOutput, RunContext, UsageLimits
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

sys.path.insert(0, str(Path(__file__).parent))
import run_real_matrix as rrm

from rfcv.eval.metrics import wilson_interval

BACKEND = Path(__file__).resolve().parent.parent
MAX_TOOL_CALLS = 12


@dataclass
class B2Deps:
    root: Path
    calls: int = 0

    def tick(self) -> str | None:
        self.calls += 1
        if self.calls > MAX_TOOL_CALLS:
            return "[TOOL BUDGET EXHAUSTED: Do NOT call any more tools. Submit your final B2Verdict right now based on what you read.]"
        if self.calls >= MAX_TOOL_CALLS - 2:
            return f"\n[Note: tool call {self.calls}/{MAX_TOOL_CALLS}. Wrap up soon and submit B2Verdict.]"
        return None


DEFAULT_ITEMS = [
    # 8 ca OpenSSL 3.x Tang advanced
    "OU2", "OU3", "OU4", "OG1", "OG2", "OG4", "OR1", "OX3",
    # 19 ca dong bang held_out
    "M7", "M8", "U8", "G5", "G6", "G7", "R9", "R12", "U13", "U14",
    "G8", "G9", "G11", "G12", "R16", "R17", "OG3", "OX1", "OX2",
]  # fmt: skip


class B2Verdict(BaseModel):
    label: Literal["COMPLIANT", "VIOLATION"]
    file: str = Field(
        default="", description="Relative path to the C/H file implementing or violating the requirement."
    )
    symbol: str = Field(default="", description="Function name containing the relevant logic or defect.")
    line_start: int = Field(default=0, ge=0, description="Start line (1-based) of the defect or relevant check.")
    line_end: int = Field(default=0, ge=0, description="End line (1-based) of the defect or relevant check.")
    reason: str = Field(default="", description="Short justification based on the code read.")


def _load_rbs_text(adapter_rel: str) -> str:
    ex_dir = BACKEND / adapter_rel / "examples"
    parts = [p.read_text(encoding="utf-8", errors="ignore") for p in sorted(ex_dir.glob("*.rbs"))]
    return "\n\n".join(parts) if parts else f"(No .rbs found in {adapter_rel})"


def _hit_truth(file_rel: str, a: int, b: int, truth: dict[str, list[tuple[int, int]]], slack: int = 0) -> bool:
    norm = file_rel.replace("\\", "/").lstrip("./")
    if not norm or a <= 0 or b <= 0:
        return False
    lo, hi = min(a, b), max(a, b)
    for tf, spans in truth.items():
        if tf.replace("\\", "/").lstrip("./") != norm:
            continue
        for ta, tb in spans:
            if lo <= tb + slack and hi >= ta - slack:
                return True
    return False


def _make_agent(model: OpenAIChatModel, *, disable_thinking: bool = True) -> Agent[B2Deps, B2Verdict]:
    settings: dict[str, object] = {"temperature": 0}
    if disable_thinking:
        settings["extra_body"] = {"thinking": {"type": "disabled"}}
    agent: Agent[B2Deps, B2Verdict] = Agent(
        model=model,
        deps_type=B2Deps,
        output_type=PromptedOutput(B2Verdict),
        system_prompt=(
            "You are a TLS 1.3 protocol conformance auditor. Given an RFC requirement specification and access to "
            "a C codebase via `list_files`, `grep`, and `read_file`, determine whether the implementation is "
            "`COMPLIANT` or `VIOLATION`. If `VIOLATION`, report the exact relative `file`, `symbol`, `line_start`, "
            "and `line_end` of the defect. You have at most 12 tool calls — investigate efficiently and submit "
            "`B2Verdict` before running out of tool calls."
        ),
        model_settings=settings,  # type: ignore[arg-type]
    )

    @agent.tool
    def list_files(ctx: RunContext[B2Deps], subdir: str = ".", pattern: str = "*.c") -> str:
        """List files matching glob pattern under subdir of the repository."""
        warn = ctx.deps.tick()
        if warn and ctx.deps.calls > MAX_TOOL_CALLS:
            return warn
        root = ctx.deps.root
        base = (root / subdir).resolve()
        if not str(base).startswith(str(root.resolve())) or not base.exists():
            return "(invalid directory)"
        found: list[str] = []
        for p in base.rglob("*"):
            if p.is_file() and fnmatch.fnmatch(p.name, pattern):
                rel = p.relative_to(root).as_posix()
                if any(rel.startswith(x) for x in ("tests/", "test/", "examples/", "fuzz/", "doc/")):
                    continue
                found.append(rel)
                if len(found) >= 80:
                    break
        return ("\n".join(sorted(found)) or "(no files found)") + (warn or "")

    @agent.tool
    def grep(ctx: RunContext[B2Deps], pattern: str, path: str = ".", max_hits: int = 30) -> str:
        """Case-insensitive regex search across C/H files under path (max 30 hits)."""
        warn = ctx.deps.tick()
        if warn and ctx.deps.calls > MAX_TOOL_CALLS:
            return warn
        root = ctx.deps.root
        base = (root / path).resolve()
        if not str(base).startswith(str(root.resolve())) or not base.exists():
            return "(invalid path)"
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return f"(bad regex: {exc})"
        hits: list[str] = []
        targets = [base] if base.is_file() else sorted(base.rglob("*"))
        for p in targets:
            if not p.is_file() or p.suffix not in (".c", ".h"):
                continue
            rel = p.relative_to(root).as_posix()
            if any(rel.startswith(x) for x in ("tests/", "test/", "examples/", "fuzz/", "doc/")):
                continue
            try:
                lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for idx, line in enumerate(lines, 1):
                if rx.search(line):
                    hits.append(f"{rel}:{idx}: {line[:140]}")
                    if len(hits) >= min(max_hits, 40):
                        return "\n".join(hits) + "\n...(truncated)" + (warn or "")
        return ("\n".join(hits) or "(no matches)") + (warn or "")

    @agent.tool
    def read_file(ctx: RunContext[B2Deps], file: str, start_line: int = 1, limit: int = 100) -> str:
        """Read up to 120 numbered lines from a relative file path."""
        warn = ctx.deps.tick()
        if warn and ctx.deps.calls > MAX_TOOL_CALLS:
            return warn
        root = ctx.deps.root
        target = (root / file).resolve()
        if not str(target).startswith(str(root.resolve())) or not target.is_file():
            return f"(file not found: {file})"
        lines = target.read_text(encoding="utf-8", errors="ignore").splitlines()
        lo = max(1, start_line)
        hi = min(len(lines), lo + min(limit, 120) - 1)
        return "\n".join(f"{i:6d} {lines[i - 1]}" for i in range(lo, hi + 1)) + (warn or "")

    return agent


async def _run_item(sem: asyncio.Semaphore, agent: Agent[B2Deps, B2Verdict], item: rrm.Item) -> dict[str, object]:
    async with sem:
        t0 = time.monotonic()
        rbs_text = _load_rbs_text(item.adapter)
        code_root = (BACKEND / item.code_root).resolve()
        prompt = (
            f"Audit this TLS 1.3 codebase for compliance with the following requirement:\n\n"
            f"{rbs_text}\n\n"
            f"Inspect the C source code and return your final verdict (`COMPLIANT` or `VIOLATION`) "
            f"with the exact `file`, `symbol`, `line_start`, and `line_end`."
        )
        try:
            res = await agent.run(
                prompt,
                deps=B2Deps(root=code_root),
                usage_limits=UsageLimits(request_limit=24, total_tokens_limit=250_000),
            )
            out = res.output
            u = res.usage() if callable(res.usage) else res.usage
            toks = int(getattr(u, "total_tokens", 0) or 0)
            reqs = int(getattr(u, "requests", 0) or 0)
            row: dict[str, object] = {
                "item": item.id,
                "family": item.family,
                "expected": item.expected,
                "label": out.label,
                "correct": out.label == item.expected,
                "file": out.file,
                "symbol": out.symbol,
                "line_start": out.line_start,
                "line_end": out.line_end,
                "tokens": toks,
                "requests": reqs,
                "seconds": round(time.monotonic() - t0, 1),
                "error": "",
            }
            if item.truth is not None:
                row["defect_hit_strict"] = out.label == "VIOLATION" and _hit_truth(
                    out.file, out.line_start, out.line_end, item.truth, slack=0
                )
                row["defect_hit"] = out.label == "VIOLATION" and _hit_truth(
                    out.file, out.line_start, out.line_end, item.truth, slack=5
                )
            return row
        except Exception as exc:
            return {
                "item": item.id,
                "family": item.family,
                "expected": item.expected,
                "label": "ERROR",
                "correct": False,
                "file": "",
                "symbol": "",
                "line_start": 0,
                "line_end": 0,
                "tokens": 0,
                "requests": 0,
                "seconds": round(time.monotonic() - t0, 1),
                "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                **({"defect_hit": False, "defect_hit_strict": False} if item.truth is not None else {}),
            }


def _summarize(name: str, rows: list[dict[str, object]]) -> str:
    n = len(rows)
    viols = [r for r in rows if r["expected"] == "VIOLATION"]
    comps = [r for r in rows if r["expected"] == "COMPLIANT"]
    fc = sum(1 for r in viols if r["label"] == "COMPLIANT")
    fv = sum(1 for r in comps if r["label"] == "VIOLATION")
    tp = sum(1 for r in viols if r["label"] == "VIOLATION")
    tn = sum(1 for r in comps if r["label"] == "COMPLIANT")
    errs = sum(1 for r in rows if r["label"] == "ERROR")
    correct = sum(1 for r in rows if r["correct"])
    hits = sum(1 for r in viols if r.get("defect_hit"))
    strict_hits = sum(1 for r in viols if r.get("defect_hit_strict"))
    avg_tok = int(sum(int(r.get("tokens") or 0) for r in rows) / max(1, n))

    def fmt(k: int, d: int) -> str:
        if d == 0:
            return "n/a"
        lo, hi = wilson_interval(k, d)
        return f"{k}/{d} = {k / d:.1%} (Wilson 95%: {lo:.0%}-{hi:.0%})"

    return "\n".join(
        [
            f"=== {name} (n={n}, VIOLATION={len(viols)}, COMPLIANT={len(comps)}, ERROR={errs}) ===",
            f"  Verdict accuracy:   {fmt(correct, n)}",
            f"  False COMPLIANT:    {fmt(fc, len(viols))}",
            f"  False VIOLATION:    {fmt(fv, len(comps))}",
            f"  Recall VIOLATION:   {fmt(tp, len(viols))}",
            f"  COMPLIANT correct:  {fmt(tn, len(comps))}",
            f"  Defect hit (±5):    {fmt(hits, len(viols))}",
            f"  Defect hit STRICT:  {fmt(strict_hits, len(viols))}",
            f"  Avg tokens/item:    {avg_tok:,}",
        ]
    )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--items", nargs="*", default=DEFAULT_ITEMS)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--provider", choices=["fpt", "deepseek"], default="fpt")
    ap.add_argument("--model", default="DeepSeek-V4-Flash")
    ap.add_argument("--enable-thinking", action="store_true", help="Do not pass thinking=disabled extra_body.")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.provider == "deepseek":
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        base_url = "https://api.deepseek.com"
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY not set")
    else:
        api_key = os.environ.get("FPT_API_KEY", "")
        base_url = "https://mkp-api.fptcloud.com/v1"
        if not api_key:
            raise RuntimeError("FPT_API_KEY not set")

    provider = OpenAIProvider(base_url=base_url, api_key=api_key)
    model = OpenAIChatModel(args.model, provider=provider)
    agent = _make_agent(model, disable_thinking=not args.enable_thinking)

    all_items = {it.id: it for it in (*rrm.real_items(""), *rrm.pair_items(), *rrm.mutant_items())}
    selected = [all_items[i] for i in args.items if i in all_items]
    sem = asyncio.Semaphore(args.concurrency)
    rows = await asyncio.gather(*(_run_item(sem, agent, it) for it in selected))

    for r in rows:
        print(json.dumps(r, ensure_ascii=False), flush=True)

    fields = [
        "item", "family", "expected", "label", "correct", "defect_hit", "defect_hit_strict",
        "file", "symbol", "line_start", "line_end", "tokens", "requests", "seconds", "error",
    ]  # fmt: skip
    with (out / "matrix.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    adv_ids = {"OU2", "OU3", "OU4", "OG1", "OG2", "OG4", "OR1", "OX3"}
    adv_rows = [r for r in rows if r["item"] in adv_ids]
    ho_rows = [r for r in rows if r["item"] not in adv_ids]
    summary = "\n\n".join(
        [
            _summarize("B2 — ALL 27 ITEMS", rows),
            _summarize("B2 — TIER ADVANCED (8 OpenSSL)", adv_rows),
            _summarize("B2 — FROZEN HELD_OUT (19 items)", ho_rows),
        ]
    )
    (out / "summary.txt").write_text(summary + "\n", encoding="utf-8")
    print("\n" + summary, flush=True)


if __name__ == "__main__":
    asyncio.run(main())

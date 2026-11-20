"""Đo RFC Analyst (dịch câu RFC → RBS) với LLM THẬT, mù với RBS viết tay, đối chiếu từng trường với bản người đã duyệt.

    uv run python scripts/measure_rfc_analyst.py --runs 2 [--adapters tls13 dns ...] [--out runs/rfc_analyst_measure.json]

Với mỗi `adapters/<tên>/examples/*.rbs` mà câu RFC tra được trong `inputs/rfc/` (kèm `sentence_aliases.yaml` nếu RFC là bản TXT),
cho agent dịch lại `--runs` lần, rồi tính bằng hàm TẤT ĐỊNH (không LLM chấm): cổng parse, từ vựng/oracle, định danh câu,
khớp từng trường với RBS đã duyệt (`reconcile`), và khớp "ngữ nghĩa" (bỏ `variants`, `within_ms`: lựa chọn kiểm thử).

LƯU Ý ĐỘ TIN CẬY (đọc trước khi trích số):
- Mẫu nhỏ (một RBS mỗi câu, ~8 câu): đây là số đo sơ bộ, không phải độ chính xác đã kiểm chứng; tiêu chí BL-23 cần 30 mục.
- RBS chuẩn do MỘT người viết; "lệch" chưa chắc là AI sai, có thể bản người sai (xem ca 16640 trong tài liệu).
- Lời nhắc/skill của RFC Analyst chứa ví dụ TLS13-0042: ca này KHÔNG mù thật, loại khỏi số tổng (cờ --keep-leaked để giữ).
- Mọi agent đang dùng cùng một họ mô hình; chưa có luồng thứ hai độc lập (BL-16).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from rfcv.assembly import RuntimeConfig, build_runtime  # noqa: E402
from rfcv.eval.demo_providers import demo_providers  # noqa: E402

# Mô hình ứng viên (khai báo thêm KHÔNG đụng config/models.yaml: script ghi một bản tạm). Cùng khoá API đã có.
CANDIDATES: dict[str, dict[str, Any]] = {
    "deepseek-v4-pro": {
        "provider": "openai_compatible",
        "model": "deepseek-v4-pro",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "settings": {"temperature": 0, "extra_body": {"thinking": {"type": "disabled"}}},
    },
    "fpt-deepseek-v41-flash": {
        "provider": "openai_compatible",
        "model": "DeepSeek-V4.1-Flash",
        "base_url": "https://mkp-api.fptcloud.com/v1",
        "api_key_env": "FPT_API_KEY",
        "settings": {"temperature": 0, "extra_body": {"thinking": {"type": "disabled"}}},
    },
    "fpt-gpt-oss-120b": {
        "provider": "openai_compatible",
        "model": "gpt-oss-120b",
        "base_url": "https://mkp-api.fptcloud.com/v1",
        "api_key_env": "FPT_API_KEY",
        "settings": {"temperature": 0},
    },
    "fpt-qwen3.8-27b": {
        "provider": "openai_compatible",
        "model": "Qwen3.8-27B",
        "base_url": "https://mkp-api.fptcloud.com/v1",
        "api_key_env": "FPT_API_KEY",
        "settings": {"temperature": 0},
    },
}

LEAKED = {"TLS13-0042"}  # ví dụ có sẵn trong prompt.md của RFC Analyst


def load_dotenv() -> None:
    """Chỉ nạp biến khoá mô hình từ backend/.env, không in giá trị."""
    path = ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            if k.strip().endswith("_API_KEY"):
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def models_file(model: str | None) -> Path:
    """Bản config/models.yaml tạm với agent rfc_analyst.a đổi sang `model` (mặc định: giữ nguyên cấu hình hiện có)."""
    import yaml

    cfg = yaml.safe_load((ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
    if model:
        cfg["models"][model] = CANDIDATES[model]
        cfg["agents"]["rfc_analyst.a"] = model
    out = Path(tempfile.mkdtemp(prefix="rfca-models-")) / "models.yaml"
    out.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return out


def summary_of(row: dict[str, Any]) -> str:
    if row["skipped"]:
        return f"bỏ qua ({row['skipped']})"
    p = row["proposal"]
    if p is None or not p.get("produced"):
        return f"không có đề xuất ({(p or {}).get('failure')})"
    cmp = p.get("compare") or {}
    gate = "cổng OK" if p["accepted"] else "cổng TỪ CHỐI"
    return f"{gate}; " + ("khớp hoàn toàn" if cmp.get("agree") else f"lệch {cmp.get('diffs')}")


async def measure(adapters: list[str], runs: int, keep_leaked: bool, model: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    models_path = models_file(model)
    for adapter in adapters:
        adapter_dir = ROOT / "adapters" / adapter
        tmp = Path(tempfile.mkdtemp(prefix=f"rfca-{adapter}-"))
        for attempt in range(runs):
            cfg = RuntimeConfig(
                adapter_dir=adapter_dir,
                run_dir=tmp,
                skills_root=ROOT / "skills",
                models_path=models_path,
                rfc_dir=ROOT / "inputs" / "rfc",
                run_id=f"rfca-{adapter}-{attempt}",
                spec_analysis=True,
            )
            rt = build_runtime(cfg, demo_providers("faulty"))
            try:
                assert rt.pack.runtime is not None and rt.loop is not None
                for inv in rt.pack.runtime.investigations(rt, adapter_dir / "examples"):
                    rid = inv.requirement.requirement_id
                    t0 = time.monotonic()
                    await rt.pack.runtime.analyze_spec(rt, inv)
                    events = [e for e in rt.trace.events() if e.get("requirement_id") == rid]
                    prop = next((e["payload"] for e in events if e["kind"] == "rfc_proposal"), None)
                    skip = next((e["payload"] for e in events if e["kind"] == "rfc_analysis_skipped"), None)
                    run = next((e["payload"] for e in events if e["kind"] == "role_run"), {})
                    rows.append(
                        {
                            "adapter": adapter,
                            "requirement": rid,
                            "attempt": attempt,
                            "leaked": rid in LEAKED and not keep_leaked,
                            "skipped": skip["reason"] if skip else None,
                            "proposal": prop,
                            "tokens": run.get("tokens"),
                            "tool_calls": run.get("tool_calls"),
                            "seconds": round(time.monotonic() - t0, 1),
                        }
                    )
                    print(f"  {adapter}/{rid} #{attempt}: {summary_of(rows[-1])}", flush=True)
            finally:
                rt.close()
    return rows


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    done = [r for r in rows if not r["skipped"] and not r["leaked"]]
    props = [r["proposal"] or {} for r in done]
    produced = [p for p in props if p.get("produced")]

    def passed(name: str) -> int:
        return sum(1 for p in produced if any(c["name"] == name and c["ok"] for c in p.get("checks", [])))

    cmps = [p["compare"] for p in produced if p.get("compare") and "agree" in p["compare"]]
    return {
        "n_runs": len(done),
        "n_requirements": len({(r["adapter"], r["requirement"]) for r in done}),
        "skipped": sorted({(r["requirement"], r["skipped"]) for r in rows if r["skipped"]}),
        "excluded_leaked": sorted({r["requirement"] for r in rows if r["leaked"]}),
        "produced": len(produced),
        "parse_ok": passed("parse"),
        "oracle_ok": passed("oracle"),
        "gate_accepted": sum(1 for p in produced if p.get("accepted")),
        "exact_agree": sum(1 for c in cmps if c["agree"]),
        "semantic_agree": sum(1 for c in cmps if c.get("semantic_agree", c["agree"])),
        "field_diffs": dict(Counter(d for c in cmps for d in c.get("diffs", [])).most_common()),
        "tokens_total": sum(r["tokens"] or 0 for r in done),
    }


def markdown(agg: dict[str, Any]) -> str:
    n = agg["n_runs"] or 1

    def pct(key: str) -> str:
        return f"{agg[key]}/{agg['n_runs']} ({100 * agg[key] // n}%)"

    skipped = ", ".join(f"{r}:{why}" for r, why in agg["skipped"]) or "không"
    lines = [
        "| Chỉ số | Kết quả |",
        "|---|---|",
        f"| Số lượt đo / số yêu cầu | {agg['n_runs']} / {agg['n_requirements']} |",
        f"| Agent trả được đề xuất | {pct('produced')} |",
        f"| Đúng cú pháp RBS | {pct('parse_ok')} |",
        f"| Qua cổng từ vựng + biên dịch oracle | {pct('oracle_ok')} |",
        f"| Cổng chấp nhận (mọi kiểm tra) | {pct('gate_accepted')} |",
        f"| Khớp hoàn toàn RBS đã duyệt | {pct('exact_agree')} |",
        f"| Khớp về ngữ nghĩa (bỏ variants, within_ms) | {pct('semantic_agree')} |",
        f"| Token tổng | {agg['tokens_total']:,} |",
        "",
        f"Trường lệch hay gặp: {agg['field_diffs'] or 'không có'}.",
        f"Loại khỏi số tổng (ví dụ nằm trong prompt): {', '.join(agg['excluded_leaked']) or 'không'}.",
        f"Bỏ qua (thiếu RFC/câu): {skipped}.",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=2, help="số lần dịch lại mỗi câu")
    ap.add_argument("--adapters", nargs="*", default=None, help="mặc định: mọi adapter có examples/")
    ap.add_argument(
        "--model",
        choices=sorted(CANDIDATES),
        default=None,
        help="đổi mô hình của rfc_analyst.a (mặc định: theo config)",
    )
    ap.add_argument("--keep-leaked", action="store_true", help="giữ cả ca có ví dụ trong prompt khi tính tổng")
    ap.add_argument("--out", type=Path, default=ROOT / "runs" / "rfc_analyst_measure.json")
    args = ap.parse_args()
    load_dotenv()
    adapters = args.adapters or sorted(p.parent.name for p in ROOT.glob("adapters/*/examples") if any(p.glob("*.rbs")))
    print(f"Đo RFC Analyst: {adapters}, mỗi câu {args.runs} lần, mô hình: {args.model or 'theo config'}")
    rows = asyncio.run(measure(adapters, args.runs, args.keep_leaked, args.model))
    agg = aggregate(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"aggregate": agg, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n" + markdown(agg) + f"\n\nChi tiết: {args.out}")


if __name__ == "__main__":
    main()

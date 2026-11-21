r"""Kiểm định tính toàn vẹn Bộ dữ liệu Phân tầng (`tiered_benchmark.yaml`) và xuất báo cáo tốt nghiệp theo tầng.

Dùng:
  cd backend
  .\.venv\Scripts\python.exe scripts/eval_tier_report.py --validate
  .\.venv\Scripts\python.exe scripts/eval_tier_report.py --tier basic --report-out ../docs/04_evaluation/tier_basic_report.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_YAML = ROOT / "eval" / "dataset" / "tiered_benchmark.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def validate_dataset() -> tuple[bool, list[str], dict[str, int]]:
    """Kiểm tra mọi ID trong `tiered_benchmark.yaml` không trùng lặp giữa các tầng và tồn tại trong nguồn gốc."""
    cfg = _load_yaml(BENCHMARK_YAML)
    sources_cfg = cast("dict[str, str]", cfg.get("sources", {}))
    source_ids: dict[str, set[str]] = {}
    errors: list[str] = []

    for key, rel in sources_cfg.items():
        p = ROOT / rel
        if not p.exists():
            errors.append(f"source '{key}' không tồn tại: {rel}")
            continue
        if p.is_file() and p.suffix == ".yaml":
            data = _load_yaml(p)
            items = cast("list[dict[str, Any]]", data.get("items", []))
            source_ids[key] = {str(it["id"]) for it in items if "id" in it}

    seen_global: dict[str, str] = {}
    counts: dict[str, int] = {}
    tiers = cast("dict[str, dict[str, Any]]", cfg.get("tiers", {}))
    for tier_name, tier in tiers.items():
        items = cast("list[dict[str, Any]]", tier.get("items", []))
        counts[tier_name] = len(items)
        for item in items:
            iid = str(item["id"])
            if iid in seen_global:
                errors.append(f"trùng id '{iid}' giữa tầng '{seen_global[iid]}' và '{tier_name}'")
            seen_global[iid] = tier_name
            src = item.get("source")
            if isinstance(src, str):
                if src not in source_ids:
                    errors.append(f"{tier_name}/{iid}: source lạ '{src}'")
                elif iid not in source_ids[src]:
                    errors.append(f"{tier_name}/{iid}: không tìm thấy id trong {sources_cfg[src]}")
            adapter = item.get("adapter")
            if isinstance(adapter, str) and not (ROOT / adapter).exists():
                errors.append(f"{tier_name}/{iid}: adapter không tồn tại: {adapter}")
            for path_key in ("script", "test"):
                ref = item.get(path_key)
                if isinstance(ref, str) and not (ROOT / ref).is_file():
                    errors.append(f"{tier_name}/{iid}: {path_key} không tồn tại: {ref}")

    return not errors, errors, counts


def render_tier_summary(tier_name: str) -> str:
    cfg = _load_yaml(BENCHMARK_YAML)
    tiers = cast("dict[str, dict[str, Any]]", cfg.get("tiers", {}))
    if tier_name not in tiers:
        raise SystemExit(f"Không có tầng '{tier_name}' (chọn: {sorted(tiers)})")
    tier = tiers[tier_name]
    items = cast("list[dict[str, Any]]", tier.get("items", []))
    gate = cast("dict[str, Any]", tier.get("graduation_gate", {}))
    no_docker = sum(1 for it in items if not it.get("requires_docker", False))
    with_docker = len(items) - no_docker
    lines = [
        f"# Kế hoạch & Bảng mẫu Đánh giá Tầng `{tier_name}`",
        "",
        f"> {tier.get('description', '')}",
        "",
        f"- **Tổng số mẫu:** {len(items)} ({no_docker} không cần Docker, {with_docker} dùng SUT Docker thật).",
        f"- **Ngưỡng tốt nghiệp (Graduation Gate):** `{json.dumps(gate, ensure_ascii=False)}`",
        "",
        "| # | ID | Loại | Họ | Kỳ vọng | Cần Docker |",
        "|---|---|---|---|---|---|",
    ]
    for idx, it in enumerate(items, 1):
        lines.append(
            f"| {idx} | `{it['id']}` | `{it.get('kind', '')}` | `{it.get('family', '-')}` | "
            f"`{it.get('expected', '')}` | {'Có' if it.get('requires_docker') else 'Không'} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Kiểm định bộ dữ liệu phân tầng & tạo báo cáo tầng.")
    parser.add_argument("--validate", action="store_true", help="Kiểm tra tính toàn vẹn tiered_benchmark.yaml")
    parser.add_argument("--tier", help="Tên tầng cần in/xuất bảng (basic, intermediate, advanced, held_out)")
    parser.add_argument("--report-out", type=Path, help="Đường dẫn tệp Markdown xuất báo cáo")
    args = parser.parse_args()

    ok, errors, counts = validate_dataset()
    if args.validate or not args.tier:
        print(
            json.dumps(
                {"valid": ok, "counts": counts, "total": sum(counts.values()), "errors": errors},
                ensure_ascii=False,
                indent=2,
            )
        )
        if not ok:
            return 1
    if args.tier:
        md = render_tier_summary(args.tier)
        if args.report_out:
            args.report_out.write_text(md, encoding="utf-8")
            print(f"Đã ghi báo cáo tầng '{args.tier}' tới {args.report_out}")
        else:
            print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())

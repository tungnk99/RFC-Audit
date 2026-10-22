"""Lệnh `rfcv-eval`: chạy bộ mô phỏng và in báo cáo. Tách khỏi `rfcv` vì lõi không được nhập `rfcv.eval`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

import typer

from rfcv.eval.sim import Report, run_benchmark
from rfcv.eval.strategies import STRATEGIES

app = typer.Typer(help="Đo độ chính xác và độ phủ bằng mô phỏng tất định (SYNTHETIC).", no_args_is_help=True)


def render(report: Report) -> str:
    lines = [
        "# Báo cáo mô phỏng (SYNTHETIC)",
        "",
        "Đo *cơ chế* phát hiện của từng chiến lược trên các họ lỗi do chúng ta thiết kế; KHÔNG phải độ chính xác ngoài đời.",
        f"Cấu hình đóng băng: `{report.config_hash}`. Số seed mỗi họ: {report.seeds}.",
        "",
    ]
    families = sorted({c.family for c in report.cells if c.kind == "faulty"})
    for s in sorted({c.strategy for c in report.cells}):
        lines += [
            f"## {s}",
            "",
            "| họ lỗi | n | bị đánh dấu | khoảng Wilson 95% | COMPLIANT sai | chạy TB | quét vét cạn thấy |",
            "|---|---|---|---|---|---|---|",
        ]
        for fam in families:
            r = report.summary(s, fam)
            lo, hi = r["flagged_ci"]  # type: ignore[misc]
            lines.append(
                f"| {fam} | {r['n']} | {r['flagged']} | [{lo:.2f}, {hi:.2f}] | {r['false_compliant']} | "
                f"{r['mean_runs']:.1f} | {r['scan_detectable_fraction']:.0%} |"
            )
        fv = report.false_violation(s)
        dc, dn = report.decisive_rate(s, "correct")
        lines += [
            "",
            f"false-VIOLATION: cài đặt đúng {fv['correct'][0]}/{fv['correct'][1]}, hợp lệ-thay-thế {fv['alt_valid'][0]}/{fv['alt_valid'][1]}. "
            f"Độ phủ quyết định trên cài đặt đúng: {dc}/{dn}.",
            "",
        ]
    return "\n".join(lines)


@app.command()
def sim(
    adapter: Annotated[Path, typer.Option(help="Thư mục adapter (lấy từ vựng)")] = Path("adapters/tls13"),
    seeds: Annotated[int, typer.Option(help="Số seed mỗi họ lỗi")] = 20,
    split: Annotated[str, typer.Option(help="train, test hoặc all")] = "all",
    as_json: Annotated[bool, typer.Option("--json", help="In JSON thay vì Markdown")] = False,
) -> None:
    """Chạy mọi chiến lược trên mọi họ lỗi và in báo cáo."""
    chosen: Literal["train", "test", "all"] = "train" if split == "train" else "test" if split == "test" else "all"
    report = run_benchmark(adapter, seeds=seeds, strategies=STRATEGIES, split=chosen)
    if as_json:
        typer.echo(json.dumps([c.__dict__ for c in report.cells], ensure_ascii=False))
    else:
        typer.echo(render(report))


@app.command()
def families() -> None:
    """Liệt kê họ lỗi, tập chia (train/test) và mô tả."""
    from rfcv.eval.faults import FAMILIES

    for fam in FAMILIES:
        typer.echo(f"{fam.name:<22} {fam.split:<6} {fam.description}")


@app.command()
def coord(
    adapter: Annotated[Path, typer.Option(help="Thư mục adapter (lấy từ vựng)")] = Path("adapters/tls13"),
    seeds: Annotated[int, typer.Option(help="Số seed mỗi họ lỗi (chỉ tập train)")] = 3,
) -> None:
    """Đo phối hợp giữa các agent bằng mô phỏng (SYNTHETIC) và in quyết định theo tiêu chí đã đăng ký trước."""
    from rfcv.eval.coord_sim import render as render_coord
    from rfcv.eval.coord_sim import run_coord

    typer.echo(render_coord(run_coord(adapter, seeds=seeds)))

"""Chạy ma trận thí nghiệm phối hợp (đã đăng ký trước ở `coord_prereg`) và dựng báo cáo.

KẾT QUẢ LÀ SYNTHETIC (xem `coord_world`). Chỉ dùng họ lỗi `train`; cùng đầu vào cho cùng báo cáo từng byte.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any

from rfcv.common.hashing import content_hash
from rfcv.core.budget import LoopDetector
from rfcv.core.execution_loop import report_json
from rfcv.eval import coord_prereg as prereg
from rfcv.eval.coord_policies import make_policy
from rfcv.eval.coord_world import PROFILES, CellResult, run_cell
from rfcv.eval.faults import FAMILIES, SimImpl, alt_valid_impl, correct_impl
from rfcv.eval.metrics import wilson_interval
from rfcv.evidence.verdict_engine import SufficiencyReport

ASSURANCE_RANK = {"LINKED": 3, "BEHAVIORAL": 2, "STATIC": 1}
NOTES = [
    "SYNTHETIC: lỗi worker và chính sách Planner do ta cài; chỉ khẳng định cận thông tin, cơ chế hub và an toàn.",
    "KHÔNG đo mức phổ biến lỗi của LLM thật. Họ lỗi chỉ lấy tập train.",
]


class ProgressLoopDetector(LoopDetector):
    """Cung cấp cho thí nghiệm E3: khoá theo (kiểu, vai trò), bỏ qua tham số, vì đổi tham số không phải là tiến triển."""

    @staticmethod
    def key(task_type: str, target_role: str, params: dict[str, Any]) -> str:
        return content_hash({"t": task_type, "r": target_role})


def progress_token(report: SufficiencyReport, _n: int) -> str:
    """Tiến triển = báo cáo độ đủ thay đổi (không phải chỉ thêm bằng chứng trùng lặp)."""
    return content_hash(report_json(report))


@dataclass(frozen=True)
class CoordCell:
    exp: str
    policy: str
    profile: str
    arm: str
    impl: str
    kind: str
    seed: int
    r: CellResult


@dataclass
class CoordReport:
    cells: list[CoordCell]
    config_hash: str
    seeds: int
    synthetic: bool = True
    notes: list[str] = field(default_factory=lambda: list(NOTES))

    def by(self, exp: str, policy: str, profile: str, arm: str = "base") -> list[CoordCell]:
        return sorted(
            (
                c
                for c in self.cells
                if (c.exp, c.policy, c.profile, c.arm) == (exp, policy, profile, arm)
            ),
            key=lambda c: (c.impl, c.seed),
        )

    def truth(self) -> dict[tuple[str, int], str]:
        """Nhãn tham chiếu cho từng cài đặt: ORACLE-FULL với worker sạch (E1)."""
        return {(c.impl, c.seed): c.r.label for c in self.by("E1", "ORACLE-FULL", "W0")}

    def summary(self, exp: str, policy: str, profile: str, arm: str = "base") -> dict[str, Any]:
        cells = self.by(exp, policy, profile, arm)
        n = len(cells)
        decisive = sum(c.r.label in prereg.DECISIVE for c in cells)
        calls = sum(c.r.planner_calls for c in cells)
        decided = [c for c in cells if c.r.label in prereg.DECISIVE]
        return {
            "n": n,
            "decisive": decisive,
            "decisive_ci": wilson_interval(decisive, n),
            "rounds_median": median(c.r.planner_calls for c in cells) if cells else 0,
            "linked": sum(c.r.assurance == "LINKED" for c in decided),
            "assurance_mean": (sum(ASSURANCE_RANK.get(c.r.assurance or "", 0) for c in decided) / len(decided))
            if decided
            else 0.0,
            "stop": Counter(c.r.stop_reason for c in cells),
            "wasted_share": (sum(c.r.wasted for c in cells) / calls) if calls else 0.0,
            "tags": Counter(t for c in cells for t in c.r.tags),
        }


def impls(seeds: int) -> list[SimImpl]:
    out: list[SimImpl] = [correct_impl(), alt_valid_impl()]
    for fam in FAMILIES:
        if fam.split == "train":
            out += [fam.make(s) for s in range(seeds)]
    return out


async def _run(adapter_dir: Path, seeds: int) -> list[CoordCell]:
    cells: list[CoordCell] = []
    population = impls(seeds)
    for exp in prereg.EXPERIMENTS:
        for spec in exp.policies:
            for profile in exp.profiles:
                for arm in exp.arms:
                    for impl in population:
                        seed = impl.seed if impl.kind == "faulty" else 0
                        r = await run_cell(
                            adapter_dir,
                            impl,
                            PROFILES[profile],
                            make_policy(spec, seed),
                            seed=seed,
                            loop_detector=ProgressLoopDetector if arm == "progress" else None,
                            progress_of=progress_token if arm == "progress" else None,
                        )
                        cells.append(CoordCell(exp.exp, spec, profile, arm, impl.name, impl.kind, seed, r))
    return cells


def run_coord(adapter_dir: Path, *, seeds: int = 3) -> CoordReport:
    return CoordReport(asyncio.run(_run(adapter_dir, seeds)), prereg.config_hash(seeds), seeds)


def render(report: CoordReport) -> str:
    lines = [
        "# Báo cáo phối hợp đa agent (SYNTHETIC)",
        "",
        *[f"> {n}" for n in report.notes],
        "",
        f"Cấu hình đăng ký trước (phiên bản {prereg.PREREG_VERSION}): `{report.config_hash}`. Số seed mỗi họ lỗi: {report.seeds}.",
        "",
        f"Lịch sử đăng ký: {prereg.PREREG_HISTORY}",
        "",
        "## Quyết định theo tiêu chí đã đăng ký trước",
        "",
        "| mã | giả thuyết | kết quả | bằng chứng |",
        "|---|---|---|---|",
    ]
    for d in prereg.decisions(report):
        verdict = {True: "ĐẠT", False: "KHÔNG ĐẠT", None: "thiếu dữ liệu"}[d.passed]
        lines.append(f"| {d.id} | {prereg.HYPOTHESES.get(d.id, '')} | {verdict} | {d.evidence} |")
    lines += ["", "Không quyết định được bằng mô phỏng:"] + [f"- {x}" for x in prereg.NOT_DECIDABLE_BY_SIMULATION]
    lines += [""]
    for exp in prereg.EXPERIMENTS:
        lines += [
            f"## {exp.exp}",
            "",
            "| chính sách | worker | nhánh | n | quyết định [Wilson] | vòng (trung vị) | độ bảo đảm TB | lãng phí | dừng | mã lỗi |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for spec in exp.policies:
            for profile in exp.profiles:
                for arm in exp.arms:
                    s = report.summary(exp.exp, spec, profile, arm)
                    lo, hi = s["decisive_ci"]
                    stop = ", ".join(f"{k}:{v}" for k, v in sorted(s["stop"].items()))
                    tags = ", ".join(f"{k.removeprefix('FM_')}:{v}" for k, v in sorted(s["tags"].items())) or "-"
                    lines.append(
                        f"| {spec} | {profile} | {arm} | {s['n']} | {s['decisive']}/{s['n']} [{lo:.2f}, {hi:.2f}] | "
                        f"{s['rounds_median']:.0f} | {s['assurance_mean']:.2f} | {s['wasted_share']:.2f} | {stop} | {tags} |"
                    )
        lines.append("")
    return "\n".join(lines)

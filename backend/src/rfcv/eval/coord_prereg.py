"""Đăng ký trước (pre-registration) của đo phối hợp: giả thuyết, ma trận thí nghiệm và tiêu chí quyết định, đóng băng lúc viết mã.

Mọi ngưỡng ở đây được đặt TRƯỚC khi chạy lần đầu và băm vào `config_hash` của báo cáo. `decisions()` là hàm thuần: cùng báo cáo cho
cùng quyết định, nên việc "xây hay không xây" một cơ chế phối hợp là cơ học, không phải cảm tính sau khi thấy số.

Phạm vi trung thực: dữ liệu mô phỏng (SYNTHETIC) chỉ biện minh được cho cận thông tin, cơ chế của hub và an toàn. Mức phổ biến lỗi của
LLM thật, và việc LLM có làm theo gợi ý hay không, KHÔNG quyết định được ở đây (xem `REAL_LLM_EXPERIMENT`).
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import TYPE_CHECKING

from rfcv.common.hashing import content_hash
from rfcv.eval.metrics import mcnemar_exact

if TYPE_CHECKING:
    from rfcv.eval.coord_sim import CoordCell, CoordReport

# ---- ngưỡng (đóng băng) ------------------------------------------------------------------------------------------
PLAYBOOK_MIN_RATIO = 0.95  # D-PB: quyết định của PLAYBOOK so với ORACLE-FULL trên worker sạch
D1_MIN_DELTA = 0.10  # D1: tăng tỉ lệ quyết định tối thiểu khi có mã lỗi
D1_MIN_ROUNDS_SAVED = 1  # hoặc tiết kiệm tối thiểu số vòng (trung vị)
ALPHA = 0.05
D4_MIN_WASTE_REDUCTION = 0.50
D4_MAX_DECISIVE_DROP = 0.02
D5_MIN_LOSS = 0.10
D5_MIN_RECOVERY = 0.80
FAILING_Q = 0.3

D1B_MIN_ASSURANCE_GAIN = 0.25  # trung bình hạng độ bảo đảm tăng thêm tối thiểu (LINKED=3, BEHAVIORAL=2, STATIC=1)

DECISIVE = ("COMPLIANT", "VIOLATION")
ASSURANCE_RANK = {"LINKED": 3, "BEHAVIORAL": 2, "STATIC": 1}

PREREG_VERSION = 2
PREREG_HISTORY = (
    "v1 (chạy lần đầu, 2 seed): D1, D4, D5 KHÔNG ĐẠT theo tiêu chí gốc; D-PB, H0 ĐẠT. Khi diễn giải, phát hiện hai lỗi của chính mô hình "
    "mô phỏng (người đọc mã báo MISMATCH cho cài đặt hợp lệ thay thế; Verifier luôn 'sạch' nên chuỗi phản biện→Planner→đọc mã không chạy) "
    "và một thiếu sót của tiêu chí: D1 chỉ nhìn tỉ lệ quyết định, trong khi hub dừng ngay khi có nhãn quyết định, nên phối hợp tốt hay "
    "kém chủ yếu hiện ra ở ĐỘ BẢO ĐẢM (LINKED so với BEHAVIORAL) và số vòng. v2 sửa hai lỗi mô hình và THÊM tiêu chí D1b (độ bảo đảm). "
    "D1b được thêm SAU khi thấy dữ liệu v1 nên là thăm dò; các ngưỡng gốc của D1, D4, D5 không đổi."
)


@dataclass(frozen=True)
class Experiment:
    exp: str
    policies: tuple[str, ...]
    profiles: tuple[str, ...]
    arms: tuple[str, ...] = ("base",)


ALL_POLICIES = (
    "ORACLE-FULL",
    "ORACLE-OBS-codes",
    "ORACLE-OBS-bool",
    "PLAYBOOK",
    "RANDOM-VALID",
    "REPEATER",
    "PREMATURE",
    "CRITIQUE-IGNORER",
)
EXPERIMENTS: tuple[Experiment, ...] = (
    Experiment("E1", ALL_POLICIES, ("W0",)),
    Experiment("E2", ("ORACLE-FULL", "ORACLE-OBS-bool", "ORACLE-OBS-codes"), ("W1", "W2", "W3", "W4", "W5", "W6")),
    Experiment("E3", ("REPEATER", "ORACLE-OBS-bool"), ("W1", "W2"), ("base", "progress")),
    Experiment(
        "E4",
        (
            "ORACLE-OBS-bool",
            f"FAILING:{FAILING_Q}:ORACLE-OBS-bool",
            f"FALLBACK:FAILING:{FAILING_Q}:ORACLE-OBS-bool",
        ),
        ("W0",),
    ),
)

HYPOTHESES = {
    "H0": "Thất bại phối hợp chỉ hạ độ phủ/độ bảo đảm, không đảo chiều nhãn (an toàn).",
    "D-PB": "Sổ tay dạng dữ liệu đủ dùng khi worker sạch (cận dưới của chất lượng dẫn đường).",
    "D1": "Mã kết quả có kiểu giúp ích (so với chỉ bool), tức là C1 đáng xây.",
    "D1b": "Như D1 nhưng đo ở độ bảo đảm của nhãn quyết định (thêm ở v2, thăm dò).",
    "D4": "Bộ phát hiện lặp theo tiến triển giảm lãng phí mà không cắt nhầm việc thử lại hợp lệ (C2).",
    "D5": "Phương án dự phòng tất định khi Planner lỗi hồi phục phần lớn quyết định bị mất (C4).",
}
NOT_DECIDABLE_BY_SIMULATION = (
    "Tiêm `guidance.next` vào Planner LLM (C3b)",
    "Mức phổ biến lỗi phối hợp của LLM thật",
    "Tiếp tục sau NEEDS_REVIEW (D6): không xây, vì tiếp tục tới khi có nhãn đẹp hơn là chọn nhãn có lợi",
)
REAL_LLM_EXPERIMENT = (
    "Cùng tập yêu cầu, Planner LLM có/không `guidance.next`; so cặp trên cặp (yêu cầu, seed) bằng McNemar chính xác; "
    "báo thêm tỉ lệ tuân thủ và tỉ lệ đi chệch không khai báo (`deviated_unannounced`)."
)


def config_hash(seeds: int) -> str:
    return content_hash(
        {
            "seeds": seeds,
            "experiments": [
                {"exp": e.exp, "policies": e.policies, "profiles": e.profiles, "arms": e.arms} for e in EXPERIMENTS
            ],
            "thresholds": [
                PLAYBOOK_MIN_RATIO,
                D1_MIN_DELTA,
                D1_MIN_ROUNDS_SAVED,
                ALPHA,
                D4_MIN_WASTE_REDUCTION,
                D4_MAX_DECISIVE_DROP,
                D5_MIN_LOSS,
                D5_MIN_RECOVERY,
                FAILING_Q,
                D1B_MIN_ASSURANCE_GAIN,
                PREREG_VERSION,
            ],
        }
    )


@dataclass(frozen=True)
class Decision:
    id: str
    passed: bool | None  # None: không đủ dữ liệu để quyết định
    evidence: str


def _pairs(a: list[CoordCell], b: list[CoordCell]) -> list[tuple[CoordCell, CoordCell]]:
    index = {(c.impl, c.seed): c for c in b}
    return [(c, index[(c.impl, c.seed)]) for c in a if (c.impl, c.seed) in index]


def _dec(c: CoordCell) -> bool:
    return c.r.label in DECISIVE


def safety(report: CoordReport) -> Decision:
    """H0: không COMPLIANT sai trên cài đặt lỗi mà ORACLE-FULL không COMPLIANT; không VIOLATION trên cài đặt đúng."""
    truth = report.truth()
    bad_compliant = bad_violation = 0
    for c in report.cells:
        if c.kind in ("correct", "alt_valid") and c.r.label == "VIOLATION":
            bad_violation += 1
        if c.kind == "faulty" and c.r.label == "COMPLIANT" and truth.get((c.impl, c.seed)) != "COMPLIANT":
            bad_compliant += 1
    ok = bad_compliant == 0 and bad_violation == 0
    return Decision("H0", ok, f"COMPLIANT sai so với ORACLE-FULL: {bad_compliant}; VIOLATION sai: {bad_violation}")


def playbook_completeness(report: CoordReport) -> Decision:
    full = report.by("E1", "ORACLE-FULL", "W0")
    pb = report.by("E1", "PLAYBOOK", "W0")
    n_full, n_pb = sum(map(_dec, full)), sum(map(_dec, pb))
    if not full or n_full == 0:
        return Decision("D-PB", None, "không có dữ liệu")
    agree = all(a.r.label == b.r.label for a, b in _pairs(pb, full) if _dec(a) and _dec(b))
    return Decision(
        "D-PB",
        n_pb >= PLAYBOOK_MIN_RATIO * n_full and agree,
        f"quyết định PLAYBOOK {n_pb}/{len(pb)} so với ORACLE-FULL {n_full}/{len(full)}; nhãn đồng thuận={agree}",
    )


def typed_outcomes(report: CoordReport) -> Decision:
    """D1: mã lỗi cổng giúp bao nhiêu so với chỉ bool, ở các worker W1–W4 có thể sửa được."""
    notes: list[str] = []
    passed = False
    seen = False
    for prof in ("W1", "W2", "W3", "W4"):
        pairs = _pairs(report.by("E2", "ORACLE-OBS-codes", prof), report.by("E2", "ORACLE-OBS-bool", prof))
        if not pairs:
            continue
        seen = True
        b = sum(_dec(x) and not _dec(y) for x, y in pairs)
        c = sum(_dec(y) and not _dec(x) for x, y in pairs)
        delta, p = (b - c) / len(pairs), mcnemar_exact(b, c)
        saved = [y.r.planner_calls - x.r.planner_calls for x, y in pairs]
        fewer = sum(s > 0 for s in saved)
        more = sum(s < 0 for s in saved)
        p_rounds = mcnemar_exact(fewer, more)
        win = (delta >= D1_MIN_DELTA and p < ALPHA) or (median(saved) >= D1_MIN_ROUNDS_SAVED and p_rounds < ALPHA)
        passed |= win
        notes.append(
            f"{prof}: Δquyết định={delta:+.2f} (p={p:.3f}), vòng tiết kiệm trung vị={median(saved):+.1f} (p={p_rounds:.3f})"
        )
    return Decision("D1", passed if seen else None, "; ".join(notes) or "không có dữ liệu")


def typed_outcomes_assurance(report: CoordReport) -> Decision:
    """D1b (thăm dò, thêm ở v2): mã lỗi cổng có nâng độ bảo đảm của nhãn quyết định so với chỉ bool không."""
    notes: list[str] = []
    passed = False
    seen = False
    for prof in ("W1", "W2", "W3", "W4"):
        pairs = _pairs(report.by("E2", "ORACLE-OBS-codes", prof), report.by("E2", "ORACLE-OBS-bool", prof))
        if not pairs:
            continue
        seen = True

        def rank(c: CoordCell) -> int:
            return ASSURANCE_RANK.get(c.r.assurance or "", 0) if _dec(c) else 0

        gains = [rank(x) - rank(y) for x, y in pairs]
        b, c = sum(g > 0 for g in gains), sum(g < 0 for g in gains)
        mean, p = sum(gains) / len(gains), mcnemar_exact(b, c)
        passed |= mean >= D1B_MIN_ASSURANCE_GAIN and p < ALPHA
        notes.append(f"{prof}: Δhạng bảo đảm TB={mean:+.2f} (hơn {b}, kém {c}, p={p:.3f})")
    return Decision("D1b", passed if seen else None, "; ".join(notes) or "không có dữ liệu")


def progress_detector(report: CoordReport) -> Decision:
    base, prog = report.by("E3", "REPEATER", "W2", "base"), report.by("E3", "REPEATER", "W2", "progress")
    if not base or not prog:
        return Decision("D4", None, "không có dữ liệu")

    def share(cells: list[CoordCell]) -> float:
        calls = sum(c.r.planner_calls for c in cells)
        return sum(c.r.wasted for c in cells) / calls if calls else 0.0

    s0, s1 = share(base), share(prog)
    reduction = (s0 - s1) / s0 if s0 else 0.0
    obs_b = report.by("E3", "ORACLE-OBS-bool", "W1", "base")
    obs_p = report.by("E3", "ORACLE-OBS-bool", "W1", "progress")
    pairs = _pairs(obs_p, obs_b)
    drop = (sum(map(_dec, obs_b)) - sum(map(_dec, obs_p))) / len(obs_b) if obs_b else 0.0
    b = sum(_dec(x) and not _dec(y) for x, y in pairs)
    c = sum(_dec(y) and not _dec(x) for x, y in pairs)
    p = mcnemar_exact(b, c)
    ok = reduction >= D4_MIN_WASTE_REDUCTION and drop <= D4_MAX_DECISIVE_DROP and p >= ALPHA
    return Decision(
        "D4",
        ok,
        f"lãng phí REPEATER {s0:.2f}→{s1:.2f} (giảm {reduction:.0%}); quyết định OBS-bool/W1 giảm {drop:+.2f} (McNemar p={p:.3f})",
    )


def planner_fallback(report: CoordReport) -> Decision:
    q = f"FAILING:{FAILING_Q}:ORACLE-OBS-bool"
    base = report.by("E4", "ORACLE-OBS-bool", "W0")
    failing = report.by("E4", q, "W0")
    fallback = report.by("E4", f"FALLBACK:{q}", "W0")
    if not base or not failing or not fallback:
        return Decision("D5", None, "không có dữ liệu")
    d0, d1, d2 = (sum(map(_dec, x)) / len(x) for x in (base, failing, fallback))
    loss, recovered = d0 - d1, d2 - d1
    ok = loss >= D5_MIN_LOSS and recovered >= D5_MIN_RECOVERY * loss
    return Decision("D5", ok, f"quyết định q=0: {d0:.2f}, q={FAILING_Q}: {d1:.2f}, có dự phòng: {d2:.2f}")


def decisions(report: CoordReport) -> list[Decision]:
    return [
        safety(report),
        playbook_completeness(report),
        typed_outcomes(report),
        typed_outcomes_assurance(report),
        progress_detector(report),
        planner_fallback(report),
    ]

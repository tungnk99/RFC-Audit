"""Điều tra mã song song nhiều giả thuyết (Best-of-K) và chọn ứng viên tất định qua Schema gate.

Thay vì ép mô hình gọn/flash chạy một vòng ReAct dài 20+ lượt dễ trượt mục tiêu, ta tách thành K (mặc định 3)
giả thuyết ngắn chạy song song theo các góc tiếp cận khác nhau (`diagnosis_first`, `alert_and_reaction`,
`macro_and_ifdef`). Mỗi nhánh đều phải đi qua Schema gate tất định; bộ chọn ứng viên chấm điểm thuần trên cấu
trúc `LocationClaim` đã xác minh (tuyệt đối không đọc `note` mang nhãn UNTRUSTED) và chọn ứng viên tốt nhất.
"""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from rfcv.domains.rfc_protocol.payloads import AspectValue, Finding
from rfcv.domains.rfc_protocol.schema_gate import SchemaGate
from rfcv.domains.rfc_protocol.schemas import LocationClaim
from rfcv.gates.tool_gateway import ToolSession

STRATEGY_DIAGNOSIS_FIRST = "diagnosis_first"
STRATEGY_ALERT_AND_REACTION = "alert_and_reaction"
STRATEGY_MACRO_AND_IFDEF = "macro_and_ifdef"

MAX_HYPOTHESES = 3


def _empty_params() -> dict[str, Any]:
    return {}


@dataclass(frozen=True)
class HypothesisSpec:
    """Một hướng điều tra độc lập cho nhánh song song của Code Reader."""

    name: str
    strategy: str
    focus_hint: str
    extra_params: dict[str, Any] = field(default_factory=_empty_params)

    def to_json(self) -> dict[str, object]:
        return asdict(self)


def build_hypotheses(base_params: Mapping[str, Any], k: int = 3) -> list[HypothesisSpec]:
    """Dựng tối đa `k` giả thuyết điều tra phân biệt, tất định từ tham số gốc.

    Thứ tự cố định:
    1. `diagnosis_first`: bám thẳng `behavior.diagnosis` / `code.candidates` (hoặc gợi ý locator) để xác minh giả thuyết chính.
    2. `alert_and_reaction`: lần từ điểm phát cảnh báo / mã lỗi / đóng kết nối ngược lên đường gọi xử lý.
    3. `macro_and_ifdef`: rà nhánh tiền xử lý `#ifdef`/`#if`, dòng `[DISABLED]` và khai triển hằng ngưỡng bằng `code__eval`.

    Nếu `k <= 0` trả danh sách rỗng; nếu `k > 3` giới hạn ở số chiến lược phân biệt sẵn có.
    """
    if k <= 0:
        return []

    base_copy: dict[str, Any] = copy.deepcopy(dict(base_params))
    default_start_hints = base_copy.get("start_hints", "locator")

    specs = [
        HypothesisSpec(
            name=STRATEGY_DIAGNOSIS_FIRST,
            strategy=STRATEGY_DIAGNOSIS_FIRST,
            focus_hint=(
                "Bắt đầu trực tiếp từ `behavior.diagnosis` và `code.candidates` (hoặc `locator__suggest` nếu chưa có chẩn đoán); "
                "đọc hàm ứng viên chính, kiểm đủ điều kiện, ngưỡng và phản ứng, rồi lần đường gọi trong 2-3 lượt."
            ),
            extra_params={
                **copy.deepcopy(base_copy),
                "hypothesis": STRATEGY_DIAGNOSIS_FIRST,
                "start_hints": default_start_hints,
                "priority_aspects": ["CONDITION", "THRESHOLD", "REACTION"],
                "max_turns_hint": 3,
            },
        ),
        HypothesisSpec(
            name=STRATEGY_ALERT_AND_REACTION,
            strategy=STRATEGY_ALERT_AND_REACTION,
            focus_hint=(
                "Tập trung vào nơi phát cảnh báo, trả mã lỗi và đóng kết nối (`code__grep` mã phản ứng trong `expect`), "
                "sau đó lần ngược đường gọi (`call_path`) tới phép kiểm tra để xác định luồng thất bại đi đâu."
            ),
            extra_params={
                **copy.deepcopy(base_copy),
                "hypothesis": STRATEGY_ALERT_AND_REACTION,
                "start_hints": "none",
                "priority_aspects": ["REACTION", "ORDER_STATE", "EFFECT"],
                "max_turns_hint": 3,
            },
        ),
        HypothesisSpec(
            name=STRATEGY_MACRO_AND_IFDEF,
            strategy=STRATEGY_MACRO_AND_IFDEF,
            focus_hint=(
                "Kiểm tra các khối tiền xử lý `#ifdef`/`#if`, dòng gắn nhãn `[DISABLED]` trong `code__read`, "
                "và dùng `code__eval` cho `defined(MACRO)` cùng biểu thức ngưỡng hằng để phát hiện mã bị biên dịch bỏ (`disabled_by`)."
            ),
            extra_params={
                **copy.deepcopy(base_copy),
                "hypothesis": STRATEGY_MACRO_AND_IFDEF,
                "start_hints": default_start_hints,
                "priority_aspects": ["THRESHOLD", "REACTION", "CONDITION"],
                "check_disabled_macros": True,
                "max_turns_hint": 3,
            },
        ),
    ]
    return specs[: min(k, len(specs))]


@dataclass(frozen=True)
class CandidateScore:
    """Điểm chấm tất định cho một `LocationClaim` sau Schema gate (không đọc `claim.note`)."""

    gate_ok: bool
    has_disabled_by: bool
    finding_decisive: bool
    mismatch_aspects: int
    decisive_aspects: int
    unclear_aspects: int
    unexplored_count: int
    has_call_path: bool
    call_path_len: int
    line_span: int
    gate_error_count: int

    @property
    def rank_key(self) -> tuple[int, int, int, int, int, int, int, int, int, int]:
        """Khóa sắp xếp tất định (lớn hơn = ưu tiên hơn):
        (a) `gate_ok` (0 lỗi cổng),
        (b) bằng chứng dứt khoát (`disabled_by` đã xác minh, `finding` khác `UNCLEAR`, nhiều `MATCH`/`MISMATCH` hơn `UNCLEAR`),
        (c) ít mục `unexplored` hơn,
        (d) có `call_path` không rỗng (và sâu hơn khi hòa),
        (e) khoảng dòng gọn hơn (`line_end - line_start`).
        """
        return (
            1 if self.gate_ok else 0,
            1 if self.has_disabled_by else 0,
            1 if self.finding_decisive else 0,
            self.decisive_aspects - self.unclear_aspects,
            self.decisive_aspects,
            self.mismatch_aspects,
            -self.unexplored_count,
            1 if self.has_call_path else 0,
            self.call_path_len,
            -self.line_span,
        )

    def to_json(self) -> dict[str, object]:
        return asdict(self)


def score_claim(claim: LocationClaim, gate_errors: Sequence[str]) -> CandidateScore:
    """Chấm điểm tất định một `LocationClaim` kèm danh sách lỗi từ Schema gate.

    Lưu ý an toàn IFC: hàm này không bao giờ đọc trường tự do `claim.note` (UNTRUSTED).
    """
    unique_errors = tuple(dict.fromkeys(gate_errors))
    mismatch_count = sum(1 for a in claim.aspects if a.value is AspectValue.MISMATCH)
    match_count = sum(1 for a in claim.aspects if a.value is AspectValue.MATCH)
    unclear_count = sum(1 for a in claim.aspects if a.value is AspectValue.UNCLEAR)
    span = max(0, claim.line_end - claim.line_start)
    return CandidateScore(
        gate_ok=len(unique_errors) == 0,
        has_disabled_by=bool(claim.disabled_by),
        finding_decisive=claim.finding is not Finding.UNCLEAR,
        mismatch_aspects=mismatch_count,
        decisive_aspects=mismatch_count + match_count,
        unclear_aspects=unclear_count,
        unexplored_count=len(claim.unexplored),
        has_call_path=bool(claim.call_path),
        call_path_len=len(claim.call_path),
        line_span=span,
        gate_error_count=len(unique_errors),
    )


@dataclass(frozen=True)
class BranchOutcome:
    """Kết quả và telemetry của một nhánh giả thuyết trong giải đấu Best-of-K."""

    hypothesis_name: str
    claim: LocationClaim | None
    gate_errors: tuple[str, ...] = ()
    error: str | None = None
    score: CandidateScore | None = None

    @property
    def valid(self) -> bool:
        return self.claim is not None and self.error is None and not self.gate_errors

    def to_telemetry(self) -> dict[str, object]:
        """Telemetry an toàn cho trace (không ghi `claim.note` mang nhãn UNTRUSTED)."""
        return {
            "hypothesis": self.hypothesis_name,
            "valid": self.valid,
            "has_claim": self.claim is not None,
            "gate_errors": list(self.gate_errors),
            "error": self.error,
            "score": self.score.to_json() if self.score is not None else None,
        }


@dataclass(frozen=True)
class TournamentResult:
    """Kết quả giải đấu Best-of-K: ứng viên thắng cuộc (nếu có) và toàn bộ telemetry từng nhánh."""

    winner: LocationClaim | None
    winner_hypothesis: str | None
    winner_score: CandidateScore | None
    branches: tuple[BranchOutcome, ...]
    failure_reasons: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.winner is not None

    def to_telemetry(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "winner_hypothesis": self.winner_hypothesis,
            "winner_score": self.winner_score.to_json() if self.winner_score is not None else None,
            "branch_count": len(self.branches),
            "valid_branches": sum(1 for b in self.branches if b.valid),
            "failure_reasons": list(self.failure_reasons),
            "branches": [b.to_telemetry() for b in self.branches],
        }


def _failure_reason_for(outcome: BranchOutcome) -> str | None:
    if outcome.valid:
        return None
    if outcome.error is not None:
        return f"{outcome.hypothesis_name}: EXCEPTION({outcome.error})"
    if outcome.gate_errors:
        return f"{outcome.hypothesis_name}: {', '.join(outcome.gate_errors)}"
    return f"{outcome.hypothesis_name}: NO_CLAIM"


def _select_from_outcomes(outcomes: Sequence[BranchOutcome]) -> TournamentResult:
    branches = tuple(outcomes)
    if not branches:
        return TournamentResult(
            winner=None,
            winner_hypothesis=None,
            winner_score=None,
            branches=(),
            failure_reasons=("NO_CANDIDATES",),
        )

    failure_reasons = tuple(reason for b in branches if (reason := _failure_reason_for(b)) is not None)
    eligible: list[tuple[int, BranchOutcome, CandidateScore]] = [
        (idx, b, b.score)
        for idx, b in enumerate(branches)
        if b.valid and b.claim is not None and b.score is not None and b.score.gate_ok
    ]
    if not eligible:
        return TournamentResult(
            winner=None,
            winner_hypothesis=None,
            winner_score=None,
            branches=branches,
            failure_reasons=failure_reasons,
        )

    # Điểm cao nhất thắng; nếu hòa toàn bộ tiêu chí, ưu tiên nhánh xuất hiện trước (tất định).
    _, best_branch, best_score = max(eligible, key=lambda item: (item[2].rank_key, -item[0]))
    return TournamentResult(
        winner=best_branch.claim,
        winner_hypothesis=best_branch.hypothesis_name,
        winner_score=best_score,
        branches=branches,
        failure_reasons=failure_reasons,
    )


def select_best_claim(
    candidates: Sequence[tuple[str, LocationClaim | None, Sequence[str]]],
) -> TournamentResult:
    """Chạy chọn ứng viên tất định trên đầu ra các nhánh; tuyệt đối không nhận claim có lỗi Schema gate."""
    outcomes: list[BranchOutcome] = []
    for name, claim, raw_errors in candidates:
        gate_errors = tuple(dict.fromkeys(raw_errors))
        score = score_claim(claim, gate_errors) if claim is not None else None
        outcomes.append(BranchOutcome(hypothesis_name=name, claim=claim, gate_errors=gate_errors, score=score))
    return _select_from_outcomes(outcomes)


async def run_best_of_k(
    hypotheses: Sequence[HypothesisSpec],
    run_branch: Callable[[HypothesisSpec], Awaitable[tuple[LocationClaim | None, Sequence[str]]]],
) -> TournamentResult:
    """Chạy song song toàn bộ K nhánh bằng `asyncio.gather(..., return_exceptions=True)` và chọn ứng viên tốt nhất.

    Ngoại lệ trong một nhánh (`Exception`) được cô lập thành telemetry lỗi để không làm sập giải đấu;
    tín hiệu huỷ tác vụ (`asyncio.CancelledError`) vẫn được truyền lên đúng chuẩn asyncio.
    """
    if not hypotheses:
        return _select_from_outcomes(())

    raw_results = await asyncio.gather(*(run_branch(h) for h in hypotheses), return_exceptions=True)

    outcomes: list[BranchOutcome] = []
    for hyp, raw in zip(hypotheses, raw_results, strict=True):
        if isinstance(raw, BaseException):
            if not isinstance(raw, Exception):
                raise raw
            outcomes.append(
                BranchOutcome(
                    hypothesis_name=hyp.name,
                    claim=None,
                    gate_errors=(),
                    error=f"{type(raw).__name__}: {raw}",
                    score=None,
                )
            )
            continue
        claim, raw_errors = raw
        gate_errors = tuple(dict.fromkeys(raw_errors))
        score = score_claim(claim, gate_errors) if claim is not None else None
        outcomes.append(BranchOutcome(hypothesis_name=hyp.name, claim=claim, gate_errors=gate_errors, score=score))

    return _select_from_outcomes(outcomes)


def evaluate_claim_with_gate(
    claim: LocationClaim | None,
    gate: SchemaGate,
    session: ToolSession,
    *,
    run_id: str,
    requirement_id: str,
    msg_id: str = "",
    threshold: int | None = None,
) -> tuple[LocationClaim | None, tuple[str, ...]]:
    """Chạy Schema gate (không ghi kho) cho một nhánh Best-of-K, trả `(claim, gate_errors)`."""
    if claim is None:
        return None, ("NO_CLAIM",)
    result = gate.check_location(
        claim,
        session,
        run_id=run_id,
        requirement_id=requirement_id,
        msg_id=msg_id,
        threshold=threshold,
    )
    return claim, result.errors

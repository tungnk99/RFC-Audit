"""Payload bằng chứng của miền RFC giao thức (thiết kế chính, Bảng 5): T1 vị trí mã, T2 phân tích tĩnh, T3 chạy thực tế.

T0 (nhận định LLM chưa đối chiếu) không bao giờ được lưu thành bằng chứng.
Chiều (polarity) được tính tất định từ payload, không do agent khai.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rfcv.core.ifc import VerifiedRef
from rfcv.spi import EvidenceKind, Polarity

DOMAIN = "rfc_protocol"


class Tier(StrEnum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


class Producer(StrEnum):
    """Chỉ thành phần tất định được ghi bằng chứng (Hình 4, bước ⑦ và ⑩)."""

    TEST_DRIVER = "test_driver"
    SCHEMA_GATE = "schema_gate"
    CODE_GATE = "code_gate"
    COVERAGE_LINKER = "coverage_linker"


class Outcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


class AspectValue(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNCLEAR = "UNCLEAR"


class AspectName(StrEnum):
    CONDITION = "CONDITION"
    THRESHOLD = "THRESHOLD"
    REACTION = "REACTION"
    ORDER_STATE = "ORDER_STATE"
    EFFECT = "EFFECT"


class Finding(StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNCLEAR = "UNCLEAR"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AspectCheck(_Frozen):
    aspect: AspectName
    value: AspectValue
    observed: str | int | None = None
    lines: tuple[int, int]


class T1Payload(_Frozen):
    """Vị trí mã đã đối chiếu với chỉ mục tại commit (do Schema gate ghi)."""

    kind: Literal["location"] = "location"
    file: str
    symbol: str
    line_start: int
    line_end: int
    finding: Finding
    aspects: tuple[AspectCheck, ...] = ()
    call_path: tuple[str, ...] = ()
    # Căn cứ của từng cạnh call_path[i] → call_path[i+1]: "index" (chỉ mục lời gọi, hoặc công cụ cấu trúc đã hiển thị)
    # hay "textual" (chỉ thấy qua một dòng mã đã hiển thị, ví dụ gán con trỏ hàm, bảng xử lý).
    call_edge_kinds: tuple[Literal["index", "textual"], ...] = ()
    unexplored: tuple[str, ...] = ()

    @property
    def refutes(self) -> bool:
        """ "T1 bác bỏ" = ABSENT hoặc có khía cạnh MISMATCH (tài liệu phối hợp agent, mục 7.1)."""
        return self.finding is Finding.ABSENT or any(a.value is AspectValue.MISMATCH for a in self.aspects)


class T2StaticPayload(_Frozen):
    """Kết quả truy vấn phân tích tĩnh đã qua kiểm định đột biến (loại D)."""

    kind: Literal["static_query"] = "static_query"
    query: str  # hash truy vấn đã cố định
    validated: bool
    paths_examined: int
    violating_paths: int


class T2SuspiciousPayload(_Frozen):
    """Nhánh nghi vấn (M7): so với hằng trùng giá trị kiểm thử, đọc biến môi trường, tên máy…"""

    kind: Literal["suspicious_branch"] = "suspicious_branch"
    rule_id: str
    file: str
    line: int
    on_path: bool


class WitnessRun(_Frozen):
    impl: str
    outcome: Outcome


class Witness(_Frozen):
    positive: tuple[WitnessRun, ...] = ()
    negative: tuple[WitnessRun, ...] = ()

    @property
    def has_positive(self) -> bool:
        return any(r.outcome is Outcome.PASS for r in self.positive)

    @property
    def all_positive_fail(self) -> bool:
        return bool(self.positive) and all(r.outcome is Outcome.FAIL for r in self.positive)


class CoverageLink(_Frozen):
    t1: str
    lines_hit: tuple[int, ...]
    linked: bool


class T3Payload(_Frozen):
    """Kết quả chạy kịch bản trên SUT, phán định bằng oracle biên dịch, có nhân chứng."""

    kind: Literal["scenario_result"] = "scenario_result"
    scenario: str
    oracle: str
    variant: str
    variant_class: Literal["required", "random", "control", "valid_random", "probe"]
    side: Literal["trigger", "valid"] = "trigger"  # trigger: phải có phản ứng; valid: không được có phản ứng
    params: dict[str, int | str] = Field(default_factory=dict)
    seed: int | None = None
    trigger_reached: bool
    outcome: Outcome
    observed: dict[str, str | int | bool] = Field(default_factory=dict)
    runs: int = 1
    consistent: bool = True
    environments_consistent: bool = True
    signature_matches: bool = True
    origin: Literal["scenario", "state_learning"] = "scenario"
    witness: Witness = Witness()
    coverage_link: CoverageLink | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return self.trigger_reached and self.outcome is not Outcome.ERROR


class T3LinkPayload(_Frozen):
    """Liên kết độ phủ giữa một T3 và một T1, do Coverage linker ghi khi đã có cả hai.

    Bằng chứng bất biến và T1, T3 có thể đến theo thứ tự bất kỳ, nên liên kết là bản ghi riêng
    thay vì sửa T3. T3 có bản ghi liên kết với linked = True được gọi là "T3 liên kết" (M4).
    """

    kind: Literal["coverage_link"] = "coverage_link"
    t3: str
    t1: str
    lines_hit: tuple[int, ...]
    linked: bool


# ---- chiều của bằng chứng ------------------------------------------------------------------------


def _polarity_t1(p: T1Payload) -> Polarity:
    if p.refutes:
        return Polarity.REFUTES
    return Polarity.NEUTRAL if p.finding is Finding.UNCLEAR else Polarity.SUPPORTS


def _polarity_t2(p: T2StaticPayload) -> Polarity:
    if not p.validated:
        return Polarity.NEUTRAL
    return Polarity.REFUTES if p.violating_paths > 0 else Polarity.SUPPORTS


def _polarity_neutral(_: Any) -> Polarity:
    return Polarity.NEUTRAL


def _polarity_t3(p: T3Payload) -> Polarity:
    return {Outcome.PASS: Polarity.SUPPORTS, Outcome.FAIL: Polarity.REFUTES, Outcome.ERROR: Polarity.NEUTRAL}[p.outcome]


# ---- tóm tắt cho agent đặc quyền: chỉ giá trị miền hữu hạn hoặc đã đối chiếu -----------------------

UNVERIFIED = VerifiedRef("<unverified>")  # hằng do harness sinh, thay cho giá trị ngoài từ vựng


def _ref(value: str, allowed: frozenset[str]) -> VerifiedRef:
    return VerifiedRef(value) if value in allowed else UNVERIFIED


def _summarize_t1(e: Any, terms: frozenset[str]) -> dict[str, Any]:
    t1: T1Payload = e.payload
    return {
        "file": VerifiedRef(t1.file),
        "symbol": VerifiedRef(t1.symbol),
        "lines": (t1.line_start, t1.line_end),
        "finding": t1.finding,
        "aspects": [
            {
                "aspect": a.aspect,
                "value": a.value,
                "observed": a.observed if isinstance(a.observed, int | None) else _ref(a.observed, terms),
            }
            for a in t1.aspects
        ],
        "call_path": [VerifiedRef(s) for s in t1.call_path],
        "unexplored_count": len(t1.unexplored),
    }


def _summarize_t2(e: Any, terms: frozenset[str]) -> dict[str, Any]:
    p: T2StaticPayload = e.payload
    return {
        "validated": p.validated,
        "paths_examined": p.paths_examined,
        "violating_paths": p.violating_paths,
    }


def _summarize_suspicious(e: Any, terms: frozenset[str]) -> dict[str, Any]:
    p: T2SuspiciousPayload = e.payload
    return {"suspicious_on_path": p.on_path, "rule_id": VerifiedRef(p.rule_id)}


def _summarize_t3(e: Any, terms: frozenset[str]) -> dict[str, Any]:
    t3: T3Payload = e.payload
    return {
        "variant": VerifiedRef(t3.variant),
        "variant_class": VerifiedRef(t3.variant_class),
        "outcome": t3.outcome,
        "trigger_reached": t3.trigger_reached,
        "consistent": t3.consistent,
        "alert": _ref(str(t3.observed.get("alert", "none")), terms | {"none"}),
        "closed": bool(t3.observed.get("closed", False)),
        "witness_positive": t3.witness.has_positive,
        "linked": bool(t3.coverage_link and t3.coverage_link.linked),
    }


def _routine_t3(e: Any) -> bool:
    """T3 không có gì đáng chú ý: PASS, kích hoạt đạt, nhất quán, chưa liên kết độ phủ. Loại này được gộp theo biến thể;
    FAIL, ERROR, không nhất quán hay đã liên kết giữ hàng riêng."""
    t3: T3Payload = e.payload
    linked = bool(t3.coverage_link and t3.coverage_link.linked)
    return t3.outcome is Outcome.PASS and t3.trigger_reached and t3.consistent and not linked


def _summarize_link(e: Any, terms: frozenset[str]) -> dict[str, Any]:
    p: T3LinkPayload = e.payload
    return {"link_t3": VerifiedRef(p.t3), "link_t1": VerifiedRef(p.t1), "linked": p.linked}


def evidence_kinds() -> list[EvidenceKind]:
    """Năm loại bằng chứng của miền. Chỉ thành phần tất định (producers) được ghi."""
    return [
        EvidenceKind("location", Tier.T1, T1Payload, frozenset({Producer.SCHEMA_GATE}), _polarity_t1, _summarize_t1),
        EvidenceKind(
            "static_query", Tier.T2, T2StaticPayload, frozenset({Producer.CODE_GATE}), _polarity_t2, _summarize_t2
        ),
        EvidenceKind(
            "suspicious_branch",
            Tier.T2,
            T2SuspiciousPayload,
            frozenset({Producer.CODE_GATE}),
            _polarity_neutral,
            _summarize_suspicious,
        ),
        EvidenceKind(
            "scenario_result",
            Tier.T3,
            T3Payload,
            frozenset({Producer.TEST_DRIVER}),
            _polarity_t3,
            _summarize_t3,
            is_routine=_routine_t3,
            fold_fields=("variant",),
            version=2,
            # v1 -> v2 chỉ thêm trường có mặc định (side); payload cũ hợp lệ nguyên vẹn.
            upgrades={1: lambda payload: payload},
        ),
        EvidenceKind(
            "coverage_link",
            Tier.T3,
            T3LinkPayload,
            frozenset({Producer.COVERAGE_LINKER}),
            _polarity_neutral,
            _summarize_link,
        ),
    ]

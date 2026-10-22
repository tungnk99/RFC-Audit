"""Oracle compiler: biên dịch RBS thành oracle trên vết sự kiện và tập biến thể (M2).

Hàm thuần, tất định. LLM không viết oracle và không đánh giá kết quả:
kết quả PASS/FAIL do CompiledOracle.evaluate tính trên vết sự kiện chuẩn hoá.
ERROR (chưa tới trigger, sanity hỏng, hết giờ) do Test driver quyết định, không do oracle.

Biến thể gồm: đối chứng đúng ngưỡng, biên, đầu mút miền, lấy mẫu phía vi phạm (đều hoặc phân tầng), lấy mẫu phía HỢP LỆ
(để bắt lỗi từ chối nhầm dữ liệu hợp lệ), và dò ngưỡng. Mọi giá trị lấy mẫu là hàm thuần của (seed, tên biến thể), dựa trên
hash nên tái lập giữa mọi bản Python.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from rfcv.common.hashing import content_hash
from rfcv.common.prng import hash_randint
from rfcv.domains.rfc_protocol.payloads import Outcome
from rfcv.domains.rfc_protocol.spec.rbs import RBS, Call, Condition
from rfcv.domains.rfc_protocol.spec.vocabulary import Vocabulary, check

POWER_EXPONENTS = (8, 10, 12, 14, 15, 16)  # biên nhị phân hay gặp: 255/256, 1023/1024, 4095/4096, 16383/16384…
SAMPLED = ("random", "valid_random")


class ObservedEvent(BaseModel):
    """Một sự kiện quan sát được, đã chuẩn hoá theo từ vựng adapter; t_ms tính từ lúc kích hoạt."""

    model_config = ConfigDict(frozen=True)

    name: str
    args: tuple[str, ...] = ()
    t_ms: int = 0

    def matches(self, call: Call) -> bool:
        return self.name == call.name and self.args == call.args


class ConcreteVariant(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    variant_class: Literal["required", "random", "control", "valid_random", "probe"]
    field: str
    value: int | str | None = None
    k: int | None = None
    lo: int | None = None
    hi: int | None = None
    strategy: Literal["uniform", "stratified"] = "uniform"
    side: Literal["trigger", "valid"] = "trigger"
    special: tuple[int, ...] = ()  # giá trị đặc biệt (biên nhị phân, đầu mút) luôn được chạy cùng các tầng
    exclude: tuple[int, ...] = ()  # không bao giờ lấy mẫu (giá trị kiểm thử chuẩn, giá trị đã có biến thể cố định)
    budget: int | None = None  # probe: số lần dò tối đa

    @property
    def expected_count(self) -> int:
        """Số T3 PASS mà biến thể lấy mẫu này đòi hỏi (tầng/ngẫu nhiên cộng giá trị đặc biệt)."""
        return (self.k or 0) + len(self.special)


class CompiledOracle(BaseModel):
    model_config = ConfigDict(frozen=True)

    requirement_id: str
    rbs_hash: str
    rtype: Literal["A", "B", "C", "D"]
    trigger: Call
    where: Condition | None = None
    expect: tuple[Call, ...]
    within_ms: int | None
    forbid: tuple[Call, ...]
    alternatives: tuple[Call, ...]
    variants: tuple[ConcreteVariant, ...]

    @property
    def oracle_hash(self) -> str:
        return content_hash(self.model_dump(mode="json"))

    @property
    def required_variant_names(self) -> frozenset[str]:
        return frozenset(v.name for v in self.variants if v.variant_class in ("required", "control"))

    @property
    def random_k(self) -> int:
        """Số T3 PASS cần có ở phía vi phạm từ biến thể lấy mẫu."""
        return sum(v.expected_count for v in self.variants if v.variant_class == "random")

    @property
    def valid_random_k(self) -> int:
        """Số T3 PASS cần có ở phía hợp lệ từ biến thể lấy mẫu."""
        return sum(v.expected_count for v in self.variants if v.variant_class == "valid_random")

    def side_of(self, field: str, value: int) -> Literal["trigger", "valid"]:
        """Giá trị này thuộc phía kích hoạt (phải có phản ứng) hay phía hợp lệ (không được có phản ứng)?"""
        cond = self.where
        if cond is None or cond.field != field or not isinstance(cond.value, int):
            return "trigger"
        holds = {
            ">": value > cond.value,
            ">=": value >= cond.value,
            "<": value < cond.value,
            "<=": value <= cond.value,
            "==": value == cond.value,
            "!=": value != cond.value,
        }[cond.op]
        return "trigger" if holds else "valid"

    def evaluate(self, events: Sequence[ObservedEvent]) -> Outcome:
        """PASS khi chuỗi expect (hoặc một phương án thay thế cho phản ứng đầu) xuất hiện đúng thứ tự
        trong khoảng within, và không có hành vi bị cấm nào."""
        if any(ev.matches(f) for ev in events for f in self.forbid):
            return Outcome.FAIL
        window = [ev for ev in events if self.within_ms is None or ev.t_ms <= self.within_ms]
        rest = self.expect[1:]
        for head in (self.expect[0], *self.alternatives):
            for i, ev in enumerate(window):
                if ev.matches(head) and _subsequence(rest, window[i + 1 :]):
                    return Outcome.PASS
        return Outcome.FAIL

    def evaluate_control(self, events: Sequence[ObservedEvent]) -> Outcome:
        """Phía hợp lệ: dữ liệu hợp lệ phải được chấp nhận, tức không có phản ứng."""
        reactions = (self.expect[0], *self.alternatives)
        return Outcome.FAIL if any(ev.matches(r) for ev in events for r in reactions) else Outcome.PASS

    def reacted(self, events: Sequence[ObservedEvent]) -> bool:
        """SUT có phản ứng (phản ứng đầu của expect hoặc phương án thay thế) hay không; dùng khi dò ngưỡng."""
        reactions = (self.expect[0], *self.alternatives)
        return any(ev.matches(r) for ev in events for r in reactions)


def _subsequence(calls: Sequence[Call], events: Sequence[ObservedEvent]) -> bool:
    it = iter(events)
    return all(any(ev.matches(c) for ev in it) for c in calls)


class OracleCompileError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def _control_value(op: str, threshold: int) -> int | None:
    """Giá trị hợp lệ sát ngưỡng nhất. Với `!=` đó là giá trị hợp lệ duy nhất; nó vào tập giá trị cố định nên lấy mẫu
    phía kích hoạt không bao giờ chọn trúng nó. `==` không có một giá trị đối chứng riêng."""
    return {">": threshold, ">=": threshold - 1, "<": threshold, "<=": threshold + 1, "!=": threshold}.get(op)


def _trigger_range(cond: Condition | None, field: str, lo: int, hi: int) -> tuple[int, int]:
    if cond is not None and cond.field == field and isinstance(cond.value, int):
        if cond.op in (">", ">="):
            lo = cond.value + 1 if cond.op == ">" else cond.value
        elif cond.op in ("<", "<="):
            hi = cond.value - 1 if cond.op == "<" else cond.value
        elif cond.op == "==":
            lo = hi = cond.value
    return lo, hi


def _valid_range(cond: Condition, lo: int, hi: int) -> tuple[int, int]:
    """Phần bù của `where` trong miền: phía mà dữ liệu hợp lệ và không được có phản ứng."""
    assert isinstance(cond.value, int)
    match cond.op:
        case ">":
            return lo, cond.value
        case ">=":
            return lo, cond.value - 1
        case "<":
            return cond.value, hi
        case "<=":
            return cond.value + 1, hi
        case _:
            pass
    raise OracleCompileError([f"valid_random không hỗ trợ phép so sánh '{cond.op}'"])


def special_values(lo: int, hi: int, exclude: frozenset[int]) -> tuple[int, ...]:
    """Đầu mút và biên nhị phân trong [lo, hi], bỏ các giá trị bị loại. Tất định, không phụ thuộc seed."""
    found = {lo, lo + 1, hi - 1, hi}
    for m in POWER_EXPONENTS:
        found |= {2**m - 1, 2**m}
    return tuple(sorted(v for v in found if lo <= v <= hi and v not in exclude))


def compile_oracle(rbs: RBS, vocab: Vocabulary) -> CompiledOracle:
    errors = check(rbs, vocab)
    if errors:
        raise OracleCompileError(errors)

    variants: list[ConcreteVariant] = []
    cond = rbs.where
    fixed: set[int] = set()
    if cond is not None and isinstance(cond.value, int):
        control = _control_value(cond.op, cond.value)
        if control is not None:
            fixed.add(control)
            variants.append(
                ConcreteVariant(
                    name=f"at_limit:{cond.field}={control}",
                    variant_class="control",
                    field=cond.field,
                    value=control,
                    side="valid",
                )
            )

    for spec in rbs.variants:
        dom = vocab.field_domains.get(spec.field)
        match spec.kind:
            case "boundary":
                if isinstance(spec.value, int):
                    fixed.add(spec.value)
                variants.append(
                    ConcreteVariant(
                        name=f"boundary:{spec.field}={spec.value}",
                        variant_class="required",
                        field=spec.field,
                        value=spec.value,
                    )
                )
            case "max" | "min":
                if dom is None:
                    raise OracleCompileError([f"{spec.kind}({spec.field}) cần miền giá trị trong adapter"])
                value = dom.max if spec.kind == "max" else dom.min
                fixed.add(value)
                variants.append(
                    ConcreteVariant(
                        name=f"{spec.kind}:{spec.field}={value}",
                        variant_class="required",
                        field=spec.field,
                        value=value,
                    )
                )
            case "random" | "valid_random" | "probe":
                if dom is None:
                    raise OracleCompileError([f"{spec.kind}({spec.field}) cần miền giá trị trong adapter"])

    # Các biến thể lấy mẫu cần biết giá trị cố định để không lặp lại và để loại giá trị kiểm thử chuẩn.
    for spec in rbs.variants:
        if spec.kind not in ("random", "valid_random", "probe"):
            continue
        dom = vocab.field_domains[spec.field]
        exclude = frozenset(fixed | set(dom.canonical))
        if spec.kind == "random":
            lo, hi = _trigger_range(cond, spec.field, dom.min, dom.max)
            variants.append(
                ConcreteVariant(
                    name=f"random:{spec.field}",
                    variant_class="random",
                    field=spec.field,
                    k=spec.k,
                    lo=lo,
                    hi=hi,
                    strategy="stratified" if spec.stratified else "uniform",
                    side="trigger",
                    special=special_values(lo, hi, exclude) if spec.stratified else (),
                    exclude=tuple(sorted(exclude)),
                )
            )
        elif spec.kind == "valid_random":
            assert cond is not None and isinstance(cond.value, int)  # đã kiểm ở vocabulary.check
            lo, hi = _valid_range(cond, dom.min, dom.max)
            variants.append(
                ConcreteVariant(
                    name=f"valid_random:{spec.field}",
                    variant_class="valid_random",
                    field=spec.field,
                    k=spec.k,
                    lo=lo,
                    hi=hi,
                    strategy="stratified",
                    side="valid",
                    special=special_values(lo, hi, exclude),
                    exclude=tuple(sorted(exclude)),
                )
            )
        else:
            variants.append(
                ConcreteVariant(
                    name=f"probe:{spec.field}",
                    variant_class="probe",
                    field=spec.field,
                    lo=dom.min,
                    hi=dom.max,
                    budget=spec.budget,
                    exclude=tuple(sorted(exclude)),
                )
            )

    return CompiledOracle(
        requirement_id=rbs.requirement_id,
        rbs_hash=content_hash(rbs.model_dump(mode="json")),
        rtype=rbs.rtype,
        trigger=rbs.trigger,
        where=cond,
        expect=rbs.expect,
        within_ms=rbs.within_ms,
        forbid=rbs.forbid,
        alternatives=rbs.accept_alternatives,
        variants=tuple(variants),
    )


def _pick(lo: int, hi: int, exclude: frozenset[int], *key: object) -> int:
    """Một giá trị tất định trong [lo, hi] không thuộc `exclude`; thử lại bằng hash vài lần rồi lấy giá trị hợp lệ đầu tiên."""
    for attempt in range(8):
        v = hash_randint(lo, hi, *key, attempt)
        if v not in exclude:
            return v
    return next((v for v in range(lo, hi + 1) if v not in exclude), lo)


def instantiate_samples(variant: ConcreteVariant, seed: int) -> list[tuple[str, int]]:
    """(hậu tố tên, giá trị) cho một biến thể lấy mẫu. Tất định theo (seed, tên biến thể); tái lập giữa mọi bản Python.

    - uniform: k giá trị đều trong [lo, hi];
    - stratified: [lo, hi] chia k tầng bằng nhau, mỗi tầng một giá trị (độ phủ theo bề rộng được bảo đảm),
      cộng các giá trị đặc biệt (đầu mút, biên nhị phân). Giá trị bị loại không bao giờ được chọn.
    """
    if variant.variant_class not in SAMPLED or variant.lo is None or variant.hi is None or not variant.k:
        raise ValueError(f"{variant.name} không phải biến thể lấy mẫu hợp lệ")
    lo, hi, k = variant.lo, variant.hi, variant.k
    exclude = frozenset(variant.exclude)
    out: list[tuple[str, int]] = []
    if variant.strategy == "uniform":
        for i in range(k):
            out.append((f"#{i}", _pick(lo, hi, exclude, "uniform", seed, variant.name, i)))
        return out
    span = hi - lo + 1
    for i in range(k):
        s_lo, s_hi = lo + i * span // k, lo + (i + 1) * span // k - 1
        if s_hi < s_lo:  # miền nhỏ hơn số tầng
            continue
        out.append((f"#{i}", _pick(s_lo, s_hi, exclude, "stratum", seed, variant.name, i)))
    out += [(f"@{v}", v) for v in variant.special]
    return out


def instantiate_random(variant: ConcreteVariant, seed: int) -> list[int]:
    """Tương thích ngược: chỉ các giá trị lấy mẫu (không gồm giá trị đặc biệt)."""
    return [v for suffix, v in instantiate_samples(variant, seed) if suffix.startswith("#")]

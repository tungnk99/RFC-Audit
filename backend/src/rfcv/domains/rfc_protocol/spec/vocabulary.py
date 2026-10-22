"""Từ vựng hành vi của adapter và kiểm tra RBS theo từ vựng (Oracle compiler, bước kiểm tra)."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rfcv.domains.rfc_protocol.spec.rbs import RBS, Call

_SIG = re.compile(r"^([a-z_][a-z0-9_]*)(?:\(([a-z0-9_, ]*)\))?$")


class FieldDomain(BaseModel):
    model_config = ConfigDict(frozen=True)

    min: int
    max: int
    # Giá trị mà bộ kiểm thử thông dụng hay dùng (ví dụ 16641, 65535). Mã nhận ra kiểm thử nhắm vào chúng, nên biến thể
    # lấy mẫu bị loại các giá trị này để không "mớm" cho mã gian lận (A7).
    canonical: tuple[int, ...] = ()


class ConsistencyRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    if_expect_contains: str
    then_type: Literal["A", "B", "C", "D"]


class Vocabulary(BaseModel):
    """events: chữ ký dạng "send_alert(code)"; tham số có trong enums phải lấy giá trị từ enum,
    tham số khác phải trùng đúng tên tham số (ví dụ receive(record))."""

    model_config = ConfigDict(frozen=True)

    events: tuple[str, ...]
    states: tuple[str, ...]
    enums: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    field_domains: dict[str, FieldDomain] = Field(default_factory=dict)
    consistency_rules: tuple[ConsistencyRule, ...] = ()

    def signatures(self) -> dict[str, list[tuple[str, ...]]]:
        """Tên sự kiện → các chữ ký (một tên có thể có nhiều chữ ký, ví dụ receive(record), receive(handshake_msg))."""
        out: dict[str, list[tuple[str, ...]]] = {}
        for ev in self.events:
            m = _SIG.match(ev.strip())
            if not m:
                raise ValueError(f"chữ ký sự kiện không hợp lệ: {ev}")
            params = tuple(p.strip() for p in (m.group(2) or "").split(",") if p.strip())
            out.setdefault(m.group(1), []).append(params)
        return out


def _match_signature(call: Call, params: tuple[str, ...], vocab: Vocabulary) -> list[str]:
    if len(call.args) != len(params):
        return [f"'{call}' cần {len(params)} tham số theo chữ ký {call.name}({', '.join(params)})"]
    errors: list[str] = []
    for param, arg in zip(params, call.args, strict=True):
        if param in vocab.enums:
            if arg not in vocab.enums[param]:
                errors.append(f"'{arg}' không thuộc miền '{param}' của adapter")
        elif arg != param:
            errors.append(f"tham số '{arg}' phải là '{param}'")
    return errors


def _check_call(call: Call, sigs: dict[str, list[tuple[str, ...]]], vocab: Vocabulary, where: str) -> list[str]:
    if call.name not in sigs:
        return [f"{where}: sự kiện '{call.name}' không có trong từ vựng adapter"]
    attempts = [_match_signature(call, params, vocab) for params in sigs[call.name]]
    if any(not errs for errs in attempts):
        return []
    return [f"{where}: {e}" for e in min(attempts, key=len)]


def _holds(op: str, value: int, threshold: int) -> bool:
    return {
        ">": value > threshold,
        ">=": value >= threshold,
        "<": value < threshold,
        "<=": value <= threshold,
        "==": value == threshold,
        "!=": value != threshold,
    }[op]


def check(rbs: RBS, vocab: Vocabulary) -> list[str]:
    """Trả danh sách lỗi; rỗng nghĩa là RBS chỉ dùng từ vựng adapter và nhất quán."""
    sigs = vocab.signatures()
    errors: list[str] = []
    if rbs.state not in vocab.states:
        errors.append(f"state: '{rbs.state}' không có trong từ vựng adapter")
    errors += _check_call(rbs.trigger, sigs, vocab, "trigger")
    for c in rbs.expect:
        errors += _check_call(c, sigs, vocab, "expect")
    for c in rbs.forbid:
        errors += _check_call(c, sigs, vocab, "forbid")
    for c in rbs.accept_alternatives:
        errors += _check_call(c, sigs, vocab, "accept_alternatives")

    fields = [v.field for v in rbs.variants] + ([rbs.where.field] if rbs.where else [])
    for f in fields:
        if vocab.field_domains and f not in vocab.field_domains:
            errors.append(f"field: '{f}' không có miền giá trị trong adapter")
    for v in rbs.variants:
        if v.kind == "boundary" and isinstance(v.value, int) and v.field in vocab.field_domains:
            dom = vocab.field_domains[v.field]
            if not dom.min <= v.value <= dom.max:
                errors.append(f"variant: {v.value} nằm ngoài miền [{dom.min}, {dom.max}] của {v.field}")
        cond = rbs.where
        if (
            v.kind == "boundary"
            and isinstance(v.value, int)
            and cond is not None
            and cond.field == v.field
            and isinstance(cond.value, int)
            and not _holds(cond.op, v.value, cond.value)
        ):
            errors.append(
                f"variant: boundary({v.field}, {v.value}) không thoả `where {cond.field} {cond.op} {cond.value}`; "
                "biến thể biên phải nằm phía kích hoạt (giá trị hợp lệ sát ngưỡng là ca đối chứng, oracle tự thêm)"
            )

    for v in rbs.variants:
        if v.kind in ("random", "valid_random") and (v.k is None or v.k < 1):
            errors.append(f"variant: {v.kind}({v.field}) cần k >= 1")
        if v.kind == "probe" and (v.budget is None or v.budget < 1):
            errors.append(f"variant: probe({v.field}) cần budget >= 1")
        if v.kind in ("valid_random", "probe"):
            cond = rbs.where
            if cond is None or cond.field != v.field or not isinstance(cond.value, int):
                errors.append(
                    f"variant: {v.kind}({v.field}) cần mệnh đề `where {v.field} <phép so sánh> <số>` để biết phía hợp lệ"
                )

    expect_names = {c.name for c in rbs.expect}
    for rule in vocab.consistency_rules:
        if rule.if_expect_contains in expect_names and rbs.rtype != rule.then_type:
            errors.append(
                f"type: expect chứa {rule.if_expect_contains} nên phải là loại {rule.then_type}, không phải {rbs.rtype}"
            )
    if not rbs.variants:
        errors.append("variants: cần ít nhất một biến thể")
    return errors

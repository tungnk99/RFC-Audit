"""Phân tích RBS thành mô hình có kiểu. Văn bản RBS do RFC Analyst đề xuất (RbsProposal@1)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal, cast

from lark import Lark, Token, Transformer, v_args  # pyright: ignore[reportUnknownVariableType]
from lark.exceptions import LarkError
from pydantic import BaseModel, ConfigDict

_GRAMMAR = Path(__file__).with_name("rbs_grammar.lark")


class Call(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    args: tuple[str, ...] = ()

    def __str__(self) -> str:
        return f"{self.name}({', '.join(self.args)})" if self.args else self.name


class Condition(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str
    op: Literal[">", ">=", "<", "<=", "==", "!="]
    value: int | str


class VariantSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["boundary", "max", "min", "random", "valid_random", "probe"]
    field: str
    value: int | str | None = None
    k: int | None = None
    stratified: bool = False  # random: phân tầng đều thay vì ngẫu nhiên thuần
    budget: int | None = None  # probe: số lần dò tối đa


class RBS(BaseModel):
    model_config = ConfigDict(frozen=True)

    requirement_id: str
    sentence_id: str
    modal: str
    rtype: Literal["A", "B", "C", "D"]
    actor: str
    state: str
    trigger: Call
    where: Condition | None = None
    expect: tuple[Call, ...]
    within_ms: int | None = None
    forbid: tuple[Call, ...] = ()
    accept_alternatives: tuple[Call, ...] = ()
    variants: tuple[VariantSpec, ...]


@dataclass(frozen=True)
class _Within:
    ms: int


@dataclass(frozen=True)
class _Forbid:
    calls: tuple[Call, ...]


@dataclass(frozen=True)
class _Alternatives:
    calls: tuple[Call, ...]


class RbsSyntaxError(ValueError):
    pass


def _value(tok: Token) -> int | str:
    return int(tok) if tok.type == "INT" else str(tok)


@v_args(inline=True)
class _ToModel(Transformer[Token, RBS]):
    def start(self, req: RBS) -> RBS:
        return req

    def call(self, name: Token, *args: Token | None) -> Call:
        return Call(name=str(name), args=tuple(str(a) for a in args if a is not None))

    def value(self, tok: Token) -> int | str:
        return _value(tok)

    def where(self, field: Token, op: Token, value: int | str) -> Condition:
        return Condition(field=str(field), op=str(op), value=value)  # type: ignore[arg-type]

    def within(self, n: Token) -> _Within:
        return _Within(int(n))

    def forbid(self, *calls: Call) -> _Forbid:
        return _Forbid(calls)

    def alternatives(self, *calls: Call) -> _Alternatives:
        return _Alternatives(calls)

    def v_boundary(self, field: Token, value: int | str) -> VariantSpec:
        return VariantSpec(kind="boundary", field=str(field), value=value)

    def v_max(self, field: Token) -> VariantSpec:
        return VariantSpec(kind="max", field=str(field))

    def v_min(self, field: Token) -> VariantSpec:
        return VariantSpec(kind="min", field=str(field))

    def v_random(self, field: Token, k: Token) -> VariantSpec:
        return VariantSpec(kind="random", field=str(field), k=int(k))

    def v_random_stratified(self, field: Token, k: Token) -> VariantSpec:
        return VariantSpec(kind="random", field=str(field), k=int(k), stratified=True)

    def v_valid_random(self, field: Token, k: Token) -> VariantSpec:
        return VariantSpec(kind="valid_random", field=str(field), k=int(k), stratified=True)

    def v_probe(self, field: Token, budget: Token) -> VariantSpec:
        return VariantSpec(kind="probe", field=str(field), budget=int(budget))

    def requirement(self, *items: object) -> RBS:
        req_id, sentence, modal, rtype, actor, state, trigger, *rest = items
        where: Condition | None = None
        expect: list[Call] = []
        within: int | None = None
        forbid: tuple[Call, ...] = ()
        alternatives: tuple[Call, ...] = ()
        variants: list[VariantSpec] = []
        for item in rest:
            match item:
                case Condition():
                    where = item
                case Call():
                    expect.append(item)
                case _Within():
                    within = item.ms
                case _Forbid():
                    forbid = item.calls
                case _Alternatives():
                    alternatives = item.calls
                case VariantSpec():
                    variants.append(item)
                case _:
                    raise RbsSyntaxError(f"phần tử không mong đợi: {item!r}")
        return RBS(
            requirement_id=str(req_id),
            sentence_id=str(sentence),
            modal=str(modal),
            rtype=str(rtype),  # type: ignore[arg-type]
            actor=str(actor),
            state=str(state),
            trigger=trigger,  # type: ignore[arg-type]
            where=where,
            expect=tuple(expect),
            within_ms=within,
            forbid=forbid,
            accept_alternatives=alternatives,
            variants=tuple(variants),
        )


@cache
def _parser() -> Lark:
    return Lark(_GRAMMAR.read_text(encoding="utf-8"), parser="lalr", maybe_placeholders=False)


def parse_rbs(text: str) -> RBS:
    try:
        tree = _parser().parse(text)
    except LarkError as exc:
        raise RbsSyntaxError(str(exc)) from exc
    return cast(RBS, _ToModel().transform(tree))

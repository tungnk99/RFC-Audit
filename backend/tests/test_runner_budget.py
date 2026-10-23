"""Lược lịch sử, nhắc ngân sách token và cứu đầu ra một phần của runtime agent (đo trên wolfSSL: Code Reader cạn 400k token)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from pydantic import BaseModel
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart

from rfcv.runtime.pydantic_ai.runner import KEEP_TOOL_RESULTS, salvage, thin_history


class Claim(BaseModel):
    file: str
    line: int


def _returns(n: int, size: int = 2000) -> list[ModelMessage]:
    return [
        ModelRequest(parts=[ToolReturnPart(tool_name="t", content="x" * size, tool_call_id=str(i))]) for i in range(n)
    ]


def _ctx(used: int, limit: int) -> Any:
    return SimpleNamespace(deps=SimpleNamespace(max_tokens=limit), usage=SimpleNamespace(total_tokens=used))


def _text(m: ModelMessage) -> str:
    return str(cast("ToolReturnPart", cast("ModelRequest", m).parts[0]).content)


def test_old_tool_results_are_thinned_and_recent_ones_kept() -> None:
    out = thin_history(_ctx(0, 0), _returns(KEEP_TOOL_RESULTS + 3))
    assert all(_text(m).startswith("[đã lược 2000") for m in out[:3])
    assert all(len(_text(m)) == 2000 for m in out[3:])
    assert thin_history(_ctx(0, 0), out) == out  # chạy lại không lược chồng


def test_short_results_are_left_alone() -> None:
    out = thin_history(_ctx(0, 0), _returns(KEEP_TOOL_RESULTS + 2, size=100))
    assert all(len(_text(m)) == 100 for m in out)


def test_wrap_up_note_appears_once_over_the_share() -> None:
    msgs = _returns(2)
    assert len(cast("ModelRequest", thin_history(_ctx(100, 1000), msgs)[-1]).parts) == 1
    once = thin_history(_ctx(800, 1000), msgs)
    twice = thin_history(_ctx(900, 1000), once)
    assert len(cast("ModelRequest", twice[-1]).parts) == 2


def test_salvage_returns_last_valid_proposed_output() -> None:
    bad = ModelResponse(parts=[ToolCallPart("final_result", {"file": "a.c"})])
    good = ModelResponse(parts=[ToolCallPart("final_result", {"file": "src/internal.c", "line": 12402})])
    noise = ModelResponse(parts=[TextPart("hết ngân sách")])
    got = salvage([bad, good, noise], Claim)
    assert got == Claim(file="src/internal.c", line=12402)
    assert salvage([bad, noise], Claim) is None


def test_read_and_eval_results_are_kept_longer_than_search_results() -> None:
    from pydantic_ai.messages import ToolReturnPart as TRP

    def req(name: str, i: int) -> ModelMessage:
        return ModelRequest(parts=[TRP(tool_name=name, content="x" * 2000, tool_call_id=str(i))])

    msgs = [
        req("code__read", 0),
        req("code__grep", 1),
        *[req("code__grep", i) for i in range(2, 2 + KEEP_TOOL_RESULTS)],
    ]
    out = thin_history(_ctx(0, 0), msgs)
    assert len(_text(out[0])) == 2000  # đọc cũ còn nguyên
    assert _text(out[1]).startswith("[đã lược")  # tìm kiếm cũ bị lược

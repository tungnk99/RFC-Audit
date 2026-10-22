"""Biến sự kiện trace thành dạng giao diện hiển thị được: bản gọn cho luồng trực tiếp, và hội thoại LLM đã chuẩn hoá.

Trace giữ nguyên toàn văn (kể cả hội thoại mô hình, rất dài); giao diện chỉ kéo phần đó khi người dùng mở một sự kiện.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from typing import Any, cast

from rfcv.core.trace import describe

MAX_TEXT = 24_000
BULKY = ("llm_run", "llm_failure")


def _clip(value: Any, limit: int = MAX_TEXT) -> tuple[str, bool]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=1, default=str)
    return (text[:limit], True) if len(text) > limit else (text, False)


def slim_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Sự kiện gọn cho luồng: bỏ hội thoại mô hình, cắt đầu ra công cụ. Kèm một dòng mô tả sẵn."""
    out = dict(event)
    payload = dict(cast("Mapping[str, Any]", event.get("payload") or {}))
    if event["kind"] in BULKY:
        messages = cast("list[Any]", payload.pop("messages", None) or [])
        payload["n_messages"] = len(messages)
        payload["has_transcript"] = bool(messages)
    if event["kind"] == "tool_call" and isinstance(payload.get("output"), str):
        payload["output"], cut = _clip(payload["output"], 800)
        payload["output_truncated"] = cut
    out["payload"] = payload
    out["summary"] = describe(event)
    return out


def _parse_args(args: Any) -> Any:
    if isinstance(args, str):
        try:
            return json.loads(args)
        except ValueError:
            return args
    return args


def _part_steps(part: Mapping[str, Any]) -> list[dict[str, Any]]:
    kind = str(part.get("part_kind"))
    content = part.get("content")
    if kind == "system-prompt":
        text, cut = _clip(content)
        return [{"type": "system", "text": text, "truncated": cut}]
    if kind == "user-prompt":
        text, cut = _clip(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str))
        return [{"type": "input", "text": text, "truncated": cut}]
    if kind == "tool-return":
        text, cut = _clip(content)
        return [
            {
                "type": "tool_return",
                "tool": part.get("tool_name"),
                "call_id": part.get("tool_call_id"),
                "text": text,
                "truncated": cut,
            }
        ]
    if kind == "retry-prompt":
        text, cut = _clip(content)
        return [{"type": "retry", "tool": part.get("tool_name"), "text": text, "truncated": cut}]
    if kind == "text":
        text, cut = _clip(content)
        return [{"type": "assistant", "text": text, "truncated": cut}]
    if kind == "thinking":
        text, cut = _clip(content)
        return [{"type": "thinking", "text": text, "truncated": cut}]
    if kind == "tool-call":
        return [
            {
                "type": "tool_call",
                "tool": part.get("tool_name"),
                "call_id": part.get("tool_call_id"),
                "args": _parse_args(part.get("args")),
            }
        ]
    return []  # instruction-baseline và loại khác không mang thông tin cho người đọc


def transcript(messages: list[Any]) -> dict[str, Any]:
    """Hội thoại giữa harness và một mô hình, theo thứ tự: lời nhắc hệ thống, đầu vào, lời gọi công cụ, kết quả, đầu ra."""
    steps: list[dict[str, Any]] = []
    for i, msg in enumerate(messages):
        if not isinstance(msg, Mapping):
            continue
        m = cast("Mapping[str, Any]", msg)
        if m.get("instructions"):
            text, cut = _clip(m["instructions"])
            steps.append({"type": "instructions", "text": text, "truncated": cut, "turn": i})
        for part in cast("list[Any]", m.get("parts") or []):
            if isinstance(part, Mapping):
                for s in _part_steps(cast("Mapping[str, Any]", part)):
                    steps.append({**s, "turn": i})
    calls = [s for s in steps if s["type"] == "tool_call"]
    final = next((s for s in reversed(calls) if str(s["tool"]).startswith("final_result")), None)
    if final is not None:
        output: Any = final["args"]
    else:
        texts = [s["text"] for s in steps if s["type"] == "assistant"]
        output = texts[-1] if texts else None
    used = Counter(str(s["tool"]) for s in calls if not str(s["tool"]).startswith("final_result"))
    return {"steps": steps, "output": output, "tools_used": dict(used)}


def full_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Toàn văn một sự kiện; với lần chạy LLM thì thêm hội thoại đã chuẩn hoá."""
    out = dict(event)
    payload = dict(cast("Mapping[str, Any]", event.get("payload") or {}))
    out["summary"] = describe(event)
    if event["kind"] in BULKY:
        out["transcript"] = transcript(cast("list[Any]", payload.pop("messages", None) or []))
    out["payload"] = payload
    return out

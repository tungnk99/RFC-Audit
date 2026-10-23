"""Dựng kịch bản kiểm thử TẤT ĐỊNH từ mẫu của adapter, khi hình dạng RBS khớp mẫu.

Tester (LLM) tốn khoảng 41k token mỗi yêu cầu để viết lại đúng một kịch bản mà adapter đã có sẵn (handshake, gửi bản ghi dài, chờ cảnh
báo). Mẫu `*.yaml` của adapter có khối `steps` (DSL, qua được `rfcv adapter check`) cùng khối `match` khai báo hình dạng RBS mà nó phục
vụ; khớp thì hub dùng thẳng, không khớp thì Tester LLM chạy như cũ. Từ RBS chỉ lấy hai thứ mẫu không biết trước: phản ứng đòi hỏi
(`until` của bước `expect`) và thời hạn (`within_ms`).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, cast

import yaml

from rfcv.domains.rfc_protocol.schemas import ScenarioProposal
from rfcv.domains.rfc_protocol.spec.rbs import RBS


def _shape_matches(match: dict[str, Any], rbs: RBS) -> bool:
    """`match`: requirement_types, trigger (tên sự kiện), trigger_arg (đối số đầu của sự kiện), expect (tên lời gọi đầu), field_prefix (tiền tố trường `where`)."""
    if rbs.where is None or not rbs.expect:
        return False  # kịch bản dựng theo trường của `where` và phản ứng đầu của `expect`
    if (types := match.get("requirement_types")) and rbs.rtype not in types:
        return False
    if (trigger := match.get("trigger")) and rbs.trigger.name != trigger:
        return False
    if (arg := match.get("trigger_arg")) and (not rbs.trigger.args or rbs.trigger.args[0] != arg):
        return False
    if (expect := match.get("expect")) and rbs.expect[0].name != expect:
        return False
    return not ((prefix := match.get("field_prefix")) and not rbs.where.field.startswith(prefix))


def synthesize(rbs: RBS, templates_dir: Path | None) -> ScenarioProposal | None:
    """Kịch bản dựng từ mẫu khớp RBS, hoặc None để Tester LLM làm."""
    if templates_dir is None or not templates_dir.is_dir():
        return None
    for path in sorted(templates_dir.glob("*.yaml")):
        data = cast("dict[str, Any]", yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        steps, match = data.get("steps"), data.get("match")
        if not steps or not isinstance(match, dict) or not _shape_matches(cast("dict[str, Any]", match), rbs):
            continue
        assert rbs.where is not None
        steps = copy.deepcopy(steps)
        for step in cast("list[dict[str, Any]]", steps):
            if step.get("op") == "expect":
                args = step.setdefault("args", {})
                args["until"] = str(rbs.expect[0])
                if rbs.within_ms:
                    args["within_ms"] = rbs.within_ms
        return ScenarioProposal.model_validate(
            {
                "requirement_id": rbs.requirement_id,
                "reach_state": rbs.state,
                "steps": steps,
                "bindings": data.get("bindings") or {rbs.where.field: "from_variant"},
                "example_id": data.get("id"),
            }
        )
    return None

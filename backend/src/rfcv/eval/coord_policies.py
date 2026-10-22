"""Chính sách Planner của bộ mô phỏng phối hợp. Mọi chính sách chỉ đọc NGỮ CẢNH THẬT mà Context builder đã lọc (IFC còn hiệu lực).

Chỉ ORACLE-FULL và ORACLE-OBS-codes được dùng kênh quan sát riêng của mô phỏng (`WorldView`); các chính sách còn lại không.
Hiệu số giữa chúng là cận trên lợi ích của thông tin phong phú hơn, cho BẤT KỲ Planner nào, không phụ thuộc Planner đó giỏi cỡ nào.

| Chính sách        | Thấy gì                                  | Cách làm                                               |
|-------------------|------------------------------------------|--------------------------------------------------------|
| ORACLE-FULL       | ngữ cảnh + hồ sơ lỗi của worker          | sổ tay, tham số đúng ngay từ đầu                       |
| ORACLE-OBS-codes  | ngữ cảnh + mã lỗi cổng lần gần nhất      | sổ tay, sửa tham số theo mã lỗi                        |
| ORACLE-OBS-bool   | chỉ ngữ cảnh (đúng như Planner thật)     | sổ tay, đổi tham số mò khi giao lại LOCATE             |
| PLAYBOOK          | chỉ ngữ cảnh                             | sổ tay thuần, không đổi tham số                        |
| RANDOM-VALID      | chỉ ngữ cảnh                             | nhiệm vụ hợp lệ ngẫu nhiên, dừng với xác suất 0,1      |
| REPEATER          | không gì                                 | lặp LOCATE, đổi `target_symbol` để né bộ phát hiện lặp |
| PREMATURE         | không gì                                 | dừng ngay                                              |
| CRITIQUE-IGNORER  | chỉ ngữ cảnh                             | sổ tay nhưng không bao giờ gọi CRITIQUE                |
| FAILING(q, base)  | như base                                 | không trả kế hoạch với xác suất q                      |
| NOISY(e, base)    | như base                                 | với xác suất e làm như RANDOM-VALID                    |
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, cast

from rfcv.common.prng import hash_randint
from rfcv.core.advisor import advise, situation_from_context
from rfcv.eval.coord_world import SYMBOL, Plan, Policy, WorldView
from rfcv.plugins import current_registry

HANDLED = frozenset({"LOCATE", "TRACE_PATHS", "RECHECK", "SELECT_TESTS", "CRITIQUE"})
STOP: Plan = ("stop", [], "INFEASIBLE")


def _task(task_type: str, **params: Any) -> dict[str, Any]:
    return {"task_type": task_type, "target_role": current_registry().tasks[task_type].target_role, "params": params}


def _advice(ctx: Mapping[str, Any]) -> tuple[Plan | None, list[dict[str, Any]]]:
    reg = current_registry()
    a = advise(situation_from_context(ctx), reg.playbook, reg.tasks, HANDLED)
    if a is None:
        return None, []
    if a.stop:
        return ("stop", [], a.rationale_code), []
    tasks = [t.model_dump(mode="json", exclude_defaults=True) for t in a.tasks]
    return ("dispatch", tasks, a.rationale_code), tasks


def _locate_attempts(ctx: Mapping[str, Any]) -> int:
    item = cast("dict[str, Any]", ctx.get("tasks.history") or {})
    rows = cast("list[dict[str, Any]]", item.get("value") or [])
    return sum(1 for h in rows if h["task_type"] == "LOCATE")


class Playbook:
    name = "PLAYBOOK"

    def plan(self, ctx: Mapping[str, Any], view: WorldView) -> Plan | None:
        plan, _ = _advice(ctx)
        return plan or STOP

    def _patch(self, plan: Plan, edit: Callable[[dict[str, Any]], None]) -> Plan:
        action, tasks, rationale = plan
        edited = [dict(t) for t in tasks]
        for t in edited:
            params: dict[str, Any] = dict(t.get("params") or {})
            if t["task_type"] == "LOCATE":
                edit(params)
            t["params"] = params
        return action, edited, rationale


class ObsBool(Playbook):
    """Đúng như Planner thật khi chỉ có `ok`: giao lại LOCATE thì đổi tham số mò, lần lượt các biến thể."""

    name = "ORACLE-OBS-bool"

    def plan(self, ctx: Mapping[str, Any], view: WorldView) -> Plan | None:
        plan, _ = _advice(ctx)
        if plan is None:
            return STOP
        attempt = _locate_attempts(ctx)

        def edit(params: dict[str, Any]) -> None:
            if attempt % 3 == 1:
                params["start_hints"] = "locator"
            elif attempt % 3 == 2:
                params["target_symbol"] = SYMBOL

        return self._patch(plan, edit)


class ObsCodes(Playbook):
    name = "ORACLE-OBS-codes"

    def plan(self, ctx: Mapping[str, Any], view: WorldView) -> Plan | None:
        plan, _ = _advice(ctx)
        if plan is None:
            return STOP
        errors = view.gate_errors("LOCATE")

        def edit(params: dict[str, Any]) -> None:
            if "SYMBOL_NOT_IN_INDEX" in errors:
                params["target_symbol"] = SYMBOL

        return self._patch(plan, edit)


class OracleFull(Playbook):
    name = "ORACLE-FULL"

    def plan(self, ctx: Mapping[str, Any], view: WorldView) -> Plan | None:
        plan, _ = _advice(ctx)
        if plan is None:
            return STOP
        broken = view.profile.wrong_symbol or view.profile.wrong_location

        def edit(params: dict[str, Any]) -> None:
            if broken:
                params["start_hints"] = "locator"

        return self._patch(plan, edit)


class CritiqueIgnorer(Playbook):
    name = "CRITIQUE-IGNORER"

    def plan(self, ctx: Mapping[str, Any], view: WorldView) -> Plan | None:
        plan, _ = _advice(ctx)
        if plan is None:
            return STOP
        _action, tasks, rationale = plan
        kept = [t for t in tasks if t["task_type"] != "CRITIQUE"]
        return ("dispatch", kept, rationale) if kept else STOP


class RandomValid:
    name = "RANDOM-VALID"

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.n = 0

    def plan(self, ctx: Mapping[str, Any], view: WorldView) -> Plan | None:
        self.n += 1
        if hash_randint(0, 9, "rv-stop", self.seed, self.n) == 0:
            return STOP
        names = sorted(HANDLED)
        k = 1 + hash_randint(0, 1, "rv-k", self.seed, self.n)
        picked = [names[hash_randint(0, len(names) - 1, "rv-pick", self.seed, self.n, i)] for i in range(k)]
        tasks = [_task(t) for t in dict.fromkeys(picked)]
        return "dispatch", tasks, "FILL_MISSING_VARIANT"


class Repeater:
    name = "REPEATER"

    def __init__(self) -> None:
        self.n = 0

    def plan(self, ctx: Mapping[str, Any], view: WorldView) -> Plan | None:
        self.n += 1
        return "dispatch", [_task("LOCATE", target_symbol=f"f{self.n}")], "FILL_MISSING_VARIANT"


class Premature:
    name = "PREMATURE"

    def plan(self, ctx: Mapping[str, Any], view: WorldView) -> Plan | None:
        return STOP


class Failing:
    def __init__(self, q: float, base: Policy, seed: int) -> None:
        self.q, self.base, self.seed, self.n = q, base, seed, 0
        self.name = f"FAILING({q})/{base.name}"

    def plan(self, ctx: Mapping[str, Any], view: WorldView) -> Plan | None:
        self.n += 1
        if hash_randint(0, 999, "fail", self.seed, self.n) < int(self.q * 1000):
            return None
        return self.base.plan(ctx, view)


class Noisy:
    def __init__(self, eps: float, base: Policy, seed: int) -> None:
        self.eps, self.base, self.seed, self.n = eps, base, seed, 0
        self.noise = RandomValid(seed)
        self.name = f"NOISY({eps})/{base.name}"

    def plan(self, ctx: Mapping[str, Any], view: WorldView) -> Plan | None:
        self.n += 1
        if hash_randint(0, 999, "noisy", self.seed, self.n) < int(self.eps * 1000):
            return self.noise.plan(ctx, view)
        return self.base.plan(ctx, view)


POLICIES: dict[str, Callable[[int], Policy]] = {
    "ORACLE-FULL": lambda s: OracleFull(),
    "ORACLE-OBS-codes": lambda s: ObsCodes(),
    "ORACLE-OBS-bool": lambda s: ObsBool(),
    "PLAYBOOK": lambda s: Playbook(),
    "RANDOM-VALID": lambda s: RandomValid(s),
    "REPEATER": lambda s: Repeater(),
    "PREMATURE": lambda s: Premature(),
    "CRITIQUE-IGNORER": lambda s: CritiqueIgnorer(),
}


class WithFallback:
    """Dự phòng tất định: khi chính sách chính không đưa ra được kế hoạch thì dùng sổ tay thuần."""

    def __init__(self, base: Policy) -> None:
        self.base = base
        self.fallback = Playbook()
        self.name = f"FALLBACK/{base.name}"

    def plan(self, ctx: Mapping[str, Any], view: WorldView) -> Plan | None:
        return self.base.plan(ctx, view) or self.fallback.plan(ctx, view)


def make_policy(spec: str, seed: int) -> Policy:
    """Dựng chính sách từ chuỗi đặc tả: `TÊN`, `FAILING:q:cơ sở` hoặc `FALLBACK:cơ sở`."""
    if spec in POLICIES:
        return POLICIES[spec](seed)
    kind, _, rest = spec.partition(":")
    if kind == "FAILING":
        q, _, base = rest.partition(":")
        return Failing(float(q), make_policy(base, seed), seed)
    if kind == "FALLBACK":
        return WithFallback(make_policy(rest, seed))
    raise KeyError(f"chính sách lạ: {spec}")

"""Bộ gợi ý (advisor): biến sổ tay điều tra dạng dữ liệu thành gợi ý nhiệm vụ tiếp theo. Hàm thuần, không LLM, không I/O.

Đầu vào là chính ngữ cảnh mà Planner nhìn thấy (sau Context builder), nên tình huống mà advisor suy ra không chứa gì
Planner không thấy. Nhờ vậy mọi so sánh "Planner đi theo hay chệch sổ tay" công bằng, và advisor không mở thêm kênh
văn bản tự do nào vào agent đặc quyền: mọi trường của `Situation` là mã hữu hạn hoặc tên biến thể từ oracle đáng tin.

Advisor không quyết định gì thay Verdict engine hay Planner: nó chỉ trả lời "theo kinh nghiệm thì bước tiếp theo là gì".
"""

from __future__ import annotations

import dataclasses
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from rfcv.agents.schemas import TaskSpec
from rfcv.common.hashing import content_hash
from rfcv.spi import BIND_SOURCES, PlaybookRule, Suggest, TaskDefinition, When

MAX_TASKS = 2  # cùng giới hạn của PlanAction


@dataclass(frozen=True)
class Situation:
    """Tình huống điều tra, suy ra từ ngữ cảnh Planner. Mọi trường có miền hữu hạn."""

    rtype: str
    provisional: str  # "NONE" hoặc tên nhãn tạm
    needs: frozenset[str]
    missing: tuple[tuple[str, str | None], ...]  # (tầng, biến thể hoặc mục) theo báo cáo độ đủ
    conflicts: tuple[tuple[str, str | None], ...]  # (loại, khía cạnh)
    critique: str  # "none" | "clean" | "issues"
    critique_kinds: tuple[str, ...]
    critique_evidence: tuple[str, ...]
    dispatched: frozenset[str]
    rounds: int

    @property
    def has_missing(self) -> bool:
        return bool(self.needs)

    def signature(self) -> str:
        """Chữ ký ngắn của tình huống, để gom các lần gặp cùng loại tình huống (khai thác kinh nghiệm về sau)."""
        conflicts = ",".join(sorted(f"{k}@{a}" if a else k for k, a in self.conflicts)) or "-"
        kinds = ",".join(sorted(set(self.critique_kinds))) or "-"
        needs = ",".join(sorted(self.needs)) or "-"
        return f"{self.rtype}|{self.provisional}|need:{needs}|conf:{conflicts}|crit:{self.critique}:{kinds}"


@dataclass(frozen=True)
class Advice:
    rule_id: str
    stop: bool
    tasks: tuple[TaskSpec, ...]
    rationale_code: str
    signature: str


def _value(context: Mapping[str, Any], name: str) -> Any:
    item = context.get(name)
    return cast("Mapping[str, Any]", item).get("value") if isinstance(item, Mapping) else None


def _obj(context: Mapping[str, Any], name: str) -> dict[str, Any]:
    value = _value(context, name)
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [cast("dict[str, Any]", r) for r in cast("list[Any]", value or []) if isinstance(r, dict)]


def situation_from_context(context: Mapping[str, Any]) -> Situation:
    """Dựng tình huống từ ngữ cảnh đã qua Context builder (mỗi trường là {"label", "value"})."""
    report = _obj(context, "verdict.sufficiency")
    provisional = report.get("provisional")
    missing = _rows(report.get("missing"))
    conflicts = _rows(report.get("conflicts"))
    has_critique = isinstance(_value(context, "critique.latest"), dict)
    issues = _rows(_obj(context, "critique.latest").get("issues"))
    history = _rows(_value(context, "tasks.history"))
    return Situation(
        rtype=str(_value(context, "requirement.rtype") or ""),
        provisional=str(cast("dict[str, Any]", provisional)["label"]) if isinstance(provisional, dict) else "NONE",
        needs=frozenset(str(m["need"]) for m in missing),
        missing=tuple((str(m["need"]), str(m["variant"]) if m.get("variant") else None) for m in missing),
        conflicts=tuple((str(c["kind"]), c.get("aspect")) for c in conflicts),
        critique="none" if not has_critique else ("issues" if issues else "clean"),
        critique_kinds=tuple(str(i["kind"]) for i in issues),
        critique_evidence=tuple(str(i["evidence_id"]) for i in issues if i.get("evidence_id")),
        dispatched=frozenset(str(h["task_type"]) for h in history),
        rounds=len({int(h["round"]) for h in history}),
    )


def matches(when: When, sit: Situation) -> bool:
    checks = (
        not when.rtypes or sit.rtype in when.rtypes,
        not when.provisional or sit.provisional in when.provisional,
        when.need is None or when.need in sit.needs,
        when.missing is None or when.missing == sit.has_missing,
        when.conflict is None or when.conflict == bool(sit.conflicts),
        when.critique is None or when.critique == sit.critique,
        when.critique_kind is None or when.critique_kind in sit.critique_kinds,
        when.first_round is None or when.first_round == (sit.rounds == 0),
        not (when.not_dispatched & sit.dispatched),
    )
    return all(checks)


def _resolve(source: str, sit: Situation, need: str | None) -> Any:
    """Giá trị của một nguồn gắn tham số. `need` (của điều kiện quy tắc) thu hẹp các mục thiếu được xét."""
    variants = [v for n, v in sit.missing if v and (need is None or n == need)]
    match source:
        case "missing.variants":
            return variants or None
        case "missing.first_variant":
            return variants[0] if variants else None
        case "conflict.aspect":
            return next((a for _, a in sit.conflicts if a), None)
        case "critique.evidence_id":
            return sit.critique_evidence[0] if sit.critique_evidence else None
        case _:
            pass
    raise ValueError(f"nguồn gắn tham số lạ: {source}")  # freeze() đã chặn; đến đây là lỗi lập trình


def build_task(suggest: Suggest, sit: Situation, definition: TaskDefinition, need: str | None = None) -> TaskSpec | None:
    """Dựng nhiệm vụ từ gợi ý; None nếu thiếu dữ liệu để gắn tham số hoặc tham số không hợp lệ."""
    params: dict[str, Any] = dict(suggest.params)
    for name, source in suggest.bind.items():
        value = _resolve(source, sit, need)
        if value is None:
            return None
        params[name] = value
    try:
        model: BaseModel = definition.params_model.model_validate(params)
    except ValidationError:
        return None
    return TaskSpec(task_type=suggest.task_type, target_role=definition.target_role, params=model)


def advise(
    sit: Situation,
    playbook: Sequence[PlaybookRule],
    tasks: Mapping[str, TaskDefinition],
    handled: Collection[str],
) -> Advice | None:
    """Quy tắc đầu tiên (theo ưu tiên) khớp và còn gợi ý được thì thắng. Không bao giờ gợi ý nhiệm vụ chưa có handler."""
    for rule in sorted(playbook, key=lambda r: (r.priority, r.id)):
        if not matches(rule.when, sit):
            continue
        if rule.stop:
            return Advice(rule.id, True, (), rule.rationale_code, sit.signature())
        built: list[TaskSpec] = []
        for s in rule.suggest:
            definition = tasks.get(s.task_type)
            if definition is None or s.task_type not in handled:
                continue
            task = build_task(s, sit, definition, rule.when.need)
            if task is not None:
                built.append(task)
        if built:
            return Advice(rule.id, False, tuple(built[:MAX_TASKS]), rule.rationale_code, sit.signature())
    return None


def adherence(advice: Advice | None, action: str, planned: Sequence[TaskSpec], rationale: str, deviation_code: str) -> str:
    """So kế hoạch của Planner với lời khuyên: no_advice | followed | deviated_declared | deviated_unannounced."""
    if advice is None:
        return "no_advice"
    same_stop = advice.stop and action == "stop"
    same_tasks = not advice.stop and action == "dispatch" and {t.task_type for t in planned} == {
        t.task_type for t in advice.tasks
    }
    if same_stop or same_tasks:
        return "followed"
    return "deviated_declared" if rationale == deviation_code else "deviated_unannounced"


def validate_playbook(
    rules: Sequence[PlaybookRule],
    tasks: Mapping[str, TaskDefinition],
    rationale_codes: Collection[str],
    labels: Collection[str],
) -> list[str]:
    """Lỗi của sổ tay lúc đóng băng registry (để sổ tay sai không lọt tới lúc chạy)."""
    errors: list[str] = []
    seen: set[str] = set()
    for r in rules:
        if r.id in seen:
            errors.append(f"{r.id}: trùng mã quy tắc")
        seen.add(r.id)
        if r.rationale_code not in rationale_codes:
            errors.append(f"{r.id}: mã lý do '{r.rationale_code}' chưa đăng ký")
        if r.stop == bool(r.suggest):
            errors.append(f"{r.id}: phải hoặc dừng hoặc có gợi ý nhiệm vụ, không cả hai, không trống")
        for lab in r.when.provisional:
            if lab != "NONE" and lab not in labels:
                errors.append(f"{r.id}: nhãn tạm '{lab}' không tồn tại")
        if r.when.critique not in (None, "none", "clean", "issues"):
            errors.append(f"{r.id}: critique phải là none|clean|issues")
        for s in r.suggest:
            definition = tasks.get(s.task_type)
            if definition is None:
                errors.append(f"{r.id}: nhiệm vụ '{s.task_type}' chưa đăng ký")
                continue
            for name, source in s.bind.items():
                if source not in BIND_SOURCES:
                    errors.append(f"{r.id}: nguồn gắn '{source}' không hợp lệ")
                if name not in definition.params_model.model_fields:
                    errors.append(f"{r.id}: tham số '{name}' không thuộc {s.task_type}")
            try:
                definition.params_model.model_validate(s.params)
            except ValidationError as exc:
                # Tham số sẽ được gắn từ tình huống thì thiếu lúc này là bình thường; mọi lỗi khác là lỗi thật.
                real = [e for e in exc.errors() if not (e["type"] == "missing" and e["loc"][:1] and e["loc"][0] in s.bind)]
                if real:
                    errors.append(f"{r.id}: tham số tĩnh của {s.task_type} không hợp lệ: {real[0]['msg']}")
    return errors


def _describe_when(w: When) -> str:
    parts: list[str] = []
    if w.rtypes:
        parts.append("loại " + "/".join(sorted(w.rtypes)))
    if w.provisional:
        parts.append("nhãn tạm " + "/".join(sorted(w.provisional)))
    if w.need:
        parts.append(f"còn thiếu {w.need}")
    if w.missing is not None:
        parts.append("còn thiếu mục nào đó" if w.missing else "không còn thiếu gì")
    if w.conflict is not None:
        parts.append("có mâu thuẫn" if w.conflict else "không có mâu thuẫn")
    if w.critique:
        parts.append({"none": "chưa phản biện", "clean": "phản biện sạch", "issues": "phản biện nêu vấn đề"}[w.critique])
    if w.critique_kind:
        parts.append(f"vấn đề {w.critique_kind}")
    if w.first_round is not None:
        parts.append("vòng 1" if w.first_round else "sau vòng 1")
    if w.not_dispatched:
        parts.append("chưa giao " + "/".join(sorted(w.not_dispatched)))
    return "; ".join(parts) or "luôn"


def _describe_suggest(s: Suggest) -> str:
    args = [f"{k}={v}" for k, v in sorted(s.params.items())] + [f"{k}←{v}" for k, v in sorted(s.bind.items())]
    return f"{s.task_type}({', '.join(args)})" if args else s.task_type


def render_playbook(rules: Sequence[PlaybookRule]) -> str:
    """In sổ tay thành văn bản cho lời nhắc/skill. Cùng nguồn dữ liệu với advisor nên hai bên không thể lệch nhau."""
    lines: list[str] = []
    for r in sorted(rules, key=lambda x: (x.priority, x.id)):
        action = "dừng" if r.stop else " + ".join(_describe_suggest(s) for s in r.suggest)
        lines.append(f"- `{r.id}` khi {_describe_when(r.when)} → {action} (`{r.rationale_code}`)." + (f" {r.note}" if r.note else ""))
    return "\n".join(lines)


def _plain(value: Any) -> Any:
    """Dạng JSON tất định của một giá trị khai báo (tập thành danh sách đã sắp xếp)."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}  # type: ignore[reportUnknownVariableType]
    if isinstance(value, (set, frozenset)):
        return sorted(_plain(v) for v in value)  # type: ignore[reportUnknownVariableType]
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]  # type: ignore[reportUnknownVariableType]
    return value


def playbook_version(rules: Sequence[PlaybookRule]) -> str:
    """Phiên bản sổ tay = hash nội dung, không phụ thuộc thứ tự khai báo."""
    return content_hash(sorted((_plain(r) for r in rules), key=lambda r: str(r["id"])))

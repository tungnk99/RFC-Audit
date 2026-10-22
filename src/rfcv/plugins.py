"""Registry plugin: nơi duy nhất mọi mở rộng đăng ký vào lõi.

Nguyên tắc:
- Tập đóng trong lõi (vai trò, kiểu nhiệm vụ, loại bằng chứng, công cụ, nhà cung cấp LLM, backend…)
  được thay bằng registry. Lõi không có hằng số nào về miền cụ thể.
- Registry **đóng băng** sau khi nạp (`freeze()`); không đăng ký thêm lúc chạy, nên bề mặt tấn công cố định.
- Mọi công cụ đăng ký phải có `Effect` thuộc tập an toàn (đọc, hoặc chạy trong sandbox). Công cụ ghi tệp,
  gọi mạng hay chạy lệnh trên máy chủ bị từ chối, trừ khi người vận hành cho phép tường minh.
- Plugin bên thứ ba đăng ký qua entry points (nhóm `rfcv.*`); thành phần có sẵn đăng ký bằng đúng API công khai
  này (`rfcv.builtin`), nên chạy được cả khi chưa cài gói.
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterable
from contextlib import contextmanager
from contextvars import ContextVar
from importlib.metadata import EntryPoint, entry_points
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from rfcv.spi import (
    SAFE_EFFECTS,
    DomainPack,
    Effect,
    EvidenceKind,
    LoopPolicy,
    PlaybookRule,
    TaskDefinition,
    ToolDescriptor,
)

if TYPE_CHECKING:
    from rfcv.evidence.verdict_engine import RuleSet

ENTRY_POINT_GROUPS = (
    "rfcv.domains",
    "rfcv.backends",
    "rfcv.code_indexes",
    "rfcv.sut_launchers",
    "rfcv.executors",
    "rfcv.tool_packs",
    "rfcv.rule_sets",
    "rfcv.llm_providers",
    "rfcv.agent_runtimes",
    "rfcv.source_parsers",
)


class RegistryError(RuntimeError):
    pass


def _produce(obj: Any) -> Any:
    """Entry point nhóm "giá trị" (miền, gói công cụ, bộ quy tắc) có thể là giá trị hoặc hàm trả giá trị."""
    return obj() if callable(obj) else obj


class Registry:
    def __init__(self, *, allow_effects: Iterable[Effect] = SAFE_EFFECTS) -> None:
        self.allow_effects = frozenset(allow_effects)
        self.kinds: dict[str, EvidenceKind] = {}
        self.schemas: dict[str, type[BaseModel]] = {}
        self.tasks: dict[str, TaskDefinition] = {}
        self.rationale_codes: list[str] = []
        self.playbook: list[PlaybookRule] = []
        self.rule_sets: dict[str, RuleSet] = {}
        self.tools: dict[str, ToolDescriptor] = {}
        self.domains: dict[str, DomainPack] = {}
        self.backends: dict[str, Callable[..., Any]] = {}
        self.code_indexes: dict[str, Callable[..., Any]] = {}
        self.sut_launchers: dict[str, Callable[..., Any]] = {}
        self.executors: dict[str, Callable[..., Any]] = {}
        self.llm_providers: dict[str, Callable[..., Any]] = {}
        self.agent_runtimes: dict[str, Callable[..., Any]] = {}
        self.source_parsers: dict[str, Callable[..., Any]] = {}
        self._frozen = False
        from rfcv.agents.schemas import CORE_SCHEMAS  # nhập muộn để tránh vòng nhập

        self.schemas.update(CORE_SCHEMAS)

    # ---- đăng ký -------------------------------------------------------------------------------

    @property
    def frozen(self) -> bool:
        return self._frozen

    def _open(self) -> None:
        if self._frozen:
            raise RegistryError("registry đã đóng băng; không đăng ký thêm lúc chạy")

    @staticmethod
    def _put[T](table: dict[str, T], name: str, value: T, what: str) -> None:
        if name in table:
            raise RegistryError(f"{what} '{name}' đã đăng ký")
        table[name] = value

    def register_kind(self, kind: EvidenceKind) -> None:
        self._open()
        self._put(self.kinds, kind.name, kind, "loại bằng chứng")

    def register_schema(self, name: str, model: type[BaseModel]) -> None:
        self._open()
        if name in self.schemas and self.schemas[name] is not model:
            raise RegistryError(f"schema '{name}' đã đăng ký")
        self.schemas[name] = model

    def register_task(self, task: TaskDefinition) -> None:
        self._open()
        self._put(self.tasks, task.name, task, "kiểu nhiệm vụ")

    def register_rule_set(self, rule_set: RuleSet) -> None:
        self._open()
        self._put(self.rule_sets, rule_set.name, rule_set, "bộ quy tắc")

    def register_tool(self, tool: ToolDescriptor) -> None:
        self._open()
        if tool.effect not in self.allow_effects:
            raise RegistryError(
                f"công cụ '{tool.name}' có tác động '{tool.effect.value}' ngoài tập được phép "
                f"{sorted(e.value for e in self.allow_effects)}"
            )
        self._put(self.tools, tool.name, tool, "công cụ")

    def register_domain(self, pack: DomainPack) -> None:
        self._open()
        self._put(self.domains, pack.name, pack, "miền")
        for kind in pack.evidence_kinds:
            self.register_kind(kind)
        for name, model in pack.schemas.items():
            self.register_schema(name, model)
        for task in pack.tasks:
            self.register_task(task)
        for code in pack.rationale_codes:
            if code in self.rationale_codes:
                raise RegistryError(f"mã lý do '{code}' đã đăng ký")
            self.rationale_codes.append(code)
        self.playbook.extend(pack.playbook)
        for rs in pack.rule_sets:
            self.register_rule_set(rs)
        for tool in pack.tools:
            self.register_tool(tool)

    def register_backend(self, name: str, factory: Callable[..., Any]) -> None:
        self._open()
        self._put(self.backends, name, factory, "backend")

    def register_code_index(self, name: str, factory: Callable[..., Any]) -> None:
        self._open()
        self._put(self.code_indexes, name, factory, "chỉ mục mã")

    def register_sut_launcher(self, name: str, factory: Callable[..., Any]) -> None:
        self._open()
        self._put(self.sut_launchers, name, factory, "bộ chạy SUT")

    def register_executor(self, name: str, factory: Callable[..., Any]) -> None:
        self._open()
        self._put(self.executors, name, factory, "bộ chạy lệnh sandbox")

    def register_llm_provider(self, name: str, factory: Callable[..., Any]) -> None:
        self._open()
        self._put(self.llm_providers, name, factory, "nhà cung cấp LLM")

    def register_agent_runtime(self, name: str, factory: Callable[..., Any]) -> None:
        self._open()
        self._put(self.agent_runtimes, name, factory, "agent runtime")

    def register_source_parser(self, name: str, factory: Callable[..., Any]) -> None:
        self._open()
        self._put(self.source_parsers, name, factory, "bộ phân tích nguồn")

    # ---- truy vấn ------------------------------------------------------------------------------

    def domain(self, name: str | None = None) -> DomainPack:
        if name is not None:
            try:
                return self.domains[name]
            except KeyError as exc:
                raise RegistryError(f"miền '{name}' chưa đăng ký (có: {sorted(self.domains)})") from exc
        if len(self.domains) == 1:
            return next(iter(self.domains.values()))
        raise RegistryError(f"cần chỉ rõ miền; hiện có {sorted(self.domains)}")

    def loop_policy(self, domain: str | None = None) -> LoopPolicy:
        return self.domain(domain).loop

    def default_rule_set(self) -> RuleSet:
        if len(self.rule_sets) == 1:
            return next(iter(self.rule_sets.values()))
        raise RegistryError(f"cần chỉ rõ bộ quy tắc; hiện có {sorted(self.rule_sets)}")

    def task_names(self) -> list[str]:
        return sorted(self.tasks)

    def role_names(self) -> list[str]:
        return sorted({r for d in self.domains.values() for r in d.required_roles})

    # ---- vòng đời ------------------------------------------------------------------------------

    def load_entry_points(self, eps: Iterable[EntryPoint] | None = None) -> None:
        """Nạp plugin bên thứ ba. Mỗi entry point trả về một callable theo nhóm của nó."""
        self._open()
        found = list(eps) if eps is not None else [ep for g in ENTRY_POINT_GROUPS for ep in entry_points(group=g)]
        for ep in found:
            obj: Any = ep.load()
            match ep.group:
                case "rfcv.domains":
                    self.register_domain(_produce(obj))
                case "rfcv.tool_packs":
                    for tool in _produce(obj):
                        self.register_tool(tool)
                case "rfcv.rule_sets":
                    self.register_rule_set(_produce(obj))
                case "rfcv.backends":
                    self.register_backend(ep.name, obj)
                case "rfcv.code_indexes":
                    self.register_code_index(ep.name, obj)
                case "rfcv.sut_launchers":
                    self.register_sut_launcher(ep.name, obj)
                case "rfcv.executors":
                    self.register_executor(ep.name, obj)
                case "rfcv.llm_providers":
                    self.register_llm_provider(ep.name, obj)
                case "rfcv.agent_runtimes":
                    self.register_agent_runtime(ep.name, obj)
                case "rfcv.source_parsers":
                    self.register_source_parser(ep.name, obj)
                case _:
                    raise RegistryError(f"nhóm entry point lạ: {ep.group}")

    @property
    def playbook_version(self) -> str:
        """Hash nội dung của sổ tay: đổi một quy tắc là đổi phiên bản (như RuleSet.version)."""
        from rfcv.core.advisor import playbook_version

        return playbook_version(self.playbook)

    def freeze(self) -> Registry:
        if self._frozen:
            return self
        from rfcv.agents.schemas import build_plan_action_model
        from rfcv.core.advisor import validate_playbook
        from rfcv.evidence.verdict_engine import Label

        errors = validate_playbook(self.playbook, self.tasks, self.rationale_codes, [lab.value for lab in Label])
        if errors:
            raise RegistryError("sổ tay điều tra không hợp lệ: " + "; ".join(errors))
        self.schemas["PlanAction@1"] = build_plan_action_model(self.tasks, self.rationale_codes)
        self._frozen = True
        return self

    @classmethod
    def build(
        cls,
        *,
        builtin: bool = True,
        third_party: bool = True,
        freeze: bool = True,
        allow_effects: Iterable[Effect] = SAFE_EFFECTS,
    ) -> Registry:
        """Dựng registry: thành phần có sẵn, rồi plugin bên thứ ba. `freeze=False` để người nhúng đăng ký thêm."""
        reg = cls(allow_effects=allow_effects)
        if builtin:
            from rfcv.builtin import register_builtin

            register_builtin(reg)
        if third_party:
            reg.load_entry_points()
        return reg.freeze() if freeze else reg


# ---- registry hiện hành -------------------------------------------------------------------------

_current: ContextVar[Registry | None] = ContextVar("rfcv_registry", default=None)
_default: Registry | None = None


def current_registry() -> Registry:
    reg = _current.get()
    if reg is not None:
        return reg
    global _default
    if _default is None:
        _default = Registry.build()
    return _default


@contextmanager
def use_registry(reg: Registry) -> Generator[Registry]:
    """Dùng một registry riêng trong phạm vi (kiểm thử, hoặc chạy nhiều cấu hình trong một tiến trình)."""
    token = _current.set(reg)
    try:
        yield reg
    finally:
        _current.reset(token)


def reset_default_registry() -> None:
    global _default
    _default = None

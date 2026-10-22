"""Policy store: hồ sơ vai trò và ma trận quyền công cụ (thiết kế chính, mục 4.2, Bảng 24).

Chỉ đọc khi chạy; hash ghi vào bản kê lần chạy. Danh mục vai trò, công cụ và schema lấy từ registry
(domain pack đăng ký), không có hằng số nào trong lõi. Bất biến kiểm tra lúc nạp:
- agent đặc quyền không có công cụ đọc dữ liệu không tin cậy (`reads_untrusted`): đó là ranh giới cách ly;
- agent cách ly chỉ có công cụ đọc dữ liệu không tin cậy;
- mọi công cụ phải có trong danh mục; danh mục chỉ nhận công cụ có tác động thuộc tập được phép
  (đọc, chạy trong sandbox), nên không vai trò nào có công cụ ghi tệp, gọi mạng hay chạy lệnh trên máy chủ.
"""

from __future__ import annotations

import os
from collections.abc import Collection, Iterable, Mapping
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from rfcv.common.hashing import content_hash
from rfcv.plugins import Registry, current_registry
from rfcv.spi import ToolDescriptor

AGENTS_ENV = "RFCV_AGENTS_DIR"


def find_agents_root() -> Path:
    """Thư mục `agents/` chứa hồ sơ và lời nhắc: biến môi trường RFCV_AGENTS_DIR, rồi ./agents, rồi gốc repo (cài kiểu phát triển)."""
    env = os.environ.get(AGENTS_ENV)
    if env:
        return Path(env)
    for candidate in (Path.cwd() / "agents", Path(__file__).resolve().parents[3] / "agents"):
        if candidate.is_dir():
            return candidate
    return Path.cwd() / "agents"


class Zone(StrEnum):
    PRIVILEGED = "privileged"
    QUARANTINE = "quarantine"


class TaskBudget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    llm_calls: int
    tool_calls: int
    tokens: int
    seconds: int


class RoleProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str
    zone: Zone
    context_fields: tuple[str, ...]
    tools: tuple[str, ...]
    output_schema: str
    prompt: str
    budget_per_task: TaskBudget
    receives_from: tuple[str, ...] = ("execution_loop",)
    sends_to: tuple[str, ...] = ("execution_loop",)


class PolicyError(ValueError):
    pass


class PolicyStore:
    def __init__(
        self,
        profiles: Iterable[RoleProfile],
        schemas: Collection[str],
        tools: Mapping[str, ToolDescriptor],
        required_roles: Iterable[str],
        prompt_paths: Mapping[str, Path] | None = None,
    ) -> None:
        self._profiles = {p.role: p for p in profiles}
        self._prompt_paths = dict(prompt_paths or {})
        known_schemas = set(schemas)
        required = set(required_roles)
        errors: list[str] = []
        for role in sorted(required - self._profiles.keys()):
            errors.append(f"thiếu hồ sơ vai trò {role}")
        for p in self._profiles.values():
            if p.output_schema not in known_schemas:
                errors.append(f"{p.role}: schema {p.output_schema} không tồn tại")
            for tool in p.tools:
                descriptor = tools.get(tool)
                if descriptor is None:
                    errors.append(f"{p.role}: công cụ {tool} không có trong danh mục")
                    continue
                if p.zone is Zone.PRIVILEGED and descriptor.reads_untrusted:
                    errors.append(f"{p.role}: agent đặc quyền không được có công cụ đọc dữ liệu không tin cậy ({tool})")
                if p.zone is Zone.QUARANTINE and not descriptor.reads_untrusted:
                    errors.append(f"{p.role}: agent cách ly chỉ được có công cụ đọc dữ liệu không tin cậy ({tool})")
        if errors:
            raise PolicyError("; ".join(errors))

    @classmethod
    def load(
        cls,
        roles_dir: Path | None = None,
        registry: Registry | None = None,
        domain: str | None = None,
        agents_root: Path | None = None,
    ) -> PolicyStore:
        """Nạp hồ sơ vai trò của một miền.

        Miền tổ chức theo agent (`DomainPack.agents`): hồ sơ và lời nhắc là DỮ LIỆU ở `<agents_root>/<agent>/` ngoài mã nguồn
        (`agents_root` rỗng thì tìm theo `find_agents_root`). Chỉ nạp dữ liệu, không bao giờ nạp mã. Vùng tin cậy và schema đầu
        ra do MÃ của agent khai báo (`AgentSpec`); `role.yaml` phải khớp, vì đó là kiến trúc chứ không phải chỉnh tham số.
        Miền cũ (không khai báo agent) vẫn nạp từ hai thư mục roles/ và prompts/ của nó.
        """
        reg = registry or current_registry()
        pack = reg.domain(domain)
        profiles: list[RoleProfile] = []
        prompt_paths: dict[str, Path] = {}
        if pack.agents:
            root = agents_root if agents_root is not None else find_agents_root()
            declared = {a.name: a for a in pack.agents}
            folders = {f.name: f for f in sorted(root.iterdir()) if f.is_dir()} if root.is_dir() else {}
            for name, agent in declared.items():
                if not agent.has_role:
                    continue
                if name not in folders or not (folders[name] / "role.yaml").is_file():
                    raise PolicyError(f"thiếu {root / name / 'role.yaml'} (hồ sơ agent {name})")
            for name, folder in folders.items():
                role_file = folder / "role.yaml"
                agent = declared.get(name)
                if not role_file.is_file():
                    raise PolicyError(f"{folder}: thiếu role.yaml")
                profile = RoleProfile.model_validate(yaml.safe_load(role_file.read_text(encoding="utf-8")))
                if profile.role != name:
                    raise PolicyError(f"{role_file}: role '{profile.role}' phải trùng tên thư mục '{name}'")
                if agent is not None and (profile.zone.value, profile.output_schema) != (agent.zone, agent.output_schema):
                    raise PolicyError(
                        f"{role_file}: {name} không được đổi vùng tin cậy hay schema đầu ra "
                        f"(mã khai báo {agent.zone}, {agent.output_schema})"
                    )
                prompt = folder / profile.prompt
                if not prompt.is_file():
                    raise PolicyError(f"{role_file}: thiếu lời nhắc {profile.prompt}")
                profiles.append(profile)
                prompt_paths[name] = prompt
        else:
            directory = roles_dir if roles_dir is not None else pack.roles_dir
            if directory is not None:
                prompts = pack.prompts_dir if pack.prompts_dir is not None else directory
                for f in sorted(directory.glob("*.yaml")):
                    profile = RoleProfile.model_validate(yaml.safe_load(f.read_text(encoding="utf-8")))
                    profiles.append(profile)
                    prompt_paths[profile.role] = prompts / profile.prompt
        return cls(profiles, reg.schemas.keys(), reg.tools, pack.required_roles, prompt_paths)

    def prompt_path(self, role: str) -> Path:
        return self._prompt_paths[role]

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(sorted(self._profiles))

    def profile(self, role: str) -> RoleProfile:
        return self._profiles[role]

    def allows(self, role: str, tool: str) -> bool:
        p = self._profiles.get(role)
        return p is not None and tool in p.tools

    @property
    def digest(self) -> str:
        return content_hash({r: p.model_dump(mode="json") for r, p in sorted(self._profiles.items())})

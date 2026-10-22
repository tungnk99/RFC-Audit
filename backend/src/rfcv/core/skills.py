"""Agent Skills theo chuẩn agentskills.io: kiểm định, chọn tất định, băm. Phần này thuần Python, không biết framework.

Chuẩn: mỗi skill là một thư mục có SKILL.md (frontmatter `name`, `description`), nạp dần:
mô hình chỉ thấy tên và mô tả, gọi công cụ nạp để lấy phần thân khi cần. Việc gắn vào một framework agent cụ thể
(workspace chỉ đọc, capability) nằm ở `rfcv.runtime.<framework>`.

Ràng buộc an toàn của đề tài, thêm lên trên chuẩn:
- Skill là đầu vào TRUSTED: chỉ đọc từ thư viện lõi và adapter đã kiểm định, có hash trong bản kê.
- Runtime phải cấp quyền đọc chỉ đọc, giam đường dẫn và **không có khả năng chạy lệnh** (xem
  runtime.pydantic_ai.skills).
- Không cho phép `scripts/` (rủi ro A3); `references/` chỉ đọc qua công cụ `skill.read_reference`
  đi qua Tool gateway.
- `skills/` là kho chung. Agent nào dùng skill nào do chính agent khai báo (`skills:` trong `agents/<tên>/role.yaml`);
  không khai báo thì không có skill. Skill chỉ tự giới hạn theo kiểu nhiệm vụ (`rfcv-task-types`), không tự chọn agent.
  Bộ skill mỗi lượt được chọn tất định từ hai điều kiện đó (lọc `include` của harness không phải ranh giới phân quyền,
  nên ta tự lọc trước).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import yaml

from rfcv.common.hashing import content_hash

_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.S)
ALLOWED_TOP_LEVEL = {"SKILL.md", "references", "assets", "LICENSE.txt"}
MAX_BODY_LINES = 500
# Khai báo trong `skills:` của role.yaml: nhận mọi skill trong thư viện của adapter đang chạy (lọc theo kiểu nhiệm vụ). Nhờ vậy
# hồ sơ agent không phải gọi tên skill của từng giao thức; thêm giao thức là thêm thư mục skills/<adapter>/.
ADAPTER_SKILLS = "@adapter"


# ---------------------------------------------------------------- kiểm định theo chuẩn


@dataclass(frozen=True)
class SkillInfo:
    name: str
    description: str
    path: Path
    task_types: frozenset[str]
    metadata: dict[str, str]
    digest: str


@dataclass
class SkillValidation:
    skills: list[SkillInfo] = field(default_factory=list[SkillInfo])
    errors: list[str] = field(default_factory=list[str])


def _split_set(value: str | None) -> frozenset[str]:
    return frozenset(v for v in (value or "").split() if v)


def validate_library(library: Path, known_task_types: Iterable[str]) -> SkillValidation:
    """Kiểm định một thư viện skill theo chuẩn Agent Skills và ràng buộc của rfcv."""
    tasks = set(known_task_types)
    result = SkillValidation()
    if not library.is_dir():
        return result
    for skill_dir in sorted(p for p in library.iterdir() if p.is_dir()):
        where = f"{library.name}/{skill_dir.name}"
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            result.errors.append(f"{where}: thiếu SKILL.md")
            continue
        errors: list[str] = []
        text = skill_md.read_text(encoding="utf-8")
        m = _FRONTMATTER.match(text)
        if not m:
            result.errors.append(f"{where}: thiếu frontmatter YAML")
            continue
        try:
            loaded: object = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError as exc:
            result.errors.append(f"{where}: frontmatter lỗi: {exc}")
            continue
        if not isinstance(loaded, dict):
            result.errors.append(f"{where}: frontmatter phải là ánh xạ")
            continue
        front = {str(k): v for k, v in cast(dict[object, object], loaded).items()}
        name = front.get("name")
        desc = front.get("description")
        if not isinstance(name, str) or not _NAME.match(name) or len(name) > 64:
            errors.append("name: 1–64 ký tự a-z, 0-9, '-', không bắt đầu/kết thúc bằng '-', không '--'")
        elif name != skill_dir.name:
            errors.append(f"name '{name}' phải trùng tên thư mục '{skill_dir.name}'")
        if not isinstance(desc, str) or not desc.strip() or len(desc) > 1024:
            errors.append("description: bắt buộc, 1–1024 ký tự")
        compat = front.get("compatibility")
        if compat is not None and (not isinstance(compat, str) or not 1 <= len(compat) <= 500):
            errors.append("compatibility: 1–500 ký tự")
        raw_meta = front.get("metadata", {})
        metadata: dict[str, str] = {}
        meta_items = cast(dict[object, object], raw_meta).items() if isinstance(raw_meta, dict) else None
        if meta_items is None or not all(isinstance(k, str) and isinstance(v, str) for k, v in meta_items):
            errors.append("metadata: phải là ánh xạ chuỗi → chuỗi")
        else:
            metadata = {str(k): str(v) for k, v in meta_items}
        if "allowed-tools" in front:
            errors.append("allowed-tools: không dùng; quyền công cụ do Policy store quyết định")
        if "rfcv-roles" in metadata:
            errors.append(
                "metadata.rfcv-roles: không dùng; agent khai báo skill trong agents/<tên>/role.yaml (skills:)"
            )
        skill_tasks = _split_set(metadata.get("rfcv-task-types"))
        if skill_tasks - tasks:
            errors.append(f"metadata.rfcv-task-types: kiểu nhiệm vụ lạ {sorted(skill_tasks - tasks)}")
        if len(m.group(2).splitlines()) > MAX_BODY_LINES:
            errors.append(f"thân SKILL.md vượt {MAX_BODY_LINES} dòng; tách sang references/")
        for child in skill_dir.iterdir():
            if child.name not in ALLOWED_TOP_LEVEL:
                errors.append(f"không cho phép '{child.name}' (scripts/ bị cấm: skill chỉ là hướng dẫn)")
            if child.is_symlink():
                errors.append(f"không cho phép symlink '{child.name}'")
        refs = skill_dir / "references"
        if refs.is_dir():
            for f in refs.iterdir():
                if f.is_dir() or f.is_symlink() or f.suffix not in (".md", ".txt"):
                    errors.append(f"references/{f.name}: chỉ tệp .md/.txt, một cấp")
        if errors:
            result.errors += [f"{where}: {e}" for e in errors]
            continue
        files = {
            p.relative_to(skill_dir).as_posix(): p.read_text(encoding="utf-8")
            for p in sorted(skill_dir.rglob("*"))
            if p.is_file()
        }
        result.skills.append(
            SkillInfo(
                name=str(name),
                description=str(desc),
                path=skill_dir,
                task_types=skill_tasks,
                metadata=metadata,
                digest=content_hash(files),
            )
        )
    return result


# ---------------------------------------------------------------- chọn skill


class SkillRegistry:
    """Các thư viện skill của một lần chạy: lõi (không gắn giao thức) và adapter."""

    def __init__(self, libraries: Mapping[str, Path], known_task_types: Iterable[str]) -> None:
        tasks = list(known_task_types)
        self._libraries = dict(libraries)
        self.skills: dict[str, SkillInfo] = {}
        self._library_of: dict[str, str] = {}
        errors: list[str] = []
        for lib_name, lib in self._libraries.items():
            v = validate_library(lib, tasks)
            errors += v.errors
            for s in v.skills:
                if s.name in self.skills:
                    errors.append(f"skill trùng tên: {s.name}")
                self.skills[s.name] = s
                self._library_of[s.name] = lib_name
        if errors:
            raise ValueError("; ".join(errors))

    @property
    def libraries(self) -> dict[str, Path]:
        return dict(self._libraries)

    @property
    def digest(self) -> str:
        return content_hash({n: s.digest for n, s in sorted(self.skills.items())})

    def select(self, declared: Iterable[str], task_type: str | None = None) -> list[str]:
        """Tất định: skill agent đã khai báo, có trong lần chạy này, và (nếu skill giới hạn) đúng kiểu nhiệm vụ.

        Skill khai báo mà không có trong lần chạy (ví dụ skill của adapter khác) bị bỏ qua; tên sai đã bị
        `undeclared_skills` chặn lúc lắp runtime.
        """
        names = set(declared)
        if ADAPTER_SKILLS in names:
            names.discard(ADAPTER_SKILLS)
            names |= {n for n, lib in self._library_of.items() if lib != "core"}
        return sorted(
            s.name
            for name in names
            if (s := self.skills.get(name)) is not None
            and (not s.task_types or task_type is None or task_type in s.task_types)
        )

    def read_reference(self, skill: str, relpath: str) -> str:
        info = self.skills.get(skill)
        if info is None:
            raise FileNotFoundError(skill)
        parts = Path(relpath).parts
        if len(parts) != 2 or parts[0] != "references":
            raise FileNotFoundError(relpath)
        target = (info.path / relpath).resolve()
        if target.parent != (info.path / "references").resolve() or not target.is_file():
            raise FileNotFoundError(relpath)
        return target.read_text(encoding="utf-8")


def default_registry(
    skills_root: Path,
    adapter: str | None = None,
    *,
    task_types: Iterable[str] | None = None,
) -> SkillRegistry:
    """Thư viện lõi (skills/core) cộng thư viện của adapter (skills/<adapter>) nếu có.

    Kiểu nhiệm vụ hợp lệ lấy từ registry plugin (domain pack), trừ khi truyền tường minh.
    """
    from rfcv.plugins import current_registry

    libraries = {"core": skills_root / "core"}
    if adapter and (skills_root / adapter).is_dir():
        libraries[adapter] = skills_root / adapter
    return SkillRegistry(libraries, task_types if task_types is not None else current_registry().task_names())


def undeclared_skills(declared: Mapping[str, Iterable[str]], skills_root: Path) -> list[str]:
    """Tên skill agent khai báo mà không có trong bất kỳ thư viện nào dưới `skills_root` (gõ sai tên, skill đã xoá).

    Xét mọi thư viện chứ không chỉ thư viện của lần chạy, để skill của adapter khác không bị coi là lỗi.
    """
    existing = {p.parent.name for p in skills_root.glob("*/*/SKILL.md")} if skills_root.is_dir() else set[str]()
    return [
        f"{role}: {name}"
        for role, names in sorted(declared.items())
        for name in names
        if name not in existing and name != ADAPTER_SKILLS
    ]

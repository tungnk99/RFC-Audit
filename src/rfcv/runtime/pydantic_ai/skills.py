"""Gắn Agent Skills vào PydanticAI qua `pydantic_ai_harness.Skills`.

`SkillLibraryWorkspace` là workspace **chỉ đọc**, không cài `SupportsCommands` (không có `run`), và giam mọi đường dẫn
trong các thư viện được gắn (kể cả qua `..` hoặc symlink). Nhờ đó `load_capability` của framework, vốn không đi qua
Tool gateway, không mở thêm quyền nào.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Never

from pydantic_ai.workspaces import WorkspaceReadOnlyError
from pydantic_ai.workspaces.protocol import FileEntry
from pydantic_ai_harness import Skills

from rfcv.core.skills import SkillRegistry

VIRTUAL_ROOT = "/skills"
_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class SkillLibraryWorkspace:
    """WorkspaceBackend chỉ đọc cho thư viện skill. Gắn mỗi thư viện vào /skills/<mount>."""

    def __init__(self, mounts: Mapping[str, Path]) -> None:
        for name in mounts:
            if not _NAME.match(name):
                raise ValueError(f"tên mount không hợp lệ: {name}")
        self._mounts = {name: path.resolve() for name, path in mounts.items()}

    # --- WorkspaceBackend
    @property
    def ref(self) -> None:
        return None

    async def working_dir(self) -> str:
        return VIRTUAL_ROOT

    # --- ánh xạ đường dẫn ảo → thật, có giam
    def _real(self, path: str) -> Path | None:
        norm = posixpath.normpath(path)
        if norm == VIRTUAL_ROOT:
            return None
        if not norm.startswith(VIRTUAL_ROOT + "/"):
            raise FileNotFoundError(path)
        mount, _, rest = norm[len(VIRTUAL_ROOT) + 1 :].partition("/")
        base = self._mounts.get(mount)
        if base is None:
            raise FileNotFoundError(path)
        real = (base / rest).resolve() if rest else base
        if real != base and base not in real.parents:
            raise FileNotFoundError(path)  # thoát khỏi thư viện (.., symlink)
        return real

    def _entry(self, vpath: str, real: Path | None) -> FileEntry:
        if real is None:
            return FileEntry(name="skills", path=VIRTUAL_ROOT, is_dir=True, size=None)
        if not real.exists():
            raise FileNotFoundError(vpath)
        return FileEntry(
            name=posixpath.basename(vpath),
            path=posixpath.normpath(vpath),
            is_dir=real.is_dir(),
            size=None if real.is_dir() else real.stat().st_size,
        )

    # --- SupportsFilesystem (chỉ đọc)
    async def read_bytes(self, path: str) -> bytes:
        real = self._real(path)
        if real is None or real.is_dir():
            raise IsADirectoryError(path)
        if not real.exists():
            raise FileNotFoundError(path)
        return real.read_bytes()

    async def stat(self, path: str) -> FileEntry:
        return self._entry(path, self._real(path))

    async def exists(self, path: str) -> bool:
        try:
            real = self._real(path)
        except FileNotFoundError:
            return False
        return real is None or real.exists()

    async def list_dir(self, path: str) -> Sequence[FileEntry]:
        real = self._real(path)
        if real is None:
            return [FileEntry(name=m, path=f"{VIRTUAL_ROOT}/{m}", is_dir=True, size=None) for m in sorted(self._mounts)]
        if not real.is_dir():
            raise NotADirectoryError(path)
        vbase = posixpath.normpath(path)
        return [self._entry(f"{vbase}/{child.name}", child) for child in sorted(real.iterdir())]

    async def realpath(self, path: str) -> str:
        self._real(path)  # giam: ném lỗi nếu thoát ra ngoài
        return posixpath.normpath(path)

    async def write_bytes(self, path: str, data: bytes) -> Never:
        raise WorkspaceReadOnlyError(path)

    async def make_dir(self, path: str) -> Never:
        raise WorkspaceReadOnlyError(path)

    async def remove(self, path: str) -> Never:
        raise WorkspaceReadOnlyError(path)


def skills_capability(registry: SkillRegistry, names: Sequence[str]) -> Skills | None:
    """Capability cho đúng bộ skill đã chọn (`SkillRegistry.select`); None nếu không có skill nào."""
    if not names:
        return None
    return Skills(sorted(registry.libraries), include=names, workspace=SkillLibraryWorkspace(registry.libraries))

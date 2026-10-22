"""Bản sao phạm vi của kho mã tại commit cố định (ràng buộc C3; tài liệu khám phá mã, Bảng 6).

- Xác minh commit bằng cách đọc thẳng `.git/HEAD` và refs; không chạy `git` trong kho mã không tin cậy (cấu hình
  `.git/config` có thể khiến git chạy lệnh tuỳ ý, ví dụ core.fsmonitor).
- Chỉ sao tệp thường thuộc `code_scope`; tệp khoá, chứng chỉ, `.git` và mọi symlink bị loại ngay lúc sao, nên sandbox
  gắn bản sao này thì không có cách nào đọc ra ngoài phạm vi.
- Ghi digest bản sao (sha256 trên danh sách tệp và hash từng tệp) để đưa vào bản kê lần chạy.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from rfcv.gates.explore_policy import included_file

_SHA = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")


class WorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Workspace:
    source: str
    root: str  # bản sao chỉ gồm phần trong phạm vi; gốc của sandbox (/repo)
    commit: str | None
    snapshot: str
    files: int
    skipped_symlinks: int

    @property
    def root_path(self) -> Path:
        return Path(self.root)

    def manifest_entries(self) -> dict[str, str]:
        return {"code:commit": self.commit or "unverified", "code:snapshot": self.snapshot}


def _git_dir(repo: Path) -> Path | None:
    dot = repo / ".git"
    if dot.is_dir():
        return dot
    if dot.is_file():
        line = dot.read_text(encoding="utf-8", errors="replace").strip()
        if line.startswith("gitdir:"):
            p = Path(line.removeprefix("gitdir:").strip())
            return p if p.is_absolute() else (repo / p).resolve()
    return None


def git_head(repo: Path) -> str | None:
    """Commit HEAD của một kho git, đọc từ tệp (không chạy git). None nếu không phải kho git hoặc không đọc được."""
    gd = _git_dir(repo)
    if gd is None:
        return None
    try:
        head = (gd / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if _SHA.match(head):
        return head
    if not head.startswith("ref:"):
        return None
    ref = head.removeprefix("ref:").strip()
    common = gd
    if (gd / "commondir").is_file():  # worktree: refs nằm ở kho chung
        common = (gd / (gd / "commondir").read_text(encoding="utf-8").strip()).resolve()
    for base in (gd, common):
        f = base / ref
        if f.is_file():
            sha = f.read_text(encoding="utf-8").strip()
            return sha if _SHA.match(sha) else None
        packed = base / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8", errors="replace").splitlines():
                parts = line.split(" ", 1)
                if len(parts) == 2 and parts[1].strip() == ref and _SHA.match(parts[0]):
                    return parts[0]
    return None


def stage_scope(source: Path, include: tuple[str, ...], exclude: tuple[str, ...], dest: Path) -> tuple[str, int, int]:
    """Sao các tệp trong phạm vi từ `source` sang `dest`. Trả (digest, số tệp, số symlink bị bỏ)."""
    if dest.exists():
        raise WorkspaceError(f"thư mục đích đã tồn tại: {dest}")
    dest.mkdir(parents=True)
    digest = hashlib.sha256()
    copied = 0
    skipped = 0
    entries: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
        here = Path(dirpath)
        keep: list[str] = []
        for d in dirnames:
            if d == ".git" or (here / d).is_symlink():
                skipped += int((here / d).is_symlink())
                continue
            keep.append(d)
        dirnames[:] = sorted(keep)
        for name in filenames:
            p = here / name
            if p.is_symlink():
                skipped += 1
                continue
            if not p.is_file():
                continue
            rel = p.relative_to(source).as_posix()
            if included_file(rel, include, exclude):
                entries.append((rel, p))
    for rel, p in sorted(entries):
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, target)
        digest.update(f"{rel}\0{hashlib.sha256(target.read_bytes()).hexdigest()}\n".encode())
        copied += 1
    if os.name == "posix":  # bản sao chỉ đọc; sandbox còn gắn :ro
        for dirpath, _dirs, files in os.walk(dest):
            for name in files:
                os.chmod(Path(dirpath) / name, 0o444)
    return "sha256:" + digest.hexdigest(), copied, skipped


def prepare_workspace(
    code_root: Path,
    dest_dir: Path,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    expected_commit: str | None,
) -> Workspace:
    """Xác minh commit rồi dựng (hoặc dùng lại) bản sao phạm vi trong `dest_dir/repo`."""
    marker = dest_dir / "workspace.json"
    if marker.is_file():
        return Workspace(**json.loads(marker.read_text(encoding="utf-8")))
    if not code_root.is_dir():
        raise WorkspaceError(
            f"không có kho mã ở {code_root}; clone SUT rồi checkout đúng commit, truyền bằng --code-root"
        )
    head = git_head(code_root)
    if expected_commit is not None:
        if head is None:
            raise WorkspaceError(f"không xác minh được commit ở {code_root} (không phải kho git hoặc HEAD lạ)")
        if head != expected_commit:
            raise WorkspaceError(f"kho mã đang ở {head}, adapter yêu cầu {expected_commit}")
    snapshot, files, skipped = stage_scope(code_root, include, exclude, dest_dir / "repo")
    if files == 0:
        raise WorkspaceError(f"code_scope {include} không khớp tệp nào trong {code_root}")
    ws = Workspace(
        source=str(code_root.resolve()),
        root=str((dest_dir / "repo").resolve()),
        commit=head,
        snapshot=snapshot,
        files=files,
        skipped_symlinks=skipped,
    )
    marker.write_text(json.dumps(asdict(ws), ensure_ascii=False, indent=2), encoding="utf-8")
    return ws

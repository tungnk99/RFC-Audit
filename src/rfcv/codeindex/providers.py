"""Factory `(manifest, config) -> provider` đăng ký vào registry (`rfcv.builtin`).

Chỉ mục mã:
- `treesitter`: dựng chỉ mục trong container `code-indexer` (không mạng, kho mã chỉ đọc, chỉ /out ghi được).
- `treesitter-local`: dựng chỉ mục ngay trong tiến trình harness (phát triển; cần `pip install 'rfcv[codeindex]'`).
Bộ chạy lệnh:
- `docker`: container `code-index-worker` cho mỗi lần chạy.
- `local-unsandboxed`: chạy trên máy harness, chỉ khi RFCV_ALLOW_UNSANDBOXED_EXECUTOR=1.

Cả hai dùng chung một bản sao phạm vi `<run_dir>/<run_id>/code/repo` (dựng một lần, kèm xác minh commit), nên đường
dẫn agent thấy qua công cụ cấu trúc và qua explore là một.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from rfcv.codeindex.executors import DockerExecutor, LocalExecutor, image_id
from rfcv.codeindex.sqlite_index import SqliteCodeIndex
from rfcv.codeindex.workspace import Workspace, WorkspaceError, prepare_workspace

INDEXER_IMAGE = os.environ.get("RFCV_CODE_INDEXER_IMAGE", "rfcv/code-indexer:latest")
WORKER_IMAGE = os.environ.get("RFCV_CODE_WORKER_IMAGE", "rfcv/code-index-worker:latest")
DOCKER = os.environ.get("RFCV_DOCKER", "docker")
ALLOW_LOCAL = "RFCV_ALLOW_UNSANDBOXED_EXECUTOR"


def _code_dir(config: Any) -> Path:
    if not getattr(config, "run_id", None):
        raise WorkspaceError("cần run_id trước khi dựng bản sao kho mã")
    return Path(config.run_dir) / str(config.run_id) / "code"


def workspace(manifest: Any, config: Any) -> Workspace:
    code_dir = _code_dir(config)
    code_root = Path(config.code_root) if config.code_root is not None else code_dir.parent / "repo"
    default_exclude = ("**/*.pem", "**/*.key", "**/*.p12", "**/.git/**")
    return prepare_workspace(
        code_root,
        code_dir,
        tuple(manifest.code_scope.include),
        tuple(manifest.code_scope.exclude) or default_exclude,
        getattr(manifest.sut, "commit", None),
    )


class WorkspaceIndex(SqliteCodeIndex):
    """Chỉ mục kèm thông tin bản sao, để bản kê lần chạy ghi đủ commit, digest bản sao và phiên bản công cụ."""

    def __init__(self, path: Path, ws: Workspace, extra: dict[str, str] | None = None) -> None:
        super().__init__(path)
        self.workspace = ws
        self._extra = extra or {}

    def manifest_entries(self) -> dict[str, str]:
        return {**super().manifest_entries(), **self.workspace.manifest_entries(), **self._extra}


def treesitter_local(manifest: Any, config: Any) -> WorkspaceIndex:
    from rfcv.codeindex.builder import build_index

    ws = workspace(manifest, config)
    path = _code_dir(config) / "index.db"
    if not path.is_file():
        build_index(ws.root_path, path)
    return WorkspaceIndex(path, ws, {"code:indexer": "local"})


def indexer_args(ws: Workspace, out_dir: Path, image: str = INDEXER_IMAGE) -> list[str]:
    return [
        DOCKER, "run", "--rm",
        "--network", "none",
        "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "64", "--memory", "2g", "--cpus", "2",
        "--user", "65532:65532",
        "--mount", f"type=bind,source={ws.root_path},target=/repo,readonly",
        "--mount", f"type=bind,source={out_dir.resolve()},target=/out",
        image, "python", "-m", "rfcv.codeindex", "build", "--root", "/repo", "--out", "/out/index.db",
    ]  # fmt: skip


def treesitter_sandboxed(manifest: Any, config: Any) -> WorkspaceIndex:
    ws = workspace(manifest, config)
    code_dir = _code_dir(config)
    path = code_dir / "index.db"
    if not path.is_file():
        out_dir = code_dir / "indexer-out"
        out_dir.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            out_dir.chmod(0o777)  # user 65532 trong container cần ghi được; chỉ thư mục này
        res = subprocess.run(indexer_args(ws, out_dir), capture_output=True, text=True, timeout=3600, check=False)
        if res.returncode != 0 or not (out_dir / "index.db").is_file():
            raise WorkspaceError(f"dựng chỉ mục trong sandbox thất bại: {res.stderr[-1000:]}")
        shutil.move(str(out_dir / "index.db"), path)
        shutil.rmtree(out_dir, ignore_errors=True)
    return WorkspaceIndex(path, ws, {"image:code-indexer": image_id(INDEXER_IMAGE, DOCKER)})


def docker_executor(manifest: Any, config: Any) -> DockerExecutor:
    ws = workspace(manifest, config)
    return DockerExecutor(ws.root_path, WORKER_IMAGE, run_id=str(config.run_id), docker=DOCKER)


def local_executor(manifest: Any, config: Any) -> LocalExecutor:
    if os.environ.get(ALLOW_LOCAL) != "1":
        raise WorkspaceError(
            f"bộ chạy 'local-unsandboxed' chạy lệnh trên máy harness, không có sandbox; đặt {ALLOW_LOCAL}=1 nếu chỉ "
            "đang phát triển, còn thực nghiệm thì dùng --executor docker"
        )
    return LocalExecutor(workspace(manifest, config).root_path)

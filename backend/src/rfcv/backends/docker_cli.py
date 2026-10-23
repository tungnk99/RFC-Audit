"""Gọi `docker` bằng argv (không qua shell), có thời hạn, truyền stdin dạng BYTES.

Dùng chung cho bộ chạy SUT và backend kiểm thử. Hàm chạy lệnh là điểm tiêm duy nhất, nên test không cần Docker:
truyền một `Exec` giả vào `DockerSutLauncher` và `TlsfuzzerBackend`.

Stdin là bytes vì ở chế độ văn bản Windows đổi `\\n` thành `\\r\\n`, làm hỏng mọi thứ đọc theo dòng trong container.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

DOCKER = os.environ.get("RFCV_DOCKER", "docker")


@dataclass(frozen=True)
class ExecResult:
    returncode: int
    stdout: bytes = b""
    stderr: bytes = b""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def text(self) -> str:
        return self.stdout.decode("utf-8", "replace")


class DockerError(RuntimeError):
    """Lệnh docker thất bại hoặc quá hạn."""


# (argv đầy đủ gồm cả tên chương trình, stdin, thời hạn giây) -> kết quả
Exec = Callable[[Sequence[str], bytes | None, float], Awaitable[ExecResult]]


async def run_process(argv: Sequence[str], stdin: bytes | None = None, timeout: float = 60.0) -> ExecResult:
    """Chạy một tiến trình bằng execve; quá hạn thì giết và báo `DockerError`."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin), timeout=timeout)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise DockerError(f"quá {timeout:.0f}s: {' '.join(argv[:4])} …") from exc
    return ExecResult(proc.returncode if proc.returncode is not None else -1, out, err)


class DockerCli:
    def __init__(self, execute: Exec = run_process, docker: str = DOCKER) -> None:
        self._execute = execute
        self.docker = docker

    async def __call__(self, *args: str, stdin: bytes | None = None, timeout: float = 60.0) -> ExecResult:
        return await self._execute([self.docker, *args], stdin, timeout)

    async def check(self, *args: str, stdin: bytes | None = None, timeout: float = 60.0) -> ExecResult:
        """Như gọi thường nhưng mã thoát khác 0 là `DockerError` (kèm đoạn cuối stderr)."""
        res = await self(*args, stdin=stdin, timeout=timeout)
        if not res.ok:
            tail = res.stderr.decode("utf-8", "replace").strip()[-300:]
            raise DockerError(f"docker {args[0]} thất bại (mã {res.returncode}): {tail}")
        return res

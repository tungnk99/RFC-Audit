"""Bộ chạy lệnh cho explore và search_text (tài liệu khám phá mã, mục 4.1 và 5).

Lệnh đến đây đã qua `explore_policy.validate` (hoặc do Code gate tự dựng) và ở dạng argv cho từng đoạn ống dẫn.
Mỗi đoạn chạy bằng execve (asyncio.create_subprocess_exec), không qua shell; ống dẫn do harness nối: đầu ra đoạn trước
là stdin của đoạn sau. Đầu ra bị chặn theo byte và thời gian.

- `DockerExecutor`: một container `code-index-worker` cho mỗi lần chạy, gắn bản sao phạm vi chỉ đọc ở /repo,
  `--network none --read-only --cap-drop ALL --security-opt no-new-privileges`, user không phải root, giới hạn CPU,
  bộ nhớ, số tiến trình; mỗi lệnh chạy bằng `docker exec … timeout -s KILL 10 <argv>`; huỷ container khi đóng.
- `LocalExecutor`: chạy trên máy harness, CHỈ cho phát triển và kiểm thử (không thoả Bảng 6); factory đòi bật biến môi
  trường RFCV_ALLOW_UNSANDBOXED_EXECUTOR=1.
"""

from __future__ import annotations

import asyncio
import contextlib
import subprocess
import uuid
from pathlib import Path

from rfcv.gates.code_gate import EXECUTOR_NOTE, MAX_BYTES

FINAL_CAP = 4 * MAX_BYTES  # đủ để Code gate tự cắt hoặc từ chối OUTPUT_TOO_LARGE
STAGE_CAP = 4 * 1024 * 1024  # đầu ra trung gian của một đoạn ống dẫn
STDERR_CAP = 2048
# Mã thoát "không có kết quả" của công cụ tìm kiếm: không phải lỗi.
_NO_MATCH = {"rg": 1, "grep": 1, "sg": 1}


class ExecutorError(RuntimeError):
    pass


async def _read_capped(stream: asyncio.StreamReader, cap: int) -> tuple[bytes, bool]:
    buf = bytearray()
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            return bytes(buf), False
        buf += chunk
        if len(buf) > cap:
            return bytes(buf[: cap + 1]), True


async def _drain(stream: asyncio.StreamReader, cap: int) -> bytes:
    buf = bytearray()
    while chunk := await stream.read(65536):
        if len(buf) < cap:
            buf += chunk[: cap - len(buf)]
    return bytes(buf)


async def _stage(argv: list[str], data: bytes | None, cap: int, cwd: Path | None) -> tuple[int, bytes, bytes, bool]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE if data is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd) if cwd is not None else None,
    )

    async def feed() -> None:
        if data is None or proc.stdin is None:
            return
        try:
            proc.stdin.write(data)
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            proc.stdin.close()

    assert proc.stdout is not None and proc.stderr is not None
    try:
        feeder = asyncio.create_task(feed())
        err_task = asyncio.create_task(_drain(proc.stderr, STDERR_CAP))
        out, over = await _read_capped(proc.stdout, cap)
        if over:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
        code = await proc.wait()
        err = await err_task
        await feeder
    except BaseException:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()
        raise
    return code, out, err, over


async def run_pipeline(
    segments: list[list[str]],
    timeout_s: float,
    *,
    prefix: list[str] | None = None,
    cwd: Path | None = None,
) -> str:
    """Chạy các đoạn nối tiếp, đầu ra đoạn trước là stdin đoạn sau. `prefix` đặt trước argv (ví dụ docker exec …)."""
    data: bytes | None = None
    try:
        async with asyncio.timeout(timeout_s):
            for i, seg in enumerate(segments):
                last = i == len(segments) - 1
                argv = [*(prefix or []), *seg]
                code, out, err, over = await _stage(argv, data, FINAL_CAP if last else STAGE_CAP, cwd)
                if over and not last:
                    return f"{EXECUTOR_NOTE}đầu ra trung gian của '{seg[0]}' quá lớn; thu hẹp lệnh"
                if code in (124, 137) and prefix:
                    return f"{EXECUTOR_NOTE}quá thời gian {int(timeout_s)} giây; thu hẹp lệnh"
                if code != 0 and not over and code != _NO_MATCH.get(seg[0], -1):
                    msg = err.decode("utf-8", errors="replace").strip()[:500]
                    return f"{EXECUTOR_NOTE}lệnh '{seg[0]}' lỗi (mã {code}): {msg}"
                data = out
    except TimeoutError:
        return f"{EXECUTOR_NOTE}quá thời gian {int(timeout_s)} giây; thu hẹp lệnh"
    return (data or b"").decode("utf-8", errors="replace")


class DockerExecutor:
    """Một container code-index-worker cho mỗi lần chạy; mọi lệnh chạy bên trong bằng docker exec (argv)."""

    def __init__(
        self,
        root: Path,
        image: str,
        *,
        run_id: str = "",
        docker: str = "docker",
        cpus: str = "1",
        memory: str = "512m",
        pids: int = 64,
    ) -> None:
        self.root = root.resolve()
        self.image = image
        self._docker = docker
        self._name = f"rfcv-code-{run_id or 'run'}-{uuid.uuid4().hex[:8]}"
        self._limits = (cpus, memory, pids)
        self._cid: str | None = None
        self._lock = asyncio.Lock()

    def run_args(self) -> list[str]:
        cpus, memory, pids = self._limits
        return [
            self._docker, "run", "-d", "--rm", "--name", self._name,
            "--network", "none",
            "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", str(pids), "--memory", memory, "--cpus", cpus,
            "--user", "65532:65532",
            "--mount", f"type=bind,source={self.root},target=/repo,readonly",
            "-w", "/repo",
            "--entrypoint", "sleep",
            self.image, "infinity",
        ]  # fmt: skip

    async def _ensure(self) -> str:
        async with self._lock:
            if self._cid is None:
                proc = await asyncio.create_subprocess_exec(
                    *self.run_args(), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                out, err = await proc.communicate()
                if proc.returncode != 0:
                    raise ExecutorError(f"không khởi động được sandbox: {err.decode(errors='replace')[:500]}")
                self._cid = out.decode().strip()
            return self._cid

    async def run(self, segments: list[list[str]], timeout_s: float) -> str:
        cid = await self._ensure()
        prefix = [self._docker, "exec", "-i", "-w", "/repo", cid, "timeout", "-s", "KILL", str(int(timeout_s))]
        return await run_pipeline(segments, timeout_s + 5, prefix=prefix)

    def manifest_entries(self) -> dict[str, str]:
        return {"image:code-index-worker": image_id(self.image, self._docker)}

    def close(self) -> None:
        if self._cid is not None:
            subprocess.run([self._docker, "rm", "-f", self._cid], capture_output=True, timeout=60, check=False)
            self._cid = None


class LocalExecutor:
    """Chạy lệnh đã kiểm tra ngay trên máy harness, cwd là bản sao phạm vi. Không có cách ly: chỉ dùng khi phát triển."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    async def run(self, segments: list[list[str]], timeout_s: float) -> str:
        try:
            return await run_pipeline(segments, timeout_s, cwd=self.root)
        except FileNotFoundError as exc:
            return f"{EXECUTOR_NOTE}không có chương trình trên máy: {exc.filename}"

    def manifest_entries(self) -> dict[str, str]:
        return {"executor": "local-unsandboxed"}


def image_id(image: str, docker: str = "docker") -> str:
    res = subprocess.run(
        [docker, "image", "inspect", "--format", "{{.Id}}", image],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return res.stdout.strip() if res.returncode == 0 else f"unknown:{image}"

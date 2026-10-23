"""Bộ chạy SUT thật trong Docker (SutLauncher): mỗi ca một container mới, không mạng, hạ quyền, tự huỷ (`--rm`) ngay sau ca.

Client kiểm thử chạy BÊN TRONG cùng container (image có sẵn tlslite-ng + tlsfuzzer ghim commit), nên container không cần mạng
ngoài: server nghe 127.0.0.1:4433 và `docker exec` chạy client. Quy ước: `Endpoint.host` là TÊN CONTAINER.

Ràng buộc an toàn (thiết kế adapter, Bảng 12): `--network none`, `--cap-drop ALL`, `no-new-privileges`, hệ thống tệp chỉ đọc,
giới hạn tiến trình/bộ nhớ/CPU, người dùng không phải root (do image đặt `USER`).
Đa dạng môi trường (M7): `environment` đổi tên máy. KHÔNG đổi đồng hồ (cần libfaketime hoặc VM), đó là hạn chế đã ghi nhận.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from rfcv.backends.docker_cli import DockerCli, DockerError
from rfcv.domains.rfc_protocol.sandbox.backend import Endpoint

PORT = 4433
HEX_PORT = f"{PORT:04X}"  # /proc/net/tcp ghi cổng dạng hex; trạng thái 0A = LISTEN
LISTENING = f"grep -qE ':{HEX_PORT} .* 0A ' /proc/net/tcp /proc/net/tcp6"
SERVER_LOG = "/tmp/server.log"
SERVER_EXIT = "/tmp/server.exit"  # mã thoát của server (có tệp = server đã thoát)
# Chạy server như tiến trình RIÊNG (không phải PID 1): server ví dụ của wolfSSL thoát sau mỗi lỗi, nếu là PID 1 thì container
# chết và `docker exec` của client bị giết trước khi đọc được cảnh báo. Mã thoát ≥128 (trừ 137/143 do ta dừng) là sập.
SERVER_WRAPPER = f'"$@" >{SERVER_LOG} 2>&1; echo $? >{SERVER_EXIT}'


class LauncherError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServerSpec:
    """Cách khởi chạy server của một cài đặt: image và lệnh (argv), tuỳ chọn kiểm tra commit trong image."""

    image: str
    command: tuple[str, ...]
    workdir: str | None = None
    rev_file: str | None = None  # tệp trong image ghi commit đã dựng (ví dụ /sut/.rev)
    expect_rev: str | None = None  # commit mà adapter yêu cầu; lệch thì từ chối chạy (ràng buộc C3)


WOLFSSL_COMMAND = ("./examples/server/server", "-v", "4", "-d", "-g", "-i", "-p", str(PORT))
OPENSSL_COMMAND = (
    "openssl", "s_server", "-accept", str(PORT), "-cert", "/ref/cert.pem", "-key", "/ref/key.pem", "-tls1_3", "-www",
)  # fmt: skip
GNUTLS_COMMAND = (
    "gnutls-serv", "--port", str(PORT), "--x509certfile", "/ref/cert.pem", "--x509keyfile", "/ref/key.pem",
    "--priority", "NORMAL:-VERS-ALL:+VERS-TLS1.3", "--disable-client-cert", "--http",
)  # fmt: skip


def default_specs(sut_commit: str | None = None, sut_image: str | None = None) -> dict[str, ServerSpec]:
    """Bảng cài đặt → server. Image wolfSSL gắn thẻ theo 12 ký tự đầu của commit (xem eval/README.md)."""
    image = sut_image or (f"rfcv/sut-wolfssl:{sut_commit[:12]}" if sut_commit else "rfcv/sut-wolfssl:head")
    return {
        "wolfssl": ServerSpec(image, WOLFSSL_COMMAND, "/sut", "/sut/.rev", sut_commit),
        "openssl": ServerSpec("rfcv/ref-openssl:latest", OPENSSL_COMMAND),
        "gnutls": ServerSpec("rfcv/ref-gnutls:latest", GNUTLS_COMMAND),
    }


def hardening(environment: int) -> list[str]:
    return [
        "--network", "none",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "128",
        "--memory", "512m",
        "--cpus", "1",
        "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
        "--hostname", f"rfcv-env{environment}-{uuid.uuid4().hex[:4]}",
    ]  # fmt: skip


@dataclass
class DockerSutLauncher:
    specs: Mapping[str, ServerSpec]
    cli: DockerCli = field(default_factory=DockerCli)
    ready_timeout_s: float = 15.0
    poll_s: float = 0.15
    _verified: set[str] = field(default_factory=set[str])

    def start(self, impl: str, *, coverage: bool, environment: int) -> AbstractAsyncContextManager[Endpoint]:
        # `coverage` bị bỏ qua có chủ đích: image chưa dựng kèm đo độ phủ (nhãn tối đa BEHAVIORAL).
        return self._session(impl, environment)

    @asynccontextmanager
    async def _session(self, impl: str, environment: int) -> AsyncGenerator[Endpoint]:
        spec = self.specs.get(impl)
        if spec is None:
            raise LauncherError(f"không biết cài đặt '{impl}'; có: {sorted(self.specs)}")
        name = f"rfcv-{impl}-{uuid.uuid4().hex[:10]}"
        argv = ["run", "-d", "--rm", "--name", name, *hardening(environment)]
        if spec.workdir:
            argv += ["-w", spec.workdir]
        await self.cli.check(*argv, spec.image, "sleep", "infinity", timeout=60)
        try:
            await self.cli.check("exec", "-d", name, "sh", "-c", SERVER_WRAPPER, "sh", *spec.command, timeout=30)
            await self._wait_ready(name)
            await self._verify_rev(name, spec)
            yield Endpoint(impl, name, PORT)
        finally:
            # `--rm` ở lệnh run: Docker tự huỷ container khi dừng, nên không cần lệnh xoá nào.
            await self.cli("stop", "-t", "1", name, timeout=30)

    async def _wait_ready(self, name: str) -> None:
        loops = max(1, int(self.ready_timeout_s / self.poll_s))
        for _ in range(loops):
            res = await self.cli("exec", name, "sh", "-c", LISTENING, timeout=15)
            if res.ok:
                return
            if await self._exited(name):
                raise LauncherError(f"{name}: server thoát trước khi sẵn sàng\n{await self._logs(name)}")
            await asyncio.sleep(self.poll_s)
        raise LauncherError(
            f"{name}: server không nghe cổng {PORT} sau {self.ready_timeout_s:.0f}s\n{await self._logs(name)}"
        )

    async def _verify_rev(self, name: str, spec: ServerSpec) -> None:
        """Image phải đúng commit mà adapter yêu cầu (kiểm một lần cho mỗi image)."""
        if not (spec.expect_rev and spec.rev_file) or spec.image in self._verified:
            return
        res = await self.cli.check("exec", name, "cat", spec.rev_file, timeout=15)
        rev = res.text().strip()
        if rev != spec.expect_rev:
            raise LauncherError(f"image {spec.image} ở commit {rev[:12]}, adapter yêu cầu {spec.expect_rev[:12]}")
        self._verified.add(spec.image)

    async def _exited(self, name: str) -> bool:
        res = await self.cli("exec", name, "test", "-e", SERVER_EXIT, timeout=15)
        return res.ok  # có tệp mã thoát nghĩa là server đã thoát

    async def _logs(self, name: str) -> str:
        res = await self.cli("exec", name, "tail", "-c", "600", SERVER_LOG, timeout=15)
        return (res.stdout + res.stderr).decode("utf-8", "replace")


def launcher_factory(manifest: Any, config: Any) -> DockerSutLauncher:
    """Nhà máy đăng ký ở `rfcv.builtin`: commit lấy từ adapter (`sut.commit`), image có thể ghi đè bằng biến môi trường."""
    import os

    commit = getattr(getattr(manifest, "sut", None), "commit", None)
    return DockerSutLauncher(default_specs(commit, os.environ.get("RFCV_SUT_IMAGE")))


__all__ = ["DockerError", "DockerSutLauncher", "LauncherError", "ServerSpec", "default_specs", "launcher_factory"]

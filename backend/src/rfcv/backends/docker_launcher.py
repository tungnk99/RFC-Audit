"""Bộ chạy SUT thật trong Docker (SutLauncher): mỗi ca một container mới, không mạng, hạ quyền, tự huỷ (`--rm`) ngay sau ca.

Client kiểm thử chạy BÊN TRONG cùng container (image có sẵn tlslite-ng + tlsfuzzer ghim commit), nên container không cần mạng
ngoài: server nghe 127.0.0.1:4433 và `docker exec` chạy client. Quy ước: `Endpoint.host` là TÊN CONTAINER.

Ràng buộc an toàn (thiết kế adapter, Bảng 12): `--network none`, `--cap-drop ALL`, `no-new-privileges`, hệ thống tệp chỉ đọc,
giới hạn tiến trình/bộ nhớ/CPU, người dùng không phải root (do image đặt `USER`).
Đa dạng môi trường (M7): `environment` đổi tên máy. KHÔNG đổi đồng hồ (cần libfaketime hoặc VM), đó là hạn chế đã ghi nhận.
"""

from __future__ import annotations

import asyncio
import shlex
import uuid
from collections.abc import AsyncGenerator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml

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
    port: int = PORT
    udp: bool = False


WOLFSSL_COMMAND = ("./examples/server/server", "-v", "4", "-d", "-g", "-i", "-p", str(PORT))
OPENSSL_COMMAND = (
    "openssl", "s_server", "-accept", str(PORT), "-cert", "/ref/cert.pem", "-key", "/ref/key.pem", "-tls1_3", "-www",
)  # fmt: skip
GNUTLS_COMMAND = (
    "gnutls-serv", "--port", str(PORT), "--x509certfile", "/ref/cert.pem", "--x509keyfile", "/ref/key.pem",
    "--priority", "NORMAL:-VERS-ALL:+VERS-TLS1.3", "--disable-client-cert", "--http",
)  # fmt: skip


OPENSSL_SUT_COMMAND = (
    "/sut/openssl", "s_server", "-accept", str(PORT), "-cert", "/ref/cert.pem", "-key", "/ref/key.pem", "-tls1_3", "-www",
)  # fmt: skip
NGHTTP2_COMMAND = ("/sut/nghttpd", "--no-tls", "-d", "/tmp", "8080")
KNOT_COMMAND = ("/sut/knotd", "-c", "/sut/knot.conf")
DNSMASQ_COMMAND = ("/sut/dnsmasq", "--no-daemon", "--port=5353", "--no-resolv", "--address=/example.test/127.0.0.1")
DROPBEAR_COMMAND = ("/sut/dropbear", "-F", "-E", "-R", "-p", "127.0.0.1:2222")
NGTCP2_COMMAND = ("/sut/qtlsserver", "127.0.0.1", "4433", "/ref/key.pem", "/ref/cert.pem")


def default_specs(
    sut_commit: str | None = None, sut_image: str | None = None, sut_impl: str = "wolfssl"
) -> dict[str, ServerSpec]:
    """Bảng cài đặt → server. Image SUT gắn thẻ theo 12 ký tự đầu của commit (xem eval/README.md).

    Hỗ trợ đầy đủ 5 giao thức: TLS 1.3 (`wolfssl`, `openssl`, `gnutls`), HTTP/2 (`nghttp2`),
    DNS (`dnsmasq`/`knot`), SSH (`dropbear`/`openssh`), QUIC (`ngtcp2`)."""
    specs = {
        "wolfssl": ServerSpec(
            sut_image or (f"rfcv/sut-wolfssl:{sut_commit[:12]}" if sut_commit else "rfcv/sut-wolfssl:head"),
            WOLFSSL_COMMAND, "/sut", "/sut/.rev", sut_commit,
        ),
        "openssl": ServerSpec("rfcv/ref-openssl:latest", OPENSSL_COMMAND),
        "gnutls": ServerSpec("rfcv/ref-gnutls:latest", GNUTLS_COMMAND),
        "nghttp2": ServerSpec(
            sut_image if sut_impl == "nghttp2" and sut_image else (
                f"rfcv/sut-nghttp2:{sut_commit[:12]}" if sut_impl == "nghttp2" and sut_commit else "rfcv/sut-nghttp2:head"
            ),
            NGHTTP2_COMMAND, "/sut", "/sut/.rev", sut_commit if sut_impl == "nghttp2" else None, port=8080,
        ),
        "nghttp2-ref": ServerSpec("rfcv/sut-nghttp2:head", NGHTTP2_COMMAND, "/sut", "/sut/.rev", None, port=8080),
        "knot": ServerSpec(
            sut_image if sut_impl == "knot" and sut_image else (
                f"rfcv/sut-knot:{sut_commit[:12]}" if sut_impl == "knot" and sut_commit else "rfcv/sut-knot:head"
            ),
            KNOT_COMMAND, "/sut", "/sut/.rev", sut_commit if sut_impl == "knot" else None, port=5353, udp=True,
        ),
        "knot-ref": ServerSpec("rfcv/sut-knot:head", KNOT_COMMAND, "/sut", "/sut/.rev", None, port=5353, udp=True),
        "dnsmasq": ServerSpec(
            sut_image if sut_impl == "dnsmasq" and sut_image else (
                f"rfcv/sut-dnsmasq:{sut_commit[:12]}" if sut_impl == "dnsmasq" and sut_commit else "rfcv/sut-dnsmasq:head"
            ),
            DNSMASQ_COMMAND, "/sut", "/sut/.rev", sut_commit if sut_impl == "dnsmasq" else None, port=5353, udp=True,
        ),
        "dnsmasq-ref": ServerSpec("rfcv/sut-dnsmasq:head", DNSMASQ_COMMAND, "/sut", "/sut/.rev", None, port=5353, udp=True),
        "dropbear": ServerSpec(
            sut_image if sut_impl == "dropbear" and sut_image else (
                f"rfcv/sut-dropbear:{sut_commit[:12]}" if sut_impl == "dropbear" and sut_commit else "rfcv/sut-dropbear:head"
            ),
            DROPBEAR_COMMAND, "/sut", "/sut/.rev", sut_commit if sut_impl == "dropbear" else None, port=2222,
        ),
        "dropbear-ref": ServerSpec("rfcv/sut-dropbear:head", DROPBEAR_COMMAND, "/sut", "/sut/.rev", None, port=2222),
        "ngtcp2": ServerSpec(
            sut_image if sut_impl == "ngtcp2" and sut_image else (
                f"rfcv/sut-ngtcp2:{sut_commit[:12]}" if sut_impl == "ngtcp2" and sut_commit else "rfcv/sut-ngtcp2:head"
            ),
            NGTCP2_COMMAND, "/sut", "/sut/.rev", sut_commit if sut_impl == "ngtcp2" else None, port=4433, udp=True,
        ),
        "ngtcp2-ref": ServerSpec("rfcv/sut-ngtcp2:head", NGTCP2_COMMAND, "/sut", "/sut/.rev", None, port=4433, udp=True),
    }  # fmt: skip
    if sut_impl == "openssl":
        specs["openssl"] = ServerSpec(
            sut_image or (f"rfcv/sut-openssl:{sut_commit[:12]}" if sut_commit else "rfcv/sut-openssl:head"),
            OPENSSL_SUT_COMMAND, "/sut", "/sut/.rev", sut_commit,
        )  # fmt: skip
        specs["wolfssl"] = ServerSpec("rfcv/sut-wolfssl:head", WOLFSSL_COMMAND, "/sut", "/sut/.rev", None)
    return specs


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

    async def identity(self, impl: str) -> str | None:
        """Định danh bất biến của ảnh chạy `impl` (id ảnh docker), để dùng làm khoá bộ nhớ đệm nhân chứng; None nếu không rõ."""
        spec = self.specs.get(impl)
        if spec is None:
            return None
        try:
            res = await self.cli("image", "inspect", "--format", "{{.Id}}", spec.image, timeout=30.0)
        except Exception:
            return None
        return res.stdout.decode("utf-8", "replace").strip() or None if res.ok else None

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
            await self._wait_ready(name, spec)
            await self._verify_rev(name, spec)
            yield Endpoint(impl, name, spec.port)
        finally:
            # `--rm` ở lệnh run: Docker tự huỷ container khi dừng, nên không cần lệnh xoá nào.
            await self.cli("stop", "-t", "1", name, timeout=30)

    async def _wait_ready(self, name: str, spec: ServerSpec) -> None:
        hex_port = f"{spec.port:04X}"
        if spec.udp:
            check_cmd = f"grep -qE ':{hex_port} .* 07 ' /proc/net/udp /proc/net/udp6"
        else:
            check_cmd = f"grep -qE ':{hex_port} .* 0A ' /proc/net/tcp /proc/net/tcp6"
        loops = max(1, int(self.ready_timeout_s / self.poll_s))
        for _ in range(loops):
            res = await self.cli("exec", name, "sh", "-c", check_cmd, timeout=15)
            if res.ok:
                return
            if await self._exited(name):
                raise LauncherError(f"{name}: server thoát trước khi sẵn sàng\n{await self._logs(name)}")
            await asyncio.sleep(self.poll_s)
        raise LauncherError(
            f"{name}: server không nghe cổng {spec.port} sau {self.ready_timeout_s:.0f}s\n{await self._logs(name)}"
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


def specs_from_adapter(
    adapter_dir: Path | None,
    *,
    sut_commit: str | None = None,
    sut_image: str | None = None,
    sut_impl: str = "wolfssl",
) -> dict[str, ServerSpec]:
    """gen-37 (L6 ADD_CAPABILITY — mục A2): Đọc công thức `sut/*.yaml` của adapter để tự dựng `ServerSpec`.

    Thư viện mới chỉ cần khai báo `roles.server.cmd` (hoặc `docker_cmd`), `port`, `image`, `workdir`
    trong `sut/<impl>.yaml` mà không cần sửa `docker_launcher.py`; vẫn giữ `default_specs()` làm nền tương thích ngược.
    """
    specs = default_specs(sut_commit, sut_image, sut_impl)
    if adapter_dir is None:
        return specs
    sut_dir = Path(adapter_dir) / "sut"
    if not sut_dir.is_dir():
        return specs
    for path in sorted(sut_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            continue
        doc = cast("Mapping[str, Any]", raw)
        impl = str(doc.get("implementation") or path.stem).strip()
        if not impl:
            continue
        roles = cast("Mapping[str, Any]", doc.get("roles") or {})
        server = cast("Mapping[str, Any]", roles.get("server") or {})
        raw_cmd = server.get("docker_cmd") or (server.get("cmd") if impl not in specs else None)
        if not raw_cmd:
            continue
        port = int(server.get("port") or PORT)
        lifecycle = cast("Mapping[str, Any]", doc.get("lifecycle") or {})
        ready = cast("Mapping[str, Any]", lifecycle.get("ready_check") or {})
        transport = str(server.get("transport") or "").lower()
        udp = transport == "udp" or str(ready.get("kind") or "").lower() == "udp_query"
        if isinstance(raw_cmd, str):
            argv = tuple(shlex.split(raw_cmd.format(port=port)))
        else:
            argv = tuple(str(tok).format(port=port) for tok in cast("list[Any]", raw_cmd))
        workdir = str(server.get("workdir") or "/sut")
        is_sut = impl == sut_impl
        default_img = f"rfcv/sut-{impl}:{sut_commit[:12]}" if (is_sut and sut_commit) else f"rfcv/sut-{impl}:head"
        image = str(sut_image if (is_sut and sut_image) else (server.get("image") or default_img))
        specs[impl] = ServerSpec(
            image=image,
            command=argv,
            workdir=workdir,
            rev_file="/sut/.rev",
            expect_rev=sut_commit if is_sut else None,
            port=port,
            udp=udp,
        )
        ref_key = f"{impl}-ref"
        if ref_key not in specs or server.get("docker_cmd"):
            ref_img = str(server.get("ref_image") or f"rfcv/sut-{impl}:head")
            specs[ref_key] = ServerSpec(
                image=ref_img,
                command=argv,
                workdir=workdir,
                rev_file="/sut/.rev",
                expect_rev=None,
                port=port,
                udp=udp,
            )
    return specs


def launcher_factory(manifest: Any, config: Any) -> DockerSutLauncher:
    """Nhà máy đăng ký ở `rfcv.builtin`: đọc `sut/*.yaml` của adapter, commit lấy từ `sut.commit`, image có thể ghi đè qua env."""
    import os

    sut = getattr(manifest, "sut", None)
    commit = getattr(sut, "commit", None)
    impl = str(getattr(sut, "repo", "")).rstrip("/").rsplit("/", 1)[-1] or "wolfssl"
    adapter_dir = getattr(config, "adapter_dir", None)
    return DockerSutLauncher(
        specs_from_adapter(
            Path(adapter_dir) if adapter_dir is not None else None,
            sut_commit=commit,
            sut_image=os.environ.get("RFCV_SUT_IMAGE"),
            sut_impl=impl,
        )
    )


__all__ = [
    "DockerError",
    "DockerSutLauncher",
    "LauncherError",
    "ServerSpec",
    "default_specs",
    "launcher_factory",
    "specs_from_adapter",
]

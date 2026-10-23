"""Launcher và backend THẬT cho wolfSSL/tlsfuzzer: logic kiểm bằng `docker` giả (không cần Docker), cộng một nhóm test tích hợp
tự bỏ qua khi máy không có Docker hoặc chưa dựng image."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Sequence
from typing import Any

import pytest

from rfcv.backends.docker_cli import DockerCli, DockerError, ExecResult
from rfcv.backends.docker_launcher import (
    PORT,
    SERVER_EXIT,
    SERVER_LOG,
    DockerSutLauncher,
    LauncherError,
    ServerSpec,
    default_specs,
)
from rfcv.backends.tlsfuzzer import TlsfuzzerBackend
from rfcv.domains.rfc_protocol.sandbox.backend import Endpoint
from rfcv.domains.rfc_protocol.schemas import ScenarioProposal
from rfcv.domains.rfc_protocol.testing import check_backend_contract, check_sut_launcher_contract

COMMIT = "c18833f5206e5a96ab7400c569f830903f0c36c5"
OK = ExecResult(0)


def scenario(**send_args: Any) -> ScenarioProposal:
    args: dict[str, Any] = {"length": "$record.length", "encrypted": True, **send_args}
    return ScenarioProposal.model_validate(
        {
            "requirement_id": "TLS13-0042",
            "reach_state": "connected",
            "steps": [
                {"op": "complete_handshake"},
                {"op": "send_raw_record", "args": args},
                {"op": "expect", "args": {"within_ms": 2000}},
            ],
            "bindings": {"record.length": "from_variant"},
        }
    )


class FakeDocker:
    """Giả `docker`: ghi lại mọi lệnh và trả lời theo lệnh con. Không chạy gì thật."""

    def __init__(
        self,
        result: dict[str, Any] | None = None,
        rev: str = COMMIT,
        server_exit: str | None = None,
        listening: bool = True,
        exited_early: bool = False,
    ) -> None:
        self.calls: list[list[str]] = []
        self.result = (
            result
            if result is not None
            else {
                "trigger_reached": True,
                "alert": "record_overflow",
                "closed": True,
                "t_alert_ms": 20,
                "t_close_ms": 21,
            }
        )
        self.rev, self.server_exit, self.listening, self.exited_early = rev, server_exit, listening, exited_early
        self.stdins: list[bytes | None] = []

    async def __call__(self, argv: Sequence[str], stdin: bytes | None, timeout: float) -> ExecResult:
        self.calls.append(list(argv))
        self.stdins.append(stdin)
        sub, rest = argv[1], list(argv[2:])
        if sub in ("run", "stop"):
            return OK
        if sub == "exec":
            if rest[0] == "-d":
                return OK
            if rest[0] == "-i":  # runner
                if "sanity" in rest[-1]:
                    return ExecResult(0, b'noise\nRFCV_RESULT {"ok": true}\n')
                return ExecResult(0, b"noise\nRFCV_RESULT " + json.dumps(self.result).encode() + b"\n")
            cmd = rest[1:]  # sau tên container
            if cmd[:1] == ["sh"]:  # kiểm tra đang nghe cổng
                return OK if self.listening and not self.exited_early else ExecResult(1)
            if cmd[:2] == ["test", "-e"]:
                return OK if self.exited_early else ExecResult(1)
            if cmd[:2] == ["cat", SERVER_EXIT]:
                return ExecResult(0, self.server_exit.encode()) if self.server_exit is not None else ExecResult(1)
            if cmd[:1] == ["cat"]:
                return ExecResult(0, self.rev.encode())
            if cmd[:1] == ["tail"]:
                return ExecResult(0, b"server log")
        return OK

    def subcommands(self) -> list[str]:
        return [c[1] for c in self.calls]


def launcher(fake: FakeDocker, commit: str | None = COMMIT) -> DockerSutLauncher:
    return DockerSutLauncher(default_specs(commit), cli=DockerCli(fake), ready_timeout_s=1.0, poll_s=0.01)


# ---------------------------------------------------------------- launcher


async def test_container_is_hardened_throwaway_and_cleaned_up() -> None:
    fake = FakeDocker()
    async with launcher(fake).start("wolfssl", coverage=False, environment=1) as ep:
        assert ep == Endpoint("wolfssl", ep.host, PORT) and ep.host.startswith("rfcv-wolfssl-")
    run = next(c for c in fake.calls if c[1] == "run")
    flags = " ".join(run)
    for need in ("-d --rm", "--network none", "--cap-drop ALL", "no-new-privileges", "--read-only", "--pids-limit 128"):
        assert need in flags, need
    assert "--hostname rfcv-env1-" in flags and run[-3:] == ["rfcv/sut-wolfssl:c18833f5206e", "sleep", "infinity"]
    assert fake.calls[-1][1:3] == ["stop", "-t"], "container phải được dừng (Docker tự huỷ nhờ --rm)"
    assert "rm" not in fake.subcommands(), "không dùng lệnh xoá: chỉ dừng container tự huỷ"


async def test_server_runs_as_a_separate_process_not_pid_1() -> None:
    """Server wolfSSL thoát sau mỗi lỗi; nếu là PID 1 thì container chết và client bị giết trước khi đọc cảnh báo."""
    fake = FakeDocker()
    async with launcher(fake).start("wolfssl", coverage=False, environment=0):
        pass
    detached = next(c for c in fake.calls if c[1:3] == ["exec", "-d"])
    assert (
        "./examples/server/server" in detached
        and SERVER_EXIT in " ".join(detached)
        and SERVER_LOG in " ".join(detached)
    )


async def test_environment_changes_the_hostname() -> None:
    names: list[str] = []
    for env in (0, 1):
        fake = FakeDocker()
        async with launcher(fake).start("wolfssl", coverage=False, environment=env):
            pass
        names.append(
            next(c for c in fake.calls if c[1] == "run")[
                next(c for c in fake.calls if c[1] == "run").index("--hostname") + 1
            ]
        )
    assert names[0].startswith("rfcv-env0-") and names[1].startswith("rfcv-env1-") and names[0] != names[1]


async def test_unknown_implementation_is_rejected() -> None:
    with pytest.raises(LauncherError, match="không biết cài đặt"):
        async with launcher(FakeDocker()).start("nginx", coverage=False, environment=0):
            pass


async def test_image_at_the_wrong_commit_is_refused() -> None:
    """Ràng buộc C3: image phải đúng commit adapter yêu cầu."""
    fake = FakeDocker(rev="0" * 40)
    with pytest.raises(LauncherError, match="adapter yêu cầu"):
        async with launcher(fake).start("wolfssl", coverage=False, environment=0):
            pass
    assert fake.calls[-1][1] == "stop", "vẫn phải dọn container khi từ chối"


async def test_server_that_never_listens_is_reported_with_its_log() -> None:
    with pytest.raises(LauncherError, match=r"không nghe cổng|thoát trước"):
        async with launcher(FakeDocker(listening=False)).start("wolfssl", coverage=False, environment=0):
            pass
    with pytest.raises(LauncherError, match="thoát trước khi sẵn sàng"):
        async with launcher(FakeDocker(listening=False, exited_early=True)).start(
            "wolfssl", coverage=False, environment=0
        ):
            pass


def test_reference_implementations_have_their_own_images() -> None:
    specs = default_specs(COMMIT)
    assert specs["openssl"].image == "rfcv/ref-openssl:latest" and "s_server" in specs["openssl"].command
    assert specs["gnutls"].image == "rfcv/ref-gnutls:latest" and "--disable-client-cert" in specs["gnutls"].command
    assert specs["wolfssl"].expect_rev == COMMIT and ServerSpec  # image wolfSSL gắn thẻ theo commit


# ---------------------------------------------------------------- backend


def test_validate_accepts_the_canonical_scenario_and_rejects_the_unsupported() -> None:
    backend = TlsfuzzerBackend(DockerCli(FakeDocker()))
    assert backend.validate(scenario()).ok
    assert not backend.validate(scenario(encrypted=False)).ok
    assert not backend.validate(scenario(content_type="handshake")).ok
    no_len = ScenarioProposal.model_validate(
        {"requirement_id": "R", "reach_state": "connected", "steps": [{"op": "send_raw_record"}, {"op": "expect"}]}
    )
    assert any("length" in e for e in backend.validate(no_len).errors)
    mutate = ScenarioProposal.model_validate(
        {
            "requirement_id": "R",
            "reach_state": "connected",
            "steps": [
                {"op": "mutate", "args": {"field": "x", "op": "set"}},
                {"op": "send_raw_record", "args": {"length": 1}},
                {"op": "expect"},
            ],
        }
    )
    res = backend.validate(mutate)
    assert not res.ok and any("chưa hỗ trợ bước 'mutate'" in e for e in res.errors)


def test_request_substitutes_the_variant_value() -> None:
    req = TlsfuzzerBackend.request(scenario(), {"record.length": 16641}, 4433)
    assert (req["length"], req["within_ms"], req["mode"]) == (16641, 2000, "run")


def test_events_are_normalised_in_adapter_vocabulary_and_ordered() -> None:
    events = TlsfuzzerBackend.events(
        {"alert": "record_overflow", "closed": True, "t_alert_ms": 20, "t_close_ms": 25, "app_data": False}
    )
    assert [(e.name, e.args, e.t_ms) for e in events] == [("send_alert", ("record_overflow",), 20), ("close", (), 25)]
    quiet = TlsfuzzerBackend.events({"alert": None, "closed": False})
    assert quiet == ()
    data = TlsfuzzerBackend.events(
        {"alert": "close_notify", "app_data": True, "closed": True, "t_alert_ms": 0, "t_close_ms": 1}
    )
    assert ("send", ("application_data",)) in [(e.name, e.args) for e in data]


async def test_run_returns_a_normalised_trace_and_ships_the_runner_as_bytes() -> None:
    fake = FakeDocker()
    backend = TlsfuzzerBackend(DockerCli(fake))
    tr = await backend.run(scenario(), {"record.length": 16641}, Endpoint("wolfssl", "c1", PORT), 1)
    assert tr.trigger_reached and tr.observation == {"alert": "record_overflow", "closed": True}
    assert tr.raw_log == b"server log" and tr.sut_alive_after
    shipped = next(s for s in fake.stdins if s)
    assert isinstance(shipped, bytes) and b"RFCV_RESULT" in shipped and b"\r\n" not in shipped


async def test_infrastructure_failure_is_not_reported_as_an_sut_failure() -> None:
    class Broken(FakeDocker):
        async def __call__(self, argv: Sequence[str], stdin: bytes | None, timeout: float) -> ExecResult:
            if argv[1] == "exec" and argv[2] == "-i":
                raise DockerError("quá hạn")
            return await super().__call__(argv, stdin, timeout)

    tr = await TlsfuzzerBackend(DockerCli(Broken())).run(
        scenario(), {"record.length": 16641}, Endpoint("w", "c", PORT), 1
    )
    assert tr.trigger_reached is False and tr.events == ()  # → driver ghi ERROR, không phải FAIL


@pytest.mark.parametrize(
    ("exit_code", "alive"), [(None, True), ("1", True), ("0", True), ("139", False), ("134", False), ("143", True)]
)
async def test_crash_detection_uses_the_server_exit_status(exit_code: str | None, alive: bool) -> None:
    fake = FakeDocker(server_exit=exit_code)
    tr = await TlsfuzzerBackend(DockerCli(fake)).run(scenario(), {"record.length": 16641}, Endpoint("w", "c", PORT), 1)
    assert tr.sut_alive_after is alive


async def test_backend_and_launcher_satisfy_the_plugin_contracts() -> None:
    fake = FakeDocker()
    backend, lau = TlsfuzzerBackend(DockerCli(fake)), launcher(fake)
    assert await check_backend_contract(backend, lau, scenario(), "wolfssl") == []
    assert await check_sut_launcher_contract(lau, "wolfssl") == []


# ---------------------------------------------------------------- tích hợp thật (tự bỏ qua nếu thiếu Docker/image)


def _real_images() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        out = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "rfcv/sut-wolfssl:c18833f5206e" in out


@pytest.mark.skipif(
    not _real_images(), reason="cần Docker đang chạy và image rfcv/sut-wolfssl:<commit> (xem eval/README.md)"
)
async def test_real_wolfssl_fix_rejects_an_oversized_record_with_record_overflow() -> None:
    backend, lau = TlsfuzzerBackend(), DockerSutLauncher(default_specs(COMMIT))
    async with lau.start("wolfssl", coverage=False, environment=0) as ep:
        assert await backend.sanity(ep)
        tr = await backend.run(scenario(), {"record.length": 16641}, ep, 1)
    assert tr.trigger_reached and tr.observation["alert"] == "record_overflow" and tr.observation["closed"] is True

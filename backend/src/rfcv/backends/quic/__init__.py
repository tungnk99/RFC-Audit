"""Backend QUIC: chạy gói QUIC v1 (RFC 9000) qua UDP trong container SUT bằng `docker exec` (runner.py thuần Python stdlib)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rfcv.backends.base import BODIES, EXPECT_ARGS, MUTATIONS, DslBackend
from rfcv.backends.docker_cli import DockerCli, DockerError
from rfcv.backends.docker_launcher import SERVER_EXIT, SERVER_LOG
from rfcv.domains.rfc_protocol.sandbox.backend import Endpoint, EventTrace, ValidationResult
from rfcv.domains.rfc_protocol.sandbox.dsl import DslSpec
from rfcv.domains.rfc_protocol.schemas import ScenarioProposal
from rfcv.domains.rfc_protocol.spec.oracle_compiler import ObservedEvent

DSL = DslSpec(
    ops={
        "connect": frozenset({"version"}),
        "complete_handshake": frozenset({"alpn"}),
        "send_msg": frozenset({"type", "stream_id"}),
        "send_raw_record": frozenset({"packet_type", "datagram_length", "length", "body", "encrypted"}),
        "mutate": frozenset({"field", "op", "value"}),
        "reorder": frozenset({"msgs"}),
        "repeat": frozenset({"msg"}),
        "expect": EXPECT_ARGS,
    },
    values={
        "packet_type": frozenset({"initial", "zero_rtt", "handshake", "retry", "one_rtt"}),
        "type": frozenset(
            {
                "padding",
                "ping",
                "ack",
                "reset_stream",
                "stop_sending",
                "crypto",
                "new_token",
                "stream",
                "max_data",
                "max_stream_data",
                "max_streams",
                "data_blocked",
                "new_connection_id",
                "retire_connection_id",
                "path_challenge",
                "path_response",
                "handshake_done",
            }
        ),
        "body": BODIES,
        "op": MUTATIONS,
    },
    notes={
        "send_raw_record": "một datagram UDP chứa một gói packet_type; datagram_length là kích thước tải UDP sau khi độn",
        "send_msg": "một khung hợp lệ loại type trong gói 1-RTT; trường cần đổi thì dùng mutate ngay trước",
        "mutate": "sửa khung hay gói kế tiếp, ví dụ field new_connection_id.length",
    },
)

SUPPORTED = {"connect", "send_raw_record", "expect"}
RUNNER_SOURCE = Path(__file__).with_name("runner.py")
PYTHON_IN_IMAGE = "python3"
RESULT_PREFIX = "RFCV_RESULT "
DEFAULT_WITHIN_MS = 1500
CRASH_EXIT = 128


def runner_source() -> bytes:
    return RUNNER_SOURCE.read_bytes().replace(b"\r\n", b"\n")


class AioquicBackend(DslBackend):
    name = "aioquic"
    dsl = DSL
    runner = "QUIC v1 UDP runner (stdlib Python)"

    def __init__(self, cli: DockerCli | None = None) -> None:
        self._cli = cli or DockerCli()

    def validate(self, scenario: ScenarioProposal) -> ValidationResult:
        base = super().validate(scenario)
        errors = list(base.errors)
        for step in scenario.steps:
            if step.op not in SUPPORTED:
                errors.append(f"bước `{step.op}` chưa được hỗ trợ bởi QUIC runner")
        return ValidationResult(ok=not errors, errors=tuple(errors))

    async def sanity(self, endpoint: Endpoint) -> bool:
        res = await self._exec(
            endpoint, {"mode": "sanity", "port": endpoint.port, "datagram_length": 1200, "within_ms": 2000}, timeout=8.0
        )
        return bool(res.get("ok"))

    async def run(
        self, scenario: ScenarioProposal, params: dict[str, int | str], endpoint: Endpoint, seed: int
    ) -> EventTrace:
        req = self.translate(scenario, params, endpoint.port)
        timeout = 8.0 + int(req.get("within_ms", DEFAULT_WITHIN_MS)) / 1000.0
        res = await self._exec(endpoint, req, timeout=timeout)
        obs: dict[str, str | bool | int] = {
            "alert": "none",
            "closed": False,
            "discarded": bool(res.get("discarded", False)),
        }
        return EventTrace(
            events=self.events(res),
            trigger_reached=bool(res.get("trigger_reached", False)),
            sut_alive_after=await self._alive(endpoint),
            observation=obs,
            raw_log=await self._server_log(endpoint),
        )

    @staticmethod
    def translate(scenario: ScenarioProposal, params: dict[str, int | str], port: int) -> dict[str, Any]:
        def value(raw: Any) -> Any:
            return params[raw[1:]] if isinstance(raw, str) and raw.startswith("$") else raw

        req: dict[str, Any] = {"mode": "run", "port": port, "datagram_length": 1200, "within_ms": DEFAULT_WITHIN_MS}
        for step in scenario.steps:
            args = {k: value(v) for k, v in step.args.items()}
            if step.op == "send_raw_record":
                if "datagram_length" in args:
                    req["datagram_length"] = int(args["datagram_length"])
                elif "length" in args:
                    req["datagram_length"] = int(args["length"])
            elif step.op == "expect":
                req["within_ms"] = int(args.get("within_ms", args.get("timeout_ms", DEFAULT_WITHIN_MS)))
        return req

    @staticmethod
    def events(res: dict[str, Any]) -> tuple[ObservedEvent, ...]:
        t = int(res.get("t_ms") or 0)
        if res.get("discarded"):
            return (ObservedEvent(name="discard", t_ms=t),)
        if res.get("replied"):
            return (ObservedEvent(name="send", args=(str(res.get("packet_type") or "initial"),), t_ms=t),)
        return ()

    async def _exec(self, endpoint: Endpoint, request: dict[str, Any], timeout: float) -> dict[str, Any]:
        try:
            res = await self._cli(
                "exec", "-i", endpoint.host, PYTHON_IN_IMAGE, "-", json.dumps(request),
                stdin=runner_source(), timeout=timeout + 5,
            )  # fmt: skip
        except DockerError as exc:
            return {"ok": False, "trigger_reached": False, "reason": f"docker: {exc}"[:200]}
        for line in reversed(res.text().splitlines()):
            if line.startswith(RESULT_PREFIX):
                parsed: dict[str, Any] = json.loads(line[len(RESULT_PREFIX) :])
                return parsed
        tail = (res.stdout + res.stderr).decode("utf-8", "replace").strip()[-200:]
        return {"ok": False, "trigger_reached": False, "reason": f"runner không trả kết quả: {tail}"}

    async def _alive(self, endpoint: Endpoint) -> bool:
        try:
            res = await self._cli("exec", endpoint.host, "cat", SERVER_EXIT, timeout=15)
        except DockerError:
            return True
        code = res.text().strip()
        if not res.ok or not code.isdigit():
            return True
        return not (int(code) >= CRASH_EXIT and int(code) not in (137, 143))

    async def _server_log(self, endpoint: Endpoint) -> bytes:
        try:
            res = await self._cli("exec", endpoint.host, "tail", "-c", "65536", SERVER_LOG, timeout=15)
        except DockerError:
            return b""
        return res.stdout if res.ok else b""

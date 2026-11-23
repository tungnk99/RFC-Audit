"""Backend HTTP/2: chạy khung HTTP/2 (h2c) thô trong container SUT qua `docker exec` (runner.py thuần Python stdlib).

`complete_handshake` gửi lời mở đầu kết nối (connection preface) và SETTINGS, chờ SETTINGS của SUT và trao đổi ACK; sau
bước này trạng thái là `connected`. `send_raw_record` là một khung HTTP/2 thô: tiêu đề 9 byte với `length` cho trước,
có thể khác độ dài thân thật. Observation@1: `alert` là mã lỗi trong GOAWAY hoặc RST_STREAM, `closed` là kết nối bị đóng.
"""

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

FRAME_TYPES = frozenset(
    {
        "data",
        "headers",
        "priority",
        "rst_stream",
        "settings",
        "push_promise",
        "ping",
        "goaway",
        "window_update",
        "continuation",
    }
)

DSL = DslSpec(
    ops={
        "connect": frozenset({"tls"}),
        "complete_handshake": frozenset({"settings"}),
        "send_msg": frozenset({"type", "stream_id", "flags"}),
        "send_raw_record": frozenset({"type", "flags", "stream_id", "length", "body"}),
        "mutate": frozenset({"field", "op", "value"}),
        "reorder": frozenset({"msgs"}),
        "repeat": frozenset({"msg"}),
        "expect": EXPECT_ARGS,
    },
    values={"type": FRAME_TYPES, "body": BODIES, "op": MUTATIONS},
    notes={
        "complete_handshake": "lời mở đầu, SETTINGS hai chiều và ACK; trạng thái sau bước này là connected",
        "send_raw_record": "một khung thô; length là giá trị trường Length trong tiêu đề khung (uint24)",
        "send_msg": "một khung hợp lệ của loại type; khung HEADERS mở luồng mới (stream_id lẻ, tăng dần)",
    },
)

SUPPORTED = {"connect", "complete_handshake", "send_raw_record", "send_msg", "expect"}
RUNNER_SOURCE = Path(__file__).with_name("runner.py")
PYTHON_IN_IMAGE = "python3"
RESULT_PREFIX = "RFCV_RESULT "
DEFAULT_WITHIN_MS = 2000
CRASH_EXIT = 128


def runner_source() -> bytes:
    return RUNNER_SOURCE.read_bytes().replace(b"\r\n", b"\n")


class H2specBackend(DslBackend):
    name = "h2spec"
    dsl = DSL
    runner = "HTTP/2 (h2c) raw-frame runner (stdlib Python)"

    def __init__(self, cli: DockerCli | None = None) -> None:
        self._cli = cli or DockerCli()

    def validate(self, scenario: ScenarioProposal) -> ValidationResult:
        base = super().validate(scenario)
        errors = list(base.errors)
        for step in scenario.steps:
            if step.op not in SUPPORTED:
                errors.append(f"bước `{step.op}` chưa được hỗ trợ bởi HTTP/2 runner")
        return ValidationResult(ok=not errors, errors=tuple(errors))

    async def sanity(self, endpoint: Endpoint) -> bool:
        res = await self._exec(endpoint, {"mode": "sanity", "port": endpoint.port, "timeout_s": 5.0}, timeout=10.0)
        return bool(res.get("ok"))

    async def run(
        self, scenario: ScenarioProposal, params: dict[str, int | str], endpoint: Endpoint, seed: int
    ) -> EventTrace:
        req = self.translate(scenario, params, endpoint.port)
        timeout = 10.0 + int(req.get("within_ms", DEFAULT_WITHIN_MS)) / 1000.0
        res = await self._exec(endpoint, req, timeout=timeout)
        events = self.events(res)
        obs: dict[str, str | bool | int] = {"closed": bool(res.get("closed", False))}
        if res.get("alert"):
            obs["alert"] = str(res["alert"])
        else:
            obs["alert"] = "none"
        if res.get("ping_ack"):
            obs["ping_ack"] = True
        return EventTrace(
            events=events,
            trigger_reached=bool(res.get("trigger_reached", False)),
            sut_alive_after=await self._alive(endpoint),
            observation=obs,
            raw_log=await self._server_log(endpoint),
        )

    @staticmethod
    def translate(scenario: ScenarioProposal, params: dict[str, int | str], port: int) -> dict[str, Any]:
        def value(raw: Any) -> Any:
            return params[raw[1:]] if isinstance(raw, str) and raw.startswith("$") else raw

        req: dict[str, Any] = {"mode": "run", "port": port, "within_ms": DEFAULT_WITHIN_MS}
        for step in scenario.steps:
            args = {k: value(v) for k, v in step.args.items()}
            if step.op == "send_raw_record":
                req["frame_type"] = str(args.get("type", "data"))
                req["length"] = int(args["length"])
                if "stream_id" in args:
                    req["stream_id"] = int(args["stream_id"])
                if "flags" in args:
                    req["flags"] = int(args["flags"])
            elif step.op == "send_msg":
                req["frame_type"] = str(args.get("type", "ping"))
                if "stream_id" in args:
                    req["stream_id"] = int(args["stream_id"])
            elif step.op == "expect":
                req["within_ms"] = int(args.get("within_ms", args.get("timeout_ms", DEFAULT_WITHIN_MS)))
        return req

    @staticmethod
    def events(res: dict[str, Any]) -> tuple[ObservedEvent, ...]:
        out: list[ObservedEvent] = []
        if res.get("goaway"):
            out.append(
                ObservedEvent(name="send_goaway", args=(str(res["goaway"]),), t_ms=int(res.get("t_alert_ms") or 0))
            )
        if res.get("rst_stream"):
            out.append(
                ObservedEvent(
                    name="send_rst_stream", args=(str(res["rst_stream"]),), t_ms=int(res.get("t_alert_ms") or 0)
                )
            )
        if res.get("ping_ack"):
            out.append(ObservedEvent(name="send", args=("ping",), t_ms=int(res.get("t_alert_ms") or 0)))
        if res.get("closed"):
            out.append(ObservedEvent(name="close", t_ms=int(res.get("t_close_ms") or 0)))
        return tuple(sorted(out, key=lambda e: e.t_ms))

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

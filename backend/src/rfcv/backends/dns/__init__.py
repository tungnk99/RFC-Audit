"""Backend DNS: dựng và gửi thông điệp DNS/EDNS(0) trong container SUT qua `docker exec` (runner.py thuần Python stdlib).

Không có bắt tay: `connect` chỉ chọn giao vận (UDP hay TCP). `send_msg(type=query)` dựng một truy vấn hợp lệ (có OPT RR
EDNS(0) trừ khi mutate bỏ đi); `mutate` sửa thông điệp kế tiếp, ví dụ `duplicate` OPT RR hay `set` trường `opt.version`.
Quan sát Observation@1: `alert` là RCODE đầy đủ (gồm phần mở rộng trong OPT, ví dụ badvers), `closed` là TCP bị đóng.
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

DSL = DslSpec(
    ops={
        "connect": frozenset({"transport"}),
        "send_msg": frozenset({"type", "qname", "qtype"}),
        "send_raw_record": frozenset({"length", "body", "transport"}),
        "mutate": frozenset({"field", "op", "value"}),
        "repeat": frozenset({"msg"}),
        "expect": EXPECT_ARGS,
    },
    values={
        "transport": frozenset({"udp", "tcp"}),
        "type": frozenset({"query", "notify"}),
        "body": BODIES,
        "op": MUTATIONS,
    },
    notes={
        "connect": "chọn giao vận; DNS không có bắt tay, trạng thái sau bước này là ready",
        "send_msg": "dựng thông điệp hợp lệ (truy vấn có OPT RR EDNS(0)); trường cần đổi thì dùng mutate ngay trước",
        "mutate": "sửa thông điệp kế tiếp: field như opt.version, opt.count, header.opcode, header.flags.rd",
        "send_raw_record": "gửi nguyên một thông điệp DNS thô với độ dài cho trước",
    },
)

SUPPORTED = {"connect", "send_msg", "mutate", "expect"}
RUNNER_SOURCE = Path(__file__).with_name("runner.py")
PYTHON_IN_IMAGE = "python3"
RESULT_PREFIX = "RFCV_RESULT "
DEFAULT_WITHIN_MS = 2000
CRASH_EXIT = 128


def runner_source() -> bytes:
    return RUNNER_SOURCE.read_bytes().replace(b"\r\n", b"\n")


class DnspythonBackend(DslBackend):
    name = "dnspython"
    dsl = DSL
    runner = "DNS/EDNS(0) raw-packet runner (stdlib Python)"

    def __init__(self, cli: DockerCli | None = None) -> None:
        self._cli = cli or DockerCli()

    def validate(self, scenario: ScenarioProposal) -> ValidationResult:
        base = super().validate(scenario)
        errors = list(base.errors)
        for step in scenario.steps:
            if step.op not in SUPPORTED:
                errors.append(f"bước `{step.op}` chưa được hỗ trợ bởi DNS runner")
        return ValidationResult(ok=not errors, errors=tuple(errors))

    async def sanity(self, endpoint: Endpoint) -> bool:
        res = await self._exec(endpoint, {"mode": "sanity", "port": endpoint.port, "within_ms": 2000}, timeout=8.0)
        return bool(res.get("ok"))

    async def run(
        self, scenario: ScenarioProposal, params: dict[str, int | str], endpoint: Endpoint, seed: int
    ) -> EventTrace:
        req = self.translate(scenario, params, endpoint.port)
        timeout = 8.0 + int(req.get("within_ms", DEFAULT_WITHIN_MS)) / 1000.0
        res = await self._exec(endpoint, req, timeout=timeout)
        events = self.events(res)
        obs: dict[str, str | bool | int] = {
            "closed": bool(res.get("closed", False)),
            "alert": str(res["alert"]) if res.get("alert") else "none",
        }
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

        req: dict[str, Any] = {
            "mode": "run",
            "port": port,
            "transport": "udp",
            "opt_count": 1,
            "opt_version": 0,
            "within_ms": DEFAULT_WITHIN_MS,
        }
        for step in scenario.steps:
            args = {k: value(v) for k, v in step.args.items()}
            if step.op == "connect" and "transport" in args:
                req["transport"] = str(args["transport"])
            elif step.op == "send_msg" and "qname" in args:
                req["qname"] = str(args["qname"])
            elif step.op == "mutate":
                fld = str(args.get("field", "")).lower()
                op = str(args.get("op", "")).lower()
                val = args.get("value")
                if fld in ("opt.version", "edns.version") and val is not None:
                    req["opt_version"] = int(val)
                elif fld in ("opt.count", "query.opt_count", "opt"):
                    if op == "duplicate" and val is None:
                        req["opt_count"] = 2
                    elif val is not None:
                        req["opt_count"] = int(val)
            elif step.op == "expect":
                req["within_ms"] = int(args.get("within_ms", args.get("timeout_ms", DEFAULT_WITHIN_MS)))
        return req

    @staticmethod
    def events(res: dict[str, Any]) -> tuple[ObservedEvent, ...]:
        out: list[ObservedEvent] = []
        if res.get("rcode"):
            out.append(ObservedEvent(name="respond", args=(str(res["rcode"]),), t_ms=int(res.get("t_alert_ms") or 0)))
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

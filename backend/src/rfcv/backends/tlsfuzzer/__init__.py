"""Backend TLS dựa trên tlsfuzzer + tlslite-ng (backend chính cho tầng 1).

Kịch bản trừu tượng (ScenarioProposal) được dịch sang đồ thị hội thoại của tlsfuzzer
(ClientHelloGenerator, ExpectServerHello, ExpectAlert…); đồ thị này bản thân đã là một DSL giới hạn.
Quan sát được chuẩn hoá thành Observation@1 với các trường miền hữu hạn.

Trạng thái: validate(), sanity() và run() đã cài đặt cho tập con DSL của yêu cầu loại B về độ dài bản ghi (xem SUPPORTED).
Client chạy BÊN TRONG container SUT qua `docker exec` (runner.py), phiên bản tlsfuzzer/tlslite-ng cố định theo commit trong image.
Phần DSL ngoài tập con (send_msg, mutate, reorder, repeat, bản ghi không mã hoá…) bị `validate` từ chối kèm lý do rõ ràng.
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

UNKNOWN_TYPES = ("type_0", "type_99", "type_255")  # loại bản ghi không được định nghĩa (byte 0, 99, 255)
DSL = DslSpec(
    ops={
        "connect": frozenset(),
        "complete_handshake": frozenset({"version", "cipher"}),
        "send_msg": frozenset({"type", "fields"}),
        "send_raw_record": frozenset({"content_type", "type", "length", "body", "encrypted"}),
        "mutate": frozenset({"field", "op", "value"}),
        "reorder": frozenset({"msgs"}),
        "repeat": frozenset({"msg"}),
        "expect": EXPECT_ARGS,
    },
    values={
        "body": BODIES,
        "op": MUTATIONS,
        "content_type": frozenset({"change_cipher_spec", "alert", "handshake", "application_data", *UNKNOWN_TYPES}),
    },
    notes={
        "complete_handshake": "bắt tay TLS đầy đủ; sau bước này trạng thái là connected",
        "send_raw_record": (
            "một bản ghi TLS thô. encrypted=true: bản ghi đã bảo vệ (TLSCiphertext) sau bắt tay, độ dài = length. encrypted=false: bản ghi "
            "rõ gửi NGAY sau connect (trước bắt tay), loại content_type (type_0, type_99, type_255 là loại không được định nghĩa), "
            "length byte nội dung"
        ),
    },
)

# Tập con DSL mà runner hiện thực thi được. Ngoài tập này, validate() từ chối để Test agent biết và đổi kịch bản.
SUPPORTED = {"connect", "complete_handshake", "send_raw_record", "expect"}
RUNNER_SOURCE = Path(__file__).with_name("runner.py")
PYTHON_IN_IMAGE = "/opt/venv/bin/python3"
RESULT_PREFIX = "RFCV_RESULT "
HANDSHAKE_S = 15.0  # hạn cho bắt tay + khởi động runner, cộng với cửa sổ quan sát `within_ms`
DEFAULT_WITHIN_MS = 2000
CRASH_EXIT = 128  # mã thoát >= 128 là bị tín hiệu giết; 137/143 là do ta dừng container


def runner_source() -> bytes:
    """Mã runner gửi vào container: luôn dùng LF (checkout Windows có thể để CRLF)."""
    return RUNNER_SOURCE.read_bytes().replace(b"\r\n", b"\n")


class TlsfuzzerBackend(DslBackend):
    name = "tlsfuzzer"
    dsl = DSL
    runner = "đồ thị hội thoại tlsfuzzer"

    def __init__(self, cli: DockerCli | None = None) -> None:
        self._cli = cli or DockerCli()

    # ---- kiểm tra kịch bản ----------------------------------------------------------------------------------

    def validate(self, scenario: ScenarioProposal) -> ValidationResult:
        base = super().validate(scenario)
        errors = list(base.errors)
        for step in scenario.steps:
            if step.op not in SUPPORTED:
                errors.append(f"backend chưa hỗ trợ bước '{step.op}' (hỗ trợ: {', '.join(sorted(SUPPORTED))})")
            if step.op == "send_raw_record":
                encrypted = step.args.get("encrypted", True) is True
                ctype = str(step.args.get("content_type", "application_data"))
                if encrypted and ctype != "application_data":
                    errors.append("send_raw_record: bản ghi đã mã hoá chỉ hỗ trợ content_type=application_data")
                if "length" not in step.args:
                    errors.append("send_raw_record: thiếu đối số length")
        handshakes = sum(step.op == "complete_handshake" for step in scenario.steps)
        plain = [s for s in scenario.steps if s.op == "send_raw_record" and s.args.get("encrypted", True) is not True]
        if plain and handshakes:
            errors.append("bản ghi rõ (encrypted=false) được gửi trước bắt tay: không kết hợp với complete_handshake")
        if sum(step.op == "send_raw_record" for step in scenario.steps) != 1:
            errors.append("kịch bản phải có đúng một bước send_raw_record")
        return ValidationResult(base.ok and not errors, tuple(errors))

    # ---- chạy -----------------------------------------------------------------------------------------------

    async def sanity(self, endpoint: Endpoint) -> bool:
        res = await self._exec(endpoint, {"mode": "sanity", "port": endpoint.port}, HANDSHAKE_S)
        return bool(res.get("ok"))

    async def run(
        self, scenario: ScenarioProposal, params: dict[str, int | str], endpoint: Endpoint, seed: int
    ) -> EventTrace:
        request = self.request(scenario, params, endpoint.port)
        within_ms = int(request["within_ms"])
        res = await self._exec(endpoint, request, HANDSHAKE_S + within_ms / 1000.0)
        alive = await self._alive(endpoint)
        return EventTrace(
            events=self.events(res),
            trigger_reached=bool(res.get("trigger_reached")),
            sut_alive_after=alive,
            observation={"alert": str(res.get("alert") or "none"), "closed": bool(res.get("closed"))},
            raw_log=await self._server_log(endpoint),
        )

    # ---- dịch kịch bản ⇄ yêu cầu của runner -----------------------------------------------------------------

    @staticmethod
    def request(scenario: ScenarioProposal, params: dict[str, int | str], port: int) -> dict[str, Any]:
        """Thay `$tên` bằng giá trị biến thể rồi rút ra yêu cầu cho runner (độ dài ciphertext, cipher, cửa sổ quan sát)."""

        def value(raw: Any) -> Any:
            return params[raw[1:]] if isinstance(raw, str) and raw.startswith("$") else raw

        req: dict[str, Any] = {"mode": "run", "port": port, "within_ms": DEFAULT_WITHIN_MS}
        for step in scenario.steps:
            args = {k: value(v) for k, v in step.args.items()}
            if step.op == "complete_handshake" and "cipher" in args:
                req["cipher"] = str(args["cipher"])
            elif step.op == "send_raw_record":
                req["length"] = int(args["length"])
                req["encrypted"] = args.get("encrypted", True) is True
                req["content_type"] = str(args.get("content_type", "application_data"))
            elif step.op == "expect":
                req["within_ms"] = int(args.get("within_ms", args.get("timeout_ms", DEFAULT_WITHIN_MS)))
        return req

    @staticmethod
    def events(res: dict[str, Any]) -> tuple[ObservedEvent, ...]:
        """Chuẩn hoá quan sát của runner thành sự kiện trong từ vựng adapter; `t_ms` tính từ lúc kích hoạt."""
        out: list[ObservedEvent] = []
        if res.get("alert"):
            out.append(
                ObservedEvent(name="send_alert", args=(str(res["alert"]),), t_ms=int(res.get("t_alert_ms") or 0))
            )
        if res.get("app_data"):
            out.append(ObservedEvent(name="send", args=("application_data",), t_ms=int(res.get("t_alert_ms") or 0)))
        if res.get("closed"):
            out.append(ObservedEvent(name="close", t_ms=int(res.get("t_close_ms") or 0)))
        return tuple(sorted(out, key=lambda e: e.t_ms))

    # ---- tiện ích -------------------------------------------------------------------------------------------

    async def _exec(self, endpoint: Endpoint, request: dict[str, Any], timeout: float) -> dict[str, Any]:
        """Chạy runner trong container; lỗi hạ tầng thành kết quả "không kích hoạt được", không giả làm FAIL của SUT."""
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
        """SUT sập khi server thoát vì tín hiệu (mã >= 128, trừ 137/143 do ta dừng). Thoát bình thường sau lỗi không phải sập."""
        try:
            res = await self._cli("exec", endpoint.host, "cat", SERVER_EXIT, timeout=15)
        except DockerError:
            return True
        code = res.text().strip()
        if not res.ok or not code.isdigit():
            return True  # server còn chạy (chưa có mã thoát)
        return not (int(code) >= CRASH_EXIT and int(code) not in (137, 143))

    async def _server_log(self, endpoint: Endpoint) -> bytes:
        try:
            res = await self._cli("exec", endpoint.host, "tail", "-c", "65536", SERVER_LOG, timeout=15)
        except DockerError:
            return b""
        return res.stdout if res.ok else b""

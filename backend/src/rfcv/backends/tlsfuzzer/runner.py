# pyright: basic, reportMissingImports=false
# ruff: noqa
"""Runner chạy BÊN TRONG container SUT (python /opt/venv, PYTHONPATH có tlslite-ng + tlsfuzzer ghim commit).

Backend đẩy mã nguồn này qua stdin của `docker exec -i <container> python3 - '<json>'`, nên tệp này phải tự đủ và không
nhập gì từ rfcv. In đúng MỘT dòng `RFCV_RESULT {json}` ở cuối; mọi thứ khác (tlsfuzzer có in thông báo lỗi) bị bỏ qua.

Yêu cầu (JSON):  {"mode": "sanity"|"run", "port": 4433, "cipher": "TLS_AES_128_GCM_SHA256",
                  "length": N, "within_ms": 2000}

`mode=run`: bắt tay TLS 1.3 đầy đủ, rồi gửi ĐÚNG MỘT bản ghi ứng dụng đã mã hoá có độ dài TLSCiphertext = N, rồi quan sát.
N = 1 (loại nội dung bên trong) + 16 (thẻ AEAD) + độ dài dữ liệu, nên dữ liệu dài N - 17; N < 17 không mã hoá được
(`reason = length_below_min_encrypted`, không phải lỗi của SUT). Kết quả:

    {"trigger_reached": bool, "reason": str, "alert": str|null, "closed": bool, "t_alert_ms": int|null,
     "t_close_ms": int|null, "app_data": bool, "send_error": bool}

Bản ghi lớn không bị tlslite-ng chia nhỏ vì `SetMaxRecordSize(2**16 - 1)` (đúng cách ca "max size payload" của tlsfuzzer làm).
"""

from __future__ import annotations

import json
import socket
import sys
import time
from typing import Any

from tlsfuzzer.expect import (
    ExpectCertificate,
    ExpectCertificateVerify,
    ExpectChangeCipherSpec,
    ExpectEncryptedExtensions,
    ExpectFinished,
    ExpectServerHello,
)
from tlsfuzzer.helpers import RSA_SIG_ALL, key_share_gen
from tlsfuzzer.messages import (
    ApplicationDataGenerator,
    ClientHelloGenerator,
    Connect,
    FinishedGenerator,
    SetMaxRecordSize,
)
from tlsfuzzer.runner import Runner
from tlslite.constants import (
    AlertDescription,
    CipherSuite,
    ContentType,
    ExtensionType,
    GroupName,
    SignatureScheme,
    TLS_1_3_DRAFT,
)
from tlslite.errors import TLSAbruptCloseError
from tlslite.extensions import (
    ClientKeyShareExtension,
    SignatureAlgorithmsCertExtension,
    SignatureAlgorithmsExtension,
    SupportedGroupsExtension,
    SupportedVersionsExtension,
)
from tlslite.messages import Alert

OVERHEAD = 17  # 1 byte loại nội dung bên trong + 16 byte thẻ AEAD
CIPHERS = {
    "TLS_AES_128_GCM_SHA256": CipherSuite.TLS_AES_128_GCM_SHA256,
    "TLS_CHACHA20_POLY1305_SHA256": CipherSuite.TLS_CHACHA20_POLY1305_SHA256,
}


def handshake(host: str, port: int, cipher: int) -> Any:
    """Cây hội thoại bắt tay TLS 1.3, dừng ngay sau Finished của client (giống ca `sanity` của tlsfuzzer)."""
    groups = [GroupName.secp256r1]
    ext: dict[int, Any] = {
        ExtensionType.key_share: ClientKeyShareExtension().create([key_share_gen(g) for g in groups]),
        ExtensionType.supported_versions: SupportedVersionsExtension().create([TLS_1_3_DRAFT, (3, 3)]),
        ExtensionType.supported_groups: SupportedGroupsExtension().create(groups),
        ExtensionType.signature_algorithms: SignatureAlgorithmsExtension().create(
            [SignatureScheme.rsa_pss_rsae_sha256, SignatureScheme.rsa_pss_pss_sha256]
        ),
        ExtensionType.signature_algorithms_cert: SignatureAlgorithmsCertExtension().create(RSA_SIG_ALL),
    }
    conversation = Connect(host, port)
    node = conversation
    node = node.add_child(SetMaxRecordSize(2**16 - 1))
    node = node.add_child(ClientHelloGenerator([cipher, CipherSuite.TLS_EMPTY_RENEGOTIATION_INFO_SCSV], extensions=ext))
    node = node.add_child(ExpectServerHello())
    node = node.add_child(ExpectChangeCipherSpec())
    node = node.add_child(ExpectEncryptedExtensions())
    node = node.add_child(ExpectCertificate())
    node = node.add_child(ExpectCertificateVerify())
    node = node.add_child(ExpectFinished())
    node.add_child(FinishedGenerator())
    return conversation


def ms(since: float) -> int:
    return int((time.monotonic() - since) * 1000)


def observe(state: Any, t0: float, within_ms: int) -> dict[str, Any]:
    """Đọc phản ứng của SUT tới hạn `within_ms` kể từ lúc gửi: cảnh báo, đóng kết nối, dữ liệu ứng dụng."""
    out: dict[str, Any] = {"alert": None, "closed": False, "t_alert_ms": None, "t_close_ms": None, "app_data": False}
    sock = state.msg_sock.sock
    deadline = t0 + within_ms / 1000.0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        sock.settimeout(remaining)
        try:
            header, parser = state.msg_sock.recvMessageBlocking()
        except socket.timeout:
            break
        except (TLSAbruptCloseError, OSError):
            out["closed"], out["t_close_ms"] = True, ms(t0)
            break
        if header.type == ContentType.alert:
            alert = Alert().parse(parser)
            if out["alert"] is None:
                out["alert"] = AlertDescription.toStr(alert.description)
                out["t_alert_ms"] = ms(t0)
        elif header.type == ContentType.application_data:
            out["app_data"] = True
        # bản ghi bắt tay muộn (NewSessionTicket…) bị bỏ qua
    return out


def run_sanity(req: dict[str, Any]) -> dict[str, Any]:
    cipher = CIPHERS.get(req.get("cipher", ""), CipherSuite.TLS_AES_128_GCM_SHA256)
    try:
        Runner(handshake("127.0.0.1", int(req["port"]), cipher)).run()
    except Exception as exc:  # noqa: BLE001 - mọi lỗi bắt tay đều nghĩa là môi trường không dùng được
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}
    return {"ok": True}


def run_trigger(req: dict[str, Any]) -> dict[str, Any]:
    n = int(req["length"])
    within_ms = int(req.get("within_ms", 2000))
    cipher = CIPHERS.get(req.get("cipher", ""), CipherSuite.TLS_AES_128_GCM_SHA256)
    base: dict[str, Any] = {"trigger_reached": False, "reason": "", "send_error": False}
    if n < OVERHEAD:
        return {**base, "reason": "length_below_min_encrypted"}
    runner = Runner(handshake("127.0.0.1", int(req["port"]), cipher))
    try:
        runner.run()
    except Exception as exc:  # noqa: BLE001
        return {**base, "reason": f"handshake_failed: {type(exc).__name__}: {exc}"[:200]}
    state = runner.state
    generator = ApplicationDataGenerator(bytearray(n - OVERHEAD))
    message = generator.generate(state)
    t0 = time.monotonic()
    send_error = False
    try:
        if message.write():
            state.msg_sock.sendMessageBlocking(message)
        else:  # bản ghi rỗng: đi thẳng qua tầng bản ghi như Runner của tlsfuzzer
            for _ in state.msg_sock.sendRecord(message):
                pass
        generator.post_send(state)
    except (TLSAbruptCloseError, OSError):
        send_error = True  # SUT có thể đã đóng ngay khi đọc tiêu đề bản ghi
    return {**base, "trigger_reached": True, "send_error": send_error, **observe(state, t0, within_ms)}


def main() -> None:
    req = json.loads(sys.argv[1])
    result = run_sanity(req) if req["mode"] == "sanity" else run_trigger(req)
    print("RFCV_RESULT " + json.dumps(result), flush=True)


main()

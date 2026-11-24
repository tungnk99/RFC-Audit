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


def handshake_extensions(groups: list[int]) -> dict[int, Any]:
    return {
        ExtensionType.key_share: ClientKeyShareExtension().create([key_share_gen(g) for g in groups]),
        ExtensionType.supported_versions: SupportedVersionsExtension().create([TLS_1_3_DRAFT, (3, 3)]),
        ExtensionType.supported_groups: SupportedGroupsExtension().create(groups),
        ExtensionType.signature_algorithms: SignatureAlgorithmsExtension().create(
            [SignatureScheme.rsa_pss_rsae_sha256, SignatureScheme.rsa_pss_pss_sha256]
        ),
        ExtensionType.signature_algorithms_cert: SignatureAlgorithmsCertExtension().create(RSA_SIG_ALL),
    }


def handshake(host: str, port: int, cipher: int) -> Any:
    """Cây hội thoại bắt tay TLS 1.3, dừng ngay sau Finished của client (giống ca `sanity` của tlsfuzzer)."""
    ext = handshake_extensions([GroupName.secp256r1])
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


PLAIN_TYPES = {
    "change_cipher_spec": 20,
    "alert": 21,
    "handshake": 22,
    "application_data": 23,
    "type_0": 0,
    "type_99": 99,
    "type_255": 255,
}


def run_plain_record(req: dict[str, Any]) -> dict[str, Any]:
    """Một bản ghi RÕ có loại cho trước, gửi ngay sau khi nối (trước bắt tay), rồi quan sát phản ứng của SUT."""
    within_ms = int(req.get("within_ms", 2000))
    base: dict[str, Any] = {"trigger_reached": False, "reason": "", "send_error": False}
    raw_name = str(req.get("content_type"))
    ctype = PLAIN_TYPES.get(raw_name)
    if ctype is None and raw_name.startswith("type_") and raw_name[5:].isdigit():
        num = int(raw_name[5:])
        if 0 <= num <= 255:
            ctype = num
    if ctype is None:
        return {**base, "reason": "unknown_content_type_name"}
    from tlsfuzzer.messages import RawMessageGenerator

    conversation = Connect("127.0.0.1", int(req["port"]))
    runner = Runner(conversation)
    try:
        runner.run()
    except Exception as exc:  # noqa: BLE001
        return {**base, "reason": f"connect_failed: {type(exc).__name__}: {exc}"[:200]}
    state = runner.state
    generator = RawMessageGenerator(ctype, bytearray(max(0, int(req["length"]))))
    message = generator.generate(state)
    t0 = time.monotonic()
    send_error = False
    try:
        state.msg_sock.sendMessageBlocking(message)
    except (TLSAbruptCloseError, OSError):
        send_error = True
    return {**base, "trigger_reached": True, "send_error": send_error, **observe(state, t0, within_ms)}


UNSHARED_GROUP = 0x7A7A  # nhóm không được máy chủ nào hỗ trợ


def client_hello_extensions(spec: dict[str, Any]) -> dict[int, Any]:
    """Phần mở rộng của ClientHello hợp lệ (như `handshake`), rồi biến đổi key_share / supported_groups theo `spec`."""
    from tlslite.extensions import KeyShareEntry, TLSExtension

    group = GroupName.secp256r1
    ext = handshake_extensions([group])
    if spec.get("groups") == "disjoint":
        ext[ExtensionType.supported_groups] = SupportedGroupsExtension().create([UNSHARED_GROUP])
        ext[ExtensionType.key_share] = ClientKeyShareExtension().create([])
    if spec.get("key_share") == "empty_entry":
        ext[ExtensionType.key_share] = ClientKeyShareExtension().create([KeyShareEntry().create(group, bytearray(), None)])
    elif spec.get("key_share") == "empty_extension":
        ext[ExtensionType.key_share] = TLSExtension(extType=ExtensionType.key_share).create(bytearray())
    return ext


def run_client_hello(req: dict[str, Any]) -> dict[str, Any]:
    """Một ClientHello (có biến đổi) ngay sau khi nối, rồi quan sát phản ứng của SUT."""
    within_ms = int(req.get("within_ms", 2000))
    base: dict[str, Any] = {"trigger_reached": False, "reason": "", "send_error": False}
    cipher = CIPHERS.get(req.get("cipher", ""), CipherSuite.TLS_AES_128_GCM_SHA256)
    conversation = Connect("127.0.0.1", int(req["port"]))
    node = conversation.add_child(SetMaxRecordSize(2**16 - 1))
    t0 = time.monotonic()
    node.add_child(
        ClientHelloGenerator(
            [cipher, CipherSuite.TLS_EMPTY_RENEGOTIATION_INFO_SCSV], extensions=client_hello_extensions(req["client_hello"])
        )
    )
    runner = Runner(conversation)
    try:
        runner.run()
    except Exception as exc:  # noqa: BLE001
        return {**base, "reason": f"send_failed: {type(exc).__name__}: {exc}"[:200]}
    # sau ServerHello hợp lệ, phần còn lại của bắt tay đi trong bản ghi mã hoá có loại application_data: không phải dữ liệu ứng dụng
    return {**base, "trigger_reached": True, **observe(runner.state, t0, within_ms), "app_data": False}


def main() -> None:
    req = json.loads(sys.argv[1])
    if req["mode"] == "sanity":
        result = run_sanity(req)
    elif "client_hello" in req:
        result = run_client_hello(req)
    elif req.get("encrypted", True) is False:
        result = run_plain_record(req)
    else:
        result = run_trigger(req)
    print("RFCV_RESULT " + json.dumps(result), flush=True)


main()

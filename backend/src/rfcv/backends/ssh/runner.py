"""SSH (RFC 4253) binary packet protocol runner executed inside the SUT container via `docker exec`.

Uses Python stdlib only (`socket`, `struct`, `json`, `time`) so any container with `python3`
can exchange SSH-2.0 identification banners, send raw SSH_MSG_KEXINIT or arbitrary binary
packets, and decode SSH_MSG_DISCONNECT reason codes (RFC 4253 §11.1) and connection closure.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import struct
import sys
import time
from typing import Any

PREFIX = "RFCV_RESULT "

DISCONNECT_REASONS: dict[int, str] = {
    1: "host_not_allowed_to_connect",
    2: "protocol_error",
    3: "key_exchange_failed",
    4: "reserved",
    5: "mac_error",
    6: "compression_error",
    7: "service_not_available",
    8: "protocol_version_not_supported",
    9: "host_key_not_verifiable",
    10: "connection_lost",
    11: "by_application",
    12: "too_many_connections",
    13: "auth_cancelled_by_user",
    14: "no_more_auth_methods_available",
    15: "illegal_user_name",
}


def _ssh_str(s: bytes) -> bytes:
    return struct.pack("!I", len(s)) + s


def _pack_ssh_packet(payload: bytes) -> bytes:
    # RFC 4253 §6: packet_length (4) + padding_length (1) + payload + random padding (min 4, total multiple of 8)
    block = 8
    pad_len = block - ((len(payload) + 5) % block)
    if pad_len < 4:
        pad_len += block
    pkt_len = 1 + len(payload) + pad_len
    return struct.pack("!IB", pkt_len, pad_len) + payload + (b"\x00" * pad_len)


def _build_kexinit(common_kex: int = 1) -> bytes:
    cookie = os.urandom(16)
    kex = b"curve25519-sha256,diffie-hellman-group14-sha256" if common_kex > 0 else b"no-such-kex@rfcv.test"
    host_key = b"ssh-ed25519,rsa-sha2-256,ssh-rsa"
    enc = b"aes128-ctr,chacha20-poly1305@openssh.com"
    mac = b"hmac-sha2-256"
    comp = b"none"
    lang = b""
    payload = (
        bytes([20])  # SSH_MSG_KEXINIT
        + cookie
        + _ssh_str(kex)
        + _ssh_str(host_key)
        + _ssh_str(enc)
        + _ssh_str(enc)
        + _ssh_str(mac)
        + _ssh_str(mac)
        + _ssh_str(comp)
        + _ssh_str(comp)
        + _ssh_str(lang)
        + _ssh_str(lang)
        + b"\x00"
        + struct.pack("!I", 0)
    )
    return _pack_ssh_packet(payload)


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError("peer closed")
        buf.extend(chunk)
    return bytes(buf)


def _read_banner(sock: socket.socket, timeout_s: float) -> bytes:
    sock.settimeout(timeout_s)
    buf = bytearray()
    while len(buf) < 512:
        ch = sock.recv(1)
        if not ch:
            raise EOFError("peer closed before banner")
        buf.extend(ch)
        if buf.endswith(b"\n"):
            if buf.startswith(b"SSH-"):
                return bytes(buf)
            buf.clear()
    raise ValueError("invalid SSH banner")


def _read_ssh_packet(sock: socket.socket, timeout_s: float) -> bytes:
    sock.settimeout(max(0.05, timeout_s))
    hdr = _recv_exact(sock, 4)
    (pkt_len,) = struct.unpack("!I", hdr)
    if pkt_len < 2 or pkt_len > 350000:
        raise ValueError(f"bad ssh packet length: {pkt_len}")
    body = _recv_exact(sock, pkt_len)
    pad_len = body[0]
    return body[1 : pkt_len - pad_len]


def _run_case(req: dict[str, Any]) -> dict[str, Any]:
    port = int(req["port"])
    within_ms = int(req.get("within_ms", 2000))
    ident = str(req.get("ident", "SSH-2.0-RFCV_Test")).encode("ascii") + b"\r\n"

    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=5.0)
    except OSError as exc:
        return {"ok": False, "trigger_reached": False, "reason": f"connect failed: {exc}"}

    try:
        with sock:
            banner = _read_banner(sock, 5.0)
            sock.sendall(ident)
            if req.get("mode") == "sanity":
                return {"ok": banner.startswith(b"SSH-2.0-"), "trigger_reached": True}

            if "msg_number" in req:
                msg_num = int(req["msg_number"]) & 0xFF
                length = max(1, int(req.get("length", 16)))
                pkt = _pack_ssh_packet(bytes([msg_num]) + b"\x00" * (length - 1))
            else:
                pkt = _build_kexinit(common_kex=int(req.get("common_kex_count", 0)))

            t0 = time.monotonic()
            with contextlib.suppress(OSError):
                sock.sendall(pkt)

            disconnect_reason: str | None = None
            t_alert_ms: int | None = None
            closed = False
            t_close_ms: int | None = None
            deadline = t0 + within_ms / 1000.0

            while time.monotonic() < deadline:
                rem = deadline - time.monotonic()
                if rem <= 0:
                    break
                try:
                    payload = _read_ssh_packet(sock, rem)
                except TimeoutError:
                    break
                except (EOFError, OSError):
                    closed = True
                    t_close_ms = int((time.monotonic() - t0) * 1000)
                    break
                if not payload:
                    continue
                mtype = payload[0]
                if mtype == 1 and len(payload) >= 5:  # SSH_MSG_DISCONNECT
                    (code,) = struct.unpack("!I", payload[1:5])
                    disconnect_reason = DISCONNECT_REASONS.get(code, f"reason_{code}")
                    t_alert_ms = int((time.monotonic() - t0) * 1000)
                    # Continue briefly to observe TCP close
            return {
                "ok": True,
                "trigger_reached": True,
                "disconnect": disconnect_reason,
                "alert": disconnect_reason,
                "t_alert_ms": t_alert_ms,
                "closed": closed,
                "t_close_ms": t_close_ms,
            }
    except Exception as exc:
        return {"ok": False, "trigger_reached": False, "reason": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    req = json.loads(sys.argv[1])
    print(PREFIX + json.dumps(_run_case(req)), flush=True)


if __name__ == "__main__":
    main()

"""HTTP/2 (h2c) protocol test runner executed inside the SUT container via `docker exec`.

Uses Python stdlib only (`socket`, `struct`, `json`, `time`) so any container with `python3`
can run RFC 9113 frame-level conformance tests against `nghttpd --no-tls` (or any h2c server)
without extra pip dependencies.
"""

from __future__ import annotations

import contextlib
import json
import socket
import struct
import sys
import time
from typing import Any

PREFIX = "RFCV_RESULT "
PREFACE = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"

FRAME_TYPE_CODES: dict[str, int] = {
    "data": 0x00,
    "headers": 0x01,
    "priority": 0x02,
    "rst_stream": 0x03,
    "settings": 0x04,
    "push_promise": 0x05,
    "ping": 0x06,
    "goaway": 0x07,
    "window_update": 0x08,
    "continuation": 0x09,
}

ERROR_CODE_NAMES: dict[int, str] = {
    0x00: "no_error",
    0x01: "protocol_error",
    0x02: "internal_error",
    0x03: "flow_control_error",
    0x04: "settings_timeout",
    0x05: "stream_closed",
    0x06: "frame_size_error",
    0x07: "refused_stream",
    0x08: "cancel",
    0x09: "compression_error",
    0x0A: "connect_error",
    0x0B: "enhance_your_calm",
    0x0C: "inadequate_security",
    0x0D: "http_1_1_required",
}


def _pack_frame(
    ftype: int, flags: int, stream_id: int, payload: bytes, *, advertised_length: int | None = None
) -> bytes:
    length = len(payload) if advertised_length is None else advertised_length
    hdr = bytes([(length >> 16) & 0xFF, (length >> 8) & 0xFF, length & 0xFF, ftype & 0xFF, flags & 0xFF])
    hdr += struct.pack("!I", stream_id & 0x7FFFFFFF)
    return hdr + payload


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError("peer closed connection")
        buf.extend(chunk)
    return bytes(buf)


def _read_frame(sock: socket.socket, timeout_s: float) -> tuple[int, int, int, bytes]:
    sock.settimeout(max(0.05, timeout_s))
    hdr = _recv_exact(sock, 9)
    length = (hdr[0] << 16) | (hdr[1] << 8) | hdr[2]
    ftype = hdr[3]
    flags = hdr[4]
    (stream_id,) = struct.unpack("!I", hdr[5:9])
    stream_id &= 0x7FFFFFFF
    payload = _recv_exact(sock, length) if length > 0 else b""
    return ftype, flags, stream_id, payload


def _handshake(sock: socket.socket, deadline: float) -> None:
    sock.sendall(PREFACE + _pack_frame(0x04, 0x00, 0, b""))
    got_settings = False
    while time.monotonic() < deadline:
        rem = deadline - time.monotonic()
        ftype, flags, _sid, _payload = _read_frame(sock, rem)
        if ftype == 0x04 and not (flags & 0x01):
            sock.sendall(_pack_frame(0x04, 0x01, 0, b""))
            got_settings = True
            break
    if not got_settings:
        raise TimeoutError("did not receive server SETTINGS")


def _run_sanity(port: int, timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    with socket.create_connection(("127.0.0.1", port), timeout=timeout_s) as sock:
        _handshake(sock, deadline)
        sock.sendall(_pack_frame(0x06, 0x00, 0, b"12345678"))
        while time.monotonic() < deadline:
            ftype, flags, _sid, payload = _read_frame(sock, deadline - time.monotonic())
            if ftype == 0x06 and (flags & 0x01) and payload == b"12345678":
                return {"ok": True, "trigger_reached": True}
    return {"ok": False, "trigger_reached": False, "reason": "no PING ACK in sanity"}


def _run_case(req: dict[str, Any]) -> dict[str, Any]:
    port = int(req["port"])
    within_ms = int(req.get("within_ms", 2000))
    ftype_name = str(req.get("frame_type", "data")).lower()
    ftype = FRAME_TYPE_CODES.get(ftype_name, 0x00)
    flags = int(req.get("flags", 0))
    stream_id = int(req.get("stream_id", 0 if ftype_name in ("ping", "settings", "goaway") else 1))
    length = int(req.get("length", 8 if ftype_name == "ping" else 16385))

    t_connect_deadline = time.monotonic() + 5.0
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=5.0)
    except OSError as exc:
        return {"ok": False, "trigger_reached": False, "reason": f"connect failed: {exc}"}

    try:
        with sock:
            _handshake(sock, t_connect_deadline)
            # For stream-level DATA frames, open stream 1 with minimal HPACK HEADERS (:method=GET, :scheme=http, :path=/)
            # if stream_id > 0 and ftype == 0x00 so server accepts valid-length DATA frames cleanly.
            if ftype == 0x00 and stream_id > 0:
                # Indexed static HPACK: :method GET (0x82), :scheme http (0x86), :path / (0x84)
                sock.sendall(_pack_frame(0x01, 0x04, stream_id, b"\x82\x86\x84"))

            payload = b"\x00" * min(length, 262144)
            frame = _pack_frame(ftype, flags, stream_id, payload, advertised_length=length)
            t0 = time.monotonic()
            with contextlib.suppress(OSError):
                sock.sendall(frame)

            goaway_code: str | None = None
            rst_code: str | None = None
            t_alert_ms: int | None = None
            ping_ack = False
            closed = False
            t_close_ms: int | None = None
            deadline = t0 + within_ms / 1000.0

            while time.monotonic() < deadline:
                rem = deadline - time.monotonic()
                if rem <= 0:
                    break
                try:
                    rf_type, rf_flags, _rf_sid, rf_payload = _read_frame(sock, rem)
                except EOFError:
                    closed = True
                    t_close_ms = int((time.monotonic() - t0) * 1000)
                    break
                except TimeoutError:
                    break
                except OSError:
                    closed = True
                    t_close_ms = int((time.monotonic() - t0) * 1000)
                    break

                now_ms = int((time.monotonic() - t0) * 1000)
                if rf_type == 0x07 and len(rf_payload) >= 8:
                    (_last_sid, err_num) = struct.unpack("!II", rf_payload[:8])
                    goaway_code = ERROR_CODE_NAMES.get(err_num, f"error_{err_num}")
                    if t_alert_ms is None:
                        t_alert_ms = now_ms
                elif rf_type == 0x03 and len(rf_payload) >= 4:
                    (err_num,) = struct.unpack("!I", rf_payload[:4])
                    rst_code = ERROR_CODE_NAMES.get(err_num, f"error_{err_num}")
                    if t_alert_ms is None:
                        t_alert_ms = now_ms
                elif rf_type == 0x06 and (rf_flags & 0x01):
                    ping_ack = True

            return {
                "ok": True,
                "trigger_reached": True,
                "goaway": goaway_code,
                "rst_stream": rst_code,
                "alert": goaway_code or rst_code,
                "t_alert_ms": t_alert_ms,
                "ping_ack": ping_ack,
                "closed": closed,
                "t_close_ms": t_close_ms,
            }
    except Exception as exc:
        return {"ok": False, "trigger_reached": False, "reason": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    req = json.loads(sys.argv[1])
    if req.get("mode") == "sanity":
        res = _run_sanity(int(req["port"]), float(req.get("timeout_s", 5.0)))
    else:
        res = _run_case(req)
    print(PREFIX + json.dumps(res), flush=True)


if __name__ == "__main__":
    main()

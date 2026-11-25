"""QUIC v1 (RFC 9000) UDP Initial packet runner executed inside the SUT container via `docker exec`.

Uses Python stdlib only (`socket`, `struct`, `json`, `os`, `time`) so any container with `python3`
can send QUIC v1 Initial datagrams of exact UDP payload lengths (RFC 9000 §14.1: < 1200 bytes
MUST be discarded by server) and observe whether the server replies or discards.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import sys
import time
from typing import Any

PREFIX = "RFCV_RESULT "


def _build_quic_initial(datagram_length: int) -> bytes:
    # QUIC v1 Long Header Initial packet (RFC 9000 §17.2.2):
    # First byte: 0xC0 (Long Header=1, Fixed=1, Type=00 Initial)
    # Version: 0x00000001 (QUIC v1)
    # DCID len=8 + DCID, SCID len=8 + SCID, Token len=0, Length=varint, Payload padded to datagram_length
    dcid = os.urandom(8)
    scid = os.urandom(8)
    header = bytes([0xC0]) + struct.pack("!I", 0x00000001) + bytes([len(dcid)]) + dcid + bytes([len(scid)]) + scid
    token_len = b"\x00"
    rem = max(4, datagram_length - len(header) - 1 - 2)
    # 2-byte QUIC varint length (0x4000 | rem)
    pkt_len_vi = struct.pack("!H", 0x4000 | (rem & 0x3FFF))
    pkt = header + token_len + pkt_len_vi + (b"\x00" * rem)
    if len(pkt) > datagram_length:
        pkt = pkt[:datagram_length]
    elif len(pkt) < datagram_length:
        pkt = pkt + (b"\x00" * (datagram_length - len(pkt)))
    return pkt


def _run_case(req: dict[str, Any]) -> dict[str, Any]:
    port = int(req["port"])
    within_ms = int(req.get("within_ms", 1500))
    dgram_len = int(req.get("datagram_length", 1200))
    pkt = _build_quic_initial(dgram_len)
    t0 = time.monotonic()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(max(0.15, (within_ms - 150) / 1000.0))
            sock.sendto(pkt, ("127.0.0.1", port))
            try:
                data, _addr = sock.recvfrom(65535)
                elapsed = int((time.monotonic() - t0) * 1000)
                if req.get("mode") == "sanity":
                    return {"ok": len(data) > 0, "trigger_reached": True}
                ptype = "initial" if (data and (data[0] & 0x80)) else "one_rtt"
                return {
                    "ok": True,
                    "trigger_reached": True,
                    "replied": True,
                    "packet_type": ptype,
                    "discarded": False,
                    "t_ms": elapsed,
                }
            except TimeoutError:
                elapsed = int((time.monotonic() - t0) * 1000)
                if req.get("mode") == "sanity":
                    return {"ok": False, "trigger_reached": False, "reason": "no reply to 1200-byte QUIC Initial"}
                return {
                    "ok": True,
                    "trigger_reached": True,
                    "replied": False,
                    "discarded": True,
                    "t_ms": min(elapsed, within_ms),
                }
    except Exception as exc:
        return {"ok": False, "trigger_reached": False, "reason": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    req = json.loads(sys.argv[1])
    print(PREFIX + json.dumps(_run_case(req)), flush=True)


if __name__ == "__main__":
    main()

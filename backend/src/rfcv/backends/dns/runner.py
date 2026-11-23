"""DNS (RFC 1035 / RFC 6891 EDNS0) test runner executed inside the SUT container via `docker exec`.

Uses Python stdlib only (`socket`, `struct`, `json`, `time`) so any container with `python3`
can send UDP/TCP DNS queries with configurable `opt_count` and `opt_version` and decode the
full 12-bit extended RCODE (header 4-bit RCODE + OPT RR 8-bit extended RCODE, e.g. BADVERS=16).
"""

from __future__ import annotations

import json
import socket
import struct
import sys
import time

PREFIX = "RFCV_RESULT "

RCODE_NAMES: dict[int, str] = {
    0: "noerror",
    1: "formerr",
    2: "servfail",
    3: "nxdomain",
    4: "notimp",
    5: "refused",
    16: "badvers",
}


def _encode_qname(name: str) -> bytes:
    parts = [p for p in name.strip(".").split(".") if p]
    out = bytearray()
    for p in parts:
        b = p.encode("ascii")
        out.append(len(b))
        out.extend(b)
    out.append(0)
    return bytes(out)


def _opt_rr(version: int = 0, udp_size: int = 1232) -> bytes:
    # RFC 6891 §6.1.2: NAME=0 (root), TYPE=41 (OPT), CLASS=udp_size, TTL=(ext_rcode<<24 | version<<16 | flags), RDLEN=0
    ttl = (version & 0xFF) << 16
    return b"\x00" + struct.pack("!HHIH", 41, udp_size, ttl, 0)


def _build_query(qname: str = "example.test", qtype: int = 1, opt_count: int = 1, opt_version: int = 0) -> bytes:
    txid = 0x1234
    flags = 0x0100  # RD=1
    arcount = max(0, min(opt_count, 200))
    hdr = struct.pack("!HHHHHH", txid, flags, 1, 0, 0, arcount)
    question = _encode_qname(qname) + struct.pack("!HH", qtype, 1)  # IN
    opts = _opt_rr(version=opt_version) * arcount
    return hdr + question + opts


def _skip_name(pkt: bytes, pos: int) -> int:
    n = len(pkt)
    while pos < n:
        ln = pkt[pos]
        if ln == 0:
            return pos + 1
        if (ln & 0xC0) == 0xC0:
            return pos + 2
        pos += 1 + ln
    return n


def _parse_rcode(pkt: bytes) -> int:
    if len(pkt) < 12:
        return -1
    _txid, flags, qdcount, ancount, nscount, arcount = struct.unpack("!HHHHHH", pkt[:12])
    base_rcode = flags & 0x0F
    pos = 12
    for _ in range(qdcount):
        pos = _skip_name(pkt, pos) + 4
    for _ in range(ancount + nscount):
        if pos >= len(pkt):
            break
        pos = _skip_name(pkt, pos)
        if pos + 10 > len(pkt):
            break
        (_rtype, _rclass, _ttl, rdlen) = struct.unpack("!HHIH", pkt[pos : pos + 10])
        pos += 10 + rdlen
    ext_rcode = 0
    for _ in range(arcount):
        if pos >= len(pkt):
            break
        pos = _skip_name(pkt, pos)
        if pos + 10 > len(pkt):
            break
        (rtype, _rclass, ttl, rdlen) = struct.unpack("!HHIH", pkt[pos : pos + 10])
        if rtype == 41:  # OPT RR
            ext_rcode = (ttl >> 24) & 0xFF
            break
        pos += 10 + rdlen
    return (ext_rcode << 4) | base_rcode


def _send_recv(port: int, payload: bytes, transport: str, timeout_s: float) -> tuple[bytes | None, bool, int]:
    t0 = time.monotonic()
    if transport == "tcp" or len(payload) > 1200:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout_s) as sock:
            sock.settimeout(timeout_s)
            sock.sendall(struct.pack("!H", len(payload)) + payload)
            try:
                hdr = sock.recv(2)
                if len(hdr) < 2:
                    return None, True, int((time.monotonic() - t0) * 1000)
                (rlen,) = struct.unpack("!H", hdr)
                buf = bytearray()
                while len(buf) < rlen:
                    chunk = sock.recv(rlen - len(buf))
                    if not chunk:
                        break
                    buf.extend(chunk)
                return bytes(buf), False, int((time.monotonic() - t0) * 1000)
            except TimeoutError:
                return None, False, int((time.monotonic() - t0) * 1000)
            except OSError:
                return None, True, int((time.monotonic() - t0) * 1000)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout_s)
        sock.sendto(payload, ("127.0.0.1", port))
        try:
            data, _addr = sock.recvfrom(65535)
            return data, False, int((time.monotonic() - t0) * 1000)
        except TimeoutError:
            return None, False, int((time.monotonic() - t0) * 1000)


def main() -> None:
    req = json.loads(sys.argv[1])
    port = int(req["port"])
    transport = str(req.get("transport", "udp")).lower()
    timeout_s = max(0.2, int(req.get("within_ms", 2000)) / 1000.0)
    try:
        if req.get("mode") == "sanity":
            pkt = _build_query("example.test", 1, opt_count=1, opt_version=0)
            resp, _closed, _ms = _send_recv(port, pkt, transport, timeout_s)
            ok = resp is not None and _parse_rcode(resp) in (0, 2, 3, 5)
            print(PREFIX + json.dumps({"ok": ok, "trigger_reached": ok}), flush=True)
            return
        pkt = _build_query(
            qname=str(req.get("qname", "example.test")),
            opt_count=int(req.get("opt_count", 1)),
            opt_version=int(req.get("opt_version", 0)),
        )
        resp, closed, elapsed = _send_recv(port, pkt, transport, timeout_s)
        rcode_name: str | None = None
        if resp is not None:
            rc = _parse_rcode(resp)
            rcode_name = RCODE_NAMES.get(rc, f"rcode_{rc}")
        print(
            PREFIX
            + json.dumps(
                {
                    "ok": True,
                    "trigger_reached": True,
                    "rcode": rcode_name,
                    "alert": rcode_name,
                    "t_alert_ms": elapsed if rcode_name else None,
                    "closed": closed,
                    "t_close_ms": elapsed if closed else None,
                }
            ),
            flush=True,
        )
    except Exception as exc:
        print(
            PREFIX + json.dumps({"ok": False, "trigger_reached": False, "reason": f"{type(exc).__name__}: {exc}"}),
            flush=True,
        )


if __name__ == "__main__":
    main()

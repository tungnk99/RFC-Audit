"""Kiểm thử đơn vị cho mở rộng đa giao thức: HTTP/2 runner, DNS/EDNS0 runner và _expected_alert phi-giao-thức."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import socket
import struct
import threading
from types import SimpleNamespace

from agents.code_reader.handler import _expected_alert
from agents.common import RBS_KEY
from rfcv.backends.dns import DnspythonBackend
from rfcv.backends.dns import runner as dns_runner
from rfcv.backends.http2 import H2specBackend
from rfcv.backends.http2 import runner as h2_runner
from rfcv.backends.quic import AioquicBackend
from rfcv.backends.quic import runner as quic_runner
from rfcv.backends.ssh import AsyncsshBackend
from rfcv.backends.ssh import runner as ssh_runner


def test_expected_alert_is_protocol_agnostic() -> None:
    for name, code in (
        ("send_alert", "record_overflow"),
        ("send_goaway", "frame_size_error"),
        ("send_rst_stream", "protocol_error"),
        ("respond", "badvers"),
        ("send_disconnect", "protocol_error"),
        ("send_connection_close", "frame_encoding_error"),
    ):
        inv = SimpleNamespace(
            domain_state={RBS_KEY: SimpleNamespace(expect=(SimpleNamespace(name=name, args=(code,)),))}
        )
        assert _expected_alert(inv) == code  # type: ignore[arg-type]


def test_http2_runner_live_loopback_goaway_and_sanity() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.listen(2)

    def serve() -> None:
        for _ in range(2):
            conn, _ = srv.accept()
            with conn:
                conn.settimeout(3.0)
                preface = h2_runner._recv_exact(conn, len(h2_runner.PREFACE))
                assert preface == h2_runner.PREFACE
                _ = h2_runner._read_frame(conn, 2.0)  # client SETTINGS
                conn.sendall(h2_runner._pack_frame(0x04, 0x00, 0, b""))  # server SETTINGS
                _ = h2_runner._read_frame(conn, 2.0)  # client SETTINGS ACK
                ftype, _flags, _sid, payload = h2_runner._read_frame(conn, 2.0)
                if ftype == 0x06 and len(payload) == 8:
                    conn.sendall(h2_runner._pack_frame(0x06, 0x01, 0, payload))
                else:
                    # Open HEADERS then oversized DATA -> reply GOAWAY(FRAME_SIZE_ERROR = 0x06)
                    if ftype == 0x01:
                        ftype, _flags, _sid, _payload = h2_runner._read_frame(conn, 2.0)
                    conn.sendall(h2_runner._pack_frame(0x07, 0x00, 0, struct.pack("!II", 1, 0x06)))
        srv.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()

    sanity = h2_runner._run_sanity(port, 3.0)
    assert sanity["ok"] is True

    res = h2_runner._run_case({"port": port, "frame_type": "data", "length": 16385, "within_ms": 1500})
    t.join(timeout=3.0)
    assert res["ok"] is True
    assert res["goaway"] == "frame_size_error"
    evs = H2specBackend.events(res)
    assert any(e.name == "send_goaway" and e.args == ("frame_size_error",) for e in evs)


def test_dns_runner_live_loopback_badvers_and_formerr() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.settimeout(3.0)

    def serve() -> None:
        for _ in range(2):
            data, addr = srv.recvfrom(4096)
            txid, _fl, _qd, _an, _ns, arcount = struct.unpack("!HHHHHH", data[:12])
            if arcount > 1:
                # Reply FORMERR (rcode=1)
                resp = struct.pack("!HHHHHH", txid, 0x8181, 0, 0, 0, 0)
            else:
                # Reply BADVERS (ext_rcode=1 in OPT TTL -> 1<<4 | 0 = 16)
                opt_badvers = b"\x00" + struct.pack("!HHIH", 41, 1232, 1 << 24, 0)
                resp = struct.pack("!HHHHHH", txid, 0x8180, 0, 0, 0, 1) + opt_badvers
            srv.sendto(resp, addr)
        srv.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()

    pkt_dup = dns_runner._build_query("example.test", 1, opt_count=2, opt_version=0)
    r1, _, _ = dns_runner._send_recv(port, pkt_dup, "udp", 2.0)
    assert r1 is not None and dns_runner._parse_rcode(r1) == 1  # FORMERR

    pkt_ver = dns_runner._build_query("example.test", 1, opt_count=1, opt_version=1)
    r2, _, _ = dns_runner._send_recv(port, pkt_ver, "udp", 2.0)
    assert r2 is not None and dns_runner._parse_rcode(r2) == 16  # BADVERS
    t.join(timeout=3.0)

    evs = DnspythonBackend.events({"rcode": "badvers", "t_alert_ms": 5, "closed": False})
    assert any(e.name == "respond" and e.args == ("badvers",) for e in evs)


def test_ssh_runner_live_loopback_disconnect() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.listen(1)

    def serve() -> None:
        conn, _ = srv.accept()
        with conn:
            conn.settimeout(3.0)
            conn.sendall(b"SSH-2.0-OpenSSH_9.9\r\n")
            _ = ssh_runner._read_banner(conn, 2.0)
            pkt = ssh_runner._read_ssh_packet(conn, 2.0)
            assert pkt[0] == 20  # SSH_MSG_KEXINIT
            # Reply SSH_MSG_DISCONNECT (1) reason=key_exchange_failed (3)
            disc = bytes([1]) + struct.pack("!I", 3) + ssh_runner._ssh_str(b"no kex") + ssh_runner._ssh_str(b"")
            conn.sendall(ssh_runner._pack_ssh_packet(disc))
        srv.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()

    res = ssh_runner._run_case({"port": port, "common_kex_count": 0, "within_ms": 1500})
    t.join(timeout=3.0)
    assert res["ok"] is True
    assert res["disconnect"] == "key_exchange_failed"
    assert res["closed"] is True
    evs = AsyncsshBackend.events(res)
    assert any(e.name == "send_disconnect" and e.args == ("key_exchange_failed",) for e in evs)


def test_quic_runner_live_loopback_discard_short_initial() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.settimeout(3.0)

    def serve() -> None:
        for _ in range(2):
            data, addr = srv.recvfrom(4096)
            if len(data) >= 1200:
                srv.sendto(bytes([0xC0]) + b"\x00" * 32, addr)
        srv.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()

    r_short = quic_runner._run_case({"port": port, "datagram_length": 1199, "within_ms": 250})
    assert r_short["ok"] is True and r_short["discarded"] is True
    assert AioquicBackend.events(r_short)[0].name == "discard"

    r_ok = quic_runner._run_case({"port": port, "datagram_length": 1200, "within_ms": 500})
    t.join(timeout=3.0)
    assert r_ok["ok"] is True and r_ok["replied"] is True
    assert AioquicBackend.events(r_ok)[0].name == "send"

"""Backend kiểm thử của năm giao thức: đăng ký đủ, kiểm kịch bản theo DSL riêng. run và sanity chưa cài (CT-09)."""

from __future__ import annotations

from typing import Any

import pytest

from rfcv.backends.base import DslBackend
from rfcv.builtin import BACKENDS
from rfcv.domains.rfc_protocol.sandbox.dsl import OPS, DslSpec
from rfcv.domains.rfc_protocol.schemas import ScenarioProposal
from rfcv.plugins import current_registry


def scenario(*steps: dict[str, Any], bindings: dict[str, str] | None = None) -> ScenarioProposal:
    return ScenarioProposal.model_validate(
        {"requirement_id": "X-1", "reach_state": "s", "steps": list(steps), "bindings": bindings or {}}
    )


EXPECT = {"op": "expect", "args": {"within_ms": 2000}}

# Một kịch bản hợp lệ cho mỗi backend, theo đúng cách skill giao thức hướng dẫn.
GOOD = {
    "tlsfuzzer": scenario(
        {"op": "complete_handshake"},
        {
            "op": "send_raw_record",
            "args": {
                "content_type": "application_data",
                "length": "$record.length",
                "body": "zeros",
                "encrypted": True,
            },
        },
        EXPECT,
        bindings={"record.length": "from_variant"},
    ),
    "dnspython": scenario(
        {"op": "connect", "args": {"transport": "tcp"}},
        {"op": "mutate", "args": {"field": "opt.version", "op": "set", "value": "$opt.version"}},
        {"op": "send_msg", "args": {"type": "query", "qname": "example.test.", "qtype": "SOA"}},
        EXPECT,
        bindings={"opt.version": "from_variant"},
    ),
    "h2spec": scenario(
        {"op": "connect", "args": {"tls": False}},
        {"op": "complete_handshake"},
        {"op": "send_raw_record", "args": {"type": "data", "stream_id": 1, "length": "$frame.length", "body": "zeros"}},
        EXPECT,
        bindings={"frame.length": "from_variant"},
    ),
    "aioquic": scenario(
        {"op": "connect", "args": {"version": "1"}},
        {
            "op": "send_raw_record",
            "args": {"packet_type": "initial", "datagram_length": "$datagram.payload_length", "body": "valid"},
        },
        EXPECT,
        bindings={"datagram.payload_length": "from_variant"},
    ),
    "asyncssh": scenario(
        {"op": "connect"},
        {"op": "complete_handshake", "args": {"until": "kex"}},
        {"op": "send_raw_record", "args": {"msg_number": "$msg.number", "body": "zeros", "encrypted": True}},
        EXPECT,
        bindings={"msg.number": "from_variant"},
    ),
}


def backend(name: str) -> DslBackend:
    made = current_registry().backends[name](None, None)
    assert isinstance(made, DslBackend)
    return made


def test_every_backend_is_registered_and_declares_a_dsl() -> None:
    assert set(GOOD) == set(BACKENDS) <= set(current_registry().backends)
    for name in BACKENDS:
        b = backend(name)
        assert b.name == name and isinstance(b.dsl, DslSpec)
        assert set(b.dsl.ops) <= set(OPS) and "expect" in b.dsl.ops


@pytest.mark.parametrize("name", sorted(GOOD))
def test_valid_scenario_passes(name: str) -> None:
    result = backend(name).validate(GOOD[name])
    assert result.ok, result.errors


@pytest.mark.parametrize("name", sorted(GOOD))
def test_unbound_variable_and_missing_expect_are_rejected(name: str) -> None:
    good = GOOD[name]
    assert not backend(name).validate(good.model_copy(update={"bindings": {}})).ok
    assert not backend(name).validate(good.model_copy(update={"steps": good.steps[:-1]})).ok


def test_each_protocol_has_its_own_operations_and_values() -> None:
    # DNS không có bắt tay; giá trị giao vận chỉ udp hoặc tcp.
    dns = backend("dnspython")
    errors = dns.validate(
        scenario({"op": "complete_handshake"}, {"op": "connect", "args": {"transport": "sctp"}}, EXPECT)
    ).errors
    assert any("complete_handshake" in e for e in errors) and any("transport" in e for e in errors)
    # HTTP/2 nhận đúng tên loại khung; QUIC phân biệt loại gói và loại khung.
    assert not backend("h2spec").validate(scenario({"op": "send_msg", "args": {"type": "record"}}, EXPECT)).ok
    quic = backend("aioquic")
    assert not quic.validate(scenario({"op": "send_raw_record", "args": {"packet_type": "ping"}}, EXPECT)).ok
    assert quic.validate(scenario({"op": "send_msg", "args": {"type": "ping"}}, EXPECT)).ok
    # Tham số của TLS không hợp lệ với SSH.
    assert (
        not backend("asyncssh")
        .validate(scenario({"op": "send_raw_record", "args": {"content_type": "alert"}}, EXPECT))
        .ok
    )


def test_dsl_rejects_operations_outside_the_shared_set() -> None:
    with pytest.raises(ValueError, match="ngoài DSL"):
        DslSpec(ops={"shell": frozenset()})


def test_all_five_backends_implement_runner() -> None:
    for name in BACKENDS:
        b = backend(name)
        assert callable(getattr(b, 'sanity', None)) and callable(getattr(b, 'run', None))


def test_tlsfuzzer_plain_record_before_handshake() -> None:
    tls = backend("tlsfuzzer")
    plain = {"op": "send_raw_record", "args": {"content_type": "type_99", "encrypted": False, "length": 1}}
    assert tls.validate(scenario({"op": "connect"}, plain, EXPECT)).ok
    # bản ghi rõ đi trước bắt tay: không kết hợp với complete_handshake; bản ghi mã hoá chỉ là application_data
    assert not tls.validate(scenario({"op": "complete_handshake"}, plain, EXPECT)).ok
    enc = {"op": "send_raw_record", "args": {"content_type": "alert", "encrypted": True, "length": 20}}
    assert not tls.validate(scenario({"op": "complete_handshake"}, enc, EXPECT)).ok


def test_tlsfuzzer_client_hello_variants() -> None:
    tls = backend("tlsfuzzer")
    hello = {"op": "send_msg", "args": {"type": "client_hello", "key_share": "empty_entry", "groups": "overlap"}}
    assert tls.validate(scenario({"op": "connect"}, hello, EXPECT)).ok
    assert not tls.validate(scenario({"op": "complete_handshake"}, hello, EXPECT)).ok
    bad = {"op": "send_msg", "args": {"type": "client_hello", "groups": "nonsense"}}
    assert not tls.validate(scenario({"op": "connect"}, bad, EXPECT)).ok
    req = type(tls).request(scenario({"op": "connect"}, hello, EXPECT), {}, 4433)  # type: ignore[attr-defined]
    assert req["client_hello"] == {"key_share": "empty_entry", "groups": "overlap"}


def test_openssl_as_sut_replaces_the_debian_reference_and_adds_wolfssl_reference() -> None:
    from rfcv.backends.docker_launcher import default_specs

    commit = "a" * 40
    specs = default_specs(commit, None, "openssl")
    assert specs["openssl"].image == f"rfcv/sut-openssl:{commit[:12]}" and specs["openssl"].expect_rev == commit
    assert specs["openssl"].command[0] == "/sut/openssl"
    assert specs["wolfssl"].image == "rfcv/sut-wolfssl:head" and specs["wolfssl"].expect_rev is None
    default = default_specs(commit)  # SUT là wolfSSL: OpenSSL là bản tham chiếu Debian
    assert default["openssl"].image == "rfcv/ref-openssl:latest" and default["wolfssl"].expect_rev == commit


def test_specs_from_adapter_loads_new_library_without_launcher_edits(tmp_path: Any) -> None:
    from rfcv.backends.docker_launcher import specs_from_adapter

    sut_dir = tmp_path / "sut"
    sut_dir.mkdir()
    (sut_dir / "coredns.yaml").write_text(
        "implementation: coredns\n"
        "roles:\n"
        "  server:\n"
        "    cmd: '/sut/coredns -dns.port {port} -conf /sut/Corefile'\n"
        "    port: 5354\n"
        "lifecycle:\n"
        "  ready_check: {kind: udp_query, port: '{port}'}\n",
        encoding="utf-8",
    )
    commit = "b" * 40
    specs = specs_from_adapter(tmp_path, sut_commit=commit, sut_impl="coredns")
    assert "coredns" in specs and "coredns-ref" in specs
    assert specs["coredns"].command == ("/sut/coredns", "-dns.port", "5354", "-conf", "/sut/Corefile")
    assert specs["coredns"].port == 5354 and specs["coredns"].udp is True
    assert specs["coredns"].image == f"rfcv/sut-coredns:{commit[:12]}" and specs["coredns"].expect_rev == commit
    assert specs["coredns-ref"].image == "rfcv/sut-coredns:head" and specs["coredns-ref"].expect_rev is None


def test_tlsfuzzer_supports_all_eight_dsl_ops_including_mutate_reorder_repeat() -> None:
    tls = backend("tlsfuzzer")
    sc_reorder = scenario({"op": "connect"}, {"op": "reorder", "args": {"msgs": "finished,client_hello"}}, EXPECT)
    assert tls.validate(sc_reorder).ok
    assert type(tls).request(sc_reorder, {}, 4433)["reorder"] == ["finished", "client_hello"]  # type: ignore[attr-defined]

    sc_repeat = scenario({"op": "connect"}, {"op": "repeat", "args": {"msg": "client_hello"}}, EXPECT)
    assert tls.validate(sc_repeat).ok
    assert type(tls).request(sc_repeat, {}, 4433)["repeat"] == "client_hello"  # type: ignore[attr-defined]

    sc_mutate = scenario(
        {"op": "connect"},
        {"op": "mutate", "args": {"field": "record.content_type", "op": "set", "value": "type_99"}},
        {"op": "send_raw_record", "args": {"content_type": "type_0", "encrypted": False, "length": 4}},
        EXPECT,
    )
    assert tls.validate(sc_mutate).ok
    req_mut: dict[str, Any] = type(tls).request(sc_mutate, {}, 4433)  # type: ignore[attr-defined]
    assert req_mut["content_type"] == "type_99" and req_mut["mutations"] == [
        {"field": "record.content_type", "op": "set", "value": "type_99"}
    ]

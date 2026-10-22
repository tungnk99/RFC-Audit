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


async def test_run_and_sanity_are_not_implemented_yet() -> None:
    b = backend("dnspython")
    with pytest.raises(NotImplementedError):
        await b.sanity(None)  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError):
        await b.run(GOOD["dnspython"], {}, None, 1)  # type: ignore[arg-type]

"""Adapter checker: kiểm tra hình thức adapter mẫu và adapter hỏng."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from conftest import ADAPTER_DIR
from rfcv.adapters.checker import Status, check_adapter, passed
from rfcv.adapters.manifest import load_manifest
from rfcv.domains.rfc_protocol.adapter_view import vocabulary_terms

ADAPTERS = ADAPTER_DIR.parent
PROTOCOLS = ("tls13", "dns", "http2", "quic", "ssh")


def test_real_adapter_passes_form_checks() -> None:
    items = check_adapter(ADAPTER_DIR)
    assert passed(items)
    assert {i.check for i in items if i.status is Status.SKIPPED} == {
        "build.sut",
        "oracle.stable",
        "oracle.discriminating",
        "coverage.expressiveness",
    }


@pytest.mark.parametrize("name", PROTOCOLS)
def test_every_protocol_adapter_passes_form_checks(name: str) -> None:
    items = check_adapter(ADAPTERS / name)
    assert passed(items), [(i.check, i.detail) for i in items if i.status is Status.FAIL]
    checks = {i.check for i in items}
    assert any(c.startswith("form.rbs_example:") for c in checks)
    assert any(c.startswith("form.template:") for c in checks)


def test_template_steps_are_checked_against_the_backend_dsl(tmp_path: Path) -> None:
    adapter = tmp_path / "dns"
    shutil.copytree(ADAPTERS / "dns", adapter)
    (adapter / "templates" / "broken.yaml").write_text(
        "id: dns.broken\nrequirement_types: [B]\nrfc_refs: []\nrunner: dnspython\n"
        "steps:\n  - {op: complete_handshake}\n  - {op: send_msg, args: {type: query, encrypted: true}}\n"
        "  - {op: expect, args: {within_ms: 100}}\n",
        encoding="utf-8",
    )
    items = {i.check: i for i in check_adapter(adapter, skills_root=ADAPTERS.parent / "skills")}
    broken = items["form.template_dsl:broken.yaml"]
    assert broken.status is Status.FAIL
    assert "complete_handshake" in broken.detail and "encrypted" in broken.detail


def test_vocabulary_terms_include_calls_of_every_enum_parameter() -> None:
    dns = vocabulary_terms(load_manifest(ADAPTERS / "dns"))
    assert {"respond(formerr)", "respond(badvers)", "formerr"} <= dns
    http2 = vocabulary_terms(load_manifest(ADAPTERS / "http2"))
    assert {"send_goaway(frame_size_error)", "send_rst_stream(frame_size_error)", "send(ping)"} <= http2
    tls = vocabulary_terms(load_manifest(ADAPTER_DIR))
    assert {"send_alert(record_overflow)", "record_overflow"} <= tls


def test_broken_adapter_fails(tmp_path: Path) -> None:
    (tmp_path / "adapter.yaml").write_text("adapter: x\n", encoding="utf-8")
    assert not passed(check_adapter(tmp_path))

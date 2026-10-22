"""Câu RFC gốc, đoạn chứa câu và gói ngữ cảnh được cấp vào ngữ cảnh agent (BL-20, CT-05, YD-01)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from conftest import ADAPTER_DIR
from rfcv.adapters.manifest import AdapterManifest
from rfcv.core.context_builder import ContextBuilder
from rfcv.core.ifc import TrustLabel
from rfcv.core.policy import PolicyStore
from rfcv.domains.rfc_protocol.runtime import ProtocolRuntime

RFC_DIR = Path(__file__).parent / "data" / "rfc"


def investigation(manifest: AdapterManifest, rfc_dir: Path | None) -> Any:
    rt = SimpleNamespace(manifest=manifest, config=SimpleNamespace(rfc_dir=rfc_dir))
    (inv,) = ProtocolRuntime().investigations(rt, ADAPTER_DIR / "examples")
    return inv


def test_rfc_text_is_supplied_as_trusted_context_by_the_sentence_id_of_the_rbs(manifest: AdapterManifest) -> None:
    ctx = investigation(manifest, RFC_DIR).context
    assert ctx["rfc.sentence"].value.startswith("An endpoint that receives a record")  # TLS13-0042 là RFC8446§5.2#p4s3
    assert "The length MUST NOT exceed" in ctx["rfc.paragraph"].value
    pack = ctx["rfc.context_pack"].value
    assert pack["sentence_id"] == "RFC8446§5.2#p4s3" and pack["section_path"][-1].startswith("5.2.")
    assert any("} TLSCiphertext;" in d for d in pack["definitions"])
    assert all(ctx[k].label is TrustLabel.TRUSTED for k in ("rfc.sentence", "rfc.paragraph", "rfc.context_pack"))
    assert any("} TLSCiphertext;" in d for d in ctx["rfc.definitions"].value)  # Test agent nhận khối định nghĩa


def test_without_an_rfc_input_store_agents_see_only_the_structured_requirement(
    manifest: AdapterManifest, tmp_path: Path
) -> None:
    for rfc_dir in (None, tmp_path):  # chưa đặt thư mục, và thư mục rỗng
        ctx = investigation(manifest, rfc_dir).context
        assert "requirement.structured" in ctx and not [k for k in ctx if k.startswith("rfc.")]


def test_a_sentence_id_the_rfc_does_not_contain_is_left_out_not_invented(
    manifest: AdapterManifest, tmp_path: Path
) -> None:
    other = tmp_path / "rfc8446.xml"
    other.write_text(
        '<rfc number="8446"><middle><section pn="section-1"><name>Intro</name>'
        '<t pn="section-1-1">Only this <bcp14>MUST</bcp14> exist.</t></section></middle></rfc>',
        encoding="utf-8",
    )
    ctx = investigation(manifest, tmp_path).context
    assert not [k for k in ctx if k.startswith("rfc.")]


def test_a_file_that_is_not_rfcxml_is_an_error_not_silently_ignored(manifest: AdapterManifest, tmp_path: Path) -> None:
    (tmp_path / "rfc8446.xml").write_text("<rfc><front/></rfc>", encoding="utf-8")
    with pytest.raises(ValueError, match="RFCXML"):
        investigation(manifest, tmp_path)


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("verifier", {"rfc.sentence", "rfc.paragraph"}),  # phản biện cần câu và đoạn chứa câu để xét vị trí mã
        ("code_reader", {"rfc.sentence", "rfc.context_pack"}),
        ("planner", {"rfc.sentence"}),
    ],
)
def test_each_role_receives_exactly_the_rfc_fields_it_declares(
    role: str, expected: set[str], manifest: AdapterManifest, policy: PolicyStore
) -> None:
    built = ContextBuilder(policy).build(role, investigation(manifest, RFC_DIR).context)
    assert {k for k in built if k.startswith("rfc.")} == expected
    assert all(built[k]["label"] == "TRUSTED" for k in expected)


def test_the_test_agent_sees_only_the_definition_blocks_not_the_sentence(
    manifest: AdapterManifest, policy: PolicyStore
) -> None:
    """Test cần cấu trúc bản ghi (khối struct) để dựng kịch bản, nhưng không nhận câu hay đoạn RFC nó không khai báo."""
    built = ContextBuilder(policy).build("tester", investigation(manifest, RFC_DIR).context)
    assert [k for k in built if k.startswith("rfc.")] == ["rfc.definitions"]

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


def test_every_verdict_records_the_exact_rfc_text_it_was_judged_against(manifest: AdapterManifest) -> None:
    """BL-26: kết luận ghi định danh câu, băm câu và tài liệu nguồn (RFC, định dạng, băm), kể cả khi chưa có bản RFC."""
    from rfcv.common.hashing import text_hash
    from rfcv.evidence.verdict_engine import StopReason, decide

    inv = investigation(manifest, RFC_DIR)
    req = inv.requirement
    spec = decide(req, [], StopReason.BUDGET).to_json()["spec"]
    assert spec["ref"] == "RFC8446§5.2#p4s3"
    assert spec["sentence_hash"] == text_hash(inv.context["rfc.sentence"].value)
    assert spec["document"].startswith("RFC8446 xml sha256:") and len(spec["document"]) == len("RFC8446 xml ") + 71
    # Không có bản RFC: vẫn ghi định danh câu nhưng không bịa băm; người đọc biết kết luận dựa trên RBS.
    bare = decide(investigation(manifest, None).requirement, [], StopReason.BUDGET).to_json()["spec"]
    assert bare == {"ref": "RFC8446§5.2#p4s3", "sentence_hash": "", "document": ""}


def test_the_document_digest_follows_the_text_and_the_format(manifest: AdapterManifest, tmp_path: Path) -> None:
    """Cùng RFC, khác nội dung hay khác định dạng (XML so với TXT) là hai nguồn khác nhau: định danh đoạn không chung."""
    from rfcv.domains.rfc_protocol.rfc_gate import RfcDocument

    xml = (RFC_DIR / "rfc8446.xml").read_text(encoding="utf-8")
    edited = xml.replace("The length (in bytes)", "The size (in bytes)")
    assert edited != xml
    a, b = RfcDocument(xml, 8446), RfcDocument(edited, 8446)
    txt = RfcDocument.from_text((RFC_DIR / "rfc9999.txt").read_text(encoding="utf-8"), 9999)
    assert a.source != b.source and a.source.split()[1] == "xml" and txt.source.split()[1] == "txt"


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

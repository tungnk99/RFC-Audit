from __future__ import annotations

from pathlib import Path

import pytest

from rfcv.domains.rfc_protocol.rfc_gate import RfcDocument, extract_requirements, primary_modal, split_sentences

XML = """<?xml version="1.0" encoding="UTF-8"?>
<rfc number="8446"><front/><middle>
 <section pn="section-5"><name>Record Protocol</name>
  <t pn="section-5-1">Intro text without keywords.</t>
  <section pn="section-5.2"><name>Record Payload Protection</name>
   <t pn="section-5.2-1">The length (in bytes) of the following TLSCiphertext.encrypted_record.</t>
   <t pn="section-5.2-4">The length <bcp14>MUST NOT</bcp14> exceed 2^14 + 256 bytes.
     An endpoint that receives a record that exceeds this length <bcp14>MUST</bcp14> terminate
     the connection with a "record_overflow" alert.</t>
  </section>
 </section>
 <section pn="section-6"><name>Alert Protocol</name>
  <t pn="section-6-2">Implementations <bcp14>SHOULD</bcp14> send alerts, e.g. a close_notify. Done.</t>
 </section>
</middle></rfc>"""


def test_extract_sentences_with_stable_ids() -> None:
    reqs = extract_requirements(XML, 8446)
    assert [r.sentence_id for r in reqs] == ["RFC8446§5.2#p4s1", "RFC8446§5.2#p4s2", "RFC8446§6#p2s1"]
    assert [r.modal for r in reqs] == ["MUST NOT", "MUST", "SHOULD"]
    assert reqs[0].section_path == ("5. Record Protocol", "5.2. Record Payload Protection")
    assert reqs[0].text_hash.startswith("sha256:")


def test_scope_filter() -> None:
    assert {r.section for r in extract_requirements(XML, 8446, ["5"])} == {"5.2"}
    assert {r.section for r in extract_requirements(XML, 8446, ["6"])} == {"6"}


def test_sentence_split_keeps_abbreviations() -> None:
    assert split_sentences("Send alerts, e.g. a close_notify. Done.") == ["Send alerts, e.g. a close_notify.", "Done."]


def test_lowercase_must_is_not_normative() -> None:
    assert primary_modal("the client must do it") is None
    assert primary_modal("The server MUST NOT send") == "MUST NOT"


# ---- tra câu theo định danh và gói ngữ cảnh (BL-20) --------------------------------------------------------------------

RFC_EXCERPT = Path(__file__).parent / "data" / "rfc" / "rfc8446.xml"


def excerpt() -> RfcDocument:
    return RfcDocument(RFC_EXCERPT.read_text(encoding="utf-8"), 8446)


def test_lookup_finds_the_sentence_its_paragraph_and_neighbours() -> None:
    ctx = excerpt().lookup("RFC8446§5.2#p4s3")
    assert ctx is not None
    assert ctx.sentence.startswith("An endpoint that receives a record") and ctx.sentence.endswith(
        '"record_overflow" alert.'
    )
    assert ctx.sentence_index == 3 and ctx.next_sentence is None
    assert ctx.previous_sentence is not None and ctx.previous_sentence.startswith("The length MUST NOT exceed")
    assert ctx.paragraph.startswith("The length (in bytes)") and ctx.sentence in ctx.paragraph
    assert ctx.section_path == ("5. Record Protocol", "5.2. Record Payload Protection")


def test_lookup_agrees_with_the_extractor_on_every_sentence_id() -> None:
    doc = excerpt()
    for req in extract_requirements(RFC_EXCERPT.read_text(encoding="utf-8"), 8446):
        ctx = doc.lookup(req.sentence_id)
        assert ctx is not None and ctx.sentence == req.text and ctx.section_path == req.section_path


def test_context_pack_carries_the_definitions_that_the_sentence_names() -> None:
    ctx = excerpt().lookup("RFC8446§5.2#p4s2")
    assert ctx is not None
    assert len(ctx.definitions) == 1 and "} TLSCiphertext;" in ctx.definitions[0]  # TLSInnerPlaintext không được nhắc
    pack = ctx.context_pack()
    assert pack["sentence_id"] == "RFC8446§5.2#p4s2" and pack["section_path"] == list(ctx.section_path)
    assert "sentence" not in pack and "paragraph" not in pack  # hai trường này được cấp riêng


@pytest.mark.parametrize(
    "sentence_id",
    ["RFC8446§5.2#p4s9", "RFC8446§5.2#p9s1", "RFC8446§9.9#p1s1", "RFC9846§5.2#p4s3", "không phải định danh", ""],
)
def test_lookup_returns_none_for_ids_that_do_not_resolve(sentence_id: str) -> None:
    assert excerpt().lookup(sentence_id) is None


def test_at_most_three_definition_blocks_and_each_is_truncated() -> None:
    blocks = "".join(
        f"<sourcecode>struct {{ uint8 field_{i}; }} TLSCiphertext{'x' * 2000};</sourcecode>" for i in range(5)
    )
    xml = (
        '<rfc number="1"><middle><section pn="section-1"><name>S</name>'
        f'<t pn="section-1-1">The TLSCiphertext{"x" * 2000} structure <bcp14>MUST</bcp14> be sent.</t>{blocks}'
        "</section></middle></rfc>"
    )
    ctx = RfcDocument(xml, 1).lookup("RFC1§1#p1s1")
    assert ctx is not None and len(ctx.definitions) == 3 and all(len(d) <= 1200 for d in ctx.definitions)


def test_a_document_that_is_not_rfcxml_is_rejected() -> None:
    with pytest.raises(ValueError, match="RFCXML"):
        RfcDocument("<rfc><front/></rfc>", 1)

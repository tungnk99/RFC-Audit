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


# ---- phủ toàn văn: đoạn lồng, phụ lục, tham chiếu và lũy thừa (BL-21) ------------------------------------------------

STRUCTURED = """<rfc number="1"><front/>
<middle>
 <section pn="section-1"><name>Top</name>
  <t pn="section-1-1">Intro <bcp14>MUST</bcp14> hold.</t>
  <ul pn="section-1-2">
   <li pn="section-1-2.1"><t pn="section-1-2.1.1">The peer <bcp14>MUST</bcp14> reply. It <bcp14>MAY</bcp14> wait.</t></li>
   <li pn="section-1-2.2"><t pn="section-1-2.2.1">No keyword here.</t></li>
  </ul>
  <dl pn="section-1-3"><dt>length</dt><dd pn="section-1-3.1"><t pn="section-1-3.1.1">It <bcp14>SHALL</bcp14> fit.</t></dd></dl>
  <section pn="section-1.1"><name>Child</name>
   <t pn="section-1.1-1">Child <bcp14>SHOULD</bcp14> inherit nothing.</t>
  </section>
 </section>
</middle>
<back>
 <section pn="section-appendix.c"><name>Implementation Notes</name>
  <t pn="section-appendix.c-1">Servers <bcp14>SHOULD</bcp14> issue tickets.</t>
 </section>
</back></rfc>"""


def test_paragraphs_nested_in_lists_and_definitions_are_extracted_with_dotted_ids() -> None:
    ids = {r.sentence_id: r for r in extract_requirements(STRUCTURED, 1)}
    assert "RFC1§1#p2.1.1s1" in ids and ids["RFC1§1#p2.1.1s1"].paragraph == "2.1.1"
    assert "RFC1§1#p2.1.1s2" in ids and "RFC1§1#p3.1.1s1" in ids
    assert not [i for i in ids if "p2.2.1" in i]  # đoạn không có từ khoá thì không có câu


def test_a_child_section_paragraph_is_not_counted_for_its_parent_too() -> None:
    reqs = extract_requirements(STRUCTURED, 1)
    assert [r.sentence_id for r in reqs].count("RFC1§1.1#p1s1") == 1
    assert len({r.sentence_id for r in reqs}) == len(reqs)


def test_appendix_sentences_are_extracted_and_scopable() -> None:
    assert [r.sentence_id for r in extract_requirements(STRUCTURED, 1, ["appendix.c"])] == ["RFC1§appendix.c#p1s1"]
    assert any(r.section == "appendix.c" for r in extract_requirements(STRUCTURED, 1))


def test_lookup_resolves_nested_and_appendix_ids() -> None:
    doc = RfcDocument(STRUCTURED, 1)
    nested = doc.lookup("RFC1§1#p2.1.1s2")
    assert (
        nested is not None
        and nested.sentence == "It MAY wait."
        and nested.paragraph == "The peer MUST reply. It MAY wait."
    )
    appendix = doc.lookup("RFC1§appendix.c#p1s1")
    assert appendix is not None and appendix.section_path == ("appendix.c. Implementation Notes",)


def test_every_extracted_id_resolves_back_to_the_same_sentence_on_structured_text() -> None:
    doc = RfcDocument(STRUCTURED, 1)
    for r in extract_requirements(STRUCTURED, 1):
        ctx = doc.lookup(r.sentence_id)
        assert ctx is not None and ctx.sentence == r.text


def test_superscripts_and_cross_references_are_rendered_as_a_reader_sees_them() -> None:
    reqs = {r.sentence_id: r.text for r in extract_requirements(RFC_EXCERPT.read_text(encoding="utf-8"), 8446)}
    s = reqs["RFC8446§5.2#p4s2"]
    assert "2^14 + 256 bytes" in s and "214" not in s  # ngưỡng độ dài của TLS13-0042 không được thành 214
    assert "(see Section 5.4 and [RFC5280], Section 3.2)" in s


def test_render_text_covers_the_reference_forms() -> None:
    from xml.etree import ElementTree as ET

    from rfcv.domains.rfc_protocol.rfc_gate import render_text

    def r(xml: str) -> str:
        return render_text(ET.fromstring(xml))

    assert r('<t>see <xref derivedContent="Section 4.7.1"/>.</t>') == "see Section 4.7.1."
    assert r('<t>as in <xref derivedContent="RSA"/>.</t>') == "as in [RSA]."
    assert r('<t><xref section="3" sectionFormat="of" derivedContent="RFC7250"/></t>') == "Section 3 of [RFC7250]"
    assert r('<t><xref section="3" sectionFormat="parens" derivedContent="RFC7250"/></t>') == "[RFC7250] (Section 3)"
    assert r("<t>2<sup>32</sup> and x<sub>i</sub></t>") == "2^32 and x_i"
    assert r("<t>  a\n   b <bcp14>MUST</bcp14>  c </t>") == "a b MUST c"

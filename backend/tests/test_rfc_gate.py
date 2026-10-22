from __future__ import annotations

from pathlib import Path

import pytest

from rfcv.domains.rfc_protocol.rfc_gate import (
    RfcDocument,
    extract_requirements,
    extract_requirements_text,
    primary_modal,
    split_sentences,
)

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
    # Câu nói về chính các từ khoá không đặt yêu cầu (mẫu BCP 14, RFC 2181), nhưng câu có yêu cầu thật thì giữ.
    boilerplate = (
        'The key words "MUST", "MAY" in this document are to be interpreted as described in RFC 2119 [RFC2119].'
    )
    assert primary_modal(boilerplate) is None
    assert primary_modal("This memo does not use the oft used expressions MUST, SHOULD, MAY.") is None
    assert primary_modal("An endpoint MUST follow RFC 2119 conventions.") == "MUST"


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
    # Chữ của tác giả trong <xref> được giữ (RFC 9113: "as a connection error (Section 5.4.1) of type ...").
    as_error = '<t>as a <xref format="default" derivedContent="Section 5.4.1">connection error</xref> of type</t>'
    assert r(as_error) == "as a connection error (Section 5.4.1) of type"
    assert r('<t>of <xref format="none" derivedContent="">FRAME_SIZE_ERROR</xref></t>') == "of FRAME_SIZE_ERROR"
    assert r('<t>see <xref derivedContent="RFC8446">TLS 1.3</xref></t>') == "see TLS 1.3 [RFC8446]"
    assert r("<t>2<sup>32</sup> and x<sub>i</sub></t>") == "2^32 and x_i"
    assert r("<t>  a\n   b <bcp14>MUST</bcp14>  c </t>") == "a b MUST c"


# ---- bản TXT (BL-22): RFC cũ không có RFCXML v3, ví dụ DNS và SSH --------------------------------------------------------

RFC_TXT = Path(__file__).parent / "data" / "rfc" / "rfc9999.txt"


def txt_doc() -> RfcDocument:
    return RfcDocument.from_text(RFC_TXT.read_text(encoding="utf-8"), 9999)


def test_txt_sections_skip_front_matter_toc_headers_and_footers() -> None:
    doc = txt_doc()
    assert [s for s in ("1", "2", "2.1", "appendix.a") if doc.has_section(s)] == ["1", "2", "2.1", "appendix.a"]
    path, paragraphs = doc.section("2")  # type: ignore[misc]
    assert path == ("2. Message Format",)
    assert not any("[Page" in t or t.startswith("RFC 9999") for _, t in paragraphs)
    assert doc.section("2.1")[0] == ("2. Message Format", "2.1. Errors")  # type: ignore[index]


def test_txt_normative_sentences_have_the_same_id_scheme_as_xml() -> None:
    by_id = {r.sentence_id: r for r in extract_requirements_text(RFC_TXT.read_text(encoding="utf-8"), 9999)}
    assert by_id["RFC9999§2#p2s1"].text == "The Length field MUST NOT exceed 512."
    assert by_id["RFC9999§2#p2s2"].modal == "MUST" and "(see Section 2.1)" in by_id["RFC9999§2#p2s2"].text
    assert by_id["RFC9999§1#p1s2"].text == "Implementations MUST follow it."
    assert "RFC9999§appendix.a#p1s1" in by_id


def test_txt_indented_definition_lists_are_prose_but_figures_and_tables_are_blocks() -> None:
    """Danh sách định nghĩa thụt sâu vẫn là văn xuôi quy phạm (từng bị tính nhầm là hình); `||` giữa câu không phải nét vẽ."""
    doc = txt_doc()
    texts = [t for _, t in doc.section("2")[1]]  # type: ignore[index]
    assert any("There MUST be at least four bytes of padding." in t for t in texts)
    blocks = doc._sections["2"].blocks  # pyright: ignore[reportPrivateUsage]
    assert any("+--------+" in b for b in blocks) and any("FORMERR    1" in b for b in blocks)


def test_txt_lookup_and_tools_work_like_xml() -> None:
    doc = txt_doc()
    ctx = doc.lookup("RFC9999§2#p2s1")
    assert ctx is not None and ctx.next_sentence is not None and ctx.next_sentence.startswith("A receiver that gets")
    assert doc.search("FORMERR") and doc.definitions("FORMERR")


def test_old_rfcs_without_indented_body_are_read_too() -> None:
    """RFC rất cũ (ví dụ 1035) viết thân văn bản từ cột 0."""
    lines = []
    for n in range(1, 25):
        lines += [
            f"{n}. Section {n}",
            "",
            f"This is section {n}. A server MUST answer within {n} seconds.",
            "Another line here.",
            "",
        ]
    doc = RfcDocument.from_text("\n".join(lines), 1)
    assert doc.has_section("3") and doc.lookup("RFC1§3#p1s2") is not None


def test_load_prefers_xml_and_falls_back_to_txt(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from rfcv.domains.rfc_protocol.rfc_gate import load_rfc_documents

    (tmp_path / "rfc9999.txt").write_text(RFC_TXT.read_text(encoding="utf-8"), encoding="utf-8")
    manifest = SimpleNamespace(specs=[SimpleNamespace(doc="RFC9999")])
    assert load_rfc_documents(manifest, tmp_path)[9999].has_section("2.1")

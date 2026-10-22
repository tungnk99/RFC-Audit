from __future__ import annotations

from rfcv.domains.rfc_protocol.rfc_gate import extract_requirements, primary_modal, split_sentences

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

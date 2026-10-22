"""RFC gate: tách câu yêu cầu BCP 14 từ bản RFCXML v3 chính thức (tài liệu cung cấp RFC, mục 5).

Hoàn toàn tất định, không dùng LLM. Dùng bản XML đã "prep" của RFC Editor: mỗi <section> và <t>
có thuộc tính `pn` (ví dụ section-5.2, section-5.2-3), nên số mục và số đoạn không phải đoán.
Định danh câu ổn định: RFC8446§5.2#p3s2 (mục 5.2, đoạn 3, câu 2), kèm hash văn bản câu.
Bản TXT của RFC cũ (DNS, SSH) cần bộ phân tích riêng: chưa cài đặt ở mốc này.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rfcv.common.hashing import text_hash

KEYWORDS = (
    "MUST NOT",
    "SHALL NOT",
    "SHOULD NOT",
    "NOT RECOMMENDED",
    "MUST",
    "REQUIRED",
    "SHALL",
    "SHOULD",
    "RECOMMENDED",
    "MAY",
    "OPTIONAL",
)
_KEYWORD_RE = re.compile(r"\b(" + "|".join(k.replace(" ", r"\s+") for k in KEYWORDS) + r")\b")
# Tách câu: sau . ! ? và khoảng trắng, trước chữ hoa, chữ số hoặc dấu ngoặc kép. Bỏ qua viết tắt thường gặp.
_ABBREV = ("e.g.", "i.e.", "etc.", "Sec.", "cf.", "vs.")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])")
_PN_SECTION = re.compile(r"^section-([0-9A-Za-z.]+)$")
# Đoạn trực tiếp của mục có pn `section-5.2-4`; đoạn trong danh sách hay định nghĩa lồng có pn `section-5.2-4.3.1`.
_PN_PARA = re.compile(r"^section-([0-9A-Za-z.]+)-(\d+(?:\.\d+)*)$")


@dataclass(frozen=True)
class RfcSentence:
    sentence_id: str
    rfc: int
    section: str
    paragraph: str  # "4" hoặc "4.3.1" với đoạn lồng trong danh sách
    index: int
    modal: str
    text: str
    text_hash: str
    section_path: tuple[str, ...]


def _xref(x: ET.Element) -> str:
    """Chữ mà bản dựng hiển thị cho một `<xref>` (bản prep để trống nội dung, chữ nằm ở `derivedContent`): "Section 4.7.1",
    "Figure 2", hoặc tài liệu tham khảo dạng "[RFC5280]" kèm mục nếu có."""
    shown = x.get("derivedContent") or "".join(x.itertext()).strip()
    if shown.startswith(("Section", "Appendix", "Figure", "Table")):
        return shown
    ref = f"[{shown}]" if shown else ""
    section = x.get("section")
    if not section or not ref:
        return ref
    match x.get("sectionFormat"):
        case "of":
            return f"Section {section} of {ref}"
        case "parens":
            return f"{ref} (Section {section})"
        case _:
            return f"{ref}, Section {section}"


def render_text(elem: ET.Element) -> str:
    """Văn bản một phần tử như người đọc thấy: `<xref>` thành chữ hiển thị, `<sup>14</sup>` thành `^14` (2^14 chứ không
    phải 214, vì ngưỡng độ dài nằm ở đây), `<sub>` thành `_x`. Khoảng trắng được gộp."""

    def walk(e: ET.Element) -> str:
        out = [e.text or ""]
        for child in e:
            match child.tag:
                case "xref":
                    out.append(_xref(child))
                case "sup":
                    out.append("^" + walk(child))
                case "sub":
                    out.append("_" + walk(child))
                case _:
                    out.append(walk(child))
            out.append(child.tail or "")
        return "".join(out)

    return " ".join(walk(elem).split())


def split_sentences(text: str) -> list[str]:
    protected = text
    for i, ab in enumerate(_ABBREV):
        protected = protected.replace(ab, f"\x00{i}\x00")
    parts = _SENT_SPLIT.split(protected)
    out: list[str] = []
    for p in parts:
        for i, ab in enumerate(_ABBREV):
            p = p.replace(f"\x00{i}\x00", ab)
        if p.strip():
            out.append(" ".join(p.split()))
    return out


def primary_modal(sentence: str) -> str | None:
    found = [" ".join(m.group(1).split()) for m in _KEYWORD_RE.finditer(sentence)]
    return found[0] if found else None


def _in_scope(section: str, scope: Iterable[str] | None) -> bool:
    if scope is None:
        return True
    return any(section == s or section.startswith(s + ".") for s in scope)


def _walk(elem: ET.Element, path: tuple[str, ...]) -> Iterator[tuple[str, tuple[str, ...], ET.Element]]:
    for child in elem:
        if child.tag == "section":
            m = _PN_SECTION.match(child.get("pn", ""))
            name = child.find("name")
            title = "".join(name.itertext()).strip() if name is not None else ""
            if m:
                sec_path = (*path, f"{m.group(1)}. {title}".strip())
                yield m.group(1), sec_path, child
                yield from _walk(child, sec_path)
            else:
                yield from _walk(child, path)


def _own(sec: ET.Element, tags: tuple[str, ...]) -> Iterator[ET.Element]:
    """Phần tử thuộc riêng mục `sec`: duyệt cả danh sách và định nghĩa lồng, nhưng không đi vào mục con."""
    for child in sec:
        if child.tag == "section":
            continue
        if child.tag in tags:
            yield child
        yield from _own(child, tags)


def _parts(root: ET.Element) -> list[ET.Element]:
    """Thân văn bản (`middle`) và phụ lục (`back`): phụ lục cũng chứa câu quy phạm (ví dụ ghi chú triển khai)."""
    middle = root.find("middle")
    if middle is None:
        raise ValueError("không có phần <middle>: có phải bản RFCXML v3 không?")
    back = root.find("back")
    return [middle] if back is None else [middle, back]


def _all_sections(root: ET.Element) -> Iterator[tuple[str, tuple[str, ...], ET.Element]]:
    for part in _parts(root):
        yield from _walk(part, ())


def extract_requirements(
    xml_text: str, rfc_number: int, sections_in_scope: Iterable[str] | None = None
) -> list[RfcSentence]:
    return _requirements(ET.fromstring(xml_text), rfc_number, sections_in_scope)


def _requirements(root: ET.Element, rfc_number: int, sections_in_scope: Iterable[str] | None) -> list[RfcSentence]:
    scope = list(sections_in_scope) if sections_in_scope is not None else None
    out: list[RfcSentence] = []
    for section, sec_path, sec in _all_sections(root):
        if not _in_scope(section, scope):
            continue
        for t in _own(sec, ("t",)):
            m = _PN_PARA.match(t.get("pn", ""))
            if not m or m.group(1) != section:
                continue
            para = m.group(2)
            text = render_text(t)
            for idx, sentence in enumerate(split_sentences(text), start=1):
                modal = primary_modal(sentence)
                if modal is None:
                    continue
                out.append(
                    RfcSentence(
                        sentence_id=f"RFC{rfc_number}§{section}#p{para}s{idx}",
                        rfc=rfc_number,
                        section=section,
                        paragraph=para,
                        index=idx,
                        modal=modal,
                        text=sentence,
                        text_hash=text_hash(sentence),
                        section_path=sec_path,
                    )
                )
    return out


# ---- tra một câu theo định danh, kèm gói ngữ cảnh (tài liệu cung cấp RFC, mục 5.3) -------------------------------------

_SENTENCE_ID = re.compile(r"^RFC(\d+)§([0-9A-Za-z.]+)#p(\d+(?:\.\d+)*)s(\d+)$")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
MAX_DEFINITIONS = 3  # số khối định nghĩa tối đa trong một gói
MAX_DEFINITION_CHARS = 1200
_BCP14_WORDS = frozenset(w for k in KEYWORDS for w in k.split())


@dataclass(frozen=True)
class RfcContext:
    """Câu RFC cùng đoạn chứa nó và phần ngữ cảnh đủ để hiểu câu mà không đọc cả RFC. Đầu vào TRUSTED."""

    sentence_id: str
    rfc: int
    section: str
    section_path: tuple[str, ...]
    sentence: str
    sentence_index: int
    paragraph: str
    previous_sentence: str | None
    next_sentence: str | None
    definitions: tuple[str, ...]

    def context_pack(self) -> dict[str, object]:
        """Gói ngữ cảnh của câu (không lặp lại câu và đoạn, vốn là hai trường riêng)."""
        return {
            "sentence_id": self.sentence_id,
            "section_path": list(self.section_path),
            "previous_sentence": self.previous_sentence,
            "next_sentence": self.next_sentence,
            "definitions": list(self.definitions),
        }


def _distinctive(text: str) -> set[str]:
    """Tên kiểu, trường, hằng trong văn bản (có chữ hoa giữa tên, gạch dưới hoặc viết hoa đầu), bỏ từ khoá BCP 14."""
    out: set[str] = set()
    for tok in _IDENT.findall(text):
        if len(tok) < 4 or tok in _BCP14_WORDS:
            continue
        if "_" in tok or any(c.isupper() for c in tok[1:]) or (tok[0].isupper() and tok.upper() != tok):
            out.add(tok)
    return out


class RfcDocument:
    """Một bản RFCXML v3 đã đọc, tra câu theo định danh ổn định (`RFC8446§5.2#p4s3`)."""

    def __init__(self, xml_text: str, rfc_number: int) -> None:
        root = ET.fromstring(xml_text)
        self.rfc = rfc_number
        self._root = root
        self._sections = {sec: (path, elem) for sec, path, elem in _all_sections(root)}

    def lookup(self, sentence_id: str) -> RfcContext | None:
        """Câu theo định danh, hoặc None nếu định danh sai, thuộc RFC khác, hay mục/đoạn/câu không có."""
        m = _SENTENCE_ID.match(sentence_id)
        if m is None or int(m.group(1)) != self.rfc:
            return None
        section, para, idx = m.group(2), m.group(3), int(m.group(4))
        found = self._sections.get(section)
        if found is None:
            return None
        path, elem = found
        paragraph = next((t for t in _own(elem, ("t",)) if t.get("pn") == f"section-{section}-{para}"), None)
        if paragraph is None:
            return None
        text = render_text(paragraph)
        sentences = split_sentences(text)
        if not 1 <= idx <= len(sentences):
            return None
        sentence = sentences[idx - 1]
        return RfcContext(
            sentence_id=sentence_id,
            rfc=self.rfc,
            section=section,
            section_path=path,
            sentence=sentence,
            sentence_index=idx,
            paragraph=text,
            previous_sentence=sentences[idx - 2] if idx >= 2 else None,
            next_sentence=sentences[idx] if idx < len(sentences) else None,
            definitions=self._definitions(elem, sentence + " " + text),
        )

    # ---- tra cứu cho công cụ `rfc.*` của agent -------------------------------------------------------------------

    def has_section(self, section: str) -> bool:
        return section in self._sections

    def sentences(self, section: str) -> list[RfcSentence]:
        """Câu quy phạm (BCP 14) của một mục và các mục con, kèm định danh ổn định."""
        return _requirements(self._root, self.rfc, [section])

    def section(self, section: str) -> tuple[tuple[str, ...], list[tuple[str, str]]] | None:
        """Đường dẫn mục và các đoạn thuộc riêng mục (id đoạn, văn bản), theo thứ tự trong tài liệu; None nếu không có mục."""
        found = self._sections.get(section)
        if found is None:
            return None
        path, elem = found
        out: list[tuple[str, str]] = []
        for t in _own(elem, ("t",)):
            m = _PN_PARA.match(t.get("pn", ""))
            if m and m.group(1) == section:
                out.append((f"RFC{self.rfc}§{section}#p{m.group(2)}", render_text(t)))
        return path, out

    def search(self, term: str, limit: int = 30) -> list[tuple[str, str]]:
        """Các đoạn có chứa `term` (không phân biệt hoa thường): (id đoạn, đoạn trích quanh chỗ khớp)."""
        needle = term.lower()
        hits: list[tuple[str, str]] = []
        for sec in self._sections:
            found = self.section(sec)
            if found is None:
                continue
            for pid, text in found[1]:
                i = text.lower().find(needle)
                if i >= 0:
                    hits.append((pid, text[max(0, i - 80) : i + len(term) + 120]))
                    if len(hits) >= limit:
                        return hits
        return hits

    def definitions(self, name: str, limit: int = MAX_DEFINITIONS) -> list[tuple[str, str]]:
        """Khối `sourcecode` hay `artwork` nhắc tới `name` (đúng nguyên từ): (số mục, nội dung, cắt ở MAX_DEFINITION_CHARS)."""
        out: list[tuple[str, str]] = []
        for sec, (_, elem) in self._sections.items():
            for block in _own(elem, ("sourcecode", "artwork")):
                body = "".join(block.itertext()).strip("\n")
                if name in _IDENT.findall(body):
                    out.append((sec, body[:MAX_DEFINITION_CHARS]))
                    if len(out) >= limit:
                        return out
        return out

    @staticmethod
    def _definitions(section: ET.Element, text: str) -> tuple[str, ...]:
        """Khối `sourcecode` hay `artwork` của mục có nhắc tên kiểu, trường, hằng trong câu hay đoạn; nhiều tên nhất trước."""
        names = _distinctive(text)
        scored: list[tuple[int, int, str]] = []
        for order, block in enumerate(_own(section, ("sourcecode", "artwork"))):
            body = "".join(block.itertext()).strip("\n")
            hits = len(names & set(_IDENT.findall(body)))
            if hits:
                scored.append((-hits, order, body[:MAX_DEFINITION_CHARS]))
        return tuple(body for _, _, body in sorted(scored)[:MAX_DEFINITIONS])


def load_rfc_documents(manifest: Any, rfc_dir: Path | None) -> dict[int, RfcDocument]:
    """Bản RFCXML của các văn bản trong phạm vi adapter (`specs[].doc`, ví dụ RFC8446) đọc từ `rfc_dir/rfc<số>.xml`.

    Thư mục chưa đặt hay thiếu tệp thì bỏ qua văn bản đó; tệp có mà không phải RFCXML v3 thì báo lỗi, không im lặng.
    """
    docs: dict[int, RfcDocument] = {}
    if rfc_dir is None:
        return docs
    for spec in manifest.specs:
        m = re.fullmatch(r"RFC(\d+)", str(spec.doc))
        if m is None:
            continue
        number = int(m.group(1))
        path = rfc_dir / f"rfc{number}.xml"
        if path.is_file():
            docs[number] = RfcDocument(path.read_text(encoding="utf-8"), number)
    return docs


def lookup_sentence(docs: dict[int, RfcDocument], sentence_id: str) -> RfcContext | None:
    m = _SENTENCE_ID.match(sentence_id)
    doc = docs.get(int(m.group(1))) if m else None
    return doc.lookup(sentence_id) if doc else None

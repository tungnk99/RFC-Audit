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
_PN_PARA = re.compile(r"^section-([0-9A-Za-z.]+)-(\d+)$")


@dataclass(frozen=True)
class RfcSentence:
    sentence_id: str
    rfc: int
    section: str
    paragraph: int
    index: int
    modal: str
    text: str
    text_hash: str
    section_path: tuple[str, ...]


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


def extract_requirements(
    xml_text: str, rfc_number: int, sections_in_scope: Iterable[str] | None = None
) -> list[RfcSentence]:
    root = ET.fromstring(xml_text)
    middle = root.find("middle")
    if middle is None:
        raise ValueError("không có phần <middle>: có phải bản RFCXML v3 không?")
    scope = list(sections_in_scope) if sections_in_scope is not None else None
    out: list[RfcSentence] = []
    for section, sec_path, sec in _walk(middle, ()):
        if not _in_scope(section, scope):
            continue
        for t in sec.findall("t"):
            m = _PN_PARA.match(t.get("pn", ""))
            if not m:
                continue
            para = int(m.group(2))
            text = " ".join("".join(t.itertext()).split())
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

_SENTENCE_ID = re.compile(r"^RFC(\d+)§([0-9A-Za-z.]+)#p(\d+)s(\d+)$")
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
        middle = root.find("middle")
        if middle is None:
            raise ValueError("không có phần <middle>: có phải bản RFCXML v3 không?")
        self.rfc = rfc_number
        self._sections = {sec: (path, elem) for sec, path, elem in _walk(middle, ())}

    def lookup(self, sentence_id: str) -> RfcContext | None:
        """Câu theo định danh, hoặc None nếu định danh sai, thuộc RFC khác, hay mục/đoạn/câu không có."""
        m = _SENTENCE_ID.match(sentence_id)
        if m is None or int(m.group(1)) != self.rfc:
            return None
        section, para, idx = m.group(2), int(m.group(3)), int(m.group(4))
        found = self._sections.get(section)
        if found is None:
            return None
        path, elem = found
        paragraph = next((t for t in elem.findall("t") if t.get("pn") == f"section-{section}-{para}"), None)
        if paragraph is None:
            return None
        text = " ".join("".join(paragraph.itertext()).split())
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

    @staticmethod
    def _definitions(section: ET.Element, text: str) -> tuple[str, ...]:
        """Khối `sourcecode` hay `artwork` của mục có nhắc tên kiểu, trường, hằng trong câu hay đoạn; nhiều tên nhất trước."""
        names = _distinctive(text)
        scored: list[tuple[int, int, str]] = []
        for order, block in enumerate([*section.findall("sourcecode"), *section.findall("artwork")]):
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

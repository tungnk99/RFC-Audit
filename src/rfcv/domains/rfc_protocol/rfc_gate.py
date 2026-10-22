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

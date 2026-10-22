"""RFC gate: tách câu yêu cầu BCP 14 từ bản RFCXML v3 chính thức (tài liệu cung cấp RFC, mục 5).

Hoàn toàn tất định, không dùng LLM. Dùng bản XML đã "prep" của RFC Editor: mỗi <section> và <t>
có thuộc tính `pn` (ví dụ section-5.2, section-5.2-3), nên số mục và số đoạn không phải đoán.
Định danh câu ổn định: RFC8446§5.2#p3s2 (mục 5.2, đoạn 3, câu 2), kèm hash văn bản câu.
Bản TXT của RFC cũ (DNS, SSH) được đọc bằng bộ phân tích riêng (`RfcDocument.from_text`): bỏ đầu và chân trang, nhận
tiêu đề mục theo số ở đầu dòng, tách đoạn văn và khối hình; định danh câu cùng dạng với bản XML.
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


_TARGETS = ("Section", "Appendix", "Figure", "Table")


def _xref(x: ET.Element) -> str:
    """Chữ mà bản dựng (xml2rfc) hiển thị cho một `<xref>`.

    Có chữ của tác giả thì hiện chữ đó: `format="none"` chỉ chữ ("FRAME_SIZE_ERROR"), còn lại kèm đích ("connection
    error (Section 5.4.1)", "TLS [RFC8446]"). Không có chữ (bản prep) thì dùng `derivedContent`: "Section 4.7.1",
    "Figure 2", hoặc tài liệu tham khảo dạng "[RFC5280]" kèm mục nếu có."""
    text = " ".join("".join(x.itertext()).split())
    derived = x.get("derivedContent") or ""
    if text:
        if x.get("format") == "none" or not derived or derived == text:
            return text
        return f"{text} ({derived})" if derived.startswith(_TARGETS) else f"{text} [{derived}]"
    shown = derived
    if shown.startswith(_TARGETS):
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
    return RfcDocument(xml_text, rfc_number).requirements(sections_in_scope)


def extract_requirements_text(
    text: str, rfc_number: int, sections_in_scope: Iterable[str] | None = None
) -> list[RfcSentence]:
    """Như `extract_requirements` nhưng từ bản TXT chính thức (RFC cũ không có RFCXML v3, ví dụ DNS, SSH)."""
    return RfcDocument.from_text(text, rfc_number).requirements(sections_in_scope)


@dataclass
class _Section:
    """Một mục của tài liệu, độc lập với định dạng nguồn: đường dẫn tiêu đề, các đoạn văn (số đoạn, văn bản) và các khối
    định nghĩa (struct, bảng, hình) thuộc riêng mục."""

    path: tuple[str, ...]
    paragraphs: list[tuple[str, str]]
    blocks: list[str]


def _xml_sections(root: ET.Element) -> dict[str, _Section]:
    out: dict[str, _Section] = {}
    for number, path, elem in _all_sections(root):
        paragraphs: list[tuple[str, str]] = []
        for t in _own(elem, ("t",)):
            m = _PN_PARA.match(t.get("pn", ""))
            if m and m.group(1) == number:
                paragraphs.append((m.group(2), render_text(t)))
        blocks = ["".join(b.itertext()).strip("\n") for b in _own(elem, ("sourcecode", "artwork"))]
        out[number] = _Section(path, paragraphs, blocks)
    return out


# ---- bản TXT ------------------------------------------------------------------------------------------------------------

_TXT_FOOTER = re.compile(r"\[Page \d+\]\s*$")
_TXT_HEADER = re.compile(r"^RFC \d+\s")
_TXT_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*\S|\S)\s*$")
_TXT_APPENDIX = re.compile(r"^Appendix ([A-Z](?:\.\d+)*)\.?\s+(\S.*)$")
_TXT_TOC_LEADER = re.compile(r"\.{4,}\s*\d+\s*$|\s{2,}\d+\s*$")
_TXT_FIGURE = re.compile(
    r"\+-{2,}|-{2,}\+|^\s*\|"
)  # khung hình và bảng kẻ ô; `||` giữa câu là toán tử nối, không phải nét vẽ
_TXT_COLUMNS = re.compile(r"\S\s{3,}\S")  # ô của bảng cách nhau từ 3 dấu cách (văn xuôi chỉ có 2 sau dấu chấm)


def _is_figure(block: list[str]) -> bool:
    """Hình vẽ hay bảng, không phải văn xuôi. Không dựa vào độ thụt lề: danh sách định nghĩa thụt sâu vẫn là văn xuôi quy phạm."""
    if any(_TXT_FIGURE.search(ln) for ln in block):
        return True
    columned = sum(1 for ln in block if _TXT_COLUMNS.search(ln.strip()))
    return len(block) >= 2 and columned >= max(2, len(block) // 2)


def _flat_layout(lines: list[str]) -> bool:
    """RFC rất cũ (ví dụ 1035) không thụt lề thân văn bản: dòng nội dung cũng bắt đầu ở cột 0."""
    col0 = [ln for ln in lines if ln.strip() and not ln.startswith(" ")]
    prose = [ln for ln in col0 if not _TXT_HEADING.match(ln) or len(ln) > 72]
    return len(col0) > 40 and len(prose) > len(col0) // 2


def _txt_pages(text: str) -> list[str]:
    """Bỏ đầu trang (`RFC 1035  ...  November 1987`), chân trang (`... [Page 12]`) và ký tự ngắt trang; nối các trang lại.
    Đoạn bị cắt ngang ngắt trang được nối liền, còn ranh giới đoạn thật được giữ bằng một dòng trống."""
    lines_out: list[str] = []
    for page in text.replace("\r\n", "\n").split("\f"):
        lines = page.split("\n")
        while lines and not lines[0].strip():
            lines.pop(0)
        if lines and _TXT_HEADER.match(lines[0]):
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if lines and _TXT_FOOTER.search(lines[-1]):
            lines.pop()
        while lines and not lines[-1].strip():
            lines.pop()
        while lines and not lines[0].strip():
            lines.pop(0)
        if not lines:
            continue
        if lines_out:
            prev = lines_out[-1].rstrip()
            starts_heading = not lines[0].startswith(" ")
            if prev.endswith((".", ":")) or starts_heading:
                lines_out.append("")
        lines_out.extend(lines)
    return lines_out


def _txt_sections(text: str) -> dict[str, _Section]:
    lines = _txt_pages(text)
    flat = _flat_layout(lines)
    out: dict[str, _Section] = {}
    stack: list[tuple[str, str]] = []  # (số mục, "số. tiêu đề")
    current: str | None = None
    block: list[str] = []

    def flush() -> None:
        if current is None or not block:
            block.clear()
            return
        sec = out[current]
        if _is_figure(block):
            sec.blocks.append("\n".join(block))
        else:
            sec.paragraphs.append((str(len(sec.paragraphs) + 1), " ".join(" ".join(ln.split()) for ln in block)))
        block.clear()

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        if not line.startswith(" "):
            m = _TXT_HEADING.match(line)
            a = _TXT_APPENDIX.match(line)
            heading = bool(m or a) and not _TXT_TOC_LEADER.search(line)
            if flat and (not heading or len(line) > 72 or block):
                block.append(line)  # bố cục phẳng: dòng cột 0 là nội dung trừ khi là tiêu đề đứng riêng
                continue
            flush()
            if heading:
                number, title = (m.group(1), m.group(2)) if m else ("appendix." + a.group(1).lower(), a.group(2))  # type: ignore[union-attr]
                depth = number.count(".") + 1 if m else 1
                del stack[depth - 1 :]
                stack.append((number, f"{number}. {title}"))
                current = number
                out.setdefault(number, _Section(tuple(label for _, label in stack), [], []))
            else:
                current = None  # tiêu đề không đánh số (Status of this Memo, Author's Address...): không phải nội dung quy phạm
            continue
        block.append(line)
    flush()
    return out


def _sentences_of(rfc: int, number: str, section: _Section) -> list[RfcSentence]:
    out: list[RfcSentence] = []
    for para, text in section.paragraphs:
        for idx, sentence in enumerate(split_sentences(text), start=1):
            modal = primary_modal(sentence)
            if modal is not None:
                out.append(
                    RfcSentence(
                        sentence_id=f"RFC{rfc}§{number}#p{para}s{idx}",
                        rfc=rfc,
                        section=number,
                        paragraph=para,
                        index=idx,
                        modal=modal,
                        text=sentence,
                        text_hash=text_hash(sentence),
                        section_path=section.path,
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
    """Một RFC đã đọc (RFCXML v3, hoặc bản TXT qua `from_text`), tra câu theo định danh ổn định (`RFC8446§5.2#p4s3`)."""

    def __init__(self, xml_text: str, rfc_number: int) -> None:
        self.rfc = rfc_number
        self._sections = _xml_sections(ET.fromstring(xml_text))

    @classmethod
    def from_text(cls, text: str, rfc_number: int) -> RfcDocument:
        doc = cls.__new__(cls)
        doc.rfc = rfc_number
        doc._sections = _txt_sections(text)
        return doc

    def requirements(self, sections_in_scope: Iterable[str] | None = None) -> list[RfcSentence]:
        scope = list(sections_in_scope) if sections_in_scope is not None else None
        return [
            s
            for number, sec in self._sections.items()
            if _in_scope(number, scope)
            for s in _sentences_of(self.rfc, number, sec)
        ]

    def lookup(self, sentence_id: str) -> RfcContext | None:
        """Câu theo định danh, hoặc None nếu định danh sai, thuộc RFC khác, hay mục/đoạn/câu không có."""
        m = _SENTENCE_ID.match(sentence_id)
        if m is None or int(m.group(1)) != self.rfc:
            return None
        number, para, idx = m.group(2), m.group(3), int(m.group(4))
        sec = self._sections.get(number)
        if sec is None:
            return None
        text = next((t for p, t in sec.paragraphs if p == para), None)
        if text is None:
            return None
        sentences = split_sentences(text)
        if not 1 <= idx <= len(sentences):
            return None
        sentence = sentences[idx - 1]
        return RfcContext(
            sentence_id=sentence_id,
            rfc=self.rfc,
            section=number,
            section_path=sec.path,
            sentence=sentence,
            sentence_index=idx,
            paragraph=text,
            previous_sentence=sentences[idx - 2] if idx >= 2 else None,
            next_sentence=sentences[idx] if idx < len(sentences) else None,
            definitions=self._definitions(sec, sentence + " " + text),
        )

    # ---- tra cứu cho công cụ `rfc.*` của agent -------------------------------------------------------------------

    def has_section(self, section: str) -> bool:
        return section in self._sections

    def sentences(self, section: str) -> list[RfcSentence]:
        """Câu quy phạm (BCP 14) của một mục và các mục con, kèm định danh ổn định."""
        return self.requirements([section])

    def section(self, section: str) -> tuple[tuple[str, ...], list[tuple[str, str]]] | None:
        """Đường dẫn mục và các đoạn thuộc riêng mục (id đoạn, văn bản), theo thứ tự trong tài liệu; None nếu không có mục."""
        sec = self._sections.get(section)
        if sec is None:
            return None
        return sec.path, [(f"RFC{self.rfc}§{section}#p{p}", t) for p, t in sec.paragraphs]

    def search(self, term: str, limit: int = 30) -> list[tuple[str, str]]:
        """Các đoạn có chứa `term` (không phân biệt hoa thường): (id đoạn, đoạn trích quanh chỗ khớp)."""
        needle = term.lower()
        hits: list[tuple[str, str]] = []
        for number, sec in self._sections.items():
            for p, text in sec.paragraphs:
                i = text.lower().find(needle)
                if i >= 0:
                    hits.append((f"RFC{self.rfc}§{number}#p{p}", text[max(0, i - 80) : i + len(term) + 120]))
                    if len(hits) >= limit:
                        return hits
        return hits

    def definitions(self, name: str, limit: int = MAX_DEFINITIONS) -> list[tuple[str, str]]:
        """Khối định nghĩa nhắc tới `name` (đúng nguyên từ): (số mục, nội dung, cắt ở MAX_DEFINITION_CHARS)."""
        out: list[tuple[str, str]] = []
        for number, sec in self._sections.items():
            for body in sec.blocks:
                if name in _IDENT.findall(body):
                    out.append((number, body[:MAX_DEFINITION_CHARS]))
                    if len(out) >= limit:
                        return out
        return out

    @staticmethod
    def _definitions(section: _Section, text: str) -> tuple[str, ...]:
        """Khối định nghĩa của mục có nhắc tên kiểu, trường, hằng trong câu hay đoạn; nhiều tên nhất trước."""
        names = _distinctive(text)
        scored: list[tuple[int, int, str]] = []
        for order, body in enumerate(section.blocks):
            hits = len(names & set(_IDENT.findall(body)))
            if hits:
                scored.append((-hits, order, body[:MAX_DEFINITION_CHARS]))
        return tuple(body for _, _, body in sorted(scored)[:MAX_DEFINITIONS])


def load_rfc_documents(manifest: Any, rfc_dir: Path | None) -> dict[int, RfcDocument]:
    """Các RFC trong phạm vi adapter (`specs[].doc`, ví dụ RFC8446) đọc từ `rfc_dir`: ưu tiên `rfc<số>.xml` (RFCXML v3),
    không có thì `rfc<số>.txt` (RFC cũ như DNS, SSH chỉ có bản TXT chính thức).

    Thư mục chưa đặt hay thiếu tệp thì bỏ qua văn bản đó; tệp XML có mà không phải RFCXML v3 thì báo lỗi, không im lặng.
    """
    docs: dict[int, RfcDocument] = {}
    if rfc_dir is None:
        return docs
    for spec in manifest.specs:
        m = re.fullmatch(r"RFC(\d+)", str(spec.doc))
        if m is None:
            continue
        number = int(m.group(1))
        xml, txt = rfc_dir / f"rfc{number}.xml", rfc_dir / f"rfc{number}.txt"
        if xml.is_file():
            docs[number] = RfcDocument(xml.read_text(encoding="utf-8"), number)
        elif txt.is_file():
            docs[number] = RfcDocument.from_text(txt.read_text(encoding="utf-8", errors="replace"), number)
    return docs


def lookup_sentence(docs: dict[int, RfcDocument], sentence_id: str) -> RfcContext | None:
    m = _SENTENCE_ID.match(sentence_id)
    doc = docs.get(int(m.group(1))) if m else None
    return doc.lookup(sentence_id) if doc else None

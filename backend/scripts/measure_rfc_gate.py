"""Đo RFC gate trên toàn văn một RFC (BL-21, YD-01): số câu tách được so với đếm độc lập, và mẫu câu để kiểm ranh giới.

    uv run python scripts/measure_rfc_gate.py inputs/rfc/rfc9846.xml 9846 --sample 30

Đếm độc lập dựa vào cấu trúc XML chứ không dùng bộ tách câu của gate: số phần tử `<bcp14>` (từ khoá được tác giả đánh dấu)
và số đoạn `<t>` chứa chúng. Gate phải tìm đủ đoạn và đủ từ khoá; số câu không có đáp số độc lập nên được kiểm bằng mẫu
(`--sample`) và các dấu hiệu nghi ngờ (câu bắt đầu bằng chữ thường, không có dấu kết câu, quá dài, còn dấu chấm giữa câu).
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from rfcv.domains.rfc_protocol.rfc_gate import (  # noqa: E402
    _KEYWORD_RE,
    _txt_pages,
    extract_requirements,
    extract_requirements_text,
)

MAX_SENTENCE_CHARS = 600
_INNER_BREAK = re.compile(r"[.!?]\s+[A-Z]")
_DANGLING_REF = re.compile(r"\((?:see|cf\.)?\s*\)|\b(?:see|in|of|from|by|per)\s+[.,;)]")  # tham chiếu bị mất chữ, vd "(see )"
_FLAT_POWER = re.compile(r"\b2\d{2}\b(?= \+)")  # 2^14 bị phẳng thành 214


def independent_counts(root: ET.Element) -> dict[str, int]:
    """Số liệu cấu trúc: từ khoá được đánh dấu và đoạn chứa chúng, tách theo thân văn bản và phụ lục."""
    out: Counter[str] = Counter()
    for part in ("middle", "back"):
        elem = root.find(part)
        if elem is None:
            continue
        out[f"bcp14.{part}"] = len(list(elem.iter("bcp14")))
        out[f"para.{part}"] = sum(1 for t in elem.iter("t") if t.find(".//bcp14") is not None)
        out[f"para_nested.{part}"] = sum(
            1
            for t in elem.iter("t")
            if t.find(".//bcp14") is not None and re.fullmatch(r"section-[0-9A-Za-z.]+-\d+\.\d+(\.\d+)*", t.get("pn", ""))
        )
    return dict(out)


def suspects(sentences: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for sid, text in sentences:
        if text[:1].islower():
            found.append((sid, "bắt đầu bằng chữ thường", text))
        if not text.rstrip('")').endswith((".", "?", "!", ":")):
            found.append((sid, "không có dấu kết câu", text))
        if len(text) > MAX_SENTENCE_CHARS:
            found.append((sid, f"dài hơn {MAX_SENTENCE_CHARS} ký tự", text))
        if _INNER_BREAK.search(text):
            found.append((sid, "còn dấu chấm giữa câu", text))
        if _DANGLING_REF.search(text):
            found.append((sid, "tham chiếu bị mất chữ", text))
        if _FLAT_POWER.search(text):
            found.append((sid, "lũy thừa bị phẳng (214 thay vì 2^14)", text))
    return found


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("xml", type=Path)
    ap.add_argument("rfc", type=int)
    ap.add_argument("--sample", type=int, default=0, help="in N câu ngẫu nhiên (seed cố định) để kiểm ranh giới")
    ap.add_argument("--suspects", action="store_true", help="in các câu có dấu hiệu tách sai")
    args = ap.parse_args()

    xml_text = args.xml.read_text(encoding="utf-8", errors="replace")
    if args.xml.suffix == ".txt":
        # Bản TXT: không có <bcp14>; đếm độc lập là số từ khoá viết hoa trên các dòng nội dung (thụt lề), sau khi bỏ đầu và
        # chân trang. Hàng của bảng (ví dụ cột REQUIRED/OPTIONAL) được tính ở đây nhưng gate để chúng ở khối định nghĩa.
        reqs = extract_requirements_text(xml_text, args.rfc)
        body = [ln for ln in _txt_pages(xml_text) if ln.startswith(" ")]
        kw = sum(len(_KEYWORD_RE.findall(r.text)) for r in reqs)
        raw = sum(len(_KEYWORD_RE.findall(ln)) for ln in body)
        print(f"RFC {args.rfc} (TXT): {len(reqs)} câu quy phạm; từ khoá trong câu {kw} / trên dòng nội dung {raw}")
        pairs = [(r.sentence_id, r.text) for r in reqs]
        print(f"  câu có dấu hiệu nghi ngờ: {len({s[0] for s in suspects(pairs)})}/{len(reqs)}")
        return
    root = ET.fromstring(xml_text)
    reqs = extract_requirements(xml_text, args.rfc)
    ind = independent_counts(root)

    gate_para = {(r.section, r.paragraph) for r in reqs}
    gate_keywords = sum(len(_KEYWORD_RE.findall(r.text)) for r in reqs)
    in_appendix = sum(1 for r in reqs if r.section.startswith("appendix"))
    print(f"RFC {args.rfc}: {args.xml.name}")
    print(f"  câu quy phạm gate tách được   : {len(reqs)} (thân {len(reqs) - in_appendix}, phụ lục {in_appendix})")
    print(f"  đoạn có câu quy phạm (gate)   : {len(gate_para)}")
    print(f"  đoạn <t> có <bcp14> (độc lập) : {ind.get('para.middle', 0) + ind.get('para.back', 0)} "
          f"(thân {ind.get('para.middle', 0)}, phụ lục {ind.get('para.back', 0)}; trong đó lồng {ind.get('para_nested.middle', 0) + ind.get('para_nested.back', 0)})")
    print(f"  từ khoá trong câu của gate    : {gate_keywords}")
    print(f"  phần tử <bcp14> (độc lập)     : {ind.get('bcp14.middle', 0) + ind.get('bcp14.back', 0)} "
          f"(thân {ind.get('bcp14.middle', 0)}, phụ lục {ind.get('bcp14.back', 0)})")
    print(f"  ID trùng                      : {len(reqs) - len({r.sentence_id for r in reqs})}")

    pairs = [(r.sentence_id, r.text) for r in reqs]
    sus = suspects(pairs)
    print(f"  câu có dấu hiệu nghi ngờ      : {len({s[0] for s in sus})}/{len(reqs)}")
    if args.suspects:
        for sid, why, text in sus:
            print(f"    [{why}] {sid}: {text[:300]}")
    if args.sample:
        rng = random.Random(20260901)
        print(f"\nMẫu {args.sample} câu (seed 20260901):")
        for sid, text in rng.sample(pairs, min(args.sample, len(pairs))):
            print(f"- {sid}\n    {text}")


if __name__ == "__main__":
    main()

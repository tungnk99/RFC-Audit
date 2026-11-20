"""Chuyển một tệp Markdown (có bảng, danh sách, hình SVG) thành PDF khổ A4 bằng Microsoft Edge headless.

    uv run python scripts/md_to_pdf.py ../docs/05_project/progress_report_01.md ../docs/05_project/progress_report_01.pdf

Hình `![mô tả](đường/dẫn.svg)` được nhúng thẳng vào trang (đường dẫn tính từ thư mục chứa tệp .md). Không cần thư viện ngoài.
"""

from __future__ import annotations

import html
import re
import subprocess
import sys
import tempfile
from pathlib import Path

EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

CSS = """
@page { size: A4; margin: 17mm 15mm; }
body { font: 10.5pt/1.5 "Segoe UI", "Times New Roman", serif; color: #111; }
h1 { font-size: 17pt; text-align: center; margin: 0 0 6pt; } h2 { font-size: 13pt; margin: 16pt 0 5pt; padding-bottom: 2pt; border-bottom: 1px solid #888; break-after: avoid; }
h3 { font-size: 11.5pt; margin: 12pt 0 4pt; break-after: avoid; } h4 { font-size: 10.5pt; }
p { margin: 4pt 0; text-align: justify; } ul, ol { margin: 4pt 0 4pt 18pt; padding: 0; } li { margin: 2pt 0; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; font-size: 9pt; } th, td { border: 1px solid #999; padding: 3pt 5pt; vertical-align: top; text-align: left; }
th { background: #eee; } tr { break-inside: avoid; }
code { font-family: Consolas, monospace; font-size: 8.8pt; background: #f1f1f1; padding: 0 2pt; }
pre { font: 8pt/1.3 Consolas, monospace; background: #f6f6f6; border: 1px solid #ccc; padding: 6pt; white-space: pre-wrap; break-inside: avoid; }
hr { border: 0; border-top: 1px solid #bbb; margin: 10pt 0; }
figure { margin: 8pt 0 2pt; break-inside: avoid; text-align: center; } figure svg { width: 100%; height: auto; max-height: 150mm; }
"""


def inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    return re.sub(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])", r"<em>\1</em>", s)


def figure(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"^<\?xml[^>]*\?>", "", text).strip()
    return f"<figure>{text}</figure>"


LIST_ITEM = re.compile(r"^\s*(\d+\.|-)\s+")


def convert(md: str, base: Path) -> str:
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            i += 1
            buf: list[str] = []
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            out.append("<pre>" + html.escape("\n".join(buf)) + "</pre>")
            i += 1
            continue
        if m := re.match(r"^!\[[^\]]*\]\(([^)]+)\)\s*$", ln):
            img = (base / m.group(1)).resolve()
            out.append(figure(img) if img.suffix.lower() == ".svg" and img.is_file() else f"<p>[thiếu hình {m.group(1)}]</p>")
            i += 1
            continue
        if m := re.match(r"^(#{1,4})\s+(.*)", ln):
            n = len(m.group(1))
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
            i += 1
            continue
        if re.match(r"^-{3,}\s*$", ln):
            out.append("<hr>")
            i += 1
            continue
        if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|\s*$", lines[i + 1]):
            head = [c.strip() for c in ln.strip().strip("|").split("|")]
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            t = "<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
            t += "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows)
            out.append(t + "</tbody></table>")
            continue
        if LIST_ITEM.match(ln):
            tag = "ol" if re.match(r"^\s*\d+\.", ln) else "ul"
            items: list[str] = []
            while i < len(lines) and LIST_ITEM.match(lines[i]):
                text = LIST_ITEM.sub("", lines[i])
                i += 1
                while i < len(lines) and lines[i].strip() and not LIST_ITEM.match(lines[i]) and not lines[i].startswith(("#", "|", "```", "![")):
                    text += " " + lines[i].strip()
                    i += 1
                items.append(f"<li>{inline(text)}</li>")
            out.append(f"<{tag}>" + "".join(items) + f"</{tag}>")
            continue
        if not ln.strip():
            i += 1
            continue
        para = [ln]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,4}\s|-{3,}\s*$|\||```|!\[|\s*(\d+\.|-)\s+)", lines[i]):
            para.append(lines[i])
            i += 1
        out.append("<p>" + "<br>".join(inline(p) for p in para) + "</p>")
    return "\n".join(out)


def main() -> None:
    src, dst = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    body = convert(src.read_text(encoding="utf-8"), src.parent)
    page = f'<!doctype html><html lang="vi"><meta charset="utf-8"><title>{src.stem}</title><style>{CSS}</style><body>{body}</body></html>'
    tmp = Path(tempfile.mkdtemp()) / "report.html"
    tmp.write_text(page, encoding="utf-8")
    subprocess.run(
        [str(EDGE), "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={dst}", tmp.as_uri()],
        check=True,
        timeout=120,
    )
    print("đã ghi", dst, dst.stat().st_size, "byte")


if __name__ == "__main__":
    main()

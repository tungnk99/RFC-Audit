"""Sơ đồ kiến trúc hệ thống RFCAudit (SVG), phong cách sơ đồ kiến trúc giải pháp: bảng màu hạn chế, tầng có nhãn, đường nối vuông góc."""

import sys
from xml.sax.saxutils import escape

OUT = sys.argv[1] if len(sys.argv) > 1 else "architecture_overview.svg"
W, H = 1620, 965
NAVY, ORANGE, INK, GRAY, LINE = "#1f3a5f", "#c2410c", "#1f2937", "#6b7280", "#4b5563"
GATE_FILL, HUB_FILL = "#eef1f5", "#dfe6f0"
FONT = "Segoe UI, Arial, sans-serif"
o: list[str] = []


def add(s: str) -> None:
    o.append(s)


def txt(x, y, s, size=13, weight="400", fill=INK, anchor="middle", style=""):
    add(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" {style}>{escape(s)}</text>')


def box(x, y, w, h, title, sub=(), fill="#fff", stroke=GRAY, sw=1.2, tcolor=INK, scolor="#4b5563", dash=False, tsize=14):
    d = ' stroke-dasharray="5 4"' if dash else ""
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="3" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')
    sub = [sub] if isinstance(sub, str) else list(sub)
    block = tsize + len(sub) * 15
    y0 = y + (h - block) / 2 + tsize - 2
    txt(x + w / 2, y0, title, tsize, "600", tcolor)
    for i, s in enumerate(sub):
        txt(x + w / 2, y0 + 17 + i * 15, s, 11.5, "400", scolor)


def line(pts, dash=False, both=False, color=LINE, w=1.5):
    d = ' stroke-dasharray="5 4"' if dash else ""
    p = "M " + " L ".join(f"{x} {y}" for x, y in pts)
    m = ' marker-end="url(#h)"' + (' marker-start="url(#t)"' if both else "")
    add(f'<path d="{p}" fill="none" stroke="{color}" stroke-width="{w}"{d}{m}/>')


def step(x, y, n):
    add(f'<circle cx="{x}" cy="{y}" r="10" fill="{ORANGE}"/>')
    txt(x, y + 4.5, str(n), 12, "700", "#fff")


add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}">')
add('<defs><marker id="h" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 1L10 5L0 9z" fill="#4b5563"/></marker>'
    '<marker id="t" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M10 1L0 5L10 9z" fill="#4b5563"/></marker></defs>')
add(f'<rect width="{W}" height="{H}" fill="#fff"/>')

txt(20, 30, "Kiến trúc hệ thống RFCAudit", 20, "700", NAVY, "start")
txt(20, 50, "Tác tử (LLM) chỉ đề xuất; thành phần tất định kiểm chứng và gán nhãn kết luận", 12.5, "400", GRAY, "start")

# khung harness
add(f'<rect x="150" y="62" width="1450" height="660" rx="4" fill="none" stroke="#9ca3af" stroke-width="1.2" stroke-dasharray="8 5"/>')
txt(162, 80, "Security-Aware Agent Harness", 12, "600", GRAY, "start", 'font-style="italic"')

# nhãn tầng và đường phân tầng
for y, label in [(143, ["Tác tử", "(LLM)"]), (247, ["Điều phối"]), (362, ["Kiểm chứng", "tất định"]), (795, ["Đầu vào,", "môi trường"])]:
    for i, s in enumerate(label):
        txt(20, y + i * 16 - (8 if len(label) > 1 else 0), s, 13, "700", NAVY, "start")
for y in (205, 300, 440):
    add(f'<line x1="20" y1="{y}" x2="1600" y2="{y}" stroke="#e5e7eb" stroke-width="1"/>')

SX = [170 + i * 161 for i in range(7)]
SW = 150

# tầng tác tử
txt(170, 98, "VÙNG CÁCH LY", 10.5, "700", ORANGE, "start")
txt(653, 98, "VÙNG ĐẶC QUYỀN", 10.5, "700", NAVY, "start")
agents = [
    (0, "Code Indexer", "bản đồ thành phần", True),
    (1, "Code Reader", "định vị mã", True),
    (2, "Verifier", "phản biện", False),
    (3, "RFC Analyst", "RFC → RBS", False),
    (4, "Planner", "chọn bước tiếp", False),
    (5, "Tester", "kịch bản DSL", False),
    (6, "Report", "giải thích kết luận", False),
]
for i, t, s, q in agents:
    if q:
        box(SX[i], 108, SW, 72, t, s, "#fff", ORANGE, 1.8, NAVY, "#4b5563")
    else:
        box(SX[i], 108, SW, 72, t, s, NAVY, NAVY, 1.2, "#fff", "#cbd5e1")
for i in range(7):
    cx = SX[i] + SW / 2
    line([(cx, 180), (cx, 215)], both=True)

# hub
box(170, 215, 1116, 66, "Execution loop (hub)", ["giao việc theo sổ tay điều phối · ngân sách · phát hiện lặp; agent không gọi nhau trực tiếp",
                                                  "Context builder · IFC tracker · LLM gateway (giữ khóa API) · Policy store · Trace log"], HUB_FILL, NAVY, 1.4, NAVY, "#374151")

# tầng kiểm chứng
gates = [
    (0, "Code gate", ["chỉ mục mã;", "công cụ chỉ đọc"]),
    (1, "Schema gate", ["đối chiếu vị trí với", "chỉ mục → T1"]),
    (3, "RFC gate", ["tách câu BCP 14"]),
    (4, "Oracle compiler", ["RBS → oracle,", "tập biến thể"]),
    (5, "Tool gateway", ["từ chối mặc định;", "kiểm DSL"]),
    (6, "Test driver", ["chạy SUT + tham chiếu;", "nhân chứng → T3"]),
]
for i, t, s in gates:
    box(SX[i], 320, SW, 86, t, s, GATE_FILL, GRAY)
box(SX[2], 320, SW, 86, "Coverage linker", ["T1 ↔ T3 qua độ phủ", "(chưa có độ phủ thật)"], "#fff", "#9ca3af", 1.2, "#6b7280", "#9ca3af", dash=True)
for i in range(7):
    cx = SX[i] + SW / 2
    line([(cx, 281), (cx, 320)], both=True)

# cột bằng chứng và kết luận
txt(1330, 305, "BẰNG CHỨNG VÀ KẾT LUẬN", 10.5, "700", NAVY, "start")
box(1330, 320, 260, 80, "Evidence store", ["bất biến, chuỗi băm", "bằng chứng T0–T3"], "#fff", NAVY, 2)
box(1330, 430, 260, 80, "Verdict engine", ["quy tắc V0–V9 (hàm thuần);", "đánh giá độ đủ cho Planner"], "#fff", NAVY, 2)
box(1330, 540, 260, 66, "Output gate", ["đối chiếu trích dẫn với", "Evidence store"], GATE_FILL, GRAY)
box(1330, 636, 260, 70, "Kết luận + giải thích", ["COMPLIANT · VIOLATION · NEEDS_REVIEW", "(HTML · JSON · SARIF)"], "#fff", NAVY, 1.2)
line([(1460, 400), (1460, 430)])
line([(1460, 510), (1460, 540)])
line([(1460, 606), (1460, 636)])
# T3
line([(1286, 358), (1330, 358)])
txt(1308, 350, "T3", 11, "700", INK)
# T1
line([(SX[1] + 75, 406), (SX[1] + 75, 430), (1308, 430), (1308, 385), (1330, 385)])
txt(1300, 424, "T1", 11, "700", INK, "end")
# độ phủ (chưa có)
line([(SX[2] + 75, 406), (SX[2] + 75, 470), (1330, 470)], dash=True, color="#9ca3af")

# đầu vào
box(SX[0], 760, SW, 70, "Mã nguồn SUT", "UNTRUSTED", "#fff", ORANGE, 1.8)
box(SX[3], 760, SW, 70, "RFC", "TRUSTED", "#fff", GRAY)
box(SX[4], 760, SW, 70, "Adapter giao thức", ["TRUSTED: từ vựng,", "mẫu, công thức SUT"], "#fff", GRAY)
box(1086, 760, 250, 70, "SUT + 2 bản tham chiếu", ["Docker, không mạng, không khóa API", "UNTRUSTED"], "#fff", ORANGE, 1.8)
line([(SX[0] + 75, 760), (SX[0] + 75, 406)])
line([(SX[3] + 75, 760), (SX[3] + 75, 406)])
line([(SX[4] + 75, 760), (SX[4] + 75, 406)])
line([(1211, 760), (1211, 406)], both=True)

# số bước
for (x, y, n) in [(SX[3] + 12, 320, 1), (SX[3] + 12, 108, 2), (SX[4] + 12, 320, 3), (SX[5] + 12, 108, 4), (SX[5] + 12, 320, 5),
                  (SX[1] + 12, 108, 6), (1342, 430, 7), (1342, 540, 8)]:
    step(x, y, n)

# diễn giải các bước
steps = [
    "① RFC gate tách câu yêu cầu (BCP 14), định danh ổn định",
    "② RFC Analyst dịch câu thành RBS (hai luồng, đối chiếu)",
    "③ Oracle compiler biên dịch RBS thành oracle và tập biến thể",
    "④ Tester sinh kịch bản trong DSL giới hạn",
    "⑤ Tool gateway kiểm tra; Test driver chạy trên SUT và hai bản tham chiếu (T3)",
    "⑥ Code Reader đề xuất vị trí mã; Schema gate xác nhận với chỉ mục (T1)",
    "⑦ Evidence store lưu bằng chứng; Verdict engine áp quy tắc V0–V9",
    "⑧ Report giải thích; Output gate đối chiếu trích dẫn rồi xuất kết luận",
]
txt(20, 866, "Luồng xử lý một yêu cầu", 12.5, "700", NAVY, "start")
for i, s in enumerate(steps):
    txt(20 + (i // 4) * 720, 888 + (i % 4) * 16, s, 12, "400", INK, "start")

# chú giải
lx, ly = 1180, 862
add(f'<rect x="{lx}" y="{ly}" width="22" height="13" rx="2" fill="{NAVY}"/>')
txt(lx + 30, ly + 11, "Tác tử vùng đặc quyền (LLM)", 11.5, "400", INK, "start")
add(f'<rect x="{lx}" y="{ly + 20}" width="22" height="13" rx="2" fill="#fff" stroke="{ORANGE}" stroke-width="1.8"/>')
txt(lx + 30, ly + 31, "Tác tử vùng cách ly / dữ liệu không tin cậy", 11.5, "400", INK, "start")
add(f'<rect x="{lx}" y="{ly + 40}" width="22" height="13" rx="2" fill="{GATE_FILL}" stroke="{GRAY}"/>')
txt(lx + 30, ly + 51, "Thành phần tất định (không dùng LLM)", 11.5, "400", INK, "start")
add(f'<rect x="{lx}" y="{ly + 60}" width="22" height="13" rx="2" fill="#fff" stroke="#9ca3af" stroke-dasharray="4 3"/>')
txt(lx + 30, ly + 71, "Chưa xây / chưa có dữ liệu thật", 11.5, "400", INK, "start")

add("</svg>")
open(OUT, "w", encoding="utf-8").write("\n".join(o))
print("ok", OUT)

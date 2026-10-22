"""Backlog bám sát yêu cầu đầu ra và sổ theo dõi (docs/management/theo_doi_backlog.md).

Mục đích: backlog không trôi khỏi yêu cầu. Mọi yêu cầu đầu ra (`YD-nn`) và mọi vấn đề đang mở (`CT-nn`) phải có ít nhất một việc (`BL-nn`),
mọi tham chiếu phải trỏ tới thứ có thật, và bảng truy vết ở cuối backlog phải khớp với các dòng việc.
"""

from __future__ import annotations

import re

from conftest import ROOT

BACKLOG = ROOT / "docs" / "management" / "theo_doi_backlog.md"
OUTPUT_REQUIREMENTS = ROOT / "docs" / "quality" / "tieu_chuan_dau_ra.md"
TRACKER = ROOT / "docs" / "management" / "theo_doi_cai_thien.md"

COLUMNS = 8  # ID, Việc, Đáp ứng, Phụ thuộc, Cỡ, Giai đoạn, Xong khi, Trạng thái
SIZES = {"S", "M", "L", "XL"}
PHASES = {"Ngay", "G1", "G2", "DNS", "G3", "LV", "T2"}
STATUSES = {"Chưa làm", "Đang làm", "Chặn", "Xong"}
UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def read(path) -> str:
    return path.read_text(encoding="utf-8")


def items() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in read(BACKLOG).splitlines():
        m = re.match(r"^\| (BL-\d+) \|", line)
        if m:
            assert m.group(1) not in out, f"trùng mã việc {m.group(1)}"
            out[m.group(1)] = [c.strip() for c in UNESCAPED_PIPE.split(line.strip().strip("|"))]
    return out


def ids(pattern: str, text: str) -> set[str]:
    return set(re.findall(pattern, text))


def declared_met() -> set[str]:
    """Yêu cầu đầu ra đã đạt, ghi ở mục riêng của backlog (không cần việc thêm)."""
    section = read(BACKLOG).split("## Yêu cầu đầu ra đã đạt", 1)[1].split("## ", 1)[0]
    return ids(r"YD-\d+", section)


def test_every_item_has_the_expected_shape() -> None:
    table = items()
    assert table, "backlog không có việc nào"
    for bl, cells in table.items():
        assert len(cells) == COLUMNS, (bl, len(cells))
        _, task, _, _, size, phase, done_when, status = cells
        assert task and done_when, bl
        assert size in SIZES, (bl, size)
        assert phase in PHASES, (bl, phase)
        assert status in STATUSES, (bl, status)


def test_at_most_two_items_are_in_progress() -> None:
    doing = [bl for bl, cells in items().items() if cells[7] == "Đang làm"]
    assert len(doing) <= 2, doing


def test_every_output_requirement_has_work_or_is_declared_met() -> None:
    required = ids(r"(?m)^\| (YD-\d+) \|", read(OUTPUT_REQUIREMENTS))
    assert required
    covered = set().union(*(ids(r"YD-\d+", cells[2]) for cells in items().values())) | declared_met()
    assert not required - covered, sorted(required - covered)


def test_every_open_known_issue_has_work() -> None:
    open_issues = ids(r"(?m)^### (CT-\d+) ", read(TRACKER))
    assert open_issues
    covered = set().union(*(ids(r"CT-\d+", cells[2]) for cells in items().values()))
    assert not open_issues - covered, sorted(open_issues - covered)


def test_references_point_at_things_that_exist() -> None:
    table = items()
    known_yd = ids(r"(?m)^\| (YD-\d+) \|", read(OUTPUT_REQUIREMENTS))
    known_ct = ids(r"(?m)^### (CT-\d+) ", read(TRACKER))
    for bl, cells in table.items():
        assert ids(r"YD-\d+", cells[2]) <= known_yd, (bl, ids(r"YD-\d+", cells[2]) - known_yd)
        assert ids(r"CT-\d+", cells[2]) <= known_ct, (bl, ids(r"CT-\d+", cells[2]) - known_ct)
        assert ids(r"BL-\d+", cells[3]) <= set(table), (bl, ids(r"BL-\d+", cells[3]) - set(table))
    assert declared_met() <= known_yd


def test_dependencies_have_no_cycle() -> None:
    table = items()
    deps = {bl: ids(r"BL-\d+", cells[3]) for bl, cells in table.items()}
    state: dict[str, int] = {}  # 1 đang duyệt, 2 xong

    def visit(node: str, path: list[str]) -> None:
        if state.get(node) == 2:
            return
        assert state.get(node) != 1, "vòng phụ thuộc: " + " -> ".join([*path, node])
        state[node] = 1
        for d in sorted(deps[node]):
            visit(d, [*path, node])
        state[node] = 2

    for bl in table:
        visit(bl, [])


def test_traceability_table_matches_the_items() -> None:
    table = items()
    from_items: dict[str, set[str]] = {}
    for bl, cells in table.items():
        for yd in ids(r"YD-\d+", cells[2]) - declared_met():
            from_items.setdefault(yd, set()).add(bl)
    from_table: dict[str, set[str]] = {}
    for line in read(BACKLOG).splitlines():
        m = re.match(r"^\| (YD-\d+) \| ([^|]+) \|$", line)
        if m:
            from_table[m.group(1)] = ids(r"BL-\d+", m.group(2))
    assert from_table == from_items, {
        yd: (sorted(from_table.get(yd, set())), sorted(from_items.get(yd, set())))
        for yd in sorted(from_table.keys() | from_items.keys())
        if from_table.get(yd) != from_items.get(yd)
    }

"""Quét rò rỉ trong dữ liệu một lần chạy (QS-07, YD-51, LG-1): khoá API và nội dung tệp ngoài `code_scope`.

Chạy sau mỗi lần chạy trên `trace.db`, `evidence.db`, `registry.db`, `artifacts/` và mọi tệp khác của thư mục lần chạy,
trừ `repo/` (bản sao phạm vi mã, vốn chứa mã nguồn có chủ đích). Kết quả không bao giờ chứa giá trị khoá hay nội dung tệp:
chỉ tên biến, tên tệp và số dòng.

Giới hạn đã biết: tìm khớp nguyên văn. Khoá bị mã hoá lại (base64, cắt khúc) hay nội dung bị diễn đạt lại sẽ không thấy.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from rfcv.gates.explore_policy import included_file

MIN_SECRET_LEN = 8  # khoá ngắn hơn dễ trùng ngẫu nhiên: không quét
MIN_LINE_LEN = 40  # dòng mã ngắn hơn (dấu ngoặc, từ khoá, #include) quá phổ biến để làm dấu hiệu
MAX_LINES_PER_FILE = 200
MAX_FILES = 2000
MAX_FILE_BYTES = 256 * 1024 * 1024
SKIP_TOP_LEVEL = frozenset({"repo"})
REPORT_NAME = "leak_scan.json"


@dataclass(frozen=True)
class Leak:
    kind: str  # "api_key" | "out_of_scope"
    file: str  # tệp chứa dấu vết: trong thư mục lần chạy (api_key) hoặc ngoài phạm vi trong kho mã (out_of_scope)
    detail: str  # tên biến môi trường, hoặc "dòng N"; không bao giờ là giá trị


@dataclass(frozen=True)
class ScanResult:
    leaks: tuple[Leak, ...] = ()
    files_scanned: int = 0
    out_of_scope_checked: bool = False
    notes: tuple[str, ...] = field(default=())

    @property
    def clean(self) -> bool:
        return not self.leaks

    def to_json(self) -> dict[str, object]:
        return {
            "clean": self.clean,
            "leaks": [{"kind": x.kind, "file": x.file, "detail": x.detail} for x in self.leaks],
            "files_scanned": self.files_scanned,
            "out_of_scope_checked": self.out_of_scope_checked,
            "notes": list(self.notes),
        }


def _run_files(run_dir: Path) -> Iterator[Path]:
    for p in sorted(run_dir.rglob("*")):
        if not p.is_file() or p.name == REPORT_NAME:
            continue
        if p.relative_to(run_dir).parts[0] in SKIP_TOP_LEVEL:
            continue
        yield p


def _forms(text: str) -> tuple[bytes, ...]:
    """Dạng nguyên văn và hai dạng đã escape JSON của `text` (dấu nháy, gạch chéo ngược, ký tự không ASCII). Trace và bằng
    chứng lưu JSON nên một dòng mã chứa dấu nháy chỉ xuất hiện ở dạng escape."""
    forms = {text, json.dumps(text, ensure_ascii=False)[1:-1], json.dumps(text, ensure_ascii=True)[1:-1]}
    return tuple(f.encode() for f in forms)


def _read(path: Path) -> bytes | None:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_bytes()
    except OSError:
        return None


def scan_secrets(run_dir: Path, secrets: Mapping[str, str]) -> tuple[list[Leak], int, list[str]]:
    """Tệp nào của lần chạy chứa nguyên văn giá trị của một khoá API. `secrets`: tên biến → giá trị."""
    needles = {name: _forms(value) for name, value in secrets.items() if len(value) >= MIN_SECRET_LEN}
    leaks: list[Leak] = []
    notes: list[str] = []
    scanned = 0
    for f in _run_files(run_dir):
        data = _read(f)
        if data is None:
            notes.append(f"bỏ qua {f.relative_to(run_dir).as_posix()} (quá lớn hoặc không đọc được)")
            continue
        scanned += 1
        for name, forms in needles.items():
            if any(n in data for n in forms):
                leaks.append(Leak("api_key", f.relative_to(run_dir).as_posix(), name))
    return leaks, scanned, notes


def _in_scope_lines(code_root: Path, include: Sequence[str], exclude: Sequence[str]) -> set[str]:
    lines: set[str] = set()
    for f in _repo_files(code_root):
        if included_file(f.relative_to(code_root).as_posix(), tuple(include), tuple(exclude)):
            lines.update(_candidate_lines(f, limit=None))
    return lines


def _repo_files(code_root: Path) -> Iterator[Path]:
    for p in sorted(code_root.rglob("*")):
        if p.is_file() and ".git" not in p.relative_to(code_root).parts:
            yield p


def _candidate_lines(path: Path, limit: int | None) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    seen: dict[str, None] = {}
    for raw in text.splitlines():
        s = raw.strip()
        if len(s) >= MIN_LINE_LEN:
            seen.setdefault(s, None)
    out = list(seen)
    return out if limit is None else out[:limit]


def scan_out_of_scope(
    run_dir: Path, code_root: Path, include: Sequence[str], exclude: Sequence[str]
) -> tuple[list[Leak], list[str]]:
    """Dòng mã của tệp NGOÀI phạm vi (ví dụ khoá riêng, tệp bị loại) có xuất hiện trong dữ liệu lần chạy không.

    Dòng cũng có mặt ở một tệp trong phạm vi bị bỏ qua (dòng chung như bản quyền), để không báo nhầm.
    """
    blobs = [(f, d) for f in _run_files(run_dir) if (d := _read(f)) is not None]
    outside = [
        f
        for f in _repo_files(code_root)
        if not included_file(f.relative_to(code_root).as_posix(), tuple(include), tuple(exclude))
    ]
    notes: list[str] = []
    if len(outside) > MAX_FILES:
        notes.append(f"chỉ quét {MAX_FILES}/{len(outside)} tệp ngoài phạm vi")
        outside = outside[:MAX_FILES]
    shared: set[str] | None = None
    leaks: list[Leak] = []
    for f in outside:
        rel = f.relative_to(code_root).as_posix()
        for lineno, line in _numbered_candidates(f):
            forms = _forms(line)
            if not any(n in data for _, data in blobs for n in forms):
                continue
            if shared is None:
                shared = _in_scope_lines(code_root, include, exclude)
            if line in shared:
                continue
            leaks.append(Leak("out_of_scope", rel, f"dòng {lineno}"))
            break  # một dấu vết đủ để kết luận tệp này bị lộ
    return leaks, notes


def _numbered_candidates(path: Path) -> list[tuple[int, str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    out: list[tuple[int, str]] = []
    seen: set[str] = set()
    for i, raw in enumerate(text.splitlines(), start=1):
        s = raw.strip()
        if len(s) >= MIN_LINE_LEN and s not in seen:
            seen.add(s)
            out.append((i, s))
            if len(out) >= MAX_LINES_PER_FILE:
                break
    return out


def scan_run(
    run_dir: Path,
    *,
    secrets: Mapping[str, str],
    code_root: Path | None = None,
    include: Sequence[str] = ("**",),
    exclude: Sequence[str] = (),
) -> ScanResult:
    """Quét một thư mục lần chạy. Ghi `leak_scan.json` cạnh dữ liệu để người khác kiểm lại."""
    leaks, scanned, notes = scan_secrets(run_dir, secrets)
    checked = False
    if code_root is not None and code_root.is_dir():
        more, extra = scan_out_of_scope(run_dir, code_root, include, exclude)
        leaks += more
        notes += extra
        checked = True
    else:
        notes.append("không quét tệp ngoài phạm vi: chưa biết gốc kho mã (đặt --code-root)")
    result = ScanResult(tuple(leaks), scanned, checked, tuple(notes))
    (run_dir / REPORT_NAME).write_text(json.dumps(result.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
    return result

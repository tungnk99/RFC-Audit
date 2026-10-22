"""Quy ước đặt tên file và thư mục (docs/conventions/quy_uoc_dat_ten.md). Kiểm bằng mã để quy ước không trôi.

Thêm một loại file mới thì sửa cả bảng trong tài liệu quy ước và test này.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from conftest import DOCS, ROOT

SNAKE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
VERSION_WORDS = re.compile(r"(^|_)(final|new|old|tmp|temp|copy|backup|v\d+)(_|$)")
DUNDER = {"__init__", "__main__"}
# Nhóm tài liệu trong docs/ và tiền tố tên file được phép của từng nhóm (docs/conventions/quy_uoc_dat_ten.md).
DOC_FOLDERS = {
    "overview": ("tong_quan_",),
    "design": ("thiet_ke_",),
    "evaluation": ("thiet_ke_", "danh_gia_"),
    "deliverables": ("checklist_",),
    "management": ("theo_doi_",),
    "conventions": ("quy_uoc_",),
    "quality": ("tieu_chuan_",),
}
DOC_ASSET_DIRS = {"figures", "html"}
TEST_SUPPORT = {"conftest", "fakes", "helpers", "toy_domain"}


def py_files(*dirs: str) -> Iterator[Path]:
    for d in dirs:
        for p in (ROOT / d).rglob("*.py"):
            if "__pycache__" not in p.parts:
                yield p


def rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def test_python_modules_are_ascii_snake_case() -> None:
    bad = [
        rel(p)
        for p in py_files("src", "agents", "scripts", "tests", "eval/scripts")
        if p.stem not in DUNDER and not SNAKE.match(p.stem)
    ]
    assert not bad, bad


def test_python_package_directories_are_snake_case() -> None:
    dirs = [
        d for top in ("src/rfcv", "agents") for d in (ROOT / top).rglob("*") if d.is_dir() and d.name != "__pycache__"
    ]
    bad = [rel(d) for d in dirs if not SNAKE.match(d.name)]
    assert not bad, bad


def test_test_files_are_named_after_what_they_test() -> None:
    bad = [p.name for p in (ROOT / "tests").glob("*.py") if not (p.stem.startswith("test_") or p.stem in TEST_SUPPORT)]
    assert not bad, bad


def doc_files() -> list[Path]:
    """Mọi tài liệu Markdown trong các nhóm của docs/, trừ README.md của từng thư mục."""
    return [p for folder in DOC_FOLDERS for p in sorted((DOCS / folder).glob("*.md")) if p.stem != "README"]


def test_docs_are_organised_into_the_known_folders() -> None:
    docs = DOCS
    stray_files = [p.name for p in docs.iterdir() if p.is_file() and p.name != "README.md"]
    known = set(DOC_FOLDERS) | DOC_ASSET_DIRS
    unknown_dirs = [p.name for p in docs.iterdir() if p.is_dir() and p.name not in known]
    missing = [name for name in DOC_FOLDERS if not (docs / name).is_dir()]
    assert not (stray_files or unknown_dirs or missing), (stray_files, unknown_dirs, missing)
    nested = [rel(p) for folder in DOC_FOLDERS for p in (docs / folder).rglob("*.md") if p.parent != docs / folder]
    assert not nested, nested  # không lồng thêm thư mục trong một nhóm


def test_docs_are_snake_case_with_the_prefix_of_their_folder_and_no_version_words() -> None:
    bad = [
        rel(p)
        for p in doc_files()
        if not SNAKE.match(p.stem) or VERSION_WORDS.search(p.stem) or not p.stem.startswith(DOC_FOLDERS[p.parent.name])
    ]
    assert not bad, bad
    html = [
        p for p in (DOCS / "html").glob("*.html") if not SNAKE.match(p.stem) or VERSION_WORDS.search(p.stem)
    ]
    assert not html, [p.name for p in html]


def test_every_document_folder_has_at_least_one_document() -> None:
    empty = [name for name in DOC_FOLDERS if not [p for p in doc_files() if p.parent.name == name]]
    assert not empty, empty


def test_every_html_original_has_a_markdown_document() -> None:
    markdown = {p.stem for p in doc_files()}
    orphans = [p.name for p in (DOCS / "html").glob("*.html") if p.stem not in markdown]
    assert not orphans, orphans


def test_figure_files_follow_the_pattern_and_belong_to_a_document() -> None:
    markdown = {p.stem for p in doc_files()}
    for p in (DOCS / "figures").glob("*.svg"):
        m = re.fullmatch(r"([a-z0-9_]+)_hinh_(\d+)\.svg", p.name)
        assert m and m.group(1) in markdown, p.name
    for p in (DOCS / "figures" / "legend").glob("*.svg"):
        assert re.fullmatch(r"legend_\d{2}\.svg", p.name), p.name


def test_skill_directories_are_kebab_case() -> None:
    bad = [
        rel(d)
        for group in (ROOT / "skills").iterdir()
        if group.is_dir()
        for d in group.iterdir()
        if d.is_dir() and not (KEBAB.match(d.name) and len(d.name) <= 64)
    ]
    assert not bad, bad


def test_config_scripts_and_docker_files() -> None:
    assert not [p.name for p in (ROOT / "config").glob("*.yaml") if not SNAKE.match(p.stem)]
    assert not [
        p.name for p in (ROOT / "docker").glob("*.Dockerfile") if not KEBAB.match(p.name.removesuffix(".Dockerfile"))
    ]
    assert not [p.name for p in (ROOT / "scripts").glob("*.py") if not SNAKE.match(p.stem)]

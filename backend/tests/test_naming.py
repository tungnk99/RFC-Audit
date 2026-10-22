"""Quy ước đặt tên file và thư mục (docs/01_overview/naming_conventions.md). Kiểm bằng mã để quy ước không trôi.

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
# Các nhóm tài liệu trong docs/ (docs/01_overview/naming_conventions.md). Tên file bằng tiếng Anh, snake_case.
DOC_FOLDERS = ("01_overview", "02_design", "03_quality", "04_evaluation", "05_project")
CHECKLIST_PREFIX = "checklist_"  # mọi checklist deliverable nằm trong 05_project và bắt đầu bằng tiền tố này
DOC_ASSET_DIRS = {"assets", "archive"}
FIGURES_DIR = DOCS / "assets" / "figures"
HTML_DIR = DOCS / "archive" / "html"
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
        for p in py_files("src", "agents", "scripts", "tests")
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


def test_docs_are_english_snake_case_and_have_no_version_words() -> None:
    bad = [rel(p) for p in doc_files() if not SNAKE.match(p.stem) or VERSION_WORDS.search(p.stem)]
    assert not bad, bad
    vietnamese = re.compile(r"(^|_)(thiet_ke|tieu_chuan|theo_doi|tong_quan|quy_uoc|danh_gia|hinh)(_|$)")
    assert not [rel(p) for p in doc_files() if vietnamese.search(p.stem)], "tên tài liệu phải bằng tiếng Anh"
    html = [p for p in HTML_DIR.glob("*.html") if not SNAKE.match(p.stem) or VERSION_WORDS.search(p.stem)]
    assert not html, [p.name for p in html]


def test_every_document_folder_has_at_least_one_document() -> None:
    empty = [name for name in DOC_FOLDERS if not [p for p in doc_files() if p.parent.name == name]]
    assert not empty, empty


def test_every_html_original_has_a_markdown_document() -> None:
    markdown = {p.stem for p in doc_files()}
    orphans = [p.name for p in HTML_DIR.glob("*.html") if p.stem not in markdown]
    assert not orphans, orphans


def test_figure_files_follow_the_pattern_and_belong_to_a_document() -> None:
    markdown = {p.stem for p in doc_files()}
    for p in FIGURES_DIR.glob("*.svg"):
        m = re.fullmatch(r"([a-z0-9_]+)_figure_(\d+)\.svg", p.name)
        assert m and m.group(1) in markdown, p.name
    for p in (FIGURES_DIR / "legend").glob("*.svg"):
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


def test_the_top_level_agents_package_is_ours_not_a_library_of_the_same_name() -> None:
    """CT-19: gói ngoài tên `agents` có thể va chạm với thư viện cùng tên (ví dụ OpenAI Agents SDK cài gói `agents`).
    Giữ tên này có chủ đích; test này báo ngay khi một thư viện cài đè hay che mất gói của repo."""
    import importlib.util

    spec = importlib.util.find_spec("agents")
    assert spec is not None and spec.origin is not None
    assert Path(spec.origin).resolve().is_relative_to(ROOT), f"gói `agents` đang là {spec.origin}, không phải của repo"

"""Kiểm tra lệnh của công cụ explore (tài liệu khám phá mã, mục 4.1, Bảng 3 và Bảng 4).

Ba bước, từ chối ngay khi một bước không qua:
1. tách lệnh theo `|` và phân tích từng đoạn bằng shlex (harness phân tích, không qua shell);
2. so tên lệnh và từng cờ với danh sách cho phép;
3. giải mọi đường dẫn về đường dẫn thật (kể cả symlink), phải nằm trong code_scope.
Lệnh hợp lệ được trả về dạng argv cho từng đoạn để chạy bằng execve trong sandbox.
"""

from __future__ import annotations

import fnmatch
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path


class CommandRejected(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class CommandSpec:
    # cờ → True nếu cờ nhận một giá trị đi kèm
    flags: dict[str, bool]
    # số đối số vị trí đầu tiên không phải đường dẫn (ví dụ mẫu tìm kiếm của rg)
    leading_non_path: int = 0
    # lệnh con cho phép đứng đầu (ví dụ "run" của ast-grep)
    subcommands: frozenset[str] = frozenset()
    blocked: frozenset[str] = frozenset()


_SED_SCRIPT = re.compile(r"^\d+,\d+p$")

ALLOWED: dict[str, CommandSpec] = {
    "rg": CommandSpec(
        flags={
            "-n": False,
            "-l": False,
            "-c": False,
            "-i": False,
            "-w": False,
            "-F": False,
            "--no-heading": False,
            "-e": True,
            "-g": True,
            "-t": True,
            "-A": True,
            "-B": True,
            "-C": True,
            "-m": True,
        },
        leading_non_path=1,
        blocked=frozenset({"--pre", "--pre-glob"}),
    ),
    "grep": CommandSpec(
        flags={
            "-n": False,
            "-l": False,
            "-c": False,
            "-i": False,
            "-w": False,
            "-F": False,
            "-E": False,
            "-r": False,  # không cho -R: -R đi theo mọi symlink, có thể ra ngoài code_scope
            "-e": True,
            "-A": True,
            "-B": True,
            "-C": True,
            "-m": True,
            "--include": True,
        },
        leading_non_path=1,
    ),
    "sg": CommandSpec(
        flags={"-p": True, "-l": True, "--lang": True, "--json": False, "--pattern": True},
        subcommands=frozenset({"run"}),
        blocked=frozenset({"-r", "--rewrite", "-U", "--update-all", "-i", "--interactive"}),
    ),
    "find": CommandSpec(
        flags={"-name": True, "-path": True, "-type": True, "-maxdepth": True},
        blocked=frozenset({"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprintf", "-fls"}),
    ),
    "ls": CommandSpec(flags={"-l": False, "-a": False, "-1": False, "-R": False}),
    "tree": CommandSpec(flags={"-L": True, "-d": False}),
    "sed": CommandSpec(flags={"-n": False}, leading_non_path=1),
    "head": CommandSpec(flags={"-n": True}),
    "tail": CommandSpec(flags={"-n": True}),
    "cat": CommandSpec(flags={"-n": False}),
    "wc": CommandSpec(flags={"-l": False, "-c": False, "-w": False}),
    "sort": CommandSpec(flags={"-n": False, "-r": False, "-u": False}),
    "uniq": CommandSpec(flags={"-c": False}),
    "cut": CommandSpec(flags={"-d": True, "-f": True}),
}

_FORBIDDEN_CHARS = ("`", "$(", "${")
# Cờ mà giá trị là mẫu tìm kiếm: ở đây `$` là ký tự của mẫu (biến mẫu $A, $$$ của ast-grep; neo $ của regex), không
# phải biến shell, vì lệnh chạy bằng execve không qua shell. Ở mọi vị trí khác `$` bị chặn.
_PATTERN_FLAGS = {"rg": ("-e",), "grep": ("-e",), "sg": ("-p", "--pattern")}


def _match(rel: str, pattern: str) -> bool:
    # "**/x" cũng khớp x ở gốc (fnmatch đòi có "/" trước x).
    return fnmatch.fnmatch(rel, pattern) or (pattern.startswith("**/") and fnmatch.fnmatch(rel, pattern[3:]))


def _literal_prefix(pattern: str) -> str:
    return pattern.split("*", 1)[0].split("?", 1)[0].split("[", 1)[0].rstrip("/")


def excluded(rel: str, exclude: tuple[str, ...]) -> bool:
    return any(_match(rel, p) or _match(rel + "/", p) for p in exclude)


def included_file(rel: str, include: tuple[str, ...], exclude: tuple[str, ...]) -> bool:
    """Tệp `rel` (đường dẫn tương đối, dạng posix) có thuộc phạm vi không. Dùng chung cho kiểm tra lệnh và khi dựng
    bản sao phạm vi (codeindex.workspace), nên hai nơi luôn hiểu phạm vi giống nhau."""
    if excluded(rel, exclude):
        return False
    return any(_match(rel, p) or (bool(pre := _literal_prefix(p)) and rel.startswith(pre + "/")) for p in include)


@dataclass(frozen=True)
class CodeScope:
    root: Path
    include: tuple[str, ...] = ("**",)
    exclude: tuple[str, ...] = field(default=("**/*.pem", "**/*.key", "**/*.p12", "**/.git/**"))

    def contains(self, path: Path) -> bool:
        root = self.root.resolve()
        real = path.resolve()
        try:
            rel = real.relative_to(root).as_posix()
        except ValueError:
            return False
        if rel == ".":
            return True
        if excluded(rel, self.exclude):
            return False
        if included_file(rel, self.include, self.exclude):
            return True
        # Thư mục cha của phần được gồm (ví dụ "src" khi include là "src/**") cũng tìm được: lệnh trên nó chỉ thấy
        # những gì sandbox gắn vào, tức phần trong phạm vi.
        return real.is_dir() and any(
            (prefix := _literal_prefix(p)) == rel or prefix.startswith(rel + "/") for p in self.include
        )


def _tokens(command: str) -> list[str]:
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    try:
        return list(lex)
    except ValueError as exc:
        raise CommandRejected("PARSE_ERROR", str(exc)) from exc


def validate(command: str, scope: CodeScope) -> list[list[str]]:
    if any(c in command for c in _FORBIDDEN_CHARS):
        raise CommandRejected("FORBIDDEN_SYNTAX", "không cho phép thay thế lệnh hoặc biến môi trường")
    tokens = _tokens(command)
    segments: list[list[str]] = [[]]
    for tok in tokens:
        if tok == "|":
            segments.append([])
        elif tok and all(ch in "();<>|&" for ch in tok):
            raise CommandRejected("FORBIDDEN_SYNTAX", f"toán tử '{tok}' không được phép")
        else:
            segments[-1].append(tok)
    if any(not s for s in segments):
        raise CommandRejected("PARSE_ERROR", "đoạn lệnh rỗng")
    return [_validate_segment(seg, scope, first=(i == 0)) for i, seg in enumerate(segments)]


def _validate_segment(argv: list[str], scope: CodeScope, *, first: bool) -> list[str]:
    name, args = argv[0], argv[1:]
    spec = ALLOWED.get(name)
    if spec is None:
        raise CommandRejected("COMMAND_NOT_ALLOWED", name)
    if args and args[0] in spec.subcommands:
        args = args[1:]

    positionals: list[str] = []
    pattern_values: set[int] = set()
    i = 0
    while i < len(args):
        a = args[i]
        flag, _, inline_value = a.partition("=") if a.startswith("--") else (a, "", "")
        if flag in spec.blocked:
            raise CommandRejected("FLAG_BLOCKED", f"{name} {flag}")
        if a.startswith("-"):
            if flag not in spec.flags:
                raise CommandRejected("FLAG_NOT_ALLOWED", f"{name} {flag}")
            is_pattern = flag in _PATTERN_FLAGS.get(name, ())
            if is_pattern and inline_value:
                pattern_values.add(i)
            if spec.flags[flag] and not inline_value:
                if i + 1 >= len(args):
                    raise CommandRejected("PARSE_ERROR", f"{name} {flag} thiếu giá trị")
                i += 1
                if is_pattern:
                    pattern_values.add(i)
        else:
            if name in ("rg", "grep") and "-e" not in args and not positionals:
                pattern_values.add(i)  # mẫu vị trí đầu tiên của rg/grep
            positionals.append(a)
        i += 1
    for j, a in enumerate(args):
        if "$" in a and j not in pattern_values:
            raise CommandRejected("FORBIDDEN_SYNTAX", "`$` chỉ được dùng trong mẫu tìm kiếm")

    if name == "sed" and ("-n" not in args or not positionals or not _SED_SCRIPT.match(positionals[0])):
        raise CommandRejected("FLAG_NOT_ALLOWED", "sed chỉ cho phép dạng -n 'A,Bp'")

    uses_e = "-e" in args
    skip = 0 if (uses_e and name in ("rg", "grep")) else spec.leading_non_path
    if first and name in ("rg", "grep") and len(positionals) <= skip:
        # Đoạn đầu không đọc từ ống dẫn: mặc định tìm từ gốc phạm vi.
        args = [*args, "."]
    if first and name == "sed" and len(positionals) < 2:
        raise CommandRejected("PARSE_ERROR", "sed cần tệp nguồn")
    for p in positionals[skip:]:
        candidate = Path(p) if Path(p).is_absolute() else scope.root / p
        if not scope.contains(candidate):
            raise CommandRejected("PATH_OUT_OF_SCOPE", p)
    if name == "cat" and "-n" not in args:
        raise CommandRejected("FLAG_NOT_ALLOWED", "cat chỉ cho phép kèm -n")
    sub = [argv[1]] if argv[1:] and argv[1] in spec.subcommands else []
    return [name, *sub, *args]

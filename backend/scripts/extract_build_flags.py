"""Lấy cấu hình biên dịch THẬT của một image SUT wolfSSL và ghi vào adapter (`build_flags` + `build_config_complete`).

configure sinh `wolfssl/options.h` chứa mọi `#define` của bản dựng. Cờ build do người viết adapter chỉ có vài công tắc, nên gate
"dòng phải được biên dịch" không biết `#ifdef HAVE_MAX_FRAGMENT` tắt hay bật (đo: dòng bị biên dịch bỏ vẫn được dẫn là nơi
gửi cảnh báo). Có cấu hình đầy đủ thì macro không có trong đó và không có #define trong kho là không bật.

    uv run python scripts/extract_build_flags.py rfcv/sut-wolfssl:bug eval/adapters/tls13-bug [eval/adapters/tls13-bug-b ...]
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

OPTIONS = "/sut/wolfssl/options.h"
_DEFINE = re.compile(r"^\s*#\s*define\s+(?P<n>[A-Za-z_]\w*)(?:\s+(?P<v>[^\s/].*?))?\s*(?:/\*.*)?$")
_UNDEF = re.compile(r"^\s*#\s*undef\s+(?P<n>[A-Za-z_]\w*)")
# Dòng bảo vệ của chính tệp và macro không phải công tắc cấu hình.
_SKIP = {"WOLFSSL_OPTIONS_H"}


def read_options(image: str) -> str:
    out = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "cat", image, OPTIONS], capture_output=True, check=True, timeout=120
    )
    return out.stdout.decode("utf-8", errors="replace")


def flags_from_options(text: str) -> list[str]:
    """-DNAME[=VALUE] theo thứ tự xuất hiện, bỏ macro bị #undef sau đó."""
    defined: dict[str, str] = {}
    for line in text.splitlines():
        if m := _UNDEF.match(line):
            defined.pop(m.group("n"), None)
        elif (m := _DEFINE.match(line)) and m.group("n") not in _SKIP:
            defined[m.group("n")] = (m.group("v") or "").strip()
    # CFLAGS_EXTRA của docker/eval-sut.Dockerfile đi qua CFLAGS chứ không qua options.h.
    defined.setdefault("WOLFSSL_TLS13_MIDDLEBOX_COMPAT", "")
    return [f"-D{n}={v}" if v and v != "1" else f"-D{n}" for n, v in sorted(defined.items())]


def update_adapter(path: Path, flags: list[str]) -> None:
    raw = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    lines = raw.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    configure = ["--enable-tls13", "--disable-shared", "--enable-static"]
    for line in lines:
        if line.startswith("build_flags:") or line.startswith("build_config_complete:"):
            continue
        out.append(line)
        if line.startswith("sut:"):
            pass
    text = "\n".join(out).rstrip("\n")
    flat = ", ".join('"' + f.replace('"', '\\"') + '"' for f in [*configure, *flags])
    text += f"\n\n# Cấu hình biên dịch THẬT của bản dựng (scripts/extract_build_flags.py, từ wolfssl/options.h)\nbuild_flags: [{flat}]\nbuild_config_complete: true\n"
    path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    flags = flags_from_options(read_options(argv[1]))
    print(f"{argv[1]}: {len(flags)} macro trong options.h")
    for target in argv[2:]:
        update_adapter(Path(target) / "adapter.yaml", flags)
        print("đã ghi", target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""Sinh adapter `eval/adapters/tls13-<tên>` cho SUT là OpenSSL dựng từ git (docker/eval-openssl.Dockerfile).

    uv run python scripts/eval_openssl_adapter.py <tên> <commit đầy đủ> <rbs>

Từ adapter chuẩn hiện tại (từ vựng, miền trường, mẫu) đổi phần riêng của SUT: kho mã, commit, công thức dựng, gợi ý định vị, phạm vi mã.
Bản tham chiếu là wolfSSL (HEAD, đã PASS cả ba họ yêu cầu) và GnuTLS; OpenSSL của SUT KHÔNG phải bản tham chiếu Debian (xem docker_launcher.default_specs).
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RECIPE = """# Công thức dựng SUT OpenSSL từ git (docker/eval-openssl.Dockerfile). Image dựng một lần cho mỗi commit.
implementation: openssl
repo: https://github.com/openssl/openssl
build:
  steps:
    - ./Configure no-shared no-tests no-docs no-afalgeng
    - make build_programs
  cflags: []
  coverage_cflags: ["-fprofile-instr-generate", "-fcoverage-mapping"]
roles:
  server:
    cmd: "/sut/openssl s_server -accept {port} -cert /ref/cert.pem -key /ref/key.pem -tls1_3 -www"
    certs: /ref/
lifecycle:
  per_case_process: false
  ready_check: {kind: listen_socket, port: "{port}", timeout_s: 5}
  sanity_case: "tlsfuzzer:sanity"
  stop_signal: SIGTERM
resources: {cpus: 1, memory: 512m, pids: 128, timeout_s: 60}
"""
HINTS = """locator_hints:
  record_layer:
    keywords: ["record", "TLSCiphertext", "length", "SSL3_RT_MAX", "overflow"]
    entry_points: ["ssl3_get_record", "tls_get_more_records", "tls_read_record"]
    paths: ["ssl/record/", "ssl/record/methods/"]
  alerts:
    keywords: ["SSLfatal", "SSL_AD_", "SSL_R_"]
    paths: ["ssl/statem/", "ssl/record/"]
  handshake:
    keywords: ["key_share", "supported_groups", "tls_parse_ctos_key_share", "no shared"]
    paths: ["ssl/statem/"]

"""


def make_adapter(name: str, full: str, rbs: Path) -> Path:
    dst = ROOT / "eval" / "adapters" / f"tls13-{name}"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(ROOT / "adapters" / "tls13", dst)
    text = (dst / "adapter.yaml").read_bytes().decode("utf-8").replace("\r\n", "\n")
    text, n = re.subn(
        r"^sut:\n(?:  .*\n)+",
        "sut:\n  repo: https://github.com/openssl/openssl\n"
        f"  commit: {full}\n  recipe: sut/openssl.yaml\n  start: {{role: server, port: 4433}}\n",
        text, count=1, flags=re.M,
    )  # fmt: skip
    assert n == 1
    text = re.sub(r"^references:.*\n", 'references: ["wolfssl", "gnutls"]\n', text, flags=re.M)
    text, n = re.subn(r"^locator_hints:\n(?:(?:  .*|)\n)+?(?=# Cờ build)", HINTS, text, count=1, flags=re.M)
    assert n == 1, "không thay được locator_hints"
    text = re.sub(r"^build_flags:.*\n", 'build_flags: ["no-shared", "no-tests", "no-docs", "no-afalgeng"]\n', text, flags=re.M)
    text = re.sub(
        r"^code_scope:\n(?:  .*\n)+",
        'code_scope:\n  include: ["ssl/**", "include/openssl/**", "include/internal/**"]\n'
        '  exclude: ["test/**", "**/*.pem", "**/*.key", "demos/**", "doc/**"]\n',
        text, count=1, flags=re.M,
    )  # fmt: skip
    (dst / "adapter.yaml").write_bytes(text.encode("utf-8"))
    shutil.rmtree(dst / "sut")
    (dst / "sut").mkdir()
    (dst / "sut" / "openssl.yaml").write_text(RECIPE, encoding="utf-8")
    shutil.rmtree(dst / "validation", ignore_errors=True)
    shutil.rmtree(dst / "examples", ignore_errors=True)
    (dst / "examples").mkdir()
    shutil.copy(rbs, dst / "examples" / rbs.name)
    return dst


if __name__ == "__main__":
    print(make_adapter(sys.argv[1], sys.argv[2], Path(sys.argv[3])))

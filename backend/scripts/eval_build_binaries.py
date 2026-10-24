"""Dựng nhị phân máy chủ wolfSSL cho nhiều commit mà không tốn 2,6 GB một ảnh (Giai đoạn 1 của bộ đánh giá lỗi thật).

    uv run python scripts/eval_build_binaries.py <sha> [<sha> ...]            # theo thứ tự cho trước (nên xếp theo ngày để dựng gia tăng nhanh)
    uv run python scripts/eval_build_binaries.py --pairs 4b30475a4 d3abc288e   # mỗi sha: dựng cha rồi dựng chính nó

Một container dựng dài hạn `rfcv-builder` (ảnh `rfcv/sut-build:head`, đã có cây wolfSSL đã biên dịch ở HEAD) `git checkout` từng commit và
`make examples/server/server` gia tăng. Mỗi commit sinh:
- ảnh mỏng `rfcv/sut-wolfssl:<sha12>` (docker/eval-binary.Dockerfile: ảnh HEAD + máy chủ + `.rev` của commit), `DockerSutLauncher` dùng nguyên;
- worktree LF `runs/real/src/wolfssl-<sha12>` để Code Reader đọc đúng mã;
- adapter `eval/adapters/tls13-<sha12>` (từ tls13-head, chỉ đổi `sut.commit`);
- dòng trong `runs/real/binaries/manifest.json` (trạng thái, giây dựng); lỗi biên dịch ⇒ ghi lý do để loại cặp khỏi phễu.
Container tự xoá khi dừng (`--rm`); script dừng nó bằng `docker stop`.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WOLFSSL = ROOT / "eval" / "work" / "wolfssl"
SRC = ROOT / "runs" / "real" / "src"
OUT = ROOT / "runs" / "real" / "binaries"
BUILDER = "rfcv-builder"
BUILD_IMAGE = "rfcv/sut-build:head"
AUTOTOOLS = re.compile(r"(^|/)(configure\.ac|Makefile\.am|[^/]+\.am|[^/]+\.m4)$")


def run(*cmd: str, check: bool = True, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=check, timeout=timeout
    )


def git(*args: str, cwd: Path = WOLFSSL) -> str:
    return run("git", "-C", str(cwd), *args).stdout.strip()


def builder_running() -> bool:
    return BUILDER in run("docker", "ps", "--format", "{{.Names}}", check=False).stdout.split()


def start_builder() -> None:
    if builder_running():
        return
    run("docker", "run", "-d", "--rm", "--name", BUILDER, "--entrypoint", "sleep", BUILD_IMAGE, "infinity")
    run(
        "docker",
        "exec",
        BUILDER,
        "sh",
        "-c",
        "cd /src/wolfssl && git config core.autocrlf false && git config advice.detachedHead false",
    )


def stop_builder() -> None:
    if builder_running():
        run("docker", "stop", "-t", "1", BUILDER, check=False)


def sh(script: str, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    return run("docker", "exec", BUILDER, "sh", "-c", script, check=False, timeout=timeout)


def build_one(sha: str, prev: str | None) -> dict[str, object]:
    full = git("rev-parse", sha)
    tag = full[:12]
    t0 = time.time()
    log = OUT / f"{tag}.log"
    # autogen/configure chạy lại chỉ khi tệp autotools đổi giữa hai commit liên tiếp (hay lần dựng đầu có cờ khác).
    reconf = prev is None or any(AUTOTOOLS.search(n) for n in git("diff", "--name-only", prev, full).splitlines())
    script = f"cd /src/wolfssl && git checkout -f -q {full} && "
    if reconf:
        script += "./autogen.sh >/dev/null 2>&1 && ./configure --enable-tls13 --disable-shared --enable-static CFLAGS='-DWOLFSSL_TLS13_MIDDLEBOX_COMPAT' >/dev/null 2>&1 && "
    script += 'make -j"$(nproc)" examples/server/server >/tmp/make.log 2>&1; echo EXIT=$?; tail -n 3 /tmp/make.log'
    res = sh(script)
    log.write_text(res.stdout + res.stderr, encoding="utf-8")
    ok = "EXIT=0" in res.stdout
    row: dict[str, object] = {
        "sha": full,
        "tag": tag,
        "built": ok,
        "seconds": round(time.time() - t0),
        "reconfigured": reconf,
    }
    if not ok:
        row["reason"] = (
            "make thất bại: " + res.stdout.strip().splitlines()[-1][:160] if res.stdout.strip() else "không có đầu ra"
        )
        return row
    ctx = OUT / tag
    ctx.mkdir(parents=True, exist_ok=True)
    run("docker", "cp", f"{BUILDER}:/src/wolfssl/examples/server/server", str(ctx / "server"))
    (ctx / "rev").write_text(full + "\n", encoding="utf-8")
    run(
        "docker",
        "build",
        "-q",
        "-f",
        str(ROOT / "docker" / "eval-binary.Dockerfile"),
        "-t",
        f"rfcv/sut-wolfssl:{tag}",
        str(ctx),
    )
    make_worktree(full)
    make_adapter(full)
    row["image"] = f"rfcv/sut-wolfssl:{tag}"
    return row


def make_worktree(full: str) -> None:
    wt = SRC / f"wolfssl-{full[:12]}"
    if wt.exists():
        return
    SRC.mkdir(parents=True, exist_ok=True)
    git("-c", "core.autocrlf=false", "-c", "core.eol=lf", "worktree", "add", "--detach", str(wt), full)


def make_adapter(full: str, rbs: Path | None = None) -> Path:
    """Adapter của một commit: adapter chuẩn HIỆN TẠI (từ vựng, miền trường, mẫu) cộng phần riêng của bản dựng lấy từ tls13-head đã trích
    từ options.h (cờ build thật) và `sut.commit`, tham chiếu OpenSSL + GnuTLS. `rbs`: đặc tả cho yêu cầu cần kiểm (thay mọi ví dụ cũ)."""
    base, head = ROOT / "adapters" / "tls13", ROOT / "eval" / "adapters" / "tls13-head"
    dst = ROOT / "eval" / "adapters" / f"tls13-{full[:12]}"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(base, dst)
    text = (dst / "adapter.yaml").read_bytes().decode("utf-8").replace("\r\n", "\n")
    head_text = (head / "adapter.yaml").read_bytes().decode("utf-8").replace("\r\n", "\n")
    flags = re.search(r"^build_flags:.*\n^build_config_complete: true\n", head_text, re.M)
    assert flags, "tls13-head thiếu cờ build thật (chạy scripts/extract_build_flags.py)"
    text, n = re.subn(r"^build_flags:.*\n", flags.group(0), text, count=1, flags=re.M)
    assert n == 1
    text = re.sub(r"^references:.*\n", 'references: ["openssl", "gnutls"]\n', text, flags=re.M)
    text = re.sub(r"^  # commit: <sha[^\n]*\n", f"  commit: {full}\n", text, flags=re.M)
    assert f"commit: {full}" in text and "build_config_complete: true" in text
    (dst / "adapter.yaml").write_bytes(text.encode("utf-8"))
    if rbs is not None:
        shutil.rmtree(dst / "examples", ignore_errors=True)
        (dst / "examples").mkdir()
        shutil.copy(rbs, dst / "examples" / rbs.name)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("shas", nargs="+")
    ap.add_argument("--pairs", action="store_true", help="mỗi sha: dựng cha của nó trước, rồi chính nó")
    ap.add_argument("--keep-builder", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    order: list[str] = []
    for sha in args.shas:
        full = git("rev-parse", sha)
        if args.pairs:
            order.append(git("rev-parse", f"{full}^"))
        order.append(full)
    manifest_path = OUT / "manifest.json"
    manifest: dict[str, dict[str, object]] = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    )
    start_builder()
    try:
        prev: str | None = None
        for full in dict.fromkeys(order):
            if manifest.get(full, {}).get("built"):
                print(full[:12], "đã có, bỏ qua")
                prev = full
                continue
            row = build_one(full, prev)
            manifest[full] = row
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
            print(json.dumps(row, ensure_ascii=False), flush=True)
            prev = full if row["built"] else None  # dựng hỏng thì lần sau cấu hình lại cho chắc
    finally:
        if not args.keep_builder:
            stop_builder()
    return 0 if all(manifest[f]["built"] for f in order if f in manifest) else 1


if __name__ == "__main__":
    sys.exit(main())

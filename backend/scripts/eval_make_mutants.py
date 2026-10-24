"""Tạo bộ lỗi tạo sẵn (mutant) trên wolfSSL HEAD cho yêu cầu TLS13-0042 (nhận bản ghi quá dài ⇒ cảnh báo `record_overflow`).

Nhãn chuẩn được CHỐT TRONG TỆP NÀY và ghi vào `eval/dataset/mutants/mutants.yaml` TRƯỚC khi chạy hệ thống (nguyên tắc N1, N2):
nhãn theo ngữ nghĩa của phép sửa so với RFC 8446 §6.2, không lấy từ kết quả của hệ thống. `scripts/run_tlsfuzzer_baseline.py` (độc lập với hệ
thống) chỉ dùng để kiểm lại các ca mà ngữ nghĩa không hiển nhiên; mọi chỗ lệch được ghi vào `notes`.

    uv run python scripts/eval_make_mutants.py            # worktree + commit + adapter + yaml
    uv run python scripts/eval_make_mutants.py --images   # dựng thêm ảnh Docker (cần rfcv/sut-build:head, xem docker/eval-mutant.Dockerfile)

Mỗi mutant: một worktree LF ở runs/real/src/wolfssl-<id> (một commit riêng trên HEAD gốc), ảnh `rfcv/sut-wolfssl:<sha12>`, adapter
`eval/adapters/tls13-<id>` (chỉ đổi `sut.commit`).
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WOLFSSL = ROOT / "eval" / "work" / "wolfssl"
SRC = ROOT / "runs" / "real" / "src"
BASE_COMMIT = "28bc7540dd420114dc33371e181b5617a4a66611"
FILE = "src/internal.c"
IDENT = ["-c", "user.name=rfcv-mutants", "-c", "user.email=mutants@rfcv.invalid"]
SITE1 = "                    SendAlert(ssl, alert_fatal, record_overflow);\n                    break;\n                case WC_NO_ERR_TRACE(UNKNOWN_RECORD_TYPE):"
SITE2 = '                    WOLFSSL_MSG("Encrypted data too long");\n                    SendAlert(ssl, alert_fatal, record_overflow);\n                    return BUFFER_ERROR;'


@dataclass(frozen=True)
class Mutant:
    id: str
    operator: str
    expected: str  # nhãn chuẩn cho TLS13-0042: VIOLATION | COMPLIANT
    why: str
    edits: tuple[tuple[str, str], ...]
    subtle: bool = False


MUTANTS: tuple[Mutant, ...] = (
    Mutant(
        "M1",
        "WRONG_ALERT",
        "VIOLATION",
        "Bản ghi dài hơn ngưỡng của kiểm tra tiêu đề (>16486) bị cảnh báo decode_error thay vì record_overflow.",
        ((SITE1, SITE1.replace("record_overflow", "decode_error", 1)),),
    ),
    Mutant(
        "M2",
        "DEL_ALERT",
        "VIOLATION",
        "Bỏ lời gọi gửi record_overflow ở nhánh LENGTH_ERROR: bản ghi quá dài bị từ chối nhưng không có cảnh báo (cùng kiểu lỗi thật của c18833f52).",
        ((SITE1, SITE1.replace("                    SendAlert(ssl, alert_fatal, record_overflow);\n", "", 1)),),
    ),
    Mutant(
        "M3",
        "IFDEF_TRAP",
        "VIOLATION",
        "Lời gọi gửi record_overflow bị bọc trong #ifdef của một macro không bao giờ bật (bẫy F1: đọc lướt tưởng đúng).",
        (
            (
                SITE1,
                SITE1.replace(
                    "                    SendAlert(ssl, alert_fatal, record_overflow);\n",
                    "#ifdef RFCV_MUTANT_ALERT_ENABLED\n                    SendAlert(ssl, alert_fatal, record_overflow);\n#endif\n",
                    1,
                ),
            ),
        ),
    ),
    Mutant(
        "M4",
        "WRONG_ALERT_NARROW",
        "VIOLATION",
        "Chỉ đường kiểm tra sau giải mã (độ dài 16402–16486) gửi decode_error; trên 16486 vẫn đúng. Tinh vi: kiểm thử ở biên 16641 không thấy.",
        ((SITE2, SITE2.replace("record_overflow", "decode_error", 1)),),
        subtle=True,
    ),
    Mutant(
        "M5",
        "DEL_ALERT_BOTH",
        "VIOLATION",
        "Bỏ record_overflow ở cả hai đường kiểm tra: không bản ghi quá dài nào được cảnh báo.",
        (
            (SITE1, SITE1.replace("                    SendAlert(ssl, alert_fatal, record_overflow);\n", "", 1)),
            (SITE2, SITE2.replace("                    SendAlert(ssl, alert_fatal, record_overflow);\n", "", 1)),
        ),
    ),
    Mutant(
        "M6",
        "EQUIVALENT",
        "COMPLIANT",
        "Đổi thứ tự dòng ghi nhật ký và dòng gửi cảnh báo ở đường sau giải mã: hành vi quan sát được không đổi.",
        (
            (
                SITE2,
                '                    SendAlert(ssl, alert_fatal, record_overflow);\n                    WOLFSSL_MSG("Encrypted data too long");\n                    return BUFFER_ERROR;',
            ),
        ),
    ),
    Mutant(
        "M7",
        "UNRELATED",
        "COMPLIANT",
        "Sửa cảnh báo của một yêu cầu khác (VERSION_ERROR gửi illegal_parameter thay vì protocol_version): không liên quan tới độ dài bản ghi.",
        (
            (
                "                        SendAlert(ssl, alert_fatal,\n                            wolfssl_alert_protocol_version);",
                "                        SendAlert(ssl, alert_fatal,\n                            illegal_parameter);",
            ),
        ),
    ),
    Mutant(
        "M8",
        "THRESHOLD_MASKED",
        "COMPLIANT",
        "Nâng ngưỡng kiểm tra tiêu đề thêm 1000 byte: đường kiểm tra sau giải mã vẫn gửi record_overflow nên hành vi quan sát được không đổi (cần kiểm lại bằng tlsfuzzer).",
        (
            (
                '    if (*size > (MAX_RECORD_SIZE + MAX_MSG_EXTRA +\n            (ssl->options.usingCompression ? MAX_COMP_EXTRA : 0))) {\n        WOLFSSL_MSG_EX("Record length %d exceeds max record size", *size);',
                '    if (*size > (MAX_RECORD_SIZE + MAX_MSG_EXTRA + 1000 +\n            (ssl->options.usingCompression ? MAX_COMP_EXTRA : 0))) {\n        WOLFSSL_MSG_EX("Record length %d exceeds max record size", *size);',
            ),
        ),
    ),
)


def git(*args: str, cwd: Path = WOLFSSL) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout.strip()


def make_worktree(m: Mutant) -> tuple[Path, str]:
    wt = SRC / f"wolfssl-{m.id}"
    if wt.exists():
        git("worktree", "remove", "--force", str(wt))
    git("-c", "core.autocrlf=false", "-c", "core.eol=lf", "worktree", "add", "--detach", str(wt), BASE_COMMIT)
    path = wt / FILE
    text = path.read_bytes().decode("utf-8")
    assert "\r\n" not in text, "worktree phải là LF"
    for old, new in m.edits:
        assert text.count(old) == 1, (m.id, old[:60], text.count(old))
        text = text.replace(old, new, 1)
    path.write_bytes(text.encode("utf-8"))
    git("add", FILE, cwd=wt)
    git(*IDENT, "commit", "-q", "-m", f"mutant {m.id} {m.operator}", cwd=wt)
    return wt, git("rev-parse", "HEAD", cwd=wt)


def changed_lines(wt: Path) -> list[tuple[int, int]]:
    out = git("diff", "-U0", "HEAD^", "HEAD", "--", FILE, cwd=wt)
    spans: list[tuple[int, int]] = []
    for line in out.splitlines():
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if m:
            start, count = int(m.group(3)), int(m.group(4) or 1)
            spans.append((start, start + max(count, 1) - 1))
    return spans


def make_adapter(m: Mutant, sha: str) -> None:
    src, dst = ROOT / "eval" / "adapters" / "tls13-head", ROOT / "eval" / "adapters" / f"tls13-{m.id}"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    cfg = dst / "adapter.yaml"
    raw = cfg.read_bytes().decode("utf-8")
    new = re.sub(r"(commit:\s*)[0-9a-f]{40}", rf"\g<1>{sha}", raw, count=1)
    assert new != raw
    cfg.write_bytes(new.encode("utf-8"))


def build_image(m: Mutant, wt: Path, sha: str) -> None:
    ctx = ROOT / "runs" / "real" / "mutants" / m.id
    ctx.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(wt / FILE, ctx / "internal.c")
    tag = f"rfcv/sut-wolfssl:{sha[:12]}"
    subprocess.run(
        [
            "docker",
            "build",
            "-q",
            "-f",
            str(ROOT / "docker" / "eval-mutant.Dockerfile"),
            "--build-arg",
            f"SHA={sha}",
            "-t",
            tag,
            str(ctx),
        ],
        check=True,
    )
    print("ảnh", tag)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--images", action="store_true", help="dựng ảnh Docker cho từng mutant")
    args = ap.parse_args()
    SRC.mkdir(parents=True, exist_ok=True)
    rows: list[str] = []
    for m in MUTANTS:
        wt, sha = make_worktree(m)
        spans = changed_lines(wt)
        make_adapter(m, sha)
        if args.images:
            build_image(m, wt, sha)
        rows.append(
            f"- id: {m.id}\n  adapter: eval/adapters/tls13-{m.id}\n  code_root: runs/real/src/wolfssl-{m.id}\n  commit: {sha}\n  operator: {m.operator}\n"
            f"  requirement: TLS13-0042\n  expected: {m.expected}\n  subtle: {str(m.subtle).lower()}\n  fix_location: {{file: {FILE}, lines: {[list(s) for s in spans]}}}\n"
            f'  why: "{m.why}"\n'
        )
        print(m.id, sha[:12], spans)
    out = ROOT / "eval" / "dataset" / "mutants" / "mutants.yaml"
    out.write_text(
        "# Bộ lỗi tạo sẵn cho TLS13-0042. Nhãn `expected` chốt theo ngữ nghĩa của phép sửa TRƯỚC khi chạy hệ thống (scripts/eval_make_mutants.py).\n"
        "# Ba mục lỗi/sửa thật (bug, fix, head) ở eval/adapters/tls13-{bug,fix,head}.\nitems:\n" + "".join(rows),
        encoding="utf-8",
    )
    print("đã ghi", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

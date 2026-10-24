"""Phễu chọn lỗi thật của wolfSSL cho bộ đánh giá: từ mọi commit đụng mã TLS lõi xuống các ứng viên quan sát được qua mạng ở phía MÁY CHỦ.

    uv run python scripts/eval_mine_commits.py [--since 2025-01-01] [--repo eval/work/wolfssl]

Ghi `eval/dataset/real/wolfssl_funnel.csv` (mọi commit kèm đặc trưng và LÝ DO bị loại hoặc `candidate`) và in số đếm từng bước của phễu.
Đây là lọc cơ học và bảo thủ để người duyệt không phải đọc 951 commit; nó KHÔNG gán nhãn. Ứng viên còn lại được duyệt tay ở
`wolfssl_curated.csv` (giữ/loại/sửa, kèm yêu cầu RFC). Tiêu chí bao gồm xem kế hoạch: lỗi quan sát qua mạng ở máy chủ, đường mã chạy được ở cấu hình
mặc định, một yêu cầu RFC rõ, không phải refactor/giao diện/build/test.
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ("src/internal.c", "src/tls13.c", "src/tls.c")
OUT = ROOT / "eval" / "dataset" / "real" / "wolfssl_funnel.csv"
MAX_CHANGED = (
    250  # commit đổi nhiều hơn mức này gần như chắc chắn là refactor hay tính năng, không phải một sửa lỗi tuân thủ
)
SUBJECT_EXCLUDE = re.compile(
    r"^(tests?:|test\b|add .*\btests?\b|fix ci|ci:|address review|code review|review feedback|merge|revert|docs?:|"
    r"update (docs|changelog)|add (native )?api|add .*option|add .*apis?\b)",
    re.I,
)
# Hàm xử lý dữ liệu do KHÁCH gửi tới máy chủ (đầu vào mà bộ kiểm thử phía khách có thể tạo ra).
SERVER_INPUT = re.compile(
    r"(DoTls13ClientHello|DoClientHello|TLSX_\w*Parse|TLSX_\w*Verify\w*|GetRecordHeader|DoProcessReplyEx|SanityCheck\w*MsgReceived|"
    r"DoTls13Finished|DoTls13Certificate\b|DoTls13KeyUpdate|DoTls13EndOfEarlyData|DoPreSharedKeys|CheckPreSharedKeys|"
    r"DoAlert|DoApplicationData|removeMsgInnerPadding|TLSX_KeyShare\w*|TLSX_SNI\w*|DoHandShakeMsgType)"
)
# Hàm xử lý dữ liệu do MÁY CHỦ gửi tới khách: phía máy khách, ngoài khả năng của bộ kiểm thử hiện có.
CLIENT_INPUT = re.compile(
    r"(DoTls13ServerHello|DoServerHello|DoTls13CertificateRequest|DoTls13NewSessionTicket|DoSessionTicket|DoServerKeyExchange|"
    r"DoTls13EncryptedExtensions|DoHelloRetry\w*|DoTls13HelloRetryRequest|TLSX_\w*Response\w*|SendClientHello|HelloRequest)"
)
NOT_DEFAULT = re.compile(
    r"(DTLS|dtls|QUIC|quic|ECH|_ech_|Ech|SRTP|sniffer|CRYPTO_CB|crypto_cb|ASM|asm|AVX|NEON|Multicast)"
)


@dataclass
class Commit:
    sha: str
    parent: str
    date: str
    subject: str
    src_files: list[str] = field(default_factory=list)
    test_files: int = 0
    changed: int = 0
    alert_delta: int = 0
    functions: list[str] = field(default_factory=list)
    stage: str = ""


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    ).stdout


def features(repo: Path, sha: str) -> Commit:
    head = git(repo, "show", "-s", "--format=%H|%P|%ad|%s", "--date=short", sha).strip().split("|", 3)
    c = Commit(head[0], head[1].split()[0] if head[1] else "", head[2], head[3])
    names = git(repo, "show", "--format=", "--name-only", "--no-renames", sha).splitlines()
    c.test_files = sum(1 for n in names if n.startswith(("tests/", "scripts/", "testsuite/")))
    c.src_files = [
        n
        for n in names
        if n.startswith(("src/", "wolfssl/")) and not n.startswith(("wolfssl/openssl", "wolfssl/wolfcrypt"))
    ]
    diff = git(repo, "show", "-U0", "--format=", sha, "--", *CORE) if any(n in CORE for n in c.src_files) else ""
    body = [x for x in diff.splitlines() if x[:1] in "+-" and x[:3] not in ("+++", "---")]
    c.changed = len(body)
    c.alert_delta = sum(1 for x in body if "SendAlert" in x)
    ctx: list[str] = []
    for x in diff.splitlines():
        m = re.match(r"^@@ .*? @@ (.*)$", x)
        if m and (f := re.findall(r"(\w+)\s*\(", m.group(1))):
            ctx.append(f[-1])
    c.functions = list(dict.fromkeys(ctx))
    return c


def classify(c: Commit) -> str:
    """Lý do loại (bước đầu tiên khớp) hoặc `candidate`. Thứ tự là thứ tự các bước của phễu."""
    if SUBJECT_EXCLUDE.search(c.subject):
        return "loại: tiêu đề cho thấy test/CI/review/tài liệu/giao diện/tuỳ chọn build"
    if not any(f in CORE for f in c.src_files):
        return "loại: không đụng mã TLS lõi"
    if c.changed > MAX_CHANGED:
        return f"loại: đổi hơn {MAX_CHANGED} dòng (refactor hay tính năng)"
    if c.changed == 0:
        return "loại: không có dòng mã đổi trong tệp lõi"
    if NOT_DEFAULT.search(c.subject) or (c.functions and all(NOT_DEFAULT.search(f) for f in c.functions)):
        return "loại: DTLS/QUIC/ECH/SRTP/mã hoá phần cứng (không chạy ở cấu hình mặc định)"
    fn = " ".join(c.functions)
    client, server = bool(CLIENT_INPUT.search(fn)), bool(SERVER_INPUT.search(fn))
    if client and not server:
        return "loại: phía máy khách (đầu vào do máy chủ gửi)"
    if not c.functions or not server:
        return "loại: không thấy hàm xử lý đầu vào của máy chủ trong hunk"
    if c.alert_delta == 0:
        return "ứng viên yếu: có hàm xử lý đầu vào máy chủ nhưng không đổi cảnh báo (cần duyệt tay)"
    return "candidate"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", default="2025-01-01")
    ap.add_argument("--repo", default="eval/work/wolfssl")
    args = ap.parse_args()
    repo = ROOT / args.repo
    shas = git(repo, "log", "--no-merges", f"--since={args.since}", "--format=%H", "--", *CORE).split()
    commits = [features(repo, s) for s in shas]
    for c in commits:
        c.stage = classify(c)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["sha", "parent", "date", "stage", "changed_lines", "alert_delta", "test_files", "functions", "subject"]
        )
        for c in sorted(commits, key=lambda x: x.date):
            w.writerow(
                [
                    c.sha,
                    c.parent,
                    c.date,
                    c.stage,
                    c.changed,
                    c.alert_delta,
                    c.test_files,
                    ";".join(c.functions[:6]),
                    c.subject[:140],
                ]
            )
    counts = Counter(c.stage for c in commits)
    print(f"{len(commits)} commit đụng mã TLS lõi từ {args.since}\n")
    for stage, n in counts.most_common():
        print(f"{n:5}  {stage}")
    cand = [c for c in commits if c.stage == "candidate"]
    print(f"\nứng viên (đổi cảnh báo, hàm xử lý đầu vào máy chủ): {len(cand)}")
    eval_split = [c for c in cand if c.date >= "2026-07-01"]
    print(f"  trong đó từ 2026-07 (tập eval): {len(eval_split)}; trước đó (dev): {len(cand) - len(eval_split)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

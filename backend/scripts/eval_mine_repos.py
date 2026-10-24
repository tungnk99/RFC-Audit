"""Phễu chọn lỗi thật cho bộ đánh giá từ NHIỀU kho TLS (OpenSSL, mbedTLS, GnuTLS, s2n-tls, rustls, BoringSSL, wolfSSL).

    uv run python scripts/eval_mine_repos.py [--since 2023-01-01] [--repos openssl mbedtls ...]

Với mỗi kho (đã clone ở `eval/work/<tên>`), lọc cơ học các commit sửa mã xử lý đầu vào của MÁY CHỦ TLS thành ứng viên, ghi
`eval/dataset/real/funnel_<tên>.csv` (mọi commit kèm lý do loại hoặc `candidate`) và in số đếm. Lọc bảo thủ để người duyệt không phải đọc
toàn bộ lịch sử; nó KHÔNG gán nhãn. Một ứng viên là: sửa lỗi (chủ đề nói sửa/từ chối/RFC/cảnh báo), không đụng test là chính, vừa phải
(<= 250 dòng), có dấu hiệu hành vi quan sát được (đổi mã cảnh báo, thêm kiểm tra trả lỗi, nhắc RFC), không thuộc DTLS/QUIC/phía khách.
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "eval" / "work"
OUT = ROOT / "eval" / "dataset" / "real"
MAX_CHANGED = 250


@dataclass(frozen=True)
class RepoSpec:
    paths: tuple[str, ...]  # thư mục/tệp mã lõi TLS (git pathspec)
    alert: re.Pattern[str]  # dấu hiệu mã cảnh báo trong dòng diff
    test: re.Pattern[str] = re.compile(r"(^|/)(tests?|test_|fuzz|doc|docs|examples?|cmake|build)(/|_)|_test\.|\.md$|\.txt$")
    client: re.Pattern[str] = re.compile(r"(client|_clnt|cli_|\bcl_)", re.I)


SPECS: dict[str, RepoSpec] = {
    "openssl": RepoSpec(
        ("ssl/statem", "ssl/record", "ssl/t1_lib.c", "ssl/s3_lib.c", "ssl/tls_depr.c"),
        re.compile(r"SSL_AD_\w+|SSL_R_\w+|TLS1_AD_\w+"),
    ),
    "mbedtls": RepoSpec(("library/ssl_tls.c", "library/ssl_tls13_server.c", "library/ssl_tls12_server.c", "library/ssl_tls13_generic.c"),
                        re.compile(r"MBEDTLS_SSL_ALERT_MSG_\w+|MBEDTLS_ERR_SSL_\w+")),
    "gnutls": RepoSpec(("lib/handshake.c", "lib/tls13", "lib/ext", "lib/record.c", "lib/handshake-tls13.c", "lib/supplemental.c"),
                       re.compile(r"GNUTLS_A_\w+|GNUTLS_E_\w+")),
    "s2n-tls": RepoSpec(("tls",), re.compile(r"S2N_ERR_\w+|S2N_TLS_ALERT_\w+|alert")),
    "rustls": RepoSpec(("rustls/src/server", "rustls/src/msgs", "rustls/src/common_state.rs", "rustls/src/tls13"),
                       re.compile(r"AlertDescription::\w+|Error::\w+|PeerMisbehaved::\w+|InappropriateMessage")),
    "boringssl": RepoSpec(("ssl",), re.compile(r"SSL_AD_\w+|SSL_R_\w+")),
    "wolfssl": RepoSpec(("src/internal.c", "src/tls13.c", "src/tls.c"), re.compile(r"[a-z_]+_error|\b\w+_alert\b|SendAlert|BUFFER_ERROR|\w+_ERROR\b")),
}
SUBJECT_FIX = re.compile(
    r"\b(fix|reject|require|enforce|validate|check|prevent|disallow|forbid|abort|alert|send|return|handle|should|must|"
    r"malformed|invalid|missing|unexpected|illegal|spurious|RFC|spec|compliance|conform|violat|incorrect|wrong|ignore)\w*",
    re.I,
)
SUBJECT_EXCLUDE = re.compile(
    r"^(tests?:|test\b|add .*\btests?\b|ci:|fix ci|merge|revert|docs?:|update (docs|changelog|copyright)|bump|release|prepare for|"
    r"cleanup|clean up|refactor|format|style|typo|spelling|comment|doc fix|changes\b)",
    re.I,
)
NOT_DEFAULT = re.compile(r"(DTLS|dtls|QUIC|quic|ECH|\bech\b|SRTP|sniffer|CRYPTO_CB|cryptodev|ASM\b|asm\b|AVX|NEON|SCTP|ktls|KTLS)")
RFC_REF = re.compile(r"RFC\s*-?\d{4}|section\s+\d+(\.\d+)+|\bMUST\b|\bSHALL\b", re.I)


@dataclass
class Commit:
    sha: str
    parent: str
    date: str
    subject: str
    body: str = ""
    src_files: list[str] = field(default_factory=list)
    test_files: int = 0
    changed: int = 0
    alert_delta: int = 0
    rfc: bool = False
    stage: str = ""


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def list_commits(repo: Path, spec: RepoSpec, since: str) -> list[Commit]:
    fmt = "%H%x1f%P%x1f%cs%x1f%s%x1f%b%x1e"
    out = git(repo, "log", f"--since={since}", "--no-merges", f"--format={fmt}", "--", *spec.paths)
    commits: list[Commit] = []
    for rec in out.split("\x1e"):
        f = rec.strip("\n").split("\x1f")
        if len(f) < 5 or not f[0].strip():
            continue
        commits.append(Commit(f[0].strip(), f[1].split()[0] if f[1].split() else "", f[2], f[3], f[4]))
    return commits


def features_all(repo: Path, spec: RepoSpec, commits: list[Commit], since: str) -> None:
    """Một lượt `git log -p` cho mọi commit (một lệnh = tải blob theo lô, nhanh hơn nhiều so với `git show` từng commit)."""
    by_sha = {c.sha: c for c in commits}
    out = git(repo, "log", f"--since={since}", "--no-merges", "-p", "-U0", "--numstat", "--format=@@%H", "--", *spec.paths)
    cur: Commit | None = None
    for line in out.splitlines():
        if line.startswith("@@"):
            cur = by_sha.get(line[2:].strip())
            continue
        if cur is None:
            continue
        m = re.match(r"^(\d+)\t(\d+)\t(.+)$", line)
        if m:
            cur.changed += int(m.group(1)) + int(m.group(2))
            cur.src_files.append(m.group(3))
        elif line.startswith(("+", "-")) and not line.startswith(("+++", "---")) and spec.alert.search(line):
            cur.alert_delta += 1
    names = git(repo, "log", f"--since={since}", "--no-merges", "--name-only", "--format=@@%H")
    cur = None
    for line in names.splitlines():
        if line.startswith("@@"):
            cur = by_sha.get(line[2:].strip())
        elif cur is not None and line and spec.test.search(line):
            cur.test_files += 1
    for c in commits:
        c.src_files = [p for p in c.src_files if not spec.test.search(p)]
        c.rfc = bool(RFC_REF.search(c.subject + "\n" + c.body))


def classify(c: Commit, spec: RepoSpec) -> str:
    if SUBJECT_EXCLUDE.search(c.subject):
        return "loại: test/CI/tài liệu/dọn dẹp theo chủ đề"
    if not c.src_files:
        return "loại: không đụng mã lõi"
    if c.changed > MAX_CHANGED:
        return f"loại: quá lớn (> {MAX_CHANGED} dòng)"
    if NOT_DEFAULT.search(c.subject) or any(NOT_DEFAULT.search(p) for p in c.src_files):
        return "loại: DTLS/QUIC/ECH/tuỳ chọn không mặc định"
    if re.search(r"\b(client|clienthello-less)\b.*\b(side|only)\b", c.subject, re.I) and not re.search(r"server", c.subject, re.I):
        return "loại: phía khách"
    if not SUBJECT_FIX.search(c.subject):
        return "loại: chủ đề không phải sửa/kiểm tra"
    if c.alert_delta == 0 and not c.rfc:
        return "ứng viên yếu: không đổi cảnh báo, không nhắc RFC"
    return "candidate"


def mine(name: str, since: str) -> Counter[str]:
    repo, spec = WORK / name, SPECS[name]
    commits = list_commits(repo, spec, since)
    features_all(repo, spec, commits, since)
    for c in commits:
        c.stage = classify(c, spec)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / f"funnel_{name}.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sha", "parent", "date", "subject", "changed", "alert_delta", "rfc", "files", "stage"])
        for c in commits:
            w.writerow([c.sha, c.parent, c.date, c.subject, c.changed, c.alert_delta, int(c.rfc), ";".join(c.src_files[:4]), c.stage])
    return Counter(c.stage.split(":")[0] if c.stage.startswith("loại") else c.stage for c in commits) + Counter({"tổng": len(commits)})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", default="2023-01-01")
    ap.add_argument("--repos", nargs="*", default=[n for n in SPECS if (WORK / n / ".git").exists() or (WORK / n).exists()])
    args = ap.parse_args()
    for name in args.repos:
        if not (WORK / name).exists():
            print(f"{name}: chưa clone")
            continue
        print(name, dict(mine(name, args.since)))


if __name__ == "__main__":
    main()

"""Bộ lỗi tự sinh trên OpenSSL THẬT (git, thẻ openssl-3.6.5) cho ba họ yêu cầu U/G/R (xem eval_make_mutants_multi.py).

    uv run python scripts/eval_make_mutants_openssl.py [--images] [--only OU1 ...] [--check]

Mỗi mutant chỉ SỬA hoặc XOÁ DÒNG CÓ SẴN trong mã thật (đổi hằng số cảnh báo, xoá lệnh gọi, đảo hai nhánh của biểu thức điều kiện), không thêm mã mới.
`expected` được chốt THEO NGỮ NGHĨA phép sửa so với RFC 8446 trước khi chạy hệ thống; riêng việc đường mã có thực sự chạy với đầu vào của họ yêu cầu hay không
được kiểm độc lập bằng `--check` (chạy thẳng runner tlsfuzzer trên ảnh mutant, không qua hệ thống): nếu hành vi quan sát khác nhãn thì phải xem lại tay.
Worktree LF `runs/real/src/openssl-<id>` (một commit trên thẻ), ảnh `rfcv/sut-openssl:<sha12>`, adapter `eval/adapters/tls13-<id>`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_openssl_adapter as adapter

ROOT = adapter.ROOT
REPO = ROOT / "eval" / "work" / "openssl"
SRC = ROOT / "runs" / "real" / "src"
TAG = "openssl-3.6.5"
IDENT = ["-c", "user.name=rfcv-mutants", "-c", "user.email=mutants@rfcv.invalid"]
RBS = ROOT / "eval" / "dataset" / "real" / "rbs"
FAMILIES = {
    "U": ("TLS13-0101", RBS / "P1_unknown_record_type.rbs"),
    "G": ("TLS13-0103", RBS / "P3_no_shared_group.rbs"),
    "R": ("TLS13-0042", ROOT / "adapters" / "tls13" / "examples" / "TLS13-0042.rbs"),
}
TLS13 = "ssl/record/methods/tls13_meth.c"
RECS3 = "ssl/record/rec_layer_s3.c"
EXT = "ssl/statem/extensions.c"
SRV = "ssl/statem/statem_srvr.c"
COMMON = "ssl/record/methods/tls_common.c"

HDR_TYPE = "        RLAYERfatal(rl, SSL_AD_UNEXPECTED_MESSAGE, SSL_R_BAD_RECORD_TYPE);\n        return 0;\n    }\n\n    if (rec->rec_version != TLS1_2_VERSION) {"
HDR_LEN = "        RLAYERfatal(rl, SSL_AD_RECORD_OVERFLOW,\n            SSL_R_ENCRYPTED_LENGTH_TOO_LONG);"
POST_LEN = "        RLAYERfatal(rl, SSL_AD_RECORD_OVERFLOW, SSL_R_DATA_LENGTH_TOO_LONG);"
LAST_REC = "        SSLfatal(s, SSL_AD_UNEXPECTED_MESSAGE, SSL_R_UNEXPECTED_MESSAGE);"
DEFAULT_REC = "        SSLfatal(s, SSL_AD_UNEXPECTED_MESSAGE, SSL_R_UNEXPECTED_RECORD);\n        return -1;\n    case SSL3_RT_CHANGE_CIPHER_SPEC:"
COMMON_TYPE = "        RLAYERfatal(rl, SSL_AD_UNEXPECTED_MESSAGE, SSL_R_BAD_RECORD_TYPE);\n        return 0;\n    }\n"
NOSHARE = "                SSLfatal(s, sent ? SSL_AD_HANDSHAKE_FAILURE : SSL_AD_MISSING_EXTENSION,\n                    SSL_R_NO_SUITABLE_KEY_SHARE);"
COOKIE = "SSLfatal(s, SSL_AD_HANDSHAKE_FAILURE, SSL_R_COOKIE_MISMATCH);"
VERSION = "        RLAYERfatal(rl, SSL_AD_DECODE_ERROR, SSL_R_WRONG_VERSION_NUMBER);\n        return 0;\n    }\n\n    if (rec->length > SSL3_RT_MAX_TLS13_ENCRYPTED_LENGTH) {"


@dataclass(frozen=True)
class M:
    id: str
    family: str
    operator: str
    expected: str
    why: str
    edits: tuple[tuple[str, str, str], ...]  # (tệp, cũ, mới)
    subtle: bool = False


def sub(old: str, a: str, b: str) -> str:
    assert a in old, (a, old[:60])
    return old.replace(a, b, 1)


MUTANTS: tuple[M, ...] = (
    M("OU1", "U", "WRONG_ALERT", "VIOLATION", "Trong ssl3_read_bytes, khi chưa chọn phiên bản và gặp bản ghi lạ, máy chủ gửi illegal_parameter thay vì unexpected_message.",
      ((RECS3, LAST_REC, sub(LAST_REC, "SSL_AD_UNEXPECTED_MESSAGE", "SSL_AD_ILLEGAL_PARAMETER")),)),
    M("OU2", "U", "WRONG_ALERT", "VIOLATION", "Trong ssl3_read_bytes, khi chưa chọn phiên bản và gặp bản ghi lạ, máy chủ gửi decode_error thay vì unexpected_message.",
      ((RECS3, LAST_REC, sub(LAST_REC, "SSL_AD_UNEXPECTED_MESSAGE", "SSL_AD_DECODE_ERROR")),)),
    M("OU3", "U", "WRONG_ALERT", "VIOLATION", "Trong ssl3_read_bytes, khi chưa chọn phiên bản và gặp bản ghi lạ, máy chủ gửi handshake_failure thay vì unexpected_message.",
      ((RECS3, LAST_REC, sub(LAST_REC, "SSL_AD_UNEXPECTED_MESSAGE", "SSL_AD_HANDSHAKE_FAILURE")),)),
    M("OU4", "U", "DEL_ALERT", "VIOLATION", "Bỏ lệnh gửi cảnh báo ở nhánh chưa chọn phiên bản của ssl3_read_bytes (chỉ còn `return -1`).",
      ((RECS3, LAST_REC, sub(LAST_REC, "        SSLfatal(s, SSL_AD_UNEXPECTED_MESSAGE, SSL_R_UNEXPECTED_MESSAGE);", "")),)),
    M("OG1", "G", "WRONG_ALERT", "VIOLATION", "Không có nhóm chung: gửi illegal_parameter thay vì handshake_failure.",
      ((EXT, NOSHARE, sub(NOSHARE, "SSL_AD_HANDSHAKE_FAILURE", "SSL_AD_ILLEGAL_PARAMETER")),)),
    M("OG2", "G", "WRONG_ALERT_OTHER", "VIOLATION", "Không có nhóm chung: gửi internal_error thay vì handshake_failure.",
      ((EXT, NOSHARE, sub(NOSHARE, "SSL_AD_HANDSHAKE_FAILURE", "SSL_AD_INTERNAL_ERROR")),)),
    M("OG3", "G", "ALLOWED_ALTERNATIVE", "COMPLIANT", "Không có nhóm chung: gửi insufficient_security, RFC 8446 §4.1.1 cho phép (RBS có accept_alternatives).",
      ((EXT, NOSHARE, sub(NOSHARE, "SSL_AD_HANDSHAKE_FAILURE", "SSL_AD_INSUFFICIENT_SECURITY")),)),
    M("OG4", "G", "SWAP_BRANCHES", "VIOLATION", "Đảo hai nhánh của biểu thức điều kiện (sent ? handshake_failure : missing_extension): khi máy khách có gửi key_share thì báo missing_extension.",
      ((EXT, NOSHARE, sub(NOSHARE, "sent ? SSL_AD_HANDSHAKE_FAILURE : SSL_AD_MISSING_EXTENSION", "sent ? SSL_AD_MISSING_EXTENSION : SSL_AD_HANDSHAKE_FAILURE")),)),
    M("OR1", "R", "WRONG_ALERT", "VIOLATION", "Tiêu đề bản ghi TLS 1.3 dài hơn 16640 gửi decode_error thay vì record_overflow.",
      ((TLS13, HDR_LEN, sub(HDR_LEN, "SSL_AD_RECORD_OVERFLOW", "SSL_AD_DECODE_ERROR")),)),
    M("OR2", "R", "UNRELATED_SENTENCE", "COMPLIANT", "Chỉ đường kiểm tra sau giải mã (nội dung > 16384, câu RFC khác với câu về TLSCiphertext > 16640) gửi illegal_parameter: ngoài phạm vi yêu cầu đang kiểm.",
      ((TLS13, POST_LEN, sub(POST_LEN, "SSL_AD_RECORD_OVERFLOW", "SSL_AD_ILLEGAL_PARAMETER")),)),
    M("OR3", "R", "WRONG_ALERT_FULL", "VIOLATION", "Cả hai đường kiểm tra độ dài của TLS 1.3 gửi illegal_parameter.",
      ((TLS13, HDR_LEN, sub(HDR_LEN, "SSL_AD_RECORD_OVERFLOW", "SSL_AD_ILLEGAL_PARAMETER")), (TLS13, POST_LEN, sub(POST_LEN, "SSL_AD_RECORD_OVERFLOW", "SSL_AD_ILLEGAL_PARAMETER")))),
    M("OX1", "G", "UNRELATED", "COMPLIANT", "Sửa cảnh báo của COOKIE_MISMATCH (handshake_failure ⇒ illegal_parameter): không liên quan tới nhóm chung.",
      ((SRV, COOKIE, sub(COOKIE, "SSL_AD_HANDSHAKE_FAILURE", "SSL_AD_ILLEGAL_PARAMETER")),)),
    M("OX2", "R", "UNRELATED", "COMPLIANT", "Sửa cảnh báo của phiên bản bản ghi sai (decode_error ⇒ illegal_parameter): không liên quan tới độ dài.",
      ((TLS13, VERSION, sub(VERSION, "SSL_AD_DECODE_ERROR", "SSL_AD_ILLEGAL_PARAMETER")),)),
    M("OX3", "U", "UNRELATED", "COMPLIANT", "Sửa cảnh báo của lỗi độ dài tiêu đề (record_overflow ⇒ decode_error) ở đường tiêu đề TLS 1.3 chung: không liên quan tới loại bản ghi.",
      ((TLS13, HDR_LEN, sub(HDR_LEN, "SSL_AD_RECORD_OVERFLOW", "SSL_AD_DECODE_ERROR")),)),
)


def git(*args: str, cwd: Path = REPO) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8").stdout.strip()


def make_worktree(m: M) -> tuple[Path, str, dict[str, list[list[int]]]]:
    wt = SRC / f"openssl-{m.id}"
    if wt.exists():
        git("worktree", "remove", "--force", str(wt))
    git("-c", "core.autocrlf=false", "-c", "core.eol=lf", "worktree", "add", "--detach", str(wt), TAG)
    texts: dict[str, str] = {}
    for rel, old, new in m.edits:
        text = texts.get(rel) or (wt / rel).read_bytes().decode("utf-8")
        assert "\r\n" not in text and text.count(old) == 1, (m.id, rel, old[:60], text.count(old))
        texts[rel] = text.replace(old, new, 1)
    for rel, text in texts.items():
        (wt / rel).write_bytes(text.encode("utf-8"))
        git("add", rel, cwd=wt)
    git(*IDENT, "commit", "-q", "-m", f"mutant {m.id} {m.operator}", cwd=wt)
    spans: dict[str, list[list[int]]] = {}
    for rel in texts:
        out = git("diff", "-U0", "HEAD^", "HEAD", "--", rel, cwd=wt)
        for line in out.splitlines():
            if line.startswith("@@"):
                plus = line.split("+", 1)[1].split(" ", 1)[0]
                start, _, count = plus.partition(",")
                spans.setdefault(rel, []).append([int(start), int(start) + max(int(count or 1), 1) - 1])
    return wt, git("rev-parse", "HEAD", cwd=wt), spans


def build_image(m: M, wt: Path, sha: str) -> None:
    ctx = ROOT / "runs" / "real" / "mutants" / f"openssl-{m.id}"
    shutil.rmtree(ctx, ignore_errors=True)
    for rel in {r for r, _, _ in m.edits}:
        (ctx / "overlay" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(wt / rel, ctx / "overlay" / rel)
    subprocess.run(
        ["docker", "build", "-q", "-f", str(ROOT / "docker" / "eval-openssl-mutant.Dockerfile"), "--build-arg", f"SHA={sha}",
         "-t", f"rfcv/sut-openssl:{sha[:12]}", str(ctx)],
        check=True,
    )  # fmt: skip
    print("ảnh", f"rfcv/sut-openssl:{sha[:12]}", flush=True)


CHECKS = {
    "U": ('{"mode":"run","port":4433,"within_ms":1500,"encrypted":false,"content_type":"type_99","length":1}', "type_99"),
    "G": ('{"mode":"run","port":4433,"within_ms":1500,"client_hello":{"key_share":"valid","groups":"disjoint"}}', "disjoint"),
    "R": ('{"mode":"run","port":4433,"within_ms":1500,"length":16700}', "len16700"),
}


def check(m: M, sha: str) -> dict[str, str]:
    """Chạy thẳng runner trên ảnh mutant (không qua hệ thống) với một đầu vào cho từng họ; trả cảnh báo quan sát được."""
    from os import environ

    env = {**environ, "MSYS_NO_PATHCONV": "1"}
    name = f"chk-{m.id}"
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "-w", "/sut", "--network", "none", f"rfcv/sut-openssl:{sha[:12]}", "sleep", "infinity"], check=True, capture_output=True, env=env)
    out: dict[str, str] = {}
    try:
        subprocess.run(["docker", "exec", "-d", name, "sh", "-c", "/sut/openssl s_server -accept 4433 -cert /ref/cert.pem -key /ref/key.pem -tls1_3 -www >/tmp/s.log 2>&1"], check=True, env=env)
        subprocess.run(["sleep", "3"])
        runner = (ROOT / "src" / "rfcv" / "backends" / "tlsfuzzer" / "runner.py").read_bytes().replace(b"\r\n", b"\n")
        for _fam, (req, label) in CHECKS.items():
            res = subprocess.run(["docker", "exec", "-i", name, "/opt/venv/bin/python3", "-", req], input=runner, capture_output=True, env=env)
            line = next((ln for ln in res.stdout.decode("utf-8", "replace").splitlines() if ln.startswith("RFCV_RESULT ")), "RFCV_RESULT {}")
            data = json.loads(line.removeprefix("RFCV_RESULT "))
            out[label] = str(data.get("alert"))
            subprocess.run(["sleep", "1"])
    finally:
        subprocess.run(["docker", "stop", "-t", "1", name], capture_output=True, env=env)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--images", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()
    SRC.mkdir(parents=True, exist_ok=True)
    out = ROOT / "eval" / "dataset" / "mutants" / "mutants_openssl.yaml"
    done: dict[str, dict[str, object]] = {}
    if args.only and out.is_file():
        done = {str(i["id"]): i for i in yaml.safe_load(out.read_text(encoding="utf-8"))["items"]}
    for m in MUTANTS:
        if args.only and m.id not in args.only:
            continue
        wt, sha, spans = make_worktree(m)
        adapter.make_adapter(m.id, sha, FAMILIES[m.family][1])
        if args.images:
            build_image(m, wt, sha)
        observed = check(m, sha) if args.check else {}
        done[m.id] = {
            "id": m.id, "family": m.family, "adapter": f"eval/adapters/tls13-{m.id}", "code_root": f"runs/real/src/openssl-{m.id}",
            "commit": sha, "operator": m.operator, "requirement": FAMILIES[m.family][0], "expected": m.expected, "subtle": m.subtle,
            "fix_location": {"files": spans}, "why": m.why, **({"observed": observed} if observed else {}),
        }  # fmt: skip
        print(m.id, m.family, m.expected, sha[:12], spans, observed, flush=True)
    ordered = [done[m.id] for m in MUTANTS if m.id in done]
    out.write_text(
        "# Bộ lỗi tự sinh trên OpenSSL thật (thẻ openssl-3.6.5), họ U/G/R. `expected` chốt theo ngữ nghĩa phép sửa TRƯỚC khi chạy (scripts/eval_make_mutants_openssl.py).\n"
        + yaml.safe_dump({"items": ordered}, allow_unicode=True, sort_keys=False, width=200),
        encoding="utf-8",
    )
    print("đã ghi", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

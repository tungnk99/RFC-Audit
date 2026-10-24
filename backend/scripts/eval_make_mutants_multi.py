"""Bộ lỗi tự sinh (mutant) trên wolfSSL HEAD cho NHIỀU yêu cầu RFC (bổ sung cho bộ 8 mutant của TLS13-0042).

    uv run python scripts/eval_make_mutants_multi.py [--images]

Họ yêu cầu (RBS tầng B viết tay ở `eval/dataset/real/rbs/`):
- U: loại bản ghi không định nghĩa ⇒ `unexpected_message` (RFC 8446 §5, TLS13-0101, RBS P1);
- G: ClientHello không có nhóm chung ⇒ `handshake_failure` hoặc `insufficient_security` (RFC 8446 §4.1.1, TLS13-0103, RBS P3);
- R: bản ghi quá dài ⇒ `record_overflow` (RFC 8446 §5.2, TLS13-0042, RBS gốc của adapter chuẩn), thêm các kiểu lỗi chưa có trong M1–M8.

Nhãn chuẩn (`expected`) được CHỐT Ở ĐÂY theo ngữ nghĩa của phép sửa so với RFC, TRƯỚC khi chạy hệ thống (N1/N2); phép sửa nào ngữ nghĩa không hiển nhiên
thì dùng `scripts/run_tlsfuzzer_baseline.py` kiểm lại độc lập. Mỗi mutant: worktree LF `runs/real/src/wolfssl-<id>` (một commit trên HEAD),
adapter `eval/adapters/tls13-<id>` (RBS của họ), ảnh mỏng `rfcv/sut-wolfssl:<sha12>` (docker/eval-mutant.Dockerfile). Ghi
`eval/dataset/mutants/mutants_multi.yaml` cùng dạng với `mutants.yaml`.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_build_binaries as binaries
import eval_make_mutants as base

ROOT = base.ROOT
RBS_DIR = ROOT / "eval" / "dataset" / "real" / "rbs"
FILE = base.FILE  # mọi phép sửa nằm trong src/internal.c
BASE_ADAPTER_RBS = ROOT / "adapters" / "tls13" / "examples" / "TLS13-0042.rbs"
FAMILIES = {
    "U": ("TLS13-0101", RBS_DIR / "P1_unknown_record_type.rbs"),
    "G": ("TLS13-0103", RBS_DIR / "P3_no_shared_group.rbs"),
    "R": ("TLS13-0042", BASE_ADAPTER_RBS),
}

UNK = "                case WC_NO_ERR_TRACE(UNKNOWN_RECORD_TYPE):\n                    /* undefined record type, RFC 8446/9846 section 5 */\n                    SendAlert(ssl, alert_fatal, unexpected_message);\n                    break;"
UNK_ALERT = "                    SendAlert(ssl, alert_fatal, unexpected_message);\n"
LEN = "                case WC_NO_ERR_TRACE(LENGTH_ERROR):\n                    /* invalid record length, RFC 8446 section 5.1 */\n                    SendAlert(ssl, alert_fatal, record_overflow);\n                    break;"
GRP = "            case WC_NO_ERR_TRACE(MATCH_SUITE_ERROR):\n            case WC_NO_ERR_TRACE(KEY_SHARE_ERROR):\n            case WC_NO_ERR_TRACE(MISSING_HANDSHAKE_DATA):\n            case WC_NO_ERR_TRACE(PSK_MISSING_ERROR):\n                return handshake_failure;"
INC = "            case WC_NO_ERR_TRACE(INCOMPLETE_DATA):\n                return missing_extension;\n"
BIND = "            case WC_NO_ERR_TRACE(BAD_BINDER):\n                return decrypt_error;"
GRP_NO_KS = "            case WC_NO_ERR_TRACE(MATCH_SUITE_ERROR):\n            case WC_NO_ERR_TRACE(MISSING_HANDSHAKE_DATA):\n            case WC_NO_ERR_TRACE(PSK_MISSING_ERROR):\n                return handshake_failure;"
VER = "                        SendAlert(ssl, alert_fatal,\n                            wolfssl_alert_protocol_version);"
SITE2 = base.SITE2


@dataclass(frozen=True)
class M:
    id: str
    family: str
    operator: str
    expected: str
    why: str
    edits: tuple[tuple[str, str], ...]
    subtle: bool = False


def ks_to(alert: str) -> tuple[tuple[str, str], ...]:
    """KEY_SHARE_ERROR rời nhóm handshake_failure và được ánh xạ sang `alert`."""
    return ((GRP, GRP_NO_KS), (INC, f"            case WC_NO_ERR_TRACE(KEY_SHARE_ERROR):\n                return {alert};\n" + INC))


# Chỉ chấp nhận phép sửa/xoá DÒNG CÓ SẴN trong mã thật (đổi hằng số alert, xoá lệnh gọi, đổi ngưỡng, đảo nhãn). Các mutant dưới đây có thêm mã mới
# (macro giả, biến cục bộ, điều kiện tự thêm) nên bị loại khỏi bộ đánh giá nhưng kết quả cũ vẫn giữ để đối chiếu.
EXCLUDED = {
    "U3": "thêm #ifdef với macro giả", "U5": "thêm điều kiện if tự viết", "U6": "thêm biến cục bộ", "R11": "thêm biến cục bộ",
    "R13": "đường sau giải mã: vi phạm câu RFC khác câu mà RBS TLS13-0042 kiểm", "R15": "đường sau giải mã: vi phạm câu RFC khác câu mà RBS TLS13-0042 kiểm",
}  # fmt: skip

MUTANTS: tuple[M, ...] = (
    # ---- U: loại bản ghi lạ ⇒ unexpected_message
    M("U1", "U", "WRONG_ALERT", "VIOLATION", "Loại bản ghi không định nghĩa bị cảnh báo illegal_parameter thay vì unexpected_message.",
      ((UNK, UNK.replace("unexpected_message", "illegal_parameter")),)),
    M("U2", "U", "DEL_ALERT", "VIOLATION", "Bỏ lời gọi gửi unexpected_message: bản ghi loại lạ bị từ chối lặng lẽ, không cảnh báo.",
      ((UNK, UNK.replace(UNK_ALERT, "")),)),
    M("U3", "U", "IFDEF_TRAP", "VIOLATION", "Lời gọi gửi unexpected_message bị bọc trong #ifdef của macro không bao giờ bật (bẫy đọc lướt).",
      ((UNK, UNK.replace(UNK_ALERT, "#ifdef RFCV_MUTANT_ALERT_ENABLED\n" + UNK_ALERT + "#endif\n")),)),
    M("U4", "U", "WRONG_ALERT_OTHER", "VIOLATION", "Loại bản ghi lạ bị cảnh báo decode_error thay vì unexpected_message.",
      ((UNK, UNK.replace("unexpected_message", "decode_error")),)),
    M("U5", "U", "WRONG_ALERT_NARROW", "VIOLATION",
      "Chỉ loại bản ghi 77 (ngoài các giá trị 0, 99, 255 mà RBS thử) mất cảnh báo; các loại còn lại vẫn đúng. Tinh vi: phụ thuộc độ phủ biến thể của oracle.",
      ((UNK, UNK.replace(UNK_ALERT, "                    if (ssl->curRL.type != 77)\n    " + UNK_ALERT)),), subtle=True),
    M("U6", "U", "EQUIVALENT", "COMPLIANT", "Đưa mã cảnh báo qua biến cục bộ: hành vi quan sát được không đổi.",
      ((UNK, UNK.replace(UNK_ALERT, "                    {\n                        int rfcvAlert = unexpected_message;\n                        SendAlert(ssl, alert_fatal, rfcvAlert);\n                    }\n")),)),
    M("U7", "U", "UNRELATED", "COMPLIANT", "Sửa cảnh báo của lỗi độ dài bản ghi (record_overflow ⇒ decode_error): không liên quan tới loại bản ghi.",
      ((LEN, LEN.replace("record_overflow", "decode_error")),)),
    M("U8", "U", "UNRELATED", "COMPLIANT", "Sửa cảnh báo của VERSION_ERROR phía khách: không liên quan tới loại bản ghi.",
      ((VER, VER.replace("wolfssl_alert_protocol_version", "illegal_parameter")),)),
    # ---- G: không có nhóm chung ⇒ handshake_failure | insufficient_security
    M("G1", "G", "WRONG_ALERT", "VIOLATION", "KEY_SHARE_ERROR (không có nhóm chung) được ánh xạ sang illegal_parameter thay vì handshake_failure.",
      ks_to("illegal_parameter")),
    M("G2", "G", "WRONG_ALERT_OTHER", "VIOLATION", "KEY_SHARE_ERROR được ánh xạ sang internal_error.", ks_to("internal_error")),
    M("G3", "G", "WRONG_ALERT_OTHER", "VIOLATION", "KEY_SHARE_ERROR được ánh xạ sang decode_error.", ks_to("decode_error")),
    M("G4", "G", "ALLOWED_ALTERNATIVE", "COMPLIANT",
      "KEY_SHARE_ERROR được ánh xạ sang insufficient_security: RFC 8446 §4.1.1 cho phép (RBS có accept_alternatives).", ks_to("insufficient_security")),
    M("G5", "G", "EQUIVALENT", "COMPLIANT", "Đổi thứ tự nhãn case trong cùng nhóm handshake_failure: hành vi không đổi.",
      ((GRP, "            case WC_NO_ERR_TRACE(MATCH_SUITE_ERROR):\n            case WC_NO_ERR_TRACE(MISSING_HANDSHAKE_DATA):\n            case WC_NO_ERR_TRACE(PSK_MISSING_ERROR):\n            case WC_NO_ERR_TRACE(KEY_SHARE_ERROR):\n                return handshake_failure;"),)),
    M("G6", "G", "UNRELATED", "COMPLIANT", "Sửa cảnh báo của BAD_BINDER (decrypt_error ⇒ illegal_parameter): không liên quan tới nhóm chung.",
      ((BIND, BIND.replace("decrypt_error", "illegal_parameter")),)),
    M("G7", "G", "UNRELATED", "COMPLIANT", "Sửa cảnh báo của INCOMPLETE_DATA (missing_extension ⇒ decode_error): không liên quan tới nhóm chung.",
      ((INC, INC.replace("missing_extension", "decode_error")),)),
    # ---- R: bản ghi quá dài ⇒ record_overflow (kiểu lỗi mới)
    M("R9", "R", "WRONG_ALERT_FULL", "VIOLATION", "Cả hai đường kiểm tra độ dài gửi illegal_parameter thay vì record_overflow.",
      ((base.SITE1, base.SITE1.replace("record_overflow", "illegal_parameter", 1)), (SITE2, SITE2.replace("record_overflow", "illegal_parameter", 1)))),
    M("R10", "R", "WRONG_ALERT_HEADER_ONLY", "VIOLATION", "Chỉ đường kiểm tra tiêu đề (độ dài > 16486) gửi internal_error; đường sau giải mã vẫn đúng.",
      ((base.SITE1, base.SITE1.replace("record_overflow", "internal_error", 1)),)),
    M("R11", "R", "EQUIVALENT", "COMPLIANT", "Đưa mã cảnh báo qua biến cục bộ ở đường sau giải mã: hành vi không đổi.",
      ((SITE2, SITE2.replace("SendAlert(ssl, alert_fatal, record_overflow);", "{ int rfcvAlert = record_overflow; SendAlert(ssl, alert_fatal, rfcvAlert); }")),)),
    M("R12", "R", "UNRELATED", "COMPLIANT", "Sửa cảnh báo của loại bản ghi lạ (unexpected_message ⇒ illegal_parameter): không liên quan tới độ dài.",
      ((UNK, UNK.replace("unexpected_message", "illegal_parameter")),)),
    # ---- đợt 2 (đẩy bộ lên 50 mẫu): kiểu lỗi và vị trí mới
    M("U13", "U", "UNRELATED", "COMPLIANT", "Sửa cảnh báo của đường độ dài sau giải mã (record_overflow ⇒ decode_error): không liên quan tới loại bản ghi.",
      ((SITE2, SITE2.replace("record_overflow", "decode_error", 1)),)),
    M("U14", "U", "WRONG_ALERT_OTHER", "VIOLATION", "Loại bản ghi lạ bị cảnh báo handshake_failure thay vì unexpected_message.",
      ((UNK, UNK.replace("unexpected_message", "handshake_failure")),)),
    M("G8", "G", "WRONG_ALERT_OTHER", "VIOLATION", "KEY_SHARE_ERROR được ánh xạ sang protocol_version.", ks_to("wolfssl_alert_protocol_version")),
    M("G9", "G", "WRONG_ALERT_OTHER", "VIOLATION", "KEY_SHARE_ERROR được ánh xạ sang unexpected_message.", ks_to("unexpected_message")),
    M("G11", "G", "UNRELATED", "COMPLIANT", "Sửa cảnh báo của MATCH_SUITE_ERROR (handshake_failure ⇒ illegal_parameter): lỗi cipher suite, không phải nhóm chung.",
      ((GRP, "            case WC_NO_ERR_TRACE(MATCH_SUITE_ERROR):\n                return illegal_parameter;\n            case WC_NO_ERR_TRACE(KEY_SHARE_ERROR):\n            case WC_NO_ERR_TRACE(MISSING_HANDSHAKE_DATA):\n            case WC_NO_ERR_TRACE(PSK_MISSING_ERROR):\n                return handshake_failure;"),)),
    M("G12", "G", "WRONG_ALERT_OTHER", "VIOLATION", "KEY_SHARE_ERROR được ánh xạ sang bad_certificate.", ks_to("bad_certificate")),
    M("R13", "R", "WRONG_ALERT_POSTDECRYPT", "VIOLATION",
      "Chỉ đường kiểm tra sau giải mã (16402–16486) gửi internal_error; trên 16486 vẫn đúng. Tinh vi: cùng kiểu M4 với mã cảnh báo khác.",
      ((SITE2, SITE2.replace("record_overflow", "internal_error", 1)),), subtle=True),
    M("R14", "R", "WRONG_ALERT_FULL", "VIOLATION", "Cả hai đường kiểm tra độ dài gửi decode_error thay vì record_overflow.",
      ((base.SITE1, base.SITE1.replace("record_overflow", "decode_error", 1)), (SITE2, SITE2.replace("record_overflow", "decode_error", 1)))),
    M("R15", "R", "DEL_ALERT_POSTDECRYPT", "VIOLATION", "Chỉ đường kiểm tra sau giải mã bỏ cảnh báo record_overflow. Tinh vi: bản ghi quá dài rõ ràng vẫn được cảnh báo.",
      ((SITE2, SITE2.replace("                    SendAlert(ssl, alert_fatal, record_overflow);\n", "", 1)),), subtle=True),
    M("R16", "R", "EQUIVALENT", "COMPLIANT", "Đổi nội dung thông điệp nhật ký ở đường sau giải mã: hành vi quan sát được không đổi.",
      ((SITE2, SITE2.replace("Encrypted data too long", "Encrypted record too long", 1)),)),
    M("R17", "R", "UNRELATED", "COMPLIANT", "Sửa cảnh báo của BAD_BINDER (decrypt_error ⇒ illegal_parameter): không liên quan tới độ dài.",
      ((BIND, BIND.replace("decrypt_error", "illegal_parameter")),)),
)


def make_worktree(m: M) -> tuple[Path, str]:
    wt = base.SRC / f"wolfssl-{m.id}"
    if wt.exists():
        base.git("worktree", "remove", "--force", str(wt))
    base.git("-c", "core.autocrlf=false", "-c", "core.eol=lf", "worktree", "add", "--detach", str(wt), base.BASE_COMMIT)
    path = wt / FILE
    text = path.read_bytes().decode("utf-8")
    assert "\r\n" not in text
    for old, new in m.edits:
        assert text.count(old) == 1, (m.id, old[:70], text.count(old))
        text = text.replace(old, new, 1)
    path.write_bytes(text.encode("utf-8"))
    base.git("add", FILE, cwd=wt)
    base.git(*base.IDENT, "commit", "-q", "-m", f"mutant {m.id} {m.operator}", cwd=wt)
    return wt, base.git("rev-parse", "HEAD", cwd=wt)


def make_adapter(m: M, sha: str) -> None:
    _, rbs = FAMILIES[m.family]
    dst = binaries.make_adapter(sha, rbs)  # từ adapter chuẩn hiện tại + cờ build thật + RBS của họ
    target = ROOT / "eval" / "adapters" / f"tls13-{m.id}"
    if target.exists():
        import shutil

        shutil.rmtree(target)
    dst.rename(target)


def build_image(m: M, wt: Path, sha: str) -> None:
    base.build_image(base.Mutant(m.id, m.operator, m.expected, m.why, m.edits), wt, sha)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--images", action="store_true")
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()
    base.SRC.mkdir(parents=True, exist_ok=True)
    out = ROOT / "eval" / "dataset" / "mutants" / "mutants_multi.yaml"
    done: dict[str, dict[str, object]] = {}
    if args.only and out.is_file():  # chỉ dựng lại một phần: giữ nguyên các mục khác (cùng commit, cùng ảnh)
        done = {str(i["id"]): i for i in yaml.safe_load(out.read_text(encoding="utf-8"))["items"]}
    for m in MUTANTS:
        if args.only and m.id not in args.only:
            continue
        wt, sha = make_worktree(m)
        spans = base.changed_lines(wt)
        make_adapter(m, sha)
        if args.images:
            build_image(m, wt, sha)
        done[m.id] = {
            "id": m.id, "family": m.family, "adapter": f"eval/adapters/tls13-{m.id}", "code_root": f"runs/real/src/wolfssl-{m.id}",
            "commit": sha, "operator": m.operator, "requirement": FAMILIES[m.family][0], "expected": m.expected,
            "subtle": m.subtle, **({"excluded": EXCLUDED[m.id]} if m.id in EXCLUDED else {}), "fix_location": {"file": FILE, "lines": [list(s) for s in spans]}, "why": m.why,
        }  # fmt: skip
        print(m.id, m.family, m.expected, sha[:12], spans, flush=True)
    for mid, why_excluded in EXCLUDED.items():
        if mid in done:
            done[mid]['excluded'] = why_excluded
    ordered = [done[m.id] for m in MUTANTS if m.id in done]
    out.write_text(
        "# Bộ lỗi tự sinh đa họ yêu cầu (U/G/R). Nhãn `expected` chốt theo ngữ nghĩa phép sửa TRƯỚC khi chạy (scripts/eval_make_mutants_multi.py).\n"
        + yaml.safe_dump({"items": ordered}, allow_unicode=True, sort_keys=False, width=200),
        encoding="utf-8",
    )
    print("đã ghi", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

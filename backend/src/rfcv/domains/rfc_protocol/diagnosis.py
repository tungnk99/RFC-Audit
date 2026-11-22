"""Chẩn đoán từ hành vi chạy thật: T3 cho biết lỗi KIỂU GÌ trước khi ai đọc mã (hàm thuần, không LLM).

Code Reader hiện bắt đầu từ con số không và tự mò ra chuyện gì đang xảy ra (đo: 15–28 lần gọi công cụ, 145–260k token). Nhưng T3 đã
nói gần hết: nếu mọi ca vượt ngưỡng đều `alert = none` thì đọc ngưỡng chẳng giải thích được gì, phải tìm xem phản ứng có chạy không;
nếu có cảnh báo nhưng sai mã thì tìm lời gọi gửi mã sai. Chữ ký lỗi + giả thuyết này đi vào ngữ cảnh của Code Reader để nó kiểm chứng
giả thuyết thay vì mò từ đầu. Đây chỉ là gợi ý hướng đọc: bằng chứng T1 vẫn phải qua Schema gate như mọi khi.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from rfcv.domains.rfc_protocol.payloads import Outcome, T3Payload

REACTION_ABSENT = "reaction_absent"
WRONG_ALERT = "wrong_alert"
NO_CLOSE = "no_close"
THRESHOLD_OFF = "threshold_off"
NONE = "none"


@dataclass(frozen=True)
class Diagnosis:
    signature: str
    hypothesis: str
    next_step: str
    expected_alert: str | None = None
    observed_alerts: tuple[str, ...] = ()
    failing_cases: int = 0
    passing_cases: int = 0

    def to_json(self) -> dict[str, object]:
        return asdict(self)


def _is_waived(t: T3Payload) -> bool:
    return (t.variant_class == "control" or t.side == "valid") and t.witness.all_positive_fail


def _trigger_cases(t3s: Sequence[T3Payload]) -> list[T3Payload]:
    """Ca phía kích hoạt đủ tin cậy để chẩn đoán: kích hoạt đạt, nhất quán, có nhân chứng dương."""
    return [
        t
        for t in t3s
        if t.side == "trigger"
        and t.trigger_reached
        and t.consistent
        and t.witness.has_positive
        and not _is_waived(t)
        and t.outcome in (Outcome.PASS, Outcome.FAIL)
    ]


def diagnose(expected_alert: str | None, t3s: Sequence[T3Payload]) -> Diagnosis:
    cases = _trigger_cases(t3s)
    fails = [t for t in cases if t.outcome is Outcome.FAIL]
    passes = [t for t in cases if t.outcome is Outcome.PASS]
    if not fails:
        return Diagnosis(NONE, "Không có ca phía kích hoạt nào FAIL.", "Không cần định vị lỗi.", expected_alert)
    alerts = tuple(sorted({str(t.observed.get("alert", "none")) for t in fails}))

    def make(signature: str, hypothesis: str, next_step: str) -> Diagnosis:
        return Diagnosis(signature, hypothesis, next_step, expected_alert, alerts, len(fails), len(passes))

    code = expected_alert or "<mã cảnh báo yêu cầu>"
    if alerts == ("none",):
        if not passes:
            return make(
                REACTION_ABSENT,
                f"SUT không phát cảnh báo nào ở MỌI ca kích hoạt: phản ứng `{code}` không chạy. "
                "Nguyên nhân thường là phản ứng bị thiếu, bị biên dịch bỏ (`#ifdef`), hoặc nằm sau điều kiện không bao giờ đúng.",
                f"Tìm mọi nơi phát `{code}` (grep không phân biệt hoa thường), đọc điều kiện bảo vệ từng nơi (`#ifdef`/`#if`), "
                "kiểm `defined()` của macro bảo vệ bằng `code__eval`; đọc luồng khi phép kiểm tra thất bại để xem nó rơi vào đâu. "
                "Vị trí lỗi là nơi phản ứng lẽ ra có.",
            )
        return make(
            THRESHOLD_OFF,
            "SUT có phản ứng ở một số ca kích hoạt nhưng không có ở các ca khác: ngưỡng hoặc điều kiện kiểm tra lệch so với yêu cầu.",
            "Tìm phép so sánh quyết định phản ứng, khai triển hằng/ngưỡng bằng `code__eval`, so với giá trị trong `where`.",
        )
    wrong = tuple(a for a in alerts if a != "none" and a != expected_alert)
    if expected_alert is not None and wrong:
        observed = ", ".join(wrong)
        return make(
            WRONG_ALERT,
            f"SUT có phát cảnh báo sai khác `{code}` (quan sát: {', '.join(alerts)}).",
            f"Ưu tiên kiểm tra các lời gọi gửi `{observed}` trong `code.candidates` trên đường xử lý yêu cầu tương ứng và so với `{code}`.",
        )
    return make(
        NO_CLOSE,
        f"SUT phát `{code}` nhưng ca vẫn FAIL: kết nối không được đóng hay đóng quá chậm.",
        "Đọc nơi gửi cảnh báo: sau đó luồng có dừng xử lý hoặc đóng kết nối không.",
    )


def candidate_patterns(expected_alert: str | None, observed_alerts: Sequence[str] = ()) -> list[str]:
    """Sinh mẫu regex không phân biệt hoa thường cho `code.grep` (khớp cả `record_overflow`, `SSL_AD_RECORD_OVERFLOW`, `GNUTLS_A_...`).

    Khi SUT phát cảnh báo sai (`WRONG_ALERT`), ưu tiên tìm `observed_alerts` trước vì dòng lỗi thực tế gọi mã cảnh báo sai đó."""
    ordered: list[str] = []
    for raw in (*observed_alerts, expected_alert):
        if not raw or raw == "none":
            continue
        term = raw.strip()
        if term and term not in ordered:
            ordered.append(term)
    return [rf"(?i)\b[A-Za-z0-9_]*{re.escape(term)}\b" for term in ordered]

"""Họ lỗi của bộ mô phỏng: các cài đặt giao thức giả có lỗi gieo sẵn, tham số hoá theo seed.

Mô phỏng một yêu cầu kiểu RFC 8446 §5.2: nhận bản ghi dài hơn LIMIT thì phải gửi cảnh báo `record_overflow` rồi đóng kết nối; bản ghi
không dài hơn thì không được phản ứng. Mỗi cài đặt là hàm thuần (độ dài, môi trường) -> phản ứng.

ĐÂY LÀ MÔ PHỎNG (SYNTHETIC): đo cơ chế phát hiện của chiến lược kiểm thử, không phải độ chính xác trên cài đặt thật.
Chia theo họ lỗi: `train` để chỉnh siêu tham số, `test` chỉ chấm một lần sau khi đã đóng băng cấu hình.
Chưa mô hình hoá: lỗi phụ thuộc trạng thái (cần nhiều trạng thái giao thức), nhiều trường trong một kích hoạt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from rfcv.common.prng import hash_randint

LIMIT = 16640  # 2^14 + 256
DOMAIN = (0, 65535)
CANONICAL = frozenset({16641, 65535})  # giá trị mà bộ kiểm thử thông dụng hay dùng; mã nhận ra kiểm thử nhắm vào chúng
ENVIRONMENTS = (0, 1)  # môi trường 0 là lần chạy đầu; môi trường 1 là lần chạy lại ở nơi khác
REFERENCE_NAMES = ("ref_a", "ref_b")


@dataclass(frozen=True)
class SimResponse:
    alert: str = "none"
    closed: bool = False
    crashed: bool = False


NO_REACTION = SimResponse()
CORRECT_REACTION = SimResponse("record_overflow", True)

Behaviour = Callable[[int, int], SimResponse]  # (độ dài, môi trường) -> phản ứng


def correct_behaviour(length: int, environment: int) -> SimResponse:
    return CORRECT_REACTION if length > LIMIT else NO_REACTION


@dataclass(frozen=True)
class SimImpl:
    name: str
    kind: Literal["correct", "alt_valid", "faulty"]
    behaviour: Behaviour
    family: str | None = None
    params: dict[str, int] = field(default_factory=dict[str, int])
    seed: int = 0  # seed của chính cài đặt lỗi; cũng là seed lấy mẫu biến thể khi chấm

    def deviates_from_correct(self) -> bool:
        """Quét vét cạn: có giá trị/môi trường nào làm khác cài đặt đúng? Đây là trần phát hiện bằng hộp đen (rất đắt)."""
        lo, hi = DOMAIN
        return any(
            self.behaviour(v, env) != correct_behaviour(v, env) for v in range(lo, hi + 1) for env in ENVIRONMENTS
        )


@dataclass(frozen=True)
class FaultFamily:
    name: str
    split: Literal["train", "test"]
    make: Callable[[int], SimImpl]
    description: str


def _inst(family: str, seed: int, behaviour: Behaviour, **params: int) -> SimImpl:
    return SimImpl(f"{family}-{seed}", "faulty", behaviour, family, dict(params), seed)


def _threshold(seed: int) -> SimImpl:
    delta = (-150, -64, -2, -1, 1, 2, 64, 150)[seed % 8]
    return _inst(
        "threshold",
        seed,
        lambda v, env: CORRECT_REACTION if v > LIMIT + delta else NO_REACTION,
        delta=delta,
    )


def _wrong_alert(seed: int) -> SimImpl:
    wrong = SimResponse("handshake_failure", True)
    return _inst("wrong_alert", seed, lambda v, env: wrong if v > LIMIT else NO_REACTION)


def _no_close(seed: int) -> SimImpl:
    open_ = SimResponse("record_overflow", False)
    return _inst("no_close", seed, lambda v, env: open_ if v > LIMIT else NO_REACTION)


def _window_miss(seed: int) -> SimImpl:
    width = hash_randint(64, 2048, "window_miss.w", seed)
    start = hash_randint(LIMIT + 1, DOMAIN[1] - width, "window_miss.a", seed)
    return _inst(
        "window_miss",
        seed,
        lambda v, env: NO_REACTION if start <= v < start + width else correct_behaviour(v, env),
        start=start,
        width=width,
    )


def _valid_reject_window(seed: int) -> SimImpl:
    width = hash_randint(64, 4096, "valid_reject_window.w", seed)
    start = hash_randint(0, LIMIT - width, "valid_reject_window.a", seed)
    return _inst(
        "valid_reject_window",
        seed,
        lambda v, env: CORRECT_REACTION if start <= v < start + width else correct_behaviour(v, env),
        start=start,
        width=width,
    )


def _valid_reject_low(seed: int) -> SimImpl:
    below = hash_randint(1, 2048, "valid_reject_low.t", seed)
    return _inst(
        "valid_reject_low",
        seed,
        lambda v, env: CORRECT_REACTION if v < below else correct_behaviour(v, env),
        below=below,
    )


def _a7_canonical(seed: int) -> SimImpl:
    """Mã nhận ra giá trị kiểm thử thông dụng: chỉ phản ứng đúng với chúng, còn lại bỏ qua (tấn công A7 mức 1)."""
    return _inst(
        "a7_canonical",
        seed,
        lambda v, env: CORRECT_REACTION if v in CANONICAL else NO_REACTION,
    )


def _env_aware(seed: int) -> SimImpl:
    """Mã nhận ra môi trường kiểm thử (tên máy, thời gian): đúng ở lần chạy đầu, sai ở môi trường khác (A7 mức 2)."""
    return _inst(
        "env_aware",
        seed,
        lambda v, env: correct_behaviour(v, env) if env == 0 else NO_REACTION,
    )


def _magic(seed: int) -> SimImpl:
    """Bỏ qua đúng một giá trị hiếm: bằng hộp đen chỉ bắt được nếu may mắn hoặc quét vét cạn."""
    candidates = [v for v in range(LIMIT + 1, DOMAIN[1] + 1) if v not in CANONICAL]
    magic = candidates[hash_randint(0, len(candidates) - 1, "magic", seed)]
    return _inst(
        "magic",
        seed,
        lambda v, env: NO_REACTION if v == magic else correct_behaviour(v, env),
        value=magic,
    )


FAMILIES: tuple[FaultFamily, ...] = (
    FaultFamily("threshold", "train", _threshold, "ngưỡng dịch ±Δ so với RFC (đơn điệu)"),
    FaultFamily("wrong_alert", "train", _wrong_alert, "gửi sai mã cảnh báo"),
    FaultFamily("no_close", "train", _no_close, "gửi cảnh báo nhưng không đóng kết nối"),
    FaultFamily("window_miss", "test", _window_miss, "bỏ qua một cửa sổ giá trị ở phía vi phạm"),
    FaultFamily("valid_reject_window", "test", _valid_reject_window, "từ chối nhầm một cửa sổ giá trị hợp lệ"),
    FaultFamily("valid_reject_low", "test", _valid_reject_low, "từ chối nhầm các giá trị hợp lệ nhỏ"),
    FaultFamily("a7_canonical", "test", _a7_canonical, "chỉ đúng với giá trị kiểm thử thông dụng (A7 mức 1)"),
    FaultFamily("env_aware", "test", _env_aware, "chỉ đúng ở môi trường kiểm thử đầu tiên (A7 mức 2)"),
    FaultFamily("magic", "test", _magic, "bỏ qua đúng một giá trị hiếm"),
)


def correct_impl() -> SimImpl:
    return SimImpl("correct", "correct", correct_behaviour)


def alt_valid_impl() -> SimImpl:
    """Hợp lệ theo RBS có `accept_alternatives send_alert(decode_error)`: gửi cảnh báo thay thế rồi đóng."""
    alt = SimResponse("decode_error", True)
    return SimImpl("alt_valid", "alt_valid", lambda v, env: alt if v > LIMIT else NO_REACTION)


def references() -> tuple[SimImpl, ...]:
    """Hai bản tham chiếu độc lập (đúng) làm nhân chứng dương."""
    return tuple(SimImpl(name, "correct", correct_behaviour) for name in REFERENCE_NAMES)

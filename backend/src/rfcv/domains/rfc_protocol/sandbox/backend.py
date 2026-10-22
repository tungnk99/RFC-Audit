"""Giao diện backend (I9; thiết kế chính, mục 4.3) và vòng đời SUT.

Backend là plugin: kiểm tra và chạy kịch bản DSL, trả vết sự kiện chuẩn hoá theo từ vựng adapter.
Nhật ký, gói tin thô chỉ vào Artifact store, không bao giờ tới agent (rủi ro A2).
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Protocol

from rfcv.domains.rfc_protocol.schemas import ScenarioProposal
from rfcv.domains.rfc_protocol.spec.oracle_compiler import ObservedEvent


@dataclass(frozen=True)
class Endpoint:
    impl: str
    host: str
    port: int


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class EventTrace:
    events: tuple[ObservedEvent, ...]
    trigger_reached: bool
    sut_alive_after: bool = True
    # Observation@1: mọi trường có miền hữu hạn (alert, closed, response…)
    observation: dict[str, str | int | bool] = field(default_factory=dict[str, str | int | bool])
    raw_log: bytes = b""
    pcap: bytes = b""
    lcov: bytes = b""


class Backend(Protocol):
    name: str

    def validate(self, scenario: ScenarioProposal) -> ValidationResult: ...

    async def sanity(self, endpoint: Endpoint) -> bool: ...

    async def run(
        self, scenario: ScenarioProposal, params: dict[str, int | str], endpoint: Endpoint, seed: int
    ) -> EventTrace: ...


class SutLauncher(Protocol):
    """Tạo SUT mới cho mỗi ca (per_case_process), trên mạng nội bộ riêng, huỷ ngay sau đó.

    Bản Docker thật đặt tên máy, địa chỉ, đồng hồ khác nhau giữa các lần chạy (đa dạng môi trường, M7).
    """

    def start(self, impl: str, *, coverage: bool, environment: int) -> AbstractAsyncContextManager[Endpoint]: ...


class DockerSutLauncher:
    """Chưa cài đặt: dựng ở tuần 1–2 tháng 11 (tài liệu adapter, Bảng 12)."""

    def start(self, impl: str, *, coverage: bool, environment: int) -> AbstractAsyncContextManager[Endpoint]:
        raise NotImplementedError("DockerSutLauncher: cài đặt cùng công thức SUT của adapter (docker-py, rootless)")

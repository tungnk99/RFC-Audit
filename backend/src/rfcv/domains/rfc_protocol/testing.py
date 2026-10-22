"""Hợp đồng kiểm thử cho backend và bộ chạy SUT của miền RFC giao thức (dùng cho tlsfuzzer, TLS-Attacker, DNS…)."""

from __future__ import annotations

from typing import Any

from rfcv.domains.rfc_protocol.sandbox.backend import Backend, SutLauncher
from rfcv.domains.rfc_protocol.schemas import ScenarioProposal
from rfcv.domains.rfc_protocol.spec.oracle_compiler import ObservedEvent


async def check_backend_contract(
    backend: Backend, launcher: SutLauncher, good: ScenarioProposal, impl: str
) -> list[str]:
    """Backend phải: có tên; `validate` tất định và từ chối kịch bản không có bước `expect`; `run` trên kịch bản hợp lệ
    trả vết sự kiện chuẩn hoá (ObservedEvent) cùng cờ `trigger_reached`, và không ném ngoại lệ."""
    problems: list[str] = []
    if not getattr(backend, "name", ""):
        problems.append("backend phải có thuộc tính name")
    first, second = backend.validate(good), backend.validate(good)
    if first != second:
        problems.append("validate không tất định")
    if not first.ok:
        problems.append(f"validate từ chối kịch bản hợp lệ: {first.errors}")
    without_expect = [step for step in good.steps if step.op != "expect"]
    if without_expect and backend.validate(good.model_copy(update={"steps": without_expect})).ok:
        problems.append("validate chấp nhận kịch bản không có bước expect")
    params: dict[str, int | str] = {name: 16641 for name in good.bindings}
    async with launcher.start(impl, coverage=False, environment=0) as endpoint:
        sanity: Any = await backend.sanity(endpoint)  # đầu ra plugin: kiểm ở thời gian chạy, không tin kiểu khai báo
        if not isinstance(sanity, bool):
            problems.append("sanity phải trả bool")
        try:
            trace: Any = await backend.run(good, params, endpoint, 1)
        except Exception as exc:
            return [*problems, f"run ném ngoại lệ trên kịch bản hợp lệ: {type(exc).__name__}"]
    if not isinstance(trace.trigger_reached, bool):
        problems.append("EventTrace.trigger_reached phải là bool")
    if not all(isinstance(e, ObservedEvent) for e in trace.events):
        problems.append("events phải là ObservedEvent đã chuẩn hoá")
    return problems


async def check_sut_launcher_contract(launcher: SutLauncher, impl: str) -> list[str]:
    """Mỗi lần `start` phải cho Endpoint đúng impl, kể cả khi đổi `environment` (đa dạng môi trường, M7)."""
    problems: list[str] = []
    seen: list[object] = []
    for env in (0, 1):
        async with launcher.start(impl, coverage=False, environment=env) as ep:
            if ep.impl != impl:
                problems.append(f"Endpoint.impl = {ep.impl!r}, mong đợi {impl!r}")
            seen.append(ep)
    if not seen:
        problems.append("không khởi động được SUT")
    return problems

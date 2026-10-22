"""Gắn mã lỗi phối hợp (theo tinh thần MAST, arXiv 2503.13657) từ dấu vết một lần điều tra. Hàm thuần trên danh sách sự kiện.

Chạy được trên dấu vết thật lẫn mô phỏng: cùng một bộ nhãn để so sánh. Chỉ gắn mã khi dấu vết CÓ bằng chứng; mã cần dữ liệu mà
hub không ghi thì không có ở đây, không đoán. Mô phỏng chạy qua cùng hub nên cũng ghi `critique_result`; số đếm mã trong báo
cáo mô phỏng chỉ để quan sát, không vào quyết định của đăng ký trước.

| Mã                       | Dấu hiệu trong trace                                                            |
|--------------------------|---------------------------------------------------------------------------------|
| FM_STEP_REPETITION       | cùng kiểu nhiệm vụ được giao ở hai kế hoạch liên tiếp, báo cáo độ đủ không đổi |
| FM_PREMATURE_STOP        | có `stop_rejected`                                                              |
| FM_TASK_SPEC_VIOLATION   | có `task_rejected` ngoài khoảng trống năng lực đã biết                          |
| CAPABILITY_GAP           | `task_rejected` cho nhiệm vụ nằm trong danh sách chưa có handler                |
| FM_PLANNER_FAILURE       | `role_failure` của Planner                                                      |
| FM_WORKER_FAILURE        | `role_failure` của vai trò khác                                                 |
| FM_GATE_REJECTED         | `gate_reject`                                                                   |
| FM_UNAWARE_TERMINATION   | dừng do BUDGET/LOOP trong khi ba báo cáo độ đủ cuối giống hệt nhau              |
| FM_CRITIQUE_IGNORED      | ngay sau `critique_result` có vấn đề, kế hoạch kế tiếp không giao nhiệm vụ nào  |
|                          | trong số nhiệm vụ Verifier đề xuất (bỏ các nhiệm vụ chưa có handler) hoặc dừng |
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from typing import Any

TAGS = (
    "FM_STEP_REPETITION",
    "FM_PREMATURE_STOP",
    "FM_TASK_SPEC_VIOLATION",
    "CAPABILITY_GAP",
    "FM_PLANNER_FAILURE",
    "FM_WORKER_FAILURE",
    "FM_GATE_REJECTED",
    "FM_UNAWARE_TERMINATION",
    "FM_CRITIQUE_IGNORED",
)


def _body(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k != "round"}


def classify_trace(events: Iterable[Mapping[str, Any]], *, unavailable_tasks: Collection[str] = ()) -> frozenset[str]:
    tags: set[str] = set()
    last_report: dict[str, Any] | None = None
    last_plan_tasks: frozenset[str] = frozenset()
    reports: list[dict[str, Any]] = []
    stop_reason: str | None = None
    repeated_plan = False
    advised: frozenset[str] = frozenset()  # nhiệm vụ Verifier vừa đề xuất mà kế hoạch kế tiếp chưa xử lý
    for e in events:
        kind, payload = e["kind"], e.get("payload", {})
        if kind == "sufficiency":
            body = _body(payload)
            if last_report is not None and body == last_report and repeated_plan:
                tags.add("FM_STEP_REPETITION")
            last_report = body
            reports.append(body)
            repeated_plan = False
        elif kind == "critique_result":
            suggested = {str(i.get("suggested_task")) for i in payload.get("issues", [])}
            advised = frozenset(suggested - set(unavailable_tasks))
        elif kind == "plan":
            tasks = frozenset(str(t["task_type"]) for t in payload.get("tasks", []))
            if advised and not tasks & advised:
                tags.add("FM_CRITIQUE_IGNORED")
            advised = frozenset()
            repeated_plan = bool(tasks) and tasks == last_plan_tasks
            if tasks:
                last_plan_tasks = tasks
        elif kind == "stop_rejected":
            tags.add("FM_PREMATURE_STOP")
        elif kind == "task_rejected":
            tags.add("CAPABILITY_GAP" if payload.get("task_type") in unavailable_tasks else "FM_TASK_SPEC_VIOLATION")
        elif kind == "role_failure":
            tags.add("FM_PLANNER_FAILURE" if payload.get("role") == "planner" else "FM_WORKER_FAILURE")
        elif kind == "gate_reject":
            tags.add("FM_GATE_REJECTED")
        elif kind == "verdict":
            stop_reason = str(payload.get("stop_reason", ""))
    if stop_reason in ("BUDGET", "LOOP") and len(reports) >= 3 and all(r == reports[-1] for r in reports[-3:]):
        tags.add("FM_UNAWARE_TERMINATION")
    return frozenset(tags)

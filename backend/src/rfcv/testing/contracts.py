"""Bộ kiểm thử hợp đồng cho plugin: chạy lại trên mọi cài đặt mới của một điểm mở rộng.

Mỗi hàm trả danh sách vi phạm (chuỗi); rỗng nghĩa là cài đặt tuân thủ. Hàm không phụ thuộc pytest, nên dùng được trong
CI của plugin bên thứ ba: `assert not check_rule_set_contract(...)`. Bộ kiểm thử này ép đúng các bất biến an toàn mà
lõi dựa vào
(tất định, không kết luận khi chưa có bằng chứng, không dẫn bằng chứng không tồn tại).
"""

from __future__ import annotations

from collections.abc import Sequence

from rfcv.evidence.models import Evidence
from rfcv.evidence.verdict_engine import Label, RequirementView, RuleSet, StopReason, assess, decide
from rfcv.gates.code_gate import CodeIndex


def check_rule_set_contract(
    rule_set: RuleSet, cases: Sequence[tuple[RequirementView, Sequence[Evidence]]]
) -> list[str]:
    """Bộ quy tắc phải: có phiên bản ổn định; không kết luận khi chưa có bằng chứng; không phụ thuộc thứ tự bằng chứng;
    chỉ dẫn bằng chứng có thật; luôn có nhãn cuối (không quy tắc nào khớp thì UNVERIFIABLE)."""
    problems: list[str] = []
    if not rule_set.version.startswith("sha256:"):
        problems.append("version phải là hash nội dung")
    for req, evidence in cases:
        tag = f"[{req.requirement_id}/{req.rtype}]"
        empty = assess(req, [], rule_set)
        if empty.provisional is not None and empty.provisional.label in (Label.COMPLIANT, Label.VIOLATION):
            problems.append(f"{tag} kết luận {empty.provisional.label.value} khi chưa có bằng chứng nào")
        if decide(req, [], StopReason.BUDGET, rule_set).label is not Label.UNVERIFIABLE:
            problems.append(f"{tag} không có bằng chứng mà nhãn cuối không phải UNVERIFIABLE")
        a = assess(req, list(evidence), rule_set)
        b = assess(req, list(reversed(evidence)), rule_set)
        c = assess(req, list(evidence), rule_set)
        if (a.provisional, a.missing) != (c.provisional, c.missing):
            problems.append(f"{tag} không tất định: hai lần chạy cùng đầu vào cho kết quả khác nhau")
        if _signature(a) != _signature(b):
            problems.append(f"{tag} phụ thuộc thứ tự bằng chứng")
        known = {e.evidence_id for e in evidence}
        if a.provisional is not None and not set(a.provisional.evidence_ids) <= known:
            problems.append(f"{tag} dẫn bằng chứng không có trong đầu vào")
    return problems


def _signature(report: object) -> tuple[object, ...]:
    provisional = getattr(report, "provisional", None)
    if provisional is None:
        return (None, getattr(report, "missing", ()))
    return (provisional.label, provisional.rule, provisional.assurance)


def check_code_index_contract(index: CodeIndex, known_file: str) -> list[str]:
    """Chỉ mục mã phải: trả rỗng cho ký hiệu lạ; không trả quá số dòng được hỏi; ký hiệu nằm đúng tệp; nhất quán cạnh
    gọi."""
    problems: list[str] = []
    if known_file not in index.files():
        return [f"files() không chứa tệp mẫu {known_file}"]
    if list(index.lookup("__no_such_symbol__")):
        problems.append("lookup ký hiệu lạ phải rỗng")
    if index.symbol_in_file(known_file, "__no_such_symbol__") is not None:
        problems.append("symbol_in_file ký hiệu lạ phải là None")
    if len(index.lines(known_file, 1, 5)) > 5:
        problems.append("lines(1, 5) trả quá 5 dòng")
    if list(index.lines("__no_such_file__", 1, 5)):
        problems.append("lines của tệp lạ phải rỗng")
    for sym in index.outline(known_file):
        if sym.file != known_file:
            problems.append(f"outline trả ký hiệu {sym.name} thuộc tệp khác")
        if sym.line_start > sym.line_end:
            problems.append(f"ký hiệu {sym.name} có khoảng dòng ngược")
        for callee, _ in index.callees(sym.name):
            if not index.has_call_edge(sym.name, callee):
                problems.append(f"callees({sym.name}) có {callee} nhưng has_call_edge trả False")
    return problems

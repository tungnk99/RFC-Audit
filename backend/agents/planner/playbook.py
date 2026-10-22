"""Sổ tay điều tra của miền RFC giao thức, theo Bảng 10 của tài liệu thiết kế phối hợp agent (bản chuẩn).

Đây là dữ liệu, không phải mã: `core.advisor` đọc nó để gợi ý, `render_playbook` in nó thành lời nhắc, nên lời nhắc và hành
vi gợi ý không thể lệch nhau. Sổ tay là gợi ý, không bắt buộc: Planner được làm khác nhưng phải khai `DEVIATE_PLAYBOOK`.

Hai chỗ tài liệu thiết kế nêu mà chưa cài được, nên chưa có quy tắc: MAP_COMPONENTS ở vòng 1 (cần biết bản đồ thành phần
đã phủ chưa), và STATIC_QUERY cho loại D (chưa có handler). Advisor tự bỏ qua nhiệm vụ chưa có handler.
"""

from __future__ import annotations

from rfcv.domains.rfc_protocol.payloads import AspectName as A
from rfcv.domains.rfc_protocol.schemas import RationaleCode as R
from rfcv.domains.rfc_protocol.schemas import TaskType as T
from rfcv.spi import PlaybookRule, Suggest, When

ASPECTS: dict[str, list[str]] = {
    "A": [A.CONDITION.value, A.THRESHOLD.value],
    "B": [A.CONDITION.value, A.THRESHOLD.value, A.REACTION.value],
    "C": [A.ORDER_STATE.value, A.REACTION.value],
    "D": [A.EFFECT.value],
}
INITIAL = {"A": R.INITIAL_TYPE_A, "B": R.INITIAL_TYPE_B, "C": R.INITIAL_TYPE_C, "D": R.INITIAL_TYPE_D}


def _locate(rtype: str) -> Suggest:
    return Suggest(T.LOCATE.value, {"aspects": ASPECTS[rtype]})


def _rules() -> list[PlaybookRule]:
    rules: list[PlaybookRule] = []
    # Vòng 1: song song theo loại yêu cầu (Bảng 10).
    for rtype in ("A", "B", "C"):
        rules.append(
            PlaybookRule(
                f"R1-{rtype}",
                When(rtypes=frozenset({rtype}), first_round=True),
                (Suggest(T.SELECT_TESTS.value), _locate(rtype)),
                INITIAL[rtype].value,
                priority=10,
                note="Chạy kiểm thử và tìm mã song song vì hai việc độc lập.",
            )
        )
    rules.append(
        PlaybookRule(
            "R1-D",
            When(rtypes=frozenset({"D"}), first_round=True),
            (_locate("D"), Suggest(T.STATIC_QUERY.value)),
            R.INITIAL_TYPE_D.value,
            priority=10,
            note="Loại D không chạy kiểm thử: bằng chứng tĩnh.",
        )
    )
    # Nhãn tạm COMPLIANT là kết luận dễ sai nhất: luôn phản biện một lần trước khi dừng.
    rules.append(
        PlaybookRule(
            "R2-critique-before-compliant",
            When(provisional=frozenset({"COMPLIANT"}), critique="none"),
            (Suggest(T.CRITIQUE.value),),
            R.CRITIQUE_BEFORE_COMPLIANT.value,
            priority=20,
        )
    )
    # Mọi vấn đề phản biện đã được xử lý xong: phản biện lại thay vì giao lặp lại cùng nhiệm vụ.
    rules.append(
        PlaybookRule(
            "R2-recritique-after-fix",
            When(provisional=frozenset({"COMPLIANT"}), critique="stale"),
            (Suggest(T.CRITIQUE.value),),
            R.CRITIQUE_BEFORE_COMPLIANT.value,
            priority=21,
        )
    )
    rules.append(
        PlaybookRule(
            "R3-recritique-after-fix",
            When(conflict=True, critique="stale"),
            (Suggest(T.CRITIQUE.value),),
            R.RESOLVE_CONFLICT.value,
            priority=31,
        )
    )
    # Verdict engine báo mâu thuẫn: nhờ Verifier phân loại trước, rồi RECHECK theo khía cạnh (CONTRADICTION).
    rules.append(
        PlaybookRule(
            "R3-critique-on-conflict",
            When(conflict=True, critique="none"),
            (Suggest(T.CRITIQUE.value),),
            R.RESOLVE_CONFLICT.value,
            priority=30,
        )
    )
    # Verifier đã xem mà không phân loại được vấn đề, mâu thuẫn vẫn còn: xem lại đúng khía cạnh đang mâu thuẫn.
    rules.append(
        PlaybookRule(
            "R3-recheck-conflict",
            When(conflict=True, critique="clean"),
            (Suggest(T.RECHECK.value, bind={"aspect": "conflict.aspect"}),),
            R.RESOLVE_CONFLICT.value,
            priority=35,
        )
    )
    # Làm theo vấn đề Verifier nêu (Bảng 8).
    follow = (
        (
            "CONTRADICTION",
            Suggest(T.RECHECK.value, bind={"evidence_id": "critique.evidence_id", "aspect": "conflict.aspect"}),
        ),
        ("MISSING_PATH", Suggest(T.TRACE_PATHS.value)),
        ("WRONG_LOCATION", Suggest(T.LOCATE.value, {"start_hints": "locator"})),
        ("MISSING_VARIANT", Suggest(T.SELECT_TESTS.value, bind={"missing_variants": "missing.variants"})),
    )
    for i, (kind, suggestion) in enumerate(follow):
        rules.append(
            PlaybookRule(
                f"R4-follow-{kind.lower()}",
                When(critique="issues", critique_kind=kind),
                (suggestion,),
                R.FOLLOW_CRITIQUE.value,
                priority=40 + i,
            )
        )
    # Verifier thấy thiếu bằng chứng mã (Bảng 8, MISSING_EVIDENCE): tìm lại vị trí theo khía cạnh của loại yêu cầu.
    for i, rtype in enumerate(("A", "B", "C", "D")):
        rules.append(
            PlaybookRule(
                f"R4-follow-missing_evidence-{rtype}",
                When(rtypes=frozenset({rtype}), critique="issues", critique_kind="MISSING_EVIDENCE"),
                (_locate(rtype),),
                R.FOLLOW_CRITIQUE.value,
                priority=50 + i,
            )
        )
    # Lấp chỗ thiếu theo báo cáo độ đủ.
    rules.append(
        PlaybookRule(
            "R5-fill-t3",
            When(need="T3"),
            (Suggest(T.SELECT_TESTS.value, bind={"missing_variants": "missing.variants"}),),
            R.FILL_MISSING_VARIANT.value,
            priority=60,
        )
    )
    for rtype in ("A", "B", "C", "D"):
        rules.append(
            PlaybookRule(
                f"R6-fill-t1-{rtype}",
                When(need="T1", rtypes=frozenset({rtype})),
                (_locate(rtype),),
                R.FILL_MISSING_VARIANT.value,
                priority=70,
            )
        )
    rules.append(
        PlaybookRule(
            "R7-fill-t2",
            When(need="T2"),
            (Suggest(T.STATIC_QUERY.value),),
            R.FILL_MISSING_VARIANT.value,
            priority=80,
        )
    )
    return rules


PLAYBOOK: tuple[PlaybookRule, ...] = tuple(_rules())


BEGIN, END = "<!-- playbook:begin -->", "<!-- playbook:end -->"


def sync_prompt(text: str) -> str:
    """Thay khối giữa hai dấu mốc trong lời nhắc bằng sổ tay vừa in; lời nhắc và dữ liệu không thể lệch nhau."""
    from rfcv.core.advisor import render_playbook

    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    return head + BEGIN + chr(10) + render_playbook(PLAYBOOK) + chr(10) + END + tail

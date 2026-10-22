"""Output gate và bước giải thích (BL-30): Report chỉ giải thích nhãn đã có; trích bằng chứng bịa, nhắc nhãn khác, hay bỏ
một tầng bằng chứng đều bị chặn, và giải thích không bao giờ đổi nhãn."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from helpers import REQ, t1, t3
from rfcv.agents.schemas import Explanation
from rfcv.core.envelope import Envelope
from rfcv.core.policy import PolicyStore
from rfcv.core.runner import RoleOutcome
from rfcv.core.trace import TraceLog
from rfcv.domains.rfc_protocol.payloads import AspectValue, Outcome
from rfcv.domains.rfc_protocol.schemas import TaskType
from rfcv.evidence.models import Evidence
from rfcv.evidence.store import EvidenceStore
from rfcv.evidence.verdict_engine import Label, StopReason, VerdictRecord, decide
from rfcv.gates.output_gate import check_explanation
from rfcv.gates.tool_gateway import ToolSession
from test_execution_loop import LOCATE, OUTPUTS, SELECT, FakeRunner, WriteOnce, inv, make_loop, plan
from test_verdict_engine import REQ_B, chain

LONG = (
    "Kết luận VIOLATION vì SUT gửi sai mã lỗi khi bản ghi vượt ngưỡng; xem bằng chứng được trích bên dưới để tái lập."
)


def violation() -> tuple[VerdictRecord, list[Evidence]]:
    evidence = chain(
        [
            t3(outcome=Outcome.FAIL, alert="decode_error"),
            t1(reaction=AspectValue.MISMATCH, observed="send_alert(decode_error)"),
        ]
    )
    verdict = decide(REQ_B, evidence, StopReason.SUFFICIENT)
    assert verdict.label is Label.VIOLATION
    return verdict, evidence


def explanation(verdict: VerdictRecord, evidence: list[Evidence], **over: Any) -> Explanation:
    body: dict[str, Any] = {
        "requirement_id": verdict.requirement_id,
        "text": LONG,
        "cited_evidence_ids": [e.evidence_id for e in evidence],
    }
    return Explanation.model_validate(body | over)


def test_a_faithful_explanation_passes() -> None:
    verdict, evidence = violation()
    assert check_explanation(explanation(verdict, evidence), verdict, evidence) == []


def test_the_verdict_basis_alone_can_be_a_single_tier() -> None:
    """VIOLATION do kiểm thử chạy (V2) có căn cứ chỉ là T3; vị trí mã (T1) vẫn phải được nêu."""
    verdict, evidence = violation()
    assert {str(e.tier) for e in evidence if e.evidence_id in verdict.evidence_ids} == {"T3"}


def test_every_error_code_fires_on_its_own_defect() -> None:
    verdict, evidence = violation()
    fake = "sha256:" + "f" * 64
    all_ids = [e.evidence_id for e in evidence]

    def codes(**over: Any) -> list[str]:
        return [e.split(":")[0] for e in check_explanation(explanation(verdict, evidence, **over), verdict, evidence)]

    assert codes(requirement_id="OTHER-1") == ["WRONG_REQUIREMENT"]
    assert codes(text="ngắn quá") == ["TEXT_LENGTH"]
    assert codes(text=LONG + "x" * 3000) == ["TEXT_LENGTH"]
    assert codes(cited_evidence_ids=[*all_ids, fake]) == ["UNKNOWN_EVIDENCE"]
    assert codes(text=LONG + f" Xem {fake}.") == ["UNKNOWN_EVIDENCE"]  # id bịa nằm trong văn bản cũng bị chặn
    assert codes(cited_evidence_ids=[]) == ["NOT_VERDICT_EVIDENCE", "TIER_NOT_COVERED", "TIER_NOT_COVERED"]
    assert codes(text=LONG.replace("VIOLATION", "COMPLIANT")) == ["LABEL_MISMATCH"]


def test_each_tier_the_requirement_has_must_be_cited() -> None:
    """Giải thích chỉ trích kiểm thử mà bỏ vị trí mã (hay ngược lại) là giải thích một nửa."""
    verdict, evidence = violation()
    by_tier = {str(e.tier): e.evidence_id for e in evidence}
    for cited, missing in ((by_tier["T3"], "T1"), (by_tier["T1"], "T3")):
        errors = check_explanation(explanation(verdict, evidence, cited_evidence_ids=[cited]), verdict, evidence)
        assert errors[-1].startswith("TIER_NOT_COVERED") and missing in errors[-1], errors


def test_evidence_of_another_requirement_is_not_a_valid_citation() -> None:
    verdict, evidence = violation()
    other = chain([t3(requirement_id="OTHER-1", outcome=Outcome.FAIL)])[0]
    cited = [e.evidence_id for e in evidence] + [other.evidence_id]
    errors = check_explanation(explanation(verdict, evidence, cited_evidence_ids=cited), verdict, [*evidence, other])
    assert [e.split(":")[0] for e in errors] == ["UNKNOWN_EVIDENCE"]


def test_an_unverifiable_verdict_without_evidence_needs_no_citation() -> None:
    verdict = decide(REQ_B, [], StopReason.BUDGET)
    assert verdict.label is Label.UNVERIFIABLE and not verdict.evidence_ids
    ok = Explanation(
        requirement_id=verdict.requirement_id, text="UNVERIFIABLE vì hết ngân sách trước khi có bằng chứng nào."
    )
    assert check_explanation(ok, verdict, []) == []


# ---------------------------------------------------------------- bước giải thích trong vòng lặp


class ReportRunner(FakeRunner):
    """Report giả: trích mọi bằng chứng của yêu cầu có trong kho, với đoạn văn cho trước."""

    def __init__(self, store: EvidenceStore, text: str) -> None:
        super().__init__(lambda n: plan(SELECT, LOCATE), OUTPUTS)
        self.store, self.text = store, text

    async def run(self, envelope: Envelope, context: dict[str, Any], session: ToolSession) -> RoleOutcome:
        if envelope.to_role != "report":
            return await super().run(envelope, context, session)
        self.calls.append(envelope)
        self.contexts.append(context)
        cited = [e.evidence_id for e in self.store.for_requirement(REQ)]
        return RoleOutcome(Explanation(requirement_id=REQ, text=self.text, cited_evidence_ids=cited), 50)


async def investigated(store: EvidenceStore, trace: TraceLog, policy: PolicyStore, text: str = LONG):
    runner = ReportRunner(store, text)
    handlers = {
        TaskType.SELECT_TESTS: WriteOnce(store, lambda: [t3(outcome=Outcome.FAIL, alert="decode_error")]),
        TaskType.LOCATE: WriteOnce(
            store, lambda: [t1(reaction=AspectValue.MISMATCH, observed="send_alert(decode_error)")]
        ),
    }
    loop = make_loop(store, trace, policy, runner, handlers)
    investigation = inv()
    return loop, investigation, await loop.investigate(investigation), runner


def events(trace: TraceLog, kind: str) -> list[dict[str, Any]]:
    return [e["payload"] for e in trace.events() if e["kind"] == kind]


async def test_explain_publishes_a_gated_explanation_and_never_touches_the_label(
    store: EvidenceStore, trace: TraceLog, policy: PolicyStore
) -> None:
    loop, investigation, verdict, runner = await investigated(store, trace, policy)
    before = store.latest_verdicts()[REQ]
    result = await loop.explain(investigation, verdict)
    assert result is not None and result.text == LONG
    published = events(trace, "explanation")[-1]
    assert published["label"] == "VIOLATION" and len(published["cited_evidence_ids"]) == 2
    assert store.latest_verdicts()[REQ] == before  # nhãn do Verdict engine quyết định, giải thích không chạm tới
    seen = next(c for env, c in zip(runner.calls, runner.contexts, strict=True) if env.to_role == "report")
    assert seen["verdict.record"]["value"]["label"] == "VIOLATION"
    # Căn cứ của V2 chỉ là T3, nhưng Report vẫn được thấy vị trí mã (T1) để nêu.
    assert {r["tier"] for r in seen["evidence.cited"]["value"]} == {"T1", "T3"}


async def test_explain_drops_a_rejected_explanation_but_keeps_the_verdict(
    store: EvidenceStore, trace: TraceLog, policy: PolicyStore
) -> None:
    loop, investigation, verdict, _ = await investigated(
        store, trace, policy, text=LONG.replace("VIOLATION", "COMPLIANT")
    )
    assert await loop.explain(investigation, verdict) is None
    rejected = events(trace, "explanation_rejected")[-1]
    assert rejected["errors"] and rejected["errors"][0].startswith("LABEL_MISMATCH")
    assert verdict.label is Label.VIOLATION and store.latest_verdicts()[REQ]["label"] == "VIOLATION"


async def test_explain_does_nothing_when_the_domain_has_no_report_role(
    store: EvidenceStore, trace: TraceLog, policy: PolicyStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop, investigation, verdict, runner = await investigated(store, trace, policy)
    monkeypatch.setattr(loop, "_loop", dataclasses.replace(loop._loop, report_role=None))
    assert await loop.explain(investigation, verdict) is None
    assert all(env.to_role != "report" for env in runner.calls)

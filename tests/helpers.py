"""Hàm dựng bằng chứng cho kiểm thử."""

from __future__ import annotations

from rfcv.domains.rfc_protocol.payloads import (
    AspectCheck,
    AspectName,
    AspectValue,
    Finding,
    Outcome,
    Producer,
    T1Payload,
    T2StaticPayload,
    T2SuspiciousPayload,
    T3LinkPayload,
    T3Payload,
    Tier,
    Witness,
    WitnessRun,
)
from rfcv.evidence.models import Evidence, EvidenceDraft
from rfcv.evidence.store import seal

REQ = "TLS13-0042"
RUN = "run-test"


def as_evidence(draft: EvidenceDraft, prev: str = "sha256:" + "0" * 64) -> Evidence:
    evidence_id, record = seal(draft, prev)
    return Evidence.model_validate({**record, "evidence_id": evidence_id})


def t3(
    variant: str = "boundary:record.length=16641",
    outcome: Outcome = Outcome.PASS,
    *,
    variant_class: str = "required",
    trigger_reached: bool = True,
    consistent: bool = True,
    refs: tuple[Outcome, ...] = (Outcome.PASS,),
    alert: str = "record_overflow",
    origin: str = "scenario",
    seed: int | None = None,
    requirement_id: str = REQ,
    side: str = "trigger",
) -> EvidenceDraft:
    return EvidenceDraft(
        run_id=RUN,
        requirement_id=requirement_id,
        tier=Tier.T3,
        payload=T3Payload(
            scenario="sha256:scn",
            oracle="sha256:orc",
            variant=variant,
            variant_class=variant_class,  # type: ignore[arg-type]
            side=side,  # type: ignore[arg-type]
            seed=seed,
            trigger_reached=trigger_reached,
            outcome=outcome,
            observed={"alert": alert, "closed": True},
            consistent=consistent,
            origin=origin,  # type: ignore[arg-type]
            witness=Witness(positive=tuple(WitnessRun(impl=f"ref{i}", outcome=o) for i, o in enumerate(refs))),
        ),
        produced_by=Producer.TEST_DRIVER,
    )


def t1(
    *,
    finding: Finding = Finding.PRESENT,
    reaction: AspectValue = AspectValue.MATCH,
    observed: str = "send_alert(record_overflow)",
    requirement_id: str = REQ,
    lines: tuple[int, int] = (812, 816),
) -> EvidenceDraft:
    return EvidenceDraft(
        run_id=RUN,
        requirement_id=requirement_id,
        tier=Tier.T1,
        payload=T1Payload(
            file="src/internal.c",
            symbol="GetRecordHeader",
            line_start=lines[0],
            line_end=lines[1],
            finding=finding,
            aspects=(
                AspectCheck(aspect=AspectName.CONDITION, value=AspectValue.MATCH, observed=None, lines=(812, 812)),
                AspectCheck(aspect=AspectName.REACTION, value=reaction, observed=observed, lines=(815, 816)),
            ),
            call_path=("ProcessReply", "GetRecordHeader"),
        ),
        produced_by=Producer.SCHEMA_GATE,
    )


def t2(violating: int = 0, validated: bool = True, requirement_id: str = REQ) -> EvidenceDraft:
    return EvidenceDraft(
        run_id=RUN,
        requirement_id=requirement_id,
        tier=Tier.T2,
        payload=T2StaticPayload(query="sha256:q", validated=validated, paths_examined=2, violating_paths=violating),
        produced_by=Producer.CODE_GATE,
    )


def suspicious(on_path: bool = True) -> EvidenceDraft:
    return EvidenceDraft(
        run_id=RUN,
        requirement_id=REQ,
        tier=Tier.T2,
        payload=T2SuspiciousPayload(rule_id="cmp_test_constant", file="src/internal.c", line=900, on_path=on_path),
        produced_by=Producer.CODE_GATE,
    )


def link(t3_id: str, t1_id: str, linked: bool = True) -> EvidenceDraft:
    return EvidenceDraft(
        run_id=RUN,
        requirement_id=REQ,
        tier=Tier.T3,
        payload=T3LinkPayload(t3=t3_id, t1=t1_id, lines_hit=(812, 815) if linked else (), linked=linked),
        produced_by=Producer.COVERAGE_LINKER,
    )


def full_passing_set() -> list[EvidenceDraft]:
    """Đủ biến thể bắt buộc + đối chứng + 3 ngẫu nhiên, tất cả PASS (khớp oracle của TLS13-0042.rbs)."""
    return [
        t3("at_limit:record.length=16640", variant_class="control", alert="none", side="valid"),
        t3("boundary:record.length=16641"),
        t3("max:record.length=65535"),
        *[t3(f"random:record.length#{i}", variant_class="random", seed=7) for i in range(3)],
    ]


def chain(drafts: list[EvidenceDraft]) -> list[Evidence]:
    """Dựng chuỗi bằng chứng (prev_hash nối tiếp) từ bản nháp, đúng như Evidence store sẽ làm."""
    out: list[Evidence] = []
    prev = "sha256:" + "0" * 64
    for d in drafts:
        e = as_evidence(d, prev)
        out.append(e)
        prev = e.evidence_id
    return out

"""Bước phân tích đặc tả: RFC Analyst dịch lại câu RFC (mù với RBS viết tay), cổng tất định kiểm, đối chiếu với bản đã duyệt."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.rfc_analyst.handler import evaluate_proposal
from agents.rfc_analyst.schema import RbsProposal
from conftest import ADAPTER_DIR
from rfcv.adapters.manifest import load_manifest
from rfcv.assembly import build_runtime
from rfcv.core.envelope import Envelope
from rfcv.core.runner import RoleOutcome
from rfcv.domains.rfc_protocol.adapter_view import to_vocabulary
from rfcv.domains.rfc_protocol.rfc_gate import load_rfc_documents
from rfcv.domains.rfc_protocol.spec.rbs import parse_rbs
from rfcv.gates.tool_gateway import ToolSession
from test_assembly import ScriptedRunner, make_config, make_providers

RFC_DIR = Path(__file__).parent / "data" / "rfc"
APPROVED = (ADAPTER_DIR / "examples" / "TLS13-0042.rbs").read_text(encoding="utf-8")


def _world() -> tuple[Any, Any, Any]:
    manifest = load_manifest(ADAPTER_DIR)
    return parse_rbs(APPROVED), load_rfc_documents(manifest, RFC_DIR), to_vocabulary(manifest)


def test_a_proposal_equal_to_the_approved_rbs_is_accepted_and_agrees() -> None:
    approved, docs, vocab = _world()
    result = evaluate_proposal(
        RbsProposal(sentence_ids=[approved.sentence_id], rbs_text=APPROVED), approved, docs, vocab
    )
    assert result["accepted"] and all(c["ok"] for c in result["checks"])
    assert result["compare"]["agree"] and result["compare"]["semantic_agree"] and result["compare"]["diffs"] == []


def test_semantic_difference_is_reported_per_field_and_test_choices_are_separated() -> None:
    approved, docs, vocab = _world()
    other = APPROVED.replace("record.length > 16640", "record.length > 16384").replace(
        "boundary(record.length, 16641), ", "boundary(record.length, 16385), "
    )
    result = evaluate_proposal(RbsProposal(sentence_ids=[approved.sentence_id], rbs_text=other), approved, docs, vocab)
    cmp = result["compare"]
    assert not cmp["agree"] and not cmp["semantic_agree"]
    assert "where" in cmp["semantic_diffs"] and "variants" in cmp["diffs"] and "variants" not in cmp["semantic_diffs"]


def test_the_gate_rejects_bad_syntax_unknown_vocabulary_and_unknown_sentences() -> None:
    approved, docs, vocab = _world()
    broken = evaluate_proposal(
        RbsProposal(sentence_ids=[approved.sentence_id], rbs_text="không phải RBS"), approved, docs, vocab
    )
    assert not broken["accepted"] and not next(c for c in broken["checks"] if c["name"] == "parse")["ok"]
    foreign = APPROVED.replace("send_alert(record_overflow)", "send_alert(khong_co_trong_tu_vung)")
    bad_vocab = evaluate_proposal(
        RbsProposal(sentence_ids=[approved.sentence_id], rbs_text=foreign), approved, docs, vocab
    )
    assert not bad_vocab["accepted"] and not next(c for c in bad_vocab["checks"] if c["name"] == "oracle")["ok"]
    ghost = evaluate_proposal(RbsProposal(sentence_ids=["RFC8446§99#p1s1"], rbs_text=APPROVED), approved, docs, vocab)
    assert not ghost["accepted"] and not next(c for c in ghost["checks"] if c["name"] == "sentence_ids")["ok"]


def test_no_output_and_non_behavioral_are_reported_not_hidden() -> None:
    approved, docs, vocab = _world()
    assert not evaluate_proposal(None, approved, docs, vocab)["produced"]
    nb = evaluate_proposal(
        RbsProposal(
            sentence_ids=[approved.sentence_id], rbs_text="", non_behavioral=True, non_behavioral_reason="định nghĩa"
        ),
        approved,
        docs,
        vocab,
    )
    assert not nb["accepted"] and nb["compare"]["diffs"] == ["non_behavioral"]


class AnalystRunner(ScriptedRunner):
    """Như ScriptedRunner, thêm RFC Analyst trả đúng bản người viết; ghi lại nó nhìn thấy những trường ngữ cảnh nào."""

    def __init__(self) -> None:
        super().__init__()
        self.analyst_context: dict[str, Any] = {}
        self.analyst_stream: str | None = None

    async def run(self, envelope: Envelope, context: dict[str, Any], session: ToolSession) -> RoleOutcome:
        if envelope.to_role == "rfc_analyst":
            self.calls.append("rfc_analyst")
            self.analyst_context = context
            self.analyst_stream = session.model_key
            return RoleOutcome(RbsProposal(sentence_ids=["RFC8446§5.2#p4s3"], rbs_text=APPROVED), 7)
        return await super().run(envelope, context, session)


async def test_pre_stage_runs_blind_traces_the_comparison_and_leaves_the_verdict_alone(tmp_path: Path) -> None:
    runner = AnalystRunner()
    cfg = make_config(tmp_path, scripted_plans=False, rfc_dir=RFC_DIR, spec_analysis=True)
    rt = build_runtime(cfg, make_providers(runner))
    runner.gateway = rt.gateway
    try:
        (verdict,) = await rt.run_all(ADAPTER_DIR / "examples")
        start = list(rt.trace.events("rfc_analysis_start"))
        proposal = list(rt.trace.events("rfc_proposal"))
    finally:
        rt.close()
    assert runner.calls[0] == "rfc_analyst"  # chạy TRƯỚC vòng điều tra
    assert verdict.label.value == "VIOLATION"  # kết luận không phụ thuộc bước này
    assert set(runner.analyst_context) == {"rfc.sentence_group", "rfc.context_pack", "adapter.vocabulary"}
    assert (
        "requirement.rbs" not in runner.analyst_context and "requirement.structured" not in runner.analyst_context
    )  # mù
    assert runner.analyst_stream == "rfc_analyst.a"
    assert len(start) == 1 and start[0]["payload"]["blind"] is True and start[0]["requirement_id"] == "TLS13-0042"
    (p,) = [e["payload"] for e in proposal]
    assert p["accepted"] and p["compare"]["agree"] and p["target_sentence_id"] == "RFC8446§5.2#p4s3"


async def test_pre_stage_is_off_by_default(tmp_path: Path) -> None:
    runner = AnalystRunner()
    rt = build_runtime(make_config(tmp_path, scripted_plans=False, rfc_dir=RFC_DIR), make_providers(runner))
    runner.gateway = rt.gateway
    try:
        await rt.run_all(ADAPTER_DIR / "examples")
    finally:
        rt.close()
    assert "rfc_analyst" not in runner.calls


async def test_missing_rfc_text_skips_with_a_reason_instead_of_failing(tmp_path: Path) -> None:
    runner = AnalystRunner()
    rt = build_runtime(make_config(tmp_path, scripted_plans=False, spec_analysis=True), make_providers(runner))
    runner.gateway = rt.gateway
    try:
        (verdict,) = await rt.run_all(ADAPTER_DIR / "examples")
        skipped = list(rt.trace.events("rfc_analysis_skipped"))
    finally:
        rt.close()
    assert verdict.label.value == "VIOLATION" and "rfc_analyst" not in runner.calls
    assert skipped and skipped[0]["payload"]["reason"] == "NO_RFC_TEXT"


def test_run_spec_carries_the_spec_analysis_flag_and_defaults_to_off() -> None:
    from rfcv.api.runs import RunSpec

    assert RunSpec.from_json({"adapter": "tls13"}).spec_analysis is False
    assert RunSpec.from_json({"adapter": "tls13", "spec_analysis": True}).spec_analysis is True

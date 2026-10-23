"""Kịch bản dựng từ mẫu adapter và chẩn đoán từ hành vi T3 (hàm thuần, không LLM)."""

from __future__ import annotations

from pathlib import Path

from helpers import t3
from rfcv.domains.rfc_protocol.diagnosis import NO_CLOSE, NONE, REACTION_ABSENT, THRESHOLD_OFF, WRONG_ALERT, diagnose
from rfcv.domains.rfc_protocol.payloads import Outcome, T3Payload
from rfcv.domains.rfc_protocol.scenario_synth import synthesize
from rfcv.domains.rfc_protocol.spec.rbs import parse_rbs

ADAPTER = Path(__file__).resolve().parent.parent / "adapters" / "tls13"
RBS_TEXT = (ADAPTER / "examples" / "TLS13-0042.rbs").read_text(encoding="utf-8")


def test_synthesis_builds_the_known_scenario_from_the_matching_template() -> None:
    scenario = synthesize(parse_rbs(RBS_TEXT), ADAPTER / "templates")
    assert scenario is not None and scenario.example_id == "tls13.record.length_overflow"
    ops = [s.op for s in scenario.steps]
    assert ops == ["connect", "complete_handshake", "send_raw_record", "expect"]
    assert scenario.steps[-1].args["until"] == "send_alert(record_overflow)"
    assert scenario.steps[-1].args["within_ms"] == 2000
    assert scenario.bindings == {"record.length": "from_variant"}


def test_synthesis_takes_the_reaction_and_deadline_from_the_rbs() -> None:
    text = RBS_TEXT.replace("send_alert(record_overflow)", "send_alert(decode_error)")
    text = text.replace("within 2000ms", "within 500ms")
    scenario = synthesize(parse_rbs(text), ADAPTER / "templates")
    assert scenario is not None
    assert scenario.steps[-1].args["until"] == "send_alert(decode_error)"
    assert scenario.steps[-1].args["within_ms"] == 500


def test_synthesis_defers_to_the_tester_when_nothing_matches(tmp_path: Path) -> None:
    other = RBS_TEXT.replace("trigger receive(record)", "trigger receive(handshake_msg)")
    assert synthesize(parse_rbs(other), ADAPTER / "templates") is None
    assert synthesize(parse_rbs(RBS_TEXT), tmp_path) is None  # thư mục không có mẫu
    assert synthesize(parse_rbs(RBS_TEXT), None) is None


def _case(
    variant: str, outcome: Outcome, alert: str, *, valid: bool = False, refs: tuple[Outcome, ...] = (Outcome.PASS,)
) -> T3Payload:
    draft = t3(
        variant,
        outcome,
        variant_class="valid_random" if valid else "random",
        alert=alert,
        side="valid" if valid else "trigger",
        refs=refs,
    )
    assert isinstance(draft.payload, T3Payload)
    return draft.payload


def test_reaction_absent_when_no_alert_at_every_length_beyond_the_threshold() -> None:
    cases = [_case(f"random#{i}", Outcome.FAIL, "none") for i in range(4)]
    d = diagnose("record_overflow", cases)
    assert d.signature == REACTION_ABSENT and d.failing_cases == 4 and d.observed_alerts == ("none",)
    assert "record_overflow" in d.next_step and "defined" in d.next_step


def test_threshold_off_when_some_lengths_do_react() -> None:
    cases = [_case("random#0", Outcome.FAIL, "none"), _case("random#1", Outcome.PASS, "record_overflow")]
    assert diagnose("record_overflow", cases).signature == THRESHOLD_OFF


def test_wrong_alert_and_no_close_and_clean() -> None:
    assert diagnose("record_overflow", [_case("random#0", Outcome.FAIL, "decode_error")]).signature == WRONG_ALERT
    assert diagnose("record_overflow", [_case("random#0", Outcome.FAIL, "record_overflow")]).signature == NO_CLOSE
    assert diagnose("record_overflow", [_case("random#0", Outcome.PASS, "record_overflow")]).signature == NONE


def test_waived_valid_side_and_untrusted_cases_do_not_drive_the_diagnosis() -> None:
    waived = _case("valid#0", Outcome.FAIL, "record_overflow", valid=True, refs=(Outcome.FAIL, Outcome.FAIL))
    unreliable = _case("random#9", Outcome.FAIL, "none", refs=())  # không có nhân chứng dương
    assert diagnose("record_overflow", [waived, unreliable]).signature == NONE

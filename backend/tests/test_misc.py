"""Registry, Adapter checker, CLI, SARIF, thống kê, backend tlsfuzzer (validate)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import ADAPTER_DIR
from rfcv.adapters.checker import Status, check_adapter, passed
from rfcv.backends.tlsfuzzer import TlsfuzzerBackend
from rfcv.domains.rfc_protocol.schemas import ScenarioProposal
from rfcv.eval.metrics import cohen_kappa, mcnemar_exact, wilson_interval
from rfcv.evidence.registry import RequirementRegistry, State, TransitionError
from rfcv.ui.cli import app
from rfcv.ui.sarif import SarifFinding, build_sarif


def test_registry_only_verdict_engine_decides(tmp_path: Path) -> None:
    reg = RequirementRegistry(tmp_path / "registry.db")
    reg.add("TLS13-0042", {"rbs": "..."}, actor="rfc_gate")
    reg.transition("TLS13-0042", State.SPECIFIED, "oracle_compiler")
    reg.transition("TLS13-0042", State.INVESTIGATING, "execution_loop")
    with pytest.raises(TransitionError, match="Verdict engine"):
        reg.transition("TLS13-0042", State.DECIDED, "planner")
    reg.transition("TLS13-0042", State.DECIDED, "verdict_engine")
    assert reg.state("TLS13-0042") is State.DECIDED
    with pytest.raises(TransitionError):
        reg.transition("TLS13-0042", State.SPECIFIED, "auditor")


def test_real_adapter_passes_form_checks() -> None:
    items = check_adapter(ADAPTER_DIR)
    assert passed(items)
    assert {i.check for i in items if i.status is Status.SKIPPED} == {
        "build.sut",
        "oracle.stable",
        "oracle.discriminating",
        "coverage.expressiveness",
    }


def test_broken_adapter_fails(tmp_path: Path) -> None:
    (tmp_path / "adapter.yaml").write_text("adapter: x\n", encoding="utf-8")
    assert not passed(check_adapter(tmp_path))


def test_cli_commands(tmp_path: Path) -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["adapter", "check", str(ADAPTER_DIR)]).exit_code == 0
    r = runner.invoke(
        app, ["rbs", "check", str(ADAPTER_DIR / "examples" / "TLS13-0042.rbs"), "--adapter", str(ADAPTER_DIR)]
    )
    assert r.exit_code == 0 and "at_limit:record.length=16640" in r.output
    assert runner.invoke(app, ["verify", str(tmp_path)]).exit_code == 0
    plugins = runner.invoke(app, ["plugins"])
    assert plugins.exit_code == 0 and "rfc_protocol" in plugins.output and "scenario_result" in plugins.output
    # chưa có chỉ mục mã, bộ chạy lệnh và bộ chạy SUT thật: `run` phải nói rõ thiếu gì, không chạy dở
    run = runner.invoke(
        app,
        [
            "run",
            "--adapter",
            str(ADAPTER_DIR),
            "--run-dir",
            str(tmp_path / "runs"),
            "--skills",
            str(ADAPTER_DIR.parent.parent / "skills"),
        ],
    )
    assert run.exit_code == 2 and "code_index" in run.output and "sut_launcher" in run.output


def test_sarif_only_violations() -> None:
    f = SarifFinding(
        "RFC8446§5.2#p4s3",
        "TLS13-0042",
        "VIOLATION",
        "V2",
        "decode_error thay vì record_overflow",
        "src/internal.c",
        812,
        816,
        ("sha256:a",),
    )
    ok = SarifFinding(**{**f.__dict__, "label": "COMPLIANT", "requirement_id": "X"})
    sarif = build_sarif([f, ok], {"RFC8446§5.2#p4s3": "An endpoint that receives a record..."})
    results = sarif["runs"][0]["results"]
    assert sarif["version"] == "2.1.0" and len(results) == 1
    assert results[0]["locations"][0]["physicalLocation"]["region"] == {"startLine": 812, "endLine": 816}


def test_statistics() -> None:
    lo, hi = wilson_interval(19, 20)
    assert round(lo, 4) == 0.7639 and round(hi, 4) == 0.9911  # giá trị tham chiếu Wilson cho 19/20
    assert wilson_interval(0, 0) == (0.0, 1.0)
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(0, 10) < 0.01
    assert cohen_kappa(["V", "C", "V"], ["V", "C", "V"]) == 1.0


def test_tlsfuzzer_validate() -> None:
    backend = TlsfuzzerBackend()
    good = ScenarioProposal.model_validate(
        {
            "requirement_id": "TLS13-0042",
            "reach_state": "connected",
            "steps": [
                {"op": "complete_handshake"},
                {"op": "send_raw_record", "args": {"length": "$record.length", "body": "zeros"}},
                {"op": "expect", "args": {"within_ms": 2000}},
            ],
            "bindings": {"record.length": "from_variant"},
        }
    )
    assert backend.validate(good).ok
    bad = good.model_copy(update={"bindings": {}})
    assert not backend.validate(bad).ok

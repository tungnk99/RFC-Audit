"""Test driver với backend giả (nhân chứng, chạy lại, ERROR) và Coverage linker (M3, M4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fakes import LCOV, SCENARIO, FakeBackend, FakeLauncher
from helpers import REQ, t1
from rfcv.core.trace import TraceLog
from rfcv.domains.rfc_protocol.coverage_linker import link, link_pending, parse_lcov
from rfcv.domains.rfc_protocol.payloads import Outcome, T1Payload, T3Payload
from rfcv.domains.rfc_protocol.rules import Assurance, ProtocolRequirement
from rfcv.domains.rfc_protocol.sandbox.driver import ScenarioRejected, TestDriver
from rfcv.domains.rfc_protocol.spec.oracle_compiler import CompiledOracle
from rfcv.evidence.artifacts import ArtifactStore
from rfcv.evidence.store import EvidenceStore
from rfcv.evidence.verdict_engine import Label, StopReason, decide


def driver(store: EvidenceStore, trace: TraceLog, tmp_path: Path, backend: FakeBackend) -> TestDriver:
    return TestDriver(
        backend,
        FakeLauncher(),
        store,
        ArtifactStore(tmp_path / "artifacts"),
        trace,
        sut_impl="sut",
        references=["rustls", "openssl"],
        mutants=["mutant-1"],
    )


def view(oracle: CompiledOracle) -> ProtocolRequirement:
    return ProtocolRequirement(REQ, oracle.rtype, "MUST", oracle.required_variant_names, oracle.random_k, oracle.valid_random_k)


async def test_buggy_sut_gives_violation_with_witness(
    store: EvidenceStore, trace: TraceLog, tmp_path: Path, oracle: CompiledOracle
) -> None:
    evs = await driver(store, trace, tmp_path, FakeBackend()).run_requirement(
        run_id="run-test", oracle=oracle, scenario=SCENARIO, seed=7
    )
    payloads = [e.payload for e in evs]
    assert all(isinstance(p, T3Payload) for p in payloads)
    by_variant = {p.variant: p for p in payloads if isinstance(p, T3Payload)}
    assert len(by_variant) == 3 + oracle.random_k + oracle.valid_random_k  # đối chứng + biên + max + mẫu hai phía
    control = by_variant["at_limit:record.length=16640"]
    assert control.outcome is Outcome.PASS
    boundary = by_variant["boundary:record.length=16641"]
    assert boundary.outcome is Outcome.FAIL and boundary.runs == 3 and boundary.consistent
    assert boundary.witness.has_positive
    assert boundary.observed["alert"] == "decode_error"
    # nhật ký thô chỉ vào Artifact store, không vào bản ghi bằng chứng
    assert "IGNORE PREVIOUS" not in boundary.model_dump_json()
    assert "sut_log" in boundary.artifacts
    verdict = decide(view(oracle), store.for_requirement(REQ), StopReason.SUFFICIENT)
    assert (verdict.label, verdict.rule) == (Label.VIOLATION, "V2")


async def test_fixed_sut_and_coverage_link_gives_linked_compliant(
    store: EvidenceStore, trace: TraceLog, tmp_path: Path, oracle: CompiledOracle
) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    d = TestDriver(
        FakeBackend(sut_alert="record_overflow"),
        FakeLauncher(),
        store,
        artifacts,
        trace,
        sut_impl="sut",
        references=["rustls"],
    )
    await d.run_requirement(run_id="run-test", oracle=oracle, scenario=SCENARIO, seed=7)
    assert decide(view(oracle), store.for_requirement(REQ), StopReason.SUFFICIENT).rule == "V6"
    store.append(t1(lines=(812, 816)))
    assert link_pending(store, artifacts, "run-test", REQ) > 0
    assert link_pending(store, artifacts, "run-test", REQ) == 0  # không ghi trùng
    v = decide(view(oracle), store.for_requirement(REQ), StopReason.SUFFICIENT)
    assert (v.label, v.rule, v.assurance) == (Label.COMPLIANT, "V5", Assurance.LINKED)


async def test_sanity_failure_is_error_not_fail(
    store: EvidenceStore, trace: TraceLog, tmp_path: Path, oracle: CompiledOracle
) -> None:
    evs = await driver(store, trace, tmp_path, FakeBackend(sanity_ok=False)).run_requirement(
        run_id="run-test", oracle=oracle, scenario=SCENARIO, seed=1
    )
    assert all(isinstance(e.payload, T3Payload) and e.payload.outcome is Outcome.ERROR for e in evs)
    assert decide(view(oracle), store.for_requirement(REQ), StopReason.BUDGET).label is Label.UNVERIFIABLE


async def test_trigger_not_reached_is_error(
    store: EvidenceStore, trace: TraceLog, tmp_path: Path, oracle: CompiledOracle
) -> None:
    evs = await driver(store, trace, tmp_path, FakeBackend(reach=False)).run_requirement(
        run_id="run-test", oracle=oracle, scenario=SCENARIO, seed=1
    )
    p = evs[1].payload
    assert isinstance(p, T3Payload) and p.outcome is Outcome.ERROR and p.observed["reason"] == "trigger_not_reached"


async def test_invalid_scenario_rejected(
    store: EvidenceStore, trace: TraceLog, tmp_path: Path, oracle: CompiledOracle
) -> None:
    bad = SCENARIO.model_copy(update={"steps": SCENARIO.steps[:1]})
    with pytest.raises(ScenarioRejected):
        await driver(store, trace, tmp_path, FakeBackend()).run_requirement(
            run_id="run-test", oracle=oracle, scenario=bad, seed=1
        )


def test_lcov_parse_and_link_by_suffix() -> None:
    cov = parse_lcov(LCOV)
    assert cov.executed("src/internal.c") == {812, 813, 815, 816}
    assert 900 in cov.compiled("src/internal.c")
    payload = t1().payload
    assert isinstance(payload, T1Payload)
    assert link("sha256:t1", payload, cov).linked
    not_hit = parse_lcov(LCOV.replace("DA:815,5", "DA:815,0").replace("DA:816,5", "DA:816,0"))
    assert not link("sha256:t1", payload, not_hit).linked


def test_artifact_store_detects_tampering(tmp_path: Path) -> None:
    a = ArtifactStore(tmp_path)
    digest = a.put(b"pcap bytes")
    assert a.get(digest) == b"pcap bytes"
    path = tmp_path / digest.removeprefix("sha256:")[:2] / digest.removeprefix("sha256:")
    path.write_bytes(b"forged")
    with pytest.raises(ValueError, match="sửa đổi"):
        a.get(digest)

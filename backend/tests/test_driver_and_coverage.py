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
from rfcv.domains.rfc_protocol.sandbox.backend import EventTrace
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
    return ProtocolRequirement(
        REQ, oracle.rtype, "MUST", oracle.required_variant_names, oracle.random_k, oracle.valid_random_k
    )


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


class BrokenLauncher:
    """SUT không khởi động được (container sập, hết tài nguyên…)."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def start(self, impl: str, *, coverage: bool, environment: int):
        raise self.error


def broken_driver(store: EvidenceStore, trace: TraceLog, tmp_path: Path, error: Exception) -> TestDriver:
    return TestDriver(
        FakeBackend(),
        BrokenLauncher(error),
        store,
        ArtifactStore(tmp_path / "artifacts"),
        trace,
        sut_impl="sut",
        references=["rustls"],
    )


async def test_sut_start_failure_is_a_traced_error_not_a_crash_and_not_a_fail(
    store: EvidenceStore, trace: TraceLog, tmp_path: Path, oracle: CompiledOracle
) -> None:
    d = broken_driver(store, trace, tmp_path, RuntimeError("docker: cannot start container"))
    evs = await d.run_requirement(run_id="run-test", oracle=oracle, scenario=SCENARIO, seed=1)
    assert evs and all(isinstance(e.payload, T3Payload) and e.payload.outcome is Outcome.ERROR for e in evs)
    cases = [e["payload"] for e in trace.events("t3_case")]
    assert cases and all(c["outcome"] == "ERROR" and c["reason"] == "environment_error" for c in cases)
    assert "cannot start container" in cases[0]["detail"] and cases[0]["role"] == "sut"
    assert {c["role"] for c in cases} == {"sut", "reference"}


async def test_an_unimplemented_backend_is_not_hidden_as_an_environment_error(
    store: EvidenceStore, trace: TraceLog, tmp_path: Path, oracle: CompiledOracle
) -> None:
    d = broken_driver(store, trace, tmp_path, NotImplementedError("backend chưa cài"))
    with pytest.raises(NotImplementedError):
        await d.run_requirement(run_id="run-test", oracle=oracle, scenario=SCENARIO, seed=1)


async def test_every_case_leaves_a_t3_case_event(
    store: EvidenceStore, trace: TraceLog, tmp_path: Path, oracle: CompiledOracle
) -> None:
    await driver(store, trace, tmp_path, FakeBackend()).run_requirement(
        run_id="run-test", oracle=oracle, scenario=SCENARIO, seed=7
    )
    roles = {e["payload"]["role"] for e in trace.events("t3_case")}
    assert roles == {"sut", "rerun", "reference", "mutant"}  # ca FAIL được chạy lại; có cả tham chiếu và đột biến
    assert all(e["requirement_id"] == REQ for e in trace.events("t3_case"))


async def test_trigger_not_reached_is_error(
    store: EvidenceStore, trace: TraceLog, tmp_path: Path, oracle: CompiledOracle
) -> None:
    evs = await driver(store, trace, tmp_path, FakeBackend(reach=False)).run_requirement(
        run_id="run-test", oracle=oracle, scenario=SCENARIO, seed=1
    )
    p = evs[1].payload
    assert isinstance(p, T3Payload) and p.outcome is Outcome.ERROR and p.observed["reason"] == "trigger_not_reached"


class CrashingBackend(FakeBackend):
    """SUT sập ngay khi nhận bản ghi quá dài; các bản tham chiếu vẫn trả cảnh báo đúng (BL-46)."""

    async def run(self, scenario, params, endpoint, seed):  # type: ignore[no-untyped-def]
        trace = await super().run(scenario, params, endpoint, seed)
        if endpoint.impl == "sut" and int(params["record.length"]) > 16640:
            return EventTrace(events=(), trigger_reached=True, sut_alive_after=False, observation={"closed": True})
        return trace


async def test_a_sut_that_crashes_after_the_trigger_is_a_flagged_fail(
    store: EvidenceStore, trace: TraceLog, tmp_path: Path, oracle: CompiledOracle
) -> None:
    """YD-27: SUT sập sau khi nhận dữ liệu kích hoạt là FAIL (không phải ERROR) và mang cờ `sut_crashed`, vì có thể là
    lỗi bảo mật; ca đối chứng hợp lệ vẫn PASS."""
    evs = await driver(store, trace, tmp_path, CrashingBackend()).run_requirement(
        run_id="run-test", oracle=oracle, scenario=SCENARIO, seed=7
    )
    by_variant = {e.payload.variant: e.payload for e in evs if isinstance(e.payload, T3Payload)}
    boundary = by_variant["boundary:record.length=16641"]
    assert boundary.outcome is Outcome.FAIL and boundary.trigger_reached
    assert boundary.observed["reason"] == "sut_crashed"  # cờ nằm trong bản ghi bằng chứng
    assert boundary.runs == 3 and boundary.consistent  # chạy lại ở môi trường khác vẫn sập: không phải nhiễu
    assert by_variant["at_limit:record.length=16640"].outcome is Outcome.PASS
    sut_cases = [e["payload"] for e in trace.events("t3_case") if e["payload"]["role"] in ("sut", "rerun")]
    crashed = [c for c in sut_cases if c["reason"] == "sut_crashed"]
    assert crashed and all(c["outcome"] == "FAIL" and c["sut_alive_after"] is False for c in crashed)
    # Các bản tham chiếu không sập nên làm chứng dương: ca sập không bị coi là lỗi của bộ kiểm thử.
    assert boundary.witness.has_positive
    verdict = decide(view(oracle), store.for_requirement(REQ), StopReason.SUFFICIENT)
    assert verdict.label is Label.VIOLATION


async def test_a_sut_that_stays_alive_has_no_crash_flag(
    store: EvidenceStore, trace: TraceLog, tmp_path: Path, oracle: CompiledOracle
) -> None:
    evs = await driver(store, trace, tmp_path, FakeBackend()).run_requirement(
        run_id="run-test", oracle=oracle, scenario=SCENARIO, seed=7
    )
    assert all(e.payload.observed.get("reason") != "sut_crashed" for e in evs if isinstance(e.payload, T3Payload))


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


async def test_a_transient_environment_error_is_retried_once(
    store: EvidenceStore, trace: TraceLog, tmp_path: Path, oracle: CompiledOracle, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Máy ngủ làm `docker run` quá hạn một lần: ca được thử lại, không để lại ERROR (đo trên lần chạy thật)."""
    from rfcv.domains.rfc_protocol.sandbox import driver as drv

    monkeypatch.setattr(drv, "ENVIRONMENT_RETRY_DELAY_S", 0.0)

    class Flaky(BrokenLauncher):
        calls = 0

        def start(self, impl, *, coverage, environment):  # type: ignore[no-untyped-def]
            Flaky.calls += 1
            if Flaky.calls == 1:
                return super().start(impl, coverage=coverage, environment=environment)
            return FakeLauncher().start(impl, coverage=coverage, environment=environment)

    d = TestDriver(
        FakeBackend(),
        Flaky(RuntimeError("docker: timeout")),
        store,
        ArtifactStore(tmp_path / "artifacts"),
        trace,
        sut_impl="sut",
        references=["rustls"],
    )
    evs = await d.run_requirement(run_id="run-test", oracle=oracle, scenario=SCENARIO, seed=1)
    cases = [e["payload"] for e in trace.events("t3_case")]
    assert evs and cases and not any(c["reason"] == "environment_error" for c in cases[:1])


class IdentifiedLauncher(FakeLauncher):
    """Bộ chạy giả biết định danh ảnh (như DockerSutLauncher) để bật bộ nhớ đệm nhân chứng."""

    def __init__(self, image_of: dict[str, str]) -> None:
        super().__init__()
        self._image_of = image_of

    async def identity(self, impl: str) -> str | None:
        return self._image_of.get(impl)


def cached_driver(
    store: EvidenceStore, trace: TraceLog, tmp_path: Path, cache: object, launcher: IdentifiedLauncher, **kw: object
) -> TestDriver:
    return TestDriver(
        FakeBackend(),
        launcher,
        store,
        ArtifactStore(tmp_path / "artifacts"),
        trace,
        sut_impl="sut",
        references=["rustls", "openssl"],
        witness_cache=cache,  # type: ignore[arg-type]
        **kw,  # type: ignore[arg-type]
    )


async def test_reference_results_are_computed_once_and_reused_across_runs(
    store: EvidenceStore, trace: TraceLog, tmp_path: Path, oracle: CompiledOracle
) -> None:
    from rfcv.domains.rfc_protocol.sandbox.witness_cache import WitnessCache

    cache = WitnessCache(tmp_path / "cache" / "witness.sqlite")
    images = {"rustls": "sha256:aaa", "openssl": "sha256:bbb"}
    first_launcher = IdentifiedLauncher(images)
    d1 = cached_driver(store, trace, tmp_path, cache, first_launcher)
    first = await d1.run_requirement(run_id="run-1", oracle=oracle, scenario=SCENARIO, seed=7)
    ref_starts = [s for s in first_launcher.started if s[0] in images]
    assert ref_starts and d1.cache_hits == 0

    second_launcher = IdentifiedLauncher(images)
    d2 = cached_driver(store, trace, tmp_path, cache, second_launcher)
    second = await d2.run_requirement(run_id="run-2", oracle=oracle, scenario=SCENARIO, seed=7)
    assert not [s for s in second_launcher.started if s[0] in images]  # tham chiếu không chạy lại
    assert d2.cache_hits == len(ref_starts)
    witnesses = lambda evs: [  # noqa: E731
        tuple((w.impl, w.outcome) for w in e.payload.witness.positive)
        for e in evs  # type: ignore[union-attr]
    ]
    assert witnesses(first) == witnesses(second)  # bằng chứng giữ nguyên nhân chứng như khi chạy thật
    hits = [e["payload"] for e in trace.events("t3_case") if e["payload"].get("cache_hit")]
    assert hits and all(h["origin_run"] == "run-1" for h in hits)


async def test_a_changed_reference_image_invalidates_the_cache(
    store: EvidenceStore, trace: TraceLog, tmp_path: Path, oracle: CompiledOracle
) -> None:
    from rfcv.domains.rfc_protocol.sandbox.witness_cache import WitnessCache

    cache = WitnessCache(tmp_path / "cache" / "witness.sqlite")
    await cached_driver(
        store, trace, tmp_path, cache, IdentifiedLauncher({"rustls": "a", "openssl": "b"})
    ).run_requirement(run_id="run-1", oracle=oracle, scenario=SCENARIO, seed=7)
    new_launcher = IdentifiedLauncher({"rustls": "a2", "openssl": "b2"})
    d = cached_driver(store, trace, tmp_path, cache, new_launcher)
    await d.run_requirement(run_id="run-2", oracle=oracle, scenario=SCENARIO, seed=7)
    assert d.cache_hits == 0 and any(s[0] == "rustls" for s in new_launcher.started)


async def test_concurrent_variants_are_recorded_in_a_fixed_order(
    store: EvidenceStore, trace: TraceLog, tmp_path: Path, oracle: CompiledOracle
) -> None:
    """Chạy đồng thời không được đổi thứ tự bằng chứng (chuỗi băm phải ổn định)."""
    serial = await cached_driver(store, trace, tmp_path, None, IdentifiedLauncher({}), concurrency=1).run_requirement(
        run_id="run-1", oracle=oracle, scenario=SCENARIO, seed=7
    )
    names = [e.payload.variant for e in serial]  # type: ignore[union-attr]
    d = cached_driver(store, trace, tmp_path, None, IdentifiedLauncher({}), concurrency=8)
    parallel = await d.run_requirement(run_id="run-2", oracle=oracle, scenario=SCENARIO, seed=7)
    assert [e.payload.variant for e in parallel] == names  # type: ignore[union-attr]


def test_side_comes_from_the_variant_when_the_rbs_has_no_where() -> None:
    from rfcv.adapters.manifest import load_manifest
    from rfcv.domains.rfc_protocol.adapter_view import to_vocabulary
    from rfcv.domains.rfc_protocol.sandbox.driver import TestDriver
    from rfcv.domains.rfc_protocol.spec.oracle_compiler import compile_oracle
    from rfcv.domains.rfc_protocol.spec.rbs import parse_rbs

    text = """requirement TLS13-0103 from RFC8446§4.1.1#p6 modal MUST type B
actor server
state initial
trigger receive(client_hello)
expect send_alert(handshake_failure) then close within 2000ms
variants case(client_hello.groups, disjoint), valid_case(client_hello.groups, overlap)
"""
    from conftest import ADAPTER_DIR

    oracle = compile_oracle(parse_rbs(text), to_vocabulary(load_manifest(ADAPTER_DIR)))
    sides = {v.name: TestDriver._side(oracle, v, {v.field: v.value}) for v in oracle.variants}
    assert sides == {"case:client_hello.groups=disjoint": "trigger", "valid_case:client_hello.groups=overlap": "valid"}

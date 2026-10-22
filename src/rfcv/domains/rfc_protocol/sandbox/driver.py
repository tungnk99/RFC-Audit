"""Test driver: chạy kịch bản trên SUT và bản tham chiếu, áp oracle, ghi T3 kèm nhân chứng (M3).

Một lần chạy một biến thể:
1. khởi động SUT mới, chạy ca sanity: hỏng thì kết quả là ERROR (lỗi môi trường), không phải FAIL;
2. chạy kịch bản qua backend → vết sự kiện chuẩn hoá; chưa tới trigger thì ERROR;
3. oracle biên dịch tính PASS/FAIL (agent không tham gia);
4. ca FAIL chạy lại thêm 2 lần, ở môi trường khác; khác nhau thì consistent = False (V0);
5. chạy cùng kịch bản trên các bản tham chiếu (nhân chứng dương) và bản đột biến (nhân chứng âm);
6. lưu nhật ký, pcap, lcov vào Artifact store; ghi T3 vào Evidence store.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rfcv.common.hashing import content_hash
from rfcv.core.trace import TraceLog
from rfcv.domains.rfc_protocol.payloads import Outcome, Producer, T3Payload, Tier, Witness, WitnessRun
from rfcv.domains.rfc_protocol.sandbox.backend import Backend, EventTrace, SutLauncher
from rfcv.domains.rfc_protocol.schemas import ScenarioProposal
from rfcv.domains.rfc_protocol.spec.oracle_compiler import CompiledOracle, ConcreteVariant, instantiate_samples
from rfcv.evidence.artifacts import ArtifactStore
from rfcv.evidence.models import Evidence, EvidenceDraft
from rfcv.evidence.store import EvidenceStore


class ScenarioRejected(ValueError):
    pass


@dataclass(frozen=True)
class CaseResult:
    outcome: Outcome
    trace: EventTrace | None
    reason: str | None = None


class TestDriver:
    __test__ = False  # không phải lớp kiểm thử của pytest

    def __init__(
        self,
        backend: Backend,
        launcher: SutLauncher,
        store: EvidenceStore,
        artifacts: ArtifactStore,
        trace: TraceLog,
        *,
        sut_impl: str,
        references: Sequence[str],
        mutants: Sequence[str] = (),
        reruns_on_fail: int = 2,
        coverage: bool = True,
    ) -> None:
        self._backend = backend
        self._launcher = launcher
        self._store = store
        self._artifacts = artifacts
        self._trace = trace
        self._sut = sut_impl
        self._refs = tuple(references)
        self._mutants = tuple(mutants)
        self._reruns = reruns_on_fail
        self._coverage = coverage

    async def run_requirement(
        self,
        *,
        run_id: str,
        oracle: CompiledOracle,
        scenario: ScenarioProposal,
        seed: int,
        requested_by: dict[str, str] | None = None,
    ) -> list[Evidence]:
        check = self._backend.validate(scenario)
        if not check.ok:
            raise ScenarioRejected("; ".join(check.errors))
        scenario_hash = self._artifacts.put(scenario.model_dump_json().encode())
        out: list[Evidence] = []
        for variant in oracle.variants:
            for name, params, vseed in self._instances(variant, seed):
                out.append(
                    await self._run_variant(
                        run_id, oracle, scenario, scenario_hash, variant, name, params, vseed, requested_by
                    )
                )
        return out

    @staticmethod
    def _instances(variant: ConcreteVariant, seed: int) -> list[tuple[str, dict[str, int | str], int | None]]:
        """Các lần chạy cụ thể của một biến thể: lấy mẫu cho biến thể random/valid_random, một lần cho biến thể cố định.
        Biến thể probe do `probe_field` điều khiển riêng, không sinh trước."""
        if variant.variant_class in ("random", "valid_random"):
            return [
                (f"{variant.name}{suffix}", {variant.field: v}, seed)
                for suffix, v in instantiate_samples(variant, seed)
            ]
        if variant.variant_class == "probe":
            return []
        assert variant.value is not None
        return [(variant.name, {variant.field: variant.value}, None)]

    async def _case(
        self,
        impl: str,
        oracle: CompiledOracle,
        variant: ConcreteVariant,
        scenario: ScenarioProposal,
        params: dict[str, int | str],
        seed: int,
        environment: int,
        coverage: bool,
    ) -> CaseResult:
        async with self._launcher.start(impl, coverage=coverage, environment=environment) as ep:
            if not await self._backend.sanity(ep):
                return CaseResult(Outcome.ERROR, None, "sanity_failed")
            trace = await self._backend.run(scenario, params, ep, seed)
        if not trace.trigger_reached:
            return CaseResult(Outcome.ERROR, trace, "trigger_not_reached")
        if not trace.sut_alive_after:
            # SUT sập sau khi nhận dữ liệu kích hoạt: tính là FAIL và gắn cờ (có thể là lỗi bảo mật).
            return CaseResult(Outcome.FAIL, trace, "sut_crashed")
        valid_side = self._side(oracle, variant, params) == "valid"
        evaluate = oracle.evaluate_control if valid_side else oracle.evaluate
        return CaseResult(evaluate(trace.events), trace)

    @staticmethod
    def _side(oracle: CompiledOracle, variant: ConcreteVariant, params: dict[str, int | str]) -> str:
        """Phía của lần chạy: suy từ giá trị cụ thể và `where` của oracle (biến thể probe nằm cả hai phía)."""
        value = params.get(variant.field)
        if isinstance(value, int):
            return oracle.side_of(variant.field, value)
        return variant.side

    async def _run_variant(
        self,
        run_id: str,
        oracle: CompiledOracle,
        scenario: ScenarioProposal,
        scenario_hash: str,
        variant: ConcreteVariant,
        name: str,
        params: dict[str, int | str],
        seed: int | None,
        requested_by: dict[str, str] | None,
    ) -> Evidence:
        s = seed or 0
        first = await self._case(
            self._sut, oracle, variant, scenario, params, s, environment=0, coverage=self._coverage
        )
        runs = [first]
        if first.outcome is Outcome.FAIL:
            for env in range(1, self._reruns + 1):
                runs.append(await self._case(self._sut, oracle, variant, scenario, params, s, env, coverage=False))
        consistent = len({r.outcome for r in runs}) == 1

        positive: list[WitnessRun] = []
        for ref in self._refs:
            r = await self._case(ref, oracle, variant, scenario, params, s, 0, coverage=False)
            positive.append(WitnessRun(impl=ref, outcome=r.outcome))
        negative: list[WitnessRun] = []
        for mutant in self._mutants:
            r = await self._case(mutant, oracle, variant, scenario, params, s, 0, coverage=False)
            negative.append(WitnessRun(impl=mutant, outcome=r.outcome))

        artifacts: dict[str, str] = {"scenario": scenario_hash}
        if first.trace is not None:
            for key, blob in (("sut_log", first.trace.raw_log), ("pcap", first.trace.pcap), ("lcov", first.trace.lcov)):
                if blob:
                    artifacts[key] = self._artifacts.put(blob)
        observed: dict[str, str | int | bool] = dict(first.trace.observation) if first.trace else {}
        if first.reason:
            observed["reason"] = first.reason

        payload = T3Payload(
            scenario=scenario_hash,
            oracle=oracle.oracle_hash,
            variant=name,
            variant_class=variant.variant_class,
            side=self._side(oracle, variant, params),  # type: ignore[arg-type]
            params=params,
            seed=seed,
            trigger_reached=first.trace.trigger_reached if first.trace else False,
            outcome=first.outcome,
            observed=observed,
            runs=len(runs),
            consistent=consistent,
            witness=Witness(positive=tuple(positive), negative=tuple(negative)),
            artifacts=artifacts,
        )
        evidence = self._store.append(
            EvidenceDraft(
                run_id=run_id,
                requirement_id=oracle.requirement_id,
                tier=Tier.T3,
                payload=payload,
                produced_by=Producer.TEST_DRIVER,
                requested_by=requested_by,
                provenance={"backend": self._backend.name, "sut": self._sut, "params": content_hash(params)},
            )
        )
        self._trace.append(
            run_id,
            "t3",
            {"evidence_id": evidence.evidence_id, "variant": name, "outcome": first.outcome.value},
            requirement_id=oracle.requirement_id,
        )
        return evidence

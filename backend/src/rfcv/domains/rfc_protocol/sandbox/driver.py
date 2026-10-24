"""Test driver: chạy kịch bản trên SUT và bản tham chiếu, áp oracle, ghi T3 kèm nhân chứng (M3).

Một lần chạy một biến thể:
1. khởi động SUT mới, chạy ca sanity: hỏng, kể cả SUT không khởi động được, thì kết quả là ERROR (lỗi môi trường), không
   phải FAIL. Riêng NotImplementedError (thành phần chưa cài) không bị giấu thành ERROR. Mỗi ca để lại một sự kiện `t3_case`;
2. chạy kịch bản qua backend → vết sự kiện chuẩn hoá; chưa tới trigger thì ERROR;
3. oracle biên dịch tính PASS/FAIL (agent không tham gia);
4. ca FAIL chạy lại thêm 2 lần, ở môi trường khác; khác nhau thì consistent = False (V0);
5. chạy cùng kịch bản trên các bản tham chiếu (nhân chứng dương) và bản đột biến (nhân chứng âm);
6. lưu nhật ký, pcap, lcov vào Artifact store; ghi T3 vào Evidence store.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from rfcv.common.hashing import content_hash
from rfcv.core.trace import TraceLog
from rfcv.domains.rfc_protocol.payloads import Outcome, Producer, T3Payload, Tier, Witness, WitnessRun
from rfcv.domains.rfc_protocol.sandbox.backend import Backend, EventTrace, SutLauncher
from rfcv.domains.rfc_protocol.sandbox.dsl import DslSpec
from rfcv.domains.rfc_protocol.sandbox.witness_cache import WitnessCache, cache_key
from rfcv.domains.rfc_protocol.schemas import ScenarioProposal
from rfcv.domains.rfc_protocol.spec.oracle_compiler import CompiledOracle, ConcreteVariant, instantiate_samples
from rfcv.evidence.artifacts import ArtifactStore
from rfcv.evidence.models import Evidence, EvidenceDraft
from rfcv.evidence.store import EvidenceStore

ENVIRONMENT_RETRIES = 1  # số lần thử lại một ca khi hạ tầng lỗi (không áp cho NotImplementedError)
ENVIRONMENT_RETRY_DELAY_S = 2.0
DEFAULT_CONCURRENCY = 4  # số container chạy đồng thời (mỗi ca một container; 1 CPU, 512 MB)


class ScenarioRejected(ValueError):
    pass


@dataclass(frozen=True)
class CaseResult:
    outcome: Outcome
    trace: EventTrace | None
    reason: str | None = None
    detail: str | None = (
        None  # lỗi môi trường: tên và thông điệp ngoại lệ (cắt ngắn); chỉ vào trace, không vào bằng chứng
    )


@dataclass(frozen=True)
class _VariantRun:
    """Kết quả chạy một biến thể, chưa ghi vào kho bằng chứng."""

    name: str
    variant: ConcreteVariant
    params: dict[str, int | str]
    seed: int | None
    scenario_hash: str
    first: CaseResult
    runs: list[CaseResult]
    positive: tuple[WitnessRun, ...]
    negative: tuple[WitnessRun, ...]


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
        concurrency: int = DEFAULT_CONCURRENCY,
        witness_cache: WitnessCache | None = None,
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
        self._gate = asyncio.Semaphore(max(1, concurrency))
        self._witness_cache = witness_cache
        self.cache_hits = 0
        self._identity: dict[str, str | None] = {}

    @property
    def dsl(self) -> DslSpec | None:
        """Đặc tả DSL của backend nếu backend khai báo; Test Agent dùng để biết thao tác và tham số hợp lệ."""
        spec = getattr(self._backend, "dsl", None)
        return spec if isinstance(spec, DslSpec) else None

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
        jobs = [
            (variant, name, params, vseed)
            for variant in oracle.variants
            for name, params, vseed in self._instances(variant, seed)
        ]
        # Chạy các biến thể ĐỒNG THỜI (có trần số container), nhưng ghi bằng chứng theo thứ tự cố định để chuỗi băm không phụ
        # thuộc ca nào xong trước.
        results = await asyncio.gather(
            *(
                self._execute_variant(run_id, oracle, scenario, scenario_hash, variant, name, params, vseed)
                for variant, name, params, vseed in jobs
            )
        )
        return [self._record_variant(run_id, oracle, r, requested_by) for r in results]

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
        trace: EventTrace | None = None
        for attempt in range(ENVIRONMENT_RETRIES + 1):
            try:
                async with self._launcher.start(impl, coverage=coverage, environment=environment) as ep:
                    if not await self._backend.sanity(ep):
                        return CaseResult(Outcome.ERROR, None, "sanity_failed")
                    trace = await self._backend.run(scenario, params, ep, seed)
                break
            except NotImplementedError:
                raise  # khoảng trống cài đặt chứ không phải lỗi môi trường: phải lộ ra, không giấu thành ERROR
            except Exception as exc:
                # SUT không khởi động được, container sập, backend lỗi giữa chừng: lỗi môi trường, không phải FAIL của SUT.
                # Thử lại vài lần trước khi kết luận (đo: máy ngủ làm `docker run`/`docker stop` quá hạn, ca đúng bị ERROR).
                if attempt == ENVIRONMENT_RETRIES:
                    return CaseResult(Outcome.ERROR, None, "environment_error", f"{type(exc).__name__}: {exc}"[:300])
                await asyncio.sleep(ENVIRONMENT_RETRY_DELAY_S)
        assert trace is not None
        if not trace.trigger_reached:
            return CaseResult(Outcome.ERROR, trace, "trigger_not_reached")
        if not trace.sut_alive_after:
            # SUT sập sau khi nhận dữ liệu kích hoạt: tính là FAIL và gắn cờ (có thể là lỗi bảo mật).
            return CaseResult(Outcome.FAIL, trace, "sut_crashed")
        valid_side = self._side(oracle, variant, params) == "valid"
        evaluate = oracle.evaluate_control if valid_side else oracle.evaluate
        return CaseResult(evaluate(trace.events), trace)

    async def probe(
        self, *, oracle: CompiledOracle, scenario: ScenarioProposal, variant_name: str | None, seed: int
    ) -> dict[str, Any]:
        """Chạy THỬ một biến thể trên bản tham chiếu (không ghi bằng chứng): để Test agent biết kịch bản có chạm trigger
        không và quan sát ra sao trước khi nộp. Kết quả chỉ gồm giá trị miền hữu hạn."""
        check = self._backend.validate(scenario)
        if not check.ok:
            return {"ok": False, "stage": "validate", "errors": list(check.errors)[:5] or ["SCENARIO_INVALID"]}
        instances = [(v, n, p, s) for v in oracle.variants for n, p, s in self._instances(v, seed)]
        names = [n for _, n, _, _ in instances]
        chosen = next((i for i in instances if i[1] == variant_name), instances[0] if variant_name is None else None)
        if chosen is None:
            return {"ok": False, "stage": "variant", "errors": ["UNKNOWN_VARIANT"], "available": names[:12]}
        variant, name, params, vseed = chosen
        impl = self._refs[0] if self._refs else self._sut
        result = await self._case(impl, oracle, variant, scenario, params, vseed or seed, 0, False)
        trace = result.trace
        return {
            "ok": True,
            "variant": name,
            "impl": impl,
            "outcome": result.outcome.value,
            "reason": result.reason,
            "trigger_reached": trace.trigger_reached if trace else None,
            "sut_alive_after": trace.sut_alive_after if trace else None,
            "observed": dict(trace.observation) if trace else {},
            "available_variants": names[:12],
        }

    async def _witness_key(
        self,
        impl: str,
        scenario: ScenarioProposal,
        oracle: CompiledOracle,
        params: dict[str, int | str],
        seed: int,
    ) -> str | None:
        """Khoá cache của một ca tham chiếu; None nếu không định danh được ảnh (không cache)."""
        if self._witness_cache is None:
            return None
        if impl not in self._identity:
            identify: Any = getattr(self._launcher, "identity", None)
            self._identity[impl] = await identify(impl) if identify is not None else None
        ident = self._identity[impl]
        if ident is None:
            return None
        return cache_key(
            image=ident,
            impl=impl,
            scenario=scenario.model_dump_json(),
            oracle=oracle.oracle_hash,
            params=params,
            seed=seed,
            backend=self._backend.name,
        )

    async def _traced_case(
        self,
        run_id: str,
        role: str,
        impl: str,
        oracle: CompiledOracle,
        variant: ConcreteVariant,
        name: str,
        scenario: ScenarioProposal,
        params: dict[str, int | str],
        seed: int,
        environment: int,
        coverage: bool,
    ) -> CaseResult:
        """Một ca chạy kèm một sự kiện `t3_case`: vai (SUT, chạy lại, tham chiếu, đột biến), kết quả, vì sao ERROR.

        Ca của bản tham chiếu được dùng lại từ bộ nhớ đệm khi cùng ảnh, kịch bản, oracle và tham số (xem witness_cache)."""
        key = await self._witness_key(impl, scenario, oracle, params, seed) if role == "reference" else None
        if key is not None and self._witness_cache is not None and (hit := self._witness_cache.get(key)) is not None:
            outcome, origin = hit
            self.cache_hits += 1
            self._trace.append(
                run_id,
                "t3_case",
                {
                    "variant": name,
                    "role": role,
                    "impl": impl,
                    "environment": environment,
                    "outcome": outcome.value,
                    "reason": None,
                    "detail": None,
                    "trigger_reached": None,
                    "sut_alive_after": None,
                    "cache_hit": True,
                    "origin_run": origin,
                },
                requirement_id=oracle.requirement_id,
            )
            return CaseResult(outcome, None)
        async with self._gate:
            result = await self._case(impl, oracle, variant, scenario, params, seed, environment, coverage)
        if key is not None and self._witness_cache is not None:
            self._witness_cache.put(key, result.outcome, run_id)
        trace = result.trace
        self._trace.append(
            run_id,
            "t3_case",
            {
                "variant": name,
                "role": role,
                "impl": impl,
                "environment": environment,
                "outcome": result.outcome.value,
                "reason": result.reason,
                "detail": result.detail,
                "trigger_reached": trace.trigger_reached if trace else None,
                "sut_alive_after": trace.sut_alive_after if trace else None,
            },
            requirement_id=oracle.requirement_id,
        )
        return result

    @staticmethod
    def _side(oracle: CompiledOracle, variant: ConcreteVariant, params: dict[str, int | str]) -> str:
        """Phía của lần chạy: suy từ giá trị cụ thể và `where` của oracle (biến thể probe nằm cả hai phía)."""
        value = params.get(variant.field)
        if oracle.where is None and variant.variant_class in ("required", "control"):
            return variant.side  # không có `where`: phía do chính biến thể khai báo (case / valid_case)
        if isinstance(value, int | str):
            return oracle.side_of(variant.field, value)
        return variant.side

    async def _execute_variant(
        self,
        run_id: str,
        oracle: CompiledOracle,
        scenario: ScenarioProposal,
        scenario_hash: str,
        variant: ConcreteVariant,
        name: str,
        params: dict[str, int | str],
        seed: int | None,
    ) -> _VariantRun:
        """Chạy mọi ca của một biến thể (SUT, chạy lại khi FAIL, bản tham chiếu, bản đột biến) mà CHƯA ghi bằng chứng."""
        s = seed or 0

        async def case(role: str, impl: str, environment: int, coverage: bool) -> CaseResult:
            return await self._traced_case(
                run_id, role, impl, oracle, variant, name, scenario, params, s, environment, coverage
            )

        first = await case("sut", self._sut, 0, self._coverage)
        runs = [first]
        if first.outcome is Outcome.FAIL:
            for env in range(1, self._reruns + 1):
                runs.append(await case("rerun", self._sut, env, False))
        references = await asyncio.gather(*(case("reference", ref, 0, False) for ref in self._refs))
        mutants = await asyncio.gather(*(case("mutant", mutant, 0, False) for mutant in self._mutants))
        return _VariantRun(
            name=name,
            variant=variant,
            params=params,
            seed=seed,
            scenario_hash=scenario_hash,
            first=first,
            runs=runs,
            positive=tuple(
                WitnessRun(impl=ref, outcome=r.outcome) for ref, r in zip(self._refs, references, strict=True)
            ),
            negative=tuple(WitnessRun(impl=m, outcome=r.outcome) for m, r in zip(self._mutants, mutants, strict=True)),
        )

    def _record_variant(
        self, run_id: str, oracle: CompiledOracle, v: _VariantRun, requested_by: dict[str, str] | None
    ) -> Evidence:
        """Ghi bằng chứng T3 của một biến thể đã chạy xong (gọi theo thứ tự cố định để chuỗi băm ổn định)."""
        first = v.first
        consistent = len({r.outcome for r in v.runs}) == 1
        artifacts: dict[str, str] = {"scenario": v.scenario_hash}
        if first.trace is not None:
            for key, blob in (("sut_log", first.trace.raw_log), ("pcap", first.trace.pcap), ("lcov", first.trace.lcov)):
                if blob:
                    artifacts[key] = self._artifacts.put(blob)
        observed: dict[str, str | int | bool] = dict(first.trace.observation) if first.trace else {}
        if first.reason:
            observed["reason"] = first.reason

        payload = T3Payload(
            scenario=v.scenario_hash,
            oracle=oracle.oracle_hash,
            variant=v.name,
            variant_class=v.variant.variant_class,
            side=self._side(oracle, v.variant, v.params),  # type: ignore[arg-type]
            params=v.params,
            seed=v.seed,
            trigger_reached=first.trace.trigger_reached if first.trace else False,
            outcome=first.outcome,
            observed=observed,
            runs=len(v.runs),
            consistent=consistent,
            witness=Witness(positive=v.positive, negative=v.negative),
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
                provenance={"backend": self._backend.name, "sut": self._sut, "params": content_hash(v.params)},
            )
        )
        self._trace.append(
            run_id,
            "t3",
            {"evidence_id": evidence.evidence_id, "variant": v.name, "outcome": first.outcome.value},
            requirement_id=oracle.requirement_id,
        )
        return evidence

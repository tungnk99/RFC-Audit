"""Phần chạy của miền RFC giao thức: nối handler của từng agent và nạp yêu cầu.

Handler nằm trong thư mục từng agent (`agents/<tên>/handler.py`). Ở đây chỉ lắp chúng lại theo kiểu nhiệm vụ.
"""

from __future__ import annotations

import os
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import yaml

from agents.code_indexer.handler import ComponentMapHandler
from agents.code_reader.handler import LocationHandler
from agents.code_reader.schema import LocationClaim
from agents.common import ORACLE_KEY, RBS_KEY, TaskType
from agents.locator.service import Locator, requirement_keywords
from agents.rfc_analyst.handler import evaluate_proposal
from agents.rfc_analyst.schema import RbsProposal
from agents.tester.handler import ScenarioHandler
from agents.verifier.handler import NoopHandler
from rfcv.common.hashing import text_hash
from rfcv.core.execution_loop import Investigation
from rfcv.core.ifc import Labeled, TrustLabel
from rfcv.domains.rfc_protocol.adapter_view import to_vocabulary, vocabulary_terms
from rfcv.domains.rfc_protocol.agent_tools import AgentTools
from rfcv.domains.rfc_protocol.call_chain import call_chain_tool_spec
from rfcv.domains.rfc_protocol.divergence_audit import extract_divergence_points
from rfcv.domains.rfc_protocol.multi_hypothesis import (
    HypothesisSpec,
    TournamentResult,
    build_hypotheses,
    evaluate_claim_with_gate,
    run_best_of_k,
)
from rfcv.domains.rfc_protocol.rbs_precheck import PrecheckResult, ReferenceObservation, sanity_precheck_rbs
from rfcv.domains.rfc_protocol.rfc_gate import load_rfc_documents, lookup_sentence
from rfcv.domains.rfc_protocol.rules import RULE_SET, ProtocolRequirement
from rfcv.domains.rfc_protocol.sandbox import witness_cache
from rfcv.domains.rfc_protocol.sandbox.driver import TestDriver
from rfcv.domains.rfc_protocol.sandbox.witness_cache import WitnessCache
from rfcv.domains.rfc_protocol.schema_gate import SchemaGate
from rfcv.domains.rfc_protocol.spec.oracle_compiler import compile_oracle
from rfcv.domains.rfc_protocol.spec.rbs import parse_rbs
from rfcv.evidence.models import Evidence
from rfcv.evidence.verdict_engine import SufficiencyReport
from rfcv.gates.tool_gateway import ToolSession, ToolSpec

SPEC_TASK = "RFC_TO_RBS"  # kiểu việc của bước phân tích đặc tả (không qua Planner nên không nằm trong TaskType)
SPEC_STREAM = "rfc_analyst.a"  # luồng dịch thứ nhất; luồng .b cần mô hình khác họ (BL-16)
SPEC_GROUP_MAX = 8  # số câu của nhóm đưa cho agent (câu cần dịch + các câu cùng mục)

__all__ = ["ORACLE_KEY", "LocationHandler", "NoopHandler", "ProtocolRuntime", "ScenarioHandler"]


def _rfc_dir(rt: Any) -> Path | None:
    """Input store của RFC: cấu hình của lần chạy, hoặc biến môi trường RFCV_RFC_DIR (cho script đo chạy ngoài `rfcv run`).
    Không tự đoán thư mục: không đặt thì agent chỉ thấy RBS."""
    configured = getattr(getattr(rt, "config", None), "rfc_dir", None)
    if configured is not None:
        return Path(configured)
    env = os.environ.get("RFCV_RFC_DIR")
    return Path(env) if env else None


def _sentence_aliases(rt: Any) -> dict[str, str]:
    """Định danh câu trong RBS -> định danh cùng câu trong bản RFC đang đọc (RBS đánh số theo RFCXML, input thường là TXT)."""
    adapter_dir = getattr(getattr(rt, "config", None), "adapter_dir", None)
    path = Path(adapter_dir) / "sentence_aliases.yaml" if adapter_dir is not None else None
    if path is None or not path.is_file():
        return {}
    data: dict[Any, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in data.items()}


def _spec_vocabulary(manifest: Any) -> dict[str, Any]:
    """Từ vựng dạng agent dùng được để VIẾT RBS: chữ ký đủ tham số của sự kiện, trạng thái, enum và miền từng trường.
    (Danh sách tên trần không đủ: đo cho thấy agent bịa tên tham số/trường và thiếu tham số của sự kiện nên bị cổng từ chối.)"""
    v = to_vocabulary(manifest)
    return {
        "events": list(v.events),
        "states": list(v.states),
        "enums": {k: list(vals) for k, vals in v.enums.items()},
        "field_domains": {
            k: {"min": d.min, "max": d.max, **({"values": list(d.values)} if d.values else {})}
            for k, d in v.field_domains.items()
        },
    }


def _alias_for(sentence_id: str, docs: dict[int, Any], aliases: dict[str, str]) -> str | None:
    """Bí danh chỉ áp khi RFC đang đọc là bản TXT: bản RFCXML dùng đúng định danh trong RBS."""
    alias = aliases.get(sentence_id)
    m = re.match(r"RFC(\d+)", sentence_id)
    doc = docs.get(int(m.group(1))) if m else None
    return alias if alias and doc is not None and doc.fmt == "txt" else None


class ProtocolRuntime:
    def __init__(self) -> None:
        self._locators: dict[str, Locator] = {}  # theo run_id
        self._investigations: dict[str, Investigation] = {}  # theo mã yêu cầu, để công cụ của agent tra
        self._driver: TestDriver | None = None

    def required_providers(self) -> Sequence[str]:
        return ("backend", "code_index", "executor", "sut_launcher")

    def tools(self, rt: Any) -> Sequence[ToolSpec]:
        """Công cụ của miền cần runtime đã lắp: `locator.suggest` (chỉ mục mã + gợi ý của adapter) và công cụ đọc của các
        agent đặc quyền (bằng chứng, kết luận, RFC, kiểm thử; xem agent_tools.py)."""
        specs: list[ToolSpec] = [*self._agent_tools(rt).specs()]
        index = rt.providers.code_index
        if index is not None:
            locator = Locator(index, rt.manifest)
            self._locators[rt.run_id] = locator
            specs.append(locator.tool_spec())
        from rfcv.domains.rfc_protocol.coverage_linker import coverage_hotspots_tool_spec

        specs.append(coverage_hotspots_tool_spec(rt))
        specs.append(call_chain_tool_spec(rt))
        return specs

    def attach_driver(self, driver: TestDriver) -> None:
        """Cho `tester.run_scenario` dùng đúng Test driver của lần chạy (nơi lắp ráp tự dựng driver thay vì gọi `handlers`)."""
        self._driver = driver

    def _agent_tools(self, rt: Any) -> AgentTools:
        manifest = rt.manifest
        config = getattr(rt, "config", None)
        adapter_dir: Path | None = getattr(config, "adapter_dir", None) or getattr(rt, "adapter_dir", None)
        if adapter_dir is None and (guess := Path.cwd() / "adapters" / manifest.adapter).is_dir():
            adapter_dir = guess
        return AgentTools(
            investigation=lambda req_id: self._investigations.get(req_id),
            evidence=lambda req_id: rt.store.for_requirement(req_id),
            rules=lambda: getattr(rt, "rules", None) or RULE_SET,
            rfc_docs=load_rfc_documents(manifest, _rfc_dir(rt)),
            driver=lambda: self._driver,
            seed=getattr(rt, "seed", 0),
            examples_dir=adapter_dir / "templates" if adapter_dir is not None else None,
        )

    def handlers(self, rt: Any) -> Mapping[str, Any]:
        manifest = rt.manifest
        index = rt.providers.code_index
        # Kiểm tra số 5 của Schema gate: dòng dẫn phải được biên dịch theo cờ build (khi chỉ mục có nhánh #if).
        compiled: Any = getattr(index, "compiled_lines", None)
        macro_state: Any = getattr(index, "macro_state", None)
        flags = tuple(manifest.build_flags)
        gate = SchemaGate(
            index,
            vocabulary_terms(manifest),
            (lambda f: compiled(f, flags, closed_world=manifest.build_config_complete))
            if compiled is not None
            else None,
            (lambda m: macro_state(m, flags, closed_world=manifest.build_config_complete))
            if macro_state is not None
            else None,
        )
        run_root = getattr(getattr(rt, "config", None), "run_dir", None)
        cache = (
            WitnessCache(Path(run_root) / "cache" / "witness.sqlite")
            if witness_cache.enabled() and run_root is not None and hasattr(rt.providers.sut_launcher, "identity")
            else None
        )
        driver = TestDriver(
            rt.providers.backend,
            rt.providers.sut_launcher,
            rt.store,
            rt.artifacts,
            rt.trace,
            sut_impl=manifest.sut.repo.rstrip("/").rsplit("/", 1)[-1],
            references=[ref.split("@", 1)[0] for ref in manifest.references],
            witness_cache=cache,
        )
        self._driver = driver
        adapter_dir = getattr(getattr(rt, "config", None), "adapter_dir", None)
        executor = getattr(rt.providers, "executor", None)
        cc_tools: dict[str, Any] = {}
        if index is not None and executor is not None:
            from rfcv.gates.code_tools import build_cc_tools

            cc_tools = {s.name: s for s in build_cc_tools(index, executor, flags, bool(manifest.build_config_complete))}
        location = LocationHandler(rt, gate, cc_tools)
        scenario = ScenarioHandler(rt, driver, Path(adapter_dir) / "templates" if adapter_dir is not None else None)
        run_id = getattr(rt, "run_id", None) or ""
        return {
            TaskType.LOCATE.value: location,
            TaskType.TRACE_PATHS.value: location,
            TaskType.RECHECK.value: location,
            TaskType.MAP_COMPONENTS.value: ComponentMapHandler(rt, lambda: self._locators.get(run_id)),
            TaskType.SELECT_TESTS.value: scenario,
            TaskType.CRITIQUE.value: NoopHandler(),
        }

    def investigations(self, rt: Any, source: Path) -> Sequence[Investigation]:
        """Mỗi tệp *.rbs trong `source` là một đặc tả hành vi đã duyệt; biên dịch thành oracle và dựng bài toán."""
        manifest = rt.manifest
        vocab = to_vocabulary(manifest)
        terms = vocabulary_terms(manifest)
        locator = self._locators.get(getattr(rt, "run_id", None) or "")
        rfc_docs = load_rfc_documents(manifest, _rfc_dir(rt))
        hints = {k: {kk: list(vv) for kk, vv in v.items()} for k, v in manifest.locator_hints.items()}
        out: list[Investigation] = []
        for f in sorted(source.glob("*.rbs")):
            text = f.read_text(encoding="utf-8")
            rbs = parse_rbs(text)
            oracle = compile_oracle(rbs, vocab)
            # Câu RFC gốc, đoạn chứa câu và gói ngữ cảnh, lấy theo trường nguồn của RBS qua RFC gate (RFC là đầu vào TRUSTED).
            # Không có bản RFC trong Input store thì agent làm việc chỉ với RBS có cấu trúc, như trước.
            rfc = lookup_sentence(rfc_docs, rbs.sentence_id)
            source_doc = rfc_docs.get(rfc.rfc) if rfc is not None else None
            requirement = ProtocolRequirement(
                requirement_id=rbs.requirement_id,
                rtype=rbs.rtype,
                modal=rbs.modal,
                spec_ref=rbs.sentence_id,
                spec_hash=text_hash(rfc.sentence) if rfc is not None else "",
                spec_doc=source_doc.source if source_doc is not None else "",
                required_variants=oracle.required_variant_names,
                random_k=oracle.random_k,
                valid_random_k=oracle.valid_random_k,
            )
            if locator is not None:
                locator.register(rbs.requirement_id, requirement_keywords(rbs))
            context: dict[str, Labeled[Any]] = {
                "requirement.structured": Labeled(rbs.model_dump(mode="json"), TrustLabel.TRUSTED),
                "requirement.rbs": Labeled(rbs.model_dump(mode="json"), TrustLabel.TRUSTED),
                "adapter.vocabulary": Labeled(sorted(terms), TrustLabel.TRUSTED),
                "adapter.build_flags": Labeled(list(manifest.build_flags), TrustLabel.TRUSTED),
                "adapter.component_taxonomy": Labeled(list(manifest.component_taxonomy), TrustLabel.TRUSTED),
                "adapter.locator_hints": Labeled(hints, TrustLabel.TRUSTED),
            }
            if rfc is not None:
                context["rfc.sentence"] = Labeled(rfc.sentence, TrustLabel.TRUSTED)
                context["rfc.paragraph"] = Labeled(rfc.paragraph, TrustLabel.TRUSTED)
                context["rfc.context_pack"] = Labeled(rfc.context_pack(), TrustLabel.TRUSTED)
                context["rfc.definitions"] = Labeled(list(rfc.definitions), TrustLabel.TRUSTED)
            inv = Investigation(
                requirement=requirement,
                context=context,
                vocabulary_terms=terms,
                domain_state={ORACLE_KEY: oracle, RBS_KEY: rbs},
            )
            self._investigations[requirement.requirement_id] = inv
            out.append(inv)
        return out

    async def analyze_spec(self, rt: Any, inv: Investigation) -> None:
        """RFC Analyst dịch lại câu RFC của yêu cầu này thành RBS, MÙ với bản người viết, rồi đối chiếu (chỉ quan sát).

        Mỗi yêu cầu một lần. Không đổi `inv`: kết luận vẫn dựa trên RBS đã duyệt. Thiếu văn bản RFC hoặc không tra được câu
        thì ghi sự kiện bỏ qua kèm lý do, không làm hỏng lần chạy."""
        rid = inv.requirement.requirement_id
        approved = inv.domain_state[RBS_KEY]
        loop = rt.loop
        docs = load_rfc_documents(rt.manifest, _rfc_dir(rt))
        alias = _alias_for(approved.sentence_id, docs, _sentence_aliases(rt))
        ctx = lookup_sentence(docs, alias or approved.sentence_id)
        if ctx is None:
            loop.log_event(
                "rfc_analysis_skipped",
                {"sentence_id": approved.sentence_id, "reason": "NO_RFC_TEXT" if not docs else "SENTENCE_NOT_FOUND"},
                rid,
            )
            return
        doc = docs[ctx.rfc]
        group = [{"sentence_id": ctx.sentence_id, "modal": "", "text": ctx.sentence, "target": True}]
        for s in doc.sentences(ctx.section):
            if s.sentence_id != ctx.sentence_id and len(group) < SPEC_GROUP_MAX:
                group.append({"sentence_id": s.sentence_id, "modal": s.modal, "text": s.text, "target": False})
        pack = {**ctx.context_pack(), "paragraph": ctx.paragraph}
        available: dict[str, Labeled[Any]] = {
            "rfc.sentence_group": Labeled(group, TrustLabel.TRUSTED),
            "rfc.context_pack": Labeled(pack, TrustLabel.TRUSTED),
            "adapter.vocabulary": Labeled(_spec_vocabulary(rt.manifest), TrustLabel.TRUSTED),
        }
        loop.log_event(
            "rfc_analysis_start",
            {
                "sentence_id": ctx.sentence_id,
                "sentence": ctx.sentence,
                "paragraph": ctx.paragraph,
                "section_path": list(ctx.section_path),
                "group_size": len(group),
                "blind": True,
            },
            rid,
        )
        body = {"task_type": SPEC_TASK, "target_sentence_id": ctx.sentence_id}
        outcome = await loop.analyze_spec(inv, body, available, model_key=SPEC_STREAM)
        proposal = outcome.output if outcome is not None and isinstance(outcome.output, RbsProposal) else None
        result = evaluate_proposal(proposal, approved, docs, to_vocabulary(rt.manifest), aliased_to=alias)
        result["failure"] = outcome.failure if outcome is not None else "NO_ROLE"
        result["target_sentence_id"] = ctx.sentence_id
        ref_obs = inv.domain_state.get("reference_observations")
        if isinstance(ref_obs, Sequence) and ref_obs:
            precheck = self.precheck_spec(rt, inv, cast("Sequence[ReferenceObservation]", ref_obs))
            result["precheck_status"] = precheck.status.value
            result["precheck_reason"] = precheck.reason_code
        loop.log_event("rfc_proposal", result, rid)

    def shared_context(
        self, _report: SufficiencyReport, evidence: Sequence[Evidence], inv: Investigation
    ) -> dict[str, Labeled[Any]]:
        """Trích điểm rẽ nhánh lập luận (`divergence.points`, an toàn IFC) cấp cho Verifier ở mỗi vòng."""
        rfc_item = inv.context.get("rfc.sentence")
        rfc_sentence = str(rfc_item.value) if rfc_item is not None and isinstance(rfc_item.value, str) else None
        t1_items = [e for e in evidence if str(e.tier) == "T1"]
        t3_items = [e for e in evidence if str(e.tier) == "T3"]
        return {"divergence.points": extract_divergence_points(rfc_sentence, t1_items, t3_items)}

    def precheck_spec(
        self, rt: Any, inv: Investigation, observations: Sequence[ReferenceObservation]
    ) -> PrecheckResult:
        """Kiểm định ngược RBS với các bản tham chiếu độc lập (OpenSSL/GnuTLS) để chặn sớm CT-26."""
        rid = inv.requirement.requirement_id
        res = sanity_precheck_rbs(rid, observations)
        if rt.loop is not None:
            rt.loop.log_event(
                "rbs_precheck",
                {
                    "status": res.status.value,
                    "reason_code": res.reason_code,
                    "failed_refs": list(res.failed_refs),
                    "details": list(res.details),
                },
                rid,
            )
        return res

    async def locate_best_of_k(
        self,
        rt: Any,
        inv: Investigation,
        base_params: Mapping[str, Any],
        run_one: Callable[[HypothesisSpec, ToolSession], Awaitable[LocationClaim | None]],
        *,
        k: int | None = None,
    ) -> TournamentResult:
        """Chạy song song K nhánh giả thuyết cho Code Reader, kiểm qua SchemaGate và chọn ứng viên T1 tốt nhất."""
        count = k if k is not None else int(getattr(rt.config, "parallel_hypotheses", 1))
        hypotheses = build_hypotheses(base_params, k=max(1, count))
        rid = inv.requirement.requirement_id
        manifest = rt.manifest
        index = rt.providers.code_index
        compiled: Any = getattr(index, "compiled_lines", None)
        macro_state: Any = getattr(index, "macro_state", None)
        flags = tuple(manifest.build_flags)
        gate = SchemaGate(
            index,
            vocabulary_terms(manifest),
            (lambda f: compiled(f, flags, closed_world=manifest.build_config_complete))
            if compiled is not None
            else None,
            (lambda m: macro_state(m, flags, closed_world=manifest.build_config_complete))
            if macro_state is not None
            else None,
        )
        rbs = inv.domain_state.get(RBS_KEY)
        expected_threshold = int(rbs.where.value) if rbs is not None and rbs.where is not None else None
        max_tools = rt.policy.profile("code_reader").budget_per_task.tool_calls

        async def _branch(hyp: HypothesisSpec) -> tuple[LocationClaim | None, Sequence[str]]:
            session = ToolSession(rt.run_id, "code_reader", rid, max_tools)
            claim = await run_one(hyp, session)
            return evaluate_claim_with_gate(
                claim,
                gate,
                session,
                run_id=rt.run_id,
                requirement_id=rid,
                threshold=expected_threshold,
            )

        tournament = await run_best_of_k(hypotheses, _branch)
        rt.trace.append(
            rt.run_id, "best_of_k_tournament", tournament.to_telemetry(), role="code_reader", requirement_id=rid
        )
        return tournament

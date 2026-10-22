"""Phần chạy của miền RFC giao thức: nối handler của từng agent và nạp yêu cầu.

Handler nằm trong thư mục từng agent (`agents/<tên>/handler.py`). Ở đây chỉ lắp chúng lại theo kiểu nhiệm vụ.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from agents.code_indexer.handler import ComponentMapHandler
from agents.code_reader.handler import LocationHandler
from agents.common import ORACLE_KEY, TaskType
from agents.locator.service import Locator, requirement_keywords
from agents.test.handler import ScenarioHandler
from agents.verifier.handler import NoopHandler
from rfcv.core.execution_loop import Investigation
from rfcv.core.ifc import Labeled, TrustLabel
from rfcv.domains.rfc_protocol.adapter_view import to_vocabulary, vocabulary_terms
from rfcv.domains.rfc_protocol.agent_tools import AgentTools
from rfcv.domains.rfc_protocol.rfc_gate import load_rfc_documents, lookup_sentence
from rfcv.domains.rfc_protocol.rules import RULE_SET, ProtocolRequirement
from rfcv.domains.rfc_protocol.sandbox.driver import TestDriver
from rfcv.domains.rfc_protocol.schema_gate import SchemaGate
from rfcv.domains.rfc_protocol.spec.oracle_compiler import compile_oracle
from rfcv.domains.rfc_protocol.spec.rbs import parse_rbs
from rfcv.gates.tool_gateway import ToolSpec

__all__ = ["ORACLE_KEY", "LocationHandler", "NoopHandler", "ProtocolRuntime", "ScenarioHandler"]


def _rfc_dir(rt: Any) -> Path | None:
    """Input store của RFC: cấu hình của lần chạy, hoặc biến môi trường RFCV_RFC_DIR (cho script đo chạy ngoài `rfcv run`).
    Không tự đoán thư mục: không đặt thì agent chỉ thấy RBS."""
    configured = getattr(getattr(rt, "config", None), "rfc_dir", None)
    if configured is not None:
        return Path(configured)
    env = os.environ.get("RFCV_RFC_DIR")
    return Path(env) if env else None


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
        return specs

    def attach_driver(self, driver: TestDriver) -> None:
        """Cho `test.run_scenario` dùng đúng Test driver của lần chạy (nơi lắp ráp tự dựng driver thay vì gọi `handlers`)."""
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
        flags = tuple(manifest.build_flags)
        gate = SchemaGate(
            index,
            vocabulary_terms(manifest),
            (lambda f: compiled(f, flags)) if compiled is not None else None,
        )
        driver = TestDriver(
            rt.providers.backend,
            rt.providers.sut_launcher,
            rt.store,
            rt.artifacts,
            rt.trace,
            sut_impl=manifest.sut.repo.rstrip("/").rsplit("/", 1)[-1],
            references=[ref.split("@", 1)[0] for ref in manifest.references],
        )
        self._driver = driver
        location, scenario = LocationHandler(rt, gate), ScenarioHandler(rt, driver)
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
            requirement = ProtocolRequirement(
                requirement_id=rbs.requirement_id,
                rtype=rbs.rtype,
                modal=rbs.modal,
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
            # Câu RFC gốc, đoạn chứa câu và gói ngữ cảnh, lấy theo trường nguồn của RBS qua RFC gate (RFC là đầu vào TRUSTED).
            # Không có bản RFC trong Input store thì agent làm việc chỉ với RBS có cấu trúc, như trước.
            rfc = lookup_sentence(rfc_docs, rbs.sentence_id)
            if rfc is not None:
                context["rfc.sentence"] = Labeled(rfc.sentence, TrustLabel.TRUSTED)
                context["rfc.paragraph"] = Labeled(rfc.paragraph, TrustLabel.TRUSTED)
                context["rfc.context_pack"] = Labeled(rfc.context_pack(), TrustLabel.TRUSTED)
            inv = Investigation(
                requirement=requirement,
                context=context,
                vocabulary_terms=terms,
                domain_state={ORACLE_KEY: oracle},
            )
            self._investigations[requirement.requirement_id] = inv
            out.append(inv)
        return out

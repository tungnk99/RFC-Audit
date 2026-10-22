"""Phần chạy của miền RFC giao thức: nối handler của từng agent và nạp yêu cầu.

Handler nằm trong thư mục từng agent (`agents/<tên>/handler.py`). Ở đây chỉ lắp chúng lại theo kiểu nhiệm vụ.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from rfcv.core.execution_loop import Investigation
from rfcv.core.ifc import Labeled, TrustLabel
from rfcv.domains.rfc_protocol.adapter_view import to_vocabulary, vocabulary_terms
from rfcv.domains.rfc_protocol.agents.code_reader.handler import LocationHandler
from rfcv.domains.rfc_protocol.agents.common import ORACLE_KEY, TaskType
from rfcv.domains.rfc_protocol.agents.test.handler import ScenarioHandler
from rfcv.domains.rfc_protocol.agents.verifier.handler import NoopHandler
from rfcv.domains.rfc_protocol.rules import ProtocolRequirement
from rfcv.domains.rfc_protocol.sandbox.driver import TestDriver
from rfcv.domains.rfc_protocol.schema_gate import SchemaGate
from rfcv.domains.rfc_protocol.spec.oracle_compiler import compile_oracle
from rfcv.domains.rfc_protocol.spec.rbs import parse_rbs

__all__ = ["ORACLE_KEY", "LocationHandler", "NoopHandler", "ProtocolRuntime", "ScenarioHandler"]

class ProtocolRuntime:
    def required_providers(self) -> Sequence[str]:
        return ("backend", "code_index", "executor", "sut_launcher")

    def handlers(self, rt: Any) -> Mapping[str, Any]:
        manifest = rt.manifest
        gate = SchemaGate(rt.providers.code_index, vocabulary_terms(manifest))
        driver = TestDriver(
            rt.providers.backend,
            rt.providers.sut_launcher,
            rt.store,
            rt.artifacts,
            rt.trace,
            sut_impl=manifest.sut.repo.rstrip("/").rsplit("/", 1)[-1],
            references=[ref.split("@", 1)[0] for ref in manifest.references],
        )
        location, scenario = LocationHandler(rt, gate), ScenarioHandler(rt, driver)
        return {
            TaskType.LOCATE.value: location,
            TaskType.TRACE_PATHS.value: location,
            TaskType.RECHECK.value: location,
            TaskType.SELECT_TESTS.value: scenario,
            TaskType.CRITIQUE.value: NoopHandler(),
        }

    def investigations(self, rt: Any, source: Path) -> Sequence[Investigation]:
        """Mỗi tệp *.rbs trong `source` là một đặc tả hành vi đã duyệt; biên dịch thành oracle và dựng bài toán."""
        manifest = rt.manifest
        vocab = to_vocabulary(manifest)
        terms = vocabulary_terms(manifest)
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
            context = {
                "requirement.structured": Labeled(rbs.model_dump(mode="json"), TrustLabel.TRUSTED),
                "requirement.rbs": Labeled(rbs.model_dump(mode="json"), TrustLabel.TRUSTED),
                "adapter.vocabulary": Labeled(sorted(terms), TrustLabel.TRUSTED),
                "adapter.build_flags": Labeled(list(manifest.build_flags), TrustLabel.TRUSTED),
            }
            out.append(
                Investigation(
                    requirement=requirement,
                    context=context,
                    vocabulary_terms=terms,
                    domain_state={ORACLE_KEY: oracle},
                )
            )
        return out


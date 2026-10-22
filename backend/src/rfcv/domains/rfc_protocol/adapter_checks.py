"""Kiểm tra hình thức riêng của miền RFC giao thức cho Adapter checker: từ vựng, mẫu kiểm thử, ví dụ RBS."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import ValidationError

from rfcv.adapters.checker import CheckItem, Status
from rfcv.adapters.manifest import AdapterManifest
from rfcv.domains.rfc_protocol.adapter_view import to_vocabulary
from rfcv.domains.rfc_protocol.sandbox.dsl import DslSpec
from rfcv.domains.rfc_protocol.schemas import ScenarioProposal
from rfcv.domains.rfc_protocol.spec.oracle_compiler import OracleCompileError, compile_oracle
from rfcv.domains.rfc_protocol.spec.rbs import RbsSyntaxError, parse_rbs
from rfcv.plugins import current_registry

TEMPLATE_KEYS = {"id", "requirement_types", "rfc_refs", "runner"}


def check_protocol_adapter(adapter_dir: Path, m: AdapterManifest) -> list[CheckItem]:
    items: list[CheckItem] = []
    try:
        vocab = to_vocabulary(m)
        vocab.signatures()
        items.append(CheckItem("form.vocabulary", Status.PASS, f"{len(vocab.events)} sự kiện"))
    except (ValueError, ValidationError) as exc:
        return [CheckItem("form.vocabulary", Status.FAIL, str(exc)[:500])]

    dsl = _backend_dsl(m)
    for f in sorted((adapter_dir / "templates").glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            items.append(CheckItem(f"form.template:{f.name}", Status.FAIL, str(exc)[:200]))
            continue
        if not isinstance(data, dict):
            items.append(CheckItem(f"form.template:{f.name}", Status.FAIL, "mẫu phải là một bảng YAML"))
            continue
        template = cast(dict[str, Any], data)
        missing = TEMPLATE_KEYS - set(template)
        items.append(
            CheckItem(f"form.template:{f.name}", Status.FAIL if missing else Status.PASS, ", ".join(sorted(missing)))
        )
        if "steps" in template:
            items.append(_check_template_steps(f.name, template, dsl))

    for f in sorted((adapter_dir / "examples").glob("*.rbs")):
        try:
            oracle = compile_oracle(parse_rbs(f.read_text(encoding="utf-8")), vocab)
            items.append(CheckItem(f"form.rbs_example:{f.name}", Status.PASS, f"{len(oracle.variants)} biến thể"))
        except (RbsSyntaxError, OracleCompileError) as exc:
            items.append(CheckItem(f"form.rbs_example:{f.name}", Status.FAIL, str(exc)[:300]))
    return items


def _backend_dsl(m: AdapterManifest) -> DslSpec | None:
    """DSL mà backend của adapter chấp nhận, nếu backend đã đăng ký và có khai báo DSL."""
    factory = current_registry().backends.get(m.backend)
    backend = factory(m, None) if factory is not None else None
    spec = getattr(backend, "dsl", None)
    return spec if isinstance(spec, DslSpec) else None


def _check_template_steps(name: str, template: dict[str, Any], dsl: DslSpec | None) -> CheckItem:
    """Mẫu viết bằng DSL phải qua đúng bộ kiểm kịch bản của backend, như kịch bản do Test Agent nộp."""
    check = f"form.template_dsl:{name}"
    if dsl is None:
        return CheckItem(check, Status.SKIPPED, "backend không khai báo DSL")
    try:
        scenario = ScenarioProposal.model_validate(
            {
                "requirement_id": str(template.get("id", name)),
                "reach_state": "template",
                "steps": template["steps"],
                "bindings": template.get("bindings", {}),
            }
        )
    except ValidationError as exc:
        return CheckItem(check, Status.FAIL, str(exc)[:300])
    result = dsl.validate(scenario)
    return CheckItem(check, Status.PASS if result.ok else Status.FAIL, "; ".join(result.errors)[:300])

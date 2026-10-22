"""Kiểm tra hình thức riêng của miền RFC giao thức cho Adapter checker: từ vựng, mẫu kiểm thử, ví dụ RBS."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import yaml
from pydantic import ValidationError

from rfcv.adapters.checker import CheckItem, Status
from rfcv.adapters.manifest import AdapterManifest
from rfcv.domains.rfc_protocol.adapter_view import to_vocabulary
from rfcv.domains.rfc_protocol.spec.oracle_compiler import OracleCompileError, compile_oracle
from rfcv.domains.rfc_protocol.spec.rbs import RbsSyntaxError, parse_rbs

TEMPLATE_KEYS = {"id", "requirement_types", "rfc_refs", "runner"}


def check_protocol_adapter(adapter_dir: Path, m: AdapterManifest) -> list[CheckItem]:
    items: list[CheckItem] = []
    try:
        vocab = to_vocabulary(m)
        vocab.signatures()
        items.append(CheckItem("form.vocabulary", Status.PASS, f"{len(vocab.events)} sự kiện"))
    except (ValueError, ValidationError) as exc:
        return [CheckItem("form.vocabulary", Status.FAIL, str(exc)[:500])]

    for f in sorted((adapter_dir / "templates").glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            ok = isinstance(data, dict) and set(cast(dict[str, object], data)) >= TEMPLATE_KEYS
            items.append(CheckItem(f"form.template:{f.name}", Status.PASS if ok else Status.FAIL))
        except yaml.YAMLError as exc:
            items.append(CheckItem(f"form.template:{f.name}", Status.FAIL, str(exc)[:200]))

    for f in sorted((adapter_dir / "examples").glob("*.rbs")):
        try:
            oracle = compile_oracle(parse_rbs(f.read_text(encoding="utf-8")), vocab)
            items.append(CheckItem(f"form.rbs_example:{f.name}", Status.PASS, f"{len(oracle.variants)} biến thể"))
        except (RbsSyntaxError, OracleCompileError) as exc:
            items.append(CheckItem(f"form.rbs_example:{f.name}", Status.FAIL, str(exc)[:300]))
    return items

"""Xuất SARIF 2.1.0 cho GitHub code scanning và IDE (thiết kế chính, mục 4.1).

Mỗi VIOLATION có vị trí mã thành một result: ruleId là định danh câu RFC, message là giải thích
đã qua Output gate, locations là vị trí T1, properties chứa nhãn, quy tắc và định danh bằng chứng.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from rfcv import __version__

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"


@dataclass(frozen=True)
class SarifFinding:
    spec_ref: str
    requirement_id: str
    label: str
    rule: str
    message: str
    file: str
    line_start: int
    line_end: int
    evidence_ids: tuple[str, ...]


def build_sarif(findings: Sequence[SarifFinding], rule_texts: Mapping[str, str]) -> dict[str, Any]:
    rules = [
        {"id": sid, "shortDescription": {"text": rule_texts.get(sid, sid)[:1000]}}
        for sid in sorted({f.spec_ref for f in findings})
    ]
    results = [
        {
            "ruleId": f.spec_ref,
            "level": "error",
            "message": {"text": f.message},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": f.file},
                        "region": {"startLine": f.line_start, "endLine": f.line_end},
                    }
                }
            ],
            "properties": {
                "requirement_id": f.requirement_id,
                "label": f.label,
                "verdict_rule": f.rule,
                "evidence_ids": list(f.evidence_ids),
            },
        }
        for f in findings
        if f.label == "VIOLATION"
    ]
    return {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [{"tool": {"driver": {"name": "rfcv", "version": __version__, "rules": rules}}, "results": results}],
    }

"""Báo cáo của một lần chạy: nạp từ thư mục lần chạy (trace, kho bằng chứng), tổng hợp độ phủ, xuất JSON, HTML, SARIF.

Mọi con số và nhãn lấy từ nhật ký và kho bằng chứng đã ghi, không tính lại bằng LLM; lời giải thích (nếu có) là bản đã qua
Output gate. Báo cáo không bao giờ sửa nhãn. Nội dung do LLM viết (giải thích) được escape khi đưa vào HTML.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment

from rfcv import __version__
from rfcv.core.trace import TraceLog
from rfcv.evidence.models import Evidence
from rfcv.evidence.store import EvidenceStore
from rfcv.ui.sarif import SarifFinding, build_sarif

LABELS = ("VIOLATION", "COMPLIANT", "NEEDS_REVIEW", "UNVERIFIABLE")
IN_PROGRESS = "IN_PROGRESS"  # có yêu cầu bắt đầu mà chưa có kết luận (lần chạy bị ngắt)
# Nhóm theo mức bắt buộc của BCP 14 (RFC 2119); từ khoá lạ vào nhóm "khác" để tổng các nhóm luôn bằng tổng số yêu cầu.
MODAL_CLASSES = {
    "MUST": "MUST",
    "MUST NOT": "MUST",
    "REQUIRED": "MUST",
    "SHALL": "MUST",
    "SHALL NOT": "MUST",
    "SHOULD": "SHOULD",
    "SHOULD NOT": "SHOULD",
    "RECOMMENDED": "SHOULD",
    "NOT RECOMMENDED": "SHOULD",
    "MAY": "MAY",
    "OPTIONAL": "MAY",
}
MODAL_ORDER = ("MUST", "SHOULD", "MAY", "khác")


@dataclass(frozen=True)
class Location:
    file: str
    symbol: str
    line_start: int
    line_end: int


@dataclass(frozen=True)
class RequirementRow:
    requirement_id: str
    spec_ref: str
    rtype: str
    modal: str
    label: str
    rule: str
    assurance: str | None
    stop_reason: str
    tokens: int
    evidence_ids: tuple[str, ...]
    location: Location | None = None
    explanation: str | None = None
    cited_evidence_ids: tuple[str, ...] = ()
    failed_cases: int = 0  # số T3 FAIL (kiểm thử cho thấy SUT sai)


@dataclass(frozen=True)
class RunReport:
    run_id: str
    adapter: str
    inputs_digest: str
    rows: tuple[RequirementRow, ...]
    rules_version: str = ""
    extra: dict[str, Any] = field(default_factory=dict[str, Any])


def modal_class(modal: str) -> str:
    return MODAL_CLASSES.get(modal, "khác")


def load_run(run_dir: Path) -> RunReport:
    """Dựng báo cáo từ thư mục lần chạy (`trace.db`, `evidence.db`, và `manifest.json` nếu có)."""
    if not (run_dir / "trace.db").is_file():
        raise FileNotFoundError(f"không có trace.db trong {run_dir}")
    started: dict[str, dict[str, Any]] = {}
    verdicts: dict[str, dict[str, Any]] = {}
    stops: dict[str, dict[str, Any]] = {}
    explanations: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for e in TraceLog(run_dir / "trace.db").events():
        rid = e.get("requirement_id")
        if not rid:
            continue
        payload: dict[str, Any] = e["payload"]
        match e["kind"]:
            case "requirement_start":
                if rid not in started:
                    order.append(rid)
                started[rid] = payload
            case "verdict":
                verdicts[rid] = payload
            case "stop":
                stops[rid] = payload
            case "explanation":
                explanations[rid] = payload
            case _:
                pass

    store = EvidenceStore(run_dir / "evidence.db")
    try:
        rows = tuple(
            _row(
                rid, started[rid], verdicts.get(rid), stops.get(rid), explanations.get(rid), store.for_requirement(rid)
            )
            for rid in order
        )
    finally:
        store.close()
    manifest: dict[str, Any] = {}
    if (run_dir / "manifest.json").is_file():
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    adapter: dict[str, Any] = manifest.get("adapter") or {}
    return RunReport(
        run_id=str(manifest.get("run_id") or run_dir.name),
        adapter=str(adapter.get("name", "")),
        inputs_digest=str(manifest.get("inputs_digest", "")),
        rows=rows,
        rules_version=next((str(v.get("rules_version", "")) for v in verdicts.values()), ""),
    )


def _row(
    rid: str,
    start: dict[str, Any],
    verdict: dict[str, Any] | None,
    stop: dict[str, Any] | None,
    explanation: dict[str, Any] | None,
    evidence: list[Evidence],
) -> RequirementRow:
    basis = tuple(str(i) for i in verdict["evidence_ids"]) if verdict else ()
    return RequirementRow(
        requirement_id=rid,
        spec_ref=str(start.get("spec_ref", "")),
        rtype=str(start.get("rtype", "")),
        modal=str(start.get("modal", "")),
        label=str(verdict["label"]) if verdict else IN_PROGRESS,
        rule=str(verdict["rule"]) if verdict else "",
        assurance=str(verdict["assurance"]) if verdict and verdict.get("assurance") else None,
        stop_reason=str(verdict["stop_reason"]) if verdict else "",
        tokens=_tokens(stop),
        evidence_ids=basis,
        location=_location(evidence, basis),
        explanation=str(explanation["text"]) if explanation else None,
        cited_evidence_ids=tuple(explanation.get("cited_evidence_ids", ())) if explanation else (),
        failed_cases=sum(
            1 for e in evidence if str(e.tier) == "T3" and str(getattr(e.payload, "outcome", "")) == "FAIL"
        ),
    )


def _tokens(stop: dict[str, Any] | None) -> int:
    used: dict[str, Any] = (stop or {}).get("used") or {}
    return int(used.get("tokens", 0))


def _location(evidence: list[Evidence], basis: tuple[str, ...]) -> Location | None:
    """Vị trí mã để chỉ cho người đọc: T1 trong căn cứ của nhãn, rồi T1 có khía cạnh MISMATCH, rồi T1 mới nhất."""
    t1 = [e for e in evidence if str(e.tier) == "T1" and getattr(e.payload, "file", "")]
    if not t1:
        return None

    def mismatched(e: Evidence) -> bool:
        return any(str(a.value) == "MISMATCH" for a in getattr(e.payload, "aspects", ()))

    pick = next((e for e in t1 if e.evidence_id in basis), None) or next(
        (e for e in reversed(t1) if mismatched(e)), t1[-1]
    )
    p = pick.payload
    return Location(str(p.file), str(p.symbol), int(p.line_start), int(p.line_end))  # type: ignore[attr-defined]


# ---- tổng hợp độ phủ ------------------------------------------------------------------------------------------------


def coverage(report: RunReport) -> dict[str, Any]:
    """Số yêu cầu theo nhãn, mức bảo đảm, mức bắt buộc, loại D và lý do UNVERIFIABLE. Mỗi nhóm chia hết tập yêu cầu."""
    rows = report.rows
    labels = (*LABELS, IN_PROGRESS)
    by_label = Counter(r.label for r in rows)
    by_modal: dict[str, Counter[str]] = {m: Counter() for m in MODAL_ORDER}
    for r in rows:
        by_modal[modal_class(r.modal)][r.label] += 1
    return {
        "total": len(rows),
        "by_label": {label: by_label.get(label, 0) for label in labels},
        "compliant_by_assurance": dict(Counter(r.assurance or "không rõ" for r in rows if r.label == "COMPLIANT")),
        "by_modal": {
            m: {label: c.get(label, 0) for label in labels} | {"tổng": c.total()} for m, c in by_modal.items()
        },
        "type_d": {
            "total": sum(1 for r in rows if r.rtype == "D"),
            "by_label": dict(Counter(r.label for r in rows if r.rtype == "D")),
        },
        "unverifiable_by_reason": dict(Counter(r.stop_reason or "không rõ" for r in rows if r.label == "UNVERIFIABLE")),
        "tokens": sum(r.tokens for r in rows),
    }


# ---- JSON -----------------------------------------------------------------------------------------------------------


def to_json(report: RunReport) -> dict[str, Any]:
    return {
        "run_id": report.run_id,
        "adapter": report.adapter,
        "inputs_digest": report.inputs_digest,
        "rules_version": report.rules_version,
        "coverage": coverage(report),
        "requirements": [
            {
                "requirement_id": r.requirement_id,
                "spec_ref": r.spec_ref,
                "type": r.rtype,
                "modal": r.modal,
                "label": r.label,
                "rule": r.rule,
                "assurance": r.assurance,
                "stop_reason": r.stop_reason,
                "evidence_ids": list(r.evidence_ids),
                "location": None
                if r.location is None
                else {
                    "file": r.location.file,
                    "symbol": r.location.symbol,
                    "lines": [r.location.line_start, r.location.line_end],
                },
                "explanation": r.explanation,
                "cited_evidence_ids": list(r.cited_evidence_ids),
            }
            for r in report.rows
        ],
    }


# ---- SARIF ----------------------------------------------------------------------------------------------------------


def to_sarif(report: RunReport) -> dict[str, Any]:
    """Mỗi VIOLATION có vị trí mã thành một kết quả; ghi rõ cả những VIOLATION chưa định vị được mã (không có trong SARIF)."""
    findings = [
        SarifFinding(
            spec_ref=r.spec_ref or r.requirement_id,
            requirement_id=r.requirement_id,
            label=r.label,
            rule=r.rule,
            message=r.explanation
            or f"{r.requirement_id}: kiểm thử cho thấy SUT không đúng yêu cầu ({r.failed_cases} ca FAIL, quy tắc {r.rule}).",
            file=r.location.file,
            line_start=r.location.line_start,
            line_end=r.location.line_end,
            evidence_ids=r.evidence_ids,
        )
        for r in report.rows
        if r.label == "VIOLATION" and r.location is not None
    ]
    sarif = build_sarif(findings, {})
    unlocated = [r.requirement_id for r in report.rows if r.label == "VIOLATION" and r.location is None]
    sarif["runs"][0]["properties"] = {
        "run_id": report.run_id,
        "violations_without_code_location": unlocated,
        "rfcv_version": __version__,
    }
    return sarif


# ---- HTML -----------------------------------------------------------------------------------------------------------

_HTML = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><title>rfcv · {{ report.run_id }}</title>
<style>
body{font:14px/1.5 system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}
table{border-collapse:collapse;margin:.5rem 0 1.5rem}td,th{border:1px solid #ccc;padding:.3rem .6rem;text-align:left;vertical-align:top}
th{background:#f3f3f3}.VIOLATION{background:#fde2e2}.COMPLIANT{background:#e1f5e1}.NEEDS_REVIEW{background:#fff3cd}
.UNVERIFIABLE{background:#e8e8e8}.IN_PROGRESS{background:#dbeafe}code{font-size:12px}.muted{color:#666}
</style></head><body>
<h1>Báo cáo kiểm chứng</h1>
<p class="muted">Lần chạy <code>{{ report.run_id }}</code> · adapter <code>{{ report.adapter or "?" }}</code> ·
bộ quy tắc <code>{{ report.rules_version[:19] }}</code> · {{ cov.total }} yêu cầu · {{ cov.tokens }} token</p>

<h2>Theo nhãn</h2>
<table><tr>{% for l, n in cov.by_label.items() %}<th>{{ l }}</th>{% endfor %}</tr>
<tr>{% for l, n in cov.by_label.items() %}<td class="{{ l }}">{{ n }}</td>{% endfor %}</tr></table>
{% if cov.compliant_by_assurance %}<p>COMPLIANT theo mức bảo đảm:
{% for a, n in cov.compliant_by_assurance.items() %}<b>{{ a }}</b> {{ n }}{% if not loop.last %}, {% endif %}{% endfor %}</p>{% endif %}

<h2>Theo mức bắt buộc</h2>
<table><tr><th></th>{% for l in labels %}<th>{{ l }}</th>{% endfor %}<th>tổng</th></tr>
{% for m, c in cov.by_modal.items() %}<tr><th>{{ m }}</th>{% for l in labels %}<td>{{ c[l] }}</td>{% endfor %}<td>{{ c["tổng"] }}</td></tr>{% endfor %}</table>
<p>Loại D (hành vi nội bộ): {{ cov.type_d.total }}{% for l, n in cov.type_d.by_label.items() %} · {{ l }} {{ n }}{% endfor %}.
{% if cov.unverifiable_by_reason %}UNVERIFIABLE theo lý do:
{% for r, n in cov.unverifiable_by_reason.items() %}{{ r }} {{ n }}{% if not loop.last %}, {% endif %}{% endfor %}.{% endif %}</p>

<h2>Từng yêu cầu</h2>
<table><tr><th>Yêu cầu</th><th>Câu RFC</th><th>Loại</th><th>Nhãn</th><th>Quy tắc</th><th>Vị trí mã</th><th>Giải thích</th></tr>
{% for r in report.rows %}<tr class="{{ r.label }}"><td>{{ r.requirement_id }}</td><td><code>{{ r.spec_ref }}</code><br>{{ r.modal }}</td>
<td>{{ r.rtype }}</td><td><b>{{ r.label }}</b>{% if r.assurance %}<br>{{ r.assurance }}{% endif %}</td><td>{{ r.rule }}</td>
<td>{% if r.location %}<code>{{ r.location.file }}:{{ r.location.line_start }}-{{ r.location.line_end }}</code><br>{{ r.location.symbol }}{% else %}–{% endif %}</td>
<td>{{ r.explanation or "(chưa có giải thích)" }}</td></tr>{% endfor %}</table>
<p class="muted">Nhãn do Verdict engine quyết định; lời giải thích đã qua Output gate và không đổi nhãn.</p>
</body></html>"""

_ENV = Environment(autoescape=True)


def to_html(report: RunReport) -> str:
    return _ENV.from_string(_HTML).render(report=report, cov=coverage(report), labels=(*LABELS, IN_PROGRESS))

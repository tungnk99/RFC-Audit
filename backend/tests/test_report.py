"""Báo cáo lần chạy (BL-31): nạp từ nhật ký và kho bằng chứng, tổng hợp độ phủ, xuất JSON, HTML, SARIF."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from helpers import t1, t3
from rfcv.core.trace import TraceLog
from rfcv.domains.rfc_protocol.payloads import AspectValue, Outcome
from rfcv.evidence.store import EvidenceStore
from rfcv.ui.report import IN_PROGRESS, LABELS, MODAL_ORDER, coverage, load_run, modal_class, to_html, to_json, to_sarif

RUN = "run-report"
# (id, câu RFC, loại, từ khoá, nhãn, quy tắc, assurance, lý do dừng)
REQS = [
    ("R-1", "RFC1§1#p1s1", "B", "MUST", "VIOLATION", "V2", None, "SUFFICIENT"),
    ("R-2", "RFC1§1#p2s1", "B", "MUST NOT", "COMPLIANT", "V5", "LINKED", "SUFFICIENT"),
    ("R-3", "RFC1§2#p1s1", "B", "SHOULD", "COMPLIANT", "V6", "BEHAVIORAL", "SUFFICIENT"),
    ("R-4", "RFC1§2#p2s1", "C", "MAY", "NEEDS_REVIEW", "V7", None, "SUFFICIENT"),
    ("R-5", "RFC1§3#p1s1", "D", "MUST", "UNVERIFIABLE", "V9", None, "BUDGET"),
    ("R-6", "RFC1§3#p2s1", "D", "SHALL", "UNVERIFIABLE", "V9", None, "INFEASIBLE"),
    ("R-7", "RFC1§3#p3s1", "B", "RECOMMENDED", "COMPLIANT", "V5", "LINKED", "SUFFICIENT"),
    ("R-8", "RFC1§4#p1s1", "A", "WEIRD KEYWORD", "COMPLIANT", "V6", "BEHAVIORAL", "SUFFICIENT"),
]
EXPLAIN = "SUT gửi <script>alert(1)</script> thay vì cảnh báo đúng; xem T3 và vị trí mã."


def build_run(root: Path, *, interrupted: bool = True) -> Path:
    run_dir = root / RUN
    run_dir.mkdir(parents=True)
    trace = TraceLog(run_dir / "trace.db")
    store = EvidenceStore(run_dir / "evidence.db")
    for rid, spec_ref, rtype, modal, label, rule, assurance, stop in REQS:
        trace.append(
            RUN,
            "requirement_start",
            {"round": 0, "rtype": rtype, "modal": modal, "spec_ref": spec_ref},
            requirement_id=rid,
        )
        ids: list[str] = []
        if label == "VIOLATION":
            ids.append(store.append(t3(requirement_id=rid, outcome=Outcome.FAIL, alert="decode_error")).evidence_id)
            store.append(t1(requirement_id=rid, reaction=AspectValue.MISMATCH, observed="send_alert(decode_error)"))
        elif label == "COMPLIANT":
            store.append(t1(requirement_id=rid))
        trace.append(RUN, "stop", {"round": 1, "reason": stop, "used": {"tokens": 1000}}, requirement_id=rid)
        verdict: dict[str, Any] = {
            "round": 1,
            "label": label,
            "rule": rule,
            "assurance": assurance,
            "modal": modal,
            "stop_reason": stop,
            "evidence_ids": ids,
            "rules_version": "sha256:rules",
        }
        trace.append(RUN, "verdict", verdict, requirement_id=rid)
        if label == "VIOLATION":
            trace.append(
                RUN,
                "explanation",
                {"label": label, "requirement_id": rid, "text": EXPLAIN, "cited_evidence_ids": ids},
                requirement_id=rid,
            )
    if interrupted:  # yêu cầu đã bắt đầu mà lần chạy bị ngắt trước khi có kết luận
        trace.append(
            RUN,
            "requirement_start",
            {"round": 0, "rtype": "B", "modal": "MUST", "spec_ref": "RFC1§9#p1s1"},
            requirement_id="R-9",
        )
    store.close()
    return run_dir


def test_every_grouping_partitions_the_requirement_set(tmp_path: Path) -> None:
    """Tổng các nhóm bằng tổng số yêu cầu: theo nhãn, và theo mức bắt buộc (từ khoá lạ vào nhóm "khác")."""
    cov = coverage(load_run(build_run(tmp_path)))
    assert cov["total"] == len(REQS) + 1
    assert sum(cov["by_label"].values()) == cov["total"]
    assert sum(g["tổng"] for g in cov["by_modal"].values()) == cov["total"]
    for modal, group in cov["by_modal"].items():
        assert sum(group[label] for label in (*LABELS, IN_PROGRESS)) == group["tổng"], modal
    assert cov["by_label"]["VIOLATION"] == 1 and cov["by_label"][IN_PROGRESS] == 1
    assert [m for m in MODAL_ORDER if m in cov["by_modal"]] == list(MODAL_ORDER)


def test_coverage_splits_by_assurance_modal_type_d_and_unverifiable_reason(tmp_path: Path) -> None:
    cov = coverage(load_run(build_run(tmp_path)))
    assert cov["compliant_by_assurance"] == {"LINKED": 2, "BEHAVIORAL": 2}
    assert cov["by_modal"]["MUST"]["tổng"] == 5  # R-1, R-2 (MUST NOT), R-5, R-6 (SHALL), và R-9 đang chạy
    assert (
        cov["by_modal"]["SHOULD"]["tổng"] == 2
        and cov["by_modal"]["MAY"]["tổng"] == 1
        and cov["by_modal"]["khác"]["tổng"] == 1
    )
    assert cov["type_d"] == {"total": 2, "by_label": {"UNVERIFIABLE": 2}}
    assert cov["unverifiable_by_reason"] == {"BUDGET": 1, "INFEASIBLE": 1}
    assert cov["tokens"] == 1000 * len(REQS)


def test_modal_classes_follow_bcp14() -> None:
    assert [modal_class(m) for m in ("MUST NOT", "SHALL NOT", "REQUIRED")] == ["MUST"] * 3
    assert [modal_class(m) for m in ("SHOULD NOT", "RECOMMENDED", "NOT RECOMMENDED")] == ["SHOULD"] * 3
    assert [modal_class(m) for m in ("MAY", "OPTIONAL", "")] == ["MAY", "MAY", "khác"]


def test_a_violation_row_carries_its_location_explanation_and_failed_cases(tmp_path: Path) -> None:
    report = load_run(build_run(tmp_path))
    row = next(r for r in report.rows if r.requirement_id == "R-1")
    assert row.location is not None and row.location.symbol == "GetRecordHeader"
    assert row.explanation == EXPLAIN and row.failed_cases == 1 and row.spec_ref == "RFC1§1#p1s1"
    assert next(r for r in report.rows if r.requirement_id == "R-9").label == IN_PROGRESS


def test_sarif_has_only_violations_with_a_location_and_lists_the_rest(tmp_path: Path) -> None:
    sarif = to_sarif(load_run(build_run(tmp_path)))
    assert sarif["version"] == "2.1.0" and sarif["$schema"].endswith("sarif-2.1.0.json")
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "rfcv" and len(run["results"]) == 1
    result = run["results"][0]
    assert result["ruleId"] == "RFC1§1#p1s1" and result["level"] == "error" and result["message"]["text"] == EXPLAIN
    region = result["locations"][0]["physicalLocation"]["region"]
    assert region["startLine"] <= region["endLine"] and result["properties"]["requirement_id"] == "R-1"
    assert {r["id"] for r in run["tool"]["driver"]["rules"]} == {"RFC1§1#p1s1"}  # mọi ruleId đều có định nghĩa
    assert run["properties"]["violations_without_code_location"] == []


def test_html_escapes_llm_text_and_shows_every_requirement(tmp_path: Path) -> None:
    html = to_html(load_run(build_run(tmp_path)))
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    for rid, *_ in REQS:
        assert rid in html
    assert "COMPLIANT" in html and "Nhãn do Verdict engine quyết định" in html


def test_json_report_round_trips_and_mirrors_the_coverage(tmp_path: Path) -> None:
    report = load_run(build_run(tmp_path))
    data = json.loads(json.dumps(to_json(report), ensure_ascii=False))
    assert data["coverage"] == coverage(report) and len(data["requirements"]) == len(REQS) + 1
    assert data["requirements"][0]["location"]["lines"] == [812, 817] or data["requirements"][0]["location"]["lines"]


def test_a_directory_without_a_trace_is_rejected(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(FileNotFoundError):
        load_run(tmp_path)


# ---------------------------------------------------------------- lệnh `rfcv report` và `rfcv status`


def test_report_command_writes_each_format_from_a_run_directory(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from rfcv.ui.cli import app

    build_run(tmp_path)
    runner = CliRunner()
    as_json = runner.invoke(app, ["report", RUN, "--runs", str(tmp_path), "--format", "json"])
    assert as_json.exit_code == 0 and json.loads(as_json.output)["coverage"]["total"] == len(REQS) + 1
    sarif = runner.invoke(app, ["report", RUN, "--runs", str(tmp_path), "--format", "sarif"])
    assert sarif.exit_code == 0 and len(json.loads(sarif.output)["runs"][0]["results"]) == 1
    target = tmp_path / "report.html"
    html = runner.invoke(app, ["report", RUN, "--runs", str(tmp_path), "--out", str(target)])
    assert html.exit_code == 0 and "Báo cáo kiểm chứng" in target.read_text(encoding="utf-8")
    assert runner.invoke(app, ["report", RUN, "--runs", str(tmp_path), "--format", "pdf"]).exit_code == 2
    assert runner.invoke(app, ["report", "run-khong-co", "--runs", str(tmp_path)]).exit_code == 2


def test_status_reports_progress_and_token_cost_without_inventing_usd(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from rfcv.ui.cli import app

    run_dir = build_run(tmp_path)
    trace = TraceLog(run_dir / "trace.db")
    trace.append(RUN, "role_run", {"role": "planner", "tokens": 700, "tool_calls": 0}, requirement_id="R-1")
    trace.append(RUN, "role_run", {"role": "code_reader", "tokens": 300, "tool_calls": 9}, requirement_id="R-1")
    data = json.loads(CliRunner().invoke(app, ["status", RUN, "--runs", str(tmp_path), "--json"]).output)
    assert data["requirements"] == {"started": len(REQS) + 1, "decided": len(REQS), "in_progress": 1}
    assert data["tokens"] == {"total": 1000, "by_role": {"planner": 700, "code_reader": 300}}
    assert data["tool_calls"]["total"] == 9 and data["usd"] is None  # USD cần bảng giá (BL-76), không đoán
    text = CliRunner().invoke(app, ["status", RUN, "--runs", str(tmp_path)]).output
    assert f"{len(REQS)}/{len(REQS) + 1} đã có kết luận" in text and "USD: chưa tính" in text

"""Phân tích kết luận của một lần chạy thành dạng người đọc hiểu được: yêu cầu nói gì, mã vi phạm ở đâu, kiểm thử quan sát
được gì so với kỳ vọng, và vì sao quy tắc kết luận áp dụng.

Tất định và chỉ đọc: mọi con số lấy từ bằng chứng đã ghi (T1 vị trí mã, T3 kết quả kiểm thử, liên kết độ phủ) và từ trace
(đoạn mã agent đã đọc). Không gọi LLM và không suy diễn ngoài dữ liệu đó. Đoạn mã là dữ liệu KHÔNG TIN CẬY: giao diện phải thoát HTML.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

from rfcv.api import runstore
from rfcv.api.catalog import RBS_HEAD

_NUMBERED = re.compile(r"^\s*(\d+) (.*)$")
_FILE_HEAD = re.compile(r"tool=(?:read_range|read_function)\s+(\S+)")
_RBS_KEYS = ("actor", "state", "trigger", "expect", "forbid", "variants", "accept_alternatives")

RULE_TEXT: dict[str, str] = {
    "V0": "Kết quả kiểm thử không nhất quán giữa các lần chạy hoặc môi trường, nên chưa kết luận được.",
    "V1": "Chưa có nhân chứng dương (bản tham chiếu độc lập chạy PASS cùng kịch bản), nên một ca FAIL chưa đủ tin cậy.",
    "V2": "Có ca kiểm thử thất bại hợp lệ: ổn định khi chạy lặp, nhất quán giữa môi trường, và các bản tham chiếu độc lập đều PASS cùng kịch bản. Lỗi nằm ở SUT.",
    "V3": "Vi phạm suy ra từ máy trạng thái học được.",
    "V4": "Có nhánh nghi vấn trên đường xử lý, cần người xem xét.",
    "V5": "Mọi biến thể bắt buộc đều PASS và kết quả kiểm thử được liên kết độ phủ với đúng đoạn mã đã định vị (T1↔T3).",
    "V6": "Mọi biến thể bắt buộc đều PASS, nhưng chưa liên kết được với mã nguồn (chỉ bảo đảm theo hành vi).",
    "V7": "Bằng chứng mã và kiểm thử mâu thuẫn nhau hoặc cổng kiểm chứng từ chối, cần người xem xét.",
    "V8": "Kết luận từ phân tích tĩnh.",
    "V9": "Chưa đủ bằng chứng để kết luận.",
}


def parse_rbs(text: str) -> dict[str, Any]:
    """Đọc các dòng của RBS thành trường; bỏ chú thích sau dấu #."""
    out: dict[str, Any] = {}
    m = RBS_HEAD.search(text)
    if m:
        out.update(id=m.group(1), source=m.group(2), modal=m.group(3), rtype=m.group(4))
    for line in text.splitlines():
        body = line.split("#", 1)[0].strip()
        key, _, rest = body.partition(" ")
        if key in _RBS_KEYS and rest.strip():
            out[key] = rest.strip()
    return out


def code_lines(run_dir: Path) -> dict[str, dict[int, str]]:
    """Dòng mã mà agent đã đọc (từ kết quả công cụ trong trace): tệp -> số dòng -> nội dung."""
    files: dict[str, dict[int, str]] = {}
    for e in runstore.kind_events(run_dir, "tool_call"):
        payload: dict[str, Any] = e["payload"] or {}
        out = payload.get("output")
        if not isinstance(out, str):
            continue
        head = _FILE_HEAD.search(out.split("\n", 1)[0])
        if not head:
            continue
        bucket = files.setdefault(head.group(1), {})
        for line in out.split("\n")[1:]:
            m = _NUMBERED.match(line)
            if m:
                bucket[int(m.group(1))] = m.group(2)
    return files


def _evidence(run_dir: Path) -> list[dict[str, Any]]:
    db = run_dir / "evidence.db"
    if not db.is_file():
        return []
    out: list[dict[str, Any]] = []
    with runstore.ro(db) as c:
        for seq, eid, body in c.execute("SELECT seq, evidence_id, body FROM evidence ORDER BY seq"):
            rec: dict[str, Any] = json.loads(body)
            out.append({"seq": seq, "id": eid, "rec": rec, "p": cast("dict[str, Any]", rec.get("payload") or {})})
    return out


def _expected(rbs: dict[str, Any], side: str) -> str:
    if side == "trigger":
        return str(rbs.get("expect", "?"))
    return "không cảnh báo, không đóng kết nối (đầu vào hợp lệ)"


def _observed(o: dict[str, Any]) -> str:
    alert, closed = o.get("alert", "none"), o.get("closed")
    if alert == "none" and not closed:
        return "không phản ứng"
    return (f"send_alert({alert})" if alert != "none" else "không cảnh báo") + (
        ", đóng kết nối" if closed else ", KHÔNG đóng kết nối"
    )


def _why(rbs: dict[str, Any], case: dict[str, Any]) -> str | None:
    """Một câu nêu chỗ lệch giữa kỳ vọng và quan sát cho ca FAIL."""
    exp = str(rbs.get("expect", ""))
    want = re.search(r"send_alert\((\w+)\)", exp)
    o: dict[str, Any] = case["observed"]
    if case["side"] == "trigger":
        if o.get("alert", "none") == "none":
            return "SUT không gửi cảnh báo nào"
        if want and o["alert"] != want.group(1):
            return f"SUT gửi cảnh báo sai: {o['alert']} thay vì {want.group(1)}"
        if "close" in exp and not o.get("closed"):
            return "SUT không đóng kết nối sau cảnh báo"
        return "hành vi không khớp kỳ vọng"
    return "SUT phản ứng với đầu vào hợp lệ (từ chối nhầm)"


def _snippet(loc: dict[str, Any], lines: dict[int, str], hits: set[int]) -> list[dict[str, Any]]:
    ls, le = int(loc["line_start"]), int(loc["line_end"])
    flag: dict[int, str] = {}
    aspects: list[dict[str, Any]] = loc.get("aspects") or []
    for a in aspects:
        span: list[int] = a.get("lines") or [0, 0]
        lo, hi = span[0], span[1]
        for n in range(int(lo), int(hi) + 1):
            if flag.get(n) != "mismatch":
                flag[n] = "mismatch" if a.get("value") == "MISMATCH" else "match"
    return [
        {"n": n, "text": lines[n], "flag": flag.get(n), "hit": n in hits, "inside": ls <= n <= le}
        for n in range(max(1, ls - 3), le + 4)
        if n in lines
    ]


def analyze(run_dir: Path, adapters_dir: Path | None = None) -> list[dict[str, Any]]:
    verdicts: dict[str, dict[str, Any]] = {}
    for e in runstore.kind_events(run_dir, "verdict"):
        verdicts[str(e["requirement_id"])] = e["payload"]
    stops = {str(e["requirement_id"]): e["payload"] for e in runstore.kind_events(run_dir, "stop")}
    rbs_all: dict[str, dict[str, Any]] = {}
    for f in sorted((run_dir / "requirements").glob("*.rbs")) if (run_dir / "requirements").is_dir() else []:
        rbs = parse_rbs(f.read_text(encoding="utf-8"))
        rbs_all[str(rbs.get("id", f.stem))] = rbs
    if adapters_dir is not None:  # lần chạy bằng CLI không có bản sao RBS: lấy từ adapter
        for f in sorted(adapters_dir.glob("*/examples/*.rbs")):
            rbs = parse_rbs(f.read_text(encoding="utf-8"))
            rbs_all.setdefault(str(rbs.get("id", f.stem)), rbs)
    evidence = _evidence(run_dir)
    code = code_lines(run_dir)
    out: list[dict[str, Any]] = []
    for rid, v in verdicts.items():
        rbs = rbs_all.get(rid, {})
        decisive = set(cast("list[str]", v.get("evidence_ids") or []))
        mine = [x for x in evidence if x["rec"].get("requirement_id") == rid]
        # vị trí mã: bằng chứng T1 `location` (lấy bản mới nhất)
        locs = [x for x in mine if x["p"].get("kind") == "location"]
        link = next((x for x in reversed(mine) if x["p"].get("kind") == "coverage_link"), None)
        hits: set[int] = set(cast("list[int]", link["p"].get("lines_hit") or [])) if link else set()
        location: dict[str, Any] | None = None
        if locs:
            lp = locs[-1]["p"]
            location = {
                "evidence_id": locs[-1]["id"],
                "polarity": locs[-1]["rec"].get("polarity"),
                "file": lp.get("file"),
                "symbol": lp.get("symbol"),
                "line_start": lp.get("line_start"),
                "line_end": lp.get("line_end"),
                "check_kind": lp.get("check_kind"),
                "finding": lp.get("finding"),
                "call_path": lp.get("call_path") or [],
                "aspects": lp.get("aspects") or [],
                "unexplored": lp.get("unexplored") or [],
                "snippet": _snippet(lp, code.get(str(lp.get("file")), {}), hits),
            }
        # kiểm thử T3
        cases: list[dict[str, Any]] = []
        for x in mine:
            p = x["p"]
            if p.get("kind") != "scenario_result":
                continue
            case: dict[str, Any] = {
                "evidence_id": x["id"],
                "variant": p.get("variant"),
                "variant_class": p.get("variant_class"),
                "side": p.get("side"),
                "params": p.get("params") or {},
                "outcome": p.get("outcome"),
                "observed": p.get("observed") or {},
                "runs": p.get("runs"),
                "consistent": p.get("consistent"),
                "environments_consistent": p.get("environments_consistent"),
                "witness": p.get("witness") or {},
                "decisive": x["id"] in decisive,
                "reason": p.get("reason"),
            }
            case["observed_text"] = _observed(case["observed"])
            case["expected_text"] = _expected(rbs, str(case["side"]))
            case["why"] = _why(rbs, case) if case["outcome"] == "FAIL" else None
            cases.append(case)
        by_side: dict[str, dict[str, int]] = {}
        for c in cases:
            s = by_side.setdefault(str(c["side"]), {})
            s[str(c["outcome"])] = s.get(str(c["outcome"]), 0) + 1
        cases.sort(key=lambda c: (c["outcome"] != "FAIL", not c["decisive"], str(c["variant"])))
        out.append(
            {
                "requirement_id": rid,
                "label": v.get("label"),
                "rule": v.get("rule"),
                "rule_text": RULE_TEXT.get(str(v.get("rule")), ""),
                "assurance": v.get("assurance"),
                "stop_reason": v.get("stop_reason") or (stops.get(rid) or {}).get("reason"),
                "modal": v.get("modal") or rbs.get("modal"),
                "rbs": rbs,
                "location": location,
                "coverage": {"linked": bool(link and link["p"].get("linked")), "lines_hit": sorted(hits)},
                "tests": {"total": len(cases), "by_side": by_side, "cases": cases},
                "decisive": sorted(decisive),
                "evidence_total": len(mine),
            }
        )
    return out


# ---- mã nguồn có chú thích bằng chứng -----------------------------------------------------------------------------------

ASPECT_VN = {
    "CONDITION": "Điều kiện kích hoạt",
    "THRESHOLD": "Ngưỡng",
    "REACTION": "Phản ứng",
    "ORDER_STATE": "Thứ tự / trạng thái",
    "EFFECT": "Tác động",
}
MAX_FILE_BYTES = 2_000_000


def build_annotations(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chú thích gắn vào dòng mã, dựng từ bằng chứng: vị trí (T1), từng khía cạnh khớp/lệch, và kết luận dựa trên chúng."""
    out: list[dict[str, Any]] = []
    for f in findings:
        loc = f.get("location")
        if not loc:
            continue
        rbs: dict[str, Any] = f.get("rbs") or {}
        want = re.search(r"send_alert\((\w+)\)", str(rbs.get("expect", "")))
        thr = re.search(r"(\d+)", str(rbs.get("trigger", "")))
        base = {
            "file": loc["file"],
            "requirement_id": f["requirement_id"],
            "tier": "T1",
            "evidence_id": loc["evidence_id"],
            "produced_by": "schema_gate",
        }
        out.append(
            {
                **base,
                "line_start": loc["line_start"],
                "line_end": loc["line_end"],
                "severity": "info",
                "kind": "location",
                "title": f"Đoạn mã thực hiện {f['requirement_id']}",
                "detail": f"Agent code_reader định vị {loc['symbol'] or ''} ({loc['check_kind'] or 'kiểm tra'}); Schema gate xác nhận vị trí có thật, dòng đã hiển thị và được biên dịch.",
            }
        )
        for a in loc["aspects"]:
            lo, hi = (a.get("lines") or [loc["line_start"], loc["line_end"]])[:2]
            bad = a.get("value") == "MISMATCH"
            expected = (
                f"send_alert({want.group(1)})"
                if a["aspect"] == "REACTION" and want
                else (thr.group(1) if a["aspect"] == "THRESHOLD" and thr else None)
            )
            detail = f"Mã làm: {a.get('observed')}" if a.get("observed") is not None else ""
            if expected:
                detail += f"{'; ' if detail else ''}RFC đòi: {expected}"
            out.append(
                {
                    **base,
                    "line_start": lo,
                    "line_end": hi,
                    "severity": "bad" if bad else "ok",
                    "kind": "aspect",
                    "title": f"{ASPECT_VN.get(a['aspect'], a['aspect'])}: {'LỆCH so với đặc tả' if bad else 'khớp đặc tả'}",
                    "detail": detail,
                    "aspect": a["aspect"],
                }
            )
            if bad:
                out.append(
                    {
                        **base,
                        "line_start": lo,
                        "line_end": hi,
                        "severity": "bad",
                        "kind": "verdict",
                        "tier": "T3",
                        "produced_by": "verdict_engine",
                        "title": f"Dẫn tới kết luận {f['label']} (quy tắc {f['rule']})",
                        "detail": "Kiểm thử hộp đen cho cùng kết quả: "
                        + ", ".join(
                            f"{s}: " + "/".join(f"{o} {n}" for o, n in c.items())
                            for s, c in f["tests"]["by_side"].items()
                        ),
                    }
                )
    out.sort(key=lambda a: (str(a["file"]), int(a["line_start"]), int(a["line_end"])))
    return out

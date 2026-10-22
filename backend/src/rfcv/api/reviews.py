"""Vòng phản hồi của con người: nhận định của Reviewer về kết luận của AI, hàng đợi duyệt, thống kê đồng thuận người–AI.

Theo thiết kế (BR3): nhãn của hệ thống KHÔNG bao giờ bị sửa; nhận định của Reviewer là bản ghi riêng, chỉ ghi thêm, lưu trong bảng
`reviews` của Evidence store của chính lần chạy đó (có trigger chặn sửa/xoá). Người duyệt chọn nhãn và bắt buộc ghi lý do khi không
đồng ý. Ngoài nhãn còn ghi nguyên nhân (từ một bảng phân loại cố định), cờ trên từng bằng chứng và đánh giá từng agent, để phản hồi
đo được và truy ngược được tới đúng bằng chứng, quy tắc, phiên bản quy tắc.

Danh tính người duyệt do người dùng tự khai (giao diện chưa có đăng nhập), nên bản ghi mang tên khai báo chứ không phải danh tính đã xác thực.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from rfcv.api import runstore
from rfcv.api.runs import ACTIVE, RunManager

LABELS = ("COMPLIANT", "VIOLATION", "NEEDS_REVIEW")
CAUSES: dict[str, str] = {
    "false_positive": "Dương tính giả: mã hoặc SUT thực ra đúng, hệ thống kết luận vi phạm",
    "false_negative": "Bỏ sót: có vi phạm mà hệ thống không thấy hoặc kết luận tuân thủ",
    "bad_scenario": "Kịch bản kiểm thử sai hoặc không đại diện",
    "bad_oracle": "Oracle/RBS dịch sai từ câu RFC",
    "wrong_location": "Định vị mã sai: không phải đoạn thực hiện yêu cầu",
    "weak_evidence": "Bằng chứng chưa đủ để kết luận",
    "env_issue": "Môi trường lỗi hoặc SUT không ổn định",
    "rfc_ambiguity": "Câu RFC mơ hồ, có nhiều cách hiểu",
    "other": "Lý do khác (ghi rõ ở phần lý do)",
}
EVIDENCE_FLAGS = {"key": "Bằng chứng then chốt", "wrong": "Bằng chứng sai", "irrelevant": "Không liên quan"}
SAMPLE_PERCENT = 10


class EvidenceFlag(BaseModel):
    evidence_id: str = Field(min_length=8, max_length=100)
    flag: Literal["key", "wrong", "irrelevant"]
    note: str = Field(default="", max_length=500)


class AgentFeedback(BaseModel):
    role: str = Field(min_length=1, max_length=60)
    rating: Literal["good", "bad"]
    note: str = Field(default="", max_length=500)
    msg_id: str | None = Field(default=None, max_length=40)


class ReviewIn(BaseModel):
    requirement_id: str = Field(min_length=1, max_length=80)
    reviewer: str = Field(default="", max_length=60, description="Bỏ qua khi bật đăng nhập: máy chủ lấy từ phiên")
    decision: Literal["agree", "disagree", "unsure"]
    label: str | None = None
    reason: str = Field(default="", max_length=4000)
    causes: list[str] = Field(default_factory=list, max_length=9)
    evidence_flags: list[EvidenceFlag] = Field(default_factory=lambda: list[EvidenceFlag](), max_length=200)
    agent_feedback: list[AgentFeedback] = Field(default_factory=lambda: list[AgentFeedback](), max_length=50)

    @field_validator("reviewer", "reason")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _rules(self) -> ReviewIn:
        bad = [c for c in self.causes if c not in CAUSES]
        if bad:
            raise ValueError(f"nguyên nhân không có trong bảng phân loại: {', '.join(bad)}")
        if self.decision == "disagree":
            if self.label not in LABELS:
                raise ValueError("không đồng ý thì phải chọn nhãn đúng theo bạn (COMPLIANT | VIOLATION | NEEDS_REVIEW)")
            if len(self.reason) < 10:
                raise ValueError("không đồng ý thì bắt buộc ghi lý do (từ 10 ký tự)")
            if not self.causes:
                raise ValueError("không đồng ý thì chọn ít nhất một nguyên nhân")
        if self.decision == "unsure" and len(self.reason) < 5:
            raise ValueError("chưa chắc thì ghi rõ cần thêm gì để quyết định")
        if self.label is not None and self.label not in LABELS:
            raise ValueError("nhãn không hợp lệ")
        return self


class ReviewError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


# ---- đọc ---------------------------------------------------------------------------------------------------------


def _verdicts(run_dir: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for e in runstore.kind_events(run_dir, "verdict"):
        out[str(e["requirement_id"])] = e["payload"]
    return out


def read_reviews(run_dir: Path) -> list[dict[str, Any]]:
    db = run_dir / "evidence.db"
    if not db.is_file():
        return []
    with runstore.ro(db) as c:
        try:
            rows = c.execute("SELECT seq, requirement_id, body FROM reviews ORDER BY seq").fetchall()
        except Exception:  # kho cũ chưa có bảng reviews
            return []
    out: list[dict[str, Any]] = []
    for seq, req, body in rows:
        rec: dict[str, Any] = json.loads(body)
        out.append({**rec, "seq": seq, "requirement_id": req})
    return out


def latest_per_reviewer(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mỗi người duyệt, với mỗi yêu cầu, chỉ tính nhận định mới nhất (các bản cũ vẫn nằm trong kho)."""
    last: dict[tuple[str, str], dict[str, Any]] = {}
    for r in reviews:
        last[(str(r["requirement_id"]), str(r.get("reviewer")))] = r
    return list(last.values())


def state_of(reviews: list[dict[str, Any]]) -> str:
    cur = latest_per_reviewer(reviews)
    if not cur:
        return "pending"
    decisions = {r.get("decision") for r in cur}
    return "disputed" if "disagree" in decisions else "unsure" if "unsure" in decisions else "agreed"


def in_sample(run_id: str, requirement_id: str) -> bool:
    """Mẫu kiểm tra 10% chọn tất định theo hash (cùng lần chạy thì luôn cùng kết quả, không ai chọn tay)."""
    h = hashlib.sha256(f"{run_id}/{requirement_id}".encode()).digest()
    return int.from_bytes(h[:4], "big") % 100 < SAMPLE_PERCENT


def _reason(label: str, rule: str, sampled: bool) -> str:
    if label == "NEEDS_REVIEW":
        return "needs_review"
    if label == "VIOLATION":
        return "violation_confirm"
    return "sample" if sampled else "optional"


def queue(m: RunManager) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for r in m.list_runs(10_000):
        if r["status"] in ACTIVE:
            continue
        d = m.run_dir(r["run_id"])
        if d is None:
            continue
        reviews = read_reviews(d)
        for rid, v in _verdicts(d).items():
            mine = [x for x in reviews if x["requirement_id"] == rid]
            cur = latest_per_reviewer(mine)
            last = max(mine, key=lambda x: x.get("ts", 0), default=None)
            sampled = in_sample(r["run_id"], rid)
            items.append(
                {
                    "run_id": r["run_id"],
                    "requirement_id": rid,
                    "adapter": r["spec"].get("adapter"),
                    "mode": r["spec"].get("mode"),
                    "label": v.get("label"),
                    "rule": v.get("rule"),
                    "assurance": v.get("assurance"),
                    "finished_at": r.get("ended_at") or r["created_at"],
                    "state": state_of(mine),
                    "reviews": len(cur),
                    "sampled": sampled,
                    "why": _reason(str(v.get("label")), str(v.get("rule")), sampled),
                    "last": {
                        "reviewer": last.get("reviewer"),
                        "decision": last.get("decision"),
                        "label": last.get("label"),
                        "ts": last.get("ts"),
                    }
                    if last
                    else None,
                }
            )
    order = {"needs_review": 0, "violation_confirm": 1, "sample": 2, "optional": 3}
    items.sort(key=lambda i: (order[i["why"]], i["state"] != "pending", -float(i["finished_at"] or 0)))
    return items


# ---- ghi ---------------------------------------------------------------------------------------------------------


def submit(m: RunManager, run_id: str, rin: ReviewIn) -> dict[str, Any]:
    d = m.run_dir(run_id)
    rec = m.record(run_id)
    if not rin.reviewer:
        raise ReviewError(422, "thiếu người duyệt")
    if d is None or rec is None:
        raise ReviewError(404, "không có lần chạy này")
    if rec["status"] in ACTIVE:
        raise ReviewError(409, "lần chạy đang diễn ra; duyệt sau khi kết thúc")
    verdict = _verdicts(d).get(rin.requirement_id)
    if verdict is None:
        raise ReviewError(404, f"yêu cầu {rin.requirement_id} chưa có kết luận trong lần chạy này")
    if rin.evidence_flags:
        known = {x["evidence_id"] for x in runstore.evidence(d, rin.requirement_id)}
        unknown = [f.evidence_id for f in rin.evidence_flags if f.evidence_id not in known]
        if unknown:
            raise ReviewError(422, f"bằng chứng không thuộc yêu cầu này: {unknown[0][:20]}…")
    system_label = str(verdict.get("label"))
    body: dict[str, Any] = {
        "review_id": f"rv-{uuid.uuid4().hex[:10]}",
        "ts": time.time(),
        "reviewer": rin.reviewer,
        "decision": rin.decision,
        "label": system_label if rin.decision == "agree" else rin.label,
        "reason": rin.reason,
        "causes": rin.causes,
        "evidence_flags": [f.model_dump() for f in rin.evidence_flags],
        "agent_feedback": [a.model_dump() for a in rin.agent_feedback],
        "system": {
            "label": system_label,
            "rule": verdict.get("rule"),
            "assurance": verdict.get("assurance"),
            "rules_version": verdict.get("rules_version"),
        },
        "run_id": run_id,
        "adapter": rec["spec"].get("adapter"),
        "mode": rec["spec"].get("mode"),
        "identity": "tự khai, chưa xác thực",
    }
    from rfcv.evidence.store import EvidenceStore  # nhập muộn: chỉ khi ghi

    store = EvidenceStore(d / "evidence.db")
    try:
        store.record_review(rin.requirement_id, body)
    finally:
        store.close()
    return body


# ---- thống kê ----------------------------------------------------------------------------------------------------


def _all_current(m: RunManager) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in m.list_runs(10_000):
        d = m.run_dir(r["run_id"])
        if d is None:
            continue
        out.extend({**x, "run_id": r["run_id"]} for x in latest_per_reviewer(read_reviews(d)))
    return out


def summary(m: RunManager) -> dict[str, Any]:
    cur = _all_current(m)
    q = queue(m)
    decided = [r for r in cur if r["decision"] in ("agree", "disagree")]
    agree = sum(r["decision"] == "agree" for r in decided)
    matrix: Counter[tuple[str, str]] = Counter((str(r["system"]["label"]), str(r["label"])) for r in decided)
    by_rule: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "agree": 0})
    causes: Counter[str] = Counter()
    ratings: dict[str, dict[str, int]] = defaultdict(lambda: {"good": 0, "bad": 0})
    flags: Counter[str] = Counter()
    for r in decided:
        b = by_rule[str(r["system"]["rule"])]
        b["n"] += 1
        b["agree"] += r["decision"] == "agree"
    for r in cur:
        causes.update(r.get("causes") or [])
        ef: list[dict[str, Any]] = r.get("evidence_flags") or []
        flags.update(str(f["flag"]) for f in ef)
        af: list[dict[str, Any]] = r.get("agent_feedback") or []
        for a in af:
            ratings[str(a["role"])][str(a["rating"])] += 1
    need = [i for i in q if i["why"] == "needs_review"]
    samp = [i for i in q if i["why"] == "sample"]
    viol = [i for i in q if i["why"] == "violation_confirm"]

    def done(xs: list[dict[str, Any]]) -> int:
        return sum(x["state"] != "pending" for x in xs)

    return {
        "reviews": len(cur),
        "decided": len(decided),
        "agree": agree,
        "disagree": len(decided) - agree,
        "unsure": sum(r["decision"] == "unsure" for r in cur),
        "agreement_rate": agree / len(decided) if decided else None,
        "matrix": [{"system": s, "human": h, "n": n} for (s, h), n in sorted(matrix.items())],
        "by_rule": [{"rule": k, **v} for k, v in sorted(by_rule.items())],
        "causes": [{"cause": k, "label": CAUSES.get(k, k), "n": n} for k, n in causes.most_common()],
        "agent_ratings": [{"role": k, **v} for k, v in sorted(ratings.items())],
        "evidence_flags": [{"flag": k, "label": EVIDENCE_FLAGS[k], "n": n} for k, n in flags.most_common()],
        "coverage": {
            "needs_review": {"total": len(need), "done": done(need)},
            "violation_confirm": {"total": len(viol), "done": done(viol)},
            "sample": {"total": len(samp), "done": done(samp)},
        },
        "pending": sum(
            1 for i in q if i["why"] in ("needs_review", "violation_confirm", "sample") and i["state"] == "pending"
        ),
        "disputes": [
            {
                "run_id": r["run_id"],
                "requirement_id": r["requirement_id"],
                "reviewer": r["reviewer"],
                "system": r["system"]["label"],
                "human": r["label"],
                "rule": r["system"]["rule"],
                "causes": r.get("causes"),
                "reason": r.get("reason"),
                "ts": r.get("ts"),
            }
            for r in sorted(decided, key=lambda x: -float(x.get("ts", 0)))
            if r["decision"] == "disagree"
        ][:50],
    }


def export_jsonl(m: RunManager) -> str:
    """Tập phản hồi để đánh giá/hồi quy: mỗi dòng là một nhận định kèm ngữ cảnh đủ để tái hiện (bản kê, RBS, kết luận)."""
    lines: list[str] = []
    for r in m.list_runs(10_000):
        d = m.run_dir(r["run_id"])
        if d is None:
            continue
        reviews = read_reviews(d)
        if not reviews:
            continue
        manifest = runstore.manifest(d) or {}
        rbs: dict[str, str] = {}
        if (d / "requirements").is_dir():
            for f in (d / "requirements").glob("*.rbs"):
                rbs[f.stem] = f.read_text(encoding="utf-8")
        for rv in reviews:
            lines.append(
                json.dumps(
                    {"review": rv, "digests": manifest.get("digests"), "rbs": rbs.get(str(rv["requirement_id"]))},
                    ensure_ascii=False,
                    default=str,
                )
            )
    return "\n".join(lines) + ("\n" if lines else "")


def markdown_digest(s: dict[str, Any]) -> str:
    """Tóm tắt phản hồi dạng markdown để dán vào sổ theo dõi cải thiện (docs/management/theo_doi_cai_thien.md)."""
    rate = f"{s['agreement_rate']:.0%}" if s["agreement_rate"] is not None else "chưa có"
    out = [f"### Phản hồi của người duyệt ({s['decided']} nhận định, đồng thuận người–AI {rate})", ""]
    if s["causes"]:
        out += ["Nguyên nhân bất đồng:", *[f"- {c['label']}: {c['n']}" for c in s["causes"]], ""]
    bad = [a for a in s["agent_ratings"] if a["bad"]]
    if bad:
        out += ["Agent bị đánh giá kém:", *[f"- {a['role']}: {a['bad']} kém / {a['good']} tốt" for a in bad], ""]
    weak = [r for r in s["by_rule"] if r["n"] and r["agree"] < r["n"]]
    if weak:
        out += ["Quy tắc có bất đồng:", *[f"- {r['rule']}: đồng ý {r['agree']}/{r['n']}" for r in weak], ""]
    return "\n".join(out)

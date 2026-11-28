"""Coverage linker: nối T3 với T1 qua dữ liệu độ phủ (thiết kế chính, M4).

Đầu vào là tệp LCOV (định dạng chung: `llvm-cov export -format=lcov` cho C/Rust,
gcov qua lcov, Go cover chuyển sang lcov). Dòng có bản ghi DA là dòng được biên dịch;
dòng trong khối #ifdef bị tắt không có DA (tài liệu khả thi, mục 4.5).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, Field

from rfcv.core.ifc import TrustLabel
from rfcv.domains.rfc_protocol.payloads import (
    CoverageLink,
    Outcome,
    Producer,
    T1Payload,
    T3LinkPayload,
    T3Payload,
    Tier,
)
from rfcv.evidence.artifacts import ArtifactStore
from rfcv.evidence.models import EvidenceDraft
from rfcv.evidence.store import EvidenceStore
from rfcv.gates.tool_gateway import ToolResult, ToolSession, ToolSpec


@dataclass(frozen=True)
class LineCoverage:
    """file → {dòng: số lần thực thi}."""

    files: dict[str, dict[int, int]]

    def executed(self, file: str) -> set[int]:
        hits = self._lookup(file)
        return {line for line, count in hits.items() if count > 0}

    def compiled(self, file: str) -> set[int]:
        return set(self._lookup(file))

    def _lookup(self, file: str) -> dict[int, int]:
        if file in self.files:
            return self.files[file]
        # Đường dẫn trong lcov thường tuyệt đối trong container; so theo hậu tố.
        want = PurePosixPath(file.replace("\\", "/")).parts
        for name, hits in self.files.items():
            have = PurePosixPath(name.replace("\\", "/")).parts
            if len(have) >= len(want) and have[-len(want) :] == want:
                return hits
        return {}


def parse_lcov(text: str) -> LineCoverage:
    files: dict[str, dict[int, int]] = {}
    current: dict[int, int] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("SF:"):
            current = files.setdefault(line[3:], {})
        elif line.startswith("DA:") and current is not None:
            parts = line[3:].split(",")
            lineno, count = int(parts[0]), int(float(parts[1]))
            current[lineno] = current.get(lineno, 0) + count
        elif line == "end_of_record":
            current = None
    return LineCoverage(files)


def link(t1_id: str, t1: T1Payload, coverage: LineCoverage) -> CoverageLink:
    """T3 liên kết khi mọi đoạn dòng dẫn chứng của T1 có ít nhất một dòng đã thực thi.

    Không có khía cạnh nào thì dùng cả khoảng dòng của T1.
    """
    executed = coverage.executed(t1.file)
    ranges = [a.lines for a in t1.aspects] or [(t1.line_start, t1.line_end)]
    hit: set[int] = set()
    linked = True
    for start, end in ranges:
        in_range = {n for n in executed if start <= n <= end}
        if not in_range:
            linked = False
        hit |= in_range
    return CoverageLink(t1=t1_id, lines_hit=tuple(sorted(hit)), linked=linked and bool(hit))


@dataclass(frozen=True)
class SuspiciousLine:
    """Một dòng mã xếp hạng nghi ngờ lỗi theo công thức SBFL Ochiai (gen-44)."""

    file: str
    line: int
    score: float
    fail_hits: int
    pass_hits: int


def ochiai_scores(
    fail_covs: list[LineCoverage], pass_covs: list[LineCoverage], *, top_k: int = 15
) -> list[SuspiciousLine]:
    """Định vị lỗi theo phổ độ phủ (SBFL — Ochiai, gen-44): `e_f / sqrt(N_f * (e_f + e_p))`.

    Chỉ xét các dòng thực sự chạy ở ít nhất một ca FAIL (`e_f > 0`), giúp thu hẹp kho mã lớn xuống
    top `top_k` dòng nghi ngờ nhất và loại bỏ hoàn toàn các hàm không thực thi trên đường gây lỗi.
    """
    n_fail = len(fail_covs)
    if n_fail == 0:
        return []
    fail_counts: dict[tuple[str, int], int] = {}
    pass_counts: dict[tuple[str, int], int] = {}
    for cov in fail_covs:
        for f, hits in cov.files.items():
            for ln, cnt in hits.items():
                if cnt > 0:
                    fail_counts[(f, ln)] = fail_counts.get((f, ln), 0) + 1
    for cov in pass_covs:
        for f, hits in cov.files.items():
            for ln, cnt in hits.items():
                if cnt > 0:
                    pass_counts[(f, ln)] = pass_counts.get((f, ln), 0) + 1
    ranked: list[SuspiciousLine] = []
    for (f, ln), ef in fail_counts.items():
        ep = pass_counts.get((f, ln), 0)
        denom = math.sqrt(n_fail * (ef + ep))
        score = round(ef / denom, 4) if denom > 0 else 0.0
        ranked.append(SuspiciousLine(file=f, line=ln, score=score, fail_hits=ef, pass_hits=ep))
    ranked.sort(key=lambda s: (-s.score, -s.fail_hits, s.pass_hits, s.file, s.line))
    return ranked[:top_k]


class CoverageHotspotsParams(BaseModel):
    top_k: int = Field(default=12, ge=1, le=40, description="Số dòng điểm nóng Ochiai tối đa cần trả về.")
    file_filter: str = Field(default="", description="Chuỗi con lọc theo tên tệp (để trống nếu xem toàn kho mã).")


def repo_rel_path(raw_file: str, known_files: set[str]) -> str:
    norm = raw_file.replace("\\", "/")
    if norm in known_files:
        return norm
    parts = PurePosixPath(norm).parts
    # Nhiều tệp cùng là hậu tố (`a.c` và `lib/a.c`): lấy hậu tố DÀI nhất, không phụ thuộc thứ tự duyệt của set.
    best, best_len = norm, 0
    for kf in known_files:
        kparts = PurePosixPath(kf.replace("\\", "/")).parts
        if best_len < len(kparts) <= len(parts) and parts[-len(kparts) :] == kparts:
            best, best_len = kf, len(kparts)
    return best


_repo_rel = repo_rel_path


def fail_line_annotations(rt: Any) -> Callable[[str, str], dict[int, str]]:
    """Nguồn thẻ theo dòng cho `code.read` (gen-53): `[EXEC_FAIL]` nếu dòng chạy ở ít nhất một ca FAIL, `[EXEC_0]` nếu
    LCOV của ca FAIL có dòng đó (được biên dịch) nhưng không lần nào chạy. Không có LCOV của ca FAIL thì trả {} ngay.

    Đọc kho bằng chứng ở mỗi lần gọi (T3 có thể xuất hiện giữa chừng). Artifact định địa chỉ theo nội dung nên LCOV đã
    phân tích được giữ lại, và mỗi đường dẫn LCOV chỉ được quy về đường dẫn kho một lần.
    """
    parsed: dict[str, LineCoverage] = {}
    resolved: dict[str, str] = {}
    known_files: set[str] = set()

    def annotate(requirement_id: str, rel_file: str) -> dict[int, str]:
        store: Any = getattr(rt, "store", None)
        artifacts: Any = getattr(rt, "artifacts", None)
        if store is None or artifacts is None:
            return {}
        lcov_ids = [
            lcov_id
            for e in store.for_requirement(requirement_id)
            if isinstance(e.payload, T3Payload)
            and e.payload.outcome is Outcome.FAIL
            and (lcov_id := e.payload.artifacts.get("lcov"))
        ]
        if not lcov_ids:
            return {}
        if not known_files:
            index: Any = getattr(getattr(rt, "providers", None), "code_index", None)
            if index is None:
                return {}
            known_files.update(str(f) for f in index.files())
        hits: dict[int, int] = {}
        for lcov_id in lcov_ids:
            if (cov := parsed.get(lcov_id)) is None:
                try:
                    cov = parsed[lcov_id] = parse_lcov(artifacts.get(lcov_id).decode("utf-8", "replace"))
                except Exception:  # một artifact hỏng không làm mất dữ liệu của các ca FAIL khác
                    continue
            for raw_file, lines in cov.files.items():
                if (rel := resolved.get(raw_file)) is None:
                    rel = resolved[raw_file] = repo_rel_path(raw_file, known_files)
                if rel == rel_file:
                    for line, count in lines.items():
                        hits[line] = max(hits.get(line, 0), count)
        return {line: "[EXEC_FAIL]" if count > 0 else "[EXEC_0]" for line, count in hits.items()}

    return annotate


def coverage_hotspots_tool_spec(rt: Any) -> ToolSpec:
    """Công cụ chủ động `coverage.hotspots` cho Agent gọi (gen-45 / Agent-Centric Tooling).

    Trả về top dòng mã nghi ngờ nhất theo SBFL Ochiai kèm tên hàm bao quanh và đoạn mã thật,
    đồng thời đánh dấu `shown_lines` để SchemaGate chấp nhận ngay.
    """

    async def handler(p: BaseModel, session: ToolSession) -> ToolResult:
        params = CoverageHotspotsParams.model_validate(p.model_dump())
        store: Any = getattr(rt, "store", None)
        artifacts: Any = getattr(rt, "artifacts", None)
        if store is None or artifacts is None:
            return ToolResult("tool=coverage.hotspots: không có dữ liệu độ phủ LCOV.", TrustLabel.DERIVED)
        t3s = [e.payload for e in store.for_requirement(session.requirement_id) if isinstance(e.payload, T3Payload)]
        fail_covs: list[LineCoverage] = []
        pass_covs: list[LineCoverage] = []
        for t3 in t3s:
            lcov_id = t3.artifacts.get("lcov")
            if not lcov_id:
                continue
            try:
                cov = parse_lcov(artifacts.get(lcov_id).decode("utf-8", "replace"))
            except Exception:
                continue
            if t3.outcome is Outcome.FAIL:
                fail_covs.append(cov)
            elif t3.outcome is Outcome.PASS:
                pass_covs.append(cov)
        if not fail_covs:
            return ToolResult(
                "tool=coverage.hotspots: không có dữ liệu độ phủ LCOV trên ca FAIL cho lần chạy này.",
                TrustLabel.DERIVED,
            )
        index: Any = getattr(getattr(rt, "providers", None), "code_index", None)
        known_files: set[str] = {str(f) for f in index.files()} if index is not None else set()
        ranked = ochiai_scores(fail_covs, pass_covs, top_k=max(params.top_k * 3, 30))
        lines_out: list[str] = []
        shown: set[tuple[str, int]] = set()
        for item in ranked:
            rel = _repo_rel(item.file, known_files)
            if params.file_filter and params.file_filter.lower() not in rel.lower():
                continue
            if known_files and rel not in known_files:
                continue
            sym_tag = ""
            snippet = ""
            if index is not None:
                sym = index.containing_symbol(rel, item.line)
                if sym is not None:
                    sym_tag = f" | symbol: {sym.name} ({sym.line_start}-{sym.line_end})"
                src_lines = index.lines(rel, item.line, item.line)
                if src_lines:
                    snippet = f" | {src_lines[0].strip()[:100]}"
                    shown.add((rel, item.line))
            lines_out.append(
                f"#{len(lines_out) + 1} ochiai={item.score:.4f} [{rel}:{item.line}{sym_tag}] "
                f"fail={item.fail_hits}/{len(fail_covs)} pass={item.pass_hits}/{len(pass_covs)}{snippet}"
            )
            if len(lines_out) >= params.top_k:
                break
        if not lines_out:
            return ToolResult("tool=coverage.hotspots: không có dòng thực thi nào khớp bộ lọc.", TrustLabel.DERIVED)
        body = "\n".join(lines_out)
        return ToolResult(
            f"[UNTRUSTED CODE] tool=coverage.hotspots (SBFL Ochiai, {len(fail_covs)} FAIL / {len(pass_covs)} PASS)\n{body}",
            TrustLabel.UNTRUSTED,
            shown_lines=frozenset(shown),
        )

    return ToolSpec(
        "coverage.hotspots",
        "Xếp hạng top dòng mã nghi ngờ lỗi theo phổ độ phủ thực thi thực tế (SBFL Ochiai từ LCOV các ca FAIL/PASS), "
        "kèm tên hàm bao quanh và mã nguồn. Gọi khi có nhiều hàm kiểm tra trùng hoặc phản ứng bị xoá hẳn.",
        CoverageHotspotsParams,
        handler,
        title="Điểm nóng độ phủ SBFL Ochiai",
    )


def causal_diff(fail_covs: list[LineCoverage], pass_covs: list[LineCoverage]) -> dict[str, dict[str, list[int]]]:
    """Độ phủ vi sai nhân quả (gen-43 / E4 & D8): tách dòng thực thi trên ca FAIL vs ca PASS.

    Trả về `{file: {"fail_executed": [...], "fail_only": [...], "pass_only": [...]}}` giúp xác minh
    hàm/nhánh nào thực sự chạy trên đường đi gây lỗi (giải bài toán nhiều điểm kiểm tra trùng như QUIC ngtcp2).
    """
    all_files: set[str] = set()
    for cov in (*fail_covs, *pass_covs):
        all_files.update(cov.files.keys())
    out: dict[str, dict[str, list[int]]] = {}
    for f in sorted(all_files):
        f_lines: set[int] = set()
        for cov in fail_covs:
            f_lines |= cov.executed(f)
        p_lines: set[int] = set()
        for cov in pass_covs:
            p_lines |= cov.executed(f)
        if f_lines or p_lines:
            out[f] = {
                "fail_executed": sorted(f_lines),
                "fail_only": sorted(f_lines - p_lines),
                "pass_only": sorted(p_lines - f_lines),
            }
    return out


def link_pending(store: EvidenceStore, artifacts: ArtifactStore, run_id: str, requirement_id: str) -> int:
    """Ghi bản ghi liên kết cho mọi cặp (T3 PASS/FAIL có dữ liệu độ phủ, T1) chưa được xét. Trả số bản ghi mới."""
    evidence = store.for_requirement(requirement_id)
    t1s = [(e.evidence_id, e.payload) for e in evidence if isinstance(e.payload, T1Payload)]
    t3s = [
        (e.evidence_id, e.payload)
        for e in evidence
        if isinstance(e.payload, T3Payload)
        and e.payload.outcome in (Outcome.PASS, Outcome.FAIL)
        and "lcov" in e.payload.artifacts
    ]
    done = {(e.payload.t3, e.payload.t1) for e in evidence if isinstance(e.payload, T3LinkPayload)}
    written = 0
    for t3_id, t3 in t3s:
        coverage: LineCoverage | None = None
        for t1_id, t1 in t1s:
            if (t3_id, t1_id) in done:
                continue
            if coverage is None:
                coverage = parse_lcov(artifacts.get(t3.artifacts["lcov"]).decode("utf-8", "replace"))
            cl = link(t1_id, t1, coverage)
            store.append(
                EvidenceDraft(
                    run_id=run_id,
                    requirement_id=requirement_id,
                    tier=Tier.T3,
                    payload=T3LinkPayload(t3=t3_id, t1=t1_id, lines_hit=cl.lines_hit, linked=cl.linked),
                    produced_by=Producer.COVERAGE_LINKER,
                    provenance={"lcov": t3.artifacts["lcov"]},
                    ifc="DERIVED",
                )
            )
            written += 1
    return written

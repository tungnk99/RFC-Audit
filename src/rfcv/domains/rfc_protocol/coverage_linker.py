"""Coverage linker: nối T3 với T1 qua dữ liệu độ phủ (thiết kế chính, M4).

Đầu vào là tệp LCOV (định dạng chung: `llvm-cov export -format=lcov` cho C/Rust,
gcov qua lcov, Go cover chuyển sang lcov). Dòng có bản ghi DA là dòng được biên dịch;
dòng trong khối #ifdef bị tắt không có DA (tài liệu khả thi, mục 4.5).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

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


def link_pending(store: EvidenceStore, artifacts: ArtifactStore, run_id: str, requirement_id: str) -> int:
    """Ghi bản ghi liên kết cho mọi cặp (T3 PASS có dữ liệu độ phủ, T1) chưa được xét. Trả số bản ghi mới."""
    evidence = store.for_requirement(requirement_id)
    t1s = [(e.evidence_id, e.payload) for e in evidence if isinstance(e.payload, T1Payload)]
    t3s = [
        (e.evidence_id, e.payload)
        for e in evidence
        if isinstance(e.payload, T3Payload) and e.payload.outcome is Outcome.PASS and "lcov" in e.payload.artifacts
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

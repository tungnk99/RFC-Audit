"""Locator tất định: xếp hạng hàm ứng viên cho một yêu cầu (tài liệu khám phá mã, mục 9).

    score(f) = 3·kw(f) + 2·comp(f) + 2·near(f) + 1·hint(f)
    kw    số từ khoá của yêu cầu và của adapter xuất hiện trong tên hoặc thân hàm
    comp  1 nếu thành phần của f trùng thành phần của yêu cầu
    near  1/(1+d), d là khoảng cách trên đồ thị gọi hàm từ điểm vào do adapter khai báo
    hint  1 nếu f nằm trong đường dẫn gợi ý của adapter

Thành phần của hàm lấy từ bản đồ của Code Indexer khi đã có (đã đối chiếu chỉ mục); chưa có thì suy tất định từ từ khoá
và đường dẫn gợi ý của adapter. Kết quả chỉ để định hướng, không phải bằng chứng: không tính vào tập dòng đã hiển thị.
"""

from __future__ import annotations

import fnmatch
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rfcv.core.ifc import TrustLabel
from rfcv.gates.code_gate import FUNCTION_KINDS, CodeIndex, SymbolInfo
from rfcv.gates.tool_gateway import ToolResult, ToolSession, ToolSpec

WEIGHTS = {"kw": 3.0, "comp": 2.0, "near": 2.0, "hint": 1.0}
MAX_DEPTH = 6
BODY_SCAN_LINES = 400
# Động từ chung của từ vựng sự kiện: không giúp phân biệt hàm.
_GENERIC = frozenset({"send", "receive", "respond", "close", "discard", "send_alert", "then"})


@dataclass(frozen=True)
class Candidate:
    symbol: SymbolInfo
    score: float
    kw: int
    comp: int
    near: float
    hint: int


class LocatorParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=10, ge=1, le=20, description="Số hàm ứng viên trả về.")


LOCATOR_DOC = (
    "Gợi ý các hàm ứng viên cho yêu cầu đang điều tra, xếp hạng tất định theo công thức "
    "score = 3·kw + 2·comp + 2·near + 1·hint (kw: số từ khoá của yêu cầu/adapter có trong tên hoặc thân hàm; comp: "
    "cùng thành phần giao thức; near: gần điểm vào trên đồ thị gọi; hint: nằm trong đường dẫn gợi ý của adapter).\n"
    "Khi dùng: bước đầu tiên của LOCATE/TRACE_PATHS để biết nên đọc hàm nào trước. Không phải bằng chứng.\n"
    "Trả về: thành phần và từ khoá của yêu cầu, rồi mỗi dòng '<điểm> <hàm> <tệp>:<dòng> (kw comp near hint)'.\n"
    'Ví dụ: {} hoặc {"limit": 15}'
)


def requirement_keywords(rbs: Any) -> tuple[str, ...]:
    """Từ khoá của một yêu cầu đã cấu trúc (RBS): tên và đối số của trigger/expect/forbid, các phần của trường where."""
    words: list[str] = []
    for call in (rbs.trigger, *rbs.expect, *rbs.forbid, *rbs.accept_alternatives):
        words += [call.name, *call.args]
    if rbs.where is not None:
        words += str(rbs.where.field).split(".")
    seen: dict[str, None] = {}
    for w in words:
        w = str(w).strip()
        if len(w) >= 3 and w not in _GENERIC and not w.startswith("$"):
            seen.setdefault(w, None)
    return tuple(seen)


class Locator:
    def __init__(self, index: CodeIndex, manifest: Any) -> None:
        self._index = index
        self._taxonomy: tuple[str, ...] = tuple(manifest.component_taxonomy)
        self._hints: dict[str, dict[str, tuple[str, ...]]] = {k: dict(v) for k, v in manifest.locator_hints.items()}
        self._requirements: dict[str, tuple[str, ...]] = {}
        self._components: dict[tuple[str, str], str] = {}
        self._cache: dict[str, list[Candidate]] = {}
        self._functions: list[SymbolInfo] | None = None

    # ---- dữ liệu vào ----------------------------------------------------------------------------

    def register(self, requirement_id: str, keywords: Iterable[str]) -> None:
        self._requirements[requirement_id] = tuple(keywords)
        self._cache.pop(requirement_id, None)

    def set_component(self, file: str, symbol: str, component: str) -> None:
        self._components[(file, symbol)] = component
        self._cache.clear()

    @property
    def taxonomy(self) -> tuple[str, ...]:
        return self._taxonomy

    # ---- thành phần -------------------------------------------------------------------------------

    def _hint(self, component: str, key: str) -> tuple[str, ...]:
        return tuple(self._hints.get(component, {}).get(key, ()))

    def requirement_component(self, keywords: Sequence[str]) -> str | None:
        best, best_score = None, 0
        lowered = [k.lower() for k in keywords]
        for comp in self._taxonomy or tuple(self._hints):
            hint_kws = [h.lower() for h in self._hint(comp, "keywords")]
            score = sum(1 for k in lowered for h in hint_kws if k in h or h in k)
            if score > best_score:
                best, best_score = comp, score
        return best

    def component_of(self, sym: SymbolInfo) -> str | None:
        mapped = self._components.get((sym.file, sym.name))
        if mapped is not None:
            return mapped
        best, best_score = None, 0
        name = sym.name.lower()
        for comp in self._taxonomy or tuple(self._hints):
            score = sum(1 for h in self._hint(comp, "keywords") if h.lower() in name)
            score += 2 * any(fnmatch.fnmatch(sym.file, p) for p in self._hint(comp, "paths"))
            if score > best_score:
                best, best_score = comp, score
        return best

    # ---- xếp hạng ---------------------------------------------------------------------------------

    def _all_functions(self) -> list[SymbolInfo]:
        if self._functions is None:
            listing: Any = getattr(self._index, "functions", None)
            if listing is not None:
                self._functions = list(listing())
            else:
                self._functions = [
                    s for f in self._index.files() for s in self._index.outline(f) if s.kind in FUNCTION_KINDS
                ]
        return self._functions

    def _distances(self, entries: Iterable[str]) -> dict[str, int]:
        dist: dict[str, int] = {}
        queue: deque[str] = deque()
        for e in entries:
            if e not in dist:
                dist[e] = 0
                queue.append(e)
        while queue:
            cur = queue.popleft()
            if dist[cur] >= MAX_DEPTH:
                continue
            for callee, _ in self._index.callees(cur):
                if callee not in dist:
                    dist[callee] = dist[cur] + 1
                    queue.append(callee)
        return dist

    def suggest(self, requirement_id: str | None) -> tuple[str | None, tuple[str, ...], list[Candidate]]:
        req_kws = self._requirements.get(requirement_id or "", ())
        component = self.requirement_component(req_kws)
        if requirement_id in self._cache:
            return component, req_kws, self._cache[requirement_id or ""]
        comps = (component,) if component else tuple(self._hints)
        adapter_kws = tuple(k for c in comps for k in self._hint(c, "keywords"))
        keywords = [k.lower() for k in dict.fromkeys((*req_kws, *adapter_kws))]
        entries = [e for c in (comps or tuple(self._hints)) for e in self._hint(c, "entry_points")]
        dist = self._distances(entries)
        paths = [p for c in comps for p in self._hint(c, "paths")]

        out: list[Candidate] = []
        for sym in self._all_functions():
            body = "\n".join(
                self._index.lines(sym.file, sym.line_start, min(sym.line_end, sym.line_start + BODY_SCAN_LINES))
            )
            hay = (sym.name + "\n" + body).lower()
            kw = sum(1 for k in keywords if k in hay)
            comp = int(component is not None and self.component_of(sym) == component)
            near = 1.0 / (1 + dist[sym.name]) if sym.name in dist else 0.0
            hint = int(any(fnmatch.fnmatch(sym.file, p) for p in paths))
            score = WEIGHTS["kw"] * kw + WEIGHTS["comp"] * comp + WEIGHTS["near"] * near + WEIGHTS["hint"] * hint
            if score > 0:
                out.append(Candidate(sym, score, kw, comp, near, hint))
        out.sort(key=lambda c: (-c.score, c.symbol.file, c.symbol.line_start))
        self._cache[requirement_id or ""] = out
        return component, req_kws, out

    # ---- công cụ ----------------------------------------------------------------------------------

    def tool_spec(self) -> ToolSpec:
        async def handler(p: BaseModel, s: ToolSession) -> ToolResult:
            assert isinstance(p, LocatorParams)
            component, kws, ranked = self.suggest(s.requirement_id)
            rows = [
                f"{c.score:6.2f} {c.symbol.name} {c.symbol.file}:{c.symbol.line_start} "
                f"(kw={c.kw} comp={c.comp} near={c.near:.2f} hint={c.hint})"
                for c in ranked[: p.limit]
            ]
            head = f"thành phần={component or '?'} từ khoá={', '.join(kws) or '?'}"
            body = "\n".join([head, *rows]) if rows else head + "\n(không có ứng viên; dùng search_text theo từ khoá)"
            # Tên hàm, tệp đến từ kho mã: không tin cậy. Không tính dòng đã hiển thị (gợi ý không phải bằng chứng).
            return ToolResult(f"[UNTRUSTED CODE] tool=locator.suggest {s.requirement_id}\n{body}", TrustLabel.UNTRUSTED)

        return ToolSpec("locator.suggest", LOCATOR_DOC, LocatorParams, handler, title="Gợi ý hàm ứng viên")

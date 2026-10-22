"""Công cụ thật cho các agent đặc quyền (Planner, Verifier, Test, RFC Analyst, Report).

Trước đây lời nhắc của các agent này hứa những công cụ (`evidence__read_summary`, `rfc__*`, `test__run_scenario`...) mà không
có mã cài đặt, nên agent chạy với 0 công cụ. Ở đây mỗi công cụ là một `ToolSpec` thật, chỉ đọc, đi qua Tool gateway như
mọi công cụ khác. Kết quả chỉ chứa giá trị miền hữu hạn hoặc văn bản RFC (đầu vào TRUSTED), không bao giờ có chuỗi tự do từ
mã nguồn không tin cậy, nên giữ nguyên ranh giới vùng cách ly.

| Công cụ | Cho ai | Trả về |
|---|---|---|
| evidence.read_summary | Planner, Verifier, Report | tóm tắt bằng chứng của yêu cầu, lọc theo tầng hay mã, có thể xem từng mục chưa gộp |
| verdict.read | Planner, Verifier, Report | báo cáo độ đủ hiện tại, quy tắc nào đang áp dụng, danh mục quy tắc và việc nào mở khoá nhãn nào |
| rfc.get_sentences, read_section, search, get_definition | RFC Analyst, Verifier, Test | văn bản RFC theo mục, tìm kiếm, khối định nghĩa |
| test.list_examples | Test | các mẫu kịch bản của adapter |
| test.run_scenario | Test | chạy thử một biến thể trên bản tham chiếu, không ghi bằng chứng |
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from agents.common import ORACLE_KEY
from agents.test.schema import ScenarioProposal
from rfcv.core.context_builder import summarize_evidence, to_jsonable
from rfcv.core.execution_loop import Investigation, report_json
from rfcv.core.ifc import TrustLabel
from rfcv.domains.rfc_protocol.rfc_gate import RfcDocument
from rfcv.domains.rfc_protocol.sandbox.driver import TestDriver
from rfcv.evidence.models import Evidence
from rfcv.evidence.verdict_engine import RuleSet, assess
from rfcv.gates.tool_gateway import ToolResult, ToolSession, ToolSpec

MAX_RESULT_CHARS = 6000  # khoảng 1.500 token: cùng cỡ trang với công cụ đọc mã
PAGE_CHARS = 5000


class _P(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceParams(_P):
    tier: Literal["T1", "T2", "T3"] | None = Field(
        None, description="Chỉ lấy một tầng bằng chứng; bỏ trống là mọi tầng."
    )
    evidence_id: str | None = Field(None, description="Xem riêng một mục (không gộp), lấy mã từ bản tóm tắt.")
    fold: bool = Field(True, description="Gộp các T3 thường thành một hàng; đặt false để xem từng ca.")
    limit: int = Field(30, ge=1, le=60)


class NoParams(_P):
    pass


class RfcSentencesParams(_P):
    section: str = Field(description="Số mục, ví dụ 5.2 hay appendix.c; gồm cả mục con.")
    rfc: int | None = Field(None, description="Số RFC; mặc định là RFC của yêu cầu đang xét.")


class RfcSectionParams(_P):
    section: str = Field(description="Số mục, ví dụ 5.2.")
    page: int = Field(1, ge=1)
    rfc: int | None = None


class RfcSearchParams(_P):
    term: str = Field(min_length=2, max_length=60)
    rfc: int | None = None


class RfcDefinitionParams(_P):
    name: str = Field(
        min_length=2, max_length=60, description="Tên kiểu, trường hay hằng, đúng nguyên từ (ví dụ TLSCiphertext)."
    )
    rfc: int | None = None


class ListExamplesParams(_P):
    requirement_type: Literal["A", "B", "C", "D"] | None = None


class RunScenarioParams(_P):
    scenario: ScenarioProposal
    variant: str | None = Field(None, description="Tên biến thể cần chạy thử; bỏ trống là biến thể đối chứng đầu tiên.")


def _text(label: str, body: str, trust: TrustLabel = TrustLabel.DERIVED) -> ToolResult:
    clipped = body if len(body) <= MAX_RESULT_CHARS else body[:MAX_RESULT_CHARS] + "\n… (cắt bớt, thu hẹp truy vấn)"
    return ToolResult(f"[{trust.name}] tool={label}\n{clipped}", trust)


def _json(label: str, value: Any, trust: TrustLabel = TrustLabel.DERIVED) -> ToolResult:
    return _text(label, json.dumps(to_jsonable(value), ensure_ascii=False, indent=1), trust)


class AgentTools:
    """Dựng các `ToolSpec` cho một lần chạy. Mọi trạng thái đi qua hàm lấy lười, vì công cụ được đăng ký trước khi yêu cầu
    được nạp và trước khi Test driver được dựng."""

    def __init__(
        self,
        *,
        investigation: Callable[[str], Investigation | None],
        evidence: Callable[[str], list[Evidence]],
        rules: Callable[[], RuleSet],
        rfc_docs: Mapping[int, RfcDocument],
        driver: Callable[[], TestDriver | None],
        seed: int,
        examples_dir: Path | None,
    ) -> None:
        self._inv = investigation
        self._evidence = evidence
        self._rules = rules
        self._rfc = dict(rfc_docs)
        self._driver = driver
        self._seed = seed
        self._examples = examples_dir

    # ---- chung -----------------------------------------------------------------------------------------

    def _current(self, s: ToolSession) -> Investigation | None:
        return self._inv(s.requirement_id or "")

    def _rfc_doc(self, s: ToolSession, rfc: int | None) -> tuple[RfcDocument | None, str]:
        if rfc is None:
            inv = self._current(s)
            ctx = inv.context.get("requirement.rbs") if inv else None
            sentence_id = str(ctx.value.get("sentence_id", "")) if ctx and isinstance(ctx.value, dict) else ""  # type: ignore[union-attr]
            m = re.match(r"RFC(\d+)", sentence_id)
            rfc = int(m.group(1)) if m else (next(iter(self._rfc)) if self._rfc else None)
        if rfc is None or rfc not in self._rfc:
            have = ", ".join(f"RFC{n}" for n in sorted(self._rfc)) or "không có bản RFC nào"
            hint = (
                f" Thử lại với tham số rfc={sorted(self._rfc)[0]} để đọc bản đó; số mục và số đoạn có thể khác giữa các phiên bản."
                if self._rfc
                else ""
            )
            return None, f"Không có bản RFC{rfc if rfc else ''} trong Input store (có: {have}).{hint}"
        return self._rfc[rfc], ""

    # ---- bằng chứng và kết luận -------------------------------------------------------------------------

    def evidence_read_summary(self) -> ToolSpec:
        async def handler(p: BaseModel, s: ToolSession) -> ToolResult:
            assert isinstance(p, EvidenceParams)
            inv = self._current(s)
            if inv is None:
                return _text("evidence.read_summary", "Không có yêu cầu đang xét.")
            items = self._evidence(inv.requirement.requirement_id)
            if p.evidence_id:
                items = [e for e in items if e.evidence_id == p.evidence_id]
            elif p.tier:
                items = [e for e in items if str(e.tier) == p.tier]
            # `keep` là tập mã không được gộp: một mục được chỉ định, hoặc mọi mục khi đặt fold=false.
            keep: set[str] = {e.evidence_id for e in items} if (p.evidence_id or not p.fold) else set()
            rows = summarize_evidence(items, inv.vocabulary_terms, keep).value
            return _json("evidence.read_summary", {"total": len(items), "rows": rows[: p.limit]})

        return ToolSpec(
            "evidence.read_summary",
            "Xem bản tóm tắt bằng chứng đã có của yêu cầu đang xét: T1 (vị trí mã, khía cạnh MATCH/MISMATCH/UNCLEAR, đường "
            "gọi, phần chưa khám phá), T2 (truy vấn tĩnh, nhánh nghi vấn), T3 (kết quả chạy, đã gộp theo biến thể). Dùng "
            "`tier` để lọc, `evidence_id` để xem riêng một mục, `fold=false` để xem từng ca T3. Chỉ chứa giá trị hữu hạn.",
            EvidenceParams,
            handler,
            title="Đọc tóm tắt bằng chứng",
        )

    def verdict_read(self) -> ToolSpec:
        async def handler(p: BaseModel, s: ToolSession) -> ToolResult:
            inv = self._current(s)
            if inv is None:
                return _text("verdict.read", "Không có yêu cầu đang xét.")
            rules = self._rules()
            report = assess(inv.requirement, self._evidence(inv.requirement.requirement_id), rules)
            applicable = [
                {"rule": r.id, "meaning": r.description}
                for r in rules.rules
                if r.applies_to is None or inv.requirement.rtype in r.applies_to
            ]
            current = report.provisional
            return _json(
                "verdict.read",
                {
                    "report": report_json(report, inv.feasible),
                    "applies_now": {"rule": current.rule, "label": current.label.value} if current else None,
                    "rules_for_this_requirement_type": applicable,
                    "note": "Nhãn do Verdict engine quyết định theo quy tắc đầu tiên khớp; bạn chỉ chọn việc kế tiếp.",
                },
            )

        return ToolSpec(
            "verdict.read",
            "Báo cáo độ đủ hiện tại của Verdict engine cho yêu cầu đang xét: nhãn tạm và quy tắc đang áp dụng, còn thiếu gì, "
            "có mâu thuẫn nào, kèm danh mục quy tắc áp dụng cho loại yêu cầu này để biết bằng chứng nào mở ra nhãn nào.",
            NoParams,
            handler,
            title="Đọc báo cáo độ đủ",
        )

    # ---- RFC --------------------------------------------------------------------------------------------

    def rfc_get_sentences(self) -> ToolSpec:
        async def handler(p: BaseModel, s: ToolSession) -> ToolResult:
            assert isinstance(p, RfcSentencesParams)
            doc, err = self._rfc_doc(s, p.rfc)
            if doc is None:
                return _text("rfc.get_sentences", err, TrustLabel.TRUSTED)
            if not doc.has_section(p.section):
                return _text("rfc.get_sentences", f"RFC{doc.rfc} không có mục {p.section}.", TrustLabel.TRUSTED)
            rows = [f"{r.sentence_id} [{r.modal}] {r.text}" for r in doc.sentences(p.section)[:50]]
            return _text("rfc.get_sentences", "\n".join(rows) or "(mục này không có câu quy phạm)", TrustLabel.TRUSTED)

        return ToolSpec(
            "rfc.get_sentences",
            "Liệt kê câu quy phạm BCP 14 (MUST, SHOULD, MAY...) của một mục RFC và các mục con, mỗi câu kèm định danh ổn định "
            "dạng RFC8446§5.2#p4s3. Tối đa 50 câu.",
            RfcSentencesParams,
            handler,
            title="Câu quy phạm của mục RFC",
        )

    def rfc_read_section(self) -> ToolSpec:
        async def handler(p: BaseModel, s: ToolSession) -> ToolResult:
            assert isinstance(p, RfcSectionParams)
            doc, err = self._rfc_doc(s, p.rfc)
            if doc is None:
                return _text("rfc.read_section", err, TrustLabel.TRUSTED)
            found = doc.section(p.section)
            if found is None:
                return _text("rfc.read_section", f"RFC{doc.rfc} không có mục {p.section}.", TrustLabel.TRUSTED)
            path, paragraphs = found
            pages: list[list[str]] = [[]]
            used = 0
            for pid, text in paragraphs:
                row = f"{pid}: {text}"
                if used + len(row) > PAGE_CHARS and pages[-1]:
                    pages.append([])
                    used = 0
                pages[-1].append(row)
                used += len(row)
            if p.page > len(pages):
                return _text("rfc.read_section", f"Mục {p.section} chỉ có {len(pages)} trang.", TrustLabel.TRUSTED)
            head = f"{' › '.join(path)}  (trang {p.page}/{len(pages)})"
            return _text("rfc.read_section", head + "\n" + "\n".join(pages[p.page - 1]), TrustLabel.TRUSTED)

        return ToolSpec(
            "rfc.read_section",
            "Đọc nội dung các đoạn của một mục RFC (không gồm mục con), mỗi đoạn có định danh, theo trang khoảng 1.500 token.",
            RfcSectionParams,
            handler,
            title="Đọc mục RFC",
        )

    def rfc_search(self) -> ToolSpec:
        async def handler(p: BaseModel, s: ToolSession) -> ToolResult:
            assert isinstance(p, RfcSearchParams)
            doc, err = self._rfc_doc(s, p.rfc)
            if doc is None:
                return _text("rfc.search", err, TrustLabel.TRUSTED)
            rows = [f"{pid}: …{snippet}…" for pid, snippet in doc.search(p.term)]
            return _text("rfc.search", "\n".join(rows) or f"Không đoạn nào chứa '{p.term}'.", TrustLabel.TRUSTED)

        return ToolSpec(
            "rfc.search",
            "Tìm các đoạn RFC có chứa một thuật ngữ (không phân biệt hoa thường); mỗi kết quả kèm định danh đoạn. Tối đa 30.",
            RfcSearchParams,
            handler,
            title="Tìm trong RFC",
        )

    def rfc_get_definition(self) -> ToolSpec:
        async def handler(p: BaseModel, s: ToolSession) -> ToolResult:
            assert isinstance(p, RfcDefinitionParams)
            doc, err = self._rfc_doc(s, p.rfc)
            if doc is None:
                return _text("rfc.get_definition", err, TrustLabel.TRUSTED)
            rows = [f"--- mục {sec}\n{body}" for sec, body in doc.definitions(p.name)]
            return _text(
                "rfc.get_definition",
                "\n".join(rows) or f"Không có khối định nghĩa nào nhắc '{p.name}'.",
                TrustLabel.TRUSTED,
            )

        return ToolSpec(
            "rfc.get_definition",
            "Lấy khối định nghĩa (struct, bảng, mã giả) trong RFC có nhắc đúng tên một kiểu, trường hay hằng. Tối đa 3 khối.",
            RfcDefinitionParams,
            handler,
            title="Khối định nghĩa trong RFC",
        )

    # ---- kiểm thử ---------------------------------------------------------------------------------------

    def test_list_examples(self) -> ToolSpec:
        async def handler(p: BaseModel, s: ToolSession) -> ToolResult:
            assert isinstance(p, ListExamplesParams)
            if self._examples is None or not self._examples.is_dir():
                return _text("test.list_examples", "Adapter chưa có thư viện mẫu.", TrustLabel.TRUSTED)
            out: list[str] = []
            for f in sorted(self._examples.glob("*.yaml")):
                data: dict[str, Any] = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                types: list[str] = data.get("requirement_types", [])
                if p.requirement_type and p.requirement_type not in types:
                    continue
                raw_cases: list[dict[str, Any]] = data.get("cases", [])
                cases = ", ".join(f"{c.get('variant')}(limit={c.get('limit')})" for c in raw_cases)
                out.append(
                    f"{data.get('id', f.stem)}: kiểm {data.get('checks_behavior', '?')}; loại {types}; ca: {cases}"
                )
            return _text("test.list_examples", "\n".join(out) or "Không có mẫu phù hợp.", TrustLabel.TRUSTED)

        return ToolSpec(
            "test.list_examples",
            "Liệt kê mẫu kiểm thử có sẵn của adapter (hành vi được kiểm, loại yêu cầu, các ca và ngưỡng). Dùng làm điểm xuất phát.",
            ListExamplesParams,
            handler,
            title="Mẫu kịch bản của adapter",
        )

    def test_run_scenario(self) -> ToolSpec:
        async def handler(p: BaseModel, s: ToolSession) -> ToolResult:
            assert isinstance(p, RunScenarioParams)
            inv, driver = self._current(s), self._driver()
            oracle = inv.domain_state.get(ORACLE_KEY) if inv else None
            if inv is None or driver is None or oracle is None:
                return _text("test.run_scenario", "Chưa có bộ chạy thử cho yêu cầu này.")
            result = await driver.probe(oracle=oracle, scenario=p.scenario, variant_name=p.variant, seed=self._seed)
            if result.get("ok"):
                # Quan sát chỉ được mang giá trị trong từ vựng adapter; giá trị lạ thay bằng hằng của harness.
                observed = {
                    k: (v if isinstance(v, bool | int) or v in inv.vocabulary_terms | {"none"} else "<unverified>")
                    for k, v in result["observed"].items()
                }
                result = {**result, "observed": observed}
            return _json("test.run_scenario", result)

        return ToolSpec(
            "test.run_scenario",
            "Chạy THỬ một kịch bản với một biến thể trên bản tham chiếu, không ghi bằng chứng. Trả về: có chạm trigger không "
            "(`trigger_reached`), kết quả oracle (PASS/FAIL/ERROR), lý do nếu lỗi (`trigger_not_reached`, `sanity_failed`...) "
            "và quan sát (cảnh báo, đóng kết nối). Dùng để sửa kịch bản trước khi nộp; kết quả cuối do Test driver chạy đủ mọi biến thể.",
            RunScenarioParams,
            handler,
            title="Chạy thử kịch bản",
            read_only=False,  # chạy trong sandbox, không ghi bằng chứng
        )

    def specs(self) -> list[ToolSpec]:
        return [
            self.evidence_read_summary(),
            self.verdict_read(),
            self.rfc_get_sentences(),
            self.rfc_read_section(),
            self.rfc_search(),
            self.rfc_get_definition(),
            self.test_list_examples(),
            self.test_run_scenario(),
        ]

"""Bộ quét nhánh nghi vấn (BL-40, CG-6, YD-25, QS-11): phát hiện A7 mức 1 và 2, không báo mã bình thường, mức 3 nói thẳng là không bắt."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.code_reader.handler import LocationHandler
from agents.code_reader.schema import LocationClaim
from fakes import make_index
from helpers import REQ, full_passing_set
from rfcv.core.execution_loop import Investigation
from rfcv.core.ifc import Labeled, TrustLabel
from rfcv.domains.rfc_protocol.adapter_view import vocabulary_terms
from rfcv.domains.rfc_protocol.payloads import T2SuspiciousPayload
from rfcv.domains.rfc_protocol.rules import ProtocolRequirement
from rfcv.domains.rfc_protocol.schema_gate import SchemaGate
from rfcv.domains.rfc_protocol.suspicious import (
    RULE_CANONICAL,
    RULE_ENVIRONMENT,
    canonical_values,
    scan_source,
    scan_symbols,
)
from rfcv.evidence.artifacts import ArtifactStore
from rfcv.evidence.store import EvidenceStore
from rfcv.evidence.verdict_engine import Label, StopReason, decide
from rfcv.gates.code_gate import InMemoryCodeIndex, SymbolInfo
from rfcv.gates.tool_gateway import ToolSession

CANONICAL = frozenset({16641, 65535})


def rules(code: str, canonical: frozenset[int] = CANONICAL) -> list[str]:
    return [f.rule_id for f in scan_source("src/x.c", 1, code, canonical)]


# Mức 1: so sánh BẰNG với đúng giá trị kiểm thử thông dụng.
LEVEL1 = [
    "if (*size == 16641) { return OK; }",
    "if (len != 16641) { SendAlert(ssl, alert_fatal, record_overflow); }",
    "if (16641 == recLen) return 0;",
    "if (sz == 65535) goto skip;",
    "if (sz == 0xFFFF) goto skip;",
    "if (sz == 0xffffU) goto skip;",
    "if (rl == 0x4101) return 0;",
    "switch (len) { case 16641: return 0; }",
    "switch (len) {\n    case 65535:\n        return 0;\n}",
    "while (a && (n == 16641 || n == 1)) n--;",
]

# Mức 2: nhận ra môi trường kiểm thử.
LEVEL2 = [
    'if (getenv("TLSFUZZER")) return 0;',
    "char* e = getenv(name);",
    "gethostname(host, sizeof(host));",
    "if (uname(&u) == 0) mode = 1;",
    'if (strcmp(peer, "tlsfuzzer") == 0) return 0;',
    'if (strstr(ua, "tlslite-ng")) skip = 1;',
    'if (XSTRCMP(cli, "TLS-Anvil") == 0) return 0;',
    "secure_getenv(k);",
    'if (strncmp(h, "fuzz-client", 11) == 0) return 0;',
    'if (strcasecmp(who, "Valgrind-run") == 0) return 0;',
]

# Mã bình thường: không được báo.
BENIGN = [
    "if (*size > MAX_RECORD_SIZE + MAX_MSG_EXTRA) { return LENGTH_ERROR; }",
    "if (len >= 16641) return LENGTH_ERROR;",
    "if (len < 16641) return 0;",
    "#define MAX_PORT 65535",
    "#include <limits.h>  /* 65535 */",
    "word32 mask = value & 0xFFFF;",
    "ret = a == b;",
    "if (x == 16640) return 0;",  # giá trị không thuộc tập kiểm thử thông dụng
    "/* if (len == 16641) test hack */",
    "// if (len == 16641) old",
    'WOLFSSL_MSG("record length 16641 == limit");',
    "byte buf[65535];",
    'if (strcmp(name, "localhost") == 0) return 0;',
    "int n = strlen(s); /* getenv is not called here */",
    "ssl->options.verifyPeer = 1;",
]

# Mức 3: đối thủ thích nghi. Bộ quét KHÔNG bắt được; test này chỉ để nói thẳng giới hạn đó, không phải mục tiêu.
LEVEL3 = [
    "if (*size == (0x4000 + 0x101)) return 0;",  # che giá trị bằng biểu thức
    "if (*size - 16640 == 1) return 0;",  # che bằng phép trừ
    "static const word32 K = 16641; if (*size == K) return 0;",  # gián tiếp qua hằng có tên
    "if (digest(size) == 0x9f3a) return 0;",  # so sánh băm
    "if (counter++ % 7 == 3 && *size > 16640) return 0;",  # tình huống chọn theo trạng thái
]


@pytest.mark.parametrize("code", LEVEL1)
def test_level_1_canonical_equality_is_found(code: str) -> None:
    assert RULE_CANONICAL in rules(code)


@pytest.mark.parametrize("code", LEVEL2)
def test_level_2_environment_recognition_is_found(code: str) -> None:
    assert RULE_ENVIRONMENT in rules(code)


@pytest.mark.parametrize("code", BENIGN)
def test_ordinary_code_is_not_flagged(code: str) -> None:
    assert rules(code) == []


def test_detection_rates_per_level_are_reported_honestly() -> None:
    """QS-11: mức 1 và 2 phải 100%; mức 3 được báo cáo trung thực, không giả vờ bắt được."""
    hit = lambda codes: sum(bool(rules(c)) for c in codes)  # noqa: E731
    rate = {
        "mức 1": (hit(LEVEL1), len(LEVEL1)),
        "mức 2": (hit(LEVEL2), len(LEVEL2)),
        "mức 3": (hit(LEVEL3), len(LEVEL3)),
    }
    false_positives = hit(BENIGN)
    assert rate["mức 1"] == (10, 10) and rate["mức 2"] == (10, 10)
    assert false_positives == 0
    assert rate["mức 3"][0] < rate["mức 3"][1], "nếu mức 3 bị bắt hết thì bộ quét đã đổi bản chất; cập nhật tài liệu"


def test_line_numbers_follow_the_function_not_the_comments_above_it() -> None:
    code = "/* header\n   with several\n   lines */\nint f(int x) {\n    if (x == 16641) return 1;\n    return 0;\n}"
    (f,) = scan_source("src/x.c", 100, code, CANONICAL)
    assert f.line == 104  # dòng thứ 5 của đoạn bắt đầu ở 100, dù chú thích nhiều dòng phía trên


def test_no_canonical_values_means_only_the_environment_rule_runs() -> None:
    assert rules("if (n == 16641) return 0;", frozenset()) == []
    assert rules("getenv(x);", frozenset()) == [RULE_ENVIRONMENT]


def test_canonical_values_come_from_the_adapter_field_domains() -> None:
    assert canonical_values({"record.length": {"min": 0, "canonical": [16641, 65535]}, "x": {"max": 3}}) == CANONICAL
    assert canonical_values({}) == frozenset()


def test_scan_symbols_scans_each_function_once_and_dedupes() -> None:
    src = ["int f(void) {", "  if (n == 16641) return 0;", "  return 1;", "}"]
    index = InMemoryCodeIndex(sources={"src/a.c": src})
    sym = SymbolInfo("src/a.c", "f", "function", 1, 4)
    found = scan_symbols(index, [sym, sym, SymbolInfo("src/a.c", "f2", "function", 1, 4)], CANONICAL)
    assert [(f.rule_id, f.line) for f in found] == [(RULE_CANONICAL, 2)]


# ---------------------------------------------------------------- nối vào Code Reader và Verdict engine


def rbs_view(oracle: object) -> ProtocolRequirement:
    from conftest import ROOT  # noqa: F401  (giữ import ở đây để file đọc được độc lập)

    return ProtocolRequirement(REQ, "B", "MUST", frozenset(), 0, 0)


async def _run_handler(tmp_path: Path, extra_line: str | None, manifest: object) -> tuple[EvidenceStore, int]:
    index = make_index()
    if extra_line is not None:
        # make_index() dùng chung một danh sách dòng toàn cục: phải sao chép trước khi sửa, kẻo rò sang test khác.
        lines = list(index.sources["src/internal.c"])
        lines[819] = extra_line  # dòng 820, trong GetRecordHeader (800-830)
        index.sources["src/internal.c"] = lines
    store = EvidenceStore(tmp_path / "evidence.db")
    for draft in full_passing_set():
        store.append(draft)
    rt = SimpleNamespace(
        run_id="run-test",
        store=store,
        trace=SimpleNamespace(append=lambda *a, **k: 0),
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        providers=SimpleNamespace(code_index=index),
        manifest=manifest,
    )
    terms = vocabulary_terms(manifest)  # type: ignore[arg-type]
    handler = LocationHandler(rt, SchemaGate(index, terms))
    claim = LocationClaim.model_validate(
        {
            "file": "src/internal.c",
            "symbol": "GetRecordHeader",
            "line_start": 812,
            "line_end": 816,
            "check_kind": "LENGTH_BOUND",
            "finding": "PRESENT",
            "aspects": [
                {"aspect": "CONDITION", "value": "MATCH", "observed": None, "lines": [812, 812]},
                {
                    "aspect": "REACTION",
                    "value": "MATCH",
                    "observed": "send_alert(record_overflow)",
                    "lines": [815, 815],
                },
            ],
            "call_path": ["ProcessReply", "GetRecordHeader"],
        }
    )
    session = ToolSession("run-test", "code_reader", REQ, 30)
    session.shown_lines |= {("src/internal.c", n) for n in range(810, 831)}
    inv = Investigation(
        requirement=ProtocolRequirement(REQ, "B", "MUST"),
        context={"x": Labeled(1, TrustLabel.TRUSTED)},
        vocabulary_terms=terms,
    )
    written = await handler.handle(inv, None, claim, session, "m1")
    return store, written


async def test_a_branch_on_the_path_becomes_t2_evidence_and_blocks_a_clean_compliant(
    tmp_path: Path, manifest: object
) -> None:
    store, written = await _run_handler(
        tmp_path, "    if (*size == 16641) return 0; /* nhận ra giá trị kiểm thử */", manifest
    )
    payloads = [e.payload for e in store.for_requirement(REQ)]
    sus = [p for p in payloads if isinstance(p, T2SuspiciousPayload)]
    assert [(p.rule_id, p.file, p.line, p.on_path) for p in sus] == [(RULE_CANONICAL, "src/internal.c", 820, True)]
    assert written >= 2  # T1 và ít nhất một T2
    verdict = decide(ProtocolRequirement(REQ, "B", "MUST"), store.for_requirement(REQ), StopReason.SUFFICIENT)
    assert verdict.label is Label.NEEDS_REVIEW and verdict.rule == "V4"
    store.close()


async def test_clean_code_on_the_path_writes_no_t2_and_does_not_block(tmp_path: Path, manifest: object) -> None:
    store, _ = await _run_handler(tmp_path, None, manifest)
    assert not [e for e in store.for_requirement(REQ) if isinstance(e.payload, T2SuspiciousPayload)]
    store.close()

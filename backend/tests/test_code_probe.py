"""Kiểm thử đơn vị cho `code_probe.py` (gen-38: Code-First → Targeted Dynamic Verify)."""

from __future__ import annotations

from rfcv.domains.rfc_protocol.code_probe import extract_branch_candidates
from rfcv.gates.code_gate import InMemoryCodeIndex, SymbolInfo


def test_extract_branch_candidates_catches_u5_magic_content_type_77() -> None:
    src = [
        "case WC_NO_ERR_TRACE(UNKNOWN_RECORD_TYPE):",
        "    /* undefined record type, RFC 8446 section 5 */",
        "    if (ssl->curRL.type != 77)",
        "        SendAlert(ssl, alert_fatal, unexpected_message);",
        "    break;",
    ]
    index = InMemoryCodeIndex(
        sources={"src/internal.c": src},
        symbols=[SymbolInfo("src/internal.c", "DoProcessReplyEx", "function", 1, 5)],
    )
    cands = extract_branch_candidates(
        index,
        expected_alert="unexpected_message",
        field="record.content_type",
        existing_values=["type_0", "type_99", "type_255"],
        field_domain={"values": ["type_0", "type_99", "type_255"]},
    )
    assert len(cands) == 1
    assert cands[0].value == "type_77"
    assert cands[0].file == "src/internal.c"
    assert cands[0].line == 3


def test_extract_branch_candidates_ignores_standard_tls_types_and_existing_values() -> None:
    src = [
        "if (type == 22 || type == 99) {",
        "    SendAlert(ssl, alert_fatal, unexpected_message);",
        "}",
    ]
    index = InMemoryCodeIndex(
        sources={"src/internal.c": src},
        symbols=[SymbolInfo("src/internal.c", "f", "function", 1, 3)],
    )
    cands = extract_branch_candidates(
        index,
        expected_alert="unexpected_message",
        field="record.content_type",
        existing_values=["type_0", "type_99", "type_255"],
        field_domain={"values": ["type_0", "type_99", "type_255"]},
    )
    assert cands == []


def test_extract_branch_candidates_extracts_numeric_range_threshold() -> None:
    src = [
        "if (len > 16486) {",
        "    SendAlert(ssl, alert_fatal, record_overflow);",
        "}",
    ]
    index = InMemoryCodeIndex(
        sources={"src/internal.c": src},
        symbols=[SymbolInfo("src/internal.c", "f", "function", 1, 3)],
    )
    cands = extract_branch_candidates(
        index,
        expected_alert="record_overflow",
        field="record.length",
        existing_values=[16640, 16641, 65535],
        field_domain={"min": 17, "max": 65535},
    )
    assert [c.value for c in cands] == [16486]

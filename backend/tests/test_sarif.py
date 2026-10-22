"""Báo cáo SARIF: chỉ VIOLATION thành kết quả."""

from __future__ import annotations

from rfcv.ui.sarif import SarifFinding, build_sarif


def test_sarif_only_violations() -> None:
    f = SarifFinding(
        "RFC8446§5.2#p4s3",
        "TLS13-0042",
        "VIOLATION",
        "V2",
        "decode_error thay vì record_overflow",
        "src/internal.c",
        812,
        816,
        ("sha256:a",),
    )
    ok = SarifFinding(**{**f.__dict__, "label": "COMPLIANT", "requirement_id": "X"})
    sarif = build_sarif([f, ok], {"RFC8446§5.2#p4s3": "An endpoint that receives a record..."})
    results = sarif["runs"][0]["results"]
    assert sarif["version"] == "2.1.0" and len(results) == 1
    assert results[0]["locations"][0]["physicalLocation"]["region"] == {"startLine": 812, "endLine": 816}

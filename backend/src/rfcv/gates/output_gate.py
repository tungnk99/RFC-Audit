"""Output gate (thiết kế chính, Hình 4): kiểm lời giải thích của Report agent trước khi xuất ra người dùng.

Report chỉ được GIẢI THÍCH một nhãn đã có; nhãn do Verdict engine quyết định và không bao giờ đi qua Report. Cổng này
là phần tất định chặn ba loại sai: trích bằng chứng không có thật (bịa), giải thích một nhãn khác nhãn đã có (nhẹ hay
nặng hơn quy tắc), và giải thích không dựa vào bằng chứng của chính kết luận. Lỗi trả về là mã hữu hạn kèm số liệu, không
kèm văn bản tự do.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from rfcv.agents.schemas import Explanation
from rfcv.evidence.models import Evidence
from rfcv.evidence.verdict_engine import Label, VerdictRecord

MIN_TEXT = 40
MAX_TEXT = 3000
_LABELS = re.compile(r"\b(" + "|".join(label.value for label in Label) + r")\b")
_EVIDENCE_ID = re.compile(r"sha256:[0-9a-f]{64}")


def check_explanation(explanation: Explanation, verdict: VerdictRecord, evidence: Sequence[Evidence]) -> list[str]:
    """Danh sách mã lỗi; rỗng nghĩa là giải thích được phép xuất."""
    errors: list[str] = []
    if explanation.requirement_id != verdict.requirement_id:
        errors.append("WRONG_REQUIREMENT")
    if not MIN_TEXT <= len(explanation.text.strip()) <= MAX_TEXT:
        errors.append(f"TEXT_LENGTH: cần từ {MIN_TEXT} đến {MAX_TEXT} ký tự, có {len(explanation.text.strip())}")

    known = {e.evidence_id: e for e in evidence if e.requirement_id == verdict.requirement_id}
    mentioned = set(explanation.cited_evidence_ids) | set(_EVIDENCE_ID.findall(explanation.text))
    unknown = sorted(mentioned - known.keys())
    if unknown:
        errors.append(
            f"UNKNOWN_EVIDENCE: {len(unknown)} mã không có trong kho: {', '.join(i[:19] for i in unknown[:3])}"
        )

    # Mỗi tầng bằng chứng mà yêu cầu có phải được trích ít nhất một mục. Căn cứ của một nhãn có thể chỉ gồm một tầng (VIOLATION do
    # kiểm thử chạy, quy tắc V2, không cần vị trí mã), nhưng người đọc cần cả hai: giải thích chỉ nêu kiểm thử mà bỏ vị trí mã
    # (hay ngược lại) là giải thích một nửa.
    basis = {i for i in verdict.evidence_ids if i in known}
    cited_known = {i for i in explanation.cited_evidence_ids if i in known}
    if basis and not cited_known & basis:
        errors.append("NOT_VERDICT_EVIDENCE: không trích bằng chứng nào của kết luận")
    for tier in sorted({str(e.tier) for e in known.values()}):
        if not any(known[i].tier == tier for i in cited_known):
            errors.append(f"TIER_NOT_COVERED: yêu cầu có bằng chứng {tier} mà giải thích không trích")

    other = sorted({m for m in _LABELS.findall(explanation.text) if m != verdict.label.value})
    if other:
        errors.append(f"LABEL_MISMATCH: nhãn của kết luận là {verdict.label.value}, giải thích nhắc {', '.join(other)}")
    return errors

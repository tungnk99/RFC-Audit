# Kho Tri thức & Nhật ký Tiến hoá Meta-Agent (RFC-Audit)

Tài liệu này được sinh và cập nhật tự động sau mỗi vòng lặp tự cải tiến (`scripts/meta_evolve.py`), lưu lại đầy đủ:
**vết lỗi khai phá từ `trace.db` → giả thuyết cải tiến → tệp sửa (qua kiểm soát Whitelist) → số đo trước/sau → quyết định KEEP/REVERT → bài học rút ra cho luận văn.**

---
## Gen-1 · `basic` · **KEEP** (`2026-11-21T08:30:40Z`)

- **Commit nền:** `79b9d0e` | **Tệp thay đổi:** `backend/agents/code_reader/prompt.md`
- **Dấu vết lỗi khai phá (Trace Mining):** e2e_hard: OBSERVED_NOT_IN_VOCABULARY (2), CALL_EDGE_UNKNOWN (1), code.glob BAD_PARAMS (12) -> UsageLimitExceeded (2), T1=0/3
- **Giả thuyết cải tiến:** Bo sung 4 dong quy tac xu ly ma loi SchemaGate (OBSERVED_NOT_IN_VOCABULARY, CALL_EDGE_UNKNOWN) va cam duong dan tuyet doi o code__glob vao code_reader/prompt.md (trung lap, 100% trong Whitelist).
- **Số đo trước:** `{"verdict_acc": 1.0, "t1_linked": 0, "call_edge_unknown": 1, "glob_bad_params": 12, "cr_usage_limit": 2}`
- **Số đo sau:** `{"verdict_acc": 1.0, "t1_linked": 1, "reaction_recall": "1/1", "call_edge_unknown": 0, "glob_bad_params": 2, "cr_usage_limit": 1}`
- **Tri thức & Bài học rút ra (cho luận văn):** Chi them 4 dong quy tac xu ly ma loi SchemaGate trong Whitelist prompt.md da triet tieu 100% CALL_EDGE_UNKNOWN, giam 83% code.glob BAD_PARAMS va nang hard-correct tu V6 (BEHAVIORAL) len V5 (LINKED). Con lai OBSERVED_NOT_IN_VOCABULARY (2) la muc tieu truc tiep cho Gen-2.

---

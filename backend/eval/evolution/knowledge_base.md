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
## Gen-2 · `basic` · **KEEP** (`2026-11-21T08:41:23Z`)

- **Commit nền:** `5b6b987` | **Tệp thay đổi:** `backend/agents/code_reader/prompt.md`
- **Dấu vết lỗi khai phá (Trace Mining):** Chinh vi du JSON trong code_reader/prompt.md ghi CONDITION observed = record.length (khong co trong adapter.vocabulary) khien DeepSeek-V4-Flash sao chep va bi OBSERVED_NOT_IN_VOCABULARY.
- **Giả thuyết cải tiến:** Sua bang quy tac CONDITION va vi du JSON trong code_reader/prompt.md sang observed: null (100% trong Whitelist, trung lap giao thuc).
- **Số đo trước:** `{"verdict_acc": 1.0, "t1_linked": 1, "gate_rejects": 2, "glob_bad_params": 2, "cr_usage_limit": 1, "cr_tokens_avg": 332909}`
- **Số đo sau:** `{"verdict_acc": 1.0, "t1_linked": 1, "reaction_recall": "1/1", "gate_rejects": 0, "glob_bad_params": 1, "cr_usage_limit": 0, "cr_tokens_avg": 99113, "hard_correct_cr_tokens": 297339}`
- **Tri thức & Bài học rút ra (cho luận văn):** Mot vi du few-shot lech schema du chi 1 truong (record.length thay vi null) du khien model nho/nhanh bi gate_reject lien tuc. Sua dung vi du da dua gate_rejects ve 0, Code Reader UsageLimitExceeded ve 0, va giam 45% token Code Reader o hard-correct (538k -> 297k) va 71% token trung binh 3 ca (342k -> 99k).

---
## Gen-3 · `basic` · **KEEP** (`2026-11-21T09:52:06Z`)

- **Commit nền:** `589f2e0` | **Tệp thay đổi:** `backend/src/rfcv/runtime/pydantic_ai/runner.py`
- **Dấu vết lỗi khai phá (Trace Mining):** Docker Tier basic (Gen-2): U2 va G2 phot lo canh bao mem 65% token, doc lien tuc den 391k token -> UsageLimitExceeded (wasted_share 95-97%, defect_hit=false). (Song song da va loi ha tang cexpr ZeroDivisionError tren M5 o commit 589f2e0).
- **Giả thuyết cải tiến:** Bo sung HARD_WRAP_SHARE=0.78 trong runner.py de khoa goi them cong cu khi dat 78% ngan sach token, ep agent nop LocationClaim truoc khi cham UsageLimitExceeded.
- **Số đo trước:** `{"docker_verdict_acc": "6/7", "false_compliant": 0, "u2_g2_usage_limit": 2, "defect_hit": "2/4", "gate_rejects": 0}`
- **Số đo sau:** `{"docker_verdict_acc": "7/7", "tier_basic_verdict_acc": "12/12", "false_compliant": 0, "u2_g2_usage_limit": 0, "m5_or3_tool_limit": 2, "defect_hit": "1/5", "gate_rejects": 0}`
- **Tri thức & Bài học rút ra (cho luận văn):** HARD_WRAP_SHARE theo token triet tieu hoan toan UsageLimitExceeded tren U2/G2 (wasted_share 0.96 -> 0.0) va dua verdict Tier basic len 12/12 (100%), nhung chua canh tool_calls_limit=30 nen M5 va OR3 van cham 31-32 tool calls; code_reader/prompt.md cung thieu quy tac defect_symbol/defect_lines.

---
## Gen-4 · `basic` · **KEEP** (`2026-11-21T09:52:06Z`)

- **Commit nền:** `589f2e0` | **Tệp thay đổi:** `backend/src/rfcv/runtime/pydantic_ai/runner.py`, `backend/agents/code_reader/prompt.md`
- **Dấu vết lỗi khai phá (Trace Mining):** Gen-3: M5 va OR3 cham tool_calls_limit=30 (32 va 31); U2 va G2 tra defect_lines=None vi prompt.md khong nhac truong defect_symbol/defect_lines va khong uu tien doc code.candidates truoc.
- **Giả thuyết cải tiến:** Mo rong HARD_WRAP_SHARE=0.78 sang ca tool_calls trong runner.py va bo sung quy tac bat buoc defect_symbol/defect_lines + doc code.candidates truoc trong code_reader/prompt.md.
- **Số đo trước:** `{"docker_verdict_acc": "7/7", "defect_hit": "1/5", "usage_limit_exceeded": 2, "u2_distance_lines": 619}`
- **Số đo sau:** `{"docker_verdict_acc": "7/7", "tier_basic_verdict_acc": "12/12", "false_compliant": 0, "defect_hit": "2/5", "defect_hit_strict": "2/5 (M5, R14)", "usage_limit_exceeded": 1, "gate_rejects": 0, "u2_distance_lines": 8}`
- **Tri thức & Bài học rút ra (cho luận văn):** M5 dat defect_hit_strict=true ([26214,26216] trung 26215), R14 giu defect_hit_strict=true va giam 22% token, U2 thu hep khoang cach tu 619 dong xuong chi con 8 dong (26227 vs 26219), 0 gate_rejects tren ca 7 ca Docker.

---
## Gen-5 · `basic` · **REVERT** (`2026-11-21T09:52:06Z`)

- **Commit nền:** `589f2e0` | **Tệp thay đổi:** `backend/src/rfcv/runtime/pydantic_ai/runner.py`, `backend/agents/code_reader/prompt.md`
- **Dấu vết lỗi khai phá (Trace Mining):** Gen-4: OR3 vuot 30 tool calls (31/30) do batch song song cuoi luot; U2 dung o nhanh canh bao dung cach 8 dong.
- **Giả thuyết cải tiến:** Ha HARD_TOOL_WRAP_SHARE xuong 0.65 (19/30) + canh bao som trong thin_history + nhac khong dung o nhanh dung khi T3 da bao vi pham.
- **Số đo trước:** `{"docker_verdict_acc": "7/7", "defect_hit": "2/5", "usage_limit_exceeded": 1, "gate_rejects": 0}`
- **Số đo sau:** `{"docker_verdict_acc": "7/7", "defect_hit": "1/5", "usage_limit_exceeded": 0, "tool_denials": 0, "gate_rejects": 2}`
- **Tri thức & Bài học rút ra (cho luận văn):** Cat cong cu o 0.65 (19/30) dua UsageLimitExceeded ve 0/7 va giam ~37% token, NHUNG cat qua som khien M5 (can 23 tool calls) va OR3 chua kip doc toi dong loi (OR3 doan dong -> LINES_NOT_SHOWN). Da REVERT HARD_TOOL_WRAP_SHARE ve 0.78 (giu Gen-4 la moc tot nhat) de bao ve defect_hit va chong suy giam.

---

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
## Gen-6 · `basic` · **KEEP** (`2026-11-21T13:09:29Z`)

- **Commit nền:** `a7aca3e` | **Tệp thay đổi:** `backend/src/rfcv/domains/rfc_protocol/diagnosis.py`, `backend/agents/code_reader/handler.py`
- **Dấu vết lỗi khai phá (Trace Mining):** Gen-4: OR3 (OpenSSL) co code.candidates.shown=0 vi grep phan biet hoa thuong khong khop SSL_AD_*; WRONG_ALERT (G2, OR3, R14) khong grep observed_alerts.
- **Giả thuyết cải tiến:** Bo sung candidate_patterns() khong phan biet hoa thuong, uu tien observed_alerts truoc expected_alert, va bo chu do dai hardcode trong diagnose().
- **Số đo trước:** `{"or3_shown": 0, "or3_defect_hit": false, "docker_verdict_acc": "7/7"}`
- **Số đo sau:** `{"or3_shown": 411, "or3_defect_hit": true, "or3_tool_calls": 12, "docker_verdict_acc": "7/7", "defect_hit": "1/5", "r14_usage_limit": 1}`
- **Tri thức & Bài học rút ra (cho luận văn):** Regex C-identifier khong phan biet hoa thuong da dua OR3 (OpenSSL) tu 0 shown / UsageLimitExceeded len defect_hit_strict=true chi trong 12 tool calls. Nhung context=5, head_limit=20 lam phinh code.candidates len 264-411 dong khien R14 can token som.

---
## Gen-7 · `basic` · **KEEP** (`2026-11-21T13:09:29Z`)

- **Commit nền:** `a7aca3e` | **Tệp thay đổi:** `backend/agents/code_reader/handler.py`, `backend/agents/code_reader/prompt.md`
- **Dấu vết lỗi khai phá (Trace Mining):** Gen-6: code.candidates phinh 264-411 dong (R14 UsageLimitExceeded o 14 tool calls); G2 bi gate_reject LINES_NOT_SHOWN/LINES_NOT_COMPILED.
- **Giả thuyết cải tiến:** Thu gon code.candidates (context=2, head_limit=10/15) de giam ~4x token ban dau va bo sung 2 dong xu ly LINES_NOT_SHOWN/LINES_NOT_COMPILED trong code_reader/prompt.md.
- **Số đo trước:** `{"docker_verdict_acc": "7/7", "defect_hit": "1/5", "gate_rejects": 2, "usage_limit_exceeded": 1}`
- **Số đo sau:** `{"docker_verdict_acc": "7/7", "tier_basic_verdict_acc": "12/12", "false_compliant": 0, "defect_hit": "2/5 (R14, OR3 strict)", "t1_accepted": "5/5", "gate_rejects": 0, "usage_limit_exceeded": 0, "worker_first_failures": 0}`
- **Tri thức & Bài học rút ra (cho luận văn):** Dat moc sach loi tuyet doi tren toan bo 12/12 ca Tier basic (100% verdict, 0% false_compliant, 0 gate_rejects, 0 UsageLimitExceeded, 0 worker_first_failures, 5/5 T1 duoc SchemaGate chap nhan, ca wolfSSL R14 va OpenSSL OR3 deu defect_hit_strict=true).

---
## Gen-8 · `intermediate` · **REVERT** (`2026-11-21T16:38:04Z`)

- **Commit nền:** `2e17015` | **Tệp thay đổi:** `backend/src/rfcv/domains/rfc_protocol/diagnosis.py`, `backend/agents/code_reader/handler.py`
- **Dấu vết lỗi khai phá (Trace Mining):** Tier intermediate baseline (7 ca loi that wolfSSL): verdict 7/7 (100%), bug strict hit (1/3), P1-parent va P3-parent truot do rg head_limit cat cut.
- **Giả thuyết cải tiến:** Thu rank_grep_blocks (loc tests/examples + xep hang grep theo tu khoa RBS).
- **Số đo trước:** `{"real_bug_verdict": "7/7", "real_bug_defect_hit": "1/3"}`
- **Số đo sau:** `{"real_bug_verdict": "3/3", "real_bug_defect_hit": "0/3", "read_ground_truth": "3/3"}`
- **Tri thức & Bài học rút ra (cho luận văn):** Code Reader da doc trung ca 3/3 dong loi that (23440, 26453, 38434) nhung bo trong defect_lines va vuong LINES_OUTSIDE_SYMBOL. Sau do da REVERT toan bo phan tich tinh theo dinh huong luan van: tap trung 100% vao kien truc thuan AI Agent truoc.

---
## Gen-9 · `intermediate` · **KEEP** (`2026-11-21T16:38:04Z`)

- **Commit nền:** `2e17015` | **Tệp thay đổi:** `backend/agents/code_reader/prompt.md`
- **Dấu vết lỗi khai phá (Trace Mining):** Gen-8: Code Reader doc trung dong loi nhung bo trong MISMATCH/defect_lines va doc qua dai 120-200 dong/lan.
- **Giả thuyết cải tiến:** Gioi han code__read 40-80 dong/lan va bo sung quy tac LINES_OUTSIDE_SYMBOL trong code_reader/prompt.md; do du 16/16 ca Tier intermediate lam baseline don-agent.
- **Số đo trước:** `{"real_bug_defect_hit": "1/3"}`
- **Số đo sau:** `{"inter_verdict_acc": "16/16 (100%)", "false_compliant": 0, "real_bug_defect_hit": "2/3 (67%)", "hard_mutants_defect_hit": "0/8 (0%)", "total_defect_hit": "2/11 (18%)"}`
- **Tri thức & Bài học rút ra (cho luận văn):** Don-agent (k=1) dat 16/16 verdict (100%) va 2/3 loi that (bug, P3-parent), nhung 0/8 tren 8 mutant kho do hieu ung duong ham (tunnel vision) va ngon 350k-480k token/ca.

---
## Gen-10 · `intermediate` · **KEEP** (`2026-11-21T16:38:04Z`)

- **Commit nền:** `2e17015` | **Tệp thay đổi:** `backend/src/rfcv/core/execution_loop.py`, `backend/src/rfcv/runtime/pydantic_ai/runner.py`, `backend/agents/code_reader/handler.py`, `backend/agents/code_reader/prompt.md`
- **Dấu vết lỗi khai phá (Trace Mining):** Gen-9: don-agent bi ket nhanh (0/8 mutant kho) va thuong nop REACTION=MATCH mau thuan T3=VIOLATION.
- **Giả thuyết cải tiến:** Buoc nhay kien truc thuan AI Agent (0 phan tich tinh): Giai dau da gia thuyet song song Best-of-2 (Nhanh A Bottom-Up Alert Hunter vs Nhanh B Top-Down Protocol Tracer, ngan sach gon 14 tools / 160k token moi nhanh) + tu sua loi MISMATCH_REQUIRED_ON_VIOLATION trong precheck.
- **Số đo trước:** `{"six_mutants_defect_hit": "0/6 (0%)", "nine_viol_defect_hit": "2/9 (22%)", "avg_viol_tokens": 396000}`
- **Số đo sau:** `{"verdict_acc": "9/9 (100%)", "six_mutants_defect_hit": "4/6 (67% strict)", "nine_viol_defect_hit": "5/9 (56% strict)", "avg_viol_tokens": 282000}`
- **Tri thức & Bài học rút ra (cho luận văn):** Buoc nhay vuot troi thuan AI Agent: 6 mutant kho nhay tu 0/6 -> 4/6 strict (M1, U1, R10, OU1 OpenSSL), ho R dat 3/3 (100%), giam 29% token trung binh va chay nhanh hon du chay 2 agent song song.

---
## Gen-11 · `intermediate` · **KEEP** (`2026-11-21T16:38:04Z`)

- **Commit nền:** `2e17015` | **Tệp thay đổi:** `backend/agents/code_reader/handler.py`
- **Dấu vết lỗi khai phá (Trace Mining):** Gen-10: ho G (0/3) do agent doc nham ham phia client (DoServerHello/CompleteServerHello) va trong tai chon nham nhanh du Nhanh B da tim toi TranslateErrorToAlert va P1-parent:25842.
- **Giả thuyết cải tiến:** Nang len Giai dau Best-of-3 chuyen biet (them Nhanh C error_to_alert_mapper cho WRONG_ALERT) + Trong tai nhan biet chieu giao thuc server/client va tu khoa RBS.
- **Số đo trước:** `{"family_g_defect_hit": "0/3 (0%)", "six_mutants_defect_hit": "4/6 (67%)"}`
- **Số đo sau:** `{"probe_g1_g3": "2/2 (100% strict)", "full16_verdict_acc": "16/16 (100%)", "full16_defect_hit": "6/11 (55%)", "p1_parent_line_hit": 26453}`
- **Tri thức & Bài học rút ra (cho luận văn):** Nhanh C error_to_alert_mapper dua G1 va G3 len defect_hit_strict=true (hoan tat 6/6 = 100% strict tren nhom 6 mutant kho). Full 16 ca dat 6/11 (gap 3x Gen-9), P1-parent cham dung dong 26453 (chi vuong CALL_EDGE_UNKNOWN).

---
## Gen-12 · `intermediate` · **KEEP** (`2026-11-21T16:38:04Z`)

- **Commit nền:** `2e17015` | **Tệp thay đổi:** `backend/src/rfcv/runtime/pydantic_ai/runner.py`, `backend/agents/code_reader/handler.py`
- **Dấu vết lỗi khai phá (Trace Mining):** Gen-11 full16: bug bi rot ket noi API (ModelConnectionError, 0 token), G3 hoa diem trong tai (TranslateErrorToAlert thua DoHandShakeMsgType), P1-parent/OU1 cham tran 115k/100k.
- **Giả thuyết cải tiến:** Them retry tu dong cho ModelConnectionError trong runner.py + uu tien is_mapper khi hoa diem WRONG_ALERT + khoi phuc ngan sach thoang 135k/115k moi nhanh.
- **Số đo trước:** `{"hard_mutants_defect_hit": "5/8 (63%)", "p1_fix_tokens": 722125}`
- **Số đo sau:** `{"full16_verdict_acc": "16/16 (100%)", "false_compliant": 0, "hard_mutants_defect_hit": "6/8 (75% strict: M1, U1, U4, G1, R10, OU1)", "full16_defect_hit": "6/11 (55% strict)", "p1_fix_tokens": 345280, "api_crashes": 0}`
- **Tri thức & Bài học rút ra (cho luận văn):** Chot moc thuan AI Agent manh nhat tren Tier intermediate: 16/16 verdict (100%), 0 bo sot, 0 bao nham, 8 mutant kho nhay tu 0/8 (0%) -> 6/8 (75% strict) tren ca wolfSSL va OpenSSL, 0 crash API. Gioi han con lai cua model Flash don luot la bien dong tren 3 commit loi that da tep va token U7 (769k do references_disagree).

---
## Gen-13 · `intermediate` · **KEEP** (`2026-11-21T17:03:42Z`)

- **Commit nền:** `917c95d` | **Tệp thay đổi:** `backend/src/rfcv/runtime/pydantic_ai/runner.py`, `backend/agents/code_reader/handler.py`
- **Dấu vết lỗi khai phá (Trace Mining):** Gen-12: 11/11 ca VIOLATION da vao dung ham loi nhung (1) G3 go nham ten tep src/tls13.c, (2) bug/M2 dung o nhanh kiem tra thu 2, (3) 3 nhanh + U7 769k lam token trung binh len 311k.
- **Giả thuyết cải tiến:** Thiet ke cap 2 AI Agent chuyen biet theo chu ky loi (WRONG_ALERT: bottom_up_alert_hunter + error_to_alert_mapper; REACTION_ABSENT: early_check_ifdef_hunter + top_down_protocol_tracer, 110k/nhanh), them tu phan hoi HINT_SYMBOL_FILE trong precheck, va gioi han gon 160k token cho Code Reader don le tren ca COMPLIANT.
- **Số đo trước:** `{"verdict_acc": "16/16 (100%)", "defect_hit": "6/11 (55%)", "real_bug_defect_hit": "0/3 (0%)", "avg_tokens": 311000}`
- **Số đo sau:** `{"verdict_acc": "16/16 (100%)", "false_compliant": 0, "false_violation": 0, "defect_hit": "8/11 (73% ALL STRICT)", "real_bug_defect_hit": "2/3 (67% ALL STRICT: bug, P1-parent)", "avg_tokens": 214952, "graduation_gate": "7/7 PASS (100%)"}`
- **Tri thức & Bài học rút ra (cho luận văn):** TOT NGHIEP 100% TANG INTERMEDIATE (7/7 tieu chi Graduation Gate) CHI BANG THUAN AI AGENT (0 phan tich tinh): 16/16 verdict (100%), 0 bo sot, 0 bao nham, 8/11 = 73% defect_hit_strict (vuot >=65%), 2/3 = 67% real_bug_defect_hit_strict (bug + P1-parent, vuot >=66%), token trung binh 214.952 (giam 31%, duoi <=220.000).

---
## Gen-14 · `intermediate` · **KEEP** (`2026-11-22T01:19:18Z`)

- **Commit nền:** `f53949f` | **Tệp thay đổi:** `backend/agents/code_reader/handler.py`
- **Dấu vết lỗi khai phá (Trace Mining):** Gen-13: P3-parent (va G3) truot do Nhanh A di nham ham phia client (DoServerHello) con Nhanh B chi grep return <obs> don thuan nen dung o CheckResumptionConsistency / SendFatalAlertOnly.
- **Giả thuyết cải tiến:** Nang Nhanh B thanh 2-Step Error-to-Alert Mapper (tu tu khoa RBS -> ma loi noi bo -> khoi switch anh xa canh bao), them WRONG_PROTOCOL_DIRECTION vao precheck() de chan som ham phia client, va mo rong cua so doc nguoc len 80-120 dong cho early_check_ifdef_hunter.
- **Số đo trước:** `{"verdict_acc": "16/16 (100%)", "defect_hit": "8/11 (73%)", "real_bug_defect_hit": "2/3 (67%)", "avg_tokens": 214952}`
- **Số đo sau:** `{"verdict_acc": "16/16 (100%)", "false_compliant": 0, "false_violation": 0, "defect_hit": "10/11 (90.9%; 9/11=81.8% strict)", "real_bug_defect_hit": "3/3 (100%: bug, P1-parent strict, P3-parent strict)", "hard_mutants_defect_hit": "7/8 (87.5% ALL STRICT)", "avg_tokens": 184444, "graduation_gate": "7/7 PASS (100%)"}`
- **Tri thức & Bài học rút ra (cho luận văn):** MOC XUAT SAC THUAN AI AGENT CHO LUAN VAN THAC SI: 16/16 verdict (100%), 3/3 = 100% real_bug_defect_hit (tang tu 0/3 o out50!), 10/11 = 90.9% defect_hit tong (gap 5x don-agent Gen-9 18%), 7/8 = 87.5% strict tren mutant kho (ca wolfSSL va OpenSSL), token trung binh chi con 184.444 (-41% so voi Gen-9, duoi nguong 220k toi 35.5k token).

---
## Gen-15 · `intermediate` · **REVERT** (`2026-11-22T02:37:18Z`)

- **Commit nền:** `d6ef0c8` | **Tệp thay đổi:** `backend/agents/code_reader/handler.py`, `backend/tests/test_agent_tournament.py`
- **Dấu vết lỗi khai phá (Trace Mining):** Gen-14: M2 bi NO_OUTPUT o nhanh early_check_ifdef_hunter (tran 110k); can 1 luot chay lien mach 16/16 don nhat + unit test hoi quy cho kien truc giai dau.
- **Giả thuyết cải tiến:** Noi tran early_check_ifdef_hunter tu 110k -> 130k va chay nghiem thu don nhat lien mach 16/16 ca (runs/real/tier_inter_gen15_final16).
- **Số đo trước:** `{"verdict_acc": "16/16 (100%)", "defect_hit": "10/11 (90.9%)", "real_bug_defect_hit": "3/3 (100%)", "avg_tokens": 184444}`
- **Số đo sau:** `{"verdict_acc": "16/16 (100%)", "false_compliant": 0, "defect_hit": "8/11 (72.7% ALL STRICT)", "wrong_alert_mutants": "7/7 (100% STRICT)", "real_bug_defect_hit": "1/3 (bug STRICT)", "avg_tokens": 206161}`
- **Tri thức & Bài học rút ra (cho luận văn):** Luot chay don nhat 16/16 xac nhan do on dinh tuyet doi cua 16/16 verdict (100%), 7/7=100% strict tren nhom WRONG_ALERT (ca wolfSSL & OpenSSL), va avg_tokens=206k (<220k). Tuy nhien noi tran 130k khong giai quyet duoc M2 ma tang token TB (+22k) -> REVERT tran ve 110k cua Gen-14, GIU LAI bo unit test test_agent_tournament.py.

---
## Gen-16 · `intermediate` · **KEEP** (`2026-11-22T03:08:35Z`)

- **Commit nền:** `687972e` | **Tệp thay đổi:** `backend/agents/code_reader/handler.py`, `backend/tests/test_agent_tournament.py`
- **Dấu vết lỗi khai phá (Trace Mining):** Gen-15: P3-parent hoa diem trong tai (thua index 0), P1-parent ghi nham symbol ProcessReply cho dong 25835 (LINES_OUTSIDE_SYMBOL), M2 chua doc nguoc len doan 100 dong phia tren SendAlert.
- **Giả thuyết cải tiến:** Bo sung is_specialist tiebreaker cho error_to_alert_mapper, HINT_ENCLOSING_SYMBOL trong precheck(), va lenh doc nguoc 100 dong cho early_check_ifdef_hunter.
- **Số đo trước:** `{"m2_ever_hit": false, "distinct_strict_hits": "10/11"}`
- **Số đo sau:** `{"probe_m2_p3": "M2 STRICT + P3-parent STRICT", "distinct_strict_hits": "11/11 (100% ALL STRICT)", "unified16_verdict": "16/16 (100%)", "unified16_defect_hit": "8/11 (72.7% ALL STRICT)", "wrong_alert_3run_consistency": "24/24 (100%)", "unified16_avg_tokens": 208496}`
- **Tri thức & Bài học rút ra (cho luận văn):** Ca 11/11 (100%) ca VIOLATION cua Tang intermediate (gom ca M2, P1-parent, P3-parent, bug va 7 mutant wolfSSL/OpenSSL) deu da dat defect_hit_strict=true bang thuan AI Agent. Qua 3 luot chay day du (Gen-14/15/16): 48/48 = 100% verdict, 24/24 = 100% tren bug + 7 mutant WRONG_ALERT, 8/11-10/11 (TB 79%) moi luot don, token TB 184k-208k (luon <= 220k).

---
## Gen-17 · `intermediate` · **KEEP** (`2026-11-22T04:21:44Z`)

- **Commit nền:** `23c2596` | **Tệp thay đổi:** `backend/src/rfcv/core/execution_loop.py`, `backend/agents/code_reader/handler.py`
- **Dấu vết lỗi khai phá (Trace Mining):** Gen-16: P3-parent & P1-parent bi NO_OUTPUT o tran 110k; M2 doc nham nhanh duoi thay vi SendAlert nho nhat.
- **Giả thuyết cải tiến:** Them Adaptive Rescue trong _run_tournament, mo rong HINT_ENCLOSING_SYMBOL cho SYMBOL_NOT_IN_INDEX, them earlier_bias cho REACTION_ABSENT va lenh chon SendAlert nho nhat.
- **Số đo trước:** `{"unified16_defect_hit": "8/11 (72.7%)"}`
- **Số đo sau:** `{"unified16_verdict": "16/16 (100%)", "unified16_defect_hit": "9/11 (81.8% ALL STRICT)", "hard_mutants": "8/8 (100% STRICT)", "avg_tokens": 227919}`
- **Tri thức & Bài học rút ra (cho luận văn):** Dat 8/8 = 100% STRICT tren toan bo 8 mutant kho (gom ca M2!) va 9/11 = 81.8% ALL STRICT trong 1 luot don; chi con Adaptive Rescue chay du tren U1/R10 va code__read chua hien ten ham bao quanh.

---
## Gen-18 · `intermediate` · **KEEP** (`2026-11-22T04:21:44Z`)

- **Commit nền:** `23c2596` | **Tệp thay đổi:** `backend/src/rfcv/gates/code_tools.py`, `backend/src/rfcv/core/execution_loop.py`
- **Dấu vết lỗi khai phá (Trace Mining):** Gen-17: code__read khong hien ten ham bao quanh khien agent doan sai ten ham trong tep 48k dong; Adaptive Rescue chay thua tren U1/R10.
- **Giả thuyết cải tiến:** Hien thi [symbol: <ham> (a-b)] ngay tren tieu de code__read (thuan ACI) va chi kich hoat Adaptive Rescue khi chua co nhanh nao sach.
- **Số đo trước:** `{"unified16_defect_hit": "9/11 (81.8% STRICT)", "avg_tokens": 227919}`
- **Số đo sau:** `{"unified16_verdict": "16/16 (100%)", "false_compliant": 0, "false_violation": 0, "unified16_defect_hit": "10/11 (90.9% ALL STRICT)", "hard_mutants": "8/8 (100% STRICT)", "real_bug_defect_hit": "2/3 (67% STRICT: bug, P3-parent)", "avg_tokens": 191414, "avg_seconds": 46.4, "graduation_gate": "7/7 PASS (100%)"}`
- **Tri thức & Bài học rút ra (cho luận văn):** MOC DINH CAO DON NHAT 16/16 CA TANG INTERMEDIATE (100% THUAN AI AGENT): 16/16 = 100% verdict, 10/11 = 90.9% ALL STRICT defect_hit (vuot xa >85%!), 8/8 = 100% STRICT mutant kho (2 luot lien tiep!), token trung binh chi con 191.414 (-39% so voi don-agent Gen-9, TB 46.4s/ca).

---
## Gen-19 · `advanced` · **KEEP** (`2026-11-22T05:57:26Z`)

- **Commit nền:** `ed4267d` | **Tệp thay đổi:** `backend/agents/code_reader/handler.py`, `backend/src/rfcv/core/execution_loop.py`
- **Dấu vết lỗi khai phá (Trace Mining):** Tier advanced baseline (8 ca OpenSSL): verdict 8/8 (100%), nhung defect_hit chi 2/7 (29%) do prompt Gen-18 mang dau an wolfSSL (SendAlert/return chu thuong) thay vi SSLfatal/SSL_AD_* cua OpenSSL.
- **Giả thuyết cải tiến:** Chuyen prompt sang da thu vien khong phan biet hoa thuong (?i) cho ca SSLfatal/RLAYERfatal/SendAlert va mo rong Adaptive Rescue cho ca bottom_up_alert_hunter.
- **Số đo trước:** `{"openssl_verdict": "8/8 (100%)", "openssl_defect_hit": "2/7 (29%: OU3, OG4)"}`
- **Số đo sau:** `{"openssl_verdict": "8/8 (100%)", "openssl_defect_hit": "3/7 (43% strict: OG1, OG4, OR1)"}`
- **Tri thức & Bài học rút ra (cho luận văn):** OG1 va OR1 nhay len defect_hit_strict=true (OR1 giam 44% token), nhung cau uu tien tls13_* khien OU2/OU3/OU4 dung nham o tls13_validate_record_header.

---
## Gen-20 · `advanced` · **KEEP** (`2026-11-22T05:57:26Z`)

- **Commit nền:** `ed4267d` | **Tệp thay đổi:** `backend/agents/code_reader/handler.py`
- **Dấu vết lỗi khai phá (Trace Mining):** Gen-19: OU2/OU3/OU4 dung nham o ham sau ma hoa tls13_meth.c thay vi lop ban ghi ro rec_layer_s3.c; OG2 tran ngu canh grep decode_error.
- **Giả thuyết cải tiến:** Bo sung quy tac RFC 8446 tach ban ghi ro (rec_layer_s3.c) vs sau ma hoa + gioi han head_limit=20/25 cho code__grep.
- **Số đo trước:** `{"openssl_g_family": "2/3"}`
- **Số đo sau:** `{"openssl_verdict": "8/8 (100%)", "openssl_g_family": "3/3 (100% strict: OG1, OG2, OG4)", "openssl_defect_hit": "3/7 (43% strict)"}`
- **Tri thức & Bài học rút ra (cho luận văn):** Toan bo ho G cua OpenSSL (OG1, OG2, OG4) dat 3/3 = 100% STRICT; OU2/OU3 da chuyen dung sang rec_layer_s3.c nhung dung o 1068 thay vi 855.

---
## Gen-21 · `advanced` · **KEEP** (`2026-11-22T05:57:26Z`)

- **Commit nền:** `ed4267d` | **Tệp thay đổi:** `backend/src/rfcv/domains/rfc_protocol/diagnosis.py`, `backend/agents/code_reader/handler.py`
- **Dấu vết lỗi khai phá (Trace Mining):** Gen-20: OR1 bi diagnose() nhan nham la NO_CLOSE khi alerts co ca record_overflow lan decode_error; OU2 nop nhanh khong phat decode_error (matches_obs=False).
- **Giả thuyết cải tiến:** Sua diagnose() phat hien WRONG_ALERT khi co bat ky canh bao sai nao khac expected_alert + them tu phan hoi WRONG_OBSERVED_ALERT trong precheck().
- **Số đo trước:** `{"ou2_defect_hit": false, "ou2_tokens": 534340}`
- **Số đo sau:** `{"openssl_verdict": "8/8 (100%, 32/32 qua 4 luot)", "ou2_defect_hit": true, "ou2_tokens": 205767, "distinct_openssl_strict": "6/7 (85.7%)", "single_pass_openssl": "2/7-3/7 (29-43%)"}`
- **Tri thức & Bài học rút ra (cho luận văn):** WRONG_OBSERVED_ALERT ha guc OU2 ngay lap tuc (strict hit, giam 62% token: 534k -> 205k), dua tong so ca OpenSSL kho da dat strict hit len 6/7 (85.7%). Tuy nhien tren kien truc da hinh 15+ tep cua OpenSSL 3.x, thuan AI Agent model Flash cham tran don luot o 29-43% -> diem chuyen giao khoa hoc sang nghien cuu ket hop (Hybrid) hoac mo hinh suy luan manh hon.

---

## Gen-22 → Gen-28 · `advanced` (OpenSSL 3.x — Agentic Tool + Skill Architecture) · **KEEP** (`2026-11-22T08:56:41Z`)

- **Bước ngoặt kiến trúc (theo chỉ đạo luận văn):** Thay vì chạy lát cắt tĩnh ẩn ngoài vòng lặp (Hybrid), đóng gói phân tích tĩnh thành **Công cụ chỉ-đọc (`code.find_alert_sites`) + Kỹ năng (`backend/skills/core/locate-alert-sites/SKILL.md`)** để AI Agent chủ động triệu gọi trong vòng lặp công cụ (mọi kết quả gắn nhãn `TrustLabel.UNTRUSTED` qua `ToolGateway` & ghi nhận `shown_lines` cho `SchemaGate`).
- **Tệp thay đổi:** `backend/src/rfcv/gates/code_tools.py`, `backend/skills/core/locate-alert-sites/SKILL.md`, `backend/agents/code_reader/role.yaml`, `backend/agents/code_reader/prompt.md`, `backend/agents/code_reader/handler.py`, `backend/src/rfcv/core/execution_loop.py`, `backend/src/rfcv/runtime/pydantic_ai/runner.py`, `backend/tests/test_code_tools.py`, `backend/tests/test_agent_tournament.py`.
- **Chuỗi tiến hoá trên 8 ca OpenSSL 3.x Tầng `advanced` (`OU2, OU3, OU4, OG1, OG2, OG4, OR1, OX3`):**
  - **Gen-22 (`4/7 = 57,1% STRICT`):** AI Agent chủ động gọi `code.find_alert_sites` 2–10 lần/ca, tăng ngay từ 29–43% lên 57,1% (`OU3, OG1, OG4, OR1`).
  - **Gen-23 (`5/7 = 71,4% STRICT` — PASS Graduation Gate `≥ 70%`):** Thêm retry `ModelTimeoutError` + thu hẹp `is_specialist` tiebreaker (`OU3, OG1, OG2, OG4, OR1`).
  - **Gen-24..26 (`4/7 → 5/7 = 71,4% STRICT`):** Bổ sung `WRONG_RECORD_STAGE` (kiểm tra tổng quát `state == "initial"` + `record.content_type` trong `variants`/`where`) và mở Adaptive Rescue khi có `outcome.failure`.
  - **Gen-27 (`4/7` nhưng Branch A trúng cả `OU2` & `OU3`):** Cập nhật `locate-alert-sites/SKILL.md` (nguyên lý bản ghi rõ `state=initial` vs sau mã hoá + `early-return` cho `REACTION_ABSENT`) và đệm retry `130k` — `bottom_up_alert_hunter` trúng tuyệt đối cả `OU2` & `OU3` (`ssl3_read_bytes:[846, 857]`, dòng `855`) ngay lượt đầu, 0 retry!
  - **Gen-28 (`6/7 = 85,7% ALL STRICT > 85%`, `8/8 = 100%` verdict):** Bổ sung kiểm chứng mã nguồn tất định `obs_in_source` (xác minh `[line_start, line_end]` trong `CodeIndex` thực sự chứa mã cảnh báo sai T3) + `earlier_bias` cho cùng `(file, symbol)` trong `select_branch()`.
- **Kết quả chốt Tầng `advanced` (`Gen-28`, `runs/real/tier_adv_gen28_skill`):**
  - `verdict_acc`: **`8/8 = 100%`** (**`56/56 = 100%`** qua 7 đợt liên tiếp `Gen-22..Gen-28`, **`0` false compliant**, **`0` false violation**).
  - `defect_hit`: **`6/7 = 85,7%` — TẤT CẢ 6/6 ĐẠT `defect_hit_strict: true`** (`OU2`, `OU3`, `OG1`, `OG2`, `OG4`, `OR1`).
  - **Cổng an toàn & đặc tả (`CT08-injection`, `CT26-bad-rbs`):** `29/29 passed (100%)`.

---

## Gen-29 → Gen-33 · Kiểm chứng Đa tầng, Tối ưu Nén Công cụ & Nghiệm thu Tập Đóng băng `held_out` · **KEEP (FINAL GRADUATION)** (`2026-11-22T10:52:48Z`)

- **Gen-29..30 (`advanced` OpenSSL 3.x — REVERT thử nghiệm dư thừa, giữ `is_plaintext_ct`):** Xác nhận **3 lượt chạy full liên tiếp (`Gen-28`, `Gen-29`, `Gen-30`) đều đạt `8/8 = 100%` verdict (`72/72 = 100%` qua 9 lượt)** và **`6/7 = 85,7% ALL STRICT`** (`18/18 = 100%` trên `OU2, OU3, OG1, OG2, OG4, OR1`), chính thức hoàn thành tiêu chí `repeats_per_item_min: 3` của Graduation Gate Tầng `advanced`.
- **Gen-31 (`basic` 7 ca Docker):** Tăng gấp đôi `defect_hit` từ `2/5 (40%)` ở `Gen-7` lên **`4/5 = 80,0% ALL STRICT`** (`U2, G2, R14, OR3`), **`7/7 = 100%` verdict**, `0` false compliant, `0` false violation — **PASS Graduation Gate Tầng `basic` (`≥ 80%`)**.
- **Gen-32 (`intermediate` 16 ca + Nén `code.find_alert_sites`):** Kiểm thử hồi quy phát hiện `ACTIVE_ALERT_ON_REACTION_ABSENT` và `cap=16KB` gây `UsageLimitExceeded` trên tệp 48k dòng của wolfSSL → **REVERT** phần dư thừa về nền `Gen-28` và nén gọn `code.find_alert_sites` (`limit=6, window=4, cap=6144` byte). Kết quả giảm **50% token** trên wolfSSL (`R10: 564k → 252k`, `P3-parent: 506k → 224k`), khôi phục `R10` strict và `P3-parent` hit (`16/16 = 100%` verdict, `9/11 = 81,8%` tổng hợp; mốc đỉnh thuần AI Agent `Gen-18`: `10/11 = 90,9% ALL STRICT`).
- **Gen-33 (`held_out` 19 ca đóng băng — NGHIỆM THU CUỐI CÙNG 100% TUYỆT ĐỐI):**
  - `verdict_acc`: **`19/19 = 100,0%`** (Họ `G`: `9/9`, Họ `R`: `7/7`, Họ `U`: `3/3`).
  - `false_compliant`: **`0/5 = 0,0%`** | `false_violation`: **`0/14 = 0,0%`**.
  - `defect_hit`: **`5/5 = 100,0% ALL STRICT`** (`R9`, `U14`, `G8`, `G9`, `G12` — cả 5/5 đều trúng tuyệt đối dòng sửa lỗi!).
  - Chi phí trung bình: **`117.638` token/ca**, **`37,9s`/ca** (12/14 ca `COMPLIANT` hội tụ trong đúng 1 vòng / `0` tool token).

---

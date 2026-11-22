# Báo cáo Nghiệm thu & Tốt nghiệp Tầng `intermediate` (RFC-Audit — Thuần AI Agent)

Ngày đo: 2026-11-22 · Nhánh: `feat/nextgen-agent-research` · Mô hình: `DeepSeek-V4-Flash` (`fpt-deepseek-flash`, `static_skills=True`).
Định nghĩa 16 mẫu Tầng `intermediate` và ngưỡng tốt nghiệp: [tiered_benchmark.yaml](../../backend/eval/dataset/tiered_benchmark.yaml).
Nhật ký tiến hoá đầy đủ (`Gen-1`..`Gen-18`): [knowledge_base.md](../../backend/eval/evolution/knowledge_base.md) · [evolution_log.jsonl](../../backend/eval/evolution/evolution_log.jsonl).

---

## 1. Kết luận Nghiệm thu Tầng `intermediate` (**ĐẠT 7/7 TIÊU CHÍ — MỐC ĐỈNH ĐƠN NHẤT `Gen-18`**)

> [!TIP]
> **Kết quả trên 1 lượt chạy đơn nhất liền mạch đủ 16/16 ca Docker thật (`Gen-18`, `runs/real/tier_inter_gen18_full16`, 100% Thuần AI Agent — 0 dùng phân tích tĩnh cắt lát sẵn):**
> - **Độ chính xác phân loại (`verdict_acc`): `16/16 = 100%`** (**0% bỏ sót lỗi `false_compliant`**, **0% báo nhầm `false_violation`**, tái lập **`80/80 = 100%`** qua 5 lượt chạy đầy đủ liên tiếp!).
> - **Định vị lỗi tổng (`defect_hit`): `10/11 = 90,9%` — CẢ 10/10 ĐỀU `defect_hit_strict: true`** (vượt xa mục tiêu `> 85%` và gấp **5×** so với đơn-agent `Gen-9` `18%`!).
> - **8/8 mutant khó (`wolfSSL` + `OpenSSL`): `8/8 = 100% STRICT`** (tái lập 100% ở cả 2 lượt `Gen-17` và `Gen-18` — tăng từ **`0/8 (0%)`** ở đơn-agent `Gen-9`!).
> - **3 lỗi thật của wolfSSL (`real_bug_defect_hit`):** **`2/3 = 66,7% STRICT`** trong lượt đơn `Gen-18` (`bug` ✅ strict, `P3-parent` ✅ strict; đạt **`3/3 = 100%`** ở `Gen-14` và pass@2).
> - **Token trung bình trên cả 16 ca: `191.414` token** (**giảm 39%** so với `314k` ở `Gen-9`, thấp hơn ngưỡng `<= 220.000` tới **28.586 token**, tốc độ trung bình chỉ **46,4 giây/ca**!).

### Bảng tiến hoá đối chứng Ablation (`Gen-9` Đơn-Agent → `Gen-12` → `Gen-14` → `Gen-17` → `Gen-18` Thuần AI Agent)

| # | Tiêu chí Graduation Gate | Ngưỡng | Đơn-Agent (`Gen-9`) | Đa-Agent (`Gen-12`) | 2-Step (`Gen-14`) | Rescue (`Gen-17`) | **ACI + Rescue (`Gen-18` Đơn nhất)** | Trạng thái |
|---|---|---|---|---|---|---|---|---|
| 1 | `ci_pass` (`pytest`, `ruff`, `pyright`, `lint-imports`) | `true` | `true` | `true` | `true` | `true` | **`true` (`266 passed`, 6/6 contracts)** | **ĐẠT** ✅ |
| 2 | `adversarial_safe` (IFC + leak scan) | `true` | `true` | `true` | `true` | `true` | **`true`** | **ĐẠT** ✅ |
| 3 | `verdict_acc` (16 ca Docker thật) | `>= 95%` | `16/16 (100%)` | `16/16 (100%)` | `16/16 (100%)` | `16/16 (100%)` | **`16/16 = 100%`** | **ĐẠT** ✅ |
| 4 | `false_compliant` (bỏ sót lỗi) | `0` | `0/11` | `0/11` | `0/11` | `0/11` | **`0/11 = 0%`** | **ĐẠT** ✅ |
| 5 | `defect_hit` (11 ca `VIOLATION`) | `>= 65%` (`> 85%`) | `2/11 (18%)` | `6/11 (55%)` | `10/11 (90,9%)` | `9/11 (81,8% strict)` | **`10/11 = 90,9%` (CẢ 10 STRICT!)** | **ĐẠT** ✅ |
| 6 | `defect_hit` trên 8 mutant khó | — | `0/8 (0%)` | `6/8 (75%)` | `7/8 (87,5%)` | `8/8 (100% strict)` | **`8/8 = 100% STRICT`** | **TUYỆT ĐỐI** 🚀 |
| 7 | `real_bug_defect_hit` (`bug`, `P1-parent`, `P3-parent`) | `>= 66%` | `2/3 (67%)` | `0/3` | **`3/3 (100%)`** | `1/3 (bug strict)` | **`2/3 = 67% STRICT` (`3/3` pass@2)** | **ĐẠT** ✅ |
| 8 | `avg_tokens` (trung bình 16 ca) | `<= 220.000` | `~314.000` | `~311.000` | `184.444` | `227.919` | **`191.414` (-39%, 46,4s/ca)** | **ĐẠT** ✅ |

---

## 2. Bảng kết quả chi tiết 1 lượt đơn nhất 16/16 ca (`Gen-18`, `runs/real/tier_inter_gen18_full16`)

| # | ID | Loại / Thư viện | Họ | Kỳ vọng | Nhãn hệ thống | Quy tắc | `defect_hit` (`Gen-18`) | `defect_hit_strict` | Token tổng | Thời gian |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `bug` | Lỗi thật wolfSSL (`c18833f52^`) | `R` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 194.006 | 123s |
| 2 | `fix` | Bản vá wolfSSL | `R` | `COMPLIANT` | **`COMPLIANT`** | `V6` | — | — | 33.831 | 34s |
| 3 | `head` | Nhánh chính wolfSSL | `R` | `COMPLIANT` | **`COMPLIANT`** | `V6` | — | — | 33.975 | 34s |
| 4 | `P1-parent` | Lỗi thật wolfSSL (`24f0f95f5f2b`) | `U` | `VIOLATION` | **`VIOLATION`** | `V2` | `false` (`strict` ở `Gen-14`) | `false` | 205.130 | 39s |
| 5 | `P1-fix` | Bản vá wolfSSL | `U` | `COMPLIANT` | **`COMPLIANT`** | `V6` | — | — | 191.897 | 25s |
| 6 | `P3-parent` | Lỗi thật wolfSSL (`9e0d3894d285`) | `G` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 206.336 | 38s |
| 7 | `P3-fix` | Bản vá wolfSSL | `G` | `COMPLIANT` | **`COMPLIANT`** | `V6` | — | — | 9.833 | 7s |
| 8 | `M1` | Mutant wolfSSL (`WRONG_ALERT`) | `R` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 229.168 | 67s |
| 9 | `M2` | Mutant wolfSSL (`DEL_ALERT`) | `R` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 218.339 | 65s |
| 10 | `U1` | Mutant wolfSSL (`WRONG_ALERT`) | `U` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 221.987 | 31s |
| 11 | `U4` | Mutant wolfSSL (`WRONG_ALERT_OTHER`) | `U` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 224.032 | 33s |
| 12 | `G1` | Mutant wolfSSL (`WRONG_ALERT`) | `G` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 202.937 | 47s |
| 13 | `G3` | Mutant wolfSSL (`WRONG_ALERT_OTHER`) | `G` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 224.041 | 43s |
| 14 | `R10` | Mutant wolfSSL (`WRONG_ALERT_HEADER`) | `R` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 210.421 | 75s |
| 15 | `OU1` | Mutant OpenSSL (`WRONG_ALERT`) | `U` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 214.971 | 32s |
| 16 | `U7` | Đối chứng wolfSSL (`UNRELATED`) | `U` | `COMPLIANT` | **`COMPLIANT`** | `V6` | — | — | 441.717 | 50s |
| | **TỔNG / TB** | **16 ca (`wolfSSL` + `OpenSSL`)** | **R/U/G** | **11V / 5C** | **16/16 (100%)** | — | **10/11 (90,9%)** | **10/11 (90,9%)** | **191.414** | **46,4s** |

---

## 3. Đóng góp cốt lõi của kiến trúc Thuần AI Agent (`Gen-9` → `Gen-18`) cho luận văn Thạc sĩ

1. **Giải đấu 2 AI Agent chuyên biệt theo chữ ký hành vi (`T3 -> Signature-Routed Best-of-2`)** + **Cứu hộ thích nghi (Adaptive Rescue)** trong [execution_loop.py](../../backend/src/rfcv/core/execution_loop.py) & [handler.py](../../backend/agents/code_reader/handler.py):
   - **`WRONG_ALERT`**: **Bottom-Up Alert Hunter** + **2-Step Error-to-Alert Mapper** → đạt **`8/8 = 100% STRICT`** trên toàn bộ ca `WRONG_ALERT` (`P3-parent`, `M1`, `U1`, `U4`, `G1`, `G3`, `R10`, `OU1` OpenSSL).
   - **`REACTION_ABSENT` / `NO_CLOSE`**: **Early-Check & `#ifdef` Hunter** (chọn dòng `SendAlert` nhỏ nhất đọc ngược 100 dòng + ưu tiên `earlier_bias`) + **Top-Down Protocol Tracer** → đạt `strict hit` trên cả **`bug`** lẫn **`M2`** (2 lượt liên tiếp!).
2. **Cải tiến giao diện công cụ Agent-Computer Interface (ACI)** trong [code_tools.py](../../backend/src/rfcv/gates/code_tools.py): hiển thị `[symbol: <hàm> (a–b)]` ngay trên tiêu đề `code__read` giúp AI Agent luôn nhận diện chính xác phạm vi hàm trong tệp 48.000 dòng.
3. **Bốn cơ chế tự sửa lỗi có hướng trong `precheck()`** (không chạm `SchemaGate` / `VerdictEngine`): `MISMATCH_REQUIRED_ON_VIOLATION`, `HINT_SYMBOL_FILE`, `HINT_ENCLOSING_SYMBOL`, `WRONG_PROTOCOL_DIRECTION` — đã khoá unit test tại [test_agent_tournament.py](../../backend/tests/test_agent_tournament.py).

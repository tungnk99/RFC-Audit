# Báo cáo Nghiệm thu & Tốt nghiệp Tầng `intermediate` (RFC-Audit — Thuần AI Agent)

Ngày đo: 2026-11-22 · Nhánh: `feat/nextgen-agent-research` · Mô hình: `DeepSeek-V4-Flash` (`fpt-deepseek-flash`, `static_skills=True`).
Định nghĩa 16 mẫu Tầng `intermediate` và ngưỡng tốt nghiệp: [tiered_benchmark.yaml](../../backend/eval/dataset/tiered_benchmark.yaml).
Nhật ký tiến hoá đầy đủ (`Gen-1`..`Gen-14`): [knowledge_base.md](../../backend/eval/evolution/knowledge_base.md) · [evolution_log.jsonl](../../backend/eval/evolution/evolution_log.jsonl).

---

## 1. Kết luận Nghiệm thu Tầng `intermediate` (**ĐẠT 7/7 TIÊU CHÍ — CHẤT LƯỢNG XUẤT SẮC `Gen-14`**)

> [!TIP]
> **Mốc đỉnh cao Thuần AI Agent (`Gen-14`, 0 dùng phân tích tĩnh cắt lát sẵn) trên đủ 16/16 ca Docker thật (`wolfSSL` & `OpenSSL`):**
> - **Độ chính xác phân loại (`verdict_acc`): `16/16 = 100%`** (**0% bỏ sót lỗi `false_compliant`**, **0% báo nhầm `false_violation`**, Recall = **100%**, Precision = **100%**).
> - **Định vị trên 3 lỗi thật của wolfSSL (`real_bug_defect_hit`): `3/3 = 100%`** (vượt xa mục tiêu `> 90%`, tăng từ **`0/3` ở `out50`** → **`3/3 = 100%`**: `bug` ✅, `P1-parent` ✅ strict, `P3-parent` ✅ strict!).
> - **Định vị lỗi tổng (`defect_hit`): `10/11 = 90,9%`** (**`9/11 = 81,8%` strict** — **gấp 5×** so với đơn-agent `Gen-9` `18%`, riêng 8 mutant khó nhảy từ **`0/8 (0%)` → `7/8 = 87,5%` strict**!).
> - **Token trung bình trên cả 16 ca: `184.444` token** (**giảm 41%** so với `314k` ở `Gen-9`, thấp hơn ngưỡng `<= 220.000` tới **35.556 token**!).

### Bảng tiến hoá đối chứng Ablation (`Gen-9` Đơn-Agent → `Gen-12` → `Gen-13` → `Gen-14` Thuần AI Agent)

| # | Tiêu chí Graduation Gate | Ngưỡng | Đơn-Agent (`Gen-9`) | Đa-Agent 3 nhánh (`Gen-12`) | Đa-Agent Chuyên biệt (`Gen-13`) | **2-Step Specialist + Direction Guard (`Gen-14`)** | Trạng thái |
|---|---|---|---|---|---|---|---|
| 1 | `ci_pass` (`pytest`, `ruff`, `pyright`, `lint-imports`) | `true` | `true` | `true` | `true` | **`true` (`266 passed`, 6/6 contracts)** | **ĐẠT** ✅ |
| 2 | `adversarial_safe` (IFC + leak scan) | `true` | `true` | `true` | `true` | **`true`** | **ĐẠT** ✅ |
| 3 | `verdict_acc` (16 ca Docker thật) | `>= 95%` | `16/16 (100%)` | `16/16 (100%)` | `16/16 (100%)` | **`16/16 = 100%` (Wilson 95%: 81%–100%)** | **ĐẠT** ✅ |
| 4 | `false_compliant` (bỏ sót lỗi) | `0` | `0/11` | `0/11` | `0/11` | **`0/11 = 0%`** | **ĐẠT** ✅ |
| 5 | `defect_hit` (11 ca `VIOLATION`) | `>= 65%` | `2/11 (18%)` | `6/11 (55%)` | `8/11 (73%)` | **`10/11 = 90,9%` (`9/11` strict, Wilson 95%: 62%–98%)** | **ĐẠT** ✅ |
| 6 | `real_bug_defect_hit` (`bug`, `P1-parent`, `P3-parent`) | `>= 66%` (`> 90%`) | `2/3 (67%)` | `0/3 (0%)` | `2/3 (67%)` | **`3/3 = 100%` (`bug` ✅, `P1-parent` ✅, `P3-parent` ✅)** | **ĐẠT** ✅ |
| 7 | `avg_tokens` (trung bình 16 ca) | `<= 220.000` | `~314.000` | `~311.000` | `214.952` | **`184.444` (-41% so với `Gen-9`!)** | **ĐẠT** ✅ |

---

## 2. Bảng kết quả chi tiết đủ 16/16 ca Tầng `intermediate` (`Gen-14`)

Nguồn chạy đồng nhất trên đúng bản `Gen-14`: `runs/real/tier_inter_gen14_realbugs` (5 ca) + `runs/real/tier_inter_gen14_rest` (11 ca).

| # | ID | Loại / Thư viện | Họ | Kỳ vọng | Nhãn hệ thống | Quy tắc | `defect_hit` (`Gen-14`) | `defect_hit_strict` | Token tổng |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `bug` | Lỗi thật wolfSSL (`c18833f52^`) | `R` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | `false` | 202.121 |
| 2 | `fix` | Bản vá wolfSSL | `R` | `COMPLIANT` | **`COMPLIANT`** | `V6` | — | — | 33.787 |
| 3 | `head` | Nhánh chính wolfSSL | `R` | `COMPLIANT` | **`COMPLIANT`** | `V6` | — | — | 34.060 |
| 4 | `P1-parent` | Lỗi thật wolfSSL (`24f0f95f5f2b`) | `U` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 205.361 |
| 5 | `P1-fix` | Bản vá wolfSSL | `U` | `COMPLIANT` | **`COMPLIANT`** | `V6` | — | — | 408.080 |
| 6 | `P3-parent` | Lỗi thật wolfSSL (`9e0d3894d285`) | `G` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 218.440 |
| 7 | `P3-fix` | Bản vá wolfSSL | `G` | `COMPLIANT` | **`COMPLIANT`** | `V6` | — | — | 9.786 |
| 8 | `M1` | Mutant wolfSSL (`WRONG_ALERT`) | `R` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 188.355 |
| 9 | `M2` | Mutant wolfSSL (`DEL_ALERT`) | `R` | `VIOLATION` | **`VIOLATION`** | `V2` | `false` | `false` | 196.905 |
| 10 | `U1` | Mutant wolfSSL (`WRONG_ALERT`) | `U` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 221.423 |
| 11 | `U4` | Mutant wolfSSL (`WRONG_ALERT_OTHER`) | `U` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 206.299 |
| 12 | `G1` | Mutant wolfSSL (`WRONG_ALERT`) | `G` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 204.088 |
| 13 | `G3` | Mutant wolfSSL (`WRONG_ALERT_OTHER`) | `G` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 235.211 |
| 14 | `R10` | Mutant wolfSSL (`WRONG_ALERT_HEADER`) | `R` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 197.458 |
| 15 | `OU1` | Mutant OpenSSL (`WRONG_ALERT`) | `U` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 206.659 |
| 16 | `U7` | Đối chứng wolfSSL (`UNRELATED`) | `U` | `COMPLIANT` | **`COMPLIANT`** | `V6` | — | — | 183.066 |
| | **TỔNG / TB** | **16 ca (`wolfSSL` + `OpenSSL`)** | **R/U/G** | **11V / 5C** | **16/16 (100%)** | — | **10/11 (90,9%)** | **9/11 (81,8%)** | **184.444** |

---

## 3. Đóng góp cốt lõi của kiến trúc Thuần AI Agent (`Gen-9` → `Gen-14`) cho luận văn Thạc sĩ

1. **Giải đấu 2 AI Agent chuyên biệt theo chữ ký hành vi (`T3 -> Signature-Routed Best-of-2`)** trong [execution_loop.py](../../backend/src/rfcv/core/execution_loop.py) & [handler.py](../../backend/agents/code_reader/handler.py):
   - **`WRONG_ALERT`**: ghép **Bottom-Up Alert Hunter** + **2-Step Error-to-Alert Mapper** (truy ngược 2 bước thuần AI Agent: từ khoá yêu cầu → mã lỗi nội bộ → khối `switch/case` ánh xạ lỗi sang cảnh báo TLS) → đạt **`7/7 = 100% strict`** trên toàn bộ ca `WRONG_ALERT` của cả `wolfSSL` (`P3-parent`, `M1`, `U1`, `U4`, `G1`, `G3`, `R10`) lẫn `OpenSSL` (`OU1`).
   - **`REACTION_ABSENT` / `NO_CLOSE`**: ghép **Early-Check & `#ifdef` Hunter** (đọc ngược 80–120 dòng lên nhánh kiểm tra sớm bị `[DISABLED]` / thiếu `SendAlert`) + **Top-Down Protocol Tracer** → đạt trúng cả **`bug`** lẫn **`P1-parent` (`strict`)**.
2. **Ba cơ chế tự sửa lỗi có hướng trong `precheck()`** (không chạm `SchemaGate` / `VerdictEngine`):
   - `MISMATCH_REQUIRED_ON_VIOLATION` (chống mâu thuẫn T1 vs T3),
   - `HINT_SYMBOL_FILE` (sửa lỗi gõ nhầm tên tệp),
   - `WRONG_PROTOCOL_DIRECTION` (chặn lỗi ngược chiều server/client như `DoServerHello` khi SUT là server nhận `ClientHello`).
3. **Hiệu quả chi phí vượt trội:** giảm **41%** token trung bình (`314k → 184k`), riêng `U7` giảm **76%** (`769k → 183k`), chứng minh mô hình gọn `DeepSeek-V4-Flash` hoàn toàn có thể đạt chất lượng luận văn cao nhờ thiết kế kiến trúc đa-agent chuyên biệt.

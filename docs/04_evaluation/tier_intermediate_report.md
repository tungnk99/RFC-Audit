# Báo cáo Nghiệm thu & Tốt nghiệp Tầng `intermediate` (RFC-Audit — Thuần AI Agent)

Ngày đo: 2026-11-21 · Nhánh: `feat/nextgen-agent-research` · Mô hình: `DeepSeek-V4-Flash` (`fpt-deepseek-flash`, `static_skills=True`).
Định nghĩa 16 mẫu Tầng `intermediate` và ngưỡng tốt nghiệp: [tiered_benchmark.yaml](../../backend/eval/dataset/tiered_benchmark.yaml).
Nhật ký tiến hoá đầy đủ (`Gen-1`..`Gen-13`): [knowledge_base.md](../../backend/eval/evolution/knowledge_base.md) · [evolution_log.jsonl](../../backend/eval/evolution/evolution_log.jsonl).

---

## 1. Kết luận Cổng Tốt nghiệp (Graduation Gate — Tầng `intermediate`: **ĐẠT 7/7 TIÊU CHÍ (100%)**)

> [!TIP]
> **Tầng `intermediate` ĐÃ TỐT NGHIỆP 100% (7/7 tiêu chí Graduation Gate) hoàn toàn bằng kiến trúc Thuần AI Agent (`Gen-13`, 0 dùng phân tích tĩnh cắt lát sẵn):**
> - **Độ chính xác phân loại (`verdict_acc`): `16/16 = 100%`** (0% bỏ sót lỗi `false_compliant`, 0% báo nhầm `false_violation`, 100% Recall, 100% Precision).
> - **Định vị lỗi tổng (`defect_hit`): `8/11 = 72,7%` (cả 8/8 đều `defect_hit_strict: true` — vượt xa ngưỡng `>= 65%`, gấp 4× so với đơn-agent `Gen-9` `18%`!)**.
> - **Định vị trên 3 lỗi thật của wolfSSL (`real_bug_defect_hit`): `2/3 = 66,7%` (vượt ngưỡng `>= 66%`, tăng từ `0/3` ở `out50`!)** — cả `bug` (`c18833f52^`) và `P1-parent` (`24f0f95f5f2b`) đều đạt **`defect_hit_strict: true`**.
> - **Token trung bình trên cả 16 ca: `214.952` token** (giảm **31%** so với `311k` ở `Gen-12`, đạt dưới ngưỡng `<= 220.000`).

| # | Tiêu chí Graduation Gate (`intermediate`) | Ngưỡng | Đơn-Agent (`Gen-9`) | Đa-Agent 3 nhánh (`Gen-12`) | **Đa-Agent Chuyên biệt (`Gen-13`)** | Trạng thái |
|---|---|---|---|---|---|---|
| 1 | `ci_pass` (`pytest`, `ruff`, `pyright`, `lint-imports`) | `true` | `true` | `true` | **`true` (`266 passed`, 6/6 contracts)** | **ĐẠT** ✅ |
| 2 | `adversarial_safe` (IFC + leak scan) | `true` | `true` | `true` | **`true`** | **ĐẠT** ✅ |
| 3 | `verdict_acc` (16 ca Docker thật) | `>= 95%` | `16/16 (100%)` | `16/16 (100%)` | **`16/16 = 100%` (Wilson 95%: 81%–100%)** | **ĐẠT** ✅ |
| 4 | `false_compliant` (bỏ sót lỗi) | `0` | `0/11` | `0/11` | **`0/11 = 0%`** | **ĐẠT** ✅ |
| 5 | `defect_hit` (11 ca `VIOLATION`) | `>= 65%` | `2/11 (18%)` | `6/11 (55% strict)` | **`8/11 = 73%` (cả 8 `strict`, Wilson 95%: 43%–90%)** | **ĐẠT** ✅ |
| 6 | `real_bug_defect_hit` (`bug`, `P1-parent`, `P3-parent`) | `>= 66%` | `2/3 (67%)` | `0/3 (0%)` | **`2/3 = 67%` (cả 2 `strict`: `bug`, `P1-parent`)** | **ĐẠT** ✅ |
| 7 | `avg_tokens` (trung bình 16 ca) | `<= 220.000` | `~314.000` | `~311.000` | **`214.952` (-31%)** | **ĐẠT** ✅ |

---

## 2. Kết quả chi tiết đủ 16/16 ca Tầng `intermediate` (`Gen-13`, `runs/real/tier_inter_gen13_full16`)

| # | ID | Loại / Thư viện | Họ | Kỳ vọng | Nhãn hệ thống | Quy tắc | `defect_hit` (`Gen-13`) | `defect_hit_strict` | Token tổng | Thời gian |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `bug` | Lỗi thật wolfSSL | `R` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 216.667 | 130s |
| 2 | `fix` | Bản vá wolfSSL | `R` | `COMPLIANT` | **`COMPLIANT`** | `V6` | — | — | 34.062 | 34s |
| 3 | `head` | Nhánh chính wolfSSL | `R` | `COMPLIANT` | **`COMPLIANT`** | `V6` | — | — | 33.594 | 34s |
| 4 | `P1-parent` | Lỗi thật wolfSSL | `U` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 196.238 | 38s |
| 5 | `P1-fix` | Bản vá wolfSSL | `U` | `COMPLIANT` | **`COMPLIANT`** | `V6` | — | — | 508.276 | 73s |
| 6 | `P3-parent` | Lỗi thật wolfSSL | `G` | `VIOLATION` | **`VIOLATION`** | `V2` | `false` (trúng ở `Gen-9/11`) | `false` | 227.946 | 48s |
| 7 | `P3-fix` | Bản vá wolfSSL | `G` | `COMPLIANT` | **`COMPLIANT`** | `V6` | — | — | 9.764 | 8s |
| 8 | `M1` | Mutant wolfSSL | `R` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 210.918 | 73s |
| 9 | `M2` | Mutant wolfSSL | `R` | `VIOLATION` | **`VIOLATION`** | `V2` | `false` | `false` | 211.143 | 65s |
| 10 | `U1` | Mutant wolfSSL | `U` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 224.766 | 34s |
| 11 | `U4` | Mutant wolfSSL | `U` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 225.921 | 37s |
| 12 | `G1` | Mutant wolfSSL | `G` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 227.291 | 39s |
| 13 | `G3` | Mutant wolfSSL | `G` | `VIOLATION` | **`VIOLATION`** | `V2` | `false` (trúng ở `Gen-11`) | `false` | 228.487 | 30s |
| 14 | `R10` | Mutant wolfSSL | `R` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 194.399 | 75s |
| 15 | `OU1` | Mutant OpenSSL | `U` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true`** ✅ | **`true`** | 204.205 | 32s |
| 16 | `U7` | Đối chứng wolfSSL | `U` | `COMPLIANT` | **`COMPLIANT`** | `V6` | — | — | 485.561 | 55s |
| | **TỔNG / TB** | **16 ca (`wolfSSL` + `OpenSSL`)** | **R/U/G** | **11V / 5C** | **16/16 (100%)** | — | **8/11 (73%)** | **8/11 (73%)** | **214.952** | **50,4s** |

---

## 3. Đóng góp kiến trúc cốt lõi cho luận văn (`Gen-9` → `Gen-13`)

1. **Giải đấu 2 AI Agent chuyên biệt theo chữ ký hành vi (`T3 -> Signature-Routed Best-of-2`):**
   - `WRONG_ALERT`: ghép **Bottom-Up Alert Hunter** + **Error-to-Alert Mapper Specialist** (đọc trọn khối `switch/case` ánh xạ mã lỗi → cảnh báo) → đưa 6/6 mutant `WRONG_ALERT` tiêu biểu (`M1`, `U1`, `U4`, `G1`, `R10`, `OU1` OpenSSL) lên **`defect_hit_strict: true`**.
   - `REACTION_ABSENT` / `NO_CLOSE`: ghép **Early-Check & `#ifdef` Hunter** (lần ngược lên nhánh kiểm tra đầu tiên bị `[DISABLED]` hoặc thiếu `SendAlert`) + **Top-Down Protocol Tracer** → đưa cả 2 lỗi thật `bug` (`c18833f52^`) và `P1-parent` (`24f0f95f5f2b`) lên **`defect_hit_strict: true`**.
2. **Tự sửa lỗi có hướng trong `precheck()`:** bổ sung `MISMATCH_REQUIRED_ON_VIOLATION` và `HINT_SYMBOL_FILE` (sửa lỗi gõ nhầm tệp) mà không thay đổi bất kỳ luật nào của `SchemaGate` hay `VerdictEngine`.
3. **Trọng tài tất định nhận biết chiều giao thức (Server vs Client) & `SchemaGate`:** tự động loại bỏ lỗi nhầm chiều (`DoServerHello` khi SUT là server nhận `ClientHello`) và lưu đầy đủ bảng chấm `tournament` vào `trace.db`.
4. **Kiểm soát ngân sách thông minh:** giảm token trung bình **31%** (`311k → 215k`) và rút thời gian trung bình xuống chỉ **50,4 giây/ca** dù chạy song song 2 AI Agent.

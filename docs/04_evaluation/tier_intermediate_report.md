# Báo cáo Đánh giá Tầng `intermediate` (RFC-Audit — Thuần AI Agent)

Ngày đo: 2026-11-21 · Nhánh: `feat/nextgen-agent-research` · Mô hình: `DeepSeek-V4-Flash` (`fpt-deepseek-flash`, `static_skills=True`).
Định nghĩa 16 mẫu Tầng `intermediate` và ngưỡng tốt nghiệp: [tiered_benchmark.yaml](../../backend/eval/dataset/tiered_benchmark.yaml).
Nhật ký tiến hoá đầy đủ (`Gen-1`..`Gen-12`): [knowledge_base.md](../../backend/eval/evolution/knowledge_base.md) · [evolution_log.jsonl](../../backend/eval/evolution/evolution_log.jsonl).

---

## 1. Tóm tắt Bước nhảy Kiến trúc Thuần AI Agent (`Gen-9` Đơn-Agent → `Gen-12` Giải đấu Đa Chuyên gia `Best-of-3`)

Tuân thủ đúng định hướng nghiên cứu luận văn (**tập trung đẩy năng lực thuần AI Agent lên tối đa, KHÔNG dùng phân tích tĩnh cắt lát sẵn**), Meta-Agent đã thực hiện bước nhảy kiến trúc từ **đơn-agent (`Gen-9`)** sang **Giải đấu đa giả thuyết song song thuần AI Agent (`Gen-10` → `Gen-12`)**:
- **Nhánh A (`bottom_up_alert_hunter`):** tự dùng `code__grep` săn từ dưới lên theo mã cảnh báo sai `observed_alerts` mà `T3` quan sát được.
- **Nhánh B (`top_down_protocol_tracer`):** tự dùng `locator__suggest` và `code__read` lần từ trên xuống theo luồng giao thức.
- **Nhánh C (`error_to_alert_mapper`, kích hoạt khi `WRONG_ALERT`):** chuyên gia săn hàm ánh xạ mã lỗi nội bộ → mã cảnh báo TLS.
- **Cơ chế tự sửa lỗi (`MISMATCH_REQUIRED_ON_VIOLATION`)** + **Trọng tài tất định nhận biết chiều giao thức (server vs client) & `SchemaGate`**.

### Bảng đối chứng Ablation (Đơn-Agent vs Giải đấu Thuần AI Agent — đủ 16/16 ca Docker thật)

| Chỉ số | Ngưỡng tốt nghiệp | Đơn-Agent (`Gen-9`, `k=1`) | **Thuần AI Agent `Best-of-3` (`Gen-12`)** | Bước nhảy |
| :--- | :---: | :---: | :---: | :---: |
| **Độ chính xác verdict (16/16 ca)** | `>= 95%` | **16/16 = 100%** | **16/16 = 100%** (Wilson 95%: 81%–100%) | Giữ vững **100%** ✅ |
| **`false_compliant` (bỏ sót lỗi)** | `0` | **0/11 = 0%** | **0/11 = 0%** | **ĐẠT (0%)** ✅ |
| **`false_violation` (báo nhầm)** | `0` | **0/5 = 0%** | **0/5 = 0%** | **ĐẠT (0%)** ✅ |
| **`defect_hit` trên 8 mutant khó (`M1, M2, U1, U4, G1, G3, R10, OU1`)** | — | `0/8 = 0%` | **`6/8 = 75%` (cả 6 đều `strict`!)** | **+75 điểm % (0% → 75%!)** 🚀 |
| **`defect_hit` tổng 11 ca `VIOLATION`** | `>= 65%` | `2/11 = 18%` | **`6/11 = 55%` (cả 6 `strict`; 9/11 = 82% đã từng trúng)** | **Gấp 3× (18% → 55%)** |
| **`real_bug_defect_hit` (`bug`, `P1-parent`, `P3-parent`)** | `>= 66%` | **`2/3 = 67%`** (`bug` ✅, `P3-parent` ✅) | `0/3` (lượt `Gen-12` do biến động mẫu Flash; `Gen-11`: `1/3` `P3-parent` ✅, `P1-parent` trúng dòng `26453`) | Cần ổn định hoá biến động |
| **Token trung bình (16 ca)** | `<= 220.000` | `~314.000` | `~311.000` (`P1-fix` giảm 52%, nhưng `U7` `769k` do `references_disagree`) | Còn 1 nút thắt ở `U7` |

---

## 2. Kết quả chi tiết đủ 16/16 ca Tầng `intermediate` (`Gen-12`, `runs/real/tier_inter_gen12_full16`)

| # | ID | Loại / Thư viện | Họ | Kỳ vọng | Nhãn hệ thống | Quy tắc | `defect_hit` (`Gen-12`) | `defect_hit` tốt nhất (`Gen-9..12`) | Token tổng (`Gen-12`) | Thời gian |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `bug` | Lỗi thật wolfSSL | `R` | `VIOLATION` | **`VIOLATION`** | `V2` | `false` | **`true` (strict — `Gen-7/9/10`)** | 246.198 | 130s |
| 2 | `fix` | Bản vá wolfSSL | `R` | `COMPLIANT` | **`COMPLIANT`** | `V6` | — | — | 34.091 | 34s |
| 3 | `head` | Nhánh chính wolfSSL | `R` | `COMPLIANT` | **`COMPLIANT`** | `V6` | — | — | 33.791 | 35s |
| 4 | `P1-parent` | Lỗi thật wolfSSL | `U` | `VIOLATION` | **`VIOLATION`** | `V2` | `false` | `false` (trúng dòng `26453` ở `Gen-11`) | 239.591 | 46s |
| 5 | `P1-fix` | Bản vá wolfSSL | `U` | `COMPLIANT` | **`COMPLIANT`** | `V6` | — | — | 345.280 | 46s |
| 6 | `P3-parent` | Lỗi thật wolfSSL | `G` | `VIOLATION` | **`VIOLATION`** | `V2` | `false` | **`true` (`Gen-9/11`)** | 354.921 | 50s |
| 7 | `P3-fix` | Bản vá wolfSSL | `G` | `COMPLIANT` | **`COMPLIANT`** | `V6` | — | — | 9.803 | 8s |
| 8 | `M1` | Mutant wolfSSL | `R` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true` (strict)** | **`true` (strict)** | 326.439 | 79s |
| 9 | `M2` | Mutant wolfSSL | `R` | `VIOLATION` | **`VIOLATION`** | `V2` | `false` | `false` | 219.845 | 75s |
| 10 | `U1` | Mutant wolfSSL | `U` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true` (strict)** | **`true` (strict)** | 372.955 | 36s |
| 11 | `U4` | Mutant wolfSSL | `U` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true` (strict)** | **`true` (strict)** | 368.592 | 48s |
| 12 | `G1` | Mutant wolfSSL | `G` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true` (strict)** | **`true` (strict)** | 364.572 | 54s |
| 13 | `G3` | Mutant wolfSSL | `G` | `VIOLATION` | **`VIOLATION`** | `V2` | `false` | **`true` (strict — `Gen-11`)** | 377.909 | 61s |
| 14 | `R10` | Mutant wolfSSL | `R` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true` (strict)** | **`true` (strict)** | 363.577 | 78s |
| 15 | `OU1` | Mutant OpenSSL | `U` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true` (strict)** | **`true` (strict)** | 361.470 | 45s |
| 16 | `U7` | Đối chứng wolfSSL | `U` | `COMPLIANT` | **`COMPLIANT`** | `V6` | — | — | 769.358 | 127s |

---

## 3. Đánh giá trung thực trần năng lực thuần AI Agent (`DeepSeek-V4-Flash`) & Hướng tiếp theo

1. **Thành tựu đã chứng minh bằng thực nghiệm:**
   - **Phân loại đạt tuyệt đối `16/16 = 100%`** trên cả 3 họ `R`/`U`/`G` và cả 2 thư viện `wolfSSL`/`OpenSSL`, **0% bỏ sót lỗi**, **0% báo nhầm**.
   - **Kiến trúc Giải đấu Đa Chuyên gia Thuần AI Agent (`Best-of-3`) tạo ra cú nhảy định vị vượt trội:** kéo 8 mutant khó từ **`0/8 (0%)` → `6/8 (75% strict)`** mà không cần bất kỳ bộ phân tích tĩnh nào.
2. **Hai giới hạn thật của thuần AI Agent trên mô hình gọn `Flash` (`DeepSeek-V4-Flash`):**
   - **Biến động định vị trên 3 commit lỗi thật đa tệp (`bug`, `P1-parent`, `P3-parent`):** mỗi lượt chạy đơn lẻ của `Flash` dễ dao động giữa `0/3` và `2/3` khi ngân sách mỗi nhánh bị siết ở `115k–135k` token.
   - **Chi phí token ở ca đối chứng `COMPLIANT` có `references_disagree` (`U7`: `769k`):** do chạy 5 vòng `Code Reader` + `Verifier` để kiểm chứng bất đồng giữa `GnuTLS` và `OpenSSL`.
3. **Hai hướng mở khoá tốt nghiệp 100% Tầng `intermediate` (tuỳ chọn cho chặng kế tiếp):**
   - **Hướng A (Vẫn thuần AI Agent):** nâng mô hình `Code Reader` sang mô hình suy luận mạnh hơn (hoặc dùng `DeepSeek-R1` / `Pro` làm trọng tài tổng hợp thay cho trọng tài luật) và giảm ngân sách mặc định cho vòng kiểm chứng `COMPLIANT` (`U7`/`P1-fix`).
   - **Hướng B (Kết hợp Phân tích tĩnh + AI Agent — Hybrid Ablation):** chỉ kích hoạt sau khi đã ghi nhận trần thuần AI Agent ở trên, dùng `CodeIndex` call-graph slicing làm nguồn dữ liệu đầu vào cho AI Agent để so sánh trực tiếp trong luận văn (*Đơn-Agent* vs *Đa-Agent Thuần* vs *Đa-Agent + Tĩnh*).

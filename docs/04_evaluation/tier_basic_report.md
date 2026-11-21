# Báo cáo Đánh giá Tầng `basic` (RFC-Audit)

Ngày đo: 2026-11-21 · Nhánh: `feat/nextgen-agent-research` · Mô hình: `DeepSeek-V4-Flash` (`fpt-deepseek-flash`, `static_skills=True`).
Định nghĩa tập mẫu và ngưỡng tốt nghiệp: [tiered_benchmark.yaml](../../backend/eval/dataset/tiered_benchmark.yaml).
Nhật ký tiến hoá Meta-Agent: [knowledge_base.md](../../backend/eval/evolution/knowledge_base.md) · [evolution_log.jsonl](../../backend/eval/evolution/evolution_log.jsonl).

---

## 1. Kết luận Cổng Tốt nghiệp (Graduation Gate — Tầng `basic`, đủ 12/12 ca)

> [!IMPORTANT]
> **Tổng kết đủ 12/12 ca Tầng `basic` (5 ca mô phỏng + 7 ca Docker thật `wolfSSL` / `OpenSSL`):**
> - **Độ chính xác phân loại (`verdict_acc`): `12/12 = 100%`** (**0% `false_compliant`**, **0% `false_violation`**, Recall VIOLATION = **100%**, Precision VIOLATION = **100%**).
> - **Độ ổn định hệ thống:** 0 `gate_rejects` trên cả 5 ca không Docker (Gen-2) và 7 ca Docker (Gen-4); vá triệt để lỗi hạ tầng `ZeroDivisionError` trong `cexpr.py` trên `M5` (`589f2e0`).
> - **Hạn chế trung thực còn lại trước khi đóng 100% Graduation Gate:** `defect_hit` trên 5 ca Docker `VIOLATION` đạt **`2/5 = 40%`** ở cấu hình tốt nhất (`Gen-4`: `M5` và `R14` đạt **`defect_hit_strict: true`**, `OR3` từng đạt **`defect_hit_strict: true`** ở Gen-2, `U2` đã thu hẹp từ cách 619 dòng xuống chỉ còn **cách 8 dòng**), chưa đạt ngưỡng `>= 80%`. Nguyên nhân gốc đã khoanh vùng rõ: `code.candidates` chưa pre-seed nhánh `SendAlert` / `TranslateErrorToAlert` cho họ `U`/`G` trong tệp `wolfssl/src/internal.c` dài 45.000 dòng, và `run_real_matrix.py` đang chạy đơn lượt `effort=efficient` (chưa bật `locate_best_of_k`).

| Tiêu chí Graduation Gate (`basic`) | Ngưỡng | Kết quả đo thật (`Gen-4` tốt nhất) | Trạng thái |
|---|---|---|---|
| `ci_pass` (`pytest`, `ruff`, `pyright`, `lint-imports`) | `true` | `true` (`268 passed`, 6/6 contracts) | **ĐẠT** |
| `adversarial_safe` (IFC + leak scan) | `true` | `true` | **ĐẠT** |
| `verdict_acc` (đủ 12/12 ca: 5 non-Docker + 7 Docker) | `100%` | **12/12 = 100%** (Wilson 95% trên 7 ca Docker: 65%–100%) | **ĐẠT** |
| `false_compliant` (bỏ sót lỗi) | `0` | **0/7 = 0%** | **ĐẠT** |
| `false_violation` (báo nhầm) | `0` | **0/5 = 0%** | **ĐẠT** |
| `skill_reloads` | `0` | **0** (`static_skills=True`) | **ĐẠT** |
| `defect_hit` (5 ca Docker `VIOLATION`: `M5, U2, G2, R14, OR3`) | `>= 80%` | **2/5 = 40%** (`M5` ✅, `R14` ✅; `OR3` ✅ ở Gen-2; `U2` lệch 8 dòng) | **CHƯA ĐẠT (cần cải tiến `diagnosis.py` / Best-of-K)** |

---

## 2. Toàn bộ tiến trình tự tiến hoá của Meta-Agent (`Gen-0` → `Gen-5`)

Mọi đột biến đều qua kiểm định `meta_evolve.py --check-policy` (`violations: []`, 100% nằm trong Whitelist [meta_policy.yaml](../../backend/eval/meta_policy.yaml), không đụng `VerdictEngine`, `SchemaGate`, IFC hay dataset).

### Giai đoạn A — 5 ca không Docker (`e2e_hard` & `e2e_live`)

| Thế hệ | Thay đổi (100% Whitelist) | Đúng nhãn | `hard-correct` | `gate_rejects` | `code.glob BAD_PARAMS` | `CR UsageLimitExceeded` | Token CR TB (`e2e_hard`) | Quyết định |
|---|---|---|---|---|---|---|---|---|
| **Gen-0** | Baseline sau vá `PlanAction` | 3/3 | `V6 (T1=0)` | 3 | 12 | 2 | 341.686 | Baseline |
| **Gen-1** | Thêm 4 dòng quy tắc SchemaGate & cấm path tuyệt đối | 3/3 | **`V5 LINKED (T1=1)`** | 2 | 2 (-83%) | 1 | 332.909 | **KEEP** |
| **Gen-2** | Sửa ví dụ `CONDITION.observed` từ `"record.length"` → `null` | **3/3** | **`V5 LINKED (T1=1)`** | **0 (-100%)** | **1 (-92%)** | **0 (-100%)** | **99.113 (-71%)** | **KEEP** |

### Giai đoạn B — 7 ca Docker thật (`M5`, `U2`, `G2`, `R14`, `OR3`, `M6`, `G4`)

| Thế hệ | Thay đổi (100% Whitelist) | Verdict (7 ca) | `false_compliant` | `defect_hit` (strict) | `gate_rejects` | `CR UsageLimitExceeded` | Phát hiện & Quyết định |
|---|---|---|---|---|---|---|---|
| **Gen-2** | Chạy lần đầu trên 7 ca Docker | 6/7 (`M5` crash `cexpr`) | 0 | 2/4 (`R14`, `OR3`) | **0** | 2 (`U2`, `G2`) | Phát hiện lỗi `ZeroDivisionError` ở `cexpr.py` (đã vá `589f2e0`) |
| **Gen-3** | Thêm `HARD_WRAP_SHARE = 0.78` theo token trong `runner.py` | **7/7 (100%)** | **0** | 1/5 (`R14`) | **0** | 2 (`M5`, `OR3` chạm `tool_calls=30`) | **KEEP** — triệt tiêu `UsageLimitExceeded` trên `U2`, `G2` (`wasted_share: 0.96 -> 0.0`) |
| **Gen-4** | Mở rộng `HARD_WRAP_SHARE = 0.78` sang `tool_calls` + thêm `defect_symbol`/`defect_lines` & ưu tiên `code.candidates` vào `code_reader/prompt.md` | **7/7 (100%)** | **0** | **2/5 (`M5`, `R14`)** | **0** | 1 (`OR3`: 31/30) | **KEEP (Mốc tốt nhất)** — `M5` trúng strict (`[26214,26216]` vs `26215`), `U2` từ cách 619 dòng → **8 dòng** (`26227` vs `26219`) |
| **Gen-5** | Hạ `HARD_TOOL_WRAP_SHARE = 0.65` (19/30) + nhắc kiểm tra nhánh liền kề | **7/7 (100%)** | **0** | 1/5 (`R14`) | 2 (`OR3`) | **0 (0/7)** | **REVERT** — cắt quá sớm ở 19 lời gọi khiến `M5`/`OR3` thiếu dữ liệu đọc (giảm `defect_hit` 40% → 20%). Khôi phục `0.78` của `Gen-4` |
| **Gen-6** | `candidate_patterns()` không phân biệt hoa thường (`SSL_AD_*`) + ưu tiên `observed_alerts` trước trong `diagnosis.py` / `handler.py` | **7/7 (100%)** | **0** | 1/5 (`OR3` strict trong 12 tool calls!) | 2 (`G2`) | 1 (`R14` do candidates phình 264–411 dòng) | **KEEP (tiền đề Gen-7)** — `OR3` (OpenSSL) từ `shown=0` nhảy thẳng lên **`defect_hit_strict: true`** |
| **Gen-7** | Thu gọn `code.candidates` (`context=2`, `head_limit=10/15`) + thêm 2 dòng xử lý `LINES_NOT_SHOWN`/`LINES_NOT_COMPILED` vào `code_reader/prompt.md` | **7/7 (100%)** | **0** | **2/5 (`R14`, `OR3` strict; 5/5 T1 đậu)** | **0 (0/7)** | **0 (0/7)** | **KEEP (Mốc sạch lỗi tuyệt đối)** — 12/12 verdict 100%, **0 gate rejects**, **0 `UsageLimitExceeded`**, **0 `worker_first_failures`**, cả wolfSSL (`R14`) & OpenSSL (`OR3`) trúng strict |

---

## 3. Kết quả chi tiết từng ca ở cấu hình tốt nhất (`Gen-4` — `DeepSeek-V4-Flash`)

### 5 ca không cần Docker (`Gen-2`)

| # | ID | Kỳ vọng | Nhãn hệ thống | Quy tắc | Ghi chú |
|---|---|---|---|---|---|
| 1 | `e2e-faulty` | `VIOLATION` | **`VIOLATION`** | `V2` | Có T1, 0 lỗi, 0% lãng phí |
| 2 | `e2e-correct` | `COMPLIANT` | **`COMPLIANT`** | `V5 (LINKED)` | Có T1, 0 lỗi, 0 retry |
| 3 | `hard-correct` | `COMPLIANT` | **`COMPLIANT`** | `V5 (LINKED)` | `T1=1`, `REACTION 1/1`, 0 gate reject, CR 297k token (-45%) |
| 4 | `hard-wrong-alert` | `VIOLATION` | **`VIOLATION`** | `V2` | 0 gate reject, 0 `UsageLimitExceeded` |
| 5 | `hard-no-close` | `VIOLATION` | **`VIOLATION`** | `V2` | 0 gate reject, 0 `UsageLimitExceeded` |

### 7 ca Docker thật `wolfSSL` & `OpenSSL` (`Gen-4`)

| # | ID | Họ | Kỳ vọng | Nhãn hệ thống | Quy tắc | `defect_hit` | Token tổng | Thời gian | Ghi chú định vị (T1) |
|---|---|---|---|---|---|---|---|---|---|
| 6 | `M5` | `R` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true` (strict)** | 362.442 | 144s | Trúng chính xác `DoProcessReplyEx` `[26214, 26216]` (chuẩn `26215`) |
| 7 | `U2` | `U` | `VIOLATION` | **`VIOLATION`** | `V2` | `false` | 458.460 | 45s | `src/internal.c:26227-26235` — **cách chuẩn `26219` đúng 8 dòng** |
| 8 | `G2` | `G` | `VIOLATION` | **`VIOLATION`** | `V2` | `false` | 479.897 | 53s | `src/internal.c:41663-41690` (`VerifyServerSuite`, chuẩn `39772-39776`) |
| 9 | `R14` | `R` | `VIOLATION` | **`VIOLATION`** | `V2` | **`true` (strict)** | 258.088 | 67s | Trúng chính xác `DoProcessReplyEx` `[26290, 26291]` (chuẩn `26290`) |
| 10 | `OR3` | `R` (OpenSSL) | `VIOLATION` | **`VIOLATION`** | `V2` | `false` (trúng ở Gen-2) | 372.530 | 115s | Chạm `tool_calls=31/30` ở batch song song cuối |
| 11 | `M6` | `R` | `COMPLIANT` | **`COMPLIANT`** | `V6 (BEHAVIORAL)` | — | 40.393 | 34s | Đối chứng âm tính đúng 100%, 1 vòng |
| 12 | `G4` | `G` | `COMPLIANT` | **`COMPLIANT`** | `V6 (BEHAVIORAL)` | — | 9.696 | 7s | Đối chứng âm tính đúng 100%, 1 vòng, chỉ 9,7k token |

---

## 4. Hướng cải tiến tiếp theo để nâng `defect_hit` vượt ngưỡng `>= 80%`

1. **Làm giàu `code.candidates` trong `backend/src/rfcv/domains/rfc_protocol/diagnosis.py` (nằm trong Whitelist):** Khi `T3` báo vi phạm họ `U` (`unexpected_message` / `reaction_absent`) hoặc họ `G` (`handshake_failure` / `missing_extension` / `no_shared_group`), tự động grep sẵn các dòng gọi `SendAlert` / `SSLfatal` / `TranslateErrorToAlert` liên quan vào `code.candidates` để `Code Reader` nhảy thẳng tới vùng lỗi trong tệp 45.000 dòng thay vì đọc tuần tự.
2. **Bật `locate_best_of_k` (`k=2` hoặc `3`)** cho các ca `VIOLATION` khi `T1` đầu tiên chưa có `defect_lines` hoặc có `REACTION=MATCH` mâu thuẫn với `T3=VIOLATION`.

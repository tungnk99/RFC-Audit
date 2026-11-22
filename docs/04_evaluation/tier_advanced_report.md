# Báo cáo Đánh giá Tầng `advanced` (RFC-Audit — Thuần AI Agent `Gen-18` → `Gen-21`)

Ngày đo: 2026-11-22 · Nhánh: `feat/nextgen-agent-research` · Mô hình: `DeepSeek-V4-Flash` (`fpt-deepseek-flash`, `static_skills=True`).
Định nghĩa tập mẫu Tầng `advanced` và ngưỡng tốt nghiệp: [tiered_benchmark.yaml](../../backend/eval/dataset/tiered_benchmark.yaml).
Nhật ký tiến hoá đầy đủ (`Gen-1`..`Gen-21`): [knowledge_base.md](../../backend/eval/evolution/knowledge_base.md) · [evolution_log.jsonl](../../backend/eval/evolution/evolution_log.jsonl).

---

## 1. Kết quả hiện tại trên Tầng `advanced` (100% Thuần AI Agent)

> [!IMPORTANT]
> **Tóm tắt trung thực năng lực Thuần AI Agent (`DeepSeek-V4-Flash`) trên Tầng `advanced`:**
> - **2 cổng an toàn & đặc tả (`CT08-injection`, `CT26-bad-rbs`):** **ĐẠT 100%** (`29/29 passed` trong `tests/test_policy_ifc.py` & `tests/test_divergence_verifier.py`).
> - **8 ca OpenSSL 3.x khó (`OU2`, `OU3`, `OU4`, `OG1`, `OG2`, `OG4`, `OR1`, `OX3`):**
>   - **Độ chính xác phân loại (`verdict_acc`): `8/8 = 100%`** xuyên suốt cả **4 đợt chạy (`32/32 = 100%`, 0% bỏ sót `false_compliant`, 0% báo nhầm `false_violation`)**.
>   - **Độ phủ định vị (`distinct strict hit`):** **`6/7 = 85,7%`** (`OU2`, `OU3`, `OG1`, `OG2`, `OG4`, `OR1` đều đã đạt `defect_hit_strict: true`).
>   - **Trần lượt đơn (`pass@1`) của thuần AI Agent `Flash` trên OpenSSL đa tệp:** dao động **`2/7 – 3/7 (29% – 43%)`**, chưa đạt ngưỡng `>= 70%` của Tầng `advanced`.
> - **Lưu ý về 4 ca thử thách (`M3`, `U3`, `M4`, `U5`):** trong `mutants.yaml` / `mutants_multi.yaml`, cả 4 ca này đang gắn cờ `excluded` (thêm mã/macro giả hoặc vi phạm câu RFC khác) nên `run_real_matrix.py` tự động loại khỏi tập chấm chuẩn.

### Bảng tiến hoá 4 thế hệ trên 8 ca OpenSSL 3.x khó (`Gen-18` → `Gen-21`)

| Thế hệ | Cải tiến thuần AI Agent | Verdict (8 ca) | `false_compliant` | `defect_hit` lượt đơn (7 `VIOLATION`) | Ca đạt `strict` |
|---|---|---|---|---|---|
| **Gen-18** | Baseline từ đỉnh `intermediate` (`90,9%` wolfSSL) | **8/8 (100%)** | **0** | `2/7 (29%)` | `OU3`, `OG4` |
| **Gen-19** | Prompt đa thư viện không phân biệt hoa thường (`SSLfatal`/`SSL_AD_*`) | **8/8 (100%)** | **0** | **`3/7 (43% strict)`** | `OG1`, `OG4`, `OR1` |
| **Gen-20** | Quy tắc RFC 8446 bản ghi rõ (`rec_layer_s3.c`) vs sau mã hoá + `head_limit=20/25` | **8/8 (100%)** | **0** | **`3/7 (43% strict)`** | **`OG1`, `OG2`, `OG4` (3/3 họ `G` = 100%)** |
| **Gen-21** | Sửa `diagnose()` nhận `WRONG_ALERT` khi cảnh báo hỗn hợp + thêm `WRONG_OBSERVED_ALERT` trong `precheck()` | **8/8 (100%)** | **0** | `2/7 (29% strict)` | **`OU2` (-62% token: `534k → 205k`)**, `OG4` |
| **Tổng hợp** | **32 lượt Docker thật trên OpenSSL 3.x** | **`32/32 (100%)`** | **`0/28 (0%)`** | **Độ phủ riêng biệt: `6/7 (85,7% strict)`** | `OU2`, `OU3`, `OG1`, `OG2`, `OG4`, `OR1` |

---

## 2. Phân tích khoa học: Vì sao Thuần AI Agent `Flash` đạt 90,9% trên wolfSSL nhưng chạm trần 43% lượt đơn trên OpenSSL 3.x?

1. **Cấu trúc mã nguồn khác biệt căn bản:**
   - `wolfSSL` tập trung phần lớn logic TLS 1.3 vào 2 tệp chính (`src/internal.c`, `src/tls13.c`), nên AI Agent `Flash` với ngân sách `110k` token / 11 lời gọi công cụ định vị chính xác tới **90,9% strict**.
   - `OpenSSL 3.x` tách tầng bản ghi và máy trạng thái qua **15+ tệp đa hình bằng con trỏ hàm** (`rec_layer_s3.c`, `tls13_meth.c`, `tls_common.c`, `tlsany_meth.c`, `extensions.c`, `extensions_srvr.c`, `statem_srvr.c`), trong đó nhiều hàm khác nhau cùng gọi `SSLfatal(..., SSL_AD_ILLEGAL_PARAMETER)` hoặc `SSL_AD_DECODE_ERROR`.
2. **Điểm chuyển giao nghiên cứu (Inflection Point cho luận văn):**
   - Kết quả thực nghiệm này chứng minh rõ **giới hạn thực của thuần AI Agent trên mô hình gọn `Flash`** khi đối mặt với kiến trúc đa hình nhiều tệp — tạo tiền đề khoa học thuyết phục để chuyển sang **pha kết hợp (Hybrid: kết hợp dữ liệu độ phủ động gcov/dấu vết thực thi hoặc đồ thị gọi hàm với AI Agent)** để vượt mốc `>= 70%` trên OpenSSL Tầng `advanced`!

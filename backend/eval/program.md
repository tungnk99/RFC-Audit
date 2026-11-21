# Program: Vòng lặp Tự Khám phá, Tự Cải tiến & Tự Phản biện theo Tầng (RFC-Audit)

Tài liệu này là luật chơi cho AI Agent tự chạy nghiên cứu tiến hoá (theo tinh thần Karpathy `autoresearch` + Google `AlphaEvolve` + `AI Co-Scientist`) trên bộ dữ liệu phân tầng `backend/eval/dataset/tiered_benchmark.yaml`.

## 1. Quy tắc bất biến (Vi phạm = loại ngay biến thể)
1. `eval_score.py` phải đạt `ci_pass == 1`, `ruff_ok == 1`, `pyright_ok == 1`, `import_linter_ok == 1`, `adversarial_safe == 1`.
2. **Không bao giờ** đụng vào hoặc tối ưu trên tập `held_out` (19 mẫu đóng băng).
3. **Không bao giờ** giảm ngưỡng hoặc thay thế AI Agent bằng script cứng để gian lận điểm.
4. `false_compliant` trên mọi tầng bắt buộc bằng `0`.

## 2. Lộ trình tốt nghiệp bắt buộc (Basic → Intermediate → Advanced → Held-out)

### Giai đoạn A — Chinh phục Tầng `basic` (12 mẫu)
- **Mục tiêu:** Đạt toàn bộ `graduation_gate` của tầng `basic`:
  - `verdict_acc = 100%`, `false_compliant = 0`, `defect_hit >= 80%`, `worker_first_failures = 0`, `skill_reloads = 0`.
- **Đầu ra bắt buộc trước khi lên tầng:** Xuất bản báo cáo tầng `basic` kèm số đo thật, phân tích lỗi (nếu có) và commit sạch.

### Giai đoạn B — Chinh phục Tầng `intermediate` (16 mẫu: 7 lỗi thật wolfSSL + 9 ca trượt/phình token)
- **Mục tiêu:** Kéo `defect_hit` từ **32% (0/3 lỗi thật)** lên **`>= 65%` (và `>= 2/3` lỗi thật)**, giảm `avg_tokens <= 220k` (đặc biệt xử lý ca `U7` từ 509k xuống `<= 100k`), giữ `false_compliant = 0`.
- **Đòn bẩy được phép tự khám phá:**
  1. **Contrastive Trace Mining:** Đọc trace các ca trượt (`bug`, `P1-parent`, `P3-parent`, `M1`, `U1`, `G1`, `OU1`) để xác định đúng *first divergence step*.
  2. **Nâng cấp ACI (`code__read` / call-graph / error-stack hints):** Giúp `Code Reader` không bị trỏ nhầm hàm khi lỗi nằm trong `TranslateErrorToAlert` hay `extensions.c`.
  3. **Bật Best-of-K có điều kiện (`locate_best_of_k`)** khi T3 báo `VIOLATION` hoặc lượt đầu ra `UNCLEAR`.
  4. **Tối ưu đường tắt hợp lệ cho họ U** (tìm nguyên nhân vì sao `U7` vẫn đọc mã dù T3 đã PASS).
- **Đầu ra bắt buộc:** Xuất báo cáo tầng `intermediate` so sánh trước/sau kèm bảng `results.tsv`.

### Giai đoạn C — Chinh phục Tầng `advanced` (14 mẫu: `M3/U3` `#ifdef`, `M4/U5` cửa sổ hẹp, OpenSSL khó, `CT-08`, `CT-26`)
- **Mục tiêu:** Bắt được các ca hiểm `M4`, `U5` (nơi T3 mặc định bị mù) thông qua đọc mã T1 + mở rộng biến thể, chạy lặp `n >= 3` kèm khoảng tin cậy Wilson 95% và đa họ mô hình (`DeepSeek` + `GLM`).
- **Nghiệm thu cuối:** Chạy duy nhất 1 lần trên tập `held_out` (19 mẫu đóng băng) và chạy Hội đồng Phản biện 4 Vai trước khi chốt luận văn.

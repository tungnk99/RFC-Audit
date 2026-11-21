# Báo cáo Đánh giá Tầng `basic` (RFC-Audit)

Ngày đo: 2026-11-21 · Nhánh: `feat/nextgen-agent-research` · Mô hình: `DeepSeek-V4-Flash` (`fpt-deepseek-flash`, `static_skills=True`).
Định nghĩa tập mẫu và ngưỡng tốt nghiệp: [tiered_benchmark.yaml](../../backend/eval/dataset/tiered_benchmark.yaml).

---

## 1. Kết luận Cổng Tốt nghiệp (Graduation Gate — Tầng `basic`)

> [!WARNING]
> **Trạng thái Tầng `basic`: CHƯA TỐT NGHIỆP (5/5 ca không Docker ĐÚNG NHÃN, còn 2 điểm chặn rõ ràng).**
> 1. Trên 3 ca `e2e_hard.py`, nhãn đạt **3/3 đúng** (sau khi phát hiện và vá lỗi `PlanAction` thiếu `tasks` bắt buộc), nhưng `Code Reader` vẫn ra `T1 = 0` do bị `BAD_PARAMS` lặp ở `code.glob` trên môi trường `NoExec` → chưa đạt ngưỡng `defect_hit >= 80%`.
> 2. **7 ca Docker thật** (`M5`, `U2`, `G2`, `R14`, `OR3`, `M6`, `G4`) chưa chạy được vì Docker Desktop trên máy đang tắt.

| Tiêu chí Graduation Gate (`basic`) | Ngưỡng | Kết quả đo thật | Trạng thái |
|---|---|---|---|
| `ci_pass` (`pytest`, `ruff`, `pyright`, `lint-imports`) | `true` | `true` (`266 passed`, 6/6 contracts) | **ĐẠT** |
| `adversarial_safe` (IFC + leak scan) | `true` | `true` | **ĐẠT** |
| `verdict_acc` (5 ca không Docker) | `100%` | **5/5 = 100%** | **ĐẠT** |
| `false_compliant` | `0` | **0** | **ĐẠT** |
| `skill_reloads` | `0` | **0** (`static_skills=True`) | **ĐẠT** |
| `defect_hit` / T1 trên `e2e_hard` | `>= 80%` | **0/3** (`code.glob` `BAD_PARAMS` → chạm `tool_calls_limit = 30`) | **CHƯA ĐẠT** |
| 7 ca Docker thật (`M5`, `U2`, `G2`, `R14`, `OR3`, `M6`, `G4`) | Chạy đủ | Chưa chạy (Docker Desktop tắt) | **CHỜ DOCKER** |

---

## 2. Kết quả chi tiết 5 ca không cần Docker (LLM thật `DeepSeek-V4-Flash`)

| # | ID | Kỳ vọng | Nhãn hệ thống | Quy tắc | T1 / REACTION | Token tổng (CR) | Ghi chú |
|---|---|---|---|---|---|---|---|
| 1 | `e2e-faulty` | `VIOLATION` | **`VIOLATION`** | `V2` | Có T1, 0 lỗi | 232.127 (175k) | 1 vòng, 0% lãng phí, 0 retry |
| 2 | `e2e-correct` | `COMPLIANT` | **`COMPLIANT`** | `V5 (LINKED)` | Có T1, 0 lỗi | 777.978 (383k) | Mọi worker 0 lỗi, 0 retry |
| 3 | `hard-correct` | `COMPLIANT` | **`COMPLIANT`** | `V6` | `T1 = 0` | CR 517.905 | Đúng nhãn sau bản vá `PlanAction` |
| 4 | `hard-wrong-alert` | `VIOLATION` | **`VIOLATION`** | `V2` | `T1 = 0` | CR 189.735 | `code.glob` `BAD_PARAMS` ×7 → hết 30 tool calls |
| 5 | `hard-no-close` | `VIOLATION` | **`VIOLATION`** | `V2` | `T1 = 0` | CR 0 | T3 đủ kết luận V2 sớm |

---

## 3. Lỗi thật đã phát hiện & vá ngay trong quá trình chạy Tầng `basic`

1. **Lỗi P0 của `PlanAction` JSON Schema trên model nhỏ/nhanh (ĐÃ VÁ):**
   - *Hiện tượng:* Ở lần chạy đầu, cả 3/3 ca `e2e_hard.py` đều ra `UNVERIFIABLE (V9)` sau 8 vòng vì `DeepSeek-V4-Flash` liên tục gọi `final_result({"action": "dispatch", "rationale_code": "INITIAL_TYPE_B"})` mà bỏ qua trường `tasks`.
   - *Nguyên nhân gốc (Contrastive Trace Mining):* `build_plan_action_model` khai báo `tasks` với `Field(default_factory=list)` nên `"tasks"` không nằm trong `"required"` của JSON Schema; đồng thời thông điệp retry trong `runner.py` đang viết cứng cho `Code Reader`.
   - *Cách vá:* Đưa `tasks` thành trường bắt buộc (`...`) trong [schemas.py](../../backend/src/rfcv/agents/schemas.py), bổ sung `_PlanGate` trong [execution_loop.py](../../backend/src/rfcv/core/execution_loop.py), và sửa thông điệp retry tổng quát trong [runner.py](../../backend/src/rfcv/runtime/pydantic_ai/runner.py).
   - *Kết quả sau vá:* Cả **3/3 ca `e2e_hard.py` nhảy từ `0/3 UNVERIFIABLE` lên `3/3 ĐÚNG NHÃN`**.

---

## 4. Việc cần làm để tốt nghiệp 100% Tầng `basic` trước khi lên `intermediate`

1. **Vá lỗi `code.glob` `BAD_PARAMS` trên `Code Reader` (`code_tools.py`):** Kiểm tra tham số mẫu mà `DeepSeek-V4-Flash` truyền vào `code.glob` (ví dụ mẫu bắt đầu bằng `/` hoặc `..` hoặc ký tự bị `_safe_rel` chặn) và trả gợi ý sửa tham số rõ ràng thay vì chỉ `DENIED: BAD_PARAMS`, để `e2e_hard` tạo được T1 và đạt recall `REACTION = 100%`.
2. **Bật Docker Desktop và chạy 7 ca Docker Tầng `basic`** (`M5`, `U2`, `G2`, `R14`, `OR3`, `M6`, `G4`) để chốt `defect_hit >= 80%` rồi mới mở khóa Tầng `intermediate`.

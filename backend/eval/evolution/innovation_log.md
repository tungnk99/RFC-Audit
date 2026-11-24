# Nhật ký Đổi mới Tiến hoá (RFC-Audit)

| Thế hệ | Mức & Phép | Loại đóng góp | Tóm tắt & Kết quả | Bậc năng lực |
|---|---|---|---|---|
| **gen-34** | `L4 REMOVE_AGENT` | Gỡ bỏ gen lặn (Recessive Gene Removal — mục C2) | Tắt gọi Planner LLM mặc định khi `scripted_plans=True` gặp lỗi tác vụ (`planner_llm_fallback=False`), thay bằng dừng sạch `playbook_stop` và lưu `planner_llm_fallback` vào `gene_bank.yaml` để có thể REINTRODUCE.
 | bậc 1 (giảm nhiễu & ngân sách trên bài toán hiện tại) |

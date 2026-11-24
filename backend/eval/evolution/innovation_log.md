# Nhật ký Đổi mới Tiến hoá (RFC-Audit)

| Thế hệ | Mức & Phép | Loại đóng góp | Tóm tắt & Kết quả | Bậc năng lực |
|---|---|---|---|---|
| **gen-34** | `L4 REMOVE_AGENT` | Gỡ bỏ gen lặn (Recessive Gene Removal — mục C2) | Tắt gọi Planner LLM mặc định khi `scripted_plans=True` gặp lỗi tác vụ (`planner_llm_fallback=False`), thay bằng dừng sạch `playbook_stop` và lưu `planner_llm_fallback` vào `gene_bank.yaml` để có thể REINTRODUCE.
 | bậc 1 (giảm nhiễu & ngân sách trên bài toán hiện tại) |
| **gen-35** | `L2 REMOVE_HARDCODE` | Tổng quát hoá không phụ thuộc thư viện (Library-Agnostic Cleanup — mục C6) | Gỡ bỏ 100% tên hàm, tên tệp và macro đặc thù wolfSSL/OpenSSL (`DoProcessReplyEx`, `DoServerHello`, `CompleteServerHello`, `tls13_validate_record_header`, `ssl3_read_bytes`, `ssl/statem/extensions.c`, `ssl/record/rec_layer_s3.c`, `KEY_SHARE_ERROR`, `MATCH_SUITE_ERROR`, `SendFatalAlertOnly`, `SSLfatal`) khỏi `code_reader/handler.py` và làm trung lập hoàn toàn `skills/core/locate-alert-sites/SKILL.md` (vượt qua `test_skills_protocol_neutral.py`).
 | bậc 3 (cổng mới — xoá toàn bộ tên hàm/tệp/macro đặc thù wolfSSL/OpenSSL khỏi lõi) |

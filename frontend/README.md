# frontend

Giao diện tương tác cho hệ thống kiểm chứng. Chưa dựng.

## Nguyên tắc

- Frontend **không import Python và không đọc `.env`**: khóa API chỉ nằm ở `backend/`.
- Hai phía nói chuyện qua HTTP. Backend sẽ thêm lớp API tại `backend/src/rfcv/api/` (cạnh `ui/cli.py`); hợp đồng là OpenAPI, nên chọn framework frontend nào cũng được.
- Dữ liệu cần hiển thị đã có sẵn ở backend: gói lần chạy `runs/<run_id>`, trace (`rfcv trace --json`), báo cáo SARIF.

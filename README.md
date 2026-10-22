# RFC-Audit

Kiểm chứng tự động và an toàn sự tuân thủ đặc tả giao thức mạng (RFC) dựa trên bằng chứng, dùng hệ thống AI đa tác tử. Mã nguồn cho luận văn của Nguyễn Kỳ Tùng.

## Cấu trúc

| Thư mục | Vai trò |
|---|---|
| [backend/](backend/) | Engine Python `rfcv`: agents, skills, adapters, cấu hình, kiểm thử, đánh giá. Hướng dẫn cài đặt và chạy: [backend/README.md](backend/README.md) |
| [frontend/](frontend/) | Giao diện tương tác (chưa dựng). Xem [frontend/README.md](frontend/README.md) |
| [docs/](docs/) | Tài liệu thiết kế, đánh giá, tiêu chuẩn chất lượng, theo dõi cải thiện. Mục lục: [docs/README.md](docs/README.md) |

Mọi lệnh Python chạy trong `backend/`:

```bash
cd backend
uv sync
uv run pytest -q
```

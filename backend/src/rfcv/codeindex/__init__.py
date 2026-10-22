"""Chỉ mục mã và bộ chạy lệnh thật cho Code gate (tài liệu khám phá mã, mục 5 và 12).

- `workspace`: dựng bản sao chỉ gồm phần `code_scope` của kho mã tại commit cố định (tệp khoá, chứng chỉ, symlink bị
  loại ngay lúc sao), kèm digest để ghi bản kê lần chạy.
- `builder`: phân tích bản sao bằng tree-sitter (C, Rust, Go) và ghi chỉ mục SQLite: ký hiệu, lời gọi, tham chiếu,
  khối lệnh, nhánh tiền xử lý. Chạy trong container `code-indexer` (không mạng, kho mã chỉ đọc) hoặc tại chỗ khi phát
  triển.
- `sqlite_index`: `SqliteCodeIndex`, cài đặt Protocol `CodeIndex`, mở chỉ mục ở chế độ chỉ đọc.
- `executors`: `DockerExecutor` chạy lệnh của explore/search_text bằng argv (execve, không shell) trong container
  `code-index-worker`; `LocalExecutor` chỉ cho phát triển, phải bật tường minh.
- `providers`: factory đăng ký vào registry (`treesitter`, `treesitter-local`, `docker`, `local-unsandboxed`).
"""

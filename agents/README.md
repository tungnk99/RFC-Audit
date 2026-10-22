# Agent: hồ sơ và lời nhắc (dữ liệu, ngoài mã nguồn)

Mỗi thư mục là một agent: `agents/<tên>/role.yaml` (hồ sơ vai trò) và `agents/<tên>/prompt.md` (lời nhắc hệ thống). Đây là nơi
**duy nhất** chứa hai thứ đó; muốn đổi hành vi một agent thì sửa ở đây, không sửa mã nguồn. Xem bản đồ bằng `uv run rfcv agents`.

```
agents/
  planner/        role.yaml  prompt.md      Planner (đặc quyền)
  test/           role.yaml  prompt.md      Test (đặc quyền)
  verifier/       role.yaml  prompt.md      Verifier (đặc quyền)
  rfc_analyst/    role.yaml  prompt.md      RFC Analyst (đặc quyền, chưa nối vào luồng chạy)
  report/         role.yaml  prompt.md      Report (đặc quyền, chưa nối)
  code_reader/    role.yaml  prompt.md      Code Reader (cách ly)
  code_indexer/   role.yaml  prompt.md      Code Indexer (cách ly, chưa nối)
```

Phần **mã** của mỗi agent (schema đầu ra, handler, khai báo `SPEC`, sổ tay điều tra của Planner) ở
`src/rfcv/domains/rfc_protocol/agents/<tên>/`. Mã không bao giờ được nạp từ thư mục này.

## Tìm thư mục

Theo thứ tự: tuỳ chọn `--agents` / `RuntimeConfig.agents_root`, biến môi trường `RFCV_AGENTS_DIR`, `./agents`, rồi `agents/` ở gốc
repo (cài kiểu phát triển). Khi triển khai, thư mục này phải đi cùng bản cài, giống `adapters/` và `skills/`.

## Quy tắc (ép lúc nạp bởi `PolicyStore`, có test)

- Chỉ nạp **dữ liệu**; tệp Python đặt ở đây không bao giờ chạy.
- `zone` và `output_schema` trong `role.yaml` phải khớp khai báo trong mã (`AgentSpec`): dữ liệu cấu hình không đổi được kiến trúc.
- Công cụ phải có trong danh mục và đúng luật vùng (agent đặc quyền không có công cụ đọc dữ liệu không tin cậy, và ngược lại).
- Tên thư mục phải trùng `role:`; mỗi agent khai báo trong mã phải có thư mục ở đây; `prompt:` phải trỏ tới tệp có thật.
- Hash hồ sơ và lời nhắc được ghi vào bản kê lần chạy, nên một lần chạy luôn tái lập được.
- Lời nhắc của Planner có một khối §5 sinh từ dữ liệu sổ tay (giữa hai dấu `playbook:begin/end`); đừng sửa tay khối đó, chạy
  `sync_prompt` (`agents/planner/playbook.py`). Test sẽ báo lệch.

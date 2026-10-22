# Agent: hồ sơ và lời nhắc (dữ liệu, ngoài mã nguồn)

Mỗi thư mục là một agent: `agents/<tên>/role.yaml` (hồ sơ vai trò) và `agents/<tên>/prompt.md` (lời nhắc hệ thống). Đây là nơi
**duy nhất** chứa hai thứ đó; muốn đổi hành vi một agent thì sửa ở đây, không sửa mã nguồn. Xem bản đồ bằng `uv run rfcv agents`.

```
agents/
  planner/        role.yaml  prompt.md      Planner (đặc quyền)
  tester/         role.yaml  prompt.md      Test (đặc quyền)
  verifier/       role.yaml  prompt.md      Verifier (đặc quyền)
  rfc_analyst/    role.yaml  prompt.md      RFC Analyst (đặc quyền, chưa nối vào luồng chạy)
  report/         role.yaml  prompt.md      Report (đặc quyền, chưa nối)
  code_reader/    role.yaml  prompt.md      Code Reader (cách ly)
  code_indexer/   role.yaml  prompt.md      Code Indexer (cách ly, chưa nối)
```

Mỗi agent là **một thư mục** gồm cả dữ liệu (`role.yaml`, `prompt.md`) lẫn mã (`schema.py`, `handler.py`, `__init__.py` khai báo
`SPEC`, riêng Planner có `playbook.py`). `agents/` là gói Python `agents` ngoài `rfcv`, được đóng gói cùng wheel.
`PolicyStore` chỉ đọc `role.yaml` và `prompt.md`, không bao giờ nạp mã từ đường dẫn tìm được (kể cả khi trỏ `RFCV_AGENTS_DIR`
sang nơi khác): mã luôn lấy từ gói `agents` đã cài. `locator/` là thành phần tất định nên chỉ có mã, không có `role.yaml`.

## Tìm thư mục

Theo thứ tự: tuỳ chọn `--agents` / `RuntimeConfig.agents_root`, biến môi trường `RFCV_AGENTS_DIR`, `./agents`, rồi `agents/` ở gốc
repo (cài kiểu phát triển). Khi triển khai, thư mục này phải đi cùng bản cài, giống `adapters/` và `skills/`.

## Quy tắc (ép lúc nạp bởi `PolicyStore`, có test)

- Chỉ nạp **dữ liệu**; tệp Python đặt ở đây không bao giờ chạy.
- `zone` và `output_schema` trong `role.yaml` phải khớp khai báo trong mã (`AgentSpec`): dữ liệu cấu hình không đổi được kiến trúc.
- Công cụ phải có trong danh mục và đúng luật vùng (agent đặc quyền không có công cụ đọc dữ liệu không tin cậy, và ngược lại).
- Skill lấy từ kho chung `skills/` (`core/` và `<adapter>/`), nhưng agent chỉ thấy skill nó **khai báo** ở `skills:` trong
  `role.yaml`; không khai báo thì không có skill nào. Tên khai báo phải có trong `skills/` (sai tên là lỗi lúc lắp runtime);
  skill của adapter khác chỉ bị bỏ qua trong lần chạy đó. Skill không tự chọn agent (`rfcv-roles` bị từ chối), chỉ được
  giới hạn theo kiểu nhiệm vụ bằng `rfcv-task-types`. Xem bằng `uv run rfcv skills check skills --adapter tls13`.
- Tên thư mục phải trùng `role:`; mỗi agent khai báo trong mã phải có thư mục ở đây; `prompt:` phải trỏ tới tệp có thật.
- Hash hồ sơ và lời nhắc được ghi vào bản kê lần chạy, nên một lần chạy luôn tái lập được.
- Lời nhắc của Planner có một khối §5 sinh từ dữ liệu sổ tay (giữa hai dấu `playbook:begin/end`); đừng sửa tay khối đó, chạy
  `sync_prompt` (`agents/planner/playbook.py`). Test sẽ báo lệch.

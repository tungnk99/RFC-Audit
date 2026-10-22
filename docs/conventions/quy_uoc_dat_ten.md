# Quy ước đặt tên file và thư mục

Quy ước này ghi lại cách đặt tên mà repo **đang dùng**, cộng vài điều chỉnh nhỏ cho nhất quán. Phần kiểm được bằng máy nằm ở
[tests/test_naming.py](../../backend/tests/test_naming.py); đổi quy ước thì sửa cả hai nơi. Những chỗ còn lệch chưa sửa được ghi ở
[CT-19](../management/theo_doi_cai_thien.md#ct-19--p3--tên-chưa-thống-nhất-ở-vài-chỗ).

## Nguyên tắc chung

1. **Chỉ dùng ASCII, không dấu, không khoảng trắng.** Nội dung có thể tiếng Việt; tên file và thư mục thì không. Tài liệu tiếng
   Việt đặt tên bằng tiếng Việt không dấu (`thiet_ke_phoi_hop_agent.md`), mã nguồn đặt tên bằng tiếng Anh.
2. **Tên nói nội dung, không nói trạng thái.** Không đặt `final`, `new`, `old`, `copy`, `backup`, `v2` vào tên. Lịch sử thuộc
   về git và về sổ theo dõi.
3. **Mặc định là `snake_case`.** Chỉ dùng kiểu khác khi một chuẩn bên ngoài đòi hỏi (bảng dưới ghi rõ lý do).
4. Thư mục chứa nhiều thực thể cùng loại dùng số nhiều (`agents/`, `skills/`, `adapters/`, `tests/`, `scripts/`); thư mục theo
   chức năng dùng danh từ ngắn (`config/`, `docker/`, `docs/`).

## Theo từng loại

| Loại | Quy tắc | Ví dụ | Ghi chú |
|---|---|---|---|
| Gói và module Python | `snake_case`, tiếng Anh | `execution_loop.py`, `core/`, `codeindex/` | Thư mục gói có `__init__.py` |
| Lớp / hàm / hằng | `PascalCase` / `snake_case` / `UPPER_SNAKE` | `ExecutionLoop`, `build_runtime`, `MAX_LINES` | PEP 8 |
| Agent | `agents/<tên_vai_trò>/` | `agents/code_reader/` | Tên thư mục **phải trùng** `role:` trong `role.yaml` (bộ nạp kiểm). Bên trong cố định: `role.yaml`, `prompt.md`, `schema.py`, `handler.py`, `__init__.py` (khai báo `SPEC`); thêm module riêng nếu cần (`playbook.py`) |
| Skill | `kebab-case`, bắt đầu bằng động từ | `skills/core/trace-all-entry-paths/` | Chuẩn agentskills.io: `^[a-z0-9]+(-[a-z0-9]+)*$`, tối đa 64 ký tự, phải **trùng** `name:` trong `SKILL.md`. Tệp phụ chỉ ở `references/*.md` |
| Nhóm skill | `core/` hoặc tên adapter | `skills/core/`, `skills/tls13/` | `core/` là skill không gắn giao thức |
| Adapter | `adapters/<id>/`, chữ thường liền | `adapters/tls13/` | Tệp YAML trong adapter dùng `snake_case` (`known_bugs.yaml`) |
| Đặc tả hành vi | Theo mã yêu cầu | `TLS13-0042.rbs` | Mã yêu cầu viết hoa: `<GIAO_THỨC>-<số>` |
| Cấu hình | `config/<chủ_đề>.yaml` | `config/models.yaml` | Chỉ ghi tên biến môi trường chứa khoá, không ghi khoá |
| Tài liệu | `docs/<nhóm>/<tiền_tố>_<chủ_đề>.md`, `snake_case` không dấu | `docs/design/thiet_ke_adapter_kiem_thu.md` | Nhóm và tiền tố cho phép: xem mục "Cấu trúc `docs/`" bên dưới. Trang mục lục của thư mục là `README.md` |
| Hình trong tài liệu | `docs/figures/<tên_tài_liệu>_hinh_<n>.svg` | `thiet_ke_phoi_hop_agent_hinh_1.svg` | Ô chú thích màu: `docs/figures/legend/legend_<nn>.svg` |
| Bản HTML gốc | `docs/html/<cùng tên tài liệu>.html` | | Chỉ để đối chiếu, có thể xoá |
| Test | `tests/test_<mô_đun_hoặc_chủ_đề>.py` | `test_execution_loop.py` | Dùng chung: `conftest.py`, `fakes.py`, `helpers.py`, `toy_domain.py`. Hàm test `test_<hành_vi>` bằng tiếng Anh |
| Script | `scripts/<động_từ>_<đối_tượng>.py` | `analyze_run.py`, `e2e_live.py` | Có docstring đầu file nói cách chạy. Script của bộ đánh giá cũng nằm ở đây, tiền tố `eval_` (`eval_make_manifest.py`); `eval/` chỉ chứa dữ liệu và cấu hình |
| Dockerfile | `<tên-kebab>.Dockerfile` | `code-index-worker.Dockerfile` | Thói quen của Docker |
| CI | `.github/workflows/<tên>.yml` | `ci.yml` | |
| Dữ liệu chạy | `runs/<id>/`, `*.db`, `index/` | `runs/e2e-faulty/` | **Không commit** (đã có trong `.gitignore`) |

## Cấu trúc `docs/`

Tài liệu chia theo **mục đích**. Tên thư mục nhóm bằng tiếng Anh (cùng kiểu với các thư mục khác của repo), tên file bằng tiếng Việt
không dấu. Mỗi file có tiền tố của nhóm nên tên vẫn rõ khi xuất hiện riêng lẻ (kết quả tìm kiếm, tab trình soạn thảo).

| Nhóm | Dùng cho | Tiền tố file | Ví dụ |
|---|---|---|---|
| `overview/` | Giới thiệu cho người mới đọc | `tong_quan_` | `tong_quan_he_thong.md` |
| `design/` | Thiết kế hệ thống và thành phần | `thiet_ke_` | `thiet_ke_phoi_hop_agent.md` |
| `evaluation/` | Thiết kế đánh giá, kết quả thực nghiệm | `thiet_ke_`, `danh_gia_` | `danh_gia_kha_thi_thuc_nghiem.md` |
| `deliverables/` | Checklist các sản phẩm bàn giao | `checklist_` | `checklist_he_thong.md` |
| `quality/` | Tiêu chuẩn chất lượng: hệ thống cần đạt gì, từng phần cần làm được gì | `tieu_chuan_` | `tieu_chuan_agent.md` |
| `management/` | Quản lý công việc: vấn đề, số đo, hạn chế | `theo_doi_` | `theo_doi_cai_thien.md` |
| `conventions/` | Quy ước làm việc | `quy_uoc_` | `quy_uoc_dat_ten.md` |
| `figures/`, `html/` | Tài nguyên: sơ đồ SVG, bản HTML gốc | theo bảng ở trên | |

Quy tắc: không đặt file `.md` trực tiếp ở gốc `docs/` (trừ `README.md`), không lồng thêm thư mục trong một nhóm, không có nhóm rỗng.
Cần loại tài liệu mới thì thêm nhóm hoặc tiền tố vào bảng này **và** vào `DOC_FOLDERS` trong [test_naming.py](../../backend/tests/test_naming.py),
rồi thêm vào mục lục [docs/README.md](../README.md).

## Định danh bên trong mã và dữ liệu

| Loại | Quy tắc | Ví dụ |
|---|---|---|
| Biến môi trường | `UPPER_SNAKE`, có tiền tố nhà cung cấp hoặc `RFCV_` | `DEEPSEEK_API_KEY`, `RFCV_AGENTS_DIR` |
| Kiểu nhiệm vụ, mã lý do, loại vấn đề phản biện | `UPPER_SNAKE` | `SELECT_TESTS`, `INITIAL_TYPE_B`, `MISSING_PATH` |
| Quy tắc kết luận | `V0` … `V9` | `V2`, `V5` |
| Tên mô hình trong `config/models.yaml` | `kebab-case`, theo tên nhà cung cấp | `deepseek-flash` |
| Loại sự kiện trong trace | `snake_case` | `plan_context`, `t3_case` |
| Mã lần chạy | `run-<12 ký tự hex>` | `run-ab12cd34ef56` |
| Mục trong sổ theo dõi | `CT-<nn>` đang mở, `R-<nn>` đã xử lý | `CT-01`, `R-11` |

## Khi thêm file mới

1. Tìm dòng tương ứng trong bảng trên rồi đặt tên theo đó. Chưa có loại phù hợp thì thêm một dòng vào bảng **và** vào test.
2. Chạy `uv run pytest tests/test_naming.py`.
3. Đổi tên file hay thư mục đã có thì kiểm các liên kết tương đối trong Markdown và các chuỗi đường dẫn trong mã trước khi gộp.

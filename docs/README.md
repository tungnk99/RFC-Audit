# Tài liệu của dự án

Tài liệu đi kèm luận văn *"Kiểm chứng tự động và an toàn sự tuân thủ đặc tả giao thức mạng dựa trên bằng chứng, sử dụng hệ
thống AI đa tác tử"* (Nguyễn Kỳ Tùng, GVHD TS. Tống Văn Vạn). Mỗi tài liệu có mục lục riêng ở đầu trang.

> **English readers:** the project summary, quick start and status are in the [root README](../README.md). These documents are written in Vietnamese; start with the [system overview](01_overview/system_overview.md).

## Cấu trúc

```
docs/
  01_overview/     tổng quan (đọc đầu tiên) và quy ước đặt tên
  02_design/       thiết kế hệ thống và từng thành phần
  03_quality/      tiêu chuẩn chất lượng: hệ thống và từng thành phần cần đạt gì
  04_evaluation/   thiết kế đánh giá và kết quả thực nghiệm
  05_project/      quản lý dự án: backlog, sổ theo dõi cải thiện, checklist deliverable
  assets/figures/  sơ đồ SVG dùng trong các tài liệu
  archive/html/    bản HTML gốc của các tài liệu thiết kế, để đối chiếu
```

Các thư mục đánh số theo thứ tự nên đọc. Tên file bằng tiếng Anh (`snake_case`), nội dung bằng tiếng Việt.

## Tổng quan

| Tài liệu | Nói về |
|---|---|
| [Tổng quan hệ thống](01_overview/system_overview.md) | Hệ thống làm gì, luồng xử lý, các agent, bản đồ thư mục, chạy thử nhanh, trạng thái |

## Thiết kế

Nên đọc theo thứ tự này. Cột cuối là phần mã tương ứng.

| # | Tài liệu | Nói về | Mã nguồn tương ứng |
|---|---|---|---|
| 1 | [Thiết kế chi tiết hệ thống](02_design/system_design.md) | Bản hoàn chỉnh: bài toán, giải pháp, kiến trúc, an toàn, kế hoạch | toàn bộ [src/rfcv/](../backend/src/rfcv/) |
| 2 | [Nguồn RFC và cách cung cấp RFC cho agent](02_design/rfc_provisioning_design.md) | RFC gate, RFC Analyst, từ văn bản RFC tới đặc tả hành vi (RBS) | [rfc_gate.py](../backend/src/rfcv/domains/rfc_protocol/rfc_gate.py), [agents/rfc_analyst/](../backend/agents/rfc_analyst/) |
| 3 | [Khả năng khám phá mã nguồn của agent](02_design/code_exploration_design.md) | Code gate, Locator, Code Indexer, Code Reader, bộ công cụ đọc mã | [code_gate.py](../backend/src/rfcv/gates/code_gate.py), [codeindex/](../backend/src/rfcv/codeindex/), [agents/code_reader/](../backend/agents/code_reader/), [agents/locator/](../backend/agents/locator/), [agents/code_indexer/](../backend/agents/code_indexer/) |
| 4 | [Hướng dẫn và phối hợp các agent](02_design/agent_coordination_design.md) | Vòng điều tra, Planner, Verifier, báo cáo độ đủ, điều kiện dừng | [execution_loop.py](../backend/src/rfcv/core/execution_loop.py), [verdict_engine.py](../backend/src/rfcv/evidence/verdict_engine.py), [agents/planner/](../backend/agents/planner/) |
| 5 | [Protocol adapter và kiểm thử thực tế (T3)](02_design/adapter_and_testing_design.md) | Adapter, mẫu kịch bản, Test driver, SUT, oracle | [adapters/](../backend/adapters/), [sandbox/](../backend/src/rfcv/domains/rfc_protocol/sandbox/), [backends/](../backend/src/rfcv/backends/) |

## Đánh giá

| Tài liệu | Nói về | Mã nguồn tương ứng |
|---|---|---|
| [Thiết kế đánh giá](04_evaluation/evaluation_design.md) | Thực nghiệm của luận văn, chỉ số, mô phỏng | [src/rfcv/eval/](../backend/src/rfcv/eval/), [eval/README.md](../backend/eval/README.md) |
| [Đánh giá khả thi và thực nghiệm sơ bộ](04_evaluation/feasibility_assessment.md) | Thử trên lỗi thật của wolfSSL (14/10/2026) | |

## Tiêu chuẩn chất lượng

Hệ thống phải đạt gì thì mới gọi là "work", và từng phần phải làm được gì, đạt gì. Mỗi tiêu chuẩn có ngưỡng, cách đo và trạng thái hiện tại.

| Tài liệu | Nói về |
|---|---|
| [Tiêu chuẩn toàn hệ thống](03_quality/system_standards.md) | Năm tầng: an toàn, chống đối thủ, đúng, dùng được, tổng quát; ngưỡng tối thiểu và mục tiêu đăng ký trước |
| [Yêu cầu đầu ra](03_quality/output_requirements.md) | Khi dùng thực tế hệ thống phải giải quyết được gì: bao phủ RFC, mở rộng giao thức, phát hiện triển khai sai RFC mà không bỏ sót im lặng, dùng trong vòng đời phát triển, an toàn, quy mô |
| [Tiêu chuẩn các agent](03_quality/agent_standards.md) | Verifier, Planner, Code Reader, Test, Code Indexer, RFC Analyst, Report: phải làm được gì, phải đạt gì |
| [Tiêu chuẩn các thành phần tất định](03_quality/deterministic_component_standards.md) | Execution loop, các cổng, Test driver, Verdict engine, Evidence store, LLM gateway, Adapter checker |

## Checklist deliverable

[Checklist các sản phẩm bàn giao](05_project/README.md): bốn checklist (hệ thống và mã nguồn, thực nghiệm, mốc tiến độ, tài liệu và
luận văn) với trạng thái từng hạng mục và bằng chứng. Xem tiến độ bằng `uv run python scripts/checklist_progress.py`.

## Quản lý công việc

[Sổ theo dõi cải thiện](05_project/improvement_log.md) ghi các vấn đề đang mở và đã xử lý, nhật ký đo và danh sách hạn chế. Các
tài liệu thiết kế mô tả **thiết kế**; chỗ mã chưa khớp thiết kế (agent hay thành phần chưa nối, phần chạy thật chưa dựng) được ghi
ở sổ này và ở lệnh `uv run rfcv agents`. Đổi prompt, skill, cấu hình hay mô hình thì chạy lại phép đo ([scripts/](../backend/scripts/)) và
cập nhật sổ. Checklist trả lời "đã giao chưa", sổ theo dõi trả lời "còn vấn đề gì", [backlog công việc](05_project/backlog.md) trả lời "làm việc gì để gỡ". Backlog bám sát yêu cầu đầu ra và các vấn đề đang mở, có test kiểm mọi yêu cầu đều có việc; xem tiến độ bằng `uv run python scripts/backlog_progress.py`.

## Quy ước

[Quy ước đặt tên file và thư mục](01_overview/naming_conventions.md): ASCII, `snake_case` mặc định, ngoại lệ do chuẩn bên ngoài
đòi hỏi, kèm test [tests/test_naming.py](../backend/tests/test_naming.py) để quy ước không trôi.

## Hình và bản HTML gốc

- Sơ đồ nằm ở [figures/](assets/figures/) dưới dạng SVG và được tài liệu Markdown nhúng bằng ảnh. Ô chú thích màu trong các bảng ký hiệu nằm
  ở [figures/legend/](assets/figures/legend/). SVG được tách ra vì GitHub không hiển thị SVG nhúng trực tiếp trong Markdown.
- Các tài liệu thiết kế trước đây viết bằng HTML. Bản Markdown là bản chính để sửa. Bản HTML gốc giữ ở [html/](archive/html/) để đối chiếu,
  có thể xoá khi đã duyệt xong bản Markdown. Hộp ghi chú trong tài liệu dùng cú pháp cảnh báo của GitHub (`> [!NOTE]`,
  `> [!TIP]`, `> [!WARNING]`); trình xem khác chỉ hiện như khối trích dẫn.
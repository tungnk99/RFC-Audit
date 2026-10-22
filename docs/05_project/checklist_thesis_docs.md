# Checklist: tài liệu, luận văn và bàn giao

Quy ước đánh dấu: xem [README](README.md). Trạng thái ghi theo ngày **2026-10-22**. Danh mục luận văn dưới đây chỉ nêu các sản phẩm
mà tài liệu thiết kế đã nhắc tới; thêm chương và mục khi thống nhất cấu trúc luận văn với thầy.

## Tài liệu kỹ thuật (trong repo)

- [x] Thiết kế chi tiết hệ thống: [system_design.md](../02_design/system_design.md)
- [x] Nguồn RFC và cách cung cấp RFC cho agent: [rfc_provisioning_design.md](../02_design/rfc_provisioning_design.md)
- [x] Khả năng khám phá mã nguồn: [code_exploration_design.md](../02_design/code_exploration_design.md)
- [x] Hướng dẫn và phối hợp các agent: [agent_coordination_design.md](../02_design/agent_coordination_design.md)
- [x] Protocol adapter và kiểm thử thực tế: [adapter_and_testing_design.md](../02_design/adapter_and_testing_design.md)
- [x] Thiết kế đánh giá: [evaluation_design.md](../04_evaluation/evaluation_design.md)
- [x] Đánh giá khả thi và thực nghiệm sơ bộ: [feasibility_assessment.md](../04_evaluation/feasibility_assessment.md)
- [x] Tổng quan hệ thống: [system_overview.md](../01_overview/system_overview.md)
- [x] Quy ước đặt tên: [naming_conventions.md](../01_overview/naming_conventions.md), có test giữ quy ước
- [x] Yêu cầu đầu ra (năng lực cần có khi dùng thực tế): [output_requirements.md](../03_quality/output_requirements.md)
- [x] Tiêu chuẩn chất lượng: [toàn hệ thống](../03_quality/system_standards.md), [các agent](../03_quality/agent_standards.md), [các thành phần tất định](../03_quality/deterministic_component_standards.md)
- [x] Backlog công việc bám sát yêu cầu đầu ra và sổ theo dõi, có test kiểm: [backlog.md](../05_project/backlog.md)
- [x] Sổ theo dõi cải thiện và nhật ký đo: [improvement_log.md](../05_project/improvement_log.md)
- [ ] Cập nhật các tài liệu thiết kế cho khớp mã sau khi dựng xong phần chạy thật (thiết kế đang mô tả quy tắc `R0–R7`, mã dùng `V0–V9`; kiểm lại các chỗ tương tự)
- [ ] Duyệt bản Markdown rồi quyết định giữ hay xoá bản HTML gốc ở `docs/archive/html/` ([CT-19](../05_project/improvement_log.md#ct-19--p3--tên-chưa-thống-nhất-ở-vài-chỗ))

## Các điểm cần thầy xác nhận

Mỗi mục là một nhóm câu hỏi đang để ngỏ trong tài liệu thiết kế. Tích khi đã có câu trả lời và đã cập nhật vào tài liệu.

- [ ] Vấn đề cần góp ý của thiết kế chung: [mục 6.2](../02_design/system_design.md#62-vấn-đề-cần-thầy-góp-ý)
- [ ] Phối hợp agent (chi tiết hoá trường `finding`, luôn chạy Verifier trước COMPLIANT, sổ tay điều tra): [mục 14](../02_design/agent_coordination_design.md#14-rủi-ro-và-điểm-cần-xác-nhận)
- [ ] Nguồn RFC: dùng RFC 8446 kèm errata làm đặc tả chính hay dùng thẳng RFC 9846: cuối [tài liệu cung cấp RFC](../02_design/rfc_provisioning_design.md)
- [ ] Adapter và kiểm thử thực tế: cuối [tài liệu adapter](../02_design/adapter_and_testing_design.md)
- [ ] Đánh giá (chỉ số, ngưỡng mục tiêu): [mục 13](../04_evaluation/evaluation_design.md#13-điểm-cần-thầy-xác-nhận)
- [ ] Chốt phạm vi "hỗ trợ RFC" (danh sách RFC và giao thức, mức hỗ trợ) và năm điểm cần xác nhận ở cuối [yêu cầu đầu ra](../03_quality/output_requirements.md#cần-thầy-xác-nhận): [CT-22](../05_project/improvement_log.md#ct-22--p1--phạm-vi-hỗ-trợ-rfc-chưa-chốt)
- [ ] Chốt một bộ ngưỡng chất lượng thống nhất giữa Bảng 8, 13 và 30: [CT-20](../05_project/improvement_log.md#ct-20--p1--ngưỡng-chất-lượng-chưa-thống-nhất-giữa-các-tài-liệu-thiết-kế), tiêu chuẩn ở [system_standards.md](../03_quality/system_standards.md)
- [ ] Ngưỡng "work thực tế" (Bảng 13): [kế hoạch kiểm chứng thực tế](../04_evaluation/feasibility_assessment.md#7-kế-hoạch-kiểm-chứng-thực-tế)

## Luận văn

- [ ] Thống nhất cấu trúc các chương với thầy; ghi danh sách chương và nơi lưu bản nháp vào đây
- [ ] Bản nháp các chương (chưa có trong repo)
- [ ] Kết quả RQ1–RQ5 kèm bảng và hình ([checklist thực nghiệm](checklist_experiments.md))
- [ ] Phần hạn chế và mối đe doạ tính hợp lệ: đã có bản nháp danh sách ở mục "Hạn chế đã biết" của [sổ theo dõi](../05_project/improvement_log.md#hạn-chế-đã-biết-cho-phần-hạn-chế-của-luận-văn); cần viết thành văn bản luận văn
- [ ] Tài liệu tham khảo: danh sách nằm ở [mục 6.3](../02_design/system_design.md#63-tài-liệu-tham-khảo) của thiết kế; cần chuẩn hoá theo mẫu của trường
- [ ] Hoàn thiện theo góp ý và nộp luận văn (05/2027)
- [ ] Slide bảo vệ
- [ ] Bản demo chạy được (ghi rõ phần giả và phần thật, xem [tổng quan](../01_overview/system_overview.md#chạy-thử-nhanh))
- [ ] Bảo vệ (đầu 06/2027)

## Bàn giao mã nguồn và tái lập

- [x] README hướng dẫn cài đặt và chạy: [README.md](../../README.md)
- [x] Giấy phép: [LICENSE](../../LICENSE)
- [x] Không đưa khoá API vào repo: khoá chỉ đọc từ biến môi trường, `.env` nằm trong `.gitignore`
- [x] Bản kê lần chạy ghi hash của lời nhắc, skill, mô hình, quy tắc, adapter: [manifest.py](../../backend/src/rfcv/manifest.py)
- [ ] CI xanh: [ci.yml](../../.github/workflows/ci.yml) chạy `ruff`, `pyright`, `lint-imports`, `pytest`. Cục bộ `pytest`, `lint-imports`, `ruff check`, `ruff format --check` và `pyright` đều sạch (BL-90); **chưa xác nhận trên GitHub**: workflow chỉ chạy với push lên `main` và pull request, các lần chạy trên `main` đến nay đều đỏ (commit cũ) ([CT-14](../05_project/improvement_log.md#ct-14--p3--nợ-kiểm-tra-tĩnh))
- [ ] Hướng dẫn tái lập thực nghiệm từng bước, từ commit kho mã tới bảng kết quả
- [ ] Gói tái lập cho lần chạy chính thức, lưu riêng ngoài git: `manifest.json`, `evidence.db`, `trace.db`, artifacts, cấu hình mô hình
- [ ] Digest các image Docker ghi vào bản kê ([docker/](../../backend/docker/))
- [ ] Gắn thẻ git cho phiên bản nộp luận văn

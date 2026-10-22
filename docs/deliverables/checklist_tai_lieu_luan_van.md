# Checklist: tài liệu, luận văn và bàn giao

Quy ước đánh dấu: xem [README](README.md). Trạng thái ghi theo ngày **2026-10-22**. Danh mục luận văn dưới đây chỉ nêu các sản phẩm
mà tài liệu thiết kế đã nhắc tới; thêm chương và mục khi thống nhất cấu trúc luận văn với thầy.

## Tài liệu kỹ thuật (trong repo)

- [x] Thiết kế chi tiết hệ thống: [thiet_ke_chi_tiet_he_thong.md](../design/thiet_ke_chi_tiet_he_thong.md)
- [x] Nguồn RFC và cách cung cấp RFC cho agent: [thiet_ke_cung_cap_rfc.md](../design/thiet_ke_cung_cap_rfc.md)
- [x] Khả năng khám phá mã nguồn: [thiet_ke_doc_ma_nguon.md](../design/thiet_ke_doc_ma_nguon.md)
- [x] Hướng dẫn và phối hợp các agent: [thiet_ke_phoi_hop_agent.md](../design/thiet_ke_phoi_hop_agent.md)
- [x] Protocol adapter và kiểm thử thực tế: [thiet_ke_adapter_kiem_thu.md](../design/thiet_ke_adapter_kiem_thu.md)
- [x] Thiết kế đánh giá: [thiet_ke_danh_gia.md](../evaluation/thiet_ke_danh_gia.md)
- [x] Đánh giá khả thi và thực nghiệm sơ bộ: [danh_gia_kha_thi_thuc_nghiem.md](../evaluation/danh_gia_kha_thi_thuc_nghiem.md)
- [x] Tổng quan hệ thống: [tong_quan_he_thong.md](../overview/tong_quan_he_thong.md)
- [x] Quy ước đặt tên: [quy_uoc_dat_ten.md](../conventions/quy_uoc_dat_ten.md), có test giữ quy ước
- [x] Yêu cầu đầu ra (năng lực cần có khi dùng thực tế): [tieu_chuan_dau_ra.md](../quality/tieu_chuan_dau_ra.md)
- [x] Tiêu chuẩn chất lượng: [toàn hệ thống](../quality/tieu_chuan_he_thong.md), [các agent](../quality/tieu_chuan_agent.md), [các thành phần tất định](../quality/tieu_chuan_thanh_phan_tat_dinh.md)
- [x] Backlog công việc bám sát yêu cầu đầu ra và sổ theo dõi, có test kiểm: [theo_doi_backlog.md](../management/theo_doi_backlog.md)
- [x] Sổ theo dõi cải thiện và nhật ký đo: [theo_doi_cai_thien.md](../management/theo_doi_cai_thien.md)
- [ ] Cập nhật các tài liệu thiết kế cho khớp mã sau khi dựng xong phần chạy thật (thiết kế đang mô tả quy tắc `R0–R7`, mã dùng `V0–V9`; kiểm lại các chỗ tương tự)
- [ ] Duyệt bản Markdown rồi quyết định giữ hay xoá bản HTML gốc ở `docs/html/` ([CT-19](../management/theo_doi_cai_thien.md#ct-19--p3--tên-chưa-thống-nhất-ở-vài-chỗ))

## Các điểm cần thầy xác nhận

Mỗi mục là một nhóm câu hỏi đang để ngỏ trong tài liệu thiết kế. Tích khi đã có câu trả lời và đã cập nhật vào tài liệu.

- [ ] Vấn đề cần góp ý của thiết kế chung: [mục 6.2](../design/thiet_ke_chi_tiet_he_thong.md#62-vấn-đề-cần-thầy-góp-ý)
- [ ] Phối hợp agent (chi tiết hoá trường `finding`, luôn chạy Verifier trước COMPLIANT, sổ tay điều tra): [mục 14](../design/thiet_ke_phoi_hop_agent.md#14-rủi-ro-và-điểm-cần-xác-nhận)
- [ ] Nguồn RFC: dùng RFC 8446 kèm errata làm đặc tả chính hay dùng thẳng RFC 9846: cuối [tài liệu cung cấp RFC](../design/thiet_ke_cung_cap_rfc.md)
- [ ] Adapter và kiểm thử thực tế: cuối [tài liệu adapter](../design/thiet_ke_adapter_kiem_thu.md)
- [ ] Đánh giá (chỉ số, ngưỡng mục tiêu): [mục 13](../evaluation/thiet_ke_danh_gia.md#13-điểm-cần-thầy-xác-nhận)
- [ ] Chốt phạm vi "hỗ trợ RFC" (danh sách RFC và giao thức, mức hỗ trợ) và năm điểm cần xác nhận ở cuối [yêu cầu đầu ra](../quality/tieu_chuan_dau_ra.md#cần-thầy-xác-nhận): [CT-22](../management/theo_doi_cai_thien.md#ct-22--p1--phạm-vi-hỗ-trợ-rfc-chưa-chốt)
- [ ] Chốt một bộ ngưỡng chất lượng thống nhất giữa Bảng 8, 13 và 30: [CT-20](../management/theo_doi_cai_thien.md#ct-20--p1--ngưỡng-chất-lượng-chưa-thống-nhất-giữa-các-tài-liệu-thiết-kế), tiêu chuẩn ở [tieu_chuan_he_thong.md](../quality/tieu_chuan_he_thong.md)
- [ ] Ngưỡng "work thực tế" (Bảng 13): [kế hoạch kiểm chứng thực tế](../evaluation/danh_gia_kha_thi_thuc_nghiem.md#7-kế-hoạch-kiểm-chứng-thực-tế)

## Luận văn

- [ ] Thống nhất cấu trúc các chương với thầy; ghi danh sách chương và nơi lưu bản nháp vào đây
- [ ] Bản nháp các chương (chưa có trong repo)
- [ ] Kết quả RQ1–RQ5 kèm bảng và hình ([checklist thực nghiệm](checklist_thuc_nghiem.md))
- [ ] Phần hạn chế và mối đe doạ tính hợp lệ: đã có bản nháp danh sách ở mục "Hạn chế đã biết" của [sổ theo dõi](../management/theo_doi_cai_thien.md#hạn-chế-đã-biết-cho-phần-hạn-chế-của-luận-văn); cần viết thành văn bản luận văn
- [ ] Tài liệu tham khảo: danh sách nằm ở [mục 6.3](../design/thiet_ke_chi_tiet_he_thong.md#63-tài-liệu-tham-khảo) của thiết kế; cần chuẩn hoá theo mẫu của trường
- [ ] Hoàn thiện theo góp ý và nộp luận văn (05/2027)
- [ ] Slide bảo vệ
- [ ] Bản demo chạy được (ghi rõ phần giả và phần thật, xem [tổng quan](../overview/tong_quan_he_thong.md#chạy-thử-nhanh))
- [ ] Bảo vệ (đầu 06/2027)

## Bàn giao mã nguồn và tái lập

- [x] README hướng dẫn cài đặt và chạy: [README.md](../../README.md)
- [x] Giấy phép: [LICENSE](../../LICENSE)
- [x] Không đưa khoá API vào repo: khoá chỉ đọc từ biến môi trường, `.env` nằm trong `.gitignore`
- [x] Bản kê lần chạy ghi hash của lời nhắc, skill, mô hình, quy tắc, adapter: [manifest.py](../../src/rfcv/manifest.py)
- [ ] CI xanh: [ci.yml](../../.github/workflows/ci.yml) chạy `ruff`, `pyright`, `lint-imports`, `pytest`. Cục bộ `pytest` và `lint-imports` đạt; `ruff` còn 2 lỗi, khoảng 10 file chưa định dạng, `pyright` còn 16 lỗi ([CT-14](../management/theo_doi_cai_thien.md#ct-14--p3--nợ-kiểm-tra-tĩnh))
- [ ] Hướng dẫn tái lập thực nghiệm từng bước, từ commit kho mã tới bảng kết quả
- [ ] Gói tái lập cho lần chạy chính thức, lưu riêng ngoài git: `manifest.json`, `evidence.db`, `trace.db`, artifacts, cấu hình mô hình
- [ ] Digest các image Docker ghi vào bản kê ([docker/](../../docker/))
- [ ] Gắn thẻ git cho phiên bản nộp luận văn

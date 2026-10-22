# Checklist deliverable của dự án

Danh sách sản phẩm cần bàn giao của cả dự án, để biết **cái gì đã có bằng chứng, cái gì còn dở, cái gì chưa làm**. Danh mục lấy từ
các tài liệu thiết kế (Bảng 26 công sức, Bảng 27 mốc, Bảng 28–29 đánh giá), không tự thêm sản phẩm ngoài thiết kế trừ phần hạ tầng
phát triển đã ghi riêng.

| Checklist | Nội dung |
|---|---|
| [checklist_he_thong.md](checklist_he_thong.md) | Hệ thống và mã nguồn theo tầng 1, 2, 3: lõi, bằng chứng, đọc mã, RBS, backend và adapter, agent, DNS, đường cơ sở, dữ liệu |
| [checklist_thuc_nghiem.md](checklist_thuc_nghiem.md) | Câu hỏi nghiên cứu RQ1–RQ5, đường cơ sở, dữ liệu, tiêu chí "work thực tế" |
| [checklist_moc_tien_do.md](checklist_moc_tien_do.md) | Lịch từ 10/2026 đến bảo vệ 06/2027 và các cổng G1, G2, G3 |
| [checklist_tai_lieu_luan_van.md](checklist_tai_lieu_luan_van.md) | Tài liệu, các điểm cần thầy xác nhận, luận văn, bàn giao và tái lập |

## Tiến độ (ảnh chụp ngày 2026-10-22)

| Checklist | Xong / tổng | Tỉ lệ |
|---|---|---|
| Hệ thống và mã nguồn | 22 / 46 | 48% |
| Thực nghiệm và đánh giá | 2 / 24 | 8% |
| Mốc và tiến độ | 5 / 32 | 16% |
| Tài liệu, luận văn, bàn giao | 16 / 40 | 40% |
| **Tổng** | **45 / 142** | **32%** |

Số hiện tại tính bằng `uv run python scripts/checklist_progress.py` (thêm `--open` để liệt kê các hạng mục chưa xong). Bảng trên là
ảnh chụp; cập nhật khi có mốc mới. Tỉ lệ đếm theo **số hạng mục**, không theo công sức: một hạng mục lớn như backend kiểm thử thật
chỉ tính bằng một dòng, nên đừng đọc 31% như 31% công việc.

## Cách đánh dấu

- `- [x]` **Xong**: có bằng chứng đọc được ngay cạnh hạng mục (liên kết tới mã, test, tài liệu hoặc kết quả chạy).
- `- [ ]` **Chưa xong**: gồm cả chưa làm lẫn làm dở. Làm dở thì ghi rõ trên cùng dòng đã có gì và còn thiếu gì, kèm liên kết tới mục
  tương ứng trong [sổ theo dõi](../management/theo_doi_cai_thien.md) (CT-xx).
- Cổng (G1, G2, G3) chỉ tích khi đạt **đúng tiêu chí của thiết kế**. Đạt trên môi trường giả không tính; ghi chú kết quả giả ngay trên dòng.

## Cách cập nhật

1. Làm xong một hạng mục thì đổi `[ ]` thành `[x]` **cùng lúc** với việc thêm liên kết bằng chứng. Không có bằng chứng thì không tích.
2. Đổi ngày ở dòng "Trạng thái ghi theo ngày" của checklist đã sửa, rồi chạy `scripts/checklist_progress.py` và cập nhật bảng tiến độ ở trên.
3. Thiết kế đổi (thêm bớt hạng mục, dời mốc) thì sửa tài liệu thiết kế trước, rồi sửa checklist cho khớp. Checklist không tự quyết phạm vi.
4. Vấn đề phát sinh khi làm một hạng mục thì ghi ở sổ theo dõi, không ghi ở đây. Checklist trả lời "đã giao chưa", sổ theo dõi trả lời "còn vấn đề gì".

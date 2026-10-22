# Checklist: thực nghiệm và đánh giá

Nguồn: [thiết kế đánh giá](../evaluation/thiet_ke_danh_gia.md), [phương pháp đánh giá (mục 5.3)](../design/thiet_ke_chi_tiet_he_thong.md#53-phương-pháp-đánh-giá)
và [kế hoạch kiểm chứng thực tế](../evaluation/danh_gia_kha_thi_thuc_nghiem.md#7-kế-hoạch-kiểm-chứng-thực-tế). Quy ước đánh dấu: xem
[README](README.md). Trạng thái ghi theo ngày **2026-10-22**.

> [!WARNING]
> Chưa có số liệu thực nghiệm nào trên bản triển khai thật. Kết quả hiện có đều từ mô phỏng (SUT và mã giả), chỉ chứng minh cơ chế
> phối hợp chạy được. Không dùng chúng làm số liệu cho luận văn.

## Câu hỏi nghiên cứu (Bảng 28)

Mỗi câu hỏi chỉ được tích khi có số liệu từ thực nghiệm trên bản triển khai thật, kèm khoảng biến thiên.

- [ ] **RQ1** Kết luận chính xác đến đâu? Precision và recall VIOLATION, tỉ lệ COMPLIANT sai, theo loại A–D và mức assurance, độ chính xác vị trí mã
- [ ] **RQ2** So với SOTA và cách khác thế nào? B0, B2, B3 trên cùng ca, kiểm định McNemar
- [ ] **RQ3** Mỗi cơ chế đóng góp bao nhiêu? Ablation: bỏ lần lượt hai luồng RBS, nhân chứng, liên kết độ phủ, tổng hợp kịch bản
- [ ] **RQ4** Chịu được đối thủ đến đâu? Tỉ lệ đổi nhãn dưới A1–A7 so với B1 và B0
- [ ] **RQ5** Chi phí và tính tổng quát? Token, tiền, thời gian, phút công người mỗi yêu cầu; chi phí kiểm chứng lại; số dòng lõi đổi và tuần công khi thêm DNS; độ ổn định qua ba lần chạy

## Đường cơ sở (Bảng 29)

- [ ] **B0** RFCAudit trên cùng kho mã và tập yêu cầu
- [ ] **B1** Hệ thống đầy đủ nhưng tắt cách ly, IFC, kiểm tra tham số (đo giá trị của cơ chế an toàn)
- [ ] **B2** Không agent: toàn bộ mẫu TLS-Anvil, tlsfuzzer phù hợp
- [ ] **B3** Kiểu iPanda: LLM viết chương trình kiểm thử và tự đánh giá
- [ ] **Thủ công** Người kiểm chứng thủ công 20 yêu cầu TLS 1.3, ghi thời gian (mốc chi phí công người)

## Dữ liệu

- [ ] TLS 1.3: khoảng 40–60 yêu cầu trên ba bản triển khai, mỗi kho mã cố định tại một commit
- [ ] DNS: khoảng 15–20 yêu cầu trên ba bản triển khai
- [ ] Tập chia phát triển và đánh giá chính (47 commit sau 7/2026 làm tập chính, các commit trước làm tập phát triển)
- [ ] Danh sách lỗi thật đã được người xác nhận: [commit ứng viên](../../eval/dataset/real/wolfssl_commit_ung_vien.csv) còn cột do người điền
- [ ] Năm commit loại B sau 7/2026 (gồm `c18833f52`) bọc thành mẫu adapter, chạy tay trên commit cha và commit sửa (hạn giữa tháng 11). Hiện [known_bugs.yaml](../../adapters/tls13/validation/known_bugs.yaml) mới có **1/5**
- [ ] Báo cáo kết quả tách trước và sau mốc kiến thức của mô hình (chống rò rỉ dữ liệu)
- [ ] Cố định phiên bản: commit kho mã, mô hình, hash lời nhắc, hash skill ghi trong bản kê lần chạy (cơ chế đã có ở [manifest.py](../../src/rfcv/manifest.py); cần dùng cho lần chạy thật)

## Tiêu chí "work thực tế" (Bảng 13 của đánh giá khả thi)

Ngưỡng là đề xuất, **cần thầy chốt**.

| Tiêu chí | Ngưỡng đề xuất | Hiện có |
|---|---|---|
| COMPLIANT sai trên commit lỗi | 0 (tối đa 5%) | chưa đo |
| Recall trên lỗi lịch sử loại A–C | ≥ 60% | chưa đo |
| Precision của VIOLATION | ≥ 80% | chưa đo |
| Vị trí mã đúng cho VIOLATION | ≥ 70% | chưa đo |
| Tỉ lệ được kết luận, loại A–C | ≥ 60% | chưa đo |
| Chi phí mỗi yêu cầu | đo ở lát cắt dọc rồi đặt trần | mô phỏng: khoảng 210–250 nghìn token mỗi yêu cầu (SUT giả, chưa đại diện) |

- [ ] Thầy chốt các ngưỡng trên (và thống nhất với Bảng 8 và Bảng 30, xem [CT-20](../management/theo_doi_cai_thien.md#ct-20--p1--ngưỡng-chất-lượng-chưa-thống-nhất-giữa-các-tài-liệu-thiết-kế); mức tối thiểu và mục tiêu đầy đủ ở [tiêu chuẩn hệ thống](../quality/tieu_chuan_he_thong.md))
- [ ] Đo đủ sáu tiêu chí trên lát cắt dọc, sau đó trên tập mở rộng

## Phép đo đã có (không tính là số liệu thực nghiệm)

- [x] Mô phỏng cơ chế (`rfcv eval sim`, `rfcv eval coord`), có đăng ký trước và băm cấu hình: [coord_prereg.py](../../src/rfcv/eval/coord_prereg.py)
- [x] Phép thử đầu-cuối với LLM thật trên SUT giả, hai ca: bản lỗi ra `VIOLATION` (V2), bản đúng ra `COMPLIANT` (V5, LINKED). Số đo và cách chạy lại ở [sổ theo dõi](../management/theo_doi_cai_thien.md#nhật-ký-đo)
- [ ] Mỗi ca chạy ít nhất 3 lần để biết độ ổn định ([CT-16](../management/theo_doi_cai_thien.md#ct-16--p1--chưa-có-số-đo-thống-kê))
- [ ] Phép thử đối kháng với mô hình thật, ca có chỉ thị độc trong mã ([CT-08](../management/theo_doi_cai_thien.md#ct-08--p1--chưa-thử-đối-kháng-với-mô-hình-thật))
- [ ] So sánh có và không có skill ([CT-06](../management/theo_doi_cai_thien.md#ct-06--p2--chưa-biết-skill-có-giúp-ích-không))

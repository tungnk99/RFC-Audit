# Checklist: mốc và tiến độ

Nguồn: [Bảng 27 (tiến độ và mốc kiểm tra)](../design/thiet_ke_chi_tiet_he_thong.md#52-tiến-độ-và-mốc-kiểm-tra),
[Bảng 12 của tài liệu adapter](../design/thiet_ke_adapter_kiem_thu.md#15-kế-hoạch-xây-dựng) và
[kế hoạch kiểm chứng thực tế](../evaluation/danh_gia_kha_thi_thuc_nghiem.md#7-kế-hoạch-kiểm-chứng-thực-tế). Quy ước đánh dấu: xem
[README](README.md). Trạng thái ghi theo ngày **2026-10-22**.

Thời gian xây dựng và thực nghiệm: giữa tháng 10/2026 đến cuối tháng 02/2027, khoảng 20 tuần làm việc. Tầng 1 vừa khít, còn một tuần
dự phòng; tầng 2 và 3 chỉ làm khi các mốc trước đạt sớm.

## 14/10 – 31/10/2026: chốt thiết kế và dựng môi trường

- [x] Chốt thiết kế: [thiết kế chi tiết](../design/thiet_ke_chi_tiet_he_thong.md) và sáu tài liệu thành phần, đánh giá
- [ ] Dựng backend kiểm thử: tlsfuzzer (thay TLS-Attacker nếu cầu nối quá 2 tuần) ([CT-09](../management/theo_doi_cai_thien.md#ct-09--p0--chưa-có-backend-kiểm-thử-thật-và-bộ-chạy-sut-thật))
- [ ] Dựng ba SUT TLS, mỗi SUT hai bản (thường và đo độ phủ). Điều kiện cắt: kho mã nào quá 3 ngày chưa dựng được thì thay ứng viên. Đã có sẵn bản sao mã nguồn wolfSSL, tlsfuzzer, tlslite-ng trong `eval/work/`
- [ ] Chạy RFCAudit trên một SUT (làm mốc B0)

## 01/11 – 30/11: lõi harness và lát cắt dọc

- [x] Lõi harness, Evidence store, Verdict engine, Code gate, Oracle compiler (xem [checklist hệ thống](checklist_he_thong.md))
- [ ] Cầu nối backend kiểm thử với harness (quá 2 tuần thì dùng tlsfuzzer cho tầng 1)
- [ ] Giữa tháng 11: năm commit loại B sau 7/2026 bọc thành mẫu adapter (hiện 1/5)
- [ ] **G1:** ca K3 (TLS13-0042) chạy trọn luồng, đúng nhãn cho bản gốc và bản đột biến, có T3 liên kết. *Đã đạt với SUT giả (2026-10-22: bản lỗi `VIOLATION` V2, bản đúng `COMPLIANT` V5 LINKED); chưa đạt trên wolfSSL thật nên chưa tích.*
- [ ] Cuối tháng 11: lát cắt dọc với agent LLM thật cho TLS13-0042 và năm lỗi loại B; đo độ chính xác Code Reader theo từng khía cạnh và đo chi phí

Kế hoạch xây dựng phần kiểm thử thực tế (Bảng 12 của tài liệu adapter):
- [ ] Tuần 1: runner tlsfuzzer chọn ca, đọc kết quả, chuẩn hoá quan sát; công thức SUT wolfSSL trong Docker. Đầu ra: chạy lại được bảng ví dụ bằng một lệnh
- [x] Tuần 2: Test driver (vòng đời, sanity, chạy lại ca FAIL, bản ghi T3). Còn thiếu phần ghép mẫu của Tool gateway theo Bảng 7 trên backend thật
- [ ] Tuần 3: Adapter checker 5 kiểm tra (đã có phần hình thức, các kiểm tra cần sandbox đang bỏ qua) và `known_bugs.yaml` đủ 5 lỗi loại B (hiện 1/5)
- [ ] Tuần 4: mở rộng danh mục mẫu TLS theo các mục RFC trong phạm vi; runner DSL tối thiểu; báo cáo độ phủ (số yêu cầu có mẫu hợp lệ)

Ba rủi ro kỹ thuật lớn nhất, thử trong 6 tuần đầu:
- [x] Liên kết độ phủ (Coverage linker): chạy được với SUT giả, chưa với bản đo độ phủ thật
- [ ] Cầu nối DSL tới backend kiểm thử thật
- [ ] Dựng SUT (và bản đo độ phủ) thật

## 01/12 – 20/12: bảy agent và hai luồng RBS

- [ ] Bảy agent nối đủ vào luồng chạy (hiện 5/7: chưa nối RFC Analyst, Report)
- [ ] Hai luồng RBS (RFC Analyst chạy hai mô hình khác họ) và so khớp ([CT-05](../management/theo_doi_cai_thien.md#ct-05--p1--agent-không-thấy-câu-rfc), [CT-07](../management/theo_doi_cai_thien.md#ct-07--p2--một-mô-hình-cho-mọi-agent), [CT-12](../management/theo_doi_cai_thien.md#ct-12--p2--rfc-analyst-chưa-nối-loại-c-d-thiếu-mẫu-và-skill))
- [x] Nhân chứng (witness) trong Test driver
- [ ] Ca K1 và K2 với adapter TLS 1.2 nhỏ
- [ ] **G2:** K1–K3 đúng nhãn, có và không có tấn công A1, A7 mức 1. Chưa đạt thì bỏ hẳn tầng 2
- [ ] Quyết định có làm tầng 2 hay không (chỉ nếu G2 đạt trước 15/12)

## 21/12/2026 – 31/01/2027: DNS và bộ dữ liệu

- [ ] Backend và adapter DNS chạy được
- [ ] Số dòng thay đổi trong `core/` và `gates/` khi thêm DNS bằng **0** (đếm bằng git)
- [ ] Bộ dữ liệu: đột biến tự động, lỗi thật đã xác nhận, kịch bản tấn công A1–A7
- [ ] Tầng 2 (chỉ nếu G2 đạt sớm): học máy trạng thái loại C, CodeQL loại D, QUIC

## 01/02 – 28/02/2027: thực nghiệm đầy đủ

- [ ] Chạy đủ ma trận thực nghiệm, ba lần mỗi cấu hình (xem [checklist thực nghiệm](checklist_thuc_nghiem.md))
- [ ] Chạy đường cơ sở B0, B1, B2, B3 và mốc thủ công
- [ ] **G3:** đủ số liệu cho RQ1–RQ5

## 03/2027 – 06/2027: luận văn

- [ ] 03–04/2027: phân tích kết quả, viết luận văn (xem [checklist tài liệu và luận văn](checklist_tai_lieu_luan_van.md))
- [ ] 05/2027: hoàn thiện theo góp ý, nộp luận văn
- [ ] Đầu 06/2027: bảo vệ

# Tiêu chuẩn chất lượng: toàn hệ thống

Tài liệu này trả lời: **hệ thống phải đạt những gì thì mới gọi là "work"**, và đo bằng cách nào. Tiêu chuẩn của từng phần nằm ở
[tiêu chuẩn các agent](tieu_chuan_agent.md) và [tiêu chuẩn các thành phần tất định](tieu_chuan_thanh_phan_tat_dinh.md). Mọi tiêu chuẩn
đều đo được và có cột "Hiện tại" ghi trạng thái thật; chỗ chưa đo ghi "chưa đo", không đoán.

Nguồn: ba mục tiêu cụ thể MT1–MT3 và các yêu cầu nghiệp vụ BR1–BR6 trong [thiết kế chi tiết](../design/thiet_ke_chi_tiet_he_thong.md),
các chỉ số ở [Bảng 8 của thiết kế đánh giá](../evaluation/thiet_ke_danh_gia.md#6-chỉ-số), mục tiêu đăng ký trước
([Bảng 30](../design/thiet_ke_chi_tiet_he_thong.md#mục-tiêu-đăng-ký-trước)) và tiêu chí "work thực tế"
([Bảng 13](../evaluation/danh_gia_kha_thi_thuc_nghiem.md#7-kế-hoạch-kiểm-chứng-thực-tế)).

## Hệ thống "work" nghĩa là gì

Hệ thống work khi **cả năm tầng dưới đây** đạt, theo thứ tự ưu tiên. Tầng thấp hơn không đạt thì kết quả của tầng cao hơn không có
giá trị: một hệ thống nhanh và rẻ nhưng để lọt kết luận sai hay bị mã nguồn thao túng thì không dùng được.

| Tầng | Câu hỏi | Mục tiêu gốc | Đạt khi |
|---|---|---|---|
| A. An toàn | Có khi nào hệ thống sai theo cách nguy hiểm không? | BR1–BR6, rủi ro F1 | Mọi bất biến giữ, 0 ngoại lệ |
| B. Chống đối thủ | Mã nguồn cố tình đánh lừa thì sao? | MT3 | Không đổi nhãn dưới tấn công A1–A6; phát hiện A7 |
| C. Đúng | Nhãn có chính xác không? | MT1 | Đạt ngưỡng tối thiểu trên tập đánh giá thật |
| D. Dùng được | Chạy có ổn định, truy vết được, rẻ không? | MT1, MT2 | Truy vết 100%, tái lập, agent không hỏng hàng loạt, chi phí trong giới hạn |
| E. Tổng quát | Thêm giao thức mới có phải sửa lõi không? | MT2 | 0 dòng lõi đổi khi thêm adapter |

Không đạt ngưỡng vẫn là một kết quả khoa học và được báo cáo trung thực (nguyên tắc N4 của thiết kế đánh giá); điều không được làm
là đổi ngưỡng sau khi thấy kết quả (N1).

## Cách đọc các bảng

- **Tối thiểu** là ngưỡng "work": dưới mức này hệ thống không được coi là dùng được. Lấy từ Bảng 8 và Bảng 13.
- **Mục tiêu** là mức đăng ký trước cho luận văn (Bảng 30). Cao hơn hoặc bằng mức tối thiểu.
- **TK** là con số lấy từ tài liệu thiết kế. **ĐX** là con số do tài liệu này **đề xuất** vì thiết kế chỉ nói "báo cáo" hay chưa nêu; các
  con số ĐX cần thầy chốt.
- **Hiện tại** dùng các giá trị: *Đạt (test)* là có kiểm thử tự động đang pass; *Đạt (mô phỏng)* là đạt trong phép thử đầu-cuối trên SUT giả,
  **không tính là số liệu thực nghiệm**; *Chưa đo*; *Chưa đạt* kèm số quan sát.

> [!WARNING]
> Ba tài liệu thiết kế nêu ngưỡng **không khớp nhau**: Bảng 8 và Bảng 13 đặt COMPLIANT sai ≤ 5% và precision VIOLATION ≥ 80%, còn Bảng 30
> đặt ≤ 2% và ≥ 95%. Tiêu chuẩn này giữ cả hai mức (tối thiểu và mục tiêu) cho đến khi thầy chốt, xem
> [CT-20](../management/theo_doi_cai_thien.md#ct-20--p1--ngưỡng-chất-lượng-chưa-thống-nhất-giữa-các-tài-liệu-thiết-kế).

## Tầng A. An toàn (bất biến: 0 vi phạm)

| Mã | Tiêu chuẩn | Ngưỡng | Đo bằng | Nguồn | Hiện tại |
|---|---|---|---|---|---|
| QS-01 | Không agent nào tự gán nhãn; nhãn chỉ do Verdict engine theo V0–V9, cùng bằng chứng cho cùng nhãn | 0 ngoại lệ | [test_verdict_engine.py](../../backend/tests/test_verdict_engine.py), [test_contracts.py](../../backend/tests/test_contracts.py), import-linter | BR3, F1 | Đạt (test) |
| QS-02 | Chuỗi tự do từ vùng cách ly không tới agent đặc quyền | 0 | [test_policy_ifc.py](../../backend/tests/test_policy_ifc.py); ca A1, A2 với LLM thật | A1, A2, P7 | Đạt (test); chưa thử với LLM thật ([CT-08](../management/theo_doi_cai_thien.md#ct-08--p1--chưa-thử-đối-kháng-với-mô-hình-thật)) |
| QS-03 | Lời gọi công cụ ngoài quyền bị từ chối mặc định | 0 lọt qua | [test_gates.py](../../backend/tests/test_gates.py); ca A3 | A3, P8 | Đạt (test); chưa thử đối kháng thật |
| QS-04 | Bằng chứng bị sửa thì bị phát hiện | 100% | `rfcv verify`, [test_evidence_store.py](../../backend/tests/test_evidence_store.py) | A5 | Đạt (test) |
| QS-05 | Hết ngân sách hoặc lặp thì dừng với nhãn an toàn (UNVERIFIABLE), không kết luận sai | 100% | [test_execution_loop.py](../../backend/tests/test_execution_loop.py) | A6 | Đạt (test). Quan sát thật: Planner hỏng cả 8 vòng do lỗi cấu hình, hệ ra UNVERIFIABLE (V9), không ra nhãn sai |
| QS-06 | Lỗi môi trường (SUT không khởi động, sanity hỏng) không bị tính thành FAIL | 0 | [test_driver_and_coverage.py](../../backend/tests/test_driver_and_coverage.py) | BR6 | Đạt (test) |
| QS-07 | Khoá API không xuất hiện trong trace, bằng chứng hay báo cáo | 0 lần xuất hiện | quét `trace.db`, `evidence.db`, artifacts sau mỗi lần chạy | A4 | Đạt (test) trên lần chạy giả: hash cấu hình, `trace.db`, `evidence.db` không chứa khoá ([test_invariants.py](../../backend/tests/test_invariants.py)); quét tự động sau mỗi lần chạy: fcv run gọi bộ quét ([leak_scan.py](../../backend/src/rfcv/gates/leak_scan.py), [test_leak_scan.py](../../backend/tests/test_leak_scan.py)), ghi `leak_scan.json`, thoát mã 3 nếu có rò rỉ |
| QS-08 | Tính lại nhãn từ Evidence store luôn trùng nhãn đã ghi | 100% | `rfcv verify`, replay ([replay.py](../../backend/src/rfcv/eval/replay.py)) | Bảng 8 "Tái lập" | Đạt (test); chưa với lần chạy thật |

## Tầng B. Chống đối thủ (MT3)

| Mã | Tiêu chuẩn | Tối thiểu | Mục tiêu | Đo bằng | Hiện tại |
|---|---|---|---|---|---|
| QS-10 | Tỉ lệ đổi nhãn dưới tấn công A1–A6 (chỉ thị trong chú thích, trong đầu ra chạy, công cụ ngoài quyền, đọc ngoài phạm vi, giả mạo, cạn tài nguyên) | 0 ca | 0 ca | Kịch bản tấn công A1–A6, so với B1 và B0 | Chưa đo; chưa có kịch bản cụ thể ([CT-08](../management/theo_doi_cai_thien.md#ct-08--p1--chưa-thử-đối-kháng-với-mô-hình-thật)) |
| QS-11 | Phát hiện mã nhận ra kiểm thử và đổi hành vi (A7) | mức 1, 2: 100% | mức 1, 2: 100%; mức 3: báo cáo trung thực | Ba mức tinh vi tăng dần | Đạt trên bộ biến thể tự viết: mức 1 10/10, mức 2 10/10, mức 3 0/5 (báo cáo trung thực); báo nhầm 0/15 ca tổng hợp và 2/1162 hàm wolfSSL thật ([suspicious.py](../../backend/src/rfcv/domains/rfc_protocol/suspicious.py), [test_suspicious.py](../../backend/tests/test_suspicious.py)). Chưa thử với đối thủ thật |

## Tầng C. Đúng (MT1)

Ký hiệu: `G` là nhãn chuẩn, `S` là nhãn hệ thống, `V` là VIOLATION, `C` là COMPLIANT. NEEDS\_REVIEW và UNVERIFIABLE không tính đúng hay
sai trong precision và recall; chúng được báo cáo riêng qua tỉ lệ kết luận được (N4).

| Mã | Tiêu chuẩn | Tối thiểu (TK) | Mục tiêu (TK) | Đo bằng | Hiện tại |
|---|---|---|---|---|---|
| QS-20 | **Tỉ lệ COMPLIANT sai** = #(S=C, G=V) / #(G=V). Quan trọng nhất: chính là lỗi bị bỏ sót nhưng báo an toàn (P6) | 0, tối đa 5% | ≤ 2% trên đột biến | Tập đột biến và lỗi thật | Chưa đo |
| QS-21 | Precision VIOLATION = #(S=V, G=V) / #(S=V) | ≥ 80% | ≥ 95% | như trên | Chưa đo |
| QS-22 | Recall VIOLATION, loại A–C | ≥ 60% | không đăng ký | như trên | Chưa đo |
| QS-23 | Tỉ lệ kết luận được (S ∈ {C, V}), loại A–C: không né bằng UNVERIFIABLE | ≥ 60% | ≥ 60% và cao hơn B2 có ý nghĩa thống kê | như trên, so với B2 | Chưa đo |
| QS-24 | Định vị đúng: khoảng dòng T1 của mục VIOLATION giao với vị trí sửa | ≥ 70% | không đăng ký | so với vị trí sửa hoặc bản vá | Chưa đo |
| QS-25 | Báo cáo trung thực: NEEDS\_REVIEW, UNVERIFIABLE báo riêng theo loại A–D và lý do dừng | luôn | luôn | Report | Nhãn tách riêng đã có; **báo cáo chưa có** (Report chưa nối) |
| QS-26 | Loại D (hành vi nội bộ): chỉ hệ thống đầy đủ kết luận được | báo cáo | cao hơn B1 | thí nghiệm E1 | Chưa đo; loại D chưa chạy được ([CT-10](../management/theo_doi_cai_thien.md#ct-10--p2--static_query-loại-d-chưa-nối)) |

Điều kiện cứng: **nếu QS-20 vượt quá ngưỡng tối thiểu (hơn 5%) thì hệ thống không work**, bất kể các chỉ số khác tốt đến đâu.

## Tầng D. Dùng được

| Mã | Tiêu chuẩn | Ngưỡng | Đo bằng | Hiện tại |
|---|---|---|---|---|
| QS-30 | Truy vết đầy đủ: câu RFC → yêu cầu → bằng chứng → nhãn; mỗi T1 mở lại được tại commit, mỗi T3 có đủ thông tin chạy lại (TK) | 100% mục | thí nghiệm E2 | Chưa đo; chuỗi từ câu RFC chưa có ([CT-05](../management/theo_doi_cai_thien.md#ct-05--p1--agent-không-thấy-câu-rfc)) |
| QS-31 | Tái lập nhãn qua 3 lần chạy: tỉ lệ mục cùng nhãn, kappa Fleiss | Báo cáo (TK); κ ≥ 0,8 (ĐX) | `scripts/analyze_run.py` nhiều lần chạy | Chưa đo ([CT-16](../management/theo_doi_cai_thien.md#ct-16--p1--chưa-có-số-đo-thống-kê)) |
| QS-32 | Mọi lần chạy có bản kê đủ: RFC, commit, adapter, image, mô hình, lời nhắc, skill, quy tắc (N5) | 100% | `manifest.json` | Cơ chế đạt (test); chưa đủ trường commit và digest image khi chạy thật |
| QS-33 | Agent hoàn thành nhiệm vụ ngay lần chạy đầu: tỉ lệ lần chạy worker hỏng lần đầu | ≤ 5% (ĐX) | `scripts/analyze_run.py`: `worker_first_failures` / `worker_runs` | **Chưa đạt: 3/7 (43%)** trong phép thử mô phỏng ([CT-01](../management/theo_doi_cai_thien.md#ct-01--p1--test-và-agent-khác-nạp-lại-skill-đã-nạp-rồi-hỏng), [CT-02](../management/theo_doi_cai_thien.md#ct-02--p1--hạn-mức-llm_calls-của-code-reader-quá-chặt)) |
| QS-34 | Token lãng phí trong các lần chạy hỏng | ≤ 10% tổng token (ĐX) | `analyze_run.py`: `wasted_share` | **Chưa đạt: 53% (ca lỗi), 6% (ca đúng)** trong mô phỏng |
| QS-35 | Chi phí mỗi yêu cầu: token, USD, thời gian, lời gọi công cụ (trung vị, tứ phân vị) | Báo cáo; tham chiếu RFCAudit 5,03 USD và 81 phút mỗi giao thức (TK) | Trace log | Mô phỏng: khoảng 210–250 nghìn token và 26–30 giây mỗi yêu cầu; chưa quy ra USD, chưa đại diện |
| QS-36 | Công người mỗi yêu cầu | ≤ 20% so với thủ công (Bảng 30) | mốc thủ công 20 yêu cầu | Chưa đo |
| QS-37 | Hệ thống tự phát hiện và ghi lại thất bại của chính nó: mọi lần agent hỏng có hội thoại và lý do trong trace | 100% | `rfcv trace`, sự kiện `llm_failure` | Đạt (test) |

## Tầng E. Tổng quát (MT2)

| Mã | Tiêu chuẩn | Ngưỡng | Đo bằng | Hiện tại |
|---|---|---|---|---|
| QS-40 | Thêm giao thức mới không sửa lõi: số dòng đổi trong `core/`, `gates/`, `agents/`, quy tắc | 0 | `git diff --stat` trước và sau khi thêm adapter | Đạt với miền giả ([test_generality.py](../../backend/tests/test_generality.py)); DNS chưa làm |
| QS-41 | Hoạt động đúng trên giao thức thứ hai thật | Báo cáo so với TLS | chỉ số tầng C trên tập nhỏ | Chưa đo ([CT-09](../management/theo_doi_cai_thien.md#ct-09--p0--chưa-có-backend-kiểm-thử-thật-và-bộ-chạy-sut-thật)) |
| QS-42 | Kích thước và công sức của một adapter: số tệp, số dòng khai báo, số mẫu, tuần công | Báo cáo | thống kê adapter | Chưa đo |

## Dùng tài liệu này thế nào

1. Muốn biết hệ thống đã work chưa: đọc cột "Hiện tại" từ tầng A xuống tầng E, dừng ở tầng đầu tiên chưa đạt.
2. Đổi prompt, skill, cấu hình, mô hình hay ngân sách: chạy lại phép đo ([sổ theo dõi](../management/theo_doi_cai_thien.md#cách-đo)) rồi cập nhật "Hiện tại".
3. Một tiêu chuẩn đổi trạng thái thì sửa cùng lúc [checklist thực nghiệm](../deliverables/checklist_thuc_nghiem.md) nếu nó là sản phẩm bàn giao.
4. Thêm tiêu chuẩn mới: đặt mã theo tầng, ghi nguồn, ghi cách đo; không có cách đo thì chưa phải tiêu chuẩn.

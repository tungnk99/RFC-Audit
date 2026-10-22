# Tiêu chuẩn chất lượng: các agent

Với mỗi agent: **phải làm được gì** (năng lực, kiểm được bằng có/không) và **phải đạt gì** (chỉ số, có ngưỡng và cách đo). Tiêu chuẩn
toàn hệ thống ở [tieu_chuan_he_thong.md](tieu_chuan_he_thong.md); các thành phần không dùng LLM ở
[tieu_chuan_thanh_phan_tat_dinh.md](tieu_chuan_thanh_phan_tat_dinh.md). Ngữ cảnh mỗi agent được thấy theo Bảng 11 của
[thiết kế phối hợp agent](../design/thiet_ke_phoi_hop_agent.md).

Cách đọc cột: **TK** là ngưỡng lấy từ thiết kế, **ĐX** là ngưỡng do tài liệu này đề xuất (cần thầy chốt). "Hiện tại" ghi trạng thái thật;
số "mô phỏng" lấy từ phép thử đầu-cuối trên SUT và mã giả ([e2e_live.py](../../scripts/e2e_live.py)) và **không phải số liệu thực nghiệm**.
Quan sát gồm hai ca (một ca bản lỗi, một ca bản đúng), mỗi ca một lần chạy.

## Tiêu chuẩn chung cho mọi agent

| Mã | Tiêu chuẩn | Ngưỡng | Đo bằng | Hiện tại |
|---|---|---|---|---|
| AG-01 | Đầu ra đúng schema của vai trò | 100% (ép bằng schema đóng) | schema, sự kiện `output_retry`, `role_failure` | Đạt (test) |
| AG-02 | Chỉ dùng công cụ và đọc trường ngữ cảnh đã khai báo; vùng cách ly và đặc quyền tách bạch | 0 vi phạm | [test_policy_ifc.py](../../tests/test_policy_ifc.py), `PolicyStore` | Đạt (test) |
| AG-03 | Không làm theo chỉ thị nằm trong dữ liệu không tin cậy (mã, chú thích, nhật ký) | 0 ca | kịch bản tấn công A1, A2 | Chưa thử với LLM thật ([CT-08](../management/theo_doi_cai_thien.md#ct-08--p1--chưa-thử-đối-kháng-với-mô-hình-thật)) |
| AG-04 | Hoàn thành ngay lần chạy đầu, không hỏng vì lỗi của chính agent | ≥ 95% lần chạy (ĐX) | `analyze_run.py`: `worker_first_failures` | **Chưa đạt: 3/7 lần chạy worker hỏng lần đầu** (mô phỏng) |
| AG-05 | Trong ngân sách của vai trò (`budget_per_task` trong `role.yaml`): không `UsageLimitExceeded` | ≥ 95% (ĐX) | sự kiện `llm_failure` | **Chưa đạt:** Code Reader hết hạn mức 1/3 lần ([CT-02](../management/theo_doi_cai_thien.md#ct-02--p1--hạn-mức-llm_calls-của-code-reader-quá-chặt)) |
| AG-06 | Nạp mỗi skill tối đa một lần, rồi làm theo | `skill_reloads` = 0 | `analyze_run.py` | **Chưa đạt:** 4 và 3 lần nạp lại mỗi ca ([CT-01](../management/theo_doi_cai_thien.md#ct-01--p1--test-và-agent-khác-nạp-lại-skill-đã-nạp-rồi-hỏng)) |
| AG-07 | Tái lập: nhiệt độ 0, hash lời nhắc và hồ sơ vai trò ghi trong bản kê | 100% | `manifest.json` | Đạt (cơ chế) |

## Verifier (agent phản biện)

**Vai trò trong hệ thống:** Verifier là **lớp chặn cuối** trước kết luận COMPLIANT, kết luận dễ sai nhất (rủi ro F1, pain point P6).
Nhãn do Verdict engine quyết; Verifier chỉ tìm chỗ thiếu hoặc mâu thuẫn mà quy tắc tất định không nhìn thấy, để Planner giao thêm việc.
Nó nằm vùng đặc quyền, không đọc mã, không thấy chuỗi tự do từ vùng cách ly.

> [!IMPORTANT]
> Để hệ thống work, Verifier **bắt buộc**: (1) không bao giờ trả `issues` rỗng khi nhãn tạm là COMPLIANT mà thiếu bằng chứng mã
> (T1) hay còn khía cạnh `UNCLEAR` hay còn mâu thuẫn T1–T3; (2) chỉ dùng mã `kind` và `suggested_task` có trong danh mục; (3) không gán
> nhãn, không giao việc trực tiếp, không bịa `evidence_id`. Phạm lỗi (1) là để lọt COMPLIANT sai, vi phạm tiêu chuẩn
> [QS-20](tieu_chuan_he_thong.md#tầng-c-đúng-mt1).

**Phải làm được**

| # | Năng lực | Kiểm bằng |
|---|---|---|
| 1 | Nhận bản tóm tắt T1/T2/T3, báo cáo độ đủ và câu RFC, trả `Critique@1` | Schema chặt ép `kind` và `suggested_task` thuộc danh mục |
| 2 | Nêu `CONTRADICTION` khi T3 và T1 nói khác nhau (ví dụ T3 thấy `record_overflow`, T1 ghi mã gửi `decode_error`), đề xuất `RECHECK` | `scripts/verifier_smoke.py` ca B |
| 3 | Nêu `MISSING_EVIDENCE` khi thiếu T1 hoặc thiếu khía cạnh theo loại yêu cầu, đề xuất `LOCATE` hoặc `STATIC_QUERY` | `verifier_smoke.py` ca A |
| 4 | Nêu `MISSING_VARIANT` khi còn thiếu biến thể T3 bắt buộc, đề xuất `SELECT_TESTS` | ca B (thiếu `max:65535`) |
| 5 | Nêu `MISSING_PATH` khi T1 có `unexplored` khác rỗng hoặc yêu cầu nói "mọi" mà mới phủ một đường, đề xuất `TRACE_PATHS` | chưa có ca thử |
| 6 | Nêu `WRONG_LOCATION` khi vị trí rõ ràng thuộc sai tầng giao thức (cần bản đồ thành phần) | chưa có ca thử |
| 7 | Bỏ qua mục adapter không làm được (`feasible: false`) | chưa có ca thử |
| 8 | Trả `issues: []` chỉ khi mọi phép kiểm đều qua | `verifier_smoke.py` (cần thêm ca sạch) |

**Phải đạt**

| Mã | Tiêu chuẩn | Ngưỡng | Đo bằng | Hiện tại |
|---|---|---|---|---|
| VF-1 | Đầu ra `Critique@1` hợp lệ | 100% | schema, [test_coordination_contracts.py](../../tests/test_coordination_contracts.py) | Đạt (test) |
| VF-2 | **Phát hiện vấn đề thật** (recall) trên bộ ca gieo sẵn, theo từng loại `kind` | ≥ 90% mỗi loại có dấu hiệu tất định: CONTRADICTION, MISSING\_VARIANT, MISSING\_EVIDENCE, MISSING\_PATH (ĐX); WRONG\_LOCATION: báo cáo | mở rộng `verifier_smoke.py` thành bộ ca | Chưa đo. Mô phỏng: 2/2 ca nêu đúng loại và đề xuất đúng |
| VF-3 | **Không nêu vấn đề không có thật** (precision của vấn đề) | ≥ 80% vấn đề nêu là thật (ĐX); hậu quả của vấn đề giả chỉ là tốn ngân sách, không đổi nhãn | như trên | Chưa đo. Mô phỏng: 3/3 vấn đề đúng |
| VF-4 | Không để lọt COMPLIANT sai | Tỉ lệ COMPLIANT sai của hệ ≤ ngưỡng QS-20; đóng góp của Verifier đo bằng B4 (bỏ `CRITIQUE`) | thí nghiệm B4 | Chưa đo |
| VF-5 | Hiệu quả: tỉ lệ `Critique` dẫn tới bằng chứng mới làm đổi nhãn tạm hoặc giải quyết mâu thuẫn | Báo cáo (TK); ≥ 50% (ĐX) | `critique_result` kết hợp `task_result` | Chưa đo |
| VF-6 | Không vượt quyền: không gán nhãn, không giao việc, không đọc mã, không bịa `evidence_id` | 0 | trace và schema | Cấu trúc đạt (test); kiểm tự động `evidence_id` không bịa **chưa có** |
| VF-7 | Chi phí mỗi lần chạy | trong `budget_per_task` (4 lượt gọi, 80k token); ≤ 15k token (ĐX) | `role_run` | Ca thử nhỏ: 4,3–4,8k token. Trong luồng đầu-cuối: **55k** vì `evidence.summary` phình ([CT-03](../management/theo_doi_cai_thien.md#ct-03--p2--evidencesummary-phình-theo-số-bằng-chứng-t3)) |
| VF-8 | Ổn định: cùng đầu vào cho cùng tập `kind` qua 3 lần chạy | ≥ 90% (ĐX) | chạy lặp | Chưa đo |
| VF-9 | Nạp skill phản biện và làm theo thứ tự năm phép kiểm | `skill_reloads` = 0 | `analyze_run.py` | Đạt trong ca thử nhỏ (nạp `critique-evidence-consistency`); hiệu quả của skill chưa đo ([CT-06](../management/theo_doi_cai_thien.md#ct-06--p2--chưa-biết-skill-có-giúp-ích-không)) |

## Planner

**Vai trò:** quyết định giao việc gì cho ai ở vòng tiếp theo; không gán nhãn, không thấy mã, không có công cụ ngoài đọc trạng thái.

**Phải làm được**

1. Đọc báo cáo độ đủ (`missing`, `conflicts`, `feasible`), `Critique` gần nhất, lịch sử nhiệm vụ và ngân sách, rồi chọn tối đa 2 nhiệm vụ từ danh mục hoặc dừng.
2. Vòng 1: giao song song các nhiệm vụ độc lập theo loại yêu cầu (sổ tay, Bảng 10); ví dụ loại B giao `SELECT_TESTS` và `LOCATE` cùng lúc.
3. Gọi `CRITIQUE` trước khi chốt COMPLIANT và khi có mâu thuẫn.
4. Làm theo vấn đề Verifier nêu: `RECHECK`, `TRACE_PATHS`, `SELECT_TESTS`, `LOCATE`.
5. Không lặp nhiệm vụ khi chưa có bằng chứng mới; chỉ dừng `INFEASIBLE` khi mọi mục còn thiếu đều `feasible = false`.
6. Đi chệch sổ tay thì khai `DEVIATE_PLAYBOOK`.

**Phải đạt**

| Mã | Tiêu chuẩn | Ngưỡng | Đo bằng | Hiện tại |
|---|---|---|---|---|
| PL-1 | `PlanAction` hợp lệ | 100% | schema dựng chặt từ danh mục | Đạt (test); mô phỏng: 5/5 |
| PL-2 | Nhiệm vụ ngoài danh mục hoặc sai đích | 0 (`task_rejected`, trừ khoảng trống đã biết) | trace | Mô phỏng: 0 |
| PL-3 | Dừng sớm khi còn việc làm được | 0 (`stop_rejected`) | trace | Mô phỏng: 0 |
| PL-4 | Số vòng trung vị theo loại yêu cầu | Báo cáo (TK); loại B ≤ 3 vòng (ĐX) | `round_start` | Mô phỏng: 2 và 3 vòng |
| PL-5 | Tỉ lệ yêu cầu dừng do LOOP hoặc BUDGET | Báo cáo (TK); ≤ 10% (ĐX) | sự kiện `stop` | Chưa đo (một lần dừng BUDGET là do lỗi cấu hình mô hình, đã sửa) |
| PL-6 | Bám sổ tay: `followed`, hoặc chệch có khai báo | `deviated_unannounced` = 0 (ĐX) | sự kiện `plan_context` | Mô phỏng: 4 `followed`, 1 `deviated_unannounced` (có thể do chỉ số quá khắt khe, [CT-04](../management/theo_doi_cai_thien.md#ct-04--p3--chỉ-số-bám-sổ-tay-khắt-khe-với-kế-hoạch-là-tập-cha)) |
| PL-7 | Planner LLM không kém Planner cố định (B3) về nhãn đúng và số vòng | không kém | thí nghiệm B3 | Chưa đo |

## Code Reader

**Vai trò:** agent duy nhất đọc mã, nằm trong **vùng cách ly**; trả `LocationClaim` có cấu trúc. Không biết nhãn tạm, không biết kết quả T3, để T1 độc lập với T3.

**Phải làm được**

1. Tự định vị đoạn mã thực hiện yêu cầu bằng bộ công cụ đọc mã và chiến lược sáu bước (định hướng, tìm điểm vào, đọc, lần theo, kết luận, tự kiểm tra).
2. Đối chiếu từng khía cạnh được giao (CONDITION, THRESHOLD, REACTION, ORDER\_STATE, EFFECT) thành MATCH, MISMATCH hoặc UNCLEAR kèm khoảng dòng dẫn chứng.
3. **Tính ngưỡng thành số** từ macro và hằng (ví dụ `16384 + 256 = 16640`), không đoán từ tên hằng.
4. Lần từ mã lỗi nội bộ tới cảnh báo thực sự gửi đi, và kiểm có đóng kết nối không (khía cạnh REACTION).
5. `TRACE_PATHS`: liệt kê mọi lối vào tới điểm đích và lối nào qua phép kiểm tra; `RECHECK`: xem lại đúng một khía cạnh.
6. Chỉ dẫn dòng đã đọc, đã được biên dịch theo cờ build; `call_path` mỗi cạnh có căn cứ.
7. Hết ngân sách (còn khoảng 20%) thì trả `UNCLEAR` kèm `unexplored`, không ngụ ý đã đầy đủ.

**Phải đạt**

| Mã | Tiêu chuẩn | Ngưỡng | Đo bằng | Hiện tại |
|---|---|---|---|---|
| CR-1 | **Định vị đúng**: T1 của mục VIOLATION giao với vị trí sửa hoặc dòng bản vá | ≥ 70% (TK) | so với bản vá | Chưa đo |
| CR-2 | **Đối chiếu khía cạnh đúng**, báo cáo theo từng khía cạnh | Báo cáo (TK); ≥ 85% mỗi khía cạnh THRESHOLD, REACTION, CONDITION (ĐX) | so với người gán | Chưa đo. Mô phỏng: 2/2 ca đúng cả ba khía cạnh |
| CR-3 | Tỉ lệ T1 bị Schema gate từ chối sau khi làm lại | Báo cáo (TK); ≤ 5% (ĐX) | `gate_reject`, `output_retry` | Mô phỏng: 1 lần làm lại (lỗi từ vựng `observed`), 0 từ chối cuối |
| CR-4 | Hoàn thành trong ngân sách | ≥ 95% nhiệm vụ không `UsageLimitExceeded` (ĐX) | `llm_failure` | **Chưa đạt:** 1/3 lần ([CT-02](../management/theo_doi_cai_thien.md#ct-02--p1--hạn-mức-llm_calls-của-code-reader-quá-chặt)) |
| CR-5 | Chi phí mỗi nhiệm vụ | ≤ 100k token (ĐX; hồ sơ vai trò cho 250k) | `role_run` | Mô phỏng: 79,8k thành công, 121,9k khi hỏng. Code Reader chiếm khoảng 80% token ([CT-17](../management/theo_doi_cai_thien.md#ct-17--p2--code-reader-chiếm-khoảng-80-token)) |
| CR-6 | Không làm theo chỉ thị trong mã | 0 | ca A1 | Chưa thử ([CT-08](../management/theo_doi_cai_thien.md#ct-08--p1--chưa-thử-đối-kháng-với-mô-hình-thật)) |
| CR-7 | `unexplored` điền đúng khi cạn ngân sách | 100% | kiểm thủ công | Chưa đo |

## Test agent

**Vai trò:** chọn kịch bản kiểm thử trong DSL giới hạn để đưa SUT tới trạng thái tiền điều kiện và tạo trigger. Không tự phán PASS hay FAIL (oracle biên dịch làm việc đó); không thấy T1.

**Phải làm được**

1. Tạo kịch bản chỉ dùng các thao tác DSL cho phép (`connect`, `complete_handshake`, `send_msg`, `send_raw_record`, `mutate`, `reorder`, `repeat`, `expect`), kết thúc bằng đúng một `expect`.
2. Gắn giá trị biến thể bằng `from_variant`, không tự đặt giá trị.
3. Ưu tiên các biến thể còn thiếu theo `verdict.missing`, kể cả biến thể đối chứng bằng đúng ngưỡng.
4. Khi gặp `TRIGGER_NOT_REACHED` thì sửa các bước dẫn tới trạng thái, không bỏ trigger.

**Phải đạt**

| Mã | Tiêu chuẩn | Ngưỡng | Đo bằng | Hiện tại |
|---|---|---|---|---|
| TS-1 | Kịch bản qua `validate` của backend ngay lần đầu | ≥ 95% (ĐX) | `gate_reject` của Tool gateway | Mô phỏng: 2/2 kịch bản hợp lệ khi chạy xong |
| TS-2 | Tỉ lệ T3 là ERROR vì chưa tới trigger | Báo cáo (TK); ≤ 10% (ĐX) | `t3_case` với `reason = trigger_not_reached` | Mô phỏng: 0 |
| TS-3 | Phủ đủ biến thể bắt buộc | 100% sau tối đa 2 lần giao (ĐX) | `verdict.missing` | Mô phỏng: đủ ngay lần giao thành công |
| TS-4 | Không thấy T1 hay nhãn tạm | 0 trường | [test_coordination_contracts.py](../../tests/test_coordination_contracts.py) | Đạt (test) |
| TS-5 | Hoàn thành ngay lần chạy đầu | ≥ 95% (ĐX) | `analyze_run.py` | **Chưa đạt: hỏng lần đầu ở cả hai ca** (vòng nạp skill, [CT-01](../management/theo_doi_cai_thien.md#ct-01--p1--test-và-agent-khác-nạp-lại-skill-đã-nạp-rồi-hỏng)) |

## Code Indexer

**Vai trò:** lập bản đồ hàm → thành phần cho một vùng mã (vùng cách ly), để Verifier phát hiện `WRONG_LOCATION`.

| Mã | Phải làm được / phải đạt | Ngưỡng | Đo bằng | Hiện tại |
|---|---|---|---|---|
| CI-1 | Chỉ gán thành phần trong danh mục `component_taxonomy` của adapter | 100% (ép bằng cổng) | `ComponentMapHandler` | Có handler; chưa kiểm với LLM thật |
| CI-2 | Ký hiệu không có trong chỉ mục không được ghi | 0 | cổng đối chiếu chỉ mục | Có handler; chưa kiểm với LLM thật |
| CI-3 | Độ chính xác gán thành phần | ≥ 90% (ĐX) | mẫu 30 hàm do người gán | Chưa đo ([CT-18](../management/theo_doi_cai_thien.md#ct-18--p3--map_components-đã-có-handler-nhưng-chưa-thử-với-llm-thật)) |
| CI-4 | Giúp Verifier phát hiện `WRONG_LOCATION` | Báo cáo recall | ca vị trí sai gieo sẵn | Chưa đo |

## RFC Analyst

**Vai trò (chưa nối):** dịch câu RFC thành đặc tả hành vi (RBS) bằng **hai luồng dùng hai họ mô hình khác nhau** để lỗi ít tương quan; bất đồng chuyển người duyệt.

| Mã | Phải làm được / phải đạt | Ngưỡng | Đo bằng | Hiện tại |
|---|---|---|---|---|
| RA-1 | Phân loại A–D đúng | Báo cáo (TK); ≥ 90% (ĐX) | hai người gán, kappa Cohen | Chưa nối |
| RA-2 | Hành vi mong đợi (`trigger`, `expect`, `forbid`) đúng | Báo cáo (TK) | hai người gán | Chưa nối |
| RA-3 | Hai luồng lệch nhau thì không tự quyết, chuyển người duyệt | 100% | reconcile ([reconcile.py](../../src/rfcv/domains/rfc_protocol/spec/reconcile.py)) | Có mã reconcile; chưa chạy với LLM thật |
| RA-4 | Công người duyệt mỗi yêu cầu | ≤ 20% so với thủ công (Bảng 30) | mốc thủ công | Chưa đo |
| RA-5 | Yêu cầu ngoài ngữ pháp RBS thì vào UNVERIFIABLE và được báo cáo, không bịa | 100% | thống kê | Chưa nối |
| RA-6 | Hai luồng thực sự khác họ mô hình | Có | [models.yaml](../../config/models.yaml) | **Chưa đạt:** hiện cùng một mô hình ([CT-07](../management/theo_doi_cai_thien.md#ct-07--p2--một-mô-hình-cho-mọi-agent)) |

## Report

**Vai trò (chưa nối):** viết giải thích kết luận từ bản ghi đã có; không có quyền đổi nhãn.

| Mã | Phải làm được / phải đạt | Ngưỡng | Đo bằng | Hiện tại |
|---|---|---|---|---|
| RP-1 | Mọi `evidence_id` trích dẫn có trong Evidence store | 100% (ép bằng Output gate) | Output gate | Chưa nối ([CT-11](../management/theo_doi_cai_thien.md#ct-11--p3--report-chưa-nối)) |
| RP-2 | Không đổi nhãn | 0 | so nhãn trước và sau | Chưa nối |
| RP-3 | Mỗi VIOLATION nêu T3 liên quan và vị trí T1 | 100% | kiểm tự động | Chưa nối |
| RP-4 | NEEDS\_REVIEW và UNVERIFIABLE kèm lý do dừng, báo cáo riêng (BR5, N4) | 100% | kiểm tự động | Chưa nối |

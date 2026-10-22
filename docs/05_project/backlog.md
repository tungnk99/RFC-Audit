# Backlog công việc

Danh sách việc cần làm để hệ thống đạt các [yêu cầu đầu ra](../03_quality/output_requirements.md) (`YD-nn`) và sửa các vấn đề đang mở trong
[sổ theo dõi](improvement_log.md) (`CT-nn`). Mỗi việc (`BL-nn`) trỏ về yêu cầu nó phục vụ và có tiêu chí "Xong khi" lấy từ chính
yêu cầu đó, nên làm xong việc là đo được yêu cầu đã đạt. Test [test_backlog.py](../../backend/tests/test_backlog.py) bảo đảm **mọi `YD` và mọi
`CT` đang mở đều có ít nhất một việc**.

Mối quan hệ giữa các tài liệu quản lý: yêu cầu (`YD`, `QS`, `AG`) nói **cần đạt gì**; sổ theo dõi (`CT`) nói **đang vướng gì**; backlog (`BL`) nói
**làm việc gì để gỡ**; [checklist deliverable](../05_project/README.md) nói **đã giao chưa**.

## Cách dùng

- **Cỡ** là ước lượng của tài liệu này (ĐX), không phải của thiết kế: **S** ≤ 1 ngày, **M** 2–3 ngày, **L** khoảng 1 tuần, **XL** từ 2 tuần trở lên. Tổng công sức theo
  tầng của thiết kế (19 tuần công cho tầng 1) nằm ở [Bảng 26](../02_design/system_design.md#51-phạm-vi-và-công-sức) và vẫn là căn cứ chính.
- **Giai đoạn** bám lịch của [Bảng 27](../02_design/system_design.md#52-tiến-độ-và-mốc-kiểm-tra):

  | Mã | Thời gian | Nội dung chính |
  |---|---|---|
  | Ngay | từ nay đến đầu 11/2026 | việc không cần hạ tầng thật: sửa độ tin cậy agent, test thiếu, dựng SUT, chốt phạm vi |
  | G1 | 01–30/11/2026 | lõi chạy trên bản triển khai thật, ca K3 trọn luồng, lát cắt dọc |
  | G2 | 01–20/12/2026 | bảy agent nối đủ, hai luồng RBS, ca K1–K3 |
  | DNS | 21/12/2026 – 31/01/2027 | adapter DNS, bộ dữ liệu, kịch bản tấn công |
  | G3 | 01–28/02/2027 | thực nghiệm đầy đủ, đường cơ sở, phân tích |
  | LV | 03–06/2027 | viết luận văn, nộp, bảo vệ |
  | T2 | có điều kiện | tầng 2 và 3, chỉ làm khi G2 đạt trước 15/12 |

- **Trạng thái:** `Chưa làm`, `Đang làm`, `Chặn` (ghi lý do ở cột "Xong khi" hoặc sổ theo dõi), `Xong`. Giữ tối đa **2 việc `Đang làm`** cùng lúc.
- **Một việc `Xong`** khi tiêu chí "Xong khi" đạt **và có bằng chứng** (lệnh đã chạy, kết quả). Sau đó cập nhật cùng lúc: trạng thái ở đây, vấn đề `CT` tương ứng,
  cột "Hiện tại" của tiêu chuẩn, và checklist nếu là sản phẩm bàn giao.

## Đường găng

```
BL-03 dựng SUT ──► BL-02 bộ chạy SUT ──► BL-01 backend kiểm thử ──► BL-04 chạy rfcv trên wolfSSL thật ──► BL-08 lát cắt dọc ──► G1
        │                                                                  │
        └────────► BL-05 độ phủ thật ──────────────────────────────────────┘
song song:  Nhóm EP-2 (độ tin cậy agent) · BL-20/21 (câu RFC vào ngữ cảnh) · BL-25 (chốt phạm vi cùng thầy) · BL-61 (test thiếu)
```

Không có hạ tầng chạy thật (EP-1) thì các việc đo độ chính xác (BL-08, BL-72, BL-73) không bắt đầu được. Vì vậy EP-1 là **P0**; nhóm EP-2 làm được ngay và nên làm trước vì nó
quyết định số đo của mọi lần chạy sau.

## EP-1. Nền tảng chạy trên bản triển khai thật (P0)

| ID | Việc cần làm | Đáp ứng | Phụ thuộc | Cỡ | Giai đoạn | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|---|
| BL-03 | Dựng ba SUT TLS (wolfSSL và hai bản khác), mỗi SUT hai bản (thường và đo độ phủ), image có digest ghi vào bản kê. Có sẵn bản sao mã nguồn trong `eval/work/` | YD-13, CT-09 | Docker | L | Ngay | Ba SUT dựng được; kho nào quá 3 ngày chưa dựng được thì thay ứng viên | Chưa làm |
| BL-02 | Cài `DockerSutLauncher`: SUT mới mỗi ca, mạng nội bộ riêng, huỷ ngay sau ca, đa dạng môi trường (tên máy, địa chỉ, đồng hồ) | YD-13, YD-33, CT-09 | BL-03 | L | G1 | `start()` chạy wolfSSL từ image theo digest; một ca sanity qua launcher thật | Chưa làm |
| BL-01 | Cài `TlsfuzzerBackend.run()` và `sanity()`: dịch kịch bản trừu tượng sang hội thoại tlsfuzzer, chuẩn hoá quan sát (cảnh báo, đóng kết nối, sự kiện) | YD-21, CT-09 | BL-02 | L | G1 | Chạy lại ví dụ ca K3 bằng một lệnh; bản lỗi ra T3 FAIL ổn định | Chưa làm |
| BL-05 | Dựng dữ liệu độ phủ thật (lcov) từ bản đo độ phủ và nối Coverage linker | YD-20, CL-3, CT-09 | BL-03, BL-01 | M | G1 | T3 liên kết T1 (quy tắc V5) trên SUT thật | Chưa làm |
| BL-04 | Đăng ký bộ chạy SUT và backend vào builtin để `rfcv run --adapter adapters/tls13` chạy thật | YD-32, YD-33, CT-09 | BL-01, BL-02, BL-05 | M | G1 | `rfcv run` ra nhãn cho TLS13-0042 trên wolfSSL thật; bản gốc và bản đột biến đúng nhãn (cổng G1) | Chưa làm |
| BL-06 | Adapter TLS 1.3: bọc 5 lỗi loại B sau 7/2026 thành mẫu, `known_bugs.yaml` đủ 5 lỗi (hiện 1), mở rộng danh mục mẫu theo các mục RFC trong phạm vi, báo cáo độ phủ mẫu | YD-21, YD-22 | BL-01 | L | G1 | Adapter checker đạt: mỗi mẫu FAIL trên ít nhất một bản lỗi, `at_limit` PASS trên bản tham chiếu; có báo cáo số yêu cầu có mẫu hợp lệ | Chưa làm |
| BL-07 | Chạy các kiểm tra của Adapter checker cần sandbox: dựng SUT, oracle ổn định (3 lần), oracle phân biệt được, độ phủ biểu đạt được | AC-2, AC-3, AC-4 | BL-01, BL-02 | M | G1 | Bốn kiểm tra chuyển từ "bỏ qua" sang chạy và đạt | Chưa làm |
| BL-08 | Lát cắt dọc: chạy trọn luồng với agent LLM thật cho TLS13-0042 và 5 lỗi loại B; đo độ chính xác Code Reader theo khía cạnh và chi phí | YD-20, YD-21, CR-1, CR-2, CT-24 | BL-04, BL-06 | M | G1 | Có bảng số đo đầu tiên trên mã thật, ghi vào Nhật ký đo của sổ theo dõi | Chưa làm |

## EP-2. Độ tin cậy và chi phí của agent (làm ngay)

| ID | Việc cần làm | Đáp ứng | Phụ thuộc | Cỡ | Giai đoạn | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|---|
| BL-10 | Chặn vòng lặp nạp skill: thêm vào prompt "nạp mỗi skill một lần, rồi làm theo"; nếu chưa đủ thì nhúng thẳng skill ngắn vào prompt | CT-01, AG-04, AG-06 | – | S | Ngay | `skill_reloads` = 0 và `worker_first_failures` = 0 trên cả hai ca, mỗi ca ít nhất 3 lần | Xong |
| BL-11 | Bỏ giới hạn `llm_calls` của mọi agent (quyết định 2026-10-22, thay cho nâng lên 20) và đo lại; token, công cụ và thời gian vẫn bị chặn | CT-02, AG-05, CR-4 | – | S | Ngay | Không còn `UsageLimitExceeded` qua 3 lần mỗi ca (đạt: Nhật ký đo #6, 3+3 lần, 0 lần hỏng). Token mỗi ca đã tăng gấp ~3 so với #4 do viết lại prompt và skill ở #5, theo dõi ở CT-25 và BL-14, không tính vào việc này | Xong |
| BL-12 | Rút gọn `evidence.summary`: gộp T3 theo biến thể và kết quả, giữ chi tiết cho ca FAIL, mâu thuẫn, ca được trích | CT-03, VF-7 | – | M | Ngay | Token đầu vào của Verifier giảm so với mốc 55k; `verifier_smoke` vẫn nêu đúng hai tình huống | Xong |
| BL-13 | Sửa chỉ số bám sổ tay: kế hoạch chứa đủ nhiệm vụ được gợi ý tính là `followed` | CT-04, PL-6 | – | S | Ngay | Có test; ca bản lỗi không còn bị ghi `deviated_unannounced` | Xong |
| BL-14 | Giảm chi phí Code Reader: rút gọn đầu ra công cụ đọc mã, dừng sớm khi các khía cạnh đã đủ | CT-17, CT-25, CR-5 | BL-10, BL-11, BL-08 | M | G1 | Token Code Reader mỗi ca giảm có số đo mà độ chính xác T1 không đổi | Chưa làm |
| BL-15 | Thử `MAP_COMPONENTS` với LLM thật; quyết định quy tắc vòng 1 của sổ tay và skill Verifier cho `WRONG_LOCATION` | CT-18, CI-3, CI-4 | – | S | G2 | Có số đo gán thành phần trên 30 hàm; sổ tay và skill được cập nhật theo kết quả | Xong |
| BL-16 | Thêm một mô hình họ khác vào `models` và gán cho Verifier và `rfc_analyst.b` | CT-07, RA-6 | – | S | G2 | Verifier chạy bằng mô hình khác họ; có số đo so với dùng chung | Chặn |

## EP-3. Bao phủ RFC và RFC Analyst

| ID | Việc cần làm | Đáp ứng | Phụ thuộc | Cỡ | Giai đoạn | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|---|
| BL-25 | Chốt phạm vi hỗ trợ RFC cùng thầy: bảng giao thức nhân mức hỗ trợ (đầy đủ, mức chứng minh, chưa hỗ trợ) và các điểm cần xác nhận ở yêu cầu đầu ra | YD-14, CT-22 | thầy | S | Ngay | Bảng phạm vi được chốt và ghi vào báo cáo | Chưa làm |
| BL-20 | Cấp câu RFC (`rfc.sentence`, `rfc.paragraph`, `rfc.context_pack`) vào ngữ cảnh agent, lấy theo trường nguồn của RBS qua RFC gate | YD-01, CT-05 | – | M | G1 | `KNOWN_UNSUPPLIED` không còn các trường `rfc.*` đã cấp; Verifier thấy câu RFC | Xong |
| BL-21 | Đo RFC gate trên toàn văn RFC 8446: số câu tách được so với đếm độc lập, ranh giới câu đúng trên 30 câu | YD-01 | – | S | G1 | Có bảng số đo; sai lệch được giải thích hoặc sửa | Xong |
| BL-26 | Ghi phiên bản RFC, errata và hash vào mọi kết luận; xử lý RFC 8446 và RFC 9846 theo quyết định của thầy | YD-05, CT-23 | BL-25 | S | G1 | 100% kết luận ghi phiên bản RFC và hash | Chưa làm |
| BL-23 | Nối RFC Analyst: hai luồng dùng hai họ mô hình khác nhau, so khớp, phân loại A–D, bất đồng chuyển người duyệt | YD-03, YD-04, CT-12, RA-1, RA-3, RA-5 | BL-16, BL-20 | L | G2 | Phân loại A–D đúng ≥ 90% (ĐX) trên 30 mục hai người gán; câu hai luồng lệch không tự quyết (100%) | Chưa làm |
| BL-24 | Trạng thái cuối cho **mọi** câu quy phạm (cả "ngoài phạm vi" và "thiếu adapter") kèm lý do | YD-02, YD-04, YD-11, YD-42 | BL-23, BL-30 | M | G2 | Tổng theo trạng thái bằng tổng câu tách được; mỗi câu ngoài ngữ pháp hay thiếu adapter có lý do | Chưa làm |
| BL-22 | Bộ phân tích RFC bản TXT (DNS, SSH), hoặc chọn RFC có bản XML | YD-12, CT-22 | BL-25 | M | DNS | Tách câu đúng ranh giới trên 30 câu mỗi giao thức | Xong |

## EP-4. Phát hiện triển khai sai RFC, không bỏ sót im lặng

| ID | Việc cần làm | Đáp ứng | Phụ thuộc | Cỡ | Giai đoạn | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|---|
| BL-46 | Viết test riêng cho nhánh SUT sập sau khi nhận dữ liệu kích hoạt (`sut_crashed`) | YD-27 | – | S | G1 | Test pass; ca sập có cờ và là FAIL | Xong |
| BL-41 | Skill và prompt cho khía cạnh REACTION (lần từ mã lỗi nội bộ tới cảnh báo, kiểm có đóng kết nối) và cho tìm điểm vào, mẫu tìm theo cấu trúc | YD-22, CR-2 | BL-10 | S | G1 | Đo recall khía cạnh REACTION trước và sau, có cải thiện hoặc ghi rõ không đổi | Chưa làm |
| BL-40 | Bộ quét nhánh nghi vấn (T2 `suspicious_branch`): so sánh với hằng khớp giá trị thử, đọc biến môi trường hay tên máy, trên đường xử lý của yêu cầu | YD-25, CG-6, QS-11 | – | L | G2 | Phát hiện kịch bản A7 mức 1 và 2: 100%; mức 3 được báo cáo trung thực | Xong |
| BL-44 | Đo `TRACE_PATHS`: ca nhiều đường xử lý, kiểm `unexplored` điền đúng khi cạn ngân sách | YD-24, CR-7 | BL-04 | M | G2 | 100% T1 có `unexplored` đúng; tỉ lệ yêu cầu loại "mọi" đủ đường được báo cáo | Chưa làm |
| BL-45 | Bộ ca "hợp lệ nhưng làm khác" (cách làm thay thế RFC cho phép) để kiểm báo sai | YD-26, QS-21 | BL-04, BL-70 | M | DNS | Precision VIOLATION đo được; không ca hợp lệ nào bị báo VIOLATION | Chưa làm |
| BL-42 | Nối `STATIC_QUERY` cho loại D: bộ chạy truy vấn tĩnh đã kiểm định đột biến (CodeQL hoặc Semgrep) | YD-23, CT-10, CG-5 | BL-03 | L | T2 | Một yêu cầu loại D ra nhãn quyết định qua quy tắc V8 | Chưa làm |
| BL-43 | Học máy trạng thái cho loại C (quy tắc V3), skill ORDER\_STATE và mẫu kịch bản loại C | YD-22, CT-12 | BL-01 | L | T2 | Một yêu cầu loại C ra nhãn quyết định; khía cạnh ORDER\_STATE được đo | Chưa làm |

## EP-5. Báo cáo và đầu ra cho người dùng

| ID | Việc cần làm | Đáp ứng | Phụ thuộc | Cỡ | Giai đoạn | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|---|
| BL-30 | Nối Report agent và Output gate: giải thích chỉ trích bằng chứng có thật, nhãn không đổi | YD-40, CT-11, RP-1, RP-2, RP-3, RP-4 | BL-04 | M | G2 | 100% `evidence_id` trích có trong kho; 0 thay đổi nhãn; mỗi VIOLATION nêu T3 và vị trí T1 | Chưa làm |
| BL-31 | Lệnh `rfcv report --format html\|json\|sarif` (Jinja2, nối [sarif.py](../../backend/src/rfcv/ui/sarif.py)) với bản tổng hợp độ phủ: số yêu cầu theo nhãn và assurance, tách MUST, SHOULD, MAY, loại D, UNVERIFIABLE theo lý do | YD-31, YD-42 | BL-30 | L | G2 | Báo cáo sinh ra có đủ các phần; SARIF hợp lệ theo schema; tổng các nhóm bằng tổng số yêu cầu | Chưa làm |
| BL-33 | Lệnh `rfcv specs`: duyệt RBS bất đồng và mẫu 10% | YD-03, RA-4 | BL-23 | M | G2 | Người duyệt chấp nhận, sửa hoặc loại được; công người đo được | Chưa làm |
| BL-32 | Lệnh `rfcv review`: bảng duyệt NEEDS\_REVIEW (quy tắc gây nhãn, bằng chứng đặt cạnh nhau, nhân chứng, mã dạng văn bản không tin cậy), bản ghi Review riêng | YD-41 | BL-31 | M | DNS | 100% mục NEEDS\_REVIEW có đủ các phần; nhãn máy không bị sửa | Chưa làm |
| BL-34 | Lệnh `rfcv status`: tiến độ theo trạng thái và chi phí đã dùng | YD-60 | BL-04 | S | DNS | Hiển thị tiến độ và token, USD của một lần chạy | Chưa làm |
| BL-35 | Kịch bản tái lập một lệnh cho mỗi VIOLATION; người ngoài chạy lại mẫu 20 bản ghi T3 (E2) | YD-40 | BL-31 | M | G3 | ≥ 90% mẫu tái lập được (ĐX) | Chưa làm |

## EP-6. Vòng đời phát triển (tầng 3 theo Bảng 26)

| ID | Việc cần làm | Đáp ứng | Phụ thuộc | Cỡ | Giai đoạn | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|---|
| BL-50 | Lệnh `rfcv rerun`: kiểm chứng lại gia tăng bằng hash hàm; giữ bằng chứng còn hiệu lực, chạy lại mọi T3, chỉ điều tra lại yêu cầu bị ảnh hưởng. Nếu thầy coi là bắt buộc thì đưa lên giai đoạn DNS | YD-30 | BL-04 | L | T2 | Chi phí kiểm chứng lại ≤ 30% lần đầu (ĐX); nhãn khớp lần chạy toàn bộ trên mẫu | Chưa làm |
| BL-51 | Chế độ CI cho pull request và nạp SARIF vào GitHub code scanning | YD-31 | BL-31, BL-50 | M | T2 | Một pull request mẫu chạy được và kết quả hiện trên code scanning | Chưa làm |

## EP-7. An toàn trước đối thủ và kiểm soát dữ liệu

| ID | Việc cần làm | Đáp ứng | Phụ thuộc | Cỡ | Giai đoạn | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|---|
| BL-61 | Viết test cho sáu bất biến chưa có kiểm thử riêng: vòng làm lại của Schema gate, không lộ chi tiết chính sách khi từ chối, ngân sách thời gian, skill có symlink, quét khoá API, phát hiện `evidence_id` bịa | CT-21, YD-52, QS-07 | – | M | Ngay | Sáu test pass; tiêu chuẩn tương ứng chuyển sang "Đạt (test)" | Xong |
| BL-62 | Quét trace, bằng chứng và artifacts: không chứa khoá API, không chứa nội dung tệp ngoài `code_scope` | YD-51, QS-07, LG-1 | BL-61 | S | G1 | Quét tự động sau mỗi lần chạy cho kết quả 0 | Xong |
| BL-60 | Kịch bản tấn công A1–A7 (chú thích độc, nhật ký độc, công cụ ngoài quyền, đọc tệp khoá, giả mạo bằng chứng, cạn tài nguyên, mã nhận ra kiểm thử ba mức) và chạy với LLM thật, so với B1 | YD-50, CT-08, QS-10 | BL-04 | L | DNS | Đổi nhãn dưới A1–A6: 0 ca; không chuỗi độc trong ngữ cảnh Planner và Verifier | Chưa làm |
| BL-63 | Thử mô hình cục bộ (endpoint tương thích OpenAI, ví dụ vLLM) cho mã không được gửi ra ngoài | YD-51 | – | M | T2 | Một lần chạy đầu-cuối bằng mô hình cục bộ; ghi chất lượng so với mô hình ngoài | Chưa làm |

## EP-8. Dữ liệu, đường cơ sở và thực nghiệm

| ID | Việc cần làm | Đáp ứng | Phụ thuộc | Cỡ | Giai đoạn | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|---|
| BL-75 | Cùng thầy chốt **một bộ ngưỡng** chất lượng thống nhất giữa Bảng 8, 13, 30 và đăng ký trước | CT-20, QS-20, QS-21 | thầy | S | Ngay | Ba tài liệu cùng một bộ ngưỡng hoặc hai mức được định nghĩa rõ | Chưa làm |
| BL-74 | So sánh có và không có skill (`enable_skills`), thêm ca khó (nhiều macro, `#ifdef`, `unexplored` khác rỗng) | CT-06, SK-3 | BL-04 | M | G2 | Bảng A/B mỗi bên ít nhất 3 lần; quyết định giữ, sửa hay bỏ từng skill | Chưa làm |
| BL-70 | Bộ dữ liệu đột biến tự động: khoảng 150 đột biến TLS và 50 DNS, mỗi đột biến vi phạm đúng một yêu cầu | YD-21 | BL-03 | L | DNS | Bộ đột biến sinh được; mỗi đột biến được xác nhận vi phạm đúng một yêu cầu | Chưa làm |
| BL-71 | Lỗi thật: gán nhãn các commit ứng viên (cột `type`, `keep`, `requirement`) và hai người gán nhãn độc lập khoảng 30 mục, đo kappa | YD-21 | – | L | DNS | Tập đánh giá chính chốt; kappa Cohen được báo cáo | Chưa làm |
| BL-72 | Đường cơ sở B0 (RFCAudit), B1, B2, B3 và mốc thủ công 20 yêu cầu TLS 1.3 | YD-43 | BL-04 | XL | G3 | Mỗi đường cơ sở chạy trên cùng tập; mốc công người có thời gian | Chưa làm |
| BL-73 | Bộ chạy ma trận thực nghiệm, mỗi cấu hình ba lần, với thống kê Wilson, McNemar, kappa Fleiss | YD-20, YD-21, YD-60, CT-16, QS-31 | BL-70, BL-71, BL-72 | L | G3 | Bảng chỉ số tầng C đầy đủ kèm khoảng tin cậy; tái lập nhãn qua ba lần chạy | Chưa làm |
| BL-76 | Quy chi phí ra USD theo bảng giá lúc chạy; so với mốc RFCAudit (5,03 USD, 81 phút mỗi giao thức) | YD-60 | BL-73 | S | G3 | Bảng chi phí mỗi yêu cầu, loại và giao thức | Chưa làm |

## EP-9. DNS và tính tổng quát

| ID | Việc cần làm | Đáp ứng | Phụ thuộc | Cỡ | Giai đoạn | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|---|
| BL-80 | Backend DNS (dnspython và genreport) | YD-10, YD-13 | BL-04 | L | DNS | Backend chạy một ca DNS và chuẩn hoá quan sát | Chưa làm |
| BL-81 | Adapter DNS và ba bản triển khai (CoreDNS, Knot, thêm một bản tham chiếu); cần BL-22 cho RFC bản TXT | YD-10, YD-13 | BL-80, BL-22 | L | DNS | Adapter checker đạt; 15–20 yêu cầu DNS chạy được | Chưa làm |
| BL-83 | Gói khai báo cho DNS, HTTP/2, QUIC, SSH theo tài liệu adapter (Bảng 10): adapter (từ vựng, miền giá trị, gợi ý Locator, phạm vi mã, công thức SUT), RBS ví dụ trỏ câu RFC có thật, mẫu kiểm thử, skill giao thức, backend phần kiểm kịch bản; lõi miền bỏ chỗ gắn TLS | YD-10, YD-13 | – | L | Ngay | `rfcv adapter check` đạt phần hình thức cho bốn adapter; skill lõi không nhắc giao thức nào | Xong |
| BL-82 | Đo số dòng đổi trong lõi khi thêm DNS | YD-10, QS-40 | BL-81 | S | DNS | `git diff --stat` các thư mục lõi, agent, quy tắc bằng 0. Đo 2026-10-22: đợt đầu (DNS, HTTP/2, QUIC, SSH cùng lúc) phải sửa 18 dòng lõi, 34 dòng agent, khoảng 150 dòng miền để gỡ chỗ gắn TLS (R-13), chưa bằng 0; giao thức tổng hợp tiếp theo bằng 0, có test | Xong |
| BL-97 | Skill đọc mã cho Rust hoặc Go khi có adapter ngôn ngữ đó | YD-13, CT-13 | BL-81 | M | T2 | Skill tương đương skill C có số đo, hoặc ghi vào hạn chế | Chưa làm |

## EP-10. Hoàn thiện, tài liệu và luận văn

| ID | Việc cần làm | Đáp ứng | Phụ thuộc | Cỡ | Giai đoạn | Xong khi | Trạng thái |
|---|---|---|---|---|---|---|---|
| BL-90 | CI xanh: sửa 16 lỗi `pyright`, 2 lỗi `ruff`, định dạng khoảng 10 file | CT-14 | – | M | Ngay | `pyright`, `ruff check`, `ruff format --check`, `lint-imports`, `pytest` đều sạch | Xong |
| BL-92 | Quyết định CLI có tự nạp `.env` hay chỉ ghi rõ trong README | CT-15 | – | S | Ngay | Quyết định được ghi; `rfcv models` không còn báo sai khoá | Xong |
| BL-91 | Xử lý các chỗ tên chưa thống nhất: gói `agents` và `src/rfcv/agents`, `eval/scripts`, tên file test | CT-19 | – | M | G1 | Từng mục được sửa hoặc ghi lý do giữ nguyên; `pytest` và kiểm liên kết sạch | Xong |
| BL-93 | Cập nhật tài liệu thiết kế cho khớp mã sau khi dựng xong phần chạy thật (ví dụ `R0–R7` và `V0–V9`) | – | BL-04 | M | G3 | Không còn chỗ lệch đã biết giữa thiết kế và mã | Chưa làm |
| BL-95 | Gói tái lập cho lần chạy chính thức, hướng dẫn tái lập từng bước, gắn thẻ git cho phiên bản nộp | – | BL-73 | M | LV | Người ngoài chạy lại được từ commit tới bảng kết quả | Chưa làm |
| BL-94 | Viết luận văn (các chương, RQ1–RQ5, hạn chế, tham khảo), slide, bản demo; nộp 05/2027; bảo vệ đầu 06/2027 | – | BL-73 | XL | LV | Luận văn nộp; bảo vệ xong | Chưa làm |
| BL-96 | Tầng 2 và 3 còn lại: QUIC, HTTP/2, SSH, trợ lý viết adapter | – | G2 đạt sớm | XL | T2 | Chỉ làm khi G2 đạt trước 15/12; mỗi giao thức có số giờ công adapter | Chưa làm |

## Yêu cầu đầu ra đã đạt, không cần việc thêm

Các yêu cầu sau đã đạt ở mức hiện có; chỉ cần giữ đạt khi sửa code (test và `rfcv trace` đang bảo vệ):

- `YD-44` xem lại được vì sao hệ thống dừng và kết luận (`rfcv trace`, `rfcv verify`).
- `YD-52` thất bại an toàn: mọi lỗi dẫn tới UNVERIFIABLE hoặc NEEDS\_REVIEW kèm lý do.
- `YD-61` một yêu cầu hết ngân sách thì dừng độc lập.

## Bảng truy vết: yêu cầu đầu ra tới việc

| Yêu cầu | Việc |
|---|---|
| YD-01 | BL-20, BL-21 |
| YD-02 | BL-24 |
| YD-03 | BL-23, BL-33 |
| YD-04 | BL-23, BL-24 |
| YD-05 | BL-26 |
| YD-10 | BL-80, BL-81, BL-82, BL-83 |
| YD-11 | BL-24 |
| YD-12 | BL-22 |
| YD-13 | BL-02, BL-03, BL-80, BL-81, BL-83, BL-97 |
| YD-14 | BL-25 |
| YD-20 | BL-05, BL-08, BL-73 |
| YD-21 | BL-01, BL-06, BL-08, BL-70, BL-71, BL-73 |
| YD-22 | BL-06, BL-41, BL-43 |
| YD-23 | BL-42 |
| YD-24 | BL-44 |
| YD-25 | BL-40 |
| YD-26 | BL-45 |
| YD-27 | BL-46 |
| YD-30 | BL-50 |
| YD-31 | BL-31, BL-51 |
| YD-32 | BL-04 |
| YD-33 | BL-02, BL-04 |
| YD-40 | BL-30, BL-35 |
| YD-41 | BL-32 |
| YD-42 | BL-24, BL-31 |
| YD-43 | BL-72 |
| YD-50 | BL-60 |
| YD-51 | BL-62, BL-63 |
| YD-60 | BL-34, BL-73, BL-76 |

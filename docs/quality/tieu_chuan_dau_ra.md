# Yêu cầu đầu ra: hệ thống phải giải quyết được gì khi dùng thực tế

"Đầu ra" ở đây không phải định dạng báo cáo mà là **năng lực**: khi một nhóm phát triển hay một người kiểm chứng đem hệ thống vào việc thật,
nó phải giải quyết được những tình huống nào. Mỗi yêu cầu có mã `YD-nn` (yêu cầu đầu ra), mức đạt đo được và trạng thái hiện tại. Tiêu chuẩn
kỹ thuật chi tiết của từng thành phần nằm ở [toàn hệ thống](tieu_chuan_he_thong.md), [các agent](tieu_chuan_agent.md) và
[các thành phần tất định](tieu_chuan_thanh_phan_tat_dinh.md); trang này nhìn từ phía **người dùng**.

Nguồn: các điểm đau P1–P8 và mục tiêu MT1–MT3 trong [thiết kế chi tiết](../design/thiet_ke_chi_tiet_he_thong.md), các quy tắc nghiệp vụ BR1–BR6,
[thiết kế nguồn RFC](../design/thiet_ke_cung_cap_rfc.md) và [thiết kế đánh giá](../evaluation/thiet_ke_danh_gia.md). Cách đọc ký hiệu **TK** (con số lấy từ
thiết kế) và **ĐX** (con số do tài liệu này đề xuất, cần thầy chốt) giống các tài liệu tiêu chuẩn khác.

Việc cụ thể để đạt từng yêu cầu nằm ở [backlog công việc](../management/theo_doi_backlog.md), có bảng truy vết từ `YD-nn` tới `BL-nn`.

## Hai yêu cầu cốt lõi, hiểu cho đúng

Hai mong muốn của người dùng là: **hỗ trợ mọi RFC cần lọc** và **không bỏ sót bất kỳ đoạn mã nào triển khai sai RFC**. Cả hai đều chính đáng,
nhưng **không thể bảo đảm theo nghĩa đen** với bất kỳ công cụ kiểm thử nào, nên tài liệu này viết chúng thành các cam kết đo được.

> [!IMPORTANT]
> **"Không bỏ sót" được hiểu là "không bỏ sót một cách im lặng".** Hệ thống không hứa tìm ra mọi lỗi, vì kiểm thử hộp đen có trần phát hiện
> (lỗi chỉ lộ ở một cửa sổ giá trị hẹp, hay mã cố nhận ra bộ kiểm thử, là những trường hợp khó nhất). Hệ thống cam kết ba điều thay vào đó:
> (1) **mọi yêu cầu trong phạm vi đều có một trạng thái cuối**, không yêu cầu nào biến mất; (2) **COMPLIANT chỉ được cấp khi đủ bằng chứng tối thiểu** của loại yêu cầu (nhiều biến thể phía vi phạm, nhân chứng,
> liên kết độ phủ với vị trí mã, một lần phản biện sạch); thiếu thì là UNVERIFIABLE hay NEEDS\_REVIEW. Lỗi vẫn lọt qua mọi lớp đó là có thể,
> nên **tỉ lệ COMPLIANT sai được đo và bị chặn trên** (≤ 5% tối thiểu, ≤ 2% mục tiêu), không hứa bằng 0 tuyệt đối; (3) **phần chưa xét được luôn được liệt kê** (đường xử lý chưa xét, yêu cầu ngoài ngữ pháp,
> yêu cầu thiếu adapter), kèm lý do. Khả năng bắt lỗi thật được **đo và công bố** (recall), không tuyên bố tuyệt đối.
>
> **"Hỗ trợ mọi RFC" được hiểu là "mọi RFC thêm được bằng adapter, không sửa lõi".** Mỗi giao thức cần một adapter (từ vựng, mẫu kiểm thử, cách dựng SUT).
> RFC chưa có adapter vẫn được tách yêu cầu và báo cáo rõ "chưa kiểm chứng được vì thiếu adapter", chứ không bị bỏ qua hay bịa nhãn. Phạm vi cam kết trong luận
> văn là TLS 1.3 làm sâu và DNS; QUIC, HTTP/2, SSH làm theo thứ tự nếu còn thời gian (Bảng 26 của thiết kế).

## A. Bao phủ RFC: không câu quy phạm nào biến mất

| Mã | Hệ thống phải giải quyết được | Mức đạt và cách đo | Hiện tại |
|---|---|---|---|
| YD-01 | Tách **mọi câu quy phạm** BCP 14 (MUST, MUST NOT, SHOULD, MAY…) của một RFC trong phạm vi, mỗi câu có định danh ổn định truy về mục và câu gốc (ví dụ `RFC8446§5.2#p3s2`) | Số câu tách được bằng số đếm độc lập; ranh giới câu đúng trên 30 câu mỗi giao thức (TK, E3) | RFC gate đã cài ([rfc_gate.py](../../backend/src/rfcv/domains/rfc_protocol/rfc_gate.py), 4 test); **chưa đo trên toàn văn RFC thật** |
| YD-02 | Mỗi câu quy phạm kết thúc ở **đúng một trạng thái**: một trong bốn nhãn, hoặc "ngoài phạm vi" kèm lý do. Không câu nào bị bỏ lặng lẽ | Tổng theo trạng thái bằng tổng câu tách được (100%) | Nhãn có; trạng thái "ngoài phạm vi" và bảng tổng hợp **chưa có** (Report chưa nối) |
| YD-03 | Phân loại A–D và MUST, SHOULD, MAY cho mọi yêu cầu; báo cáo tách riêng (BR5) | Độ chính xác phân loại ≥ 90% (ĐX), hai người gán, kappa | RFC Analyst chưa nối |
| YD-04 | Câu **không biểu diễn được** bằng RBS không bị bỏ qua: thành UNVERIFIABLE có lý do và được thống kê | 100% câu ngoài ngữ pháp có lý do; tỉ lệ ngoài ngữ pháp được báo cáo (ĐX: ≤ 20% trong phạm vi TLS 1.3) | Chưa đo |
| YD-05 | Kết luận ghi đúng phiên bản RFC và errata (BR4); xử lý RFC bị thay thế (RFC 8446 và RFC 9846) | 100% kết luận ghi phiên bản RFC và hash | Thiết kế có; chưa có báo cáo; lựa chọn 8446 hay 9846 đang chờ thầy xác nhận |

## B. Mở rộng giao thức và bản triển khai

| Mã | Hệ thống phải giải quyết được | Mức đạt và cách đo | Hiện tại |
|---|---|---|---|
| YD-10 | Thêm giao thức hay RFC mới **chỉ bằng adapter**, không sửa lõi (MT2) | 0 dòng đổi trong lõi (`git diff --stat`); công sức adapter (tuần công) được báo cáo (TK) | Đạt với miền giả ([test_generality.py](../../backend/tests/test_generality.py)); DNS chưa làm |
| YD-11 | RFC **chưa có adapter**: vẫn tách yêu cầu và báo cáo từng yêu cầu là "chưa kiểm chứng được: thiếu adapter"; không bịa nhãn | 100% yêu cầu có trạng thái này | Chưa có (cần Report và trạng thái ở YD-02) |
| YD-12 | **RFC cũ chỉ có bản TXT** (ví dụ DNS, SSH) đọc được | Tách câu đúng như YD-01 | **Chưa**: RFC gate mới đọc RFCXML v3, "bản TXT chưa cài" |
| YD-13 | Nhiều bản triển khai và nhiều ngôn ngữ (C, Rust, Go) cho cùng một giao thức; mỗi giao thức ít nhất 3 bản (TK) | Số bản triển khai chạy được; chỉ số tầng C trên từng bản | Chưa chạy bản thật nào |
| YD-14 | Nêu rõ giao thức nào "hỗ trợ đầy đủ", "mức chứng minh", "chưa hỗ trợ" | Một bảng phạm vi công bố cùng báo cáo | Mới có TLS 1.3 với một mẫu kiểm thử ([CT-22](../management/theo_doi_cai_thien.md#ct-22--p1--phạm-vi-hỗ-trợ-rfc-chưa-chốt)) |

## C. Phát hiện triển khai sai RFC, không bỏ sót

| Mã | Hệ thống phải giải quyết được | Mức đạt và cách đo | Hiện tại |
|---|---|---|---|
| YD-20 | **COMPLIANT chỉ được cấp khi đủ bằng chứng tối thiểu** của loại yêu cầu (BR1); thiếu thì là UNVERIFIABLE hoặc NEEDS\_REVIEW. Lỗi vẫn lọt qua mọi lớp là có thể, nên tỉ lệ này phải **bị chặn trên** | Tỉ lệ COMPLIANT sai ≤ 5% tối thiểu, ≤ 2% mục tiêu ([QS-20](tieu_chuan_he_thong.md#tầng-c-đúng-mt1)) | Chưa đo. Cơ chế có: COMPLIANT đòi đủ biến thể, liên kết độ phủ và một lần phản biện sạch |
| YD-21 | Mọi yêu cầu loại A–C mà bản triển khai vi phạm theo cách **quan sát được qua giao thức** đều bị phát hiện | Recall VIOLATION ≥ 60% trên lỗi thật loại A–C (TK); ≥ 90% trên đột biến tự tạo, vì nhãn đúng biết chắc (ĐX) | Chưa đo |
| YD-22 | Phát hiện lỗi dù **kiểm tra đúng nhưng phản ứng sai** (ví dụ kiểm độ dài đúng ngưỡng nhưng gửi sai cảnh báo): đối chiếu theo năm khía cạnh CONDITION, THRESHOLD, REACTION, ORDER\_STATE, EFFECT | Recall theo từng khía cạnh | THRESHOLD, REACTION, CONDITION đúng 2/2 ca trong mô phỏng; ORDER\_STATE và EFFECT chưa chạy được |
| YD-23 | **Hành vi nội bộ không thấy được từ ngoài** (loại D, ví dụ xoá bí mật cũ) được kiểm bằng phân tích tĩnh kết hợp vị trí mã; cái không kiểm được báo cáo là UNVERIFIABLE | Chỉ cấu hình đầy đủ kết luận được loại D (giả thuyết H3 của thiết kế đánh giá) | **Chưa** (`STATIC_QUERY` chưa nối, [CT-10](../management/theo_doi_cai_thien.md#ct-10--p2--static_query-loại-d-chưa-nối)) |
| YD-24 | Xét **mọi đường xử lý** tới điểm kiểm tra ("mọi bản ghi nhận vào"); đường chưa xét được liệt kê, không ngụ ý đầy đủ | 100% T1 điền đúng `unexplored` khi cạn ngân sách; tỉ lệ yêu cầu loại "mọi" đủ đường được báo cáo | Cơ chế có (`TRACE_PATHS`, `unexplored`); chưa đo |
| YD-25 | Phát hiện **mã bất thường nhằm đánh lừa kiểm thử**: nhận ra kiểm thử, so sánh với hằng khớp giá trị thử, đọc biến môi trường hay tên máy | Mức 1, 2: 100%; mức 3: báo cáo trung thực (TK, Bảng 30) | **Chưa có bộ quét nhánh nghi vấn**; mô phỏng mới có họ lỗi `a7_canonical` |
| YD-26 | **Không báo sai**: bản triển khai hợp lệ nhưng làm khác (cách làm thay thế RFC cho phép) không bị báo VIOLATION; mọi VIOLATION có nhân chứng dương | Precision VIOLATION ≥ 80% tối thiểu, ≥ 95% mục tiêu | Chưa đo |
| YD-27 | Ghi nhận SUT **sập** khi nhận dữ liệu kích hoạt (có thể là lỗ hổng bảo mật) | 100% ca sập có cờ `sut_crashed` | Đạt (test, [test_driver_and_coverage.py](../../backend/tests/test_driver_and_coverage.py)): ca sập là FAIL, mang cờ `sut_crashed` trong bản ghi T3 và trace |

## D. Dùng trong vòng đời phát triển

| Mã | Hệ thống phải giải quyết được | Mức đạt và cách đo | Hiện tại |
|---|---|---|---|
| YD-30 | Mã đổi (commit mới): **kiểm chứng lại gia tăng**. Giữ bằng chứng còn hiệu lực, chạy lại mọi T3, chỉ điều tra lại yêu cầu bị ảnh hưởng | Chi phí kiểm chứng lại ≤ 30% lần đầu (ĐX); nhãn khớp lần chạy toàn bộ trên mẫu | **Chưa** (`rfcv rerun` chưa cài) |
| YD-31 | Chạy như một bước **CI cho pull request**; kết quả vào GitHub code scanning và IDE qua SARIF 2.1.0 | SARIF hợp lệ theo schema; mỗi VIOLATION có vị trí mã thành một `result` | Có hàm dựng SARIF ([sarif.py](../../backend/src/rfcv/ui/sarif.py)); chưa nối vào lệnh `rfcv report` |
| YD-32 | Kết luận gắn đúng với commit, phiên bản RFC, adapter và quy tắc (BR4); chạy lại cùng đầu vào cho cùng nhãn | Tái lập kết luận 100%; bằng chứng T3 chạy lại cùng kết quả | Cơ chế đạt (test); chưa với lần chạy thật |
| YD-33 | Chạy được bằng Docker trên máy của nhóm phát triển, không cần hạ tầng lớn; một yêu cầu xong trong ngân sách thời gian | ≤ 30 phút mỗi yêu cầu (ngân sách mặc định 1800 giây) | Mô phỏng: 26–30 giây; chưa đo trên SUT thật |

## E. Người dùng nhận đủ thông tin để hành động

| Mã | Hệ thống phải giải quyết được | Mức đạt và cách đo | Hiện tại |
|---|---|---|---|
| YD-40 | Mỗi VIOLATION cho nhà phát triển **sửa được ngay**: câu RFC, yêu cầu, kịch bản tái lập chạy lại bằng một lệnh, kỳ vọng so với quan sát, vị trí mã | Vị trí mã đúng ≥ 70% (TK); người ngoài tái lập được ≥ 90% mẫu 20 bản ghi T3 (ĐX, E2) | Dữ liệu có trong kho bằng chứng; báo cáo chưa có |
| YD-41 | Yêu cầu NEEDS\_REVIEW tới người duyệt **đủ thông tin**: quy tắc gây nhãn, bằng chứng mâu thuẫn đặt cạnh nhau, nhân chứng, đoạn mã (hiển thị là văn bản không tin cậy). Người duyệt ghi lý do; nhãn của máy không bị sửa (BR3) | 100% mục NEEDS\_REVIEW có đủ các phần | **Chưa** (`rfcv review` chưa cài) |
| YD-42 | Mỗi lần chạy có **bản tổng hợp độ phủ minh bạch**: số yêu cầu theo nhãn và mức assurance; tách MUST, SHOULD, MAY; tách loại D; số UNVERIFIABLE theo lý do (ngoài RBS, thiếu mẫu, thiếu adapter, hết ngân sách, không làm được). Đây là cách hệ thống nói rõ "tôi chưa kiểm chứng những gì" | 100% lần chạy có bản tổng hợp; tổng các nhóm bằng tổng số yêu cầu | **Chưa có** (Report chưa nối); dữ liệu nguồn đã có trong trace và kho bằng chứng |
| YD-43 | Giảm công người so với kiểm chứng thủ công | ≤ 20% công thủ công mỗi yêu cầu (TK, Bảng 30) | Chưa đo |
| YD-44 | Xem lại được **vì sao** hệ thống dừng và kết luận | `rfcv trace` và `rfcv verify` cho mọi lần chạy | Đạt (test) |

## F. An toàn khi dùng trên mã của bên thứ ba

| Mã | Hệ thống phải giải quyết được | Mức đạt và cách đo | Hiện tại |
|---|---|---|---|
| YD-50 | Mã không tin cậy (có thể do đối thủ viết) **không thể** đổi nhãn, chạy lệnh, đọc ngoài phạm vi hay lấy khoá | Đổi nhãn dưới A1–A6: 0 ca (TK, Bảng 30) | Đạt ở kiểm thử đơn vị; chưa thử với LLM thật ([CT-08](../management/theo_doi_cai_thien.md#ct-08--p1--chưa-thử-đối-kháng-với-mô-hình-thật)) |
| YD-51 | **Kiểm soát dữ liệu gửi ra ngoài**: chỉ phần mã trong phạm vi `code_scope` tới nhà cung cấp LLM, loại tệp nhạy cảm (`*.pem`, `*.key`); hỗ trợ mô hình cục bộ cho mã không được phép gửi ra ngoài | 0 tệp ngoài phạm vi trong các lời gọi LLM (quét trace) | Phạm vi và loại tệp nhạy cảm được ép ([test_codeindex.py](../../backend/tests/test_codeindex.py)); quét dữ liệu lần chạy tìm nội dung tệp ngoài phạm vi đã có, chạy sau mỗi `rfcv run` khi có `--code-root` ([test_leak_scan.py](../../backend/tests/test_leak_scan.py)); quét lời gọi LLM ở mức nhà cung cấp chưa có; mô hình cục bộ (endpoint tương thích OpenAI) chưa thử |
| YD-52 | **Thất bại an toàn**: mọi lỗi (mô hình, API, SUT, hết ngân sách) dẫn tới UNVERIFIABLE hoặc NEEDS\_REVIEW kèm lý do, không ra nhãn sai và không làm mất kết quả của yêu cầu khác | 100% | Đạt (test); quan sát thật: Planner hỏng cả 8 vòng, hệ ra UNVERIFIABLE |

## G. Quy mô và chi phí thực tế

| Mã | Hệ thống phải giải quyết được | Mức đạt và cách đo | Hiện tại |
|---|---|---|---|
| YD-60 | Một RFC hàng trăm yêu cầu chạy hết trong ngân sách; song song 4–8 yêu cầu; chi phí mỗi yêu cầu được báo cáo, so mốc RFCAudit (5,03 USD, 81 phút mỗi giao thức) | Token, USD, thời gian, lời gọi công cụ mỗi yêu cầu (trung vị, tứ phân vị) | Chưa đo; mô phỏng khoảng 210–250 nghìn token mỗi yêu cầu |
| YD-61 | Một yêu cầu hết ngân sách thì dừng **độc lập**, các yêu cầu còn lại vẫn chạy | 100% | Đạt (test) cho ngân sách theo yêu cầu |

## Những điều hệ thống **không** hứa

- Không hứa tìm ra mọi lỗi. Lỗi nằm ở cửa sổ giá trị hẹp hay chỉ lộ ở trạng thái hiếm có thể lọt qua mẫu kiểm thử và khi đó hệ thống vẫn ra COMPLIANT.
  Điều được cam kết là mức bằng chứng tối thiểu trước khi ra COMPLIANT (YD-20), và phần lỗi vẫn lọt được đo thành tỉ lệ bỏ sót công bố (YD-21).
- Không hứa thắng đối thủ thích nghi hoàn toàn (A7 mức 3): chỉ báo cáo trung thực tỉ lệ phát hiện.
- Không hứa kiểm chứng yêu cầu mơ hồ trong RFC hoặc yêu cầu ngoài ngữ pháp RBS: chúng được tách ra, thống kê và để người quyết.
- Không hứa chạy trên giao thức chưa có adapter: chỉ hứa báo cáo rõ phần chưa kiểm chứng được (YD-11).
- Không hứa nhãn cuối đúng khi bản triển khai, RFC hay adapter khác với bản ghi trong báo cáo (BR4).

## Cần thầy xác nhận

1. **Phạm vi "mọi RFC"** có đúng như cách hiểu ở trên không (mọi RFC thêm được bằng adapter, và phạm vi cam kết là TLS 1.3 và DNS)? Xem [CT-22](../management/theo_doi_cai_thien.md#ct-22--p1--phạm-vi-hỗ-trợ-rfc-chưa-chốt).
2. **Cách hiểu "không bỏ sót"** là "không bỏ sót im lặng, kèm tỉ lệ bỏ sót đo và công bố" có chấp nhận được không, hay cần một ngưỡng recall cụ thể cho từng loại A–D?
3. Các con số **ĐX** trong tài liệu này: recall ≥ 90% trên đột biến, tỉ lệ ngoài ngữ pháp ≤ 20%, chi phí kiểm chứng lại ≤ 30%, tái lập ≥ 90%.
4. Loại C và D có nằm trong cam kết của luận văn không (hiện thuộc tầng 2: học máy trạng thái, CodeQL)? Nếu không, YD-22 (ORDER\_STATE, EFFECT) và YD-23 chuyển thành "báo cáo là hạn chế".
5. Dữ liệu gửi tới nhà cung cấp LLM bên ngoài có được chấp nhận với mã đang kiểm chứng không, hay bắt buộc dùng mô hình cục bộ (YD-51)?

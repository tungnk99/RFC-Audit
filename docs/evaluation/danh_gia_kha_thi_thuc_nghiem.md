# Đánh giá khả thi và thực nghiệm sơ bộ trên lỗi thật của wolfSSL

*Tài liệu thiết kế chi tiết · Phần bổ sung*

Đề tài: Kiểm chứng tự động và an toàn sự tuân thủ đặc tả giao thức mạng dựa trên bằng chứng, sử dụng hệ thống AI đa tác tử · Học viên: Nguyễn Kỳ Tùng · GVHD: TS. Tống Văn Vạn<br> Ngày thực nghiệm: 14/10/2026. Tài liệu đánh giá luồng đã thiết kế ở các tài liệu "Thiết kế chi tiết", "Thiết kế khám phá mã nguồn", "Thiết kế cung cấp RFC" và "Thiết kế phối hợp agent", không mở rộng phạm vi bản đề xuất.

**MỤC LỤC**

- [1. Kết luận](#1-kết-luận)
- [2. Luồng phối hợp](#2-luồng-phối-hợp-để-giải-bài-toán)
  - [2.1 Chia nhỏ bài toán](#21-bài-toán-được-chia-nhỏ-thế-nào)
  - [2.2 Hai kênh giao tiếp](#22-hai-kênh-giao-tiếp)
  - [2.3 Luồng từ đầu đến cuối](#23-luồng-từ-đầu-đến-cuối)
- [3. Lỗi thật làm dữ liệu chuẩn](#3-lỗi-thật-làm-dữ-liệu-chuẩn)
- [4. Thực nghiệm sơ bộ](#4-thực-nghiệm-sơ-bộ)
  - [4.1 Thiết lập](#41-thiết-lập)
  - [4.2 T3 trước handshake](#42-t3-trước-handshake-mẫu-socket-thô)
  - [4.3 T3 sau handshake](#43-t3-sau-handshake-tlsfuzzer)
  - [4.4 T1 và đối chiếu](#44-t1-và-đối-chiếu-với-t3)
  - [4.5 Dòng được biên dịch](#45-xác-định-dòng-thực-sự-được-biên-dịch)
  - [4.6 Áp quy tắc kết luận](#46-áp-quy-tắc-kết-luận)
- [5. Đánh giá khả thi](#5-đánh-giá-khả-thi)
- [6. Điều chỉnh thiết kế](#6-điều-chỉnh-thiết-kế-rút-ra-từ-thực-nghiệm)
- [7. Kế hoạch kiểm chứng thực tế](#7-kế-hoạch-kiểm-chứng-thực-tế)
- [8. Rủi ro còn lại](#8-rủi-ro-còn-lại)
- [9. Tái lập](#9-tái-lập)
- [10. Nguồn](#10-nguồn)

## 1. Kết luận

> [!TIP]
> **Luồng khả thi, đánh giá 9/10.** Thực nghiệm chạy tay trên lỗi thật `c18833f52` của wolfSSL cho thấy ba điều:
>
> - Luồng cho ra đúng kết luận VIOLATION ở phiên bản lỗi.
> - Hai nguồn bằng chứng độc lập (kiểm thử T3 và đọc mã T1) khớp nhau.
> - Luồng phát hiện thêm một ứng viên sai lệch còn tồn tại ở bản mới nhất mà test của nhà phát triển không phủ.
>
> Hai rủi ro kỹ thuật lớn nhất trước đây đã được giải quyết bằng thực nghiệm: kiểm thử sau handshake và xử lý `#ifdef`.

| Câu hỏi | Trả lời | Căn cứ |
| --- | --- | --- |
| Luồng có dừng và ra nhãn trong mọi trường hợp? | Có | Ngân sách, phát hiện lặp; Verdict engine luôn gán nhãn (mục 2) |
| Có lỗi thật đúng loại hệ thống nhắm tới? | Có | 81 commit ứng viên của wolfSSL từ 2025 đến 10/2026, đủ loại A–D (mục 3) |
| T3 có phân biệt được bản lỗi và bản đã sửa? | Có | Bản lỗi hỏng 55/67 ca tlsfuzzer; bản sửa hỏng 1/67 (mục 4.3) |
| T1 có định vị và đọc đúng ngưỡng? | Có (khi người thực hiện đóng vai) | Ngưỡng đọc từ mã (16486) trùng ngưỡng đo bằng T3 (mục 4.4) |
| Agent LLM có tự làm được? | Chưa đo | Đo ở lát cắt dọc cuối tháng 11 (mục 7) |

*Bảng 1. Tóm tắt đánh giá.*

## 2. Luồng phối hợp để giải bài toán

### 2.1. Bài toán được chia nhỏ thế nào

| Tầng | Câu hỏi | Ai đặt ra |
| --- | --- | --- |
| Bài toán | Bản triển khai X tại commit C có tuân thủ RFC R trong phạm vi adapter không? | Người kiểm chứng |
| Bài toán con | Với một yêu cầu, ví dụ TLS13-0042 (loại B, MUST): nhận bản ghi quá dài thì có gửi record\_overflow rồi đóng kết nối không? | RFC Analyst; người kiểm chứng duyệt |
| Câu hỏi cụ thể | Còn thiếu T3 cho biến thể nào? T1 có mâu thuẫn T3 không? | Verdict engine, sau mỗi vòng |

*Bảng 2. Ba tầng của bài toán. Mỗi bài toán con có tiêu chí "giải xong" định sẵn: một trong các quy tắc R0–R6 áp dụng được.*

### 2.2. Hai kênh giao tiếp

Các agent không trò chuyện trực tiếp. Chúng giao tiếp qua hai kênh:

| Kênh | Nội dung | Mục đích |
| --- | --- | --- |
| **Thông điệp qua hub** (Execution loop) | `dispatch` (Planner giao nhiệm vụ có kiểu), `tool_call` (qua Tool gateway), `result` (qua Schema gate), `stop`. Agent chỉ điền `body`; hub gán người gửi, người nhận, vòng, ngân sách | Giao việc và nhận kết quả |
| **Trạng thái dùng chung** | Requirement registry (đề bài), Evidence store (lời giải từng phần T1–T3, chỉ cổng ghi), báo cáo độ đủ của Verdict engine, Critique của Verifier | Chia sẻ hiểu biết; agent đọc bản tóm tắt có cấu trúc |

*Bảng 3. Hai kênh giao tiếp. Cách làm gần với mô hình blackboard: các bên ghi kết quả lên kho dùng chung, Planner điều phối ai làm gì tiếp.*

Không cho agent trò chuyện tự do vì bốn lý do:

- **An toàn:** chuỗi tự do từ vùng cách ly có thể chở chỉ thị độc hại.
- **Kiểm tra được:** mỗi thông điệp có schema.
- **Không trôi:** câu hỏi "đủ chưa" do Verdict engine trả lời một cách tất định.
- **Tái lập được:** cùng bằng chứng thì cho cùng nhãn.

### 2.3. Luồng từ đầu đến cuối

```
GĐ0  Người kiểm chứng: chọn adapter, commit, RFC, cờ build → bản kê lần chạy

GĐ1  Đặt đề bài
     RFC gate ──câu + gói ngữ cảnh──▶ RFC Analyst ──Requirement──▶ Schema gate
       ──▶ Requirement registry ──▶ người kiểm chứng duyệt
     (song song) Code Indexer ──ComponentMap──▶ Schema gate ──▶ Index store

GĐ2  Giải từng bài toán con (vòng lặp theo yêu cầu)
     ┌▶ Planner đọc: yêu cầu + tóm tắt bằng chứng + báo cáo độ đủ + Critique + ngân sách
     │    └─dispatch─▶ hub ─▶ Code Reader / Test / Locator / Verifier
     │                         └─result─▶ cổng ─▶ Evidence store
     │  Verdict engine ─▶ báo cáo độ đủ
     └── chưa đủ và còn ngân sách: vòng mới  |  đủ, Planner dừng hoặc hết ngân sách: thoát

GĐ3  Kết luận
     Verdict engine gán nhãn R0–R7 ─▶ Report Agent ─▶ Output gate ─▶ báo cáo
```

## 3. Lỗi thật làm dữ liệu chuẩn

Lọc lịch sử commit của wolfSSL theo các từ khoá tuân thủ TLS 1.3 (tên cảnh báo, "RFC 8446", "RFC 9846"…), từ 2025 đến 10/2026, thu được **81 commit ứng viên**. Trong đó 57 commit có kèm test, 47 commit từ tháng 7/2026 trở đi. Danh sách đầy đủ ở tệp `wolfssl_commit_ung_vien.csv`; cần lọc tay để bỏ commit thêm tính năng.

| Commit | Nội dung | Loại |
| --- | --- | --- |
| `c18833f52` | Fix to send record\_overflow alert (lỗi dùng trong thực nghiệm) | B |
| `2d36eca90`, `e4007a895` | Từ chối byte thừa trong CertificateRequest, EncryptedExtensions | B |
| `38d95618e`, `eae22ab37` | Gửi đúng illegal\_parameter thay vì cảnh báo khác | B |
| `1ce351469` | Gửi unexpected\_message khi nhận trùng thông điệp handshake | C |
| `789ecb1ff` | RFC 8446 §6.2: không ghi gì sau cảnh báo fatal | C |
| `ba51fbd30` | Xoá khoá traffic TLS 1.3 sau khi đẩy sang phần cứng | D |

*Bảng 4. Một số lỗi thật tiêu biểu. Số commit liên quan năm 2026 (66) cao vượt so với các năm trước (1–6 mỗi năm). Nhiều commit mang mã "F-xxxx", gợi ý có một đợt rà soát hoặc công cụ tự động khác; cần tìm hiểu như công trình liên quan.*

**Mỗi commit sửa lỗi tự cho đáp án:**

- Commit cha là phiên bản lỗi; hệ thống phải ra VIOLATION.
- Commit sửa là phiên bản đúng; hệ thống không được ra VIOLATION cho yêu cầu đó.
- Diff chỉ ra vị trí mã đúng, dùng để chấm T1.
- Test đi kèm là oracle độc lập.

Để tránh việc mô hình đã "học" đáp án từ dữ liệu huấn luyện, tập đánh giá chính lấy các commit sau mốc kiến thức của mô hình.

## 4. Thực nghiệm sơ bộ

### 4.1. Thiết lập

| Mục | Giá trị |
| --- | --- |
| Phiên bản SUT | **bug** `0cecccdf6` (commit cha), **fix** `c18833f52` (26/6/2026), **head** `28bc7540d` (7/10/2026) |
| Cấu hình build | `./configure --enable-tls13 --disable-shared --enable-static`; bản bug và fix thêm `CFLAGS=-DWOLFSSL_TLS13_MIDDLEBOX_COMPAT` để tương thích với tlsfuzzer. Không bật `HAVE_MAX_FRAGMENT` |
| SUT | `examples/server/server -v 4 -d -g -i` (chỉ TLS 1.3, không xác thực client, trả HTTP) |
| Mẫu kiểm thử | (a) mẫu socket thô tự viết, trước handshake; (b) tlsfuzzer `test-tls13-record-layer-limits.py`, sau handshake |
| Vai trò | Build, kiểm thử, oracle chạy thật. Người thực hiện đóng vai RFC Analyst, Planner, Code Reader |

*Bảng 5. Thiết lập thực nghiệm.*

### 4.2. T3 trước handshake (mẫu socket thô)

Mẫu kiểm thử gửi header bản ghi handshake với trường length cho trước. Oracle là PASS nếu nhận được `15 03 03 00 02 02 16` (fatal, record\_overflow); oracle này lấy đúng từ test mà nhà phát triển thêm vào commit sửa.

| length | Ý nghĩa | bug | fix | head |
| --- | --- | --- | --- | --- |
| 16384 | Bằng 2^14, đối chứng hợp lệ | unexpected\_message | unexpected\_message | unexpected\_message |
| 16385 | Vừa vượt 2^14 (giới hạn TLSPlaintext, §5.1) | unexpected\_message | unexpected\_message | **unexpected\_message** |
| 16641 | Vừa vượt 2^14+256 | không cảnh báo | record\_overflow | record\_overflow |
| 65535 | Lớn nhất theo mã hoá | không cảnh báo | record\_overflow | record\_overflow |

*Bảng 6. Kết quả mẫu socket thô. Tìm nhị phân trên bản head: độ dài 16486 được chấp nhận, từ 16487 thì có record\_overflow.*

### 4.3. T3 sau handshake (tlsfuzzer)

Script `test-tls13-record-layer-limits.py` của tlsfuzzer kiểm RFC 8446 §5.1, §5.2 và §5.4 bằng 67 ca. Các ca gồm:

- bản ghi đã mã hoá dài 2^14+256 có fuzz tag;
- Finished có padding;
- app\_data dài 2^14 và 2^14+1;
- ClientHello dài lớn nhất cho phép và quá giới hạn.

Mỗi ca chạy với một tiến trình SUT mới.

| Phiên bản | PASS | FAIL | Các ca hỏng |
| --- | --- | --- | --- |
| bug | 12 | **55** | 50 ca bản ghi đã mã hoá quá dài; 4 ca Finished có padding; 1 ca ClientHello quá lớn |
| fix | 66 | 1 | ClientHello quá lớn (16168 byte padding) |
| head | 66 | 1 | ClientHello quá lớn (16168 byte padding) |

*Bảng 7. Kết quả tlsfuzzer. Kiểm thử phân biệt rõ bản lỗi và bản đã sửa ở đúng kịch bản sau handshake.*

Ca còn hỏng ở bản fix và head: wolfSSL trả ServerHello thay vì record\_overflow cho ClientHello có bản ghi dài hơn 2^14. Ca này xác nhận độc lập kết quả ở Bảng 6.

### 4.4. T1 và đối chiếu với T3

Đóng vai Code Reader trên bản head, chỉ cần hai lệnh tìm kiếm và một lệnh tra hằng là định vị được:

```
src/internal.c, GetRecordHeader (khoảng dòng 13884–13898)
    if (*size > (MAX_RECORD_SIZE + MAX_MSG_EXTRA +
            (ssl->options.usingCompression ? MAX_COMP_EXTRA : 0))) {
        ...
        return LENGTH_ERROR;
    }
wolfssl/internal.h:  MAX_RECORD_SIZE = 16384,  MAX_MSG_EXTRA = 38 + WC_MAX_DIGEST_SIZE  (= 102)
```

Ngưỡng trong mã là 16384 + 102 = **16486**, trùng với ngưỡng đo bằng T3. Ngưỡng này dùng chung cho mọi phiên bản TLS, không theo giới hạn 2^14 của TLSPlaintext trong TLS 1.3.

| Khía cạnh | Giá trị quan sát | Đối chiếu |
| --- | --- | --- |
| CONDITION | Có kiểm tra trường length của bản ghi | MATCH |
| THRESHOLD | 16486, trong khi yêu cầu §5.1 là 16384 | **MISMATCH** |
| REACTION | `send_alert(record_overflow)` khi vượt ngưỡng | MATCH |

*Bảng 8. LocationClaim cho yêu cầu §5.1 trên bản head, theo các khía cạnh ở tài liệu "Thiết kế phối hợp agent".*

### 4.5. Xác định dòng thực sự được biên dịch

Ở bản bug, dòng `SendAlert(ssl, alert_fatal, record_overflow);` có trong mã nhưng nằm trong khối `#ifdef HAVE_MAX_FRAGMENT`. Code Reader đọc mã mà không biết cấu hình build sẽ báo REACTION = MATCH, tức là sai.

**Cách giải đã thử:**

1. Chạy `gcc -E` với đúng cờ build của SUT.
2. Đọc line marker để biết dòng nào của tệp nguồn thực sự xuất hiện sau tiền xử lý.

| Dòng | bug | fix |
| --- | --- | --- |
| `SendAlert(ssl, alert_fatal, record_overflow);` | **không được biên dịch** | được biên dịch |

*Bảng 9. Kết quả xác định dòng được biên dịch.*

### 4.6. Áp quy tắc kết luận

| Yêu cầu | Phiên bản | Bằng chứng | Nhãn |
| --- | --- | --- | --- |
| §5.2: bản ghi đã mã hoá &gt; 2^14+256 → record\_overflow (loại B) | bug | T3 FAIL hợp lệ (tlsfuzzer, socket thô) | **VIOLATION** (R1) |
| như trên | fix, head | T3 PASS mọi biến thể bắt buộc; T1 khớp | COMPLIANT (R2) |
| §5.1: bản ghi chưa mã hoá &gt; 2^14 → record\_overflow (loại B) | head | T3 FAIL ở biến thể vừa vượt ngưỡng; T1 cho THRESHOLD = MISMATCH | **VIOLATION** (R1), ứng viên cần người kiểm chứng xác nhận |

*Bảng 10. Kết luận theo R0–R7. Kết quả ở dòng cuối có thể là lựa chọn tương thích có chủ đích của wolfSSL, nên cần người kiểm chứng xem lại trước khi coi là lỗi.*

## 5. Đánh giá khả thi

| Tiêu chí | Điểm | Căn cứ |
| --- | --- | --- |
| Tính đúng của luồng | 9,5 | Luôn dừng và ra nhãn; nhãn do quy tắc tất định quyết định; trên lỗi thật cho đúng nhãn ở cả ba phiên bản |
| Khả thi của T3 | 9 | Cả mẫu tự viết và tlsfuzzer đều chạy được, trước và sau handshake; dựng môi trường hết khoảng một giờ |
| Khả thi của T1 (agent đọc mã) | 8,5 | Định vị chỉ mất 2–3 lệnh; có tiền lệ RFCAudit, LocAgent; đã có cách xử lý `#ifdef`. Chưa đo với agent LLM thật |
| Giá trị thực tế | 9 | Có sẵn lỗi thật làm dữ liệu chuẩn; tìm ra ứng viên sai lệch mà test của nhà phát triển bỏ sót |
| Khối lượng so với thời gian | 8 | Khoảng 4–5 tháng cho một người với 5 giao thức; TLS làm sâu, các giao thức khác ở mức chứng minh mở rộng |
| **Tổng thể** | **9** |  |

*Bảng 11. Đánh giá khả thi theo tiêu chí.*

## 6. Điều chỉnh thiết kế rút ra từ thực nghiệm

| Điều chỉnh | Nội dung | Thành phần |
| --- | --- | --- |
| Cờ build là đầu vào cố định | Adapter khai báo cờ build của SUT; cờ được ghi vào bản kê lần chạy | Adapter, bản kê |
| Đánh dấu dòng không được biên dịch | Code gate chạy bộ tiền xử lý theo cờ build; công cụ đọc mã đánh dấu dòng không được biên dịch; LocationClaim thêm khía cạnh "dòng được biên dịch"; Schema gate từ chối dẫn chứng là dòng không được biên dịch | Code gate, Code Reader, Schema gate |
| Mỗi ca một tiến trình SUT | Sandbox khởi động SUT mới cho mỗi ca; kiểm tra sẵn sàng mà không mở kết nối thừa | Sandbox & Test driver |
| Dùng tlsfuzzer cho mẫu sau handshake | Bọc từng ca tlsfuzzer thành mẫu của adapter; cố định phiên bản tlsfuzzer và tlslite-ng (lấy từ mã nguồn, không dùng bản PyPI) | Adapter TLS |
| Đối chứng hợp lệ trong biến thể | Mỗi dạng ràng buộc độ dài có thêm biến thể "đúng bằng ngưỡng" để phát hiện mẫu kiểm thử sai | Adapter |

*Bảng 12. Điều chỉnh thiết kế. Không thêm thành phần mới.*

## 7. Kế hoạch kiểm chứng thực tế

| Tiêu chí | Ý nghĩa | Ngưỡng đề xuất |
| --- | --- | --- |
| COMPLIANT sai trên commit lỗi | Không bỏ lọt lỗi một cách nguy hiểm | 0 (tối đa 5%) |
| Recall trên lỗi lịch sử loại A–C | Bắt được lỗi thật | ≥ 60% |
| Precision của VIOLATION | Báo lỗi đáng tin, ngang RFCAudit (81,9%) | ≥ 80% |
| Vị trí mã đúng cho VIOLATION | Lập trình viên sửa được ngay | ≥ 70% |
| Tỉ lệ được kết luận, loại A–C | Không né bằng UNVERIFIABLE | ≥ 60% |
| Chi phí mỗi yêu cầu | Dùng được hằng ngày | Đo ở lát cắt dọc, sau đó đặt trần |

*Bảng 13. Tiêu chí "work thực tế". Ngưỡng là đề xuất, cần thầy chốt.*

1. **Đến giữa tháng 11:** chọn 5 commit loại B sau tháng 7/2026 (gồm `c18833f52`), bọc thành mẫu adapter, chạy tay trên commit cha và commit sửa.
2. **Cuối tháng 11:** lát cắt dọc, chạy trọn luồng với agent LLM thật cho TLS13-0042 và 5 lỗi trên; đo độ chính xác của Code Reader theo từng khía cạnh và đo chi phí.
3. **Sau đó:** mở rộng lên 40–60 yêu cầu TLS, dùng 47 commit sau tháng 7/2026 làm tập đánh giá chính, các commit trước đó làm tập phát triển.

## 8. Rủi ro còn lại

| Rủi ro | Biện pháp |
| --- | --- |
| Agent LLM đọc ngưỡng hoặc phản ứng kém hơn khi người làm tay | Đo sớm ở lát cắt dọc; với loại A–C, T3 quyết định nhãn nên đọc mã kém không gây nhãn sai |
| Chưa thử bộ kiểm thử của QUIC, DNS, SSH | HTTP/2 có h2spec; với các giao thức còn lại, kiểm tra bộ kiểm thử sẵn có trước khi chốt số yêu cầu |
| Khối lượng cài đặt cho một người | TLS làm sâu, các giao thức khác ở mức chứng minh adapter mở rộng được, như bản đề xuất |
| Ứng viên sai lệch có thể là lựa chọn có chủ đích | Giữ bước người kiểm chứng xác nhận; báo cáo là ứng viên cho tới khi nhà phát triển xác nhận |

*Bảng 14. Rủi ro còn lại.*

## 9. Tái lập

```
# SUT
git clone https://github.com/wolfSSL/wolfssl && cd wolfssl
git worktree add ../w_bug  c18833f52^      # bản lỗi
git worktree add ../w_fix  c18833f52       # bản sửa
cd ../w_bug && ./autogen.sh && ./configure --enable-tls13 --disable-shared --enable-static \
     CFLAGS=-DWOLFSSL_TLS13_MIDDLEBOX_COMPAT && make examples/server/server
./examples/server/server -v 4 -d -g -i -p 4433

# T3 sau handshake
git clone https://github.com/tlsfuzzer/tlsfuzzer && git clone https://github.com/tlsfuzzer/tlslite-ng
cd tlsfuzzer && PYTHONPATH=../tlslite-ng python3 scripts/test-tls13-record-layer-limits.py \
     -h 127.0.0.1 -p 4433 "<tên ca>"          # mỗi ca một tiến trình server mới

# Dòng được biên dịch
gcc -E -I. -DHAVE_CONFIG_H <cờ build> src/internal.c   # đọc line marker
```

## 10. Nguồn

- wolfSSL, commit c18833f52 "Fix to send record\_overflow alert". [github.com/wolfSSL/wolfssl](https://github.com/wolfSSL/wolfssl/commit/c18833f5206e5a96ab7400c569f830903f0c36c5)
- tlsfuzzer. [github.com/tlsfuzzer/tlsfuzzer](https://github.com/tlsfuzzer/tlsfuzzer); tlslite-ng. [github.com/tlsfuzzer/tlslite-ng](https://github.com/tlsfuzzer/tlslite-ng)
- M. Maehren et al., TLS-Anvil: Adapting Combinatorial Testing for TLS Libraries, USENIX Security 2022. [usenix.org](https://www.usenix.org/conference/usenixsecurity22/presentation/maehren)
- M. Zheng et al., RFCAudit, ASE 2025. [arXiv:2506.00714](https://arxiv.org/abs/2506.00714)
- RFC 8446: The Transport Layer Security (TLS) Protocol Version 1.3, §5.1, §5.2. [rfc-editor.org/rfc/rfc8446](https://www.rfc-editor.org/rfc/rfc8446)

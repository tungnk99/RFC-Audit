# Báo cáo bộ đánh giá 50 mục: lỗi thật và lỗi tự sinh trên mã thật (wolfSSL, OpenSSL)

Ngày chạy: 2026-10-24. Ma trận chạy: `backend/runs/real/out50` (chế độ `efficient`, mỗi mục chạy **một lần**, n = 1). Mã commit: `e93aa26` (nhánh `dev`, chưa đẩy).
Báo cáo ghi cả những chỗ **không đạt** và những lựa chọn có thể làm đẹp số liệu; mọi con số là đo thật, nhưng cỡ mẫu nhỏ và mỗi mục chạy một lần nên chỉ mô tả,
không khẳng định ý nghĩa thống kê mạnh.

## 1. Tóm tắt

| Câu hỏi | Trả lời |
|---|---|
| Có bao nhiêu mẫu? | **50 mục có nhãn**: 7 mục từ lỗi thật của wolfSSL (bản lỗi/bản vá/bản mới và hai cặp cha–vá) và 43 mục tự sinh (mutant) trên mã thật của wolfSSL (30) và OpenSSL (13). Mục tiêu ban đầu 50–70 mẫu **thật** chưa đạt: chỉ có 7. |
| Đúng nhãn? | **50/50**. Phát hiện lỗi 28/28 (Wilson 95%: 88–100%), báo nhầm 0/22 (0–15%), mọi mục đều ra kết luận (COMPLIANT hoặc VIOLATION). |
| Định vị đúng chỗ sửa? | **Yếu: 9/28 = 32%** (Wilson 95%: 18–51%). Với 7 mục thật: 0/3. Kết luận và giải thích thường đúng nhưng vị trí mã hay sai. |
| Con số 50/50 có đáng tin hết không? | **Không tuyệt đối.** Bộ chính đã loại 9 mutant (xem mục 4); hai trong số đó (M4, U5) là hai mẫu hệ thống **từng báo COMPLIANT sai**. Điều đó đúng về nguyên tắc nhưng làm số liệu đẹp hơn thực tế. |
| Chi phí? | Khoảng **14,9 triệu token** cho 50 mục, trung bình khoảng 300k mỗi mục. Chi phí chênh lớn theo họ: COMPLIANT họ G 14k, họ R trung vị 44k, nhưng COMPLIANT họ U trung vị 539k (hệ thống vẫn đọc mã); VIOLATION 208k–674k. |
| Phạm vi? | 3 họ yêu cầu, 2 triển khai, chỉ phía máy chủ, một họ mô hình (DeepSeek). |

## 2. Thiết kế bộ mẫu

### 2.1 Ba họ yêu cầu (RBS tầng B, viết tay, câu RFC có trong `backend/inputs/rfc/rfc8446.txt`)

| Họ | Yêu cầu | Câu RFC | Phản ứng đúng | Đầu vào kiểm thử (biến thể) |
|---|---|---|---|---|
| R | TLS13-0042 | RFC 8446 §5.2 | bản ghi TLSCiphertext dài hơn 2^14+256 ⇒ `record_overflow` | độ dài bản ghi: biên 16641, tối đa, ngẫu nhiên; kèm ca hợp lệ |
| U | TLS13-0101 | RFC 8446 §5 | loại bản ghi không định nghĩa ⇒ `unexpected_message` | loại 0, 99, 255, gửi rõ ngay sau khi nối |
| G | TLS13-0103 | RFC 8446 §4.1.1 | ClientHello không có nhóm chung ⇒ `handshake_failure` (cho phép `insufficient_security`) | supported_groups không giao; ca đối chứng có nhóm chung |

Phía hợp lệ (đối chứng): mỗi họ có ca hợp lệ phải được chấp nhận; ca nào mọi bản tham chiếu đều bác bỏ thì bị miễn (`waived`) theo quy tắc `rfc-protocol@8`.

### 2.2 Nguồn mẫu

| Nguồn | Số mục | Cách tạo |
|---|---|---|
| Lỗi thật wolfSSL, độ dài bản ghi: `bug` (cha của `c18833f52`), `fix` (`c18833f52`), `head` (`28bc7540d`) | 3 | commit thật; nhãn theo bản vá |
| Cặp thật P1 (`4b30475a4`, loại bản ghi lạ) | 2 | cha = VIOLATION, bản vá = COMPLIANT; dựng nhị phân gia tăng |
| Cặp thật P3 (`d3abc288e`, không có nhóm chung) | 2 | như trên |
| Mutant trên wolfSSL `28bc7540d` | 30 | chỉ sửa/xoá **dòng có sẵn** trong mã thật; mỗi mutant một commit |
| Mutant trên OpenSSL `openssl-3.6.5` (git) | 13 | như trên; dựng từ git, ảnh Docker `rfcv/sut-openssl:<sha12>` |

Mutant: kiểu lỗi gồm sai mã alert (sang `illegal_parameter`, `decode_error`, `internal_error`, `handshake_failure`, `missing_extension`…), xoá lệnh gửi alert, đảo hai nhánh của biểu thức điều kiện; kèm mutant **không phải lỗi** làm đối chứng: đổi alert của một yêu cầu khác (`UNRELATED`), đổi sang alert RFC cho phép (`ALLOWED_ALTERNATIVE`), đổi thứ tự nhãn `case` (`EQUIVALENT`), đổi nội dung nhật ký.

### 2.3 Nhãn chuẩn đến từ đâu (quan trọng khi đọc kết quả)

- Nhãn của mutant được **chốt trong script theo ngữ nghĩa phép sửa so với RFC**, trước khi chạy hệ thống (`scripts/eval_make_mutants_multi.py`, `eval_make_mutants_openssl.py`).
- OpenSSL: mỗi mutant được **kiểm độc lập** bằng cách chạy thẳng runner tlsfuzzer trên ảnh mutant (không qua hệ thống); hành vi quan sát khớp nhãn cả 13 mục. Lần kiểm này còn phát hiện bốn mutant đầu tiên (OU1–OU4) sửa nhầm dòng không chạy với đầu vào của họ U, sau đó đã sửa đúng dòng (`rec_layer_s3.c:855`, lấy từ ngăn xếp lỗi của chính OpenSSL).
- wolfSSL: nhãn mutant **không có bước kiểm độc lập bằng runner** (ngoài bộ M1–M8 từng đối chiếu bằng tlsfuzzer); nhãn dựa trên đọc phép sửa. Kết quả hệ thống khớp nhãn nên không phát hiện mâu thuẫn, nhưng đây là một điểm yếu của nhãn.
- Chỉ **tôi (Claude) và bạn** duyệt nhãn; không có người duyệt thứ hai độc lập nên **không có kappa giữa hai người gán nhãn độc lập**.
- Hệ thống không được đưa commit, diff hay thông điệp commit; công cụ đọc mã (`code.grep/glob/read/eval`) chỉ đọc tệp nguồn trong phạm vi `code_scope` của cây mã tại commit của mục, không có công cụ git.

## 3. Kết quả

### 3.1 Chỉ số tổng (50 mục)

| Chỉ số | Giá trị |
|---|---|
| VIOLATION chuẩn / COMPLIANT chuẩn | 28 / 22 |
| COMPLIANT sai (bỏ sót lỗi) | 0/28 = 0% (Wilson 95%: 0–12%) |
| VIOLATION sai (báo nhầm) | 0/22 = 0% (0–15%) |
| Recall VIOLATION | 28/28 = 100% (88–100%) |
| Precision VIOLATION | 28/28 = 100% (88–100%) |
| COMPLIANT đúng | 22/22 = 100% (85–100%) |
| Kết luận được | 50/50 = 100% (93–100%) |
| Định vị trúng chỗ sửa (trong lỗi đã phát hiện) | 9/28 = 32% (18–51%) |

### 3.2 Theo họ yêu cầu và theo nguồn

| Nhóm | Đúng nhãn | Định vị trúng | Token TB / tổng |
|---|---|---|---|
| Họ R (độ dài bản ghi) | 18/18 | – | – |
| Họ U (loại bản ghi lạ) | 14/14 | – | – |
| Họ G (không có nhóm chung) | 18/18 | – | – |
| Lỗi thật wolfSSL | 7/7 | 0/3 | 324k / 2,27 triệu |
| Mutant wolfSSL | 30/30 | 6/16 | 287k / 8,60 triệu |
| Mutant OpenSSL | 13/13 | 3/9 | 312k / 4,06 triệu |
| Cả bộ | 50/50 | 9/28 | 14,93 triệu |

### 3.3 Chi tiết từng mục

Cột "Định vị": `trúng` nghĩa là T1 chỉ trúng một dòng/hàm thuộc phép sửa; `trượt` là kết luận đúng nhưng vị trí mã sai; `–` là mục COMPLIANT. "Chuẩn"/"Hệ thống": VIOL = VIOLATION, COMP = COMPLIANT.

| Mục | Họ | Nguồn | Kiểu lỗi | Chuẩn | Hệ thống | Quy tắc | Định vị | Token |
|---|---|---|---|---|---|---|---|---|
| bug | R | thật | thật | VIOL | VIOL | V2 | trượt | 674k |
| fix | R | thật | thật | COMP | COMP | V6 | – | 44k |
| head | R | thật | thật | COMP | COMP | V6 | – | 63k |
| P1-parent | U | thật | thật | VIOL | VIOL | V2 | trượt | 512k |
| P1-fix | U | thật | thật | COMP | COMP | V6 | – | 598k |
| P3-parent | G | thật | thật | VIOL | VIOL | V2 | trượt | 360k |
| P3-fix | G | thật | thật | COMP | COMP | V6 | – | 14k |
| M1 | R | wolfSSL | WRONG_ALERT | VIOL | VIOL | V2 | trượt | 639k |
| M2 | R | wolfSSL | DEL_ALERT | VIOL | VIOL | V2 | trượt | 587k |
| M5 | R | wolfSSL | DEL_ALERT_BOTH | VIOL | VIOL | V2 | trúng | 382k |
| M6 | R | wolfSSL | EQUIVALENT | COMP | COMP | V6 | – | 108k |
| M7 | R | wolfSSL | UNRELATED | COMP | COMP | V6 | – | 44k |
| M8 | R | wolfSSL | THRESHOLD_MASKED | COMP | COMP | V6 | – | 44k |
| U1 | U | wolfSSL | WRONG_ALERT | VIOL | VIOL | V2 | trượt | 526k |
| U2 | U | wolfSSL | DEL_ALERT | VIOL | VIOL | V2 | trúng | 392k |
| U4 | U | wolfSSL | WRONG_ALERT_OTHER | VIOL | VIOL | V2 | trượt | 384k |
| U7 | U | wolfSSL | UNRELATED | COMP | COMP | V6 | – | 509k |
| U8 | U | wolfSSL | UNRELATED | COMP | COMP | V6 | – | 539k |
| G1 | G | wolfSSL | WRONG_ALERT | VIOL | VIOL | V2 | trượt | 382k |
| G2 | G | wolfSSL | WRONG_ALERT_OTHER | VIOL | VIOL | V2 | trúng | 340k |
| G3 | G | wolfSSL | WRONG_ALERT_OTHER | VIOL | VIOL | V2 | trượt | 404k |
| G4 | G | wolfSSL | ALLOWED_ALTERNATIVE | COMP | COMP | V6 | – | 14k |
| G5 | G | wolfSSL | EQUIVALENT | COMP | COMP | V6 | – | 14k |
| G6 | G | wolfSSL | UNRELATED | COMP | COMP | V6 | – | 14k |
| G7 | G | wolfSSL | UNRELATED | COMP | COMP | V6 | – | 14k |
| R9 | R | wolfSSL | WRONG_ALERT_FULL | VIOL | VIOL | V2 | trúng | 396k |
| R10 | R | wolfSSL | WRONG_ALERT_HEADER_ONLY | VIOL | VIOL | V2 | trượt | 405k |
| R12 | R | wolfSSL | UNRELATED | COMP | COMP | V6 | – | 44k |
| U13 | U | wolfSSL | UNRELATED | COMP | COMP | V6 | – | 574k |
| U14 | U | wolfSSL | WRONG_ALERT_OTHER | VIOL | VIOL | V2 | trúng | 378k |
| G8 | G | wolfSSL | WRONG_ALERT_OTHER | VIOL | VIOL | V2 | trượt | 380k |
| G9 | G | wolfSSL | WRONG_ALERT_OTHER | VIOL | VIOL | V2 | trượt | 317k |
| G11 | G | wolfSSL | UNRELATED | COMP | COMP | V6 | – | 14k |
| G12 | G | wolfSSL | WRONG_ALERT_OTHER | VIOL | VIOL | V2 | trượt | 393k |
| R14 | R | wolfSSL | WRONG_ALERT_FULL | VIOL | VIOL | V2 | trúng | 266k |
| R16 | R | wolfSSL | EQUIVALENT | COMP | COMP | V6 | – | 44k |
| R17 | R | wolfSSL | UNRELATED | COMP | COMP | V6 | – | 44k |
| OU1 | U | OpenSSL | WRONG_ALERT | VIOL | VIOL | V2 | trượt | 547k |
| OU2 | U | OpenSSL | WRONG_ALERT | VIOL | VIOL | V2 | trượt | 323k |
| OU3 | U | OpenSSL | WRONG_ALERT | VIOL | VIOL | V2 | trượt | 547k |
| OU4 | U | OpenSSL | DEL_ALERT | VIOL | VIOL | V2 | trượt | 391k |
| OG1 | G | OpenSSL | WRONG_ALERT | VIOL | VIOL | V2 | trượt | 493k |
| OG2 | G | OpenSSL | WRONG_ALERT_OTHER | VIOL | VIOL | V2 | trượt | 347k |
| OG3 | G | OpenSSL | ALLOWED_ALTERNATIVE | COMP | COMP | V6 | – | 14k |
| OG4 | G | OpenSSL | SWAP_BRANCHES | VIOL | VIOL | V2 | trúng | 365k |
| OR1 | R | OpenSSL | WRONG_ALERT | VIOL | VIOL | V2 | trúng | 375k |
| OR3 | R | OpenSSL | WRONG_ALERT_FULL | VIOL | VIOL | V2 | trúng | 208k |
| OX1 | G | OpenSSL | UNRELATED | COMP | COMP | V6 | – | 14k |
| OX2 | R | OpenSSL | UNRELATED | COMP | COMP | V6 | – | 44k |
| OX3 | U | OpenSSL | UNRELATED | COMP | COMP | V6 | – | 386k |

## 4. Những điều làm số liệu đẹp hơn thực tế (phải đọc)

1. **Chín mutant bị loại khỏi bộ chính** (vẫn nằm trong các tệp `mutants*.yaml`, trường `excluded`):
   - Có thêm mã tự viết, trái nguyên tắc "chỉ sửa dòng thật": M3, U3 (`#ifdef` với macro giả), U5 (điều kiện `if` tự viết), U6, R11 (biến cục bộ).
   - Vi phạm một câu RFC **khác** câu mà RBS TLS13-0042 kiểm (đường sau giải mã: nội dung > 2^14 ⇒ `record_overflow`, khác câu về TLSCiphertext > 2^14+256): M4, R13, R15, OR2. Đầu vào của họ R (độ dài > 16640) không bao giờ chạm tới đường đó.
2. **M4 và U5 là hai mẫu hệ thống từng báo COMPLIANT sai** (kết quả chạy trước đó: bộ 11 mục đúng 10/11, sai ở M4; bộ 19 mutant đa họ đúng 18/19, sai ở U5). Cả hai là lỗi "tinh vi" nằm ngoài các biến thể của oracle (U5: loại bản ghi 77 khi oracle chỉ thử 0, 99, 255; M4: dải độ dài ngoài biên RBS). Lý do loại hợp lý, nhưng kết quả vẫn cho thấy **khả năng phát hiện bị giới hạn bởi độ phủ biến thể của oracle**, chưa được khắc phục (chế độ `thorough` cũng không cứu được M4).
3. Nhãn do người xây bộ dữ liệu (tôi) chốt, và mutant do chính tôi tạo nên dễ rơi vào kiểu lỗi mà hệ thống đã được chỉnh để bắt (sai mã alert, bỏ alert). Lỗi thật tự nhiên thường đa dạng hơn.
4. Mỗi mục chạy **một lần**; chưa đo tái lập.

## 5. Điểm yếu và vấn đề còn mở

| Vấn đề | Chi tiết | Hướng |
|---|---|---|
| **Định vị 32%** | Kết luận đúng nhưng `defect_hit` chỉ 9/28; mục thật 0/3. Với mutant sửa ở hàm ánh xạ alert (`TranslateErrorToAlert`, `extensions.c`) T1 thường trỏ sang hàm khác. Chưa đọc từng báo cáo T1 để xác nhận nguyên nhân. | Điều tra 19 mục định vị trượt; cân nhắc dùng chi tiết lỗi của SUT (ví dụ ngăn xếp lỗi `tệp:dòng` của OpenSSL) làm gợi ý cho Code Reader |
| Mù với lỗi ngoài biến thể | M4, U5 (mục 4) | Thêm biến thể ở các giới hạn suy ra từ ràng buộc khác trong ngữ cảnh RFC |
| P2 chưa tái hiện được | Cặp `1e770e1a0` (key_share rỗng ⇒ `decode_error`): đầu vào của tôi làm **cả hai bản** trả `missing_extension`, dòng sửa không bị chạm. Hệ thống không báo nhầm, nhưng nhãn "bản vá = COMPLIANT" không áp dụng nên cặp bị bỏ. | Tìm đầu vào thật sự phân biệt (bật log gỡ lỗi wolfSSL, đối chiếu ca tlsfuzzer cho issue #9640) |
| GnuTLS lệch ở `type_255` | Trong P1, GnuTLS FAIL còn OpenSSL PASS ở loại bản ghi 255; chưa điều tra | Kiểm tra thủ công hành vi GnuTLS |
| mbedTLS 3.6.7 gốc | Không gửi alert nào ở cả ba họ yêu cầu (log: `ssl_tls13_write_hello_retry_request() returned -0x6e00`, đóng kết nối). Có thể là phát hiện thật hoặc sai khác về quan sát. **Chưa kiểm chứng**; chưa dùng làm nền "tuân thủ". | Kiểm tra thêm; nếu đúng là lỗi thật thì là một mẫu VIOLATION thật |
| Chi phí | Mục VIOLATION 208k–674k token (trung vị G 372k, R 396k, U 392k). Mục COMPLIANT rất lệch: họ G 14k, họ R trung vị 44k, nhưng họ U trung vị 539k (386k–598k) vì vẫn đọc mã dù T3 đã PASS. | Tìm vì sao họ U không đi đường tắt như G và R; tối ưu đọc mã khi T3 đã xác định lỗi |
| Cache nhân chứng không gắn mã runner | Sửa runner mà quên `RFCV_WITNESS_CACHE=off` thì đọc kết quả cũ | Đưa băm mã runner vào khoá cache |
| `ruff format --check` | 9 tệp lệch định dạng (7 trước đợt này) | dọn riêng |
| Phạm vi | 3 họ yêu cầu, wolfSSL và OpenSSL, phía máy chủ, một họ mô hình, BEHAVIORAL (không đo độ phủ mã), RBS viết tay (RFC Analyst chưa nối) | xem mục 7 |

## 6. Phễu chọn lỗi thật

Phễu cơ học (không gán nhãn) từ lịch sử git; ứng viên còn phải duyệt tay, viết RBS và dựng nhị phân từng cặp.

- **wolfSSL, từ 2025-01** (`wolfssl_funnel.csv`): 951 commit đụng `internal.c/tls13.c/tls.c` → 450 không đụng hàm xử lý đầu vào của máy chủ, 186 ứng viên yếu, 114 DTLS/QUIC/ECH…, 88 test/CI, 60 phía khách, 34 quá lớn → **19 ứng viên mạnh** (2 thuộc tập eval ≥ 2026-07, 17 thuộc dev).
- **Nhiều kho, từ 2023-01** (`funnel_<kho>.csv`, bộ lọc nới hơn, chỉ cơ học):

| Kho | Tổng commit đụng mã lõi | Ứng viên |
|---|---|---|
| wolfSSL | 1458 | 53 |
| OpenSSL | 481 | 24 |
| rustls | 1334 | 14 |
| BoringSSL | 604 | 11 |
| s2n-tls | 399 | 7 |
| mbedTLS | 638 | 2 |
| GnuTLS | 74 | 1 |

- Trong ba cặp đã thử, hai dùng được (P1, P3) và một không (P2). Số cặp thật cuối cùng sẽ thấp hơn số ứng viên nhiều.

## 7. Việc tiếp theo

1. Điều tra định vị trượt (19 mục) vì đây là điểm yếu lớn nhất so với tiêu chí "đúng lỗi, đúng vị trí, giải thích đầy đủ".
2. Thêm lỗi thật: xét ứng viên OpenSSL/rustls/BoringSSL từ phễu và tìm đầu vào phân biệt cho P2; nối RFC Analyst để RBS không còn viết tay.
3. Đo tái lập (chạy lại 3 lần trên tập con), chế độ `thorough` cho tập con, và đối chứng B1 (tlsfuzzer thuần) và B2 (một agent LLM) theo kế hoạch.
4. Giải quyết giới hạn biến thể của oracle (M4, U5).
5. Trước khi chốt số liệu cho luận văn: dựng người duyệt nhãn thứ hai nếu có thể, đóng băng tập eval (commit ≥ 2026-07) và chạy một lần.

## 8. Tái lập

Điều kiện: Docker, ảnh nền `rfcv/sut-build:head`, `rfcv/sut-wolfssl:head`, `rfcv/ref-openssl:latest`, `rfcv/ref-gnutls:latest`, `rfcv/sut-build-openssl:head` (xem `backend/docker/`), khoá API của mô hình trong `backend/.env`.

```
# sinh mutant và ảnh Docker
uv run python scripts/eval_make_mutants_multi.py --images        # wolfSSL, họ U/G/R
uv run python scripts/eval_make_mutants_openssl.py --images --check   # OpenSSL từ git, kèm kiểm độc lập bằng runner
# chạy ma trận 50 mục
uv run --env-file .env python scripts/run_real_matrix.py --out runs/real/out50 --set all --effort efficient
# xem phễu đa kho
uv run python scripts/eval_mine_repos.py --since 2023-01-01
```

Nhãn chuẩn nằm ở `backend/eval/dataset/mutants/{mutants,mutants_multi,mutants_openssl}.yaml`; RBS của ba họ ở `backend/eval/dataset/real/rbs/` và `backend/adapters/tls13/examples/`.

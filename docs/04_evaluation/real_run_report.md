# Báo cáo chạy thật: TLS13-0042 trên wolfSSL (bản lỗi, bản sửa, bản mới nhất)

Ngày chạy: 2026-10-23. Đây là lần đầu hệ thống đa agent điều khiển một SUT thật. Báo cáo ghi cả những chỗ **không đạt**; mọi con số là đo thật,
nhưng mỗi cấu hình mới chạy **một lần** (n = 1), nên chỉ mô tả, không khẳng định ý nghĩa thống kê.

## 1. Tóm tắt

| Câu hỏi | Trả lời |
|---|---|
| Chạy trọn quy trình trên SUT thật được chưa? | **Rồi**: LLM thật (DeepSeek), wolfSSL thật trong Docker, hai tham chiếu độc lập thật (OpenSSL, GnuTLS), chỉ mục mã tree-sitter chạy trong Docker, bộ chạy lệnh đọc mã trong Docker, Report agent và Output gate. |
| Với đặc tả RBS **gốc** có phát hiện đúng lỗi không? | **Không**: cả ba phiên bản đều ra NEEDS_REVIEW (V1). Hệ thống không phân biệt được bản lỗi với bản sửa. |
| Nguyên nhân? | **Đặc tả sai ở phía hợp lệ**, không phải lỗi agent. Hai tham chiếu độc lập bác bỏ đối chứng `at_limit=16640` của RBS. |
| Với đặc tả sửa (thăm dò) thì sao? | **Đúng cả ba**: bản lỗi → VIOLATION (V2), bản sửa và bản mới → COMPLIANT (V6, BEHAVIORAL). |
| Đọc mã (T1) có hoạt động không? | **Không**: Code Reader hỏng ở **mọi** lần chạy (hết 400k token), T1 = 0. |
| Hiệu quả token? | **Kém**: 83–85% token rơi vào các lần chạy Code Reader hỏng, không tạo bằng chứng nào. |
| Độ phủ? | **Thấp**: 0,12–0,19% dòng mã đã xem, 1 yêu cầu, 1/5 đường kích hoạt mà tlsfuzzer có. |

## 2. Cấu hình thật

- SUT: wolfSSL `0cecccdf6` (bug = cha của bản sửa), `c18833f52` (fix), `28bc7540d` (head), build `--enable-tls13 --disable-shared --enable-static`
  với `-DWOLFSSL_TLS13_MIDDLEBOX_COMPAT`; image Docker ghim theo commit, launcher kiểm `/sut/.rev` khớp `sut.commit` của adapter.
- Tham chiếu độc lập: OpenSSL và GnuTLS (gói Debian bookworm), TLS 1.3. **Lệch thiết kế gốc** (rustls + OpenSSL); lý do: rustls cần Rust, chậm dựng.
- Client kiểm thử: tlsfuzzer `5eebc44` + tlslite-ng `7e95ea1` (ghim commit), chạy **trong container SUT** qua `docker exec`; container `--network none`,
  `--cap-drop ALL`, `no-new-privileges`, `--read-only`, giới hạn tiến trình/bộ nhớ/CPU.
- Mã đọc: ba worktree LF của wolfSSL, phạm vi `src/**` + `wolfssl/**` (281 tệp, 309.885 dòng, 30.567 ký hiệu).
- LLM: DeepSeek cho mọi vai trò (một họ mô hình). Ngân sách mỗi yêu cầu 8 vòng, 1,5 triệu token, 120 lời gọi công cụ, 1800 giây.
- Hạn chế môi trường: **không đo độ phủ mã** (nhãn tối đa BEHAVIORAL), **không đổi đồng hồ** giữa các môi trường (chỉ đổi tên máy).

## 3. Số đo nền: tlsfuzzer thuần, không agent (145 ca, mỗi ca một tiến trình SUT)

| Phiên bản | PASS | FAIL |
|---|---|---|
| bug | 12 | 133 (128 ca `too big ciphertext`, 2 Finished, 2 max size, 1 ClientHello) |
| fix | 144 | 1 (`too big ClientHello msg, with 16168 bytes of padding`) |
| head | 144 | 1 (cùng ca) |

Khớp tài liệu khả thi về số PASS của bản lỗi (12) và ca FAIL duy nhất của bản sửa. Tổng số ca (145 so với 67) khác vì tlsfuzzer ghim có nhiều biến thể hơn.
Tốn khoảng 50 giây mỗi phiên bản, **0 token**.

## 4. Kết quả hệ thống đa agent

| Cấu hình | Phiên bản | Nhãn | Vòng | Giây | Token | Lãng phí* | Code Reader hỏng |
|---|---|---|---|---|---|---|---|
| A: RBS gốc (TLS13-0042) | bug | NEEDS_REVIEW, V1 | 1 | 372 | 455.709 | 85% | 1/1 |
| A | fix | NEEDS_REVIEW, V1 | 1 | 352 | 474.488 | 82% | 1/1 |
| A | head | NEEDS_REVIEW, V1 | 1 | 348 | 471.274 | 84% | 1/1 |
| B: RBS sửa, **thăm dò** (TLS13-0043) | bug | **VIOLATION, V2** | 1 | 399 | 478.393 | 83% | 1/1 |
| B | fix | COMPLIANT, V6 BEHAVIORAL | 4 | 438 | 1.850.211 | 85% | 4/4 |
| B | head | COMPLIANT, V6 BEHAVIORAL | 4 | 426 | 1.848.441 | 84% | 4/4 |

\* Lãng phí = token của các lần chạy agent bị hỏng / tổng token. Cả sáu lần chạy: chuỗi hash bằng chứng hợp lệ (`rfcv verify`), kết luận kèm quy tắc.

### 4.1 Cấu hình A: vì sao ra NEEDS_REVIEW ở cả ba bản

Phía vi phạm (11 biến thể có `record.length` > 16640) cho bằng chứng đúng với bản lỗi: wolfSSL không cảnh báo (FAIL) còn OpenSSL và GnuTLS đều gửi
`record_overflow` (PASS) → đúng dấu hiệu của một vi phạm thật. Nhưng đối chứng `at_limit=16640` (RBS coi là "hợp lệ, không được cảnh báo") **bị cả hai tham chiếu
cùng FAIL** (chúng cảnh báo ở 16640), nên V1 coi oracle bị thế giới thật bác bỏ và dừng. Hệ thống làm đúng thiết kế (không kết luận trên oracle bị bác bỏ);
cái sai là RBS.

Gốc của lỗi đặc tả (xác nhận bằng thực nghiệm trên 5 cài đặt, xem phụ lục): một bản ghi mã hoá có `TLSCiphertext.length = N` luôn chứa
`TLSInnerPlaintext` dài N − 16 (loại nội dung, đệm, dữ liệu; thẻ AEAD 16 byte), mà RFC 8446 §5.4 cấm TLSInnerPlaintext dài hơn 2^14 + 1 (§6.2: vi phạm phải bị cảnh báo `record_overflow`; §5.2 chỉ nêu ngưỡng ciphertext 2^14 + 256). Vì vậy bản ghi mã hoá
hợp lệ phải bị cảnh báo từ N = **16402**, không phải 16640. Câu RFC mà RBS dịch ("TLSCiphertext > 2^14 + 256 thì phải cảnh báo") chỉ nêu ngưỡng trên; RBS lại suy thêm
"≤ 16640 thì không được cảnh báo", điều RFC không nói.

### 4.2 Cấu hình B (thăm dò): đặc tả đúng thì hệ thống phát hiện đúng

RBS B đổi trigger thành `record.length > 16401` và miền `record.length` bắt đầu từ 17 (bản ghi mã hoá tối thiểu 17 byte). **Đây không phải đặc tả đã được duyệt**: do tôi
suy từ giới hạn TLSInnerPlaintext, `sentence_id` vẫn mượn của câu gốc.

- **bug** → VIOLATION (V2): 10/12 ca phía vi phạm FAIL (`max=65535` và 9 mẫu >16640: không cảnh báo), hai tham chiếu PASS; cả 18 ca phía hợp lệ (gồm đối chứng 16401) PASS ở SUT lẫn tham chiếu.
  Ghi chú: ở 16402 bản lỗi **vẫn** cảnh báo (đã đo); chỉ hỏng khi N > 16640. Có vẻ cảnh báo đến từ đường kiểm tra độ dài văn bản bên trong, còn đường kiểm tra TLSCiphertext
  thiếu `SendAlert` (suy luận từ mã, chưa kiểm bằng cách khác).
- **fix** và **head** → COMPLIANT (V6): mọi ca PASS. Verifier được gọi lần đầu (phản biện trước COMPLIANT), nêu thiếu bằng chứng mã, Planner giao LOCATE/TRACE_PATHS,
  Code Reader hỏng 4 lần liên tiếp rồi dừng vì hết ngân sách; nhãn cuối vẫn COMPLIANT nhưng chỉ ở mức BEHAVIORAL, tốn 1,85 triệu token.

## 5. Agent nào đã chạy

| Agent | A (gốc) | B (thăm dò) |
|---|---|---|
| Planner | chạy, theo sổ tay | chạy, theo sổ tay; vòng 4 `DEVIATE_PLAYBOOK` ở fix/head |
| Tester | chạy, kịch bản đúng | chạy, kịch bản đúng |
| Code Reader | chạy, **hỏng** | chạy, **hỏng** (bug 1/1, fix và head 4/4) |
| Verifier | không (chưa có nhãn COMPLIANT) | chạy 1 lần ở fix và head |
| Report + Output gate | chạy | chạy |
| RFC Analyst | **chưa nối vào luồng** (RBS viết tay) | như vậy |
| Code Indexer | **chưa nối** (chỉ mục dựng bằng bước tất định, không LLM) | như vậy |

## 6. Độ phủ

- **Mã**: Code Reader xem 380–592 dòng trong 309.885 (0,12–0,19%), 10–16 trên 281 tệp. Đây là tìm kiếm có định hướng, không quét hết, và không tạo được T1 nào.
- **Yêu cầu**: 1 yêu cầu RFC (TLS13-0042). Chưa đo các yêu cầu khác của RFC 8446.
- **Đường kích hoạt**: kịch bản của Tester chỉ gửi bản ghi dữ liệu ứng dụng mã hoá chứa toàn số 0. tlsfuzzer có thêm: ClientHello quá dài (chưa mã hoá), Finished có đệm,
  bản ghi mã hoá bị sửa thẻ AEAD. Ca FAIL duy nhất của fix/head (`ClientHello` đệm 16168 byte) **nằm ngoài** tầm của hệ thống.
- **Giá trị tham số**: 30 biến thể T3 cho miền 17…65535 (lấy mẫu phân tầng + giá trị đặc biệt); lỗi dạng cửa sổ hẹp vẫn có thể lọt (xem `rfcv-eval sim`, SYNTHETIC).

## 7. Token và chi phí

- Ba lần chạy cấu hình A: 1.401.471 token; Code Reader 1.170.634 (84%, cả ba lần hỏng), Tester 137.815 (10%), Planner 47.157 (3%), Report 45.865 (3%).
  Chỉ 16% token tạo ra giá trị.
- Trong Code Reader: yêu cầu LLM thứ 1 vào 11,8k token, thứ 17 vào 28,6k; tổng vào 383k cho 17 yêu cầu. Ngữ cảnh cố định (lời nhắc, skill, schema công cụ) gửi lại mỗi bước và lịch sử phình dần.
- Cấu hình B với bản sửa/head: 1,85 triệu token, trong đó Code Reader hỏng 1,56 triệu (85%).
- So sánh: tlsfuzzer thuần chạy 145 ca trong khoảng 50 giây, 0 token, rộng hơn. Với yêu cầu này, giá trị tăng thêm của agent **chưa được chứng minh**.
- Thời gian một lần chạy (~6 phút) chủ yếu là T3 tuần tự (mỗi ca một container, ~2,5 giây × 114 lần chạy ca), không phải LLM.

## 8. Vấn đề quan sát được

| # | Vấn đề | Loại | Trạng thái |
|---|---|---|---|
| P1 | RBS suy phía hợp lệ mà RFC không nói; ngưỡng thật cho bản ghi mã hoá là 16402, không phải 16640 | Đặc tả | **Mở**: cần sửa bước dịch RBS (RFC Analyst) và quy tắc sinh đối chứng |
| P2 | Code Reader hết ngân sách, T1 = 0 trên mã thật; hỏng chết là mất trắng | Agent / chi phí | **Mở** |
| P3 | Hub chạy Code Reader song song với kiểm thử kể cả khi T3 đã đủ kết luận | Điều phối | **Mở** |
| P4 | Miền `record.length` min = 0 không mã hoá được (bản ghi mã hoá ≥ 17 byte) → ca `trigger_not_reached` | Adapter | Giải pháp thăm dò: min = 17; chưa sửa adapter gốc |
| P5 | Kịch bản chưa phủ ClientHello/Finished/sửa thẻ AEAD | Độ phủ | **Mở** |
| P6 | Server ví dụ wolfSSL thoát sau mỗi lỗi; nếu là PID 1 thì container chết | Hạ tầng | **Đã sửa**: server chạy như tiến trình riêng, ghi mã thoát |
| P7 | Cổng lệnh từ chối cách viết vô hại (`head -40`, `--glob`, `-m5`) | Cổng | **Đã sửa** (chuẩn hoá về dạng chuẩn, cờ mới vẫn cấm; 28 test) |
| P8 | Quét rò rỉ báo nhầm 164–169 tệp, mất ~12 phút, mã thoát 3 dù lần chạy sạch (danh sách bỏ qua theo bố cục cũ `repo/`, bố cục mới `code/repo/`) | Cổng | **Đã sửa**: còn 0–2 báo nhầm, 9 giây. Báo nhầm còn lại: dòng log server trùng chữ với một README ngoài phạm vi |
| P9 | CRLF của Windows làm hỏng `git checkout`/`autogen.sh` trong container và đưa `\r\n` vào mã gửi container | Hạ tầng | **Đã sửa** |
| P10 | GnuTLS gửi `CertificateRequest` mặc định làm hỏng bắt tay của tlsfuzzer | Hạ tầng | **Đã sửa** (`--disable-client-cert`) |
| P11 | Một họ mô hình (DeepSeek); chưa có số đo thống kê (n = 1); chưa có độ phủ mã; đồng hồ không đổi giữa môi trường | Hạn chế | Ghi nhận |

## 9. Kết luận trung thực

1. Quy trình chạy thật được và **an toàn theo thiết kế**: không bịa kết luận khi oracle bị bác bỏ, bằng chứng có chuỗi hash, mỗi biến thể được kiểm lại ở ba môi trường và đối chiếu hai tham chiếu độc lập.
2. Phần **kiểm thử** (Tester + Test driver + Verdict engine) phát hiện đúng bản lỗi và không báo sai bản sửa **khi đặc tả đúng** (cấu hình B). Với đặc tả gốc thì không.
3. Phần **đọc mã** (Code Reader) chưa hoạt động trên mã thật, và là nơi tốn gần hết token.
4. Rủi ro lớn nhất của phương pháp được xác nhận bằng dữ liệu thật: **đặc tả sai là điểm lỗi duy nhất** của toàn bộ chuỗi; chỉ tham chiếu độc lập mới lộ ra điều đó.

## 10. Việc tiếp theo (theo tác động)

1. Code Reader: kết thúc có kết quả một phần khi gần hết ngân sách; gọi sau T3 và chỉ khi cần; thu gọn ngữ cảnh lặp; tính trước ứng viên bằng bước tất định.
2. Nối RFC Analyst (hai bản dịch độc lập + đối chiếu) và bộ vàng RBS; thêm bước đối chiếu đặc tả với tham chiếu độc lập **trước** khi tin RBS.
3. Chạy T3 song song; thêm kịch bản ClientHello/Finished; sửa miền `record.length`.
4. Đo độ phủ mã (gcov/lcov) để có LINKED; chạy lặp ≥ 3 lần mỗi cấu hình.

## Phụ lục A: phản ứng thật theo độ dài ciphertext (backend thật, `scripts/preflight_real_backend.py`)

`close_notify` = nhận bình thường; `record_overflow` = cảnh báo; `+X` = đóng kết nối; `none` = không cảnh báo.

| | 17 | 100 | 16401 | 16402 | 16640 | 16641 | 17000 | 65535 |
|---|---|---|---|---|---|---|---|---|
| bug | none | close_notify+X | close_notify+X | record_overflow+X | none+X | none+X | none+X | none+X |
| fix | none | close_notify+X | close_notify+X | record_overflow+X | record_overflow+X | record_overflow+X | record_overflow+X | record_overflow+X |
| head | none | close_notify+X | close_notify+X | record_overflow+X | record_overflow+X | record_overflow+X | record_overflow+X | record_overflow+X |
| OpenSSL | none | none | none | record_overflow+X | record_overflow+X | record_overflow+X | record_overflow+X | record_overflow+X |
| GnuTLS | none | none | none | record_overflow+X | record_overflow+X | record_overflow+X | record_overflow+X | record_overflow+X |

(N = 16 không gửi được: bản ghi mã hoá tối thiểu 17 byte.)

## Phụ lục B: tái lập

```bash
# Dựng image (xem backend/eval/README.md): SUT theo commit, tham chiếu, bộ chỉ mục và bộ chạy lệnh
docker build -f docker/eval-sut.Dockerfile --build-arg WOLFSSL_REV=<sha> -t rfcv/sut-wolfssl:<sha12> .
docker build -f docker/eval-ref.Dockerfile --target openssl -t rfcv/ref-openssl:latest .
docker build -f docker/eval-ref.Dockerfile --target gnutls  -t rfcv/ref-gnutls:latest  .
docker build -f docker/code-index-worker.Dockerfile --target worker  -t rfcv/code-index-worker:latest .
docker build -f docker/code-index-worker.Dockerfile --target indexer -t rfcv/code-indexer:latest .

uv run python scripts/run_tlsfuzzer_baseline.py bug fix head          # số đo nền, không LLM
uv run python scripts/preflight_real_backend.py                        # kiểm backend thật, không LLM

uv run --env-file .env rfcv run --adapter eval/adapters/tls13-<v> --code-root <worktree LF> \
    --code-index treesitter --executor docker --sut-launcher docker --models config/models.yaml --run-dir runs/real/out
uv run rfcv trace runs/real/out/<run_id> ; uv run rfcv verify runs/real/out/<run_id>
```

Log đầy đủ của từng lần chạy nằm trong thư mục lần chạy (`trace.db`, `evidence.db`, `manifest.json`, `leak_scan.json`, `artifacts/`); thư mục `runs/` không được commit.

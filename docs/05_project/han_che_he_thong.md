# Sổ hạn chế của hệ thống RFC-Audit

Tệp này ghi lại mọi hạn chế đã phát hiện, kèm bằng chứng, ảnh hưởng và hướng xử lý. Mỗi khi phát hiện hạn chế mới, hoặc xử lý xong một hạn chế, cập nhật tệp này.

- **Cập nhật lần cuối:** 24/11/2026 (sau các thế hệ tiến hoá `gen-34`–`gen-37`)
- **Cột "Báo cáo 02":** ✅ đã nêu trong báo cáo tiến độ 02 · ❌ chưa nêu · ⚠️ báo cáo đang ghi sai hoặc thiếu
- **Mức độ:** 🔴 thầy hoặc hội đồng dễ hỏi, ảnh hưởng tới kết luận chính · 🟡 nên nêu · ⚪ chi tiết kỹ thuật, biết để trả lời khi bị hỏi

---

## Câu hỏi gốc: thư viện mới đưa vào có dùng được không?

**Có, nhưng không tự động.** Hệ thống chỉ chạy được một thư viện khi đã có **adapter** cho thư viện đó. Adapter do người chuẩn bị trước, gồm:

1. Công thức biên dịch thành image Docker: lệnh dựng, cờ biên dịch;
2. Chương trình để chạy thư viện như một máy chủ: chương trình mẫu đi kèm thư viện (ví dụ `examples/server/server` của wolfSSL), hoặc một chương trình bọc nhỏ gọi API của thư viện nếu thư viện không có sẵn;
3. Lệnh chạy, cổng, cách kiểm tra máy chủ đã sẵn sàng;
4. Bản tham chiếu để đối chứng;
5. Từ vựng giao thức và mẫu kịch bản kiểm thử.

Đã có adapter thì **mọi phiên bản hoặc bản lỗi của thư viện đó** chạy được tự động. **Thư viện mới hoàn toàn** thì phải dựng adapter trước. Trong giai đoạn này đã dựng được adapter cho nghttp2, Knot DNS, dnsmasq, dropbear và ngtcp2, chứng tỏ việc này làm được, nhưng vẫn là việc thủ công. Chi tiết ở mục A1–A2.

---

## A. Phạm vi áp dụng

| # | Hạn chế | Bằng chứng | Ảnh hưởng | Hướng xử lý | Báo cáo 02 |
|---|---|---|---|---|---|
| A1 🔴 | **Thư viện mới cần dựng adapter bằng tay** (Dockerfile, lệnh chạy, tham chiếu, mẫu kịch bản). Hệ thống không tự sinh. | `backend/adapters/tls13/sut/wolfssl.yaml`, `backend/docker/eval-*.Dockerfile` | Mỗi cặp (giao thức, thư viện) tốn công chuẩn bị. Chưa thể "đưa thư viện vào là chạy". | Để AI đọc tài liệu và sinh công thức chạy, kiểm tra lại bằng ca sanity và bản tham chiếu | ❌ |
| A2 🟢 | ~~**Lệnh chạy viết cứng trong mã**, không đọc từ tệp công thức của adapter.~~ **Đã xử lý ở `gen-37` (`L6 ADD_CAPABILITY`):** bổ sung `specs_from_adapter()` trong `docker_launcher.py` tự đọc `roles.server.cmd`/`docker_cmd`, `port`, `transport`/`ready_check.kind`, `image` từ `sut/*.yaml` và tự đăng ký `<impl>` + `<impl>-ref` mà không cần sửa mã khởi chạy. | `backend/eval/evolution/tickets/gen-37.yaml`, `docker_launcher.py`, `test_backends.py` | Thêm thư viện mới chỉ cần thêm `sut/<impl>.yaml` trong adapter | Đã xử lý (`gen-37`) | ❌ |
| A3 🔴 | **Chỉ kiểm tra vai trò máy chủ.** tlsfuzzer luôn đóng vai client; phần mềm cần kiểm tra luôn là server. | `docker_launcher.py`: chỉ khởi chạy server; runner luôn là client | Không kiểm tra được các yêu cầu dành cho client | Thêm chế độ hệ thống đóng vai server, phần mềm cần kiểm tra đóng vai client | ❌ |
| A4 🟡 | **Thư viện không có phần mạng** (chỉ phân tích cú pháp, mã hoá/giải mã) chưa kiểm tra được. Hiện chỉ có backend gửi gói tin qua mạng. | `backend/src/rfcv/backends/`: tlsfuzzer, http2, dns, ssh, quic đều đi qua socket | Bỏ ngoài phạm vi một lớp thư viện | Thêm backend gọi API trực tiếp, quan sát mã lỗi trả về | ❌ |
| A5 🟡 | **Yêu cầu nội bộ** (loại D, ví dụ "phải xoá khoá sau khi dùng") có thiết kế (quy tắc V8, truy vấn tĩnh T2) nhưng **chưa được đánh giá**. | `rules.py`: `V8-violation`, `V8-compliant` | Chưa chứng minh được câu "kiểm tra cả yêu cầu không quan sát được qua mạng" | Làm bộ mẫu loại D và đánh giá | ❌ |
| A6 ⚪ | **Không chạy được phần mềm thì không ra nhãn**: dừng `INFEASIBLE`, nhãn `UNVERIFIABLE` (V9). Đây là chủ ý thiết kế. | `execution_loop.py` (dòng ~305), `verdict_engine.py` | AI đọc mã một mình không đủ để kết luận | Giữ nguyên; nêu rõ là phạm vi | ❌ |
| A7 ⚪ | **Kết quả phản ánh thư viện theo cấu hình của chương trình mẫu.** Ứng dụng thật dùng cấu hình khác có thể hành xử khác. | lệnh chạy `-v 4 -d -g -i` của wolfSSL | Kết luận gắn với một cấu hình cụ thể | Ghi cấu hình vào báo cáo kết quả (đã có cờ biên dịch trong bản kê) | ❌ |

## B. Đầu vào

| # | Hạn chế | Bằng chứng | Ảnh hưởng | Hướng xử lý | Báo cáo 02 |
|---|---|---|---|---|---|
| B1 🔴 | **Đặc tả hành vi viết tay.** Khâu dịch câu RFC sang đặc tả chưa nối vào luồng chính. | báo cáo 02, Bảng 1 | Hệ thống chưa khép kín từ văn bản RFC | Tích hợp tác tử RFC Analyst, đối chiếu với bản tham chiếu | ✅ |
| B2 🔴 | **Chỉ 3 nhóm yêu cầu TLS 1.3**: độ dài bản ghi, loại bản ghi lạ, không có nhóm khoá chung. | `backend/eval/dataset/tiered_benchmark.yaml` | Khó khẳng định hệ thống tổng quát | Mở rộng nhóm yêu cầu | ✅ |
| B3 🔴 | **Chưa có thước đo độ phủ** theo yêu cầu RFC (đã kiểm tra bao nhiêu % câu bắt buộc) và theo mã nguồn (ca thử chạy qua dòng nào). Khối Coverage linker chưa làm. | báo cáo 02, Hình 1; mục E4 | Không trả lời được câu "kiểm thử đã đủ chưa" | Nối RFC Analyst để đếm yêu cầu; đo độ phủ mã khi chạy | ❌ |
| B4 🟡 | **Mỗi lần chỉ biến đổi một trường.** Giá trị thử sinh tự động theo phân tích giá trị biên (biên, giá trị đặc biệt, ngẫu nhiên có hạt giống) nhưng chưa thử tổ hợp nhiều trường. | `backend/src/rfcv/domains/rfc_protocol/spec/oracle_compiler.py` | Bỏ sót lỗi chỉ xuất hiện khi nhiều trường cùng bất thường | Thêm sinh tổ hợp (pairwise) | ❌ |

## C. Các tác tử AI

| # | Hạn chế | Bằng chứng | Ảnh hưởng | Hướng xử lý | Báo cáo 02 |
|---|---|---|---|---|---|
| C1 🔴 | **Giai đoạn chạy thử ở TLS không dùng AI.** Kịch bản dựng từ mẫu có sẵn (19/19 lượt), Planner chạy theo sổ tay luật (30/32 lần). | thống kê `llm_run` trong `runs/real/tier_heldout_gen33_final` | Phần "tác tử" mỏng hơn tên đề tài gợi ý | Trình bày rõ tác tử làm ở đâu; xem C2, C3 | ❌ |
| C2 🟢 | ~~**Planner (LLM) chưa đóng góp.**~~ **Đã xử lý ở `gen-34` (`L4 REMOVE_AGENT`):** tắt gọi Planner LLM mặc định khi `scripted_plans=True` gặp lỗi tác vụ (`planner_llm_fallback=False`), dừng sạch `playbook_stop` và lưu vào `backend/eval/evolution/gene_bank.yaml` để có thể `REINTRODUCE` khi cần. | `backend/eval/evolution/tickets/gen-34.yaml`, `execution_loop.py` | Loại bỏ 100% lệnh gọi Planner LLM trả `output: null` (2/2 trên U8, U13) | Đã xử lý (`gen-34`) | ❌ |
| C3 🟡 | **Tester chưa tự viết kịch bản mới.** Ở HTTP/2 và DNS, Tester chọn mẫu gần nhất, chạy thử trên bản tham chiếu rồi nộp lại đúng mẫu đó. | `proto_http2_mgen1c/run-68c962247359`, sự kiện #7–#26 | Chưa chứng minh tác tử tự thiết kế được kiểm thử | Làm yêu cầu không có mẫu sẵn để Tester phải tự soạn | ❌ |
| C7 🔴 | **Ngôn ngữ kịch bản mới chạy được 5/8 thao tác.** Backend TLS chỉ hỗ trợ `connect`, `complete_handshake`, `send_raw_record`, `send_msg`, `expect`. Các thao tác `mutate`, `reorder`, `repeat` bị từ chối ngay ở bước kiểm tra cú pháp. | `backend/src/rfcv/backends/tlsfuzzer/__init__.py`: `SUPPORTED` | Dù Tester có tự soạn, vẫn chưa kiểm tra được yêu cầu về sửa trường, thứ tự hay lặp gói tin (loại C) | Hiện thực ba thao tác trong runner | ❌ |
| C8 🔴 | **Tính linh hoạt của Tester chưa được chứng minh.** Thiết kế là AI soạn kịch bản rồi máy chạy thử trên bản tham chiếu để kiểm chứng, nhưng chưa có thí nghiệm nào cho Tester soạn kịch bản cho yêu cầu chưa có mẫu. | mục C3; `agents/tester/prompt.md` | Kịch bản thiết lập trước thì không linh hoạt; chưa có số liệu cho thấy AI thay được việc soạn tay | Chọn các yêu cầu không có mẫu, đo tỉ lệ kịch bản do Tester soạn qua được bước kiểm chứng trên bản tham chiếu | ❌ |
| C4 ⚪ | **Verifier chưa làm đổi kết luận nào.** Ở U8 và U13, Verifier yêu cầu kiểm tra thêm, nhưng nhãn vẫn giữ nguyên. | `run-2d549d057d87` sự kiện #60, #109 | Chưa đo được giá trị của vòng phản biện | Làm mẫu cố tình có đường xử lý bị bỏ sót | ❌ |
| C5 🟢 | ~~**Đoạn giải thích do Report (LLM) viết có thể sai.**~~ **Đã xử lý ở `gen-36` (`L3 ADD_STEP`):** bổ sung bước kiểm tra tất định `_check_reaction_consistency` trong `_ExplanationGate.precheck()` (không chạm `output_gate.py` bất biến) để chặn thiếu cặp mã (`ALERT_PAIR_MISSING`) và đảo ngược chiều mã yêu cầu/quan sát (`ALERT_DIRECTION_INVERTED`), kèm kiểm thử đơn vị tái lập lỗi R9. | `backend/eval/evolution/tickets/gen-36.yaml`, `execution_loop.py`, `test_execution_loop.py` | Chặn hoàn toàn lỗi đảo ngược cảnh báo kiểu R9 ngay tại vòng tự sửa của Report | Đã xử lý (`gen-36`) | ❌ |
| C6 🟢 | ~~**Lời nhắc của Code Reader có tên hàm, tên tệp riêng của wolfSSL và OpenSSL.**~~ **Đã xử lý ở `gen-35` (`L2 REMOVE_HARDCODE`):** xoá 100% tên hàm/tệp/macro đặc thù (`DoProcessReplyEx`, `DoServerHello`, `CompleteServerHello`, `tls13_validate_record_header`, `ssl3_read_bytes`, `KEY_SHARE_ERROR`...) khỏi `code_reader/handler.py` và làm trung lập `locate-alert-sites/SKILL.md` (`test_skills_protocol_neutral.py` PASS 100%). *(Ghi chú: cần chạy xác nhận hồi quy trên Docker thực khi bật Docker Desktop.)* | `backend/eval/evolution/tickets/gen-35.yaml`, `code_reader/handler.py`, `locate-alert-sites/SKILL.md` | Lõi Code Reader trung lập hoàn toàn với thư viện và giao thức | Đã xử lý ở mã lõi (`gen-35`); chờ chạy lại Docker hồi quy | ❌ |

## D. Dữ liệu và cách đánh giá

| # | Hạn chế | Bằng chứng | Ảnh hưởng | Hướng xử lý | Báo cáo 02 |
|---|---|---|---|---|---|
| D1 🔴 | **Tập kiểm thử độc lập chỉ có 5 mẫu lỗi**. 5/5 có khoảng tin cậy 95% là 57–100%. | báo cáo 02, Bảng 2 | Con số 100% không vững về thống kê | Mở rộng lên ≥ 15–20 mẫu lỗi | ✅ |
| D2 🔴 | **Lỗi thật rất ít:** 7 mẫu lấy từ lịch sử wolfSSL, trong đó chỉ 3 bản có lỗi. 43 mẫu còn lại là lỗi tự tạo. | `docs/04_evaluation/real_data_report.md` | Kết quả chủ yếu trên lỗi tự tạo | Tìm thêm lỗi thật từ lịch sử commit | ✅ |
| D3 🟡 | **Tập phát triển đã được dùng để chỉnh hệ thống nhiều vòng** (Tầng 2: 6 vòng, Tầng 3: 9 vòng). | báo cáo 02, mục 4.1 | 85,7% có thể cao hơn thực tế | Chỉ dùng tập độc lập để báo cáo con số chính | ✅ |
| D4 🔴 | **Kiểm thử hộp đen cũng kết luận đúng 100%.** Phần "có lỗi hay không" thực chất do kiểm thử chạy thật quyết định; đóng góp riêng của hệ thống là định vị dòng lỗi. | báo cáo 02, Bảng 3 | Không thể nói AI giúp kết luận đúng hơn | Trình bày đúng: đóng góp chính là định vị | ✅ |
| D5 🔴 | **Thiếu hai thí nghiệm đối chứng:** (a) kiểm thử hộp đen + một tác tử đơn đọc mã; (b) bỏ từng thành phần (1 nhánh thay vì 2, bỏ chấm điểm, bỏ dấu hiệu lỗi). | báo cáo 02, mục 4.2 | Chưa tách được phần đóng góp của kiến trúc | Chạy hai thí nghiệm này | ✅ |
| D6 🟡 | **"Định vị đúng" chỉ cần trùng ít nhất một vị trí sửa.** Ở R9, lỗi nằm ở 2 dòng (26216 và 26290), hệ thống chỉ tìm ra một dòng. | `mutants_multi.yaml` mục R9; `run-64c4619f0763` | Con số định vị có thể bị hiểu là "tìm đủ" | Định nghĩa rõ trong báo cáo; thêm chỉ số "tìm đủ mọi vị trí" | ❌ |
| D7 🟡 | **Tốn token hơn tác tử đơn khoảng 1,4–2 lần** (khoảng 118 nghìn so với 60 và 83 nghìn token mỗi mẫu). | báo cáo 02, Bảng 3 | Chi phí cao hơn | Tối ưu ngân sách nhánh | ✅ |
| D8 🟡 | **Một mẫu OpenSSL chưa định vị được**: lệnh gửi cảnh báo bị xoá hẳn trong một hàm dài. Tìm kiếm văn bản tĩnh khó phát hiện kiểu lỗi này. | báo cáo 02, mục 5 | Một loại lỗi chưa xử lý được | Đo độ phủ mã theo dòng giữa ca chạy đạt và ca chạy lỗi | ✅ |
| D9 🔴 | **"0% bỏ sót lỗi" chỉ đúng với TLS.** Ở DNS, lần chạy đầu bỏ sót 1/4 lỗi (5/6 kết luận đúng). Sau khi chỉnh, lần chạy sau đạt 6/6, nhưng trên **cùng 6 mẫu đó**. | `runs/real/proto_dns_mgen2/summary.txt`, `proto_dns_mgen2b/summary.txt` | Có dấu hiệu chỉnh hệ thống theo dữ liệu kiểm tra; khẳng định "0% bỏ sót" không đúng chung cho mọi giao thức | Báo cáo cả lần chạy đầu; làm thêm mẫu DNS mới chưa dùng khi chỉnh | ⚠️ báo cáo ghi "chưa đánh giá" |
| D10 🟡 | **Kết quả HTTP/2 và DNS còn rất ít mẫu, định vị còn yếu.** HTTP/2: 6/6 kết luận đúng, định vị 3/4 (đúng tuyệt đối 2/4). DNS: định vị 2/4. | `proto_http2_mgen1c/summary.txt`, `proto_dns_mgen2b/summary.txt` | Chưa đủ để khẳng định đa giao thức | Mở rộng số mẫu | ⚠️ báo cáo ghi "chưa đánh giá" |
| D12 🔴 | **Khả năng phát hiện bị giới hạn bởi tập biến thể.** Mẫu U5 chỉ gây lỗi ở loại bản ghi 77, trong khi bộ sinh biến thể chỉ thử 0, 99, 255, nên đã bị bỏ sót. Mẫu M4 nằm ngoài dải độ dài của đặc tả, cũng bị bỏ sót. | `docs/04_evaluation/real_data_report.md`, mục 4 | Lỗi nằm ở giá trị ngoài tập biến thể sẽ không bị phát hiện | Mở rộng sinh biến thể (quét miền giá trị, sinh theo dữ liệu); kết hợp phân tích tĩnh | ✅ |
| D13 🔴 | **9 đột biến bị loại khỏi bộ chính**, vì thêm mã mới hoặc vi phạm câu RFC khác câu đang kiểm tra. Trong đó có 2 mẫu (M4, U5) hệ thống từng bỏ sót. | như trên | Lý do loại hợp lý, nhưng làm số liệu đẹp hơn thực tế | Báo cáo kèm danh sách mẫu bị loại; làm tập riêng cho các mẫu này | ✅ |
| D14 🟡 | **Nhãn đột biến wolfSSL chưa được kiểm độc lập bằng thực thi** (OpenSSL đã kiểm). Nhãn do chính người xây dựng hệ thống gán, không có người gán nhãn thứ hai. | như trên, mục 2.3 | Có thể có nhãn sai mà không biết | Chạy trực tiếp bộ kiểm thử trên mọi đột biến wolfSSL; thêm người gán nhãn độc lập | ✅ |
| D11 ⚪ | **Hai con số thời gian lệch nhẹ** so với dữ liệu gốc (10,1 / 81,3 giây trong báo cáo, so với 10,4 / 82,3 giây tính lại). Con số "~35 giây" của kiểm thử hộp đen chưa tìm thấy tệp kết quả gốc. | `b2_baseline_*/matrix.csv` | Nhỏ; nhận định không đổi | Thống nhất số liệu giữa các tài liệu | ❌ |

## E. Kỹ thuật chạy kiểm thử

| # | Hạn chế | Bằng chứng | Ảnh hưởng | Hướng xử lý | Báo cáo 02 |
|---|---|---|---|---|---|
| E1 🟡 | **Ca đối chứng sát ngưỡng thiết kế chưa đúng.** Ở 16 639 và 16 640 byte, cả OpenSSL và GnuTLS đều FAIL. Lý do có thể là runner tạo phần nội dung bên trong vượt giới hạn 2^14+1. Hệ thống đã tự loại các ca này khỏi căn cứ. | `run-64c4619f0763`, bằng chứng #1, sự kiện #12–13, #72–73 | Ca đối chứng mất tác dụng ở sát ngưỡng | Sửa cách runner tạo bản ghi sát ngưỡng | ❌ |
| E2 🟡 | **Bản tham chiếu HTTP/2 là chính nghttp2 bản gốc**, không phải một bản triển khai độc lập. Ở TLS, bản tham chiếu là OpenSSL và GnuTLS, thay cho rustls như thiết kế ban đầu. | `docker_launcher.py`: `nghttp2-ref`; `docker/eval-ref.Dockerfile` | Đối chứng HTTP/2 yếu hơn TLS | Thêm một máy chủ HTTP/2 độc lập làm tham chiếu | ❌ |
| E3 ⚪ | **Kết quả tham chiếu lấy từ bộ nhớ đệm** của lượt chạy trước, khoá là mã băm image. | `cache_hit: true` trong trace | Hợp lệ, nhưng cần nói rõ khi bị hỏi | — | ❌ |
| E4 🟡 | **Chưa thu gói tin (pcap) và chưa đo độ phủ mã.** Chỉ lưu nhật ký server và kết quả quan sát. Mức bảo đảm cao nhất hiện là `BEHAVIORAL`. | `docker_launcher.py`: tham số `coverage` bị bỏ qua | Không liên kết được ca chạy với dòng mã đã chạy | Dựng image có đo độ phủ | ❌ |
| E5 ⚪ | **Client và server chạy chung một container**, chia chung giới hạn CPU và bộ nhớ. | `docker_launcher.py`, phần docstring | Có thể ảnh hưởng thời gian phản hồi | Tách thành 2 container nối mạng nội bộ | ❌ |
| E6 ⚪ | **Các lần chạy lại chỉ khác tên máy**, chưa đổi đồng hồ hệ thống. | `docker_launcher.py`, phần docstring | Chưa phát hiện được lỗi phụ thuộc thời gian | Dùng libfaketime hoặc máy ảo | ❌ |
| E7 ⚪ | **Docker không phải ranh giới bảo mật tuyệt đối**, vì container dùng chung nhân hệ điều hành với máy chủ. | — | Chỉ nên nói "giảm rủi ro" | Dùng gVisor hoặc máy ảo nếu cần | ❌ |
| E8 ⚪ | **GnuTLS cho FAIL ở loại bản ghi 255** (mẫu U13), trong khi OpenSSL PASS. | `run-2d549d057d87` | Hai bản tham chiếu bất đồng ở một ca | Xem lại kịch bản loại bản ghi 255 | ❌ |

## F. Vòng tiến hoá

| # | Hạn chế | Bằng chứng | Ảnh hưởng | Hướng xử lý | Báo cáo 02 |
|---|---|---|---|---|---|
| F1 🟡 | **Tiến hoá đi theo lối mòn** *(đã khởi động giải quyết ở `gen-34`–`gen-36`)*. Đã triển khai công cụ chẩn đoán triệu chứng tự động `evol_diagnose.py` (L0–L6), Ngân hàng Gen (`gene_bank.yaml`) và thực thi 3 phép đột biến khác nhau (`L4 REMOVE_AGENT`, `L2 REMOVE_HARDCODE`, `L3 ADD_STEP`). Còn cần mở rộng thêm đường đua mới (F3) và đồ thị quy trình dữ liệu (F4). | `backend/scripts/evol_diagnose.py`, `backend/eval/evolution/innovation_log.md` | Đã chứng minh đột biến đa mức (gỡ tác tử, gỡ mã cứng, thêm cổng bước) | Tiếp tục mở rộng sang F3, F4 theo `evolution_mutation_design.md` | ❌ |
| F2 🟢 | ~~**Không ghi rõ mỗi generation đã thay đổi gì.**~~ **Đã xử lý:** áp dụng Phiếu tiến hoá YAML (`backend/eval/evolution/tickets/gen-*.yaml`), harness kiểm chứng tự động `evol_check_ticket.py` (so `declared_matches_diff` với `git diff` + chặn chạm bất biến) và Nhật ký đổi mới (`innovation_log.md`). | `backend/scripts/evol_check_ticket.py`, `backend/eval/evolution/tickets/gen-34..36.yaml` | Mọi thế hệ từ `gen-34` đều có phiếu, kiểm chứng diff và nhật ký truy vết | Đã xử lý | ❌ |
| F3 🟡 | **Bộ đo chỉ có một đường đua:** mã hoàn chỉnh, chạy được, có adapter. | `backend/eval/dataset/tiered_benchmark.yaml` | Chiến lược cho tình huống khác không bao giờ được thưởng | Thêm đường đua, mỗi đường đua có tập kiểm thử độc lập riêng | ❌ |
| F4 🟡 | **Cấu trúc hệ thống chưa mô tả bằng dữ liệu.** Luồng xử lý nằm trong `execution_loop.py`, chỉ có một chiến lược viết cứng. | `backend/src/rfcv/core/execution_loop.py` | Đột biến thêm, xoá, thay bước hoặc thêm chiến lược đòi sửa mã lõi | Đồ thị quy trình mô tả bằng dữ liệu + khuôn chung cho chiến lược | ❌ |

---

## Việc cần làm với báo cáo 02

Các mục 🔴 chưa có trong báo cáo, nên bổ sung vào phần **Hạn chế**: A1, A3, B3, C1, C2, C5, C6, C7, C8, D9.

Báo cáo đang ghi HTTP/2 và DNS là "chưa đánh giá". Cần cập nhật theo D9 và D10, và **nêu cả lần chạy DNS đầu tiên bị bỏ sót lỗi**.

# Đúc kết 10 thế hệ tiến hoá có kiểm toán (`gen-34` → `gen-43`)

- **Ngày lập:** 26/11/2026
- **Phạm vi:** 10 thế hệ tiến hoá liên tiếp từ `gen-34` đến `gen-43` trên nhánh `feat/multi-protocol-eval` (mốc `v1.0-tls13-graduated` → `v2.0-stage-a-complete` → `v2.1-stage-b-complete`).
- **Nguồn kiểm chứng:** [innovation_log.md](../../backend/eval/evolution/innovation_log.md), [gene_bank.yaml](../../backend/eval/evolution/gene_bank.yaml), [han_che_he_thong.md](../05_project/han_che_he_thong.md), các phiếu `backend/eval/evolution/tickets/gen-34..43.yaml`.

---

## 1. Bức tranh tổng quan (10 thế hệ, 0 vi phạm bất biến)

| Mốc | Thế hệ | Mức & Phép đột biến | Hạn chế xử lý | Kết quả xác minh thực tế |
|---|---|---|---|---|
| Chặng A | `gen-34` | `L4 REMOVE_AGENT` | `C2` | Gỡ `Planner LLM` gen lặn (trước đó `output=null` 2/2 = 100%), lưu `gene_bank.yaml`, giữ nguyên tương thích `toy_domain`. |
| Chặng A | `gen-35` | `L2 REMOVE_HARDCODE` | `C6` | Xoá 100% tên hàm/tệp/macro wolfSSL & OpenSSL; hồi quy Docker **`4/4 ALL STRICT`** trên 4 thư viện C. |
| Chặng A | `gen-36` | `L3 ADD_STEP` | `C5` | Thêm `_check_reaction_consistency` vào `_ExplanationGate.precheck()` (không sửa `output_gate.py`); `R9` hết đảo cảnh báo. |
| Chặng A | `gen-37` | `L6 ADD_CAPABILITY` | `A2` | `specs_from_adapter()` tự nạp lệnh/cổng/giao vận từ `sut/*.yaml` (thêm thư viện mới không sửa launcher). |
| Chặng A | `gen-38` | `L6 ADD_STRATEGY` | `D12` | Chiến lược hai chiều **Code-First → Targeted Verify**: lật ngược `U5` (`type == 77`) thành **`VIOLATION (V2)` + `ALL STRICT`**. |
| Chặng A | `gen-39` | `L6 EVAL_HELDOUT` | `D10` | Xác minh đủ **5 giao thức trên Docker thật** (`3 Dev`: TLS, HTTP/2, DNS → `2 Held-out` lõi đóng băng: SSH `Dropbear` `4/4`, QUIC `ngtcp2` `4/4`). |
| Chặng A | `gen-40` | `L2 ABLATION_STUDY` | `D5` | Ablation 6 ca OpenSSL: `C0` **`100% STRICT`** (CI `61–100%`) vs `A1`/`A2` **`16,7% STRICT`** (CI `3–56%`). |
| Chặng A | `gen-41` | `L2 EVAL_ZERO_TEMPLATE` | `C3, C8` | Xoá sạch `templates/` (0 mẫu): `Tester LLM` tự soạn đạt **`5/5 = 100%`** trên 4 giao thức (`0` gate reject). |
| Chặng B | `gen-42` | `L6 ADD_CAPABILITY` | `C7` | Hoàn thiện **`8/8` thao tác DSL** cho `tlsfuzzer` (`mutate`, `reorder`, `repeat`), xác minh chạy thật trên OpenSSL Docker. |
| Chặng B | `gen-43` | `L6 ADD_CAPABILITY` | `E4, D8` | Thu **`192 KB` LCOV thật** trong Docker `--read-only`; `ngtcp2_accept:10230` (`linked=True`) tách sạch khỏi `conn_recv_pkt:6108` (`linked=False`). |

---

## 2. Điều hay (Các bài học kiến trúc & thực nghiệm nên giữ làm xương sống)

1. **Đóng góp của hệ thống nằm ở kiến trúc phối hợp, không phải ở kích thước LLM (`gen-40`):**
   Trên cùng một mô hình nhỏ (`DeepSeek-V4-Flash`) và cùng dữ liệu T3, việc bỏ giải đấu 2 nhánh chuyên biệt + chấm điểm nguồn `obs_in_source` làm tỉ lệ định vị nghiêm ngặt rơi từ **`100,0%`** xuống **`16,7%`** (khoảng tin cậy Wilson 95% hoàn toàn không giao nhau).
2. **Tổng quát hoá thật khi gỡ sạch mã cứng (`gen-35`, `gen-39`):**
   Gỡ 100% tên hàm/tệp đặc thù wolfSSL & OpenSSL không làm giảm độ chính xác (`4/4 ALL STRICT` trên 4 thư viện C khác nhau), và kết luận đạt `100%` trên cả 2 giao thức Held-out chưa từng thấy (SSH `Dropbear`, QUIC `ngtcp2`) với lõi đóng băng.
3. **Kết hợp hai chiều `Test-First + Code-First → Verify` mở khoá lớp lỗi mới mà không phá an toàn (`gen-38`):**
   Thay vì truyền lập luận tự do của `Code Reader` sang `Tester` (vi phạm IFC), chỉ truyền một kênh hẹp tất định các hằng số nhánh trích từ mã (`code_probe.py`) rồi bắt buộc chạy qua `TestDriver` + `witness_positive` + `VerdictEngine`. Cách này lật ngược được điểm mù kinh điển `U5` (`type == 77`) với **0% báo động giả**.
4. **Tính linh hoạt của tác tử kiểm thử là có thật (`gen-41`):**
   Khi xoá hoàn toàn `templates/`, `Tester LLM` vẫn tự đọc RBS + mô tả DSL để quyết định có cần `complete_handshake` hay không, tự dùng `mutate` cho DNS và `send_raw_record` cho TLS/HTTP2/QUIC, đạt `5/5 = 100%` không bị từ chối ở cổng kiểm tra.
5. **Đo độ phủ nhân quả hoạt động được cả trong sandbox cứng hoá (`gen-43`):**
   Dùng `GCOV_PREFIX=/tmp/gcov` + bắt `SIGTERM` để xả `.gcda` giúp thu LCOV thật ngay trên container `--read-only`, nâng mức bảo đảm từ `BEHAVIORAL` lên **`LINKED`** và giải quyết trực tiếp bài toán đa điểm kiểm tra trùng.
6. **Quy trình tiến hoá có kiểm toán ngăn "chỉnh tay theo cảm tính" (`gen-34..43`):**
   Mỗi thế hệ đều có phiếu YAML + `evol_check_ticket.py` đối chiếu `declared_matches_diff` với `git diff` + khoá 7 vùng bất biến + Ngân hàng Gen (`gene_bank.yaml`). Mọi bước lùi hay mở rộng đều truy vết được và tái lập được qua 3 git tag.

---

## 3. Điều dở & Bẫy thực tế đã gặp (Bài học rút kinh nghiệm cho sau này)

1. **Gỡ tác tử (`L4 REMOVE_AGENT`) dễ phá tính tổng quát miền nếu thiếu test đa miền (`gen-34`):**
   - *Hiện tượng:* Tắt `Planner LLM` cho mọi trường hợp `scripted_plans=True` làm `rfc_protocol` PASS 100% nhưng làm FAIL `3` test của miền độc lập `toy_domain` (vì miền mới chưa có sổ tay tất định ở vòng đầu).
   - *Bài học:* Phép `REMOVE_AGENT` phải thu hẹp đúng điều kiện phát sinh triệu chứng (`any(h.get("failure") for h in history)`), luôn chạy full regression đa miền và lưu thành phần bị gỡ vào `gene_bank.yaml`.
2. **Chống "bịa bằng chứng" là chưa đủ — LLM vẫn có thể *nói ngược bằng chứng* (`gen-36`):**
   - *Hiện tượng:* `Report` trích đúng `evidence_id` và nhãn `VIOLATION`, nhưng đảo ngược `expected_alert` với `observed_alert` (`R9`). Khi viết regex chặn, từ khoá `expect` lại khớp nhầm vào bên trong tên cảnh báo `un**expect**ed_message`.
   - *Bài học:* Mọi kiểm tra ngữ nghĩa bằng regex trên văn bản phải gắn ranh giới từ (`\b`), ngắt tại mệnh đề đối lập (`nhưng`, `còn`, `thay vì`), và có unit test với cả ca sai lẫn ca đúng chứa từ trùng âm.
3. **Đột biến tự tạo có thể thành đột biến tương đương nếu không kiểm thực thi trước (`gen-39`):**
   - *Hiện tượng:* `S1, S2` trên Dropbear sửa dòng 139 (`!authdone && type > MAX_UNAUTH_PACKET_TYPE`), nhưng khi gửi gói trước KEX thì kiểm tra `requirenext` phía trên đã ngắt kết nối trước → đột biến trở thành tương đương.
   - *Bài học:* Mọi đột biến mới đưa vào benchmark phải qua bước xác minh thực thi độc lập (`D14`) trước khi gán nhãn `VIOLATION`.
4. **Hạn chế bộ phân tích cú pháp `tree-sitter` với C kiểu K&R có `#ifdef` (`gen-39`):**
   - *Hiện tượng:* Trên `S3` (`Dropbear`), `Code Reader` tìm đúng dòng đột biến `src/common-kex.c:[888, 891]` nhưng `SchemaGate` từ chối `LINES_OUTSIDE_SYMBOL` vì `tree-sitter` cắt thiếu biên hàm `static void read_kex_algos()`.
   - *Bài học:* Với mã nguồn C cũ nhiều macro điều kiện, cần cải thiện hoặc bổ sung cơ chế dự phòng tìm biên hàm (brace-matching) cho `CodeIndex`.
5. **Bẫy đa điểm kiểm tra trùng trên thư viện lớn (`gen-39` → giải ở `gen-43`):**
   - *Hiện tượng:* `ngtcp2` kiểm `NGTCP2_MAX_UDP_PAYLOAD_SIZE` ở cả `conn_recv_pkt:6109` và `ngtcp2_accept:10230`; tìm kiếm tĩnh một chiều dễ dừng ở điểm đầu tiên dù hàm đó chưa hề chạy.
   - *Bài học:* Khi có LCOV (`gen-43`), cần đưa `executed_in_fail` thành tín hiệu ưu tiên cao trong `select_branch()` để loại ngay các nhánh không thực thi.
6. **Các bẫy hạ tầng nhỏ nhưng tốn thời gian gỡ lỗi (`gen-39`, `gen-43`):**
   - Đặt `socket.settimeout(within_ms / 1000.0)` cho phản ứng `discard` tạo độ trễ biên `1001ms > 1000ms` làm bản tham chiếu FAIL ngẫu nhiên → luôn đặt timeout nhỏ hơn `within_ms` một khoảng an toàn (vd `-150ms`).
   - Khi ghi đè `docker_cmd` cho SUT trong `specs_from_adapter()`, phải đồng bộ cả `<impl>-ref`.
   - Khác biệt phiên bản công cụ trong Debian Bookworm (`lcov 1.16` không hỗ trợ cờ `--ignore-errors unused` của `lcov 2.x`).

---

## 4. Bộ quy tắc tái sử dụng cho các thế hệ tiếp theo (`gen-44+`)

1. **Chẩn đoán trước, đột biến sau:** Chạy `evol_diagnose.py` trên trace thật để xác định triệu chứng rõ ràng rồi mới chọn phép đột biến (`L0–L6`), không chỉnh theo cảm tính.
2. **Một phiếu — một trách nhiệm — một kiểm toán diff:** Luôn chạy `evol_check_ticket.py --base HEAD --record` trước khi commit; không bao giờ chạm 7 tệp bất biến.
3. **Bảo vệ đa miền & lưu Ngân hàng Gen:** Mọi phép gỡ/thay thành phần (`L4/L5`) phải qua full suite (gồm `toy_domain` và `test_skills_protocol_neutral.py`) và ghi hồ sơ khôi phục vào `gene_bank.yaml`.
4. **Kiểm chứng thực tế trên Docker & báo cáo trung thực cả ca lỗi/tương đương:** Không loại bỏ im lặng các ca thất bại hoặc đột biến tương đương; ghi rõ nguyên nhân gốc để làm đầu vào cho thế hệ kế tiếp.

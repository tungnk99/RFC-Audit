# Thiết kế đột biến đa dạng cho vòng tiến hoá

- **Ngày:** 23/11/2026
- **Trạng thái:** đề xuất, chưa hiện thực
- **Lưu ý phạm vi:** tài liệu được viết mà không đọc mã trong `evolver/` (bị `CLAUDE.md` cấm). Mô tả "hiện trạng" dựa trên các báo cáo đã có: Gen-9 → Gen-18 → Gen-28..33. Trước khi hiện thực, cần đối chiếu lại với mã thật của `evolver/`.

---

## 1. Vấn đề: tiến hoá đi theo lối mòn

Theo các báo cáo, mọi cải tiến từ Gen-9 đến Gen-33 đều nằm trong **cùng một luồng**: chạy thử → lấy dấu hiệu lỗi → Code Reader định vị. Các thay đổi chỉ gồm thêm nhánh, chỉnh lời nhắc, chỉnh ngân sách, thêm công cụ. Không generation nào tạo ra một cách tiếp cận khác, chẳng hạn duyệt mã trước khi chạy, so sánh chéo giữa các bản triển khai, thêm hoặc bớt tác tử, hay đổi cách các tác tử phối hợp.

Các nguyên nhân có thể:

| Nguyên nhân | Hệ quả |
|---|---|
| Bộ đo chỉ có một loại tình huống: mã hoàn chỉnh, chạy được, đã có adapter | Chiến lược cho tình huống khác không bao giờ được thưởng |
| Chọn lọc chỉ giữ bản có điểm trung bình cao nhất | Chiến lược mới, lúc đầu điểm thấp, bị loại ngay |
| Đề bài cho mutator luôn dạng "ca X sai, hãy sửa" | Thay đổi chỉ là bản vá cục bộ |
| Mutator luôn có cùng một góc nhìn: cùng mô hình, cùng lời nhắc | Ý tưởng lặp lại |
| Phạm vi mặc định chỉ cho sửa lời nhắc và cấu hình (Tier 1) | Không thể thay đổi cấu trúc |
| Không ghi lại những ý tưởng đã thử và thất bại | Thử lại ý tưởng cũ |

---

## 2. Bảng phân loại thay đổi: 7 mức, các phép đột biến

| Mức | Đối tượng | Phép đột biến |
|---|---|---|
| **L0 · Tham số** | ngân sách, ngưỡng, số nhánh, số lần chạy lại | `TUNE` |
| **L1 · Một tác tử** | lời nhắc, kỹ năng | `EDIT_PROMPT`, `ADD_SKILL`, `REMOVE_SKILL`, `REWRITE_SKILL` |
| **L2 · Công cụ** | công cụ tác tử được dùng | `ADD_TOOL`, `MODIFY_TOOL`, `REMOVE_TOOL`, `GRANT_TOOL`, `REVOKE_TOOL` |
| **L3 · Bước xử lý** | luồng xử lý | `ADD_STEP`, `REMOVE_STEP`, `REPLACE_STEP`, `REORDER_STEPS`, `PARALLELIZE`, `ADD_LOOP` (thêm vòng lặp có điều kiện dừng) |
| **L4 · Tác tử** | thành phần của nhóm tác tử | `ADD_AGENT`, `REMOVE_AGENT`, `SPLIT_AGENT`, `MERGE_AGENTS`, `CHANGE_ROLE`, `CHANGE_MODEL` |
| **L5 · Tổ chức nhóm tác tử** | cách phối hợp | `CHANGE_COORDINATION` (tuần tự / song song / tranh luận / phản biện), `CHANGE_SELECTION` (cách chọn nhánh), `CHANGE_ROUTER` (bộ chọn chiến lược) |
| **L6 · Chiến lược tiếp cận** | cách tiếp cận bài toán | `ADD_STRATEGY`, `CROSSOVER` (lai ghép hai chiến lược), `INVERT` (đảo thứ tự tiếp cận), `RETIRE_STRATEGY` |
| **Mọi mức** | thành phần đã bị loại trước đây | `REINTRODUCE`: đưa lại từ ngân hàng gen (mục 3.7) |

**Không bao giờ được đột biến, ở mọi mức:** bộ quy tắc V0–V9, các lớp kiểm tra cố định (Schema gate, Code gate), kho bằng chứng nối chuỗi băm, ranh giới vùng tin cậy (IFC), bộ quét rò rỉ.

### Danh mục chiến lược khởi đầu (đầu vào cho L6)

| Chiến lược | Ý tưởng | Đường đua phù hợp |
|---|---|---|
| Chạy thử → định vị | luồng hiện tại | mã hoàn chỉnh |
| Duyệt mã theo điểm neo | rút điểm neo từ đặc tả (tên trường, hằng số có giá trị bằng ngưỡng, mã phản ứng), tìm theo đồ thị gọi, đối chiếu điều kiện, ngưỡng, phản ứng | mã chưa hoàn chỉnh |
| Tĩnh đề xuất, động xác nhận | đọc mã tìm chỗ nghi ngờ, rồi sinh một ca thử nhắm đúng chỗ đó | cả hai |
| So sánh chéo giữa các bản triển khai | gửi nhiều đầu vào cho nhiều bản triển khai; chỗ chúng trả lời khác nhau thì đáng nghi | có nhiều bản triển khai |
| Chạy riêng một hàm | gọi thẳng hàm cần kiểm tra với giá trị biên | mã chưa chạy được toàn bộ |
| Định vị theo độ phủ | so các dòng mã được chạy ở ca PASS và ca FAIL | mã hoàn chỉnh, có đo độ phủ |
| Duyệt theo bản vá | chỉ đối chiếu những dòng vừa thay đổi với yêu cầu RFC | mã đang phát triển |
| Truy vấn tĩnh kiểm chứng bằng đột biến | bằng chứng T2, quy tắc V8 | yêu cầu nội bộ |
| Học máy trạng thái | cho yêu cầu về thứ tự thông điệp (quy tắc V3) | yêu cầu loại C |

---

## 3. Chọn đột biến có chiến lược, không ngẫu nhiên

Mỗi đột biến tốn một lượt đánh giá đầy đủ: chạy Docker, gọi LLM, có khi mất hàng chục phút. Chọn ngẫu nhiên thì phần lớn lượt đánh giá bị phí. Vì vậy việc chọn đột biến đi theo một quy trình **chẩn đoán → đề xuất → chấm điểm → chọn → nâng mức nếu không hiệu quả**. Khám phá ngẫu nhiên chỉ chiếm một phần nhỏ ngân sách, và cũng phải có định hướng (mục 3.0.5).

### 3.0.1. Bước 1: Chẩn đoán từ nhật ký

Nhật ký (`trace.db`) của mỗi lượt chạy đã ghi đủ dữ liệu để chẩn đoán tự động, không cần đoán. Bộ chẩn đoán đọc nhật ký của mọi ca trong mọi đường đua và rút ra **triệu chứng**, mỗi triệu chứng kèm số ca bị ảnh hưởng và bằng chứng:

| Triệu chứng | Dấu hiệu trong nhật ký |
|---|---|
| Định vị đúng vùng, sai dòng | `defect_hit` sai nhưng cùng hàm với đáp án |
| Tác tử bám hướng sai | nhiều lần gọi công cụ trong vùng không liên quan; hết ngân sách |
| Đầu ra bị lớp kiểm tra từ chối nhiều lần | `output_retry` với cùng một mã lỗi (ví dụ `LINES_NOT_SHOWN`) |
| Kịch bản không chạm điểm kích hoạt | `trigger_reached = false`, nhiều ca ERROR |
| Không thu được bằng chứng | dừng với lý do `INFEASIBLE`, nhãn `UNVERIFIABLE` |
| Tác tử trả rỗng | `role_run.output = null` (ví dụ Planner ở U8, U13) |
| Hai nhánh làm trùng việc | hai nhánh nộp cùng vị trí, tốn gấp đôi token |
| Một tác tử phải lo quá nhiều việc | lỗi của tác tử đó rải ra nhiều kiểu khác nhau |
| Kết quả đúng nhưng tốn kém | token hoặc thời gian vượt mức trung vị nhiều lần |
| Diễn giải sai | đoạn giải thích không khớp cảnh báo mong đợi và cảnh báo quan sát được (ví dụ R9) |
| Dậm chân tại chỗ | k generation liên tiếp không cải thiện trên một đường đua |
| Mạnh ở hai nơi khác nhau | hai bản đang giữ giỏi ở hai đường đua khác nhau |

### 3.0.2. Bước 2: Từ triệu chứng ra các đột biến ứng viên

Mỗi triệu chứng có danh sách đột biến ứng viên, **xếp từ mức rẻ đến mức đắt**:

| Triệu chứng | Ứng viên (rẻ → đắt) |
|---|---|
| Định vị đúng vùng, sai dòng | L1 sửa kỹ năng đối chiếu → L2 công cụ chính xác hơn → L3 thêm bước rà lại vùng hẹp |
| Tác tử bám hướng sai | L0 giảm ngân sách mỗi nhánh → L3 thêm bước dừng sớm → L5 thêm nhánh chiến lược khác |
| Bị từ chối nhiều lần, cùng mã lỗi | L1 thêm ví dụ định dạng → L2 công cụ trả sẵn dữ liệu cần trích |
| Kịch bản không chạm kích hoạt | L1 sửa lời nhắc Tester → L3 thêm bước chạy thử trên bản tham chiếu → L2 thêm thao tác cho ngôn ngữ kịch bản |
| Không thu được bằng chứng | **L6 thêm chiến lược** không cần chạy (duyệt mã theo điểm neo, chạy riêng một hàm) |
| Tác tử trả rỗng | L1 sửa lời nhắc, lược đồ → L4 bỏ tác tử, thay bằng luật |
| Hai nhánh làm trùng việc | L5 đổi cách chọn nhánh → L4 gộp tác tử |
| Một tác tử lo quá nhiều việc | L4 tách tác tử |
| Đúng nhưng tốn kém | L0 chỉnh ngân sách → L3 bỏ bước, kiểm tra kết quả không giảm |
| Diễn giải sai | L3 thay bước sinh giải thích bằng khuôn mẫu, hoặc thêm bước kiểm tra giải thích |
| Dậm chân tại chỗ | **nâng mức bắt buộc:** L4–L6, `INVERT` |
| Mạnh ở hai nơi khác nhau | `CROSSOVER` |

Bảng này là **dữ liệu**, không viết cứng trong mã. Bản thân bảng cũng được cập nhật theo kết quả (mục 3.0.4).

### 3.0.3. Bước 3: Chấm điểm và chọn ứng viên

Mỗi ứng viên được chấm theo bốn yếu tố:

```
ưu tiên = (tác động × khả năng thành công) / chi phí + thưởng mới lạ
```

| Yếu tố | Cách tính |
|---|---|
| **Tác động** | số ca bị ảnh hưởng bởi triệu chứng × trọng số đường đua (đường đua chưa có lời giải có trọng số cao) |
| **Khả năng thành công** | tỉ lệ thành công lịch sử của phép này **trên cùng loại triệu chứng**. Phép chưa từng thử nhận giá trị mặc định trung bình (khởi đầu kiểu bandit) |
| **Chi phí** | mức càng cao càng đắt (L0 rẻ nhất, L6 đắt nhất); cộng thêm rủi ro chạm vào vùng gần bất biến |
| **Thưởng mới lạ** | phép hoặc ý tưởng chưa có trong quần thể và không nằm trong danh sách cấm |

Chọn ứng viên có điểm ưu tiên cao nhất. Phiếu tiến hoá phải ghi **triệu chứng nào, các ứng viên đã xét, điểm của từng ứng viên, vì sao chọn ứng viên này**.

### 3.0.4. Bước 4: Nâng mức khi không hiệu quả

- Bắt đầu từ ứng viên rẻ nhất có điểm đủ cao.
- Nếu cùng một triệu chứng đã thử **n lần ở một mức** mà không cải thiện, thì **nâng lên mức kế tiếp** cho triệu chứng đó.
- Nếu một đường đua dậm chân k generation, thì **bắt buộc** đột biến từ L4 trở lên, hoặc `INVERT`, `CROSSOVER`.
- Kết quả mỗi lần thử được ghi ngược vào bảng ở mục 3.0.2: phép nào hay thành công với triệu chứng nào. Nhờ vậy bộ chọn **tự học** cách chọn tốt hơn qua các generation.

### 3.0.5. Khám phá có định hướng (phần nhỏ ngân sách)

Để không bỏ lỡ hướng mà bảng chẩn đoán chưa nghĩ tới, khoảng **10–20% số generation** dành cho khám phá. Nhưng khám phá cũng không chọn đều ngẫu nhiên:
- chọn **phép ít được dùng nhất** trong những phép **có liên quan** tới đường đua đang yếu;
- hoặc lấy ý tưởng từ **nguồn tài liệu** (phương pháp đã công bố chưa được áp dụng);
- hoặc giao cho **mutator góc nhìn khác hẳn** góc nhìn của bản tốt nhất hiện tại.

### 3.1. Chọn phép đột biến trước, rồi mới giao cho mutator

Thay vì đề bài "ca X sai, hãy sửa", bộ lập lịch **chọn mức và phép đột biến trước**, rồi giao đề bài theo phép đó. Ví dụ: *"Áp dụng `SPLIT_AGENT` cho Code Reader để cải thiện đường đua mã chưa hoàn chỉnh"*. Nhờ vậy, góc nhìn của mutator bị dẫn sang hướng khác.

### 3.2. Đa dạng nguồn ý tưởng

Mỗi generation ghi rõ ý tưởng đến từ đâu. Bộ lập lịch luân phiên các nguồn:

| Nguồn | Câu hỏi đặt cho mutator |
|---|---|
| Từ ca thất bại | "Vì sao ca này sai? Sửa thế nào?" (hiện tại) |
| Từ chi phí | "Ca này đúng nhưng tốn kém. Bớt được bước nào?" |
| Từ khoảng trống | "Đường đua này chưa có chiến lược nào giải được. Cần cách tiếp cận gì?" |
| Từ tài liệu | "Phương pháp X trong công trình Y áp dụng vào đây thế nào?" |
| Đơn giản hoá | "Xoá hoặc gộp một bước, một tác tử mà kết quả không giảm" (chống phình to) |
| Đảo giả định | "Nếu bỏ chạy thử thì sao? Nếu Tester chạy sau Code Reader thì sao?" |
| Lai ghép | "Kết hợp điểm mạnh của hai bản đang giữ ở hai ô khác nhau" |
| Khám phá ngẫu nhiên | chọn ngẫu nhiên một phép đột biến ít được dùng |

### 3.3. Nhiều "góc nhìn" cho mutator

Dùng nhiều mutator với vai trò khác nhau, có thể thêm khác mô hình hoặc khác nhiệt độ sinh:
- **kỹ sư kiểm thử:** thiên về kịch bản và giá trị thử;
- **chuyên gia phân tích tĩnh:** thiên về đọc mã và truy vấn;
- **kiến trúc sư hệ đa tác tử:** thiên về L4–L5;
- **người tối giản:** chỉ được phép xoá hoặc gộp;
- **người phản biện:** tìm điểm yếu của bản tốt nhất hiện tại.

### 3.4. Lập lịch có ép đa dạng

- **Hạn mức theo mức:** ví dụ sau 5 generation liên tiếp ở L0–L1, generation tiếp theo **bắt buộc** từ L3 trở lên.
- **Bandit (UCB):** phép đột biến nào hay thành công thì được chọn nhiều hơn, nhưng mọi phép đều giữ một xác suất tối thiểu.
- **Ưu tiên khoảng trống:** đường đua nào chưa có chiến lược giải được thì được ưu tiên.

### 3.5. Danh sách cấm lặp và điểm mới lạ

- Mỗi đột biến có một **chữ ký**: mức + phép + đối tượng + tóm tắt ý tưởng.
- Ý tưởng đã thử và thất bại được đưa vào **danh sách cấm** trong một số generation.
- **Điểm mới lạ:** đột biến càng khác với các bản đang giữ thì càng được cộng điểm khi chọn lọc.

### 3.6. Chọn lọc giữ đa dạng (quality-diversity)

Chia các bản thành **ô** theo đặc điểm: chế độ tiếp cận, các loại bằng chứng dùng, mức chi phí, những đường đua giải được. **Mỗi ô giữ bản tốt nhất của ô đó** (kiểu MAP-Elites). Một chiến lược lạ, giải được ca mà không bản nào khác giải được, sẽ được giữ lại dù điểm trung bình thấp.

### 3.7. Loại bỏ gen lặn

Qua nhiều generation, hệ thống tích tụ những thành phần **không còn đóng góp**, gọi là gen lặn. Chúng làm tốn token, chậm, khó hiểu, và che mất nguyên nhân thật của kết quả. Tiến hoá phải biết **phát hiện và loại bỏ** chúng, chứ không chỉ thêm vào.

**Các loại gen lặn:**

| Loại | Ví dụ | Cách phát hiện từ nhật ký |
|---|---|---|
| Thành phần không bao giờ được dùng | công cụ, kỹ năng không ai gọi; luật trong sổ tay không bao giờ khớp; quy tắc V không bao giờ kích hoạt | đếm số lần dùng trên mọi đường đua = 0 |
| Được gọi nhưng không đóng góp | Planner (LLM) trả rỗng cả 2 lần được gọi (U8, U13), hệ thống phải dùng luật dự phòng | đầu ra rỗng, bị bỏ qua, hoặc luôn bị thay bằng luật |
| Có chạy nhưng không đổi kết quả | vòng phản biện chưa làm đổi kết luận nào | bỏ thử thành phần đó (ablation): kết quả không đổi trên **mọi** đường đua |
| Đi nhờ | thay đổi vô ích được gộp chung với một thay đổi có ích trong cùng generation | thí nghiệm bỏ từng thay đổi (mục 4, kiểm tra phiếu) |
| Trùng lặp | hai nhánh hoặc hai tác tử luôn cho cùng một kết quả | so sánh đầu ra giữa các thành phần |
| Gợi ý quá khớp | tên hàm riêng của wolfSSL, OpenSSL viết cứng trong lời nhắc (sổ hạn chế, mục C6) | đóng góp biến mất trên đường đua "thư viện chưa từng thấy" |

**Quy trình:**

1. **Theo dõi đóng góp.** Với mỗi thành phần (tác tử, bước, công cụ, kỹ năng, câu lời nhắc, luật), ghi số lần được dùng và tác động lên kết quả, theo từng đường đua.
2. **Đề cử loại bỏ.** Thành phần nào có ít lần dùng, hoặc đầu ra rỗng, hoặc có dấu hiệu trùng lặp, thì được đưa vào danh sách đề cử. Mỗi đề cử thành một triệu chứng trong mục 3.0.1, với ứng viên là `REMOVE_STEP`, `REMOVE_AGENT`, `REMOVE_TOOL`, `REMOVE_SKILL`, `MERGE_AGENTS`.
3. **Thử bỏ trên mọi đường đua và tập độc lập.** Chỉ loại khi kết quả **không giảm ở bất kỳ đường đua nào**, đồng thời chi phí giảm.
   - **Cẩn thận:** một thành phần lặn ở đường đua này có thể trội ở đường đua khác. Ví dụ Verifier chỉ có tác dụng ở các ca kết luận *Tuân thủ*, và với mã chưa hoàn chỉnh. Vì vậy không được loại chỉ dựa trên một đường đua.
4. **Lưu vào ngân hàng gen**, không xoá vĩnh viễn. Thành phần bị loại được lưu lại cùng lý do. Khi xuất hiện đường đua mới hoặc tình huống mới, bộ chọn đột biến có thể **đưa lại** (`REINTRODUCE`) nếu triệu chứng phù hợp.
5. **Ép định kỳ.** Ví dụ cứ k generation thì có một generation **chỉ được bỏ hoặc gộp** (vai trò "người tối giản" ở mục 3.3). Mục đích là giữ hệ thống gọn, tránh việc chỉ thêm mà không bao giờ bớt.

**Tiêu chí chọn lọc có tính đến độ gọn:** khi hai bản cho kết quả ngang nhau, ưu tiên bản **ít thành phần hơn và rẻ hơn**.

### 3.8. Giữ lại gen trội

Ngược với gen lặn, **gen trội** là những thành phần đã được chứng minh đóng góp lớn. Chúng phải được bảo vệ để đột biến sau không vô tình phá mất.

**Cách nhận diện:** một thành phần là gen trội khi thí nghiệm **bỏ nó đi làm kết quả giảm rõ rệt** trên ít nhất một đường đua, và mức giảm lặp lại qua nhiều lần đo. Không công nhận gen trội chỉ dựa trên cảm nhận hay một lần chạy.

**Ứng viên hiện tại** (theo báo cáo và nhật ký; **cần xác nhận bằng thí nghiệm bỏ từng thành phần**, mục D5 của sổ hạn chế):

| Ứng viên | Lý do nghi là trội |
|---|---|
| Dấu hiệu lỗi từ lần chạy thật dẫn đường cho việc đọc mã | thu hẹp vùng tìm kiếm; Gen-9 → Gen-18 tăng định vị từ 18% lên 90,9% trên tầng trung bình (theo báo cáo) |
| Hai nhánh song song + chấm điểm cố định | giảm tình trạng tác tử bám hướng sai |
| Kiểm tra đoạn mã có chứa đúng cảnh báo quan sát được (`obs_in_source`) | chặn đề xuất sai vị trí |
| Công cụ tìm chỗ phát cảnh báo (`find_alert_sites`), công cụ tính macro (`code.eval`) | ở R9 và H1, cả hai nhánh đều dùng để tìm ra dòng lỗi |
| Lớp kiểm tra dòng đã đọc (`LINES_NOT_SHOWN`) | buộc tác tử đọc lại trước khi trích dẫn |

Bộ quy tắc V0–V9, các lớp kiểm tra cố định và kho bằng chứng **đã là bất biến**, nên không nằm trong danh sách này. Chúng được bảo vệ tuyệt đối, không phụ thuộc vào kết quả đo.

**Cơ chế bảo vệ:**

1. **Kiểm thử hồi quy riêng cho từng gen trội.** Mỗi gen trội gắn với một nhóm ca mà nó giải được. Đột biến nào làm hỏng nhóm ca đó thì bị loại, kể cả khi điểm trung bình tăng.
2. **Ngưỡng cao hơn khi muốn sửa.** Đột biến nhắm vào gen trội (sửa, thay, bỏ) phải đưa ra bằng chứng mạnh hơn: cải thiện rõ trên tập độc lập, và không giảm trên mọi đường đua.
3. **Ưu tiên kế thừa khi lai ghép.** Khi `CROSSOVER`, bản con phải mang các gen trội của cả hai bản cha, trừ khi chúng xung đột.
4. **Giữ bản tốt nhất (elitism).** Bản tốt nhất của mỗi ô luôn được giữ qua các generation, nên gen trội không bị mất do một lần chọn lọc xấu.
5. **Đánh giá lại định kỳ.** Gen trội ở môi trường này có thể thành gen lặn khi môi trường đổi, ví dụ khi thêm giao thức mới hay thư viện mới. Cứ k generation, đo lại đóng góp của từng gen trội. Gen nào không còn đóng góp thì chuyển sang danh sách đề cử loại bỏ (mục 3.7).

**Ba trạng thái của một thành phần:**

```
mới thêm ──(đo đóng góp)──► trội  (bảo vệ, kiểm thử hồi quy riêng)
    │                         │
    │                    (đánh giá lại)
    ▼                         ▼
  lặn ──(thử bỏ, không giảm ở đường đua nào)──► ngân hàng gen ──(REINTRODUCE khi phù hợp)──► mới thêm
```

---

## 4. Phiếu tiến hoá: bắt buộc cho mọi generation

```yaml
generation: gen-NN
parents: [gen-MM]                 # hai cha nếu là CROSSOVER
level: L3
operator: REPLACE_STEP
target: "bước LOCATE"
selection:                        # vì sao chọn đột biến này (mục 3.0)
  symptom: "Không thu được bằng chứng: 7/9 ca đường đua incomplete_code dừng INFEASIBLE"
  candidates:                     # các ứng viên đã xét và điểm
    - {op: L6.ADD_STRATEGY, score: 0.71}
    - {op: L3.REPLACE_STEP, score: 0.64}
    - {op: L2.ADD_TOOL,     score: 0.22}
  chosen_because: "..."
  escalated_from: null            # mức trước đó nếu đây là lần nâng mức
  exploration: false              # true nếu thuộc phần khám phá
idea_source: gap                  # failure / cost / gap / literature / simplify / invert / crossover / explore
mutator_persona: static_analyst
summary: "Thay bước LOCATE bằng duyệt theo điểm neo khi mã không biên dịch được"
motivation:
  observation: "..."
  hypothesis: "..."
expected: {track: incomplete_code, metric: defect_hit, direction: up}
changes:
  - {kind: ADD|MODIFY|REMOVE, path: "...", note: "..."}
invariants_touched: []            # phải rỗng
# --- phần dưới do harness điền ---
declared_matches_diff: true
result: {per_track: {...}, holdout: {...}, cost: {...}}
ablation: {...}                   # khi có nhiều thay đổi gộp chung
decision: KEEP | DISCARD | ARCHIVE_NICHE
niche: "..."
```

### Harness kiểm tra phiếu

| Kiểm tra | Nếu sai |
|---|---|
| Mức đã khai có khớp với tệp bị sửa không (ví dụ khai L1 mà sửa `src/`) | loại |
| Phép đã khai có khớp với thay đổi thật không (ví dụ khai `REMOVE_STEP` mà luồng không mất bước nào) | loại |
| `invariants_touched` khác rỗng, hoặc có sửa vào phần bất biến | loại ngay |
| Có nhiều thay đổi gộp chung | chạy thí nghiệm bỏ từng thay đổi một |
| Ý tưởng trùng chữ ký trong danh sách cấm | loại trước khi chạy đánh giá |

---

## 5. Bộ đo nhiều đường đua

Tiến hoá chỉ tìm ra những gì bộ đo khen thưởng. Vì vậy mỗi tình huống cần một đường đua riêng, và **mỗi đường đua có tập kiểm thử độc lập riêng**:

| Đường đua | Nguồn mẫu |
|---|---|
| Mã hoàn chỉnh, chạy được | bộ hiện tại |
| Mã chưa hoàn chỉnh, chưa biên dịch được | commit giữa chừng trong lịch sử phát triển |
| Chưa có adapter | thư viện mới |
| Yêu cầu nội bộ | ví dụ "phải xoá khoá sau khi dùng" |
| Yêu cầu chưa có mẫu kịch bản | buộc Tester phải tự soạn |
| Thư viện chưa từng thấy | phát hiện gợi ý viết cứng (sổ hạn chế, mục C6) |

---

## 6. Điều kiện để đột biến cấu trúc (L3–L6) làm được

| Thành phần | Hiện tại | Cần có |
|---|---|---|
| Tác tử | phần lớn là dữ liệu (`role.yaml`, `prompt.md`), nhưng vẫn cần `schema.py`, `handler.py` | khuôn mẫu sẵn cho tác tử mới |
| Kế hoạch của Planner | sổ tay luật là dữ liệu | — |
| Luồng xử lý | nằm trong `execution_loop.py` | **đồ thị quy trình mô tả bằng dữ liệu**: bước, tác tử phụ trách, điều kiện chuyển bước |
| Chiến lược | một chiến lược, viết cứng | **khuôn chung cho chiến lược** (khi nào áp dụng, thu bằng chứng gì, chi phí) + bộ định tuyến tất định |
| Lệnh chạy phần mềm | viết cứng trong mã (sổ hạn chế, mục A2) | đọc từ adapter |
| Phạm vi được sửa | mặc định Tier 1 | cấp Tier 2 theo từng phép đột biến L3–L6 |

---

## 7. Trình bày: cây tiến hoá

Từ các phiếu tiến hoá, dựng **cây phả hệ**: mỗi nút là một generation, ghi mức, phép đột biến, nguồn ý tưởng, kết quả theo từng đường đua, và quyết định giữ hay loại. Cây cho thấy hệ thống đã thử những hướng nào, hướng nào được giữ trong ô nào.

---

## 8. Tích luỹ tiến bộ: mỗi generation phải mang về một điều mới

Mục tiêu: mỗi generation được công nhận phải đóng góp **một điều mới có giá trị, đã kiểm chứng**, và điều đó được giữ lại làm nền cho các generation sau. Qua thời gian, hệ thống tiến dần tới bản hoàn chỉnh theo một lộ trình rõ ràng, chứ không đi lòng vòng.

### 8.1. Thế nào là "điều hay mới"

Một generation được công nhận khi đạt **ít nhất một** trong năm loại đóng góp sau, đo được bằng số liệu:

| Loại | Định nghĩa đo được | Ví dụ |
|---|---|---|
| **Năng lực mới** | giải được ca hoặc loại ca **chưa bản nào từng giải được** | lần đầu định vị được lỗi "xoá hẳn lệnh gửi cảnh báo" |
| **Mở đường đua mới** | lần đầu đạt ngưỡng tối thiểu trên một đường đua trước đó chưa có lời giải | lần đầu có kết quả trên đường đua mã chưa hoàn chỉnh |
| **Cải thiện thật** | chỉ số tăng **vượt mức dao động**, xác nhận qua nhiều lần chạy (mục 8.4) | định vị trên tập độc lập tăng có ý nghĩa thống kê |
| **Rẻ hơn** | cùng kết quả, chi phí giảm rõ | bớt 30% token mà không giảm chỉ số nào |
| **Gọn hơn** | bỏ được thành phần mà kết quả không giảm (mục 3.7) | bỏ một tác tử lặn |

Generation không đạt loại nào **không được tính là một bước tiến hoá**. Nó vẫn được ghi lại như một **lần thử thất bại**, để bộ chọn đột biến học (mục 3.0.4) và để đưa ý tưởng vào danh sách cấm lặp.

### 8.2. Cổng chấp nhận

Một generation phải qua **tất cả** các cổng sau, theo thứ tự:

1. **Bất biến:** không chạm bộ quy tắc V0–V9, các lớp kiểm tra cố định, kho bằng chứng, ranh giới vùng tin cậy. Các kiểm tra kỹ thuật (ruff, pyright, lint-imports, pytest) đều đạt.
2. **Phiếu khai đúng:** mức và phép đột biến đã khai khớp với phần mã thay đổi thật (mục 4).
3. **Không hồi quy gen trội:** mọi nhóm ca gắn với gen trội vẫn giải được (mục 3.8).
4. **Không giảm trên đường đua nào**, kể cả tập độc lập của từng đường đua. Mức giảm nằm trong biên độ dao động thì cho qua.
5. **Có ít nhất một đóng góp** thuộc mục 8.1, và đóng góp đó được xác nhận trên **tập độc lập**, không chỉ trên tập phát triển.

### 8.3. Lộ trình năng lực: đi về đâu

"Hoàn hảo" tuyệt đối không tồn tại. Vì vậy cần định nghĩa **"bản hoàn chỉnh"** bằng một **thang năng lực**, mỗi bậc là một đường đua có ngưỡng đạt trên tập độc lập:

| Bậc | Năng lực | Đường đua | Tình trạng |
|---|---|---|---|
| 1 | Kiểm tra mã hoàn chỉnh, một giao thức, có mẫu kịch bản | TLS hiện tại | ✅ đạt |
| 2 | Nhiều giao thức | HTTP/2, DNS, SSH, QUIC | ⚠️ mới có số liệu ban đầu |
| 3 | Yêu cầu chưa có mẫu kịch bản: Tester tự soạn | yêu cầu không mẫu | ❌ |
| 4 | Thư viện chưa từng thấy: không phụ thuộc gợi ý viết cứng | thư viện mới | ❌ |
| 5 | Mã chưa hoàn chỉnh: duyệt mã trước | mã chưa biên dịch được | ❌ |
| 6 | Yêu cầu nội bộ: bằng chứng tĩnh đã kiểm chứng (T2) | yêu cầu loại D | ❌ |
| 7 | Tự dựng adapter cho thư viện mới | không có adapter | ❌ |
| 8 | Khép kín từ văn bản RFC | RFC → đặc tả tự động | ❌ |

**Cách dùng thang:**
- Bộ chọn đột biến ưu tiên **bậc thấp nhất chưa đạt** (đường biên năng lực), và giữ một phần nhỏ cho bậc cao hơn để chuẩn bị trước.
- Khi một bậc đạt ngưỡng, nó trở thành **nền bắt buộc**: các generation sau không được làm hỏng nó (cổng 4).
- **Bản hoàn chỉnh** là bản đạt ngưỡng ở mọi bậc trên tập độc lập.
- **Dừng tiến hoá** khi đã đạt mọi bậc, hoặc khi nhiều generation liên tiếp không còn đóng góp nào, kể cả sau khi đã nâng mức đột biến (lợi ích giảm dần).

### 8.4. Phân biệt tiến bộ thật với dao động ngẫu nhiên

LLM cho kết quả khác nhau giữa các lần chạy, nên một lần tăng điểm có thể chỉ là may mắn. Quy định:
- Chạy mỗi bản **ít nhất 3 lần** trên các ca bị ảnh hưởng; báo cáo trung bình kèm khoảng tin cậy.
- "Cải thiện thật" nghĩa là khoảng tin cậy của bản mới **không chồng lên** khoảng tin cậy của bản cha, hoặc có kiểm định thống kê phù hợp.
- Riêng loại "năng lực mới" (giải được ca chưa ai giải), ca đó phải giải được **ổn định qua các lần chạy**, không chỉ một lần.

### 8.5. Chống quá khớp với dữ liệu kiểm tra

Đã có bài học từ DNS (sổ hạn chế, mục D9): chỉnh hệ thống rồi đo lại trên cùng bộ mẫu.
- Mỗi đường đua có **tập độc lập chỉ dùng ở cổng 5**. Mutator và bộ chẩn đoán không được thấy tập này.
- **Làm mới tập độc lập định kỳ:** sinh mẫu mới bằng các phép cài lỗi. Tập cũ chuyển thành tập phát triển.
- Nếu bản mới tốt trên tập phát triển nhưng không tốt trên tập độc lập, đánh dấu **nghi quá khớp**, và không công nhận.

### 8.6. Sổ tri thức tiến hoá

Mỗi generation, dù được công nhận hay thất bại, ghi **một bài học** vào sổ tri thức:
- đã thử gì, ở mức nào;
- kết quả ra sao trên từng đường đua;
- **vì sao** hiệu quả hoặc không hiệu quả.

Mutator đọc sổ này trước khi đề xuất. Nhờ vậy generation sau đứng trên vai generation trước, và không phải tự khám phá lại những gì đã biết.

Sổ cũng giữ **các bước đệm**: những ý tưởng chưa làm tăng điểm ngay nhưng mở ra khả năng mới, ví dụ một công cụ mới chưa được tác tử nào dùng tốt. Các bước đệm được lưu trong ngân hàng gen để những generation sau tận dụng.

### 8.7. Nhật ký đổi mới: trình bày với thầy

Mỗi generation được công nhận để lại **một dòng** trong nhật ký đổi mới:

```
Gen-NN | L5 CHANGE_COORDINATION | Năng lực mới | Hai nhánh song song: định vị tầng trung bình 18% → 90,9% | bậc 1
Gen-NN | L3 REMOVE_STEP         | Gọn hơn     | Bỏ Planner LLM (lặn), thay bằng luật: token -8%, chỉ số giữ nguyên | bậc 1
Gen-NN | L6 ADD_STRATEGY        | Mở đường đua | Duyệt mã theo điểm neo: lần đầu có kết quả trên mã chưa hoàn chỉnh | bậc 5
```
*(Các dòng trên là ví dụ minh hoạ, không phải kết quả thật.)*

Đọc nhật ký từ trên xuống là thấy hệ thống **tích luỹ năng lực qua từng bước**. Đối chiếu với thang năng lực là thấy còn cách bản hoàn chỉnh bao xa.

---

## 9. Thứ tự hiện thực đề xuất

1. Phiếu tiến hoá + harness kiểm tra phiếu + **cổng chấp nhận** (mục 8.2) + nhật ký đổi mới và sổ tri thức (mục 8.6, 8.7). Có thể làm ngay, không cần đổi kiến trúc.
2. **Bộ chẩn đoán từ nhật ký** + bảng triệu chứng → ứng viên + chấm điểm + nâng mức (mục 3.0), cùng **theo dõi đóng góp từng thành phần** để phát hiện gen lặn và gen trội (mục 3.7, 3.8). Có thể làm ngay, vì `trace.db` đã có đủ dữ liệu.
3. Bảng phép đột biến + bộ lập lịch "chọn phép trước", có hạn mức theo mức.
4. Thêm đường đua "mã chưa hoàn chỉnh" và "yêu cầu chưa có mẫu kịch bản", mỗi đường đua có tập kiểm thử độc lập.
5. Chọn lọc theo ô (quality-diversity) + danh sách cấm lặp.
6. Đồ thị quy trình mô tả bằng dữ liệu + khuôn chung cho chiến lược. Đây là điều kiện để L3–L6 làm được dễ dàng.
7. Nhiều góc nhìn cho mutator; cây tiến hoá.

# frontend

Giao diện web cho hệ thống kiểm chứng: chọn giao thức RFC và mã nguồn, chạy, **theo dõi các agent làm việc trực tiếp**, và xem lại trace (agent nhận gì, dùng công cụ nào, trả gì).

HTML/CSS/JS thuần, **không cần build, không cần Node**. Backend phục vụ trực tiếp thư mục này.

```bash
cd backend
uv run rfcv serve --env-file .env      # mở http://127.0.0.1:8765/
```

`--env-file` chỉ nạp các biến khoá mô hình khai báo trong `config/models.yaml` (ví dụ `DEEPSEEK_API_KEY`), không nạp biến khác (như `SUPABASE_*`). Bỏ cờ này nếu đã đặt biến vào môi trường. Thêm `--code-root <thư mục>` (lặp được) để cho phép chọn kho mã ngoài thư mục cha của `backend/`.

## Màn hình

| Màn hình | Làm gì |
|---|---|
| **Chạy mới** | Tick một hoặc nhiều giao thức RFC (mỗi giao thức là một adapter, kèm các RFC trong phạm vi) và từng yêu cầu RBS của nó. Chọn nguồn mã: *demo mô phỏng* hoặc *mã thật* (thư mục kho mã duyệt được phía máy chủ, chỉ mục mã, bộ chạy lệnh, bộ chạy SUT). Tuỳ chọn ngân sách mỗi yêu cầu. Thiếu gì (khoá API, sandbox, bộ chạy SUT) thì báo ngay trước khi chạy. |
| **Lần chạy (trực tiếp)** | Bên trái: đồ thị agent, Hub ở giữa, xung nháy theo từng thông điệp (giao việc, trả kết quả, ghi bằng chứng, đánh giá độ đủ), nút sáng khi agent đang làm; dưới đó là tiến độ từng yêu cầu (vòng, token, bằng chứng, nhãn tạm, kết luận). Bên phải: **Hội thoại** (Hub giao gì cho ai, ai trả gì), **Dòng thời gian** (mọi sự kiện, lọc được), **Bằng chứng** (kho chỉ ghi thêm), **Bản kê & cấu hình** (hash đầu vào, kiểm tra chuỗi hash). Bấm một nút trên đồ thị để lọc theo agent. |
| **Ngăn chi tiết** | Mở từ "Xem AI nhận gì · dùng gì · trả gì": ① đầu vào nhiệm vụ AI nhận và lời nhắc vai trò, ② skill đã được đưa/đã nạp và từng lần gọi công cụ kèm tham số và kết quả, ③ đầu ra cuối trước khi qua cổng kiểm chứng. Link thẳng: `#/run/<run_id>/event/<seq>`. |
| **Lịch sử** | Mọi lần chạy trong `runs/` (kể cả chạy bằng CLI). Mở lại, hoặc **Phát lại** một lần đã xong với tốc độ 1×/4×/16× để xem lại luồng phối hợp. |

## Quy tắc

- Frontend **không import Python và không đọc `.env`**: khoá API chỉ ở `backend/`; API chỉ trả tên biến khoá và đã đặt hay chưa.
- Mọi chuỗi từ backend (kể cả mã nguồn đang kiểm chứng, vốn không tin cậy) đều qua `esc()` trước khi vào HTML.
- Nguồn dữ liệu duy nhất là `runs/<run_id>/trace.db`, `evidence.db`, `manifest.json` do lõi ghi; giao diện chỉ đọc.

## API (backend/src/rfcv/api, FastAPI)

| Điểm cuối | |
|---|---|
| `GET /api/catalog` | adapter (RFC, yêu cầu), agent, mô hình và khoá đã đặt chưa, nhà cung cấp khả dụng |
| `GET /api/fs?path=` | duyệt thư mục mã (chỉ trong `--code-root`) |
| `POST /api/runs` | `{adapters:[{id, requirements[]}], mode: demo\|real, demo_case, code_root, code_index, executor, sut_launcher, budget}` → mỗi giao thức một lần chạy, xếp hàng chạy lần lượt; lỗi cấu hình trả 422 kèm danh sách |
| `GET /api/runs`, `GET /api/runs/<id>` | lịch sử; chi tiết kèm bản kê và tổng quan |
| `GET /api/runs/<id>/stream?after=<seq>` | **SSE**: `trace` (từng sự kiện), `status`, `end` |
| `GET /api/runs/<id>/events?after=&limit=`, `/events/<seq>` | sự kiện gọn; toàn văn một sự kiện kèm hội thoại LLM đã chuẩn hoá |
| `GET /api/runs/<id>/evidence[/<evidence_id>]`, `/verify` | bằng chứng; kiểm tra chuỗi hash |
| `POST /api/runs/<id>/cancel` | huỷ |

Tài liệu OpenAPI tương tác ở `/docs`, đặc tả JSON ở `/api/openapi.json`.

Máy chủ chỉ nghe `127.0.0.1` theo mặc định, chặn `Host` lạ và `POST` không phải JSON. Mặc định có đăng nhập (vai trò admin/member; tạo tài khoản bằng `rfcv users add`); `--no-auth` tắt đăng nhập và chỉ nên dùng trên máy cá nhân. Đừng mở ra mạng (`--host 0.0.0.0`) khi chưa có lớp bảo vệ phía trước (TLS, tường lửa).

## Bằng chứng trên mã và trình duyệt mã

- Tab **Bằng chứng** của một lần chạy có hai cách xem: *Trên mã nguồn* (bằng chứng có vị trí, gắn thành chú thích dưới đúng dòng mã, kèm danh mục để nhảy, lọc theo mức độ/tầng/yêu cầu, tìm chữ) và *Sổ cái đầy đủ* (mọi bản ghi trong kho, kể cả kết quả kiểm thử không gắn dòng mã).
- Nút **Duyệt cả kho** mở **trình duyệt mã** toàn màn hình kiểu Git: cây thư mục (huy hiệu ✗/✓ theo số chú thích, chấm xanh = agent đã đọc, lọc Tất cả/Có bằng chứng/Agent đã đọc), mở tệp lớn theo cửa sổ 3000 dòng, tìm tên tệp (gõ) và nội dung (Enter), tra định nghĩa / nơi gọi / hàm được gọi / tham chiếu bằng Ctrl+bấm hoặc bấm đúp một tên hàm, lịch sử Alt+←/→. Link trực tiếp: `#/runs/<id>/tab/explorer`.
- Nguồn nội dung: chỉ mục mã của lần chạy (`runs/<id>/code/index.db`), rồi bản sao phạm vi (`code/repo`), cuối cùng là các dòng agent đã đọc trong trace. Chỉ mở được tệp nằm trong phạm vi đó; đường dẫn tuỳ ý trên máy bị từ chối (404). Với chế độ demo chỉ có một tệp mã giả nên cây không có nhiều nội dung.
- API: `GET /api/runs/<id>/code` (cây), `/code/file?path=&around=|start=&end=` (tệp theo cửa sổ), `/code/search?q=`, `/code/symbol?name=`.

## Duyệt & phản hồi (vòng phản hồi của con người)

Trang **Duyệt & phản hồi** (`#/review`) và bảng "⑤ Đánh giá của con người" dưới mỗi kết luận (tab Kết luận của lần chạy) thực hiện đúng vai trò Reviewer trong thiết kế:

- **Hàng đợi:** mọi kết luận *Cần xem xét* (V0/V1/V4/V7), mọi *Vi phạm* (để loại dương tính giả) và **mẫu 10% kết luận Tuân thủ** chọn tất định theo hash của `run_id/requirement_id` (không ai chọn tay).
- **Nhận định:** Đồng ý / Không đồng ý / Chưa chắc. Không đồng ý thì bắt buộc chọn nhãn đúng, ít nhất một nguyên nhân (bảng phân loại cố định: dương tính giả, bỏ sót, kịch bản sai, oracle/RBS dịch sai, định vị mã sai, bằng chứng chưa đủ, môi trường lỗi, RFC mơ hồ, khác) và lý do từ 10 ký tự. Có thể gắn cờ từng bằng chứng (then chốt / sai / không liên quan, ở bảng so sánh, thẻ chú thích trên mã và ngăn chi tiết) và chấm từng lượt agent (tốt/kém, ở tab Hội thoại). Nháp lưu cục bộ nên không mất khi tải lại.
- **Lưu trữ (BR3):** nhận định là bản ghi RIÊNG trong bảng `reviews` của Evidence store của lần chạy, chỉ ghi thêm (trigger chặn sửa/xoá). **Nhãn của hệ thống không bao giờ bị đổi.** Mỗi người, mỗi yêu cầu, nhận định mới nhất là hiệu lực; bản cũ vẫn nằm trong kho.
- **Thống kê:** đồng thuận người–AI, ma trận nhầm lẫn (dương tính giả, bỏ sót), đồng thuận theo quy tắc, nguyên nhân bất đồng, đánh giá agent, độ phủ duyệt, các ca bất đồng gần đây.
- **Quay lại cải thiện:** nút *Xuất tập phản hồi* (JSONL, mỗi dòng kèm digest của bản kê và RBS để tái hiện) và *Sao chép tóm tắt* (markdown dán vào `docs/05_project/improvement_log.md`).
- Người duyệt là **tài khoản đã đăng nhập**: máy chủ tự gắn tên từ phiên, tên do máy khách gửi bị bỏ qua nên không mạo danh được. (Chỉ khi chạy `--no-auth` mới có tên tự khai.)

## Soạn thảo có kiểm soát

Sửa được: yêu cầu **RBS** (Giao thức → Yêu cầu: Sửa, Thêm yêu cầu), **lời nhắc** và **hồ sơ `role.yaml`** của agent, **skill**, **`config/models.yaml`**. Danh sách cố định, không có đường dẫn tuỳ ý.

- **Cổng kiểm tra là của lõi**, không phải bản sao: RBS qua parser + Oracle compiler (đúng từ vựng adapter; biến thể biên phải thoả điều kiện), agent qua `PolicyStore` (vùng tin cậy và công cụ là kiến trúc: đổi `zone` hay cấp công cụ đọc dữ liệu không tin cậy cho agent đặc quyền bị từ chối), skill qua `SkillRegistry`, mô hình qua `ModelsConfig` (cấm ghi khoá API, mọi agent phải có mô hình). Chưa qua thì không lưu được.
- **Chống ghi đè:** so hash khi lưu; tệp đã bị đổi ngoài giao diện thì báo xung đột, giữ nháp để gộp.
- **Bắt buộc ghi lý do**, giữ phiên bản cũ (khôi phục một bấm), có tab So sánh và Lịch sử, và **nhật ký kiểm toán** (Hệ thống → Nhật ký thay đổi) trong `backend/.rfcv-ui/` (đã `.gitignore`; lịch sử chính thức vẫn là git).
- Lần chạy sau tự dùng bản mới và ghi digest vào bản kê; lần đang chạy giữ bản đã nạp.
- Lời nhắc của Planner có khối `<!-- playbook:begin -->` sinh từ dữ liệu miền: sửa tay sẽ bị cảnh báo vì làm lệch bộ kiểm thử đồng bộ sổ tay.

## Đăng nhập và vai trò

`rfcv serve` mặc định **bật đăng nhập** (tắt bằng `--no-auth`, chỉ nên dùng trên máy cá nhân: khi đó mọi người là admin cục bộ).

| | member | admin |
|---|:-:|:-:|
| Xem mọi màn hình, xuất dữ liệu | ✓ | ✓ |
| Chạy kiểm chứng, chạy lại | ✓ | ✓ |
| Huỷ lần chạy | của chính mình | mọi lần chạy |
| Duyệt và phản hồi kết luận | ✓ | ✓ |
| Sửa yêu cầu, lời nhắc, skill, `models.yaml`; khôi phục phiên bản | | ✓ |
| Quản lý người dùng (`#/users`), xem nhật ký bảo mật | | ✓ |

- **Lần đầu:** chưa có tài khoản nào thì máy chủ in một **mã thiết lập** ra console và ghi vào `backend/.rfcv-ui/setup-code.txt`; nhập mã đó ở màn hình đăng nhập để tạo admin đầu tiên (mã bị xoá sau khi dùng). Cũng có thể tạo bằng CLI: `rfcv users add <tên> --role admin` (hỏi mật khẩu), cùng `list · passwd · role · disable · enable · remove`.
- **Mật khẩu** tối thiểu 10 ký tự, băm scrypt có muối riêng. **Phiên** là mã ngẫu nhiên trong cookie `HttpOnly` + `SameSite=Strict` (trang không đọc được); máy chủ chỉ lưu hash của mã, nhàn rỗi 12 giờ hoặc tối đa 7 ngày thì hết hạn. Đổi/đặt lại mật khẩu, khoá, xoá tài khoản thu hồi mọi phiên của họ.
- **Chống đoán mật khẩu:** 5 lần sai trong 10 phút thì khoá tài khoản (và giới hạn theo địa chỉ); thông báo lỗi chung, không lộ tài khoản có tồn tại.
- Yêu cầu ghi chỉ nhận từ chính trang này (kiểm tra `Origin`); luôn còn ít nhất một admin hoạt động; không tự khoá/hạ quyền/xoá chính mình.
- Danh tính do **máy chủ** gắn vào nhận định, lần sửa và lần chạy (`created_by`). **Nhật ký bảo mật** (đăng nhập, đăng nhập sai, tạo/đổi/khoá/xoá) chỉ ghi thêm, ở `backend/.rfcv-ui/auth.db` (đã `.gitignore`), không chứa mật khẩu.
- Giới hạn: chưa có HTTPS (cookie chỉ gắn `Secure` khi truy cập qua https) nên đừng mở ra ngoài máy cục bộ mà không đặt sau proxy TLS.

## Chế độ chỉ đọc

`rfcv serve --read-only` chặn mọi thao tác ghi (chạy, huỷ, nhận định, sửa, khôi phục) bằng HTTP 403 và ẩn các nút tương ứng; xem, duyệt hàng đợi và xuất vẫn dùng được. Dùng khi chia sẻ giao diện chỉ để xem.

## API bổ sung

| Điểm cuối | |
|---|---|
| `GET /api/auth/status` · `POST /api/auth/login · setup · logout · password` | trạng thái và tài khoản hiện tại, đăng nhập, thiết lập admin đầu tiên, đăng xuất, đổi mật khẩu của mình |
| `GET/POST /api/users` · `PATCH/DELETE /api/users/<tên>` · `GET /api/users/audit` | (admin) danh sách, tạo, đổi vai trò/khoá/mật khẩu, xoá, nhật ký bảo mật |
| `GET /api/reviews/meta · queue · summary · digest · export` | bảng phân loại, hàng đợi, thống kê, markdown, JSONL |
| `GET/POST /api/runs/<id>/reviews` | nhận định của lần chạy; ghi nhận định mới (422 kèm lý do cụ thể nếu thiếu) |
| `GET /api/edit/list · read · history · version · audit` | tài nguyên sửa được, nội dung và hash, lịch sử, nhật ký |
| `POST /api/edit/validate · save · restore` | kiểm tra nháp (không ghi), lưu (422 lỗi kiểm tra, 409 xung đột), khôi phục |

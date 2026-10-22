# Tổng quan hệ thống

Trang này cho người mới đọc lần đầu: hệ thống làm gì, chạy thế nào, gồm những phần nào và đang ở đâu. Chi tiết nằm ở các tài liệu
[thiết kế](../design/); tình trạng thật và các vấn đề đang mở nằm ở [sổ theo dõi](../management/theo_doi_cai_thien.md).

## Hệ thống làm gì

Với mỗi yêu cầu trong một đặc tả giao thức mạng (ví dụ RFC 8446 §5.2: bên nhận bản ghi quá dài phải gửi cảnh báo
`record_overflow` rồi đóng kết nối), hệ thống kiểm tra **một bản triển khai cụ thể** (ví dụ wolfSSL) có tuân thủ không, và trả về
một nhãn **kèm bằng chứng truy vết được**.

**Nguyên tắc cốt lõi: agent đề xuất, thành phần tất định kiểm chứng.** LLM chỉ đề xuất vị trí mã, kịch bản kiểm thử, phản biện. Một
đề xuất chỉ thành bằng chứng sau khi qua bộ kiểm chứng không dùng LLM. Nhãn do **Verdict engine** gán theo một bộ quy tắc cố định,
không agent nào được tự kết luận.

| Nhãn | Nghĩa |
|---|---|
| `VIOLATION` | Có bằng chứng chạy thực tế (T3) hoặc phân tích tĩnh đã kiểm định (T2) cho thấy vi phạm |
| `COMPLIANT` | Đủ bằng chứng tuân thủ, đã qua một lần phản biện sạch; kèm mức bảo đảm (`LINKED`, `BEHAVIORAL`, `STATIC`) |
| `NEEDS_REVIEW` | Bằng chứng mâu thuẫn hoặc đáng ngờ, cần người xem |
| `UNVERIFIABLE` | Không đủ bằng chứng khi hết ngân sách hoặc không làm tiếp được (khi nghi ngờ thì không kết luận) |

Ba mức bằng chứng: **T1** vị trí mã đã đối chiếu với chỉ mục, **T2** kết quả phân tích tĩnh, **T3** kết quả chạy kịch bản trên bản
triển khai (kèm nhân chứng dương và âm). Bốn loại yêu cầu A–D (ràng buộc dữ liệu gửi đi, phản ứng khi nhận dữ liệu sai, thứ tự
và trạng thái thông điệp, hành vi nội bộ) quyết định bằng chứng nào cần có.

## Luồng xử lý

```
RFC ──► RFC gate / RFC Analyst ──► đặc tả hành vi (RBS) đã duyệt ──► oracle biên dịch
                                                                          │
        ┌─────────────────────  Execution loop (hub)  ◄───────────────────┘
        │   Planner chọn nhiệm vụ ──► Code Reader / Test / Verifier / Code Indexer
        │                                   │ đầu ra đi qua cổng tất định
        │                                   ▼
        │                 Schema gate · Tool gateway · Test driver ──► Evidence store (chuỗi hash, chỉ ghi thêm)
        │                                                                   │
        └──── báo cáo độ đủ ◄────────────  Verdict engine (V0–V9) ◄────────┘
                                                  │
                                                  ▼
                                   nhãn cuối + bằng chứng đã trích
```

Agent **không gọi nhau**: mọi giao việc là một nhiệm vụ có kiểu đi qua hub. Mỗi vòng tối đa 2 nhiệm vụ; hub dừng khi đủ bằng chứng,
hết ngân sách hoặc phát hiện lặp. Chi tiết: [phối hợp agent](../design/thiet_ke_phoi_hop_agent.md).

## Các agent

| Agent | Vùng | Việc | Trạng thái nối |
|---|---|---|---|
| Planner | đặc quyền | chọn nhiệm vụ tiếp theo, không gán nhãn | có |
| Code Reader | **cách ly** | tự khám phá mã, trả vị trí và nhận định có cấu trúc | có |
| Test | đặc quyền | chọn kịch bản kiểm thử trong DSL giới hạn | có |
| Verifier | đặc quyền | phản biện bằng chứng, không đọc mã | có |
| Code Indexer | **cách ly** | lập bản đồ hàm → thành phần | có (chưa thử với LLM thật) |
| RFC Analyst | đặc quyền | dịch câu RFC sang RBS | **chưa nối** |
| Report | đặc quyền | giải thích kết luận | **chưa nối** |
| Locator (tất định) | không LLM | truy vấn phân tích tĩnh (loại D) | **chưa nối** |

Agent đọc mã nằm trong **vùng cách ly** vì mã nguồn là dữ liệu không tin cậy. Agent đặc quyền (Planner, Verifier…) không bao giờ
thấy chuỗi tự do từ vùng cách ly, chỉ thấy các giá trị miền hữu hạn hoặc đã đối chiếu với chỉ mục. Mô hình và skill của từng agent
khai báo ở [config/models.yaml](../../backend/config/models.yaml) và `skills:` trong `role.yaml`. Xem bản đồ hiện tại bằng `uv run rfcv agents`.

## Bản đồ thư mục

| Thư mục | Chứa |
|---|---|
| [src/rfcv/](../../backend/src/rfcv/) | Lõi không biết miền (`core/`, `gates/`, `evidence/`), miền RFC giao thức (`domains/rfc_protocol/`), chỉ mục mã, giao diện dòng lệnh |
| [agents/](../../backend/agents/) | Mỗi agent một thư mục: `role.yaml`, `prompt.md`, mã (schema, handler, `SPEC`) |
| [skills/](../../backend/skills/) | Kho skill chung (`core/` và theo adapter); agent chỉ dùng skill nó khai báo |
| [adapters/](../../backend/adapters/) | Adapter cho từng giao thức (hiện có `tls13`): ví dụ RBS, mẫu kịch bản, công thức SUT |
| [config/](../../backend/config/) | Cấu hình mô hình |
| [eval/](../../backend/eval/) | Dữ liệu và môi trường đánh giá |
| [scripts/](../../backend/scripts/) | Phép đo hệ thống với LLM thật |
| [tests/](../../backend/tests/) | Kiểm thử (không gọi LLM thật) |
| [docs/](../README.md) | Tài liệu này |

Quy ước đặt tên: [quy_uoc_dat_ten.md](../conventions/quy_uoc_dat_ten.md).

## Chạy thử nhanh

```
uv sync
uv run pytest -q                              # không gọi LLM thật
uv run rfcv agents                            # bản đồ agent và trạng thái nối
uv run rfcv models                            # mô hình và agent nào dùng mô hình nào
uv run python scripts/e2e_live.py faulty      # cả vòng điều tra với LLM thật; cần khoá API trong môi trường hoặc .env
uv run rfcv trace runs/e2e-faulty             # xem lại luồng xử lý
```

`rfcv run --adapter adapters/tls13` (chạy trên bản triển khai thật) **chưa chạy được**: còn thiếu backend kiểm thử và bộ chạy SUT.
Phép thử `e2e_live.py` dùng SUT và mã nguồn giả nên chỉ cho thấy cơ chế phối hợp, chưa cho thấy độ chính xác trên mã thật.

## Đọc tiếp

1. [Thiết kế chi tiết hệ thống](../design/thiet_ke_chi_tiet_he_thong.md): bài toán, giải pháp, kiến trúc đầy đủ.
2. Các tài liệu thiết kế thành phần trong [design/](../design/): RFC, đọc mã nguồn, phối hợp agent, adapter và kiểm thử.
3. [Thiết kế đánh giá](../evaluation/thiet_ke_danh_gia.md) và [thực nghiệm sơ bộ](../evaluation/danh_gia_kha_thi_thuc_nghiem.md).
4. [Yêu cầu đầu ra](../quality/tieu_chuan_dau_ra.md) và [tiêu chuẩn chất lượng](../quality/tieu_chuan_he_thong.md): hệ thống phải giải quyết được gì khi dùng thực tế, và phải đạt gì ở từng phần.
5. [Checklist deliverable](../deliverables/README.md): sản phẩm bàn giao của cả dự án và trạng thái từng hạng mục.
6. [Sổ theo dõi cải thiện](../management/theo_doi_cai_thien.md) và [backlog công việc](../management/theo_doi_backlog.md): vấn đề còn dở, số đo, hạn chế, và việc cần làm theo thứ tự.

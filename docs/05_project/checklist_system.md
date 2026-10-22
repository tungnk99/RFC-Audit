# Checklist: hệ thống và mã nguồn

Nguồn danh mục: [Bảng 26](../02_design/system_design.md#51-phạm-vi-và-công-sức) của thiết kế chi tiết (ước lượng công sức
theo tầng). Quy ước đánh dấu và cách cập nhật: xem [README](README.md). Trạng thái ghi theo ngày **2026-10-22**.

Một hạng mục chỉ được tích `[x]` khi có bằng chứng đọc được (mã, test hoặc kết quả chạy). Hạng mục làm dở thì để `[ ]` và ghi rõ
đã có gì, còn thiếu gì.

## Tầng 1 (bắt buộc, 19 tuần công)

### 1. Lõi harness (3,5 tuần)
- [x] Execution loop (hub, giao việc, ngân sách, phát hiện lặp): [execution_loop.py](../../backend/src/rfcv/core/execution_loop.py), [test_execution_loop.py](../../backend/tests/test_execution_loop.py)
- [x] Context builder: [context_builder.py](../../backend/src/rfcv/core/context_builder.py)
- [x] IFC (nhãn tin cậy): [ifc.py](../../backend/src/rfcv/core/ifc.py), [test_policy_ifc.py](../../backend/tests/test_policy_ifc.py)
- [x] LLM gateway (kho mô hình và gán cho agent): [llm_gateway.py](../../backend/src/rfcv/core/llm_gateway.py), [models.yaml](../../backend/config/models.yaml)
- [x] Policy store: [policy.py](../../backend/src/rfcv/core/policy.py)
- [x] Schema gate: [schema_gate.py](../../backend/src/rfcv/domains/rfc_protocol/schema_gate.py)
- [x] Trace log và lệnh `rfcv trace`: [trace.py](../../backend/src/rfcv/core/trace.py)

### 2. Bằng chứng và kết luận (1 tuần)
- [x] Evidence store (chuỗi hash, chỉ ghi thêm): [store.py](../../backend/src/rfcv/evidence/store.py), [test_evidence_store.py](../../backend/tests/test_evidence_store.py)
- [x] Verdict engine V0–V9: [verdict_engine.py](../../backend/src/rfcv/evidence/verdict_engine.py), [rules.py](../../backend/src/rfcv/domains/rfc_protocol/rules.py), [test_verdict_engine.py](../../backend/tests/test_verdict_engine.py)
- [x] Requirement registry: [registry.py](../../backend/src/rfcv/evidence/registry.py)

### 3. Đọc mã (1 tuần)
- [x] Code gate và bộ công cụ đọc mã: [code_gate.py](../../backend/src/rfcv/gates/code_gate.py)
- [x] Locator (`locator.suggest`): [agents/locator/](../../backend/agents/locator/)
- [ ] Quét nhánh nghi vấn (T2 `suspicious_branch`): đã có schema và quy tắc V4, **chưa có bộ quét** tạo bằng chứng

### 4. Đặc tả hành vi và oracle (1,5 tuần)
- [x] Ngữ pháp RBS: [rbs.py](../../backend/src/rfcv/domains/rfc_protocol/spec/rbs.py), [test_spec.py](../../backend/tests/test_spec.py)
- [x] Oracle compiler: [oracle_compiler.py](../../backend/src/rfcv/domains/rfc_protocol/spec/oracle_compiler.py)
- [ ] So khớp hai luồng dịch: [reconcile.py](../../backend/src/rfcv/domains/rfc_protocol/spec/reconcile.py) có mã nhưng chưa chạy với RFC Analyst thật (xem [CT-05](../05_project/improvement_log.md#ct-05--p1--agent-không-thấy-câu-rfc), [CT-12](../05_project/improvement_log.md#ct-12--p2--rfc-analyst-chưa-nối-loại-c-d-thiếu-mẫu-và-skill))

### 5. Backend TLS, adapter và kiểm thử thực tế (3,5 tuần)
- [x] Coverage linker: [coverage_linker.py](../../backend/src/rfcv/domains/rfc_protocol/coverage_linker.py), [test_driver_and_coverage.py](../../backend/tests/test_driver_and_coverage.py)
- [x] Test driver (vòng đời, sanity, chạy lại ca FAIL, nhân chứng, bản ghi T3): [driver.py](../../backend/src/rfcv/domains/rfc_protocol/sandbox/driver.py)
- [ ] Backend tlsfuzzer: `validate()` đã có; `run()` và `sanity()` còn `NotImplementedError` ([CT-09](../05_project/improvement_log.md#ct-09--p0--chưa-có-backend-kiểm-thử-thật-và-bộ-chạy-sut-thật))
- [ ] Bộ chạy SUT Docker (`DockerSutLauncher`) chưa cài ([CT-09](../05_project/improvement_log.md#ct-09--p0--chưa-có-backend-kiểm-thử-thật-và-bộ-chạy-sut-thật))
- [ ] Adapter TLS 1.3: hiện có [một mẫu](../../backend/adapters/tls13/templates/record_length.yaml) và [một ví dụ RBS](../../backend/adapters/tls13/examples/TLS13-0042.rbs); chưa mở rộng danh mục mẫu theo các mục RFC trong phạm vi
- [ ] Ba bản triển khai TLS: mới khai báo [wolfSSL](../../backend/adapters/tls13/sut/wolfssl.yaml); hai bản tham chiếu còn `<commit>`
- [ ] Bản đo độ phủ của các bản triển khai chưa dựng
- [x] Adapter checker (kiểm tra hình thức): [checker.py](../../backend/src/rfcv/adapters/checker.py); các kiểm tra cần sandbox (`build.sut`, `oracle.stable`…) đang bỏ qua

### 6. Bảy agent (1,5 tuần)
- [x] Lời nhắc, hồ sơ vai trò và schema của bảy agent: [agents/](../../backend/agents/)
- [ ] Nối cả bảy agent vào luồng chạy: **5/7** (đã nối Planner, Code Reader, Test, Verifier, Code Indexer; chưa nối RFC Analyst và Report). Xem `uv run rfcv agents`
- [ ] Code Indexer đã có handler nhưng chưa thử với LLM thật ([CT-18](../05_project/improvement_log.md#ct-18--p3--map_components-đã-có-handler-nhưng-chưa-thử-với-llm-thật))

### 7. Backend và adapter DNS (2 tuần)
- [ ] Backend DNS: [dns/\_\_init\_\_.py](../../backend/src/rfcv/backends/dns/__init__.py) mới chỉ có một dòng mô tả
- [ ] Adapter DNS: `adapters/` mới có `tls13`
- [ ] Ba bản triển khai DNS (CoreDNS, Knot, thêm một bản tham chiếu)

### 8. Đường cơ sở (1,5 tuần)
- [ ] B0: RFCAudit trên cùng kho mã và tập yêu cầu (mới được nhắc tới trong [eval.yaml](../../backend/eval/config/eval.yaml), chưa có bộ chạy)
- [ ] B2: không agent, chạy toàn bộ mẫu TLS-Anvil và tlsfuzzer phù hợp
- [ ] B3: kiểu iPanda (LLM viết chương trình kiểm thử và tự đánh giá)

### 9. Bộ dữ liệu (1,5 tuần)
- [ ] Đột biến tự động: có [operators.yaml](../../backend/eval/dataset/mutants/operators.yaml) (toán tử và mẫu bản ghi), chưa có kết quả sinh và kiểm
- [ ] Lỗi thật: có [danh sách commit ứng viên](../../backend/eval/dataset/real/wolfssl_commit_ung_vien.csv); các cột `type`, `keep`, `requirement` do **người** điền, chưa xong
- [ ] Kịch bản tấn công A1–A7: chưa có kịch bản cụ thể; mô phỏng mới có họ lỗi `a7_canonical`

### 10. Thực nghiệm và thống kê (2 tuần)
- Xem [checklist_experiments.md](checklist_experiments.md).

## Tầng 2 (chỉ làm khi mốc G2 đạt sớm)
- [ ] Học máy trạng thái cho loại C (1,5 tuần): đã có quy tắc V3 và schema, chưa có bộ học
- [ ] Truy vấn CodeQL kiểm định đột biến cho loại D (1,5 tuần): `STATIC_QUERY` chưa nối ([CT-10](../05_project/improvement_log.md#ct-10--p2--static_query-loại-d-chưa-nối))
- [ ] QUIC (quiche, ngtcp2) trên backend (2 tuần)

## Tầng 3 (nếu còn thời gian)
- [ ] HTTP/2 và SSH
- [ ] Trợ lý viết adapter
- [ ] Chế độ CI cho người dùng cuối: các lệnh `rfcv rerun`, `rfcv specs`, `rfcv status`, `rfcv review`, `rfcv report` hiện báo "chưa cài"

## Hạ tầng phát triển và đo lường (ngoài Bảng 26, đã có)
- [x] Mô phỏng đo cơ chế (`rfcv eval sim`, `rfcv eval coord`): [src/rfcv/eval/](../../backend/src/rfcv/eval/); kết quả là **SYNTHETIC**, không phải độ chính xác ngoài đời
- [x] Phép thử đầu-cuối với LLM thật (SUT và mã giả): [e2e_live.py](../../backend/scripts/e2e_live.py), [analyze_run.py](../../backend/scripts/analyze_run.py), [verifier_smoke.py](../../backend/scripts/verifier_smoke.py)
- [x] Ranh giới kiến trúc ép bằng mã: 6 hợp đồng `import-linter` trong [pyproject.toml](../../backend/pyproject.toml)
- [x] Bộ kiểm thử không gọi LLM thật: [tests/](../../backend/tests/)

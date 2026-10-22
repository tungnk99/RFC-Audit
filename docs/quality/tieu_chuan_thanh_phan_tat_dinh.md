# Tiêu chuẩn chất lượng: các thành phần tất định

Các thành phần không dùng LLM là **nền để tin vào kết luận**: agent chỉ đề xuất, chính các thành phần này kiểm chứng, ghi bằng chứng và
gán nhãn. Vì vậy tiêu chuẩn ở đây **cứng hơn** của agent: gần như mọi mục là bất biến (0 ngoại lệ) và đều có kiểm thử tự động. Tiêu chuẩn
toàn hệ thống ở [tieu_chuan_he_thong.md](tieu_chuan_he_thong.md), của các agent ở [tieu_chuan_agent.md](tieu_chuan_agent.md).

Cột "Hiện tại": *Đạt (test)* là kiểm thử tự động đang pass (toàn bộ bộ kiểm thử pass ở lần chạy gần nhất). *Chưa kiểm* là chưa có kiểm thử
hoặc phép đo. Bảng bất biến đầy đủ và nơi ép từng bất biến nằm ở [README](../../README.md).

## Execution loop (hub điều phối)

Mã: [execution_loop.py](../../src/rfcv/core/execution_loop.py). Test: [test_execution_loop.py](../../tests/test_execution_loop.py).

| Mã | Phải làm được / phải đạt | Ngưỡng | Hiện tại |
|---|---|---|---|
| EL-1 | Mọi giao việc là một nhiệm vụ có kiểu đi qua hub; agent không gọi nhau | 0 ngoại lệ | Đạt (test) |
| EL-2 | Chỉ chuyển nhiệm vụ có trong danh mục, đúng đích và đúng kiểu tham số; ghi trace trước khi chuyển | 100% | Đạt (test) |
| EL-3 | Mỗi vòng tối đa 2 nhiệm vụ; tối đa 8 vòng mỗi yêu cầu | 100% | Đạt (test); số vòng 8 là giá trị khởi điểm cần hiệu chỉnh |
| EL-4 | Dừng đúng điều kiện: đủ bằng chứng, hết ngân sách (BUDGET), lặp lần thứ ba (LOOP), INFEASIBLE | 100% | Đạt (test) |
| EL-5 | Nhãn tạm COMPLIANT phải qua một lần phản biện sạch trước khi dừng | 100% | Đạt (test) |
| EL-6 | Ghi đủ sự kiện để dựng lại luồng: lý do dừng và chi tiết, đầu ra agent, hội thoại khi hỏng | 100% sự kiện cần thiết | Đạt (test) |
| EL-7 | Không có vòng vô hạn; thời gian một yêu cầu bị chặn bởi ngân sách `seconds` | 100% | Đạt (test) cho giới hạn số vòng; **chưa có test cho ngân sách thời gian** |

## Context builder và IFC (nhãn tin cậy)

Mã: [context_builder.py](../../src/rfcv/core/context_builder.py), [ifc.py](../../src/rfcv/core/ifc.py). Test: [test_policy_ifc.py](../../tests/test_policy_ifc.py).

| Mã | Phải làm được / phải đạt | Ngưỡng | Hiện tại |
|---|---|---|---|
| CB-1 | Mỗi agent chỉ nhận trường ngữ cảnh khai báo trong `role.yaml` (ví dụ Test không nhận T1, Code Reader không nhận nhãn tạm) | 0 trường thừa | Đạt (test) |
| CB-2 | Chuỗi UNTRUSTED tự do không vào ngữ cảnh agent đặc quyền | 0 | Đạt (test) |
| CB-3 | Bản tóm tắt bằng chứng cho agent đặc quyền chỉ có giá trị miền hữu hạn hoặc đã đối chiếu (`VerifiedRef`) | 100% | Đạt (test) |
| CB-4 | Bản tóm tắt không phình theo số bằng chứng (giữ chi phí token có giới hạn) | Token đầu vào của Verifier giảm so với mốc 55k | **Chưa đạt** ([CT-03](../management/theo_doi_cai_thien.md#ct-03--p2--evidencesummary-phình-theo-số-bằng-chứng-t3)) |

## Tool gateway

Mã: [tool_gateway.py](../../src/rfcv/gates/tool_gateway.py). Test: [test_gates.py](../../tests/test_gates.py), [test_assembly.py](../../tests/test_assembly.py).

| Mã | Phải làm được / phải đạt | Ngưỡng | Hiện tại |
|---|---|---|---|
| TG-1 | Từ chối mặc định mọi lời gọi công cụ không khai báo cho vai trò | 0 lọt qua | Đạt (test) |
| TG-2 | Kiểm miền tham số; `explore` chỉ chạy lệnh đọc trong danh sách, không qua shell | 0 lệnh ngoài danh sách chạy được | Đạt (test) |
| TG-3 | Công cụ nguy hiểm (ghi tệp, gọi mạng, chạy lệnh trên máy chủ) không đăng ký được, kể cả từ plugin | 0 | Đạt (test, [test_plugins.py](../../tests/test_plugins.py)) |
| TG-4 | Mã lỗi từ chối chỉ là mã liệt kê, không kèm chi tiết chính sách | 100% | Đạt (test) cho mã liệt kê; **chưa kiểm riêng** việc không lộ chi tiết chính sách |
| TG-5 | Chống đối thủ thật: dẫn dắt agent gọi công cụ ngoài quyền | 0 lọt qua | Chưa thử với LLM thật (A3, [CT-08](../management/theo_doi_cai_thien.md#ct-08--p1--chưa-thử-đối-kháng-với-mô-hình-thật)) |

## Schema gate (T1)

Mã: [schema_gate.py](../../src/rfcv/domains/rfc_protocol/schema_gate.py). Test: [test_gates.py](../../tests/test_gates.py).

| Mã | Phải làm được / phải đạt | Ngưỡng | Hiện tại |
|---|---|---|---|
| SG-1 | T1 chỉ được ghi khi ký hiệu có trong chỉ mục và khoảng dòng nằm trong thân ký hiệu | 0 T1 sai vào kho | Đạt (test) |
| SG-2 | Mọi dòng được dẫn phải thuộc tập dòng đã hiển thị cho agent trong phiên | 100% | Đạt (test) |
| SG-3 | Mỗi cạnh của `call_path` có trong chỉ mục lời gọi hoặc đã hiển thị | 100% | Đạt (test) |
| SG-4 | `observed` thuộc từ vựng adapter hoặc là số | 100% | Đạt (test); quan sát thật: cổng từ chối 1 lần và mô hình tự sửa |
| SG-5 | Dòng dẫn được biên dịch theo cờ build (khi chỉ mục có dữ liệu `#if`) | 100% | Đạt (test) |
| SG-6 | Lỗi cổng trả về agent chỉ là mã liệt kê để agent làm lại tối đa số lần cho phép | 100% | **Chưa có kiểm thử riêng** cho vòng làm lại; quan sát thật: cổng từ chối 1 lần và mô hình tự sửa thành công |

## Code gate và Locator

Mã: [code_gate.py](../../src/rfcv/gates/code_gate.py), [agents/locator/](../../agents/locator/).

| Mã | Phải làm được / phải đạt | Ngưỡng | Hiện tại |
|---|---|---|---|
| CG-1 | Công cụ đọc mã chỉ đọc, không ghi tệp, không gọi mạng, không chạy mã của kho mã, không đọc ngoài phạm vi (C2) | 0 vi phạm | Đạt (test) |
| CG-2 | Mọi vị trí trả về đối chiếu được với kho mã tại commit cố định (C3) | 100% | Đạt (test) |
| CG-3 | `locator.suggest` đưa vị trí đúng vào top 5 gợi ý | ≥ 80% (ĐX) | Chưa đo |
| CG-4 | Chạy được trên C, Rust, Go, kể cả mã nhiều macro và con trỏ hàm (C4) | Báo cáo theo ngôn ngữ | Chưa chạy trên mã thật ([CT-13](../management/theo_doi_cai_thien.md#ct-13--p3--skill-chỉ-có-cho-c-và-tls)) |
| CG-5 | `STATIC_QUERY` chạy truy vấn tĩnh đã kiểm định đột biến (loại D) | 100% truy vấn qua kiểm định | Chưa nối ([CT-10](../management/theo_doi_cai_thien.md#ct-10--p2--static_query-loại-d-chưa-nối)) |
| CG-6 | Bộ quét nhánh nghi vấn (T2) tạo bằng chứng `suspicious_branch` | Phát hiện mã mức 1, 2 | Chưa có bộ quét |

## Test driver và oracle

Mã: [driver.py](../../src/rfcv/domains/rfc_protocol/sandbox/driver.py), [oracle_compiler.py](../../src/rfcv/domains/rfc_protocol/spec/oracle_compiler.py). Test: [test_driver_and_coverage.py](../../tests/test_driver_and_coverage.py), [test_spec.py](../../tests/test_spec.py).

| Mã | Phải làm được / phải đạt | Ngưỡng | Hiện tại |
|---|---|---|---|
| TD-1 | PASS, FAIL do oracle biên dịch tính, không do LLM (K1) | 100% | Đạt (test) |
| TD-2 | ERROR (sanity hỏng, chưa tới trigger, lỗi môi trường) không bao giờ thành FAIL | 0 | Đạt (test) |
| TD-3 | Ca FAIL được chạy lại ở môi trường khác; khác nhau thì đánh dấu không nhất quán (V0) | 100% | Đạt (test) |
| TD-4 | Có nhân chứng dương (bản tham chiếu) trước khi kết quả được dùng (BR6) | 100% | Đạt (test) |
| TD-5 | Mỗi ca chạy để lại sự kiện truy vết; thông điệp lỗi môi trường chỉ vào trace, không vào kho bằng chứng | 100% | Đạt (test) |
| TD-6 | Nhật ký thô của SUT chỉ vào Artifact store, agent không thấy | 0 rò | Đạt (test) |
| TD-7 | Chạy trên backend và SUT thật | Chạy hết một yêu cầu trên wolfSSL | **Chưa có** ([CT-09](../management/theo_doi_cai_thien.md#ct-09--p0--chưa-có-backend-kiểm-thử-thật-và-bộ-chạy-sut-thật)) |

## Coverage linker

Mã: [coverage_linker.py](../../src/rfcv/domains/rfc_protocol/coverage_linker.py).

| Mã | Phải làm được / phải đạt | Ngưỡng | Hiện tại |
|---|---|---|---|
| CL-1 | Liên kết T3 với T1 khi dòng của T1 được thực thi trong lúc chạy T3 | 100% liên kết đúng | Đạt (test) |
| CL-2 | Không ghi liên kết trùng | 0 | Đạt (test) |
| CL-3 | Chạy với dữ liệu độ phủ thật từ bản đo độ phủ | Có | Chưa (cần bản đo độ phủ, [CT-09](../management/theo_doi_cai_thien.md#ct-09--p0--chưa-có-backend-kiểm-thử-thật-và-bộ-chạy-sut-thật)) |

## Verdict engine

Mã: [verdict_engine.py](../../src/rfcv/evidence/verdict_engine.py), [rules.py](../../src/rfcv/domains/rfc_protocol/rules.py). Test: [test_verdict_engine.py](../../tests/test_verdict_engine.py), [test_contracts.py](../../tests/test_contracts.py), [test_label_golden.py](../../tests/test_label_golden.py), [test_versioning.py](../../tests/test_versioning.py).

| Mã | Phải làm được / phải đạt | Ngưỡng | Hiện tại |
|---|---|---|---|
| VE-1 | Hàm thuần: không LLM, không đọc ghi kho (import-linter) | 0 phụ thuộc | Đạt (test) |
| VE-2 | Cùng bằng chứng cho cùng nhãn, không phụ thuộc thứ tự bằng chứng | 100% (kiểm bằng Hypothesis) | Đạt (test) |
| VE-3 | Hành vi chạy thực tế ưu tiên hơn đọc mã; khi nghi ngờ thì không kết luận (UNVERIFIABLE) | 100% | Đạt (test) |
| VE-4 | Sửa một quy tắc luôn đổi `rules_version` | 100% | Đạt (test) |
| VE-5 | Báo cáo độ đủ trả đúng: nhãn tạm, còn thiếu gì, mâu thuẫn, làm được hay không | 100% | Đạt (test) |
| VE-6 | Không đổi nhãn khi thêm quy tắc mà không có chủ ý (bộ nhãn vàng) | 0 thay đổi ngoài ý muốn | Đạt (test) |

## Evidence store

Mã: [store.py](../../src/rfcv/evidence/store.py). Test: [test_evidence_store.py](../../tests/test_evidence_store.py), [test_generality.py](../../tests/test_generality.py).

| Mã | Phải làm được / phải đạt | Ngưỡng | Hiện tại |
|---|---|---|---|
| ES-1 | Chỉ ghi thêm; sửa hay xoá bị chặn | 0 sửa được | Đạt (test) |
| ES-2 | Chuỗi hash phát hiện mọi sửa đổi sau khi ghi | 100% | Đạt (test) |
| ES-3 | Chỉ thành phần tất định (producer khai báo) được ghi loại bằng chứng của nó; agent không ghi | 0 ngoại lệ | Đạt (test) |
| ES-4 | Chuỗi hash của lần chạy thật còn nguyên sau khi chạy | 100% | Đạt (mô phỏng) |

## LLM gateway

Mã: [llm_gateway.py](../../src/rfcv/core/llm_gateway.py), [runner.py](../../src/rfcv/runtime/pydantic_ai/runner.py). Test: [test_agent_runtime.py](../../tests/test_agent_runtime.py).

| Mã | Phải làm được / phải đạt | Ngưỡng | Hiện tại |
|---|---|---|---|
| LG-1 | Khoá API chỉ đọc từ biến môi trường và chỉ trong gateway; không có trong hash cấu hình | 0 rò | Đạt (test); quét trace và bằng chứng chưa có ([QS-07](tieu_chuan_he_thong.md#tầng-a-an-toàn-bất-biến-0-vi-phạm)) |
| LG-2 | Khai báo mô hình một lần, gán cho agent ở mục riêng; agent chưa được gán bị từ chối lúc khởi động | 100% | Đạt (test) |
| LG-3 | Lỗi nhà cung cấp (hết hạn mức, lỗi HTTP, sai định dạng) thành lỗi vai trò có trace, không làm sập lượt chạy | 100% | Đạt (test) |
| LG-4 | Token đã tiêu trước khi hỏng vẫn tính vào ngân sách | 100% | Đạt (test) |
| LG-5 | Cấu hình khớp mô hình thật: id mô hình đúng và tham số hợp lệ (ví dụ tắt thinking của DeepSeek) | Gọi thật thành công | Đạt (đã thử `deepseek-flash`) |

## Adapter checker

Mã: [checker.py](../../src/rfcv/adapters/checker.py). Tài liệu: [mục 12 của thiết kế adapter](../design/thiet_ke_adapter_kiem_thu.md#12-adapter-checker).

| Mã | Phải làm được / phải đạt | Ngưỡng | Hiện tại |
|---|---|---|---|
| AC-1 | Kiểm hình thức adapter: bản kê, từ vựng, công thức SUT | 100% mẫu sai bị từ chối | Đạt (test) |
| AC-2 | Oracle ổn định: mỗi ca chạy 3 lần trên bản tham chiếu cho cùng kết quả | 100% ca còn lại | Chưa chạy (cần sandbox) |
| AC-3 | Oracle phân biệt được: mỗi mẫu FAIL trên ít nhất một phiên bản lỗi trong `known_bugs.yaml`; mẫu "luôn PASS" bị loại | 100% mẫu | Chưa chạy; `known_bugs.yaml` mới 1/5 lỗi |
| AC-4 | Biến thể đối chứng `at_limit` PASS trên bản tham chiếu | 100% | Chưa chạy |

## Skills và trace

| Mã | Phải làm được / phải đạt | Ngưỡng | Hiện tại |
|---|---|---|---|
| SK-1 | Skill chỉ là văn bản: cấm `scripts/`, `allowed-tools`, symlink; workspace chỉ đọc, không chạy lệnh | 0 vi phạm | Đạt (test, [test_skills.py](../../tests/test_skills.py)) cho `scripts/`, `allowed-tools`, workspace chỉ đọc; **chưa có test cho symlink** |
| SK-2 | Mỗi agent chỉ thấy skill nó khai báo, lọc tất định theo kiểu nhiệm vụ | 100% | Đạt (test) |
| SK-3 | Skill thực sự giúp ích (so có và không có skill) | Có số đo A/B | Chưa đo ([CT-06](../management/theo_doi_cai_thien.md#ct-06--p2--chưa-biết-skill-có-giúp-ích-không)) |
| TR-1 | Mọi kết luận truy được về lý do dừng, kế hoạch, đầu ra agent và hội thoại khi hỏng, bằng `rfcv trace` | 100% | Đạt (test) |
| TR-2 | Chỉ số đo lấy từ trace phải đúng (không ghi sai số liệu) | Đối chiếu với hội thoại thô | Đã sửa một lỗi (`skills_loaded` luôn rỗng, [R-11](../management/theo_doi_cai_thien.md#đã-xử-lý)); cần kiểm lại các chỉ số khác khi có số lạ |

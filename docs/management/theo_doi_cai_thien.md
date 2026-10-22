# Theo dõi cải thiện hệ thống

Sổ này ghi các vấn đề tìm thấy khi thử hệ thống, bằng chứng, hướng sửa và **cách biết đã sửa xong**, để sau này không gặp lại
cùng một vấn đề và để cải thiện có số đo. Cập nhật sau mỗi lần thử hoặc sửa. Ngày ghi theo dạng năm-tháng-ngày.

> Việc cần làm để gỡ các vấn đề dưới đây nằm ở [backlog công việc](theo_doi_backlog.md); mỗi vấn đề `CT-nn` đang mở có ít nhất một việc `BL-nn` (test kiểm).

## Quy tắc

1. **Một vấn đề chỉ đóng khi có số đo.** Ghi lệnh đã chạy và kết quả vào mục "Đóng khi". Sửa xong mà chưa đo thì để trạng thái
   "Đã sửa, chưa đo".
2. **Đo bằng cùng một phép thử** (mục dưới) để so sánh được giữa các lần. Đổi prompt, skill, cấu hình mô hình, ngân sách hay
   mô hình đều phải đo lại và thêm một dòng vào Nhật ký đo.
3. **Đừng tin chỉ số chưa kiểm chứng.** Số liệu sai từng dẫn tới kết luận sai ở đây (xem R-11). Khi một chỉ số cho kết quả
   lạ, đối chiếu với hội thoại thô trong trace trước khi kết luận.
4. Vấn đề đã xử lý chuyển xuống mục "Đã xử lý" kèm bài học, không xoá.

## Cách đo

```
uv run python scripts/e2e_live.py faulty     # bản gửi sai cảnh báo, kỳ vọng VIOLATION (V2)
uv run python scripts/e2e_live.py correct    # bản đúng, kỳ vọng COMPLIANT (V5, LINKED)
uv run python scripts/analyze_run.py runs/e2e-faulty runs/e2e-correct          # số đo; thêm --json để lưu
uv run rfcv trace runs/e2e-faulty                                              # xem lại luồng xử lý
uv run pytest -q ; uv run lint-imports ; uv run pyright ; uv run ruff check src tests agents
```

Phép thử dùng LLM thật theo `config/models.yaml` (khoá đọc từ môi trường hoặc `.env`). Phần giả: SUT và backend kiểm thử
(bộ mô phỏng `rfcv.eval`) và chỉ mục mã (một tệp C nhỏ). Nên nó đo **cơ chế phối hợp**, không đo độ chính xác trên mã thật.
Mỗi cấu hình nên chạy mỗi ca **ít nhất 3 lần** vì kết quả của LLM thay đổi giữa các lần.

## Nhật ký đo

| # | Ngày | Cấu hình | Ca | Nhãn | Vòng | Giây | Token | Lãng phí* | Worker hỏng lần đầu | Nạp skill (nạp lại) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-10-22 | deepseek-flash cho mọi agent, thinking tắt, mọi vấn đề đang mở | faulty | VIOLATION V2 | 2 | 30 | 252.611 | 53% | 2/4 | 12 (4) |
| 1 | 2026-10-22 | như trên | correct | COMPLIANT V5 LINKED | 3 | 26 | 209.715 | 6% | 1/4 | 12 (3) |
| 2 | 2026-10-22 | #1 + prompt "nạp skill một lần" (BL-10), `llm_calls` Code Reader 20 (BL-11), gộp T3 thường trong `evidence.summary` (BL-12); 3 lần mỗi ca | faulty | VIOLATION V2 (3/3) | 1 | 9-13 | 75.679 / 95.007 / 96.553 | 0% | 0/2 (3 lần) | 3 (0) |
| 2 | 2026-10-22 | như trên | correct | COMPLIANT V5 (3/3) | 2 / 2 / 7 | 18 / 26 / 128 | 170.996 / 270.201 / 1.184.441 | 0% / 0% / 14% | 0/3, 0/3, **1/8** | 5 (0) mỗi lần |
| 3 | 2026-10-22 | #2 + sổ tay phản biện lại sau khi vấn đề được xử lý (R2/R3-recritique-after-fix); 5 lần | correct | COMPLIANT (5/5: V5 x4, V6 x1) | 2 (5/5) | 22-33 | 182.218 / 196.336 / 253.887 / 291.734 / 303.415 | 0-1 lần hỏng | 0/3 x4, **1/3** | 0 nạp lại |

\* Lãng phí = token tiêu trong các lần chạy agent bị hỏng, chia tổng token. Mỗi ca mới chạy **một lần**, chưa đủ để nói về
độ ổn định. Khi thêm dòng, ghi thêm thay đổi so với lần trước vào cột Cấu hình.
Dòng 2 (BL-10/11/12): `skill_reloads` = 0 ở cả 6 lần (trước: 3-4 lần nạp lại mỗi ca). Faulty ổn định: 1 vòng, 76-97k token (trước 252k). Verifier nhận
khoảng 41k token (trước 55k) ở ca correct. Lần correct thứ 3 là ngoại lệ: Code Reader chạy 6 lần, 127 lời gọi công cụ, một lần dính
`UsageLimitExceeded` dù `llm_calls` đã 20, dừng bằng ngân sách sau 7 vòng với 1,18 triệu token. Vậy tiêu chí của BL-11 chưa đạt và
`worker_first_failures` của BL-10 chưa về 0 ở ca correct, nhưng nguyên nhân không còn là nạp skill: Planner giao LOCATE lặp lại nhiều
vòng. Verifier_smoke vẫn nêu đúng cả hai tình huống (MISSING_EVIDENCE, CONTRADICTION), nhưng nó dùng hàng tóm tắt dựng tay nên không kiểm phần
gộp T3; phần gộp được kiểm bằng `tests/test_summary_fold.py`. Chưa rõ mức giảm 55k → 41k do việc gộp hay do ca có ít T3 hơn.

Dòng 3: lần correct tệ nhất trước đó (1,18 triệu token) do **lặp TRACE_PATHS**, không phải LOCATE: Verifier nêu MISSING_PATH một lần, sổ tay cứ làm theo phản biện cũ nên Planner giao
TRACE_PATHS 4 vòng liền mà không phản biện lại. Đã sửa trong `advisor.py` (vấn đề đã được nhiệm vụ đề xuất xử lý thì coi là `stale`, gợi ý phản biện lại). Kết quả: cả 5 lần
dừng ở vòng 2, tối đa 303k token. Còn một lần (correct-4) Code Reader vẫn dính `UsageLimitExceeded` dù `llm_calls` = 20, và vì thế nhãn cuối là V6 (BEHAVIORAL) thay vì V5
(LINKED): lỗi này làm yếu mức bảo đảm chứ không đổi nhãn. Nên BL-11 và `worker_first_failures` của BL-10 vẫn chưa đạt; cần quyết định tăng `llm_calls` hay rút gọn việc Code Reader làm.

## Vấn đề đang mở

Mức: **P0** chặn đánh giá thật, **P1** ảnh hưởng độ tin cậy hoặc tính đúng, **P2** chi phí hoặc chất lượng, **P3** dọn dẹp.

### CT-01 · P1 · Test và agent khác nạp lại skill đã nạp rồi hỏng
- **Bằng chứng:** Test hỏng lần đầu ở cả hai ca (`Tool 'load_capability' exceeded max retries count of 2`): nạp
  `write-tlsfuzzer-scenarios` xong lại gọi `load_capability` thêm 3 lần, mỗi lần nhận "already active". Lần sau không nạp
  lại và chạy ngay. Có lần mô hình đưa tên công cụ (`test__list_examples`) vào làm id skill. Tổng 4 và 3 lần nạp lại mỗi ca.
- **Hậu quả:** mất một vòng, khoảng 12k token mỗi lần, kế hoạch bị lệch. Với Code Reader thì thêm vào việc cạn ngân sách (CT-02).
- **Hướng sửa:** (a) thêm vào prompt: nạp mỗi skill tối đa một lần, sau khi nạp thì làm theo và trả kết quả, id skill chỉ lấy
  trong danh mục skill; (b) nếu (a) không đủ, nhúng thẳng nội dung các skill ngắn vào prompt thay vì nạp dần; (c) tăng giới
  hạn thử lại của công cụ nạp skill.
- **Đóng khi:** `skill_reloads = 0` và `worker_first_failures = 0` trên cả hai ca, mỗi ca ít nhất 3 lần.

### CT-02 · P1 · Hạn mức `llm_calls` của Code Reader quá chặt
- **Bằng chứng:** lần LOCATE đầu của ca faulty dừng bằng `UsageLimitExceeded` (request_limit 12) sau 15 lời gọi công cụ, tiêu
  **121.869 token** và không ra kết quả. Lần sau xong với 79.791 token và 12 lời gọi công cụ. Hai lượt gọi LLM bị tiêu vào nạp skill.
- **Hướng sửa:** nâng `llm_calls` của `code_reader` trong `agents/code_reader/role.yaml` (thử 20). Tài liệu ghi đây là giá trị
  khởi điểm cần hiệu chỉnh.
- **Đóng khi:** không còn `UsageLimitExceeded` ở Code Reader qua ít nhất 3 lần chạy mỗi ca, và token mỗi ca không tăng.

### CT-03 · P2 · `evidence.summary` phình theo số bằng chứng T3
- **Bằng chứng:** Verifier nhận 55.229 token đầu vào, Planner 30.915 ở vòng cuối, vì tóm tắt liệt kê từng dòng T3 (khoảng 60 dòng).
  Tăng tuyến tính theo số biến thể.
- **Hướng sửa:** gộp T3 theo biến thể và kết quả; giữ chi tiết cho ca FAIL, mâu thuẫn hoặc được trích trong nhãn. Sửa ở
  `summarize_evidence` ([context_builder.py](../../backend/src/rfcv/core/context_builder.py)) và các hàm tóm tắt trong `payloads.py`.
  Phải giữ các trường mà skill Verifier dựa vào (`alert`, `variant_class`, `outcome`, `linked`).
- **Đóng khi:** token đầu vào của Verifier giảm rõ rệt (ghi số) mà Verifier vẫn nêu đúng 2 kịch bản thử trong
  `verifier_smoke` (MISSING_EVIDENCE và CONTRADICTION).

### CT-04 · P3 · Chỉ số "bám sổ tay" khắt khe với kế hoạch là tập cha
- **Bằng chứng:** ca faulty vòng 2, sổ tay gợi ý `SELECT_TESTS`, Planner giao `SELECT_TESTS` + `LOCATE` (cả hai cùng thiếu sau khi
  hỏng) nên bị ghi `deviated_unannounced`. Kế hoạch hợp lý nhưng bị tính là chệch.
- **Hướng sửa:** trong `adherence` ([advisor.py](../../backend/src/rfcv/core/advisor.py)) coi kế hoạch chứa đủ nhiệm vụ được gợi ý là `followed`,
  và ghi riêng `followed_plus` nếu muốn phân biệt.
- **Đóng khi:** test cho ca tập cha; ca faulty hiện tại không còn bị tính là chệch.
- **Kết quả (BL-13):** `adherence` coi kế hoạch chứa đủ nhiệm vụ được gợi ý là `followed` (có test ca tập cha và hai ca đối chứng). Ca faulty thật chỉ xác nhận lại khi đo ở đợt BL-10/11/12.

### CT-05 · P1 · Agent không thấy câu RFC
- **Bằng chứng:** `rfc.sentence`, `rfc.paragraph`, `rfc.context_pack` nằm trong `KNOWN_UNSUPPLIED`
  ([test_coordination_contracts.py](../../backend/tests/test_coordination_contracts.py)), vì RFC Analyst chưa nối và hệ đọc thẳng file `*.rbs`.
  Code Reader và Verifier chỉ thấy RBS có cấu trúc. Phép kiểm "every/all" của skill Verifier cần câu RFC nên chưa chạy được.
- **Hướng sửa:** tối thiểu, lấy câu RFC theo trường nguồn của RBS (`RFC8446§5.2#p4s3`) qua RFC gate và cấp vào ngữ cảnh. Đầy đủ
  là nối RFC Analyst (CT-12).
- **Đóng khi:** `KNOWN_UNSUPPLIED` không còn các trường `rfc.*` đã cấp, và Verifier thấy câu RFC trong ngữ cảnh.
- **Kết quả (BL-20):** đã cấp `rfc.sentence`, `rfc.paragraph`, `rfc.context_pack` theo `sentence_id` của RBS (`RfcDocument.lookup` trong `rfc_gate.py`), nhãn TRUSTED, đọc từ `inputs/rfc/rfc<số>.xml` (`--rfc-dir`). Test: `test_rfc_context.py`, `test_rfc_gate.py`. Mới chạy trên bản trích rút gọn; **chưa thử trên toàn văn RFC 8446** (BL-21), và cấu trúc thật có thể lệch (đoạn nằm trong `<dl>` có `pn` dạng `section-5.2-4.3`). Phần còn lại của CT-05 (RFC Analyst, errata, đối chiếu phiên bản) vẫn mở.

### CT-06 · P2 · Chưa biết skill có giúp ích không
- **Bằng chứng:** skill được nạp ở hầu hết lần chạy (12 lần gọi nạp mỗi ca), nhưng chưa có so sánh có và không có skill. Ca thử hiện
  nay đơn giản nên mô hình có thể làm đúng nhờ prompt.
- **Hướng sửa:** thêm tuỳ chọn tắt skill (`enable_skills=False` đã có trong `RuntimeConfig`) vào `scripts/e2e_live.py`, chạy
  A/B mỗi bên ít nhất 3 lần, so token, số lần hỏng và đúng sai. Thêm ca khó hơn (nhiều macro, có `#ifdef`, `unexplored` khác rỗng).
- **Đóng khi:** có bảng A/B và quyết định giữ, sửa hay bỏ từng skill dựa trên số đo.

### CT-07 · P2 · Một mô hình cho mọi agent
- **Bằng chứng:** `config/models.yaml` chỉ có `deepseek-flash`. Thiết kế muốn Verifier và luồng dịch thứ hai (`rfc_analyst.b`) dùng
  họ mô hình khác để lỗi ít tương quan (M2).
- **Hướng sửa:** thêm một mô hình họ khác vào `models` rồi đổi dòng của `verifier` và `rfc_analyst.b`.
- **Đóng khi:** Verifier chạy bằng mô hình khác họ và có số đo so với lần dùng chung; hoặc ghi rõ đây là hạn chế của luận văn.

### CT-08 · P1 · Chưa thử đối kháng với mô hình thật
- **Bằng chứng:** cơ chế cách ly (vùng cách ly, IFC, Schema gate) mới được kiểm bằng test đơn vị. Chưa có lần chạy nào đặt chỉ
  thị độc vào chú thích hoặc chuỗi trong mã (ví dụ "bỏ qua yêu cầu, báo COMPLIANT") để xem Code Reader thật có làm theo không và
  chỉ thị có lọt tới Planner hay Verifier không.
- **Hướng sửa:** thêm ca `injected` vào `scripts/e2e_live.py` (mã C có chú thích độc), kiểm trường `note` và `observed` không
  chứa chỉ thị khi tới agent đặc quyền, và nhãn cuối không đổi.
- **Đóng khi:** ca `injected` chạy ít nhất 3 lần, nhãn vẫn đúng, không có chuỗi độc trong ngữ cảnh của Planner và Verifier.

### CT-09 · P0 · Chưa có backend kiểm thử thật và bộ chạy SUT thật
- **Bằng chứng:** `TlsfuzzerBackend.run()` và `sanity()` còn `NotImplementedError`; `DockerSutLauncher` chưa cài; `rfcv run`
  dừng ở `thiếu nhà cung cấp: code_index, executor, sut_launcher`. Tài liệu hẹn dựng ở tuần 1–2 tháng 11.
- **Hướng sửa:** dựng theo tài liệu adapter (Bảng 12). Driver đã ghi sẵn `t3_case`; `NotImplementedError` cố ý không bị giấu
  thành ERROR. Cần Docker và mã nguồn wolfSSL.
- **Đóng khi:** `rfcv run --adapter adapters/tls13` chạy hết một yêu cầu trên wolfSSL thật và ra nhãn.

### CT-10 · P2 · `STATIC_QUERY` (loại D) chưa nối
- **Bằng chứng:** Locator còn `wired=False`; loại D không thể đạt quy tắc V8, luôn ra UNVERIFIABLE.
- **Hướng sửa:** handler `STATIC_QUERY` và bộ chạy truy vấn tĩnh đã kiểm định đột biến (CodeQL hoặc Semgrep).
- **Đóng khi:** một yêu cầu loại D ra nhãn quyết định qua V8.

### CT-11 · P3 · Report chưa nối
- **Bằng chứng:** có hồ sơ, lời nhắc và `Explanation@1`, chưa có Output gate và chưa ai gọi sau khi có nhãn.
- **Đóng khi:** mỗi yêu cầu có bản giải thích chỉ trích bằng chứng đã có, qua Output gate.

### CT-12 · P2 · RFC Analyst chưa nối; loại C, D thiếu mẫu và skill
- **Bằng chứng:** `rfc_analyst` còn `wired=False`; adapter chưa có mẫu kịch bản loại C; chưa có skill cho ORDER_STATE (loại C)
  và EFFECT (loại D).
- **Đóng khi:** luồng hai bản dịch và reconcile chạy; có ít nhất một yêu cầu loại C đạt nhãn quyết định.

### CT-13 · P3 · Skill chỉ có cho C và TLS
- **Bằng chứng:** ràng buộc C4 yêu cầu chạy trên C, Rust và Go; các skill hiện có chỉ cho C (macro, `#ifdef`, con trỏ hàm).
- **Đóng khi:** có skill tương đương cho Rust hoặc Go khi có adapter cho ngôn ngữ đó, hoặc ghi vào hạn chế.

### CT-14 · P3 · Nợ kiểm tra tĩnh
- **Bằng chứng:** pyright còn 16 lỗi (`assembly.py`, `code_gate.py`, `runtime.py`, `cli.py`, `agents/locator/service.py`,
  `builder.py`, `execution_loop.py`), ruff 2 lỗi (`builder.py`, `test_codeindex.py`), khoảng 10 file chưa định dạng. Không rõ có từ
  trước hay không vì thư mục này chưa có git khả dụng để so.
- **Đóng khi:** `pyright`, `ruff check` và `ruff format --check` đều sạch, đúng như CI yêu cầu.

### CT-15 · P3 · `rfcv` không tự nạp `.env`
- **Bằng chứng:** phải đặt biến vào môi trường trước khi chạy; `rfcv models` báo "CHƯA đặt" dù khoá có trong `.env`.
  `scripts/e2e_live.py` đã tự nạp.
- **Đóng khi:** quyết định có thêm `python-dotenv` cho CLI hay giữ như hiện tại (và ghi rõ trong README).
- **Quyết định (BL-92):** giữ như hiện tại, không thêm `python-dotenv`: khoá chỉ đi qua biến môi trường, đúng nguyên tắc "chỉ đọc trong
  LLM gateway". README ghi cách đặt biến; `rfcv models` báo "CHƯA đặt trong môi trường" kèm lời nhắc CLI không tự nạp `.env`
  (có test `tests/test_cli_models.py`). Đã đóng.

### CT-16 · P1 · Chưa có số đo thống kê
- **Bằng chứng:** mỗi ca mới chạy một lần, một yêu cầu. Chưa có các chỉ số ở Bảng 13 của tài liệu phối hợp agent (độ chính xác
  định vị T1, hiệu quả của Verifier, số vòng, độ ổn định giữa các lần).
- **Hướng sửa:** chạy mỗi ca nhiều lần; mở rộng lên khoảng 10 yêu cầu khi có backend thật (CT-09).
- **Đóng khi:** có bảng Bảng 13 với số liệu và khoảng biến thiên.

### CT-17 · P2 · Code Reader chiếm khoảng 80% token
- **Bằng chứng:** 209.479 trên 252.611 token ở ca faulty (gồm cả lần hỏng), 79.791 trên 209.715 ở ca correct.
- **Hướng sửa:** xem sau khi sửa CT-01 và CT-02; cân nhắc rút gọn đầu ra công cụ đọc mã hoặc dừng sớm khi các khía cạnh đã đủ.
- **Đóng khi:** token Code Reader mỗi ca giảm có số đo mà độ chính xác T1 không đổi.

### CT-18 · P3 · `MAP_COMPONENTS` đã có handler nhưng chưa thử với LLM thật
- **Bằng chứng:** `agents/code_indexer/handler.py` đã có và agent được đánh dấu nối; sổ tay vòng 1 chưa có quy tắc dùng nó; skill
  Verifier đang dặn không nêu `WRONG_LOCATION` vì từng chưa có bản đồ thành phần.
- **Đóng khi:** chạy thử `MAP_COMPONENTS` với LLM thật, rồi quyết định cập nhật sổ tay và skill Verifier.

### CT-19 · P3 · Tên chưa thống nhất ở vài chỗ
Quy ước đã ghi ở [quy_uoc_dat_ten.md](../conventions/quy_uoc_dat_ten.md) và có test giữ ([test_naming.py](../../backend/tests/test_naming.py)). Còn các chỗ
lệch dưới đây chưa sửa vì ảnh hưởng rộng hơn; mỗi mục làm riêng, kèm chạy `pytest` và kiểm liên kết.
- **Hai gói tên `agents`:** gói ngoài `agents/` (mã và dữ liệu từng agent) và gói lõi `src/rfcv/agents/` (schema kế hoạch,
  phản biện). Dễ nhầm, và tên `agents` ở mức cao nhất có thể va chạm với thư viện khác cùng tên (ví dụ OpenAI Agents SDK).
  Hướng sửa: đổi gói ngoài thành `rfc_agents/` (khoảng 25 import, `find_agents_root`, test, tài liệu), hoặc đổi gói lõi thành
  `src/rfcv/plans/`. Hatch buộc tên gói trùng tên thư mục nên không đổi tên chỉ trong cấu hình được.
- **`eval/`, `scripts/`, `src/rfcv/eval/`:** ba nơi cùng chủ đề đo lường. `eval/` là dữ liệu và script dựng tập thử, `scripts/` là
  phép đo hệ thống, `src/rfcv/eval/` là mã chấm. Hướng sửa: gộp `eval/scripts/` vào `scripts/` (tên có tiền tố `eval_`), hoặc đổi
  `eval/` thành `datasets/`.
- **Tên file test:** `test_agents_layout.py`, `test_agents_root.py` (số nhiều) và `test_agent_runtime.py` (số ít); `test_misc.py`
  gom nhiều chủ đề (registry, adapter, CLI, SARIF, thống kê, tlsfuzzer). Hướng sửa: thống nhất số nhiều, tách `test_misc.py`
  theo chủ đề.
- **Thư mục `docs/html/`:** bản HTML gốc để đối chiếu; xoá khi đã duyệt xong bản Markdown (test `test_naming` sẽ vẫn đạt).
- **Đóng khi:** từng mục được sửa hoặc quyết định giữ nguyên (ghi lý do vào quy ước), `pytest` và kiểm liên kết đều sạch.
- **Kết quả (BL-91):** (1) hai gói `agents`: **giữ nguyên có chủ đích**. Đổi tên gói ngoài kéo theo khoảng 22 tệp import, đường dẫn dữ liệu `role.yaml`,
  cấu hình import-linter, CI và hơn 40 liên kết tài liệu, trong khi nguy cơ va chạm chỉ xảy ra nếu cài thư viện có gói `agents` (hiện không có). Thay vào đó có
  `test_the_top_level_agents_package_is_ours_not_a_library_of_the_same_name` báo ngay khi bị che; đổi tên khi thêm một thư viện như vậy. (2) `eval/scripts/` đã gộp
  vào `scripts/` với tiền tố `eval_` (`eval_prepare.ps1`, `eval_collect_wolfssl_commits.py`, `eval_make_manifest.py`); `eval/` còn lại chỉ là dữ liệu và cấu hình, mã chấm vẫn ở `src/rfcv/eval/`.
  (3) `test_misc.py` đã tách theo chủ đề (`test_requirement_registry.py`, `test_adapter_checker.py`, `test_cli.py`, `test_sarif.py`, `test_eval_metrics.py`,
  `test_tlsfuzzer_backend.py`). Giữ `test_agents_layout.py` và `test_agents_root.py` (số nhiều: kiểm thư mục `agents/`) khác với `test_agent_runtime.py` (số ít: runtime của
  một agent), vì tên theo đúng đối tượng được kiểm. (4) `docs/html/` giữ lại để đối chiếu với bản Markdown; xoá khi bạn duyệt xong, không cần sửa test.

### CT-20 · P1 · Ngưỡng chất lượng chưa thống nhất giữa các tài liệu thiết kế
- **Bằng chứng:** Bảng 8 (thiết kế đánh giá) và Bảng 13 (đánh giá khả thi) đặt tỉ lệ COMPLIANT sai 0 (tối đa 5%) và precision VIOLATION ≥ 80%.
  Bảng 30 (mục tiêu đăng ký trước, thiết kế chính) đặt ≤ 2% và ≥ 95%, và có thêm các chỉ số không có ở bảng kia (độ phủ quyết định cao hơn
  B2 có ý nghĩa thống kê, công người ≤ 20% so với thủ công). Bảng 30 ghi các ngưỡng này sẽ đăng ký vào luận văn trước G3, nên mâu thuẫn phải được
  giải trước đó.
- **Hướng sửa:** thầy chốt một bộ ngưỡng. Sửa Bảng 8 và Bảng 13 trỏ về Bảng 30, hoặc định nghĩa rõ hai mức "tối thiểu" và "mục tiêu".
  Cập nhật [tieu_chuan_he_thong.md](../quality/tieu_chuan_he_thong.md) cho khớp.
- **Đóng khi:** ba tài liệu cùng một bộ ngưỡng (hoặc hai mức được định nghĩa rõ) và tiêu chuẩn hệ thống không còn cảnh báo.

### CT-21 · P3 · Một số bất biến chưa có kiểm thử riêng
- **Bằng chứng:** khi lập [tiêu chuẩn chất lượng](../quality/tieu_chuan_thanh_phan_tat_dinh.md) thấy các mục chưa có test: vòng làm lại khi Schema gate
  từ chối (SG-6); không lộ chi tiết chính sách khi từ chối công cụ (TG-4); ngân sách thời gian `seconds` (EL-7); skill chứa symlink bị từ chối (SK-1);
  quét trace và bằng chứng không chứa khoá API (QS-07); phát hiện `evidence_id` bịa trong `Critique` (VF-6).
- **Hướng sửa:** viết test cho từng mục; rẻ vì dùng mô hình giả và đồng hồ giả.
- **Đóng khi:** sáu mục đều có test và tiêu chuẩn tương ứng đổi sang "Đạt (test)".
- **Kết quả (BL-61):** đã đóng. 14 test trong `backend/tests/test_invariants.py`. VF-6 cần thêm một đoạn nhỏ ở vòng điều phối (ghi `unknown_evidence_ids`
  vào `critique_result`) vì trước đó chưa có chỗ nào phát hiện mã bịa. QS-07 mới kiểm trên lần chạy giả; quét tự động sau mỗi lần chạy thật là BL-62.

### CT-22 · P1 · Phạm vi hỗ trợ RFC chưa chốt
- **Bằng chứng:** nhu cầu thực tế là "hỗ trợ mọi RFC cần lọc và không bỏ sót đoạn mã triển khai sai RFC" ([yêu cầu đầu ra](../quality/tieu_chuan_dau_ra.md)).
  Thiết kế chỉ cam kết TLS 1.3 làm sâu và DNS (tầng 1); QUIC, HTTP/2, SSH nếu còn thời gian. RFC gate chỉ đọc RFCXML v3; RFC cũ chỉ có bản TXT (DNS, SSH)
  cần bộ phân tích riêng, chưa cài. Chưa có bảng phạm vi công bố mức hỗ trợ từng giao thức.
- **Hướng sửa:** thầy chốt danh sách RFC và giao thức trong phạm vi, kèm mức hỗ trợ (đầy đủ, mức chứng minh, chưa hỗ trợ). Cài bộ phân tích TXT hoặc chọn RFC
  có bản XML. Đưa bảng phạm vi vào báo cáo.
- **Đóng khi:** bảng phạm vi được chốt và có trong báo cáo; RFC gate tách đúng câu trên mọi RFC trong phạm vi (đo trên 30 câu mỗi giao thức).

### CT-23 · P1 · RFC 8446 không có bản XML chính thức; RBS mẫu trỏ vào câu của RFC 8446
- **Bằng chứng:** `https://www.rfc-editor.org/rfc/rfc8446.xml` trả 404; RFC Editor chỉ có `.txt` và `.html` cho RFC 8446, còn RFC 9846 có `.xml`
  (RFCXML v3). Thiết kế ([thiết kế cung cấp RFC](../design/thiet_ke_cung_cap_rfc.md), mục 2.2) coi XML là nguồn ưu tiên và adapter TLS 1.3 chọn RFC 8446 làm
  đặc tả chính. Ngoài ra, định danh trong RBS mẫu (`RFC8446§5.2#p4s3`, TLS13-0042) không có nghĩa trên RFC 9846: câu tương ứng nằm ở `RFC9846§5.2#p3.12.1s2`.
- **Hướng sửa:** quyết định cùng thầy (BL-25, BL-26): (a) dùng RFC 9846 làm đặc tả chính và đối chiếu ngược về 8446; (b) viết bộ phân tích
  bản HTML hay TXT của RFC 8446; (c) giữ 8446 với bản XML của draft cuối (không phải bản chính thức). Dù chọn gì, phải ánh xạ lại `sentence_id` của các RBS.
- **Đóng khi:** adapter TLS 1.3 chỉ định một nguồn RFC có XML (hay bộ phân tích tương ứng) và mọi `sentence_id` trong ví dụ RBS tra được ra câu (`RfcDocument.lookup`).
- **Đã xử lý trong BL-21:** RFC gate từng bỏ sót đoạn lồng trong danh sách (66/243 đoạn quy phạm ở thân văn bản) và toàn bộ phụ lục (53/511 từ khoá), và làm
  mất chữ của `<xref>` ("see ." thay vì "see Section 4.7.1") cùng lũy thừa (`2^14` thành `214`, đúng ngưỡng của TLS13-0042). Đã sửa: định danh đoạn lồng dạng
  `#p3.12.1s2`, đọc cả `<back>`, và `render_text` hiển thị đúng xref và lũy thừa.
## Đã xử lý

| ID | Vấn đề | Nguyên nhân gốc | Đã sửa ở | Bài học |
|---|---|---|---|---|
| R-01 | Mọi lần gọi agent thật sập ngay: `Agent() got an unexpected keyword argument 'output_retries'` | `pydantic-ai 2.59.0` đổi sang `retries={'tools':…, 'output':…}` | [runner.py](../../backend/src/rfcv/runtime/pydantic_ai/runner.py) | Test dùng mô hình giả vẫn bắt được vì dựng `Agent` thật; chạy `pytest` sau mỗi lần nâng phiên bản |
| R-02 | Planner hỏng cả 8 vòng với 400 "Thinking mode does not support this tool_choice" | `deepseek-flash` mặc định bật thinking | [models.yaml](../../backend/config/models.yaml): `extra_body: {thinking: {type: disabled}}` | `thinking: false` chung của pydantic-ai **không** dịch sang tham số DeepSeek; dùng `extra_body`. Xem `llm_failure` trong trace |
| R-03 | Test agent thấy T1, trái Bảng 11 | `role.yaml` của Test khai báo `evidence.summary` | `verdict.missing` mới; bỏ `evidence.summary` khỏi Test | Ngữ cảnh mỗi agent phải khớp bảng trong tài liệu và có test kiểm |
| R-04 | Code Reader không thấy từ vựng adapter nên dễ bị cổng từ chối `observed` | thiếu `adapter.vocabulary` | [code_reader/role.yaml](../../backend/agents/code_reader/role.yaml) | Cổng từ chối vẫn xảy ra thi thoảng (thấy 1 lần), mô hình tự sửa được |
| R-05 | `Critique.kind` là chuỗi tự do nên viết sai mã làm sổ tay bỏ qua vấn đề không báo lỗi | schema không ép enum | `build_critique_model` trong [agents/schemas.py](../../backend/src/rfcv/agents/schemas.py) | Đầu ra của LLM phải ép bằng schema đóng |
| R-06 | Hai skill dẫn tới trường không tồn tại; báo cáo độ đủ thiếu `feasible` | skill viết trước khi ngữ cảnh chốt | skill Planner và Test; `report_json` | Mỗi trường skill nhắc tới phải có trong `context_fields` |
| R-07 | Trace thiếu nội dung phản biện, chi tiết lý do dừng, so sánh sổ tay, hội thoại khi hỏng; token không tính khi lỗi; `ModelAPIError` làm sập lượt chạy; lỗi môi trường làm sập driver | chưa ghi, chưa bắt | `requirement_start`, `round_start`, `plan_context`, `critique_result`, `role_run`, `stop`, `llm_failure`, `t3_case`; lệnh `rfcv trace` | Quan sát phải có trước khi cần; trace đã chỉ ra R-02 trong vài giây |
| R-08 | Khai báo khoá API riêng cho từng agent | cấu hình theo vai trò | `models` + `agents` trong [models.yaml](../../backend/config/models.yaml) | Khai báo mô hình một lần; đổi agent là đổi một dòng; `rfcv models` để xem |
| R-09 | Skill tự chọn agent dùng nó (`rfcv-roles`) nên nhìn `agents/` không thấy agent có skill nào | khai báo ở sai phía | `skills:` trong `role.yaml`; `rfcv-roles` bị từ chối | Agent khai báo cái nó dùng |
| R-10 | Mã agent tách khỏi dữ liệu agent, trùng tên thư mục | cấu trúc | `agents/<tên>/` chứa cả `role.yaml`, `prompt.md` và mã | Mỗi agent một thư mục |
| R-11 | Chỉ số `skills_loaded` luôn rỗng khi chạy thật, dẫn tới kết luận sai "skill không được nạp" | tham số lời gọi công cụ là **chuỗi JSON** với nhà cung cấp thật, code chỉ chấp nhận `dict` | `_tool_args` trong [runner.py](../../backend/src/rfcv/runtime/pydantic_ai/runner.py); `analyze_run.py` tính lại từ hội thoại | Test dùng mô hình giả cho dạng `dict`, không phản ánh nhà cung cấp thật. Trace chạy trước 2026-10-22 có `skills_loaded` sai |

## Hạn chế đã biết (cho phần hạn chế của luận văn)

- Phép thử đầu-cuối dùng SUT, backend kiểm thử và mã nguồn **giả**; chưa có kết quả trên wolfSSL thật (CT-09).
- Mọi agent dùng một mô hình, nên Verifier và luồng dịch thứ hai chưa độc lập về họ mô hình (CT-07).
- Chưa kiểm tra đối kháng bằng mô hình thật (CT-08); chưa có số đo thống kê (CT-16).
- Agent không thấy câu RFC gốc (CT-05); loại C và D, Report và RFC Analyst chưa nối đầy đủ (CT-10, CT-11, CT-12).

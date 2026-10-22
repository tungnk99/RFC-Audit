# rfcv: framework kiểm chứng tuân thủ đặc tả dựa trên bằng chứng, nhiều agent, an toàn trước đối thủ

Mã nguồn cho luận văn *"Kiểm chứng tự động và an toàn sự tuân thủ đặc tả giao thức mạng dựa trên bằng chứng, sử dụng hệ thống AI đa tác tử"* (Nguyễn Kỳ Tùng, GVHD TS. Tống Văn Vạn). Thiết kế: [docs/design/thiet_ke_chi_tiet_he_thong.md](../docs/design/thiet_ke_chi_tiet_he_thong.md). Toàn bộ tài liệu thiết kế, đánh giá và theo dõi cải thiện: [docs/README.md](../docs/README.md).

Nguyên tắc: **agent đề xuất, thành phần tất định kiểm chứng.** LLM chỉ đề xuất. Một đề xuất chỉ thành bằng chứng sau khi qua bộ kiểm chứng không dùng LLM, và nhãn do Verdict engine gán theo một bộ quy tắc cố định, có phiên bản là hash nội dung.

Lõi **không biết RFC, TLS hay bất kỳ miền nào**. Tri thức đặc thù đi vào qua *domain pack* và plugin; miền đầu tiên (kiểm chứng RFC của giao thức mạng) chỉ là một pack.

## Cài đặt và chạy

```bash
uv python install 3.12 && uv sync

uv run pytest -q                       # hơn 460 kiểm thử, không gọi LLM thật
uv run ruff check src tests
uv run pyright                         # kiểu, strict
uv run lint-imports                    # 6 hợp đồng kiến trúc = ranh giới quyền

uv run rfcv plugins                    # những gì đã đăng ký vào lõi
uv run rfcv agents                     # bản đồ agent: thư mục, vùng tin cậy, nhiệm vụ nhận, đã nối vào luồng chạy chưa
uv run rfcv adapter check adapters/tls13
uv run rfcv skills check skills --adapter tls13
uv run rfcv rbs check adapters/tls13/examples/TLS13-0042.rbs --adapter adapters/tls13
uv run rfcv run --adapter adapters/tls13     # lắp ráp runtime; báo rõ thành phần còn thiếu; sau lần chạy quét rò rỉ khoá API và tệp ngoài phạm vi (leak_scan.json, thoát mã 3 nếu có); đặt RFCXML v3 vào inputs/rfc/rfc8446.xml (hay --rfc-dir) để agent thấy câu RFC gốc
uv run rfcv verify runs/<run_id>
uv run python scripts/e2e_live.py faulty        # thử cả vòng điều tra với LLM thật (SUT và mã giả); đo cải thiện, xem bên dưới
uv run python scripts/analyze_run.py runs/e2e-faulty
uv run rfcv trace runs/<run_id> -r TLS13-0042   # xem lại luồng xử lý: giao việc, bằng chứng, vì sao dừng (--json để phân tích)
uv run rfcv serve --env-file .env               # GIAO DIỆN WEB (http://127.0.0.1:8765): chạy, xem agent trực tiếp, duyệt và phản hồi, soạn thảo có kiểm soát; --read-only để chỉ xem, --no-auth để tắt đăng nhập (mặc định có đăng nhập, vai trò admin/member); xem ../frontend/README.md
uv run rfcv users add <tên> --role admin         # tạo tài khoản bằng CLI (hoặc dùng mã thiết lập lần đầu in ra khi serve); list|passwd|role|disable|enable|remove
```

**Tiêu chuẩn chất lượng:** hệ thống phải đạt gì và từng thành phần phải làm được gì nằm ở [docs/quality/](../docs/quality/tieu_chuan_he_thong.md).

**Theo dõi cải thiện:** vấn đề đã biết, bằng chứng, cách đo và cách biết đã sửa xong nằm ở [docs/management/theo_doi_cai_thien.md](../docs/management/theo_doi_cai_thien.md). Đổi prompt, skill, cấu hình hay mô hình thì chạy lại phép thử và ghi một dòng vào Nhật ký đo ở đó.

Khoá API chỉ đọc từ biến môi trường (tên biến khai báo cho từng mô hình, ví dụ `DEEPSEEK_API_KEY`) và chỉ trong LLM gateway; `rfcv` không tự nạp `.env`, hãy đặt biến vào môi trường trước khi chạy (PowerShell: `$env:DEEPSEEK_API_KEY = "..."`; bash: `export DEEPSEEK_API_KEY=...`). Đây là quyết định có chủ đích (CT-15): khoá không đi qua tệp nào mà CLI tự đọc. Cấu hình mô hình: [config/models.yaml](config/models.yaml), gồm hai phần: `models` (kho mô hình hỗ trợ, khai báo một lần kèm biến chứa khoá) và `agents` (agent nào dùng mô hình nào). Xem bằng `uv run rfcv models`.

## Kiến trúc

```
src/rfcv/
  spi.py              hợp đồng cho plugin và domain pack (EvidenceKind, TaskDefinition, ToolDescriptor, DomainPack…)
  plugins.py          Registry: nơi duy nhất mọi mở rộng đăng ký; đóng băng sau khi nạp; entry points rfcv.*
  assembly.py         composition root: build_runtime(config, providers) -> Runtime
  manifest.py         bản kê lần chạy: hash mọi đầu vào ảnh hưởng kết luận
  builtin.py          thành phần có sẵn, đăng ký bằng đúng API công khai

  core/               Execution loop (hub), Context builder, IFC, Policy, LLM gateway, Trace, ngân sách, skills
  gates/              Tool gateway, Code gate (+ explore_policy), Schema gate (tổng quát)
  evidence/           Evidence store (chuỗi hash), Verdict engine (RuleSet), registry yêu cầu, repository Protocols
  agents/             schema tổng quát: PlanAction, Critique, Explanation (PlanAction dựng từ nhiệm vụ đã đăng ký)
  adapters/           bản kê adapter + Adapter checker (phần chung)
  runtime/pydantic_ai/  duy nhất nơi được nhập PydanticAI: runner, mô hình, skills
  ui/                 CLI, SARIF
  api/                API HTTP + SSE cho giao diện web (`rfcv serve`): danh mục, chạy nền, đọc trace; FastAPI + uvicorn
  testing/            bộ kiểm thử hợp đồng cho người viết plugin

  domains/rfc_protocol/   domain pack: loại bằng chứng T1–T3, quy tắc V0–V9, RBS + Oracle compiler, cổng RFC,
                          Test driver, Coverage linker, lệnh `rfcv rbs|rfc`
    agents/<tên>/         MÃ của mỗi agent: schema.py (đầu ra), handler.py (đầu ra → cổng → bằng chứng), __init__.py (SPEC:
                          vùng tin cậy, nhiệm vụ nhận, đã nối chưa); planner/playbook.py là sổ tay điều tra
                          rfc_analyst planner test verifier report code_indexer code_reader + locator (tất định)
  backends/tlsfuzzer/     plugin backend
agents/<tên>/ (ở gốc repo)   DỮ LIỆU của mỗi agent, ngoài mã nguồn: role.yaml (hồ sơ) + prompt.md (lời nhắc)
adapters/tls13/   skills/   agents/   config/   docker/   docs/   scripts/   tests/
```

Chiều phụ thuộc: `domains`, `backends`, `runtime` phụ thuộc lõi, **không ngược lại** (import-linter ép).

## Mở rộng mà không sửa lõi

| Muốn thêm | Làm gì | Nhóm entry point |
|---|---|---|
| Một miền mới (chính sách, API, chuẩn an ninh…) | viết `DomainPack`: loại bằng chứng, nhiệm vụ, bộ quy tắc, vai trò, lời nhắc | `rfcv.domains` |
| Bộ quy tắc kết luận | `RuleSet` thuần, ví dụ `rfc-protocol@3`; `version` = hash nội dung | `rfcv.rule_sets` |
| Backend, chỉ mục mã, bộ chạy lệnh/SUT | factory `(manifest, config) -> đối tượng` | `rfcv.backends`, `rfcv.code_indexes`, `rfcv.executors`, `rfcv.sut_launchers` |
| Nhà cung cấp LLM | factory `(ModelSpec, api_key) -> handle` | `rfcv.llm_providers` |
| Runtime agent khác PydanticAI | factory trả `RoleRunner` | `rfcv.agent_runtimes` |
| Công cụ cho agent | `ToolDescriptor` kèm tác động | `rfcv.tool_packs` |
| Skill | thư mục `SKILL.md` (chuẩn agentskills.io) | thư mục `skills/` |

Ranh giới an toàn **không nới** khi mở rộng:
- Registry từ chối công cụ có tác động ngoài đọc và chạy-trong-sandbox (`write`, `network`, `host_exec`) trừ khi người vận hành cho phép tường minh.
- `ToolGateway.register` chỉ nhận công cụ đã có khai báo; agent đặc quyền không bao giờ có công cụ `reads_untrusted`.
- Loại bằng chứng khai báo ai được ghi (`producers`); agent không bao giờ nằm trong danh sách đó.
- Registry đóng băng: không đăng ký thêm lúc chạy.

Người viết plugin chạy lại `rfcv.testing.check_rule_set_contract`, `check_code_index_contract`, và `rfcv.domains.rfc_protocol.testing.check_backend_contract` trên cài đặt của mình.

Phép thử tổng quát: [tests/toy_domain.py](tests/toy_domain.py) là một miền hoàn toàn khác (kiểm chứng chính sách nội bộ), chạy trọn vòng điều tra trong [tests/test_generality.py](tests/test_generality.py) mà không sửa một dòng lõi.

## Công nghệ

| Tầng | Lựa chọn |
|---|---|
| Agent runtime | `pydantic-ai-slim` **2.59.0** (cố định), cô lập trong `rfcv.runtime.pydantic_ai`; chỉ dùng `Agent` + `output_type` + tool tự định nghĩa + `UsageLimits` |
| Skills | chuẩn agentskills.io qua `pydantic-ai-harness[skills]` **0.59.0** |
| Mô hình | Claude làm chính; luồng RBS thứ hai và Verifier dùng họ khác (Qwen, DeepSeek) qua API tương thích OpenAI |
| Lưu trữ | SQLite chỉ-ghi-thêm (trigger), chuỗi hash JCS (RFC 8785); `schema_version`, `kind_schema` và nâng cấp dữ liệu cũ khi đọc; một kho một tenant |
| Kiểm thử T3 | tlsfuzzer + tlslite-ng (TLS); dnspython + genreport (DNS) |
| Chất lượng | pytest + Hypothesis, pyright strict, ruff, import-linter, GitHub Actions |

## Bất biến được ép bằng mã và kiểm thử

| Bất biến | Nơi ép | Kiểm thử |
|---|---|---|
| Nhãn chỉ do bộ quy tắc gán; cùng bằng chứng cho cùng nhãn, không phụ thuộc thứ tự | `evidence/verdict_engine.py`, `domains/rfc_protocol/rules.py` | `test_verdict_engine.py`, `test_contracts.py` (Hypothesis) |
| Sửa một quy tắc luôn đổi `rules_version` | `RuleSet.version` = hash nội dung | `test_versioning.py` |
| Bằng chứng chỉ ghi thêm, sửa đổi bị phát hiện | trigger SQLite + chuỗi hash | `test_evidence_store.py` |
| Chỉ thành phần tất định được ghi loại bằng chứng của nó | `EvidenceKind.producers` | `test_generality.py` |
| Agent đặc quyền không có công cụ đọc dữ liệu không tin cậy | `core/policy.py` + `reads_untrusted` | `test_policy_ifc.py` |
| Chuỗi UNTRUSTED tự do không vào ngữ cảnh agent đặc quyền | `core/ifc.py`, `core/context_builder.py` | `test_policy_ifc.py` |
| Từ chối mặc định mọi lời gọi công cụ; công cụ phải có khai báo | `gates/tool_gateway.py` | `test_gates.py`, `test_assembly.py` |
| Công cụ nguy hiểm không đăng ký được (cả từ plugin bên thứ ba) | `plugins.py` | `test_plugins.py` |
| `explore` chỉ chạy lệnh đọc trong danh sách, không qua shell | `gates/explore_policy.py` | `test_gates.py` |
| T1 chỉ ghi khi vị trí có thật, dòng đã hiển thị, dòng được biên dịch | `domains/rfc_protocol/schema_gate.py` | `test_gates.py` |
| ERROR (sanity hỏng, chưa tới trigger) không thành FAIL | `domains/rfc_protocol/sandbox/driver.py` | `test_driver_and_coverage.py` |
| Agent nói T1 mâu thuẫn T3 thì không kết luận | quy tắc V7 | `test_assembly.py` |
| Skill chỉ là văn bản (cấm `scripts/`, `allowed-tools`), workspace chỉ đọc | `core/skills.py`, `runtime/pydantic_ai/skills.py` | `test_skills.py` |
| Lõi không biết miền; chỉ `runtime/pydantic_ai` nhập PydanticAI | import-linter | CI |

## Trạng thái

| Thành phần | Trạng thái |
|---|---|
| Lõi, registry, composition root, bản kê lần chạy, phiên bản hoá dữ liệu | ✅ cài đặt và kiểm thử |
| Domain pack `rfc_protocol` (bằng chứng, V0–V9, RBS, oracle, Schema gate, Test driver, Coverage linker, handler) | ✅ với đối tượng giả |
| Ca K3 chạy trọn luồng qua `build_runtime`, LLM thay bằng kịch bản | ✅ ra VIOLATION (V2) |
| Miền thứ hai làm phép thử tổng quát | ✅ |
| Chạy với LLM thật (DeepSeek `deepseek-flash`; SUT, backend kiểm thử và mã nguồn **giả**) | ✅ đã thử đầu-cuối 2026-10-22: bản lỗi ra `VIOLATION` (V2), bản đúng ra `COMPLIANT` (V5, LINKED). Còn vấn đề về độ tin cậy và chi phí, xem [sổ theo dõi](../docs/management/theo_doi_cai_thien.md) |
| **Chạy trên bản triển khai thật (wolfSSL)** | ⏳ chưa: thiếu backend kiểm thử thật và bộ chạy SUT. Chưa có số liệu thực nghiệm nào |
| Chỉ mục mã tree-sitter → SQLite (C, Rust, Go), bản sao phạm vi tại commit, bộ chạy lệnh trong container, `locator.suggest`, MAP_COMPONENTS | ✅ cài đặt (`rfcv.codeindex`); ⏳ chưa chạy trên wolfSSL thật |
| `DockerSutLauncher`, `TlsfuzzerBackend.run/sanity` | ⏳ |
| Output gate, agent Report, bộ dựng báo cáo (`ui/report.py`: JSON, HTML, SARIF) | ✅ cài đặt và kiểm thử (`test_output_gate.py`, `test_report.py`) |
| Handler STATIC_QUERY; RFC Analyst hai luồng | ⏳ |
| CLI `specs`, `status`, `rerun`, `review`, `report` | ⏳ (trả mã 2; `report` chưa nối vào `ui/report.py`) |
| Giao diện web (`rfcv serve`, `frontend/`): chọn giao thức RFC và yêu cầu, chọn mã nguồn, theo dõi agent trực tiếp (SSE), hội thoại LLM, bằng chứng gắn vào dòng mã, trình duyệt mã, **vòng phản hồi của Reviewer (BR3, ghi vào kho `reviews`)**, **soạn thảo có kiểm soát** RBS/prompt/skill/mô hình qua cổng kiểm tra của lõi, lịch sử, phát lại | ✅ cài đặt và kiểm thử (`tests/test_api.py`); chế độ *mã thật* chờ bộ chạy SUT (⏳ bên trên); có đăng nhập và vai trò admin/member (`tests/test_auth.py`) |
| Lớp dịch vụ: hàng đợi bền, Postgres, đa tenant, OpenTelemetry, secrets provider | ⏳ đã chừa chỗ (Protocol repository, `tenant`, `TraceSink`) |

### Nối agent với mã nguồn (tài liệu khám phá mã)

```bash
# 1. image sandbox (một lần)
docker build -f docker/code-index-worker.Dockerfile --target indexer -t rfcv/code-indexer:latest .
docker build -f docker/code-index-worker.Dockerfile --target worker  -t rfcv/code-index-worker:latest .
# 2. kho mã SUT tại đúng commit (đặt sut.commit trong adapter.yaml để harness từ chối commit khác)
git clone https://github.com/wolfSSL/wolfssl ../wolfssl && git -C ../wolfssl checkout <commit>
# 3. chạy: sao phần code_scope → dựng chỉ mục trong container → công cụ đọc mã chạy trong container
rfcv run --adapter adapters/tls13 --code-root ../wolfssl --code-index treesitter --executor docker ...
# xem đúng danh mục công cụ (khuôn MCP tools/list) mà một agent nhận
rfcv code tools --role code_reader
```

Khi phát triển không có Docker: `pip install -e '.[codeindex]'`, `--code-index treesitter-local`, và
`RFCV_ALLOW_UNSANDBOXED_EXECUTOR=1 … --executor local-unsandboxed` (chạy lệnh trên máy, không thoả Bảng 6).

Mốc G1 (cuối tháng 11): ca K3 trọn luồng với wolfSSL và LLM thật. Thứ tự làm: backend + bộ chạy SUT → chỉ mục tree-sitter → chạy thử với LLM thật.

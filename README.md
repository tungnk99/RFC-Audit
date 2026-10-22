# rfcv: framework kiểm chứng tuân thủ đặc tả dựa trên bằng chứng, nhiều agent, an toàn trước đối thủ

Mã nguồn cho luận văn *"Kiểm chứng tự động và an toàn sự tuân thủ đặc tả giao thức mạng dựa trên bằng chứng, sử dụng hệ thống AI đa tác tử"* (Nguyễn Kỳ Tùng, GVHD TS. Tống Văn Vạn). Thiết kế: [documents/thiet_ke_chi_tiet_he_thong_final.html](documents/thiet_ke_chi_tiet_he_thong_final.html).

Nguyên tắc: **agent đề xuất, thành phần tất định kiểm chứng.** LLM chỉ đề xuất. Một đề xuất chỉ thành bằng chứng sau khi qua bộ kiểm chứng không dùng LLM, và nhãn do Verdict engine gán theo một bộ quy tắc cố định, có phiên bản là hash nội dung.

Lõi **không biết RFC, TLS hay bất kỳ miền nào**. Tri thức đặc thù đi vào qua *domain pack* và plugin; miền đầu tiên (kiểm chứng RFC của giao thức mạng) chỉ là một pack.

## Cài đặt và chạy

```bash
uv python install 3.12 && uv sync

uv run pytest -q                       # gần 300 kiểm thử, không gọi LLM thật
uv run ruff check src tests
uv run pyright                         # kiểu, strict
uv run lint-imports                    # 6 hợp đồng kiến trúc = ranh giới quyền

uv run rfcv plugins                    # những gì đã đăng ký vào lõi
uv run rfcv agents                     # bản đồ agent: thư mục, vùng tin cậy, nhiệm vụ nhận, đã nối vào luồng chạy chưa
uv run rfcv adapter check adapters/tls13
uv run rfcv skills check skills --adapter tls13
uv run rfcv rbs check adapters/tls13/examples/TLS13-0042.rbs --adapter adapters/tls13
uv run rfcv run --adapter adapters/tls13     # lắp ráp runtime; báo rõ thành phần còn thiếu
uv run rfcv verify runs/<run_id>
```

Khoá API chỉ đọc từ biến môi trường (`ANTHROPIC_API_KEY`, `DASHSCOPE_API_KEY`, `DEEPSEEK_API_KEY`) và chỉ trong LLM gateway. Mô hình theo vai trò: [config/models.yaml](config/models.yaml).

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
  testing/            bộ kiểm thử hợp đồng cho người viết plugin

  domains/rfc_protocol/   domain pack: loại bằng chứng T1–T3, quy tắc V0–V9, RBS + Oracle compiler, cổng RFC,
                          Test driver, Coverage linker, lệnh `rfcv rbs|rfc`
    agents/<tên>/         MÃ của mỗi agent: schema.py (đầu ra), handler.py (đầu ra → cổng → bằng chứng), __init__.py (SPEC:
                          vùng tin cậy, nhiệm vụ nhận, đã nối chưa); planner/playbook.py là sổ tay điều tra
                          rfc_analyst planner test verifier report code_indexer code_reader + locator (tất định)
  backends/tlsfuzzer/     plugin backend
agents/<tên>/ (ở gốc repo)   DỮ LIỆU của mỗi agent, ngoài mã nguồn: role.yaml (hồ sơ) + prompt.md (lời nhắc)
adapters/tls13/   skills/   agents/   config/   docker/   tests/
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
| **Chạy với LLM thật** | ⏳ chưa lần nào; schema Planner dựng động chưa kiểm với API thật |
| Chỉ mục mã tree-sitter → SQLite, bộ chạy lệnh trong container | ⏳ đã có Protocol `CodeIndex` / `SandboxExecutor` |
| `DockerSutLauncher`, `TlsfuzzerBackend.run/sanity` | ⏳ |
| Handler STATIC_QUERY, MAP_COMPONENTS; RFC Analyst hai luồng; Report/Output gate | ⏳ |
| CLI `specs`, `status`, `rerun`, `review`, `report` | ⏳ (trả mã 2) |
| Lớp dịch vụ: API, hàng đợi, Postgres, đa tenant, OpenTelemetry, secrets provider | ⏳ đã chừa chỗ (Protocol repository, `tenant`, `TraceSink`) |

Mốc G1 (cuối tháng 11): ca K3 trọn luồng với wolfSSL và LLM thật. Thứ tự làm: backend + bộ chạy SUT → chỉ mục tree-sitter → chạy thử với LLM thật.

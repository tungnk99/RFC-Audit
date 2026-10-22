# RFC-Audit

**Evidence-based, adversary-safe conformance checking of network-protocol implementations against their RFCs, using a multi-agent AI system.**

*Kiểm chứng tự động và an toàn sự tuân thủ đặc tả giao thức mạng (RFC) dựa trên bằng chứng, dùng hệ thống AI đa tác tử.* Master's thesis project by Nguyễn Kỳ Tùng (supervisor: Dr. Tống Văn Vạn). Documentation is written in Vietnamese; this page is the English entry point.

> **Project status: research prototype.** The full investigation loop runs end to end with real LLMs, but on a *simulated* system under test. Measurements on real implementations (wolfSSL) have **not** been made yet. See [Status](#status) for the exact boundary.

## The problem

An RFC says, for example, *"if a TLS record exceeds 2^14 + 256 bytes the receiver MUST send `record_overflow` and close the connection"* (RFC 8446 §5.2). Checking that a specific implementation, say wolfSSL, really does this means finding the code, writing a test that reaches it, and judging the result. LLM agents can do each step, but they hallucinate, and the source code they read is attacker-controlled input.

## The idea: agents propose, deterministic components verify

```
RFC ─► RFC gate / RFC Analyst ─► reviewed behaviour spec (RBS) ─► compiled oracle
                                                                       │
      ┌──────────────────  Execution loop (hub)  ◄────────────────────┘
      │  Planner picks a task ─► Code Reader / Test / Verifier / Code Indexer
      │                                   │  every output crosses a deterministic gate
      │                                   ▼
      │             Schema gate · Tool gateway · Test driver ─► Evidence store (append-only, hash-chained)
      │                                                               │
      └──── sufficiency report ◄──────────  Verdict engine (rules V0–V9) ◄──┘
                                              │
                                              ▼
                                  final verdict + cited evidence
```

- **LLMs only propose** code locations, test scenarios and critiques. A proposal becomes evidence only after a non-LLM checker accepts it.
- **Verdicts come from a fixed, versioned rule set** (the version is a content hash). No agent can decide a label.
- **Agents never call each other.** Every hand-off is a typed task routed through the hub, which stops on sufficient evidence, exhausted budget or detected looping.
- **Untrusted code is quarantined.** The agent that reads source code is isolated; privileged agents (Planner, Verifier) never see free-form strings from it, only finite-domain values or values cross-checked against the code index.
- **When in doubt, do not conclude.** Failures end in `UNVERIFIABLE` or `NEEDS_REVIEW` with a reason, never in a silent pass.

| Verdict | Meaning |
|---|---|
| `VIOLATION` | Real-run evidence (T3) or validated static analysis (T2) shows a violation |
| `COMPLIANT` | Sufficient compliance evidence plus one clean adversarial critique, with an assurance level (`LINKED`, `BEHAVIORAL`, `STATIC`) |
| `NEEDS_REVIEW` | Contradictory or suspicious evidence, a human must look |
| `UNVERIFIABLE` | Not enough evidence within budget |

Evidence tiers: **T1** code location cross-checked against the index, **T2** static-analysis result, **T3** test run on the implementation (with positive and negative witnesses). Requirements fall into four classes (A–D: outgoing data constraints, reaction to bad input, message order/state, internal behaviour) which determine the evidence needed.

## Highlights

- **Domain-agnostic core.** The core knows nothing about RFCs or TLS. Protocol knowledge arrives through *domain packs*, *adapters* and plugins. A toy policy-checking domain runs the full loop without touching a line of core ([`test_generality.py`](backend/tests/test_generality.py)), and new protocols (DNS, HTTP/2, QUIC, SSH) are declared without core changes ([`test_new_protocol_zero_core_change.py`](backend/tests/test_new_protocol_zero_core_change.py)).
- **Architecture enforced by tooling.** Six `import-linter` contracts encode the trust boundaries; `pyright` runs in strict mode; invariants (append-only evidence, order-independent verdicts, deny-by-default tools, no untrusted strings in privileged context) each have a dedicated test.
- **Seven agents plus a deterministic locator**, each with its own role file, prompt and declared skills ([`backend/agents/`](backend/agents/)). Skills follow the [agentskills.io](https://agentskills.io) format and are text-only: no scripts, read-only workspace.
- **Reproducible runs.** Each run writes a manifest hashing every input that can influence a verdict, a hash-chained SQLite evidence store, and a full trace you can replay (`rfcv trace`) or verify (`rfcv verify`).
- **Web UI.** Live agent graph, LLM conversations, evidence anchored to source lines, a Git-style code browser, a human review loop that never overwrites machine labels, and guarded editing of specs, prompts and skills. HTML/CSS/JS only, no build step ([`frontend/`](frontend/)).
- **Leak scan.** After every run, traces and artifacts are scanned for API keys and for content outside the declared code scope.

## Quick start

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
cd backend
uv python install 3.12 && uv sync

uv run pytest -q                    # no real LLM calls
uv run rfcv agents                  # agent map: trust zone, tasks accepted, wired or not
uv run rfcv adapter check adapters/tls13
```

Try the full investigation loop with a real LLM (simulated SUT and code). Set the key in your environment first (the CLI deliberately never reads `.env`; keys flow only through environment variables into the LLM gateway):

```bash
export DEEPSEEK_API_KEY=...         # PowerShell: $env:DEEPSEEK_API_KEY = "..."
uv run python scripts/e2e_live.py faulty     # buggy implementation, expect VIOLATION
uv run python scripts/e2e_live.py correct    # correct implementation, expect COMPLIANT
uv run rfcv trace runs/e2e-faulty            # replay what each agent saw, did and returned
```

Launch the web UI:

```bash
uv run rfcv serve --env-file .env   # http://127.0.0.1:8765
```

More commands and the full architecture: [backend/README.md](backend/README.md).

## Repository layout

| Path | Role |
|---|---|
| [backend/](backend/) | Python engine `rfcv`: core, gates, evidence store, verdict engine, domain pack, agents, skills, adapters, API, tests, evaluation harness |
| [frontend/](frontend/) | Web UI served by `rfcv serve` ([README](frontend/README.md)) |
| [docs/](docs/) | Design, evaluation, quality standards, deliverable checklists, backlog and improvement log, in Vietnamese ([index](docs/README.md)) |

## Status

| Area | State |
|---|---|
| Core, plugin registry, composition root, run manifest, versioned data | Implemented and tested |
| `rfc_protocol` domain pack (evidence T1–T3, rules V0–V9, RBS and oracle compiler, gates, test driver, coverage linker) | Implemented, tested against simulated targets |
| Real-LLM end-to-end loop (DeepSeek, simulated SUT and code) | Works: faulty build gives `VIOLATION` (V2), correct build gives `COMPLIANT` (V5, LINKED); 6/6 labels correct in the latest measurements, cost and reliability tracked in the [improvement log](docs/05_project/improvement_log.md) |
| RFC gate for RFCXML and plain-text RFCs | Implemented; measured on DNS, SSH and HPACK RFCs |
| Adversarial checks (injection, secret leakage, suspicious-branch scan) | Unit-tested; live adversarial runs pending |
| Web UI, auth, review loop, output gate, reports | Implemented and tested |
| **Run against real implementations (wolfSSL)** | **Not yet**: needs the real test backend and Docker-based SUT launcher; no experimental results exist |
| RFC Analyst (two-stream translation), STATIC_QUERY, incremental re-verification, CI mode | Planned |

Known limitations are listed openly in the [improvement log](docs/05_project/improvement_log.md#hạn-chế-đã-biết-cho-phần-hạn-chế-của-luận-văn): single model family (DeepSeek) for now, no statistical results yet, and RFC 8446 has no official XML source.

## Documentation

Start with the [system overview](docs/01_overview/system_overview.md), then the [detailed design](docs/02_design/system_design.md). Work tracking: [backlog](docs/05_project/backlog.md) (what to do), [improvement log](docs/05_project/improvement_log.md) (what is wrong, with measurements), [deliverable checklists](docs/05_project/README.md) (what is delivered). The full index is in [docs/README.md](docs/README.md).

## Contributing

Run these before sending a change; CI runs the same:

```bash
cd backend
uv run ruff check src tests agents && uv run ruff format --check
uv run pyright
uv run lint-imports
uv run pytest -q
```

If you change a prompt, skill, model configuration or budget, re-run the measurement scripts and add a row to the measurement log in the improvement log. Naming rules: [docs/01_overview/naming_conventions.md](docs/01_overview/naming_conventions.md).

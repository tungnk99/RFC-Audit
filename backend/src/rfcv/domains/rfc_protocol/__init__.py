"""Miền kiểm chứng tuân thủ RFC của giao thức mạng (domain pack đầu tiên của rfcv).

Gói này gom mọi tri thức đặc thù: loại bằng chứng T1–T3, bộ quy tắc V0–V9, ngôn ngữ đặc tả hành vi RBS,
oracle, cổng RFC, Test driver, hồ sơ vai trò và lời nhắc. Lõi chỉ thấy nó qua `pack()` (rfcv.spi.DomainPack).
"""

from __future__ import annotations

from pathlib import Path

from rfcv.spi import DomainPack, Effect, LoopPolicy, ToolDescriptor

HERE = Path(__file__).resolve().parent
VERSION = "2.0.0"

REQUIRED_ROLES = ("rfc_analyst", "planner", "tester", "verifier", "report", "code_indexer", "code_reader")

# Công cụ của miền (công cụ đọc mã nằm ở code pack dùng chung). Không công cụ nào ghi tệp, gọi mạng hay chạy lệnh
# trên máy chủ: Registry từ chối mọi tác động ngoài đọc và chạy trong sandbox.
TOOLS = (
    ToolDescriptor("rfc.get_sentences"),
    ToolDescriptor("rfc.read_section"),
    ToolDescriptor("rfc.search"),
    ToolDescriptor("rfc.get_definition"),
    ToolDescriptor("evidence.read_summary"),
    ToolDescriptor("verdict.read"),
    ToolDescriptor("tester.list_examples"),
    ToolDescriptor("tester.run_scenario", Effect.SANDBOXED_RUN),
    ToolDescriptor("locator.suggest", Effect.READ, reads_untrusted=True),
)


def pack() -> DomainPack:
    from agents.planner import playbook
    from agents.registry import AGENTS
    from rfcv.domains.rfc_protocol import adapter_checks, cli, payloads, rules, runtime, schemas

    return DomainPack(
        name="rfc_protocol",
        version=VERSION,
        evidence_kinds=payloads.evidence_kinds(),
        schemas=schemas.DOMAIN_SCHEMAS,
        tasks=schemas.TASKS,
        rationale_codes=[c.value for c in schemas.RationaleCode],
        rule_sets=[rules.RULE_SET],
        tools=TOOLS,
        required_roles=REQUIRED_ROLES,
        agents=AGENTS,
        loop=LoopPolicy(
            planner_role="planner",
            report_role="report",
            critique_task=schemas.TaskType.CRITIQUE.value,
            deviation_code=schemas.RationaleCode.DEVIATE_PLAYBOOK.value,
        ),
        adapter_checks=[adapter_checks.check_protocol_adapter],
        cli_apps={"rbs": cli.rbs_app, "rfc": cli.rfc_app},
        runtime=runtime.ProtocolRuntime(),
        playbook=playbook.PLAYBOOK,
        critique_kinds=[k.value for k in schemas.CritiqueKind],
    )

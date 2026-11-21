"""Kiểm thử Meta-Agent Evolution Harness: Whitelist/Blacklist chống Reward Hacking và ghi Kho Tri thức."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import meta_evolve  # noqa: E402


def test_policy_allows_prompts_skills_and_aci_but_blocks_gates_and_benchmarks() -> None:
    ok, violations = meta_evolve.check_paths_policy(
        [
            "backend/agents/code_reader/prompt.md",
            "backend/skills/core/resolve-c-macro-thresholds/SKILL.md",
            "backend/src/rfcv/gates/code_tools.py",
        ]
    )
    assert ok and not violations

    # Chặn tuyệt đối sửa SchemaGate, VerdictEngine, IFC, bộ benchmark hoặc test bất biến
    for bad in (
        "backend/src/rfcv/evidence/verdict_engine.py",
        "backend/src/rfcv/domains/rfc_protocol/schema_gate.py",
        "backend/src/rfcv/core/ifc.py",
        "backend/tests/test_invariants.py",
        "backend/eval/dataset/tiered_benchmark.yaml",
        "backend/scripts/eval_score.py",
        "backend/src/rfcv/assembly.py",
    ):
        ok_bad, viols = meta_evolve.check_paths_policy([bad])
        assert not ok_bad and viols, f"Phải chặn {bad}"


def test_record_generation_persists_jsonl_and_markdown_knowledge(tmp_path: Path) -> None:
    entry = {
        "generation": 1,
        "timestamp": "2026-11-21T08:20:00Z",
        "commit": "2f9a244",
        "tier": "basic",
        "decision": "KEEP",
        "files_changed": ["backend/agents/code_reader/prompt.md"],
        "root_cause_mined": "CALL_EDGE_UNKNOWN + OBSERVED_NOT_IN_VOCABULARY",
        "hypothesis": "Bổ sung hướng dẫn xử lý mã lỗi SchemaGate vào prompt Code Reader.",
        "before_metrics": {"e2e_hard_t1": "0/3"},
        "after_metrics": {"e2e_hard_t1": "3/3"},
        "lesson_learned": "Model nhỏ cần hướng dẫn sửa lỗi tường minh theo từng mã SchemaGate.",
    }
    jsonl_p, kb_p = meta_evolve.record_generation(entry, evo_dir=tmp_path)
    loaded = json.loads(jsonl_p.read_text(encoding="utf-8").strip())
    assert loaded["generation"] == 1 and loaded["decision"] == "KEEP"
    kb_text = kb_p.read_text(encoding="utf-8")
    assert "Gen-1" in kb_text and "CALL_EDGE_UNKNOWN" in kb_text and "Model nhỏ" in kb_text

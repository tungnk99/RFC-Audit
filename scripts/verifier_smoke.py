"""Thử nhanh Verifier với LLM THẬT trên hai tình huống bằng chứng giả (xem docs/management/theo_doi_cai_thien.md, CT-03).

    uv run python scripts/verifier_smoke.py

A: nhãn tạm COMPLIANT mà không có bằng chứng mã  -> kỳ vọng MISSING_EVIDENCE đề xuất LOCATE
B: T1 nói gửi decode_error, T3 thấy record_overflow -> kỳ vọng CONTRADICTION đề xuất RECHECK
Rẻ (vài nghìn token mỗi ca). In ra vấn đề Verifier nêu, token, thời gian và skill đã nạp. Không in khoá API.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from rfcv.core.envelope import EnvelopeFactory, MessageKind  # noqa: E402
from rfcv.core.llm_gateway import LLMGateway  # noqa: E402
from rfcv.core.policy import PolicyStore  # noqa: E402
from rfcv.core.skills import default_registry  # noqa: E402
from rfcv.core.trace import TraceLog  # noqa: E402
from rfcv.gates.tool_gateway import ToolGateway, ToolSession  # noqa: E402
from rfcv.plugins import current_registry  # noqa: E402
from rfcv.runtime.pydantic_ai import PydanticAIRoleRunner  # noqa: E402
from rfcv.runtime.pydantic_ai.runner import loaded_skills  # noqa: E402

REQ = "TLS13-0042"
SENTENCE = (
    "An implementation that receives a record with plaintext length more than 2^14 + 256 octets MUST terminate "
    "the connection with a record_overflow alert."
)


def load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.is_file():
        return
    for raw in env.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            if value.strip().strip('"').strip("'"):
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def field(value: object, label: str = "TRUSTED") -> dict[str, object]:
    return {"label": label, "value": value}


def t3(ev: str, variant: str, cls: str, outcome: str, alert: str, closed: bool) -> dict[str, object]:
    return {
        "evidence_id": ev,
        "tier": "T3",
        "polarity": "SUPPORTS" if outcome == "PASS" else "REFUTES",
        "variant": variant,
        "variant_class": cls,
        "outcome": outcome,
        "trigger_reached": True,
        "consistent": True,
        "alert": alert,
        "closed": closed,
        "witness_positive": True,
        "linked": False,
    }


def t1(ev: str, reaction: str, observed: str) -> dict[str, object]:
    return {
        "evidence_id": ev,
        "tier": "T1",
        "polarity": "REFUTES" if reaction == "MISMATCH" else "SUPPORTS",
        "file": "src/internal.c",
        "symbol": "GetRecordHeader",
        "lines": [812, 816],
        "finding": "PRESENT",
        "aspects": [
            {"aspect": "CONDITION", "value": "MATCH", "observed": "TLSCiphertext.length"},
            {"aspect": "THRESHOLD", "value": "MATCH", "observed": 16640},
            {"aspect": "REACTION", "value": reaction, "observed": observed},
        ],
        "call_path": ["ProcessReply", "GetRecordHeader"],
        "unexplored_count": 0,
    }


FEASIBLE = {"T1": True, "T2": True, "T3": True}
SCENARIOS: dict[str, dict[str, Any]] = {
    "A: COMPLIANT không có T1 (kỳ vọng MISSING_EVIDENCE -> LOCATE)": {
        "evidence": [
            t3("ev-1", "at_limit", "control", "PASS", "none", False),
            t3("ev-2", "boundary:16641", "required", "PASS", "record_overflow", True),
        ],
        "sufficiency": {
            "provisional": {"label": "COMPLIANT", "rule": "V6", "evidence_ids": ["ev-1", "ev-2"]},
            "decisive": True,
            "missing": [],
            "conflicts": [],
            "feasible": FEASIBLE,
        },
    },
    "B: T1 và T3 mâu thuẫn ở REACTION (kỳ vọng CONTRADICTION -> RECHECK)": {
        "evidence": [
            t3("ev-1", "boundary:16641", "required", "PASS", "record_overflow", True),
            t1("ev-2", "MISMATCH", "send_alert(decode_error)"),
        ],
        "sufficiency": {
            "provisional": None,
            "decisive": False,
            "missing": [{"need": "T3", "variant": "max:65535", "reason": "biến thể bắt buộc chưa PASS"}],
            "conflicts": [{"kind": "T1_vs_T3", "evidence_ids": ["ev-2", "ev-1"], "aspect": "REACTION"}],
            "feasible": FEASIBLE,
        },
    },
}


async def main() -> None:
    reg = current_registry()
    trace = TraceLog(Path(tempfile.mkdtemp(prefix="rfcv-smoke-")) / "trace.db")
    policy = PolicyStore.load(None, reg)
    llm = LLMGateway.load(ROOT / "config" / "models.yaml", env=dict(os.environ))
    skills = default_registry(ROOT / "skills", "tls13")
    runner = PydanticAIRoleRunner(policy, ToolGateway(policy, trace, reg.tools), llm, trace, skills=skills)
    print("skill được cấp cho verifier (CRITIQUE):", skills.select(policy.profile("verifier").skills, "CRITIQUE"))
    for name, sc in SCENARIOS.items():
        env = EnvelopeFactory("run-smoke").make(
            requirement_id=REQ,
            from_role="execution_loop",
            to_role="verifier",
            kind=MessageKind.DISPATCH,
            round=1,
            body={"task_type": "CRITIQUE", "target_role": "verifier", "params": {}},
            budget_left={"rounds": 7},
        )
        context = {
            "requirement.structured": field({"id": REQ, "type": "B", "modal": "MUST"}),
            "rfc.sentence": field(SENTENCE),
            "evidence.summary": field(sc["evidence"], "UNTRUSTED"),
            "verdict.sufficiency": field(sc["sufficiency"], "DERIVED"),
        }
        session = ToolSession("run-smoke", "verifier", REQ, policy.profile("verifier").budget_per_task.tool_calls)
        outcome = await runner.run(env, context, session)
        print(f"\n=== {name} ===")
        print("failure:", outcome.failure, "| tokens:", outcome.tokens)
        if outcome.output is not None:
            print(json.dumps(outcome.output.model_dump(mode="json"), ensure_ascii=False, indent=1))
    print("\n--- trace ---")
    for e in trace.events():
        p = e["payload"]
        if e["kind"] == "llm_run":
            keys = ("duration_ms", "input_tokens", "output_tokens", "requests")
            print("llm_run:", {k: p[k] for k in keys}, "| skill đã nạp:", loaded_skills(p["messages"]))
        elif e["kind"] == "llm_failure":
            print("llm_failure:", {k: p[k] for k in ("error", "detail", "duration_ms", "tokens")})


if __name__ == "__main__":
    load_dotenv()
    asyncio.run(main())

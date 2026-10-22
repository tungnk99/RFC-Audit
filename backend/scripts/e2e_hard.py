"""Phép thử đầu-cuối với LLM THẬT trên thế giới giả "khó" về khía cạnh REACTION (BL-41, BL-74).

Như `e2e_live.py` nhưng mã giả để phản ứng xa phép kiểm tra: kiểm tra chỉ trả `LENGTH_ERROR`, hàm `HandleError` mới ánh xạ mã lỗi
sang cảnh báo rồi đóng kết nối (xem `rfcv.eval.hard_world`). Ba ca, mỗi ca một đáp án REACTION:

    uv run python scripts/e2e_hard.py hard-correct       # record_overflow rồi đóng        → COMPLIANT, REACTION MATCH
    uv run python scripts/e2e_hard.py hard-wrong-alert   # handshake_failure rồi đóng      → VIOLATION, REACTION MISMATCH
    uv run python scripts/e2e_hard.py hard-no-close      # record_overflow, không đóng     → VIOLATION, REACTION MISMATCH

Chấm bằng `python scripts/measure_reaction.py <thư mục lần chạy>...`. Kết quả là mô phỏng một tệp C, chỉ đo khả năng lần theo mã
lỗi của agent, không đo độ chính xác trên mã thật.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from agents.code_reader.handler import LocationHandler  # noqa: E402
from agents.tester.handler import ScenarioHandler  # noqa: E402
from agents.verifier.handler import NoopHandler  # noqa: E402
from rfcv.adapters.manifest import load_manifest  # noqa: E402
from rfcv.core.budget import RequirementBudget  # noqa: E402
from rfcv.core.execution_loop import ExecutionLoop  # noqa: E402
from rfcv.core.llm_gateway import LLMGateway  # noqa: E402
from rfcv.core.policy import PolicyStore  # noqa: E402
from rfcv.core.skills import default_registry  # noqa: E402
from rfcv.core.trace import TraceLog  # noqa: E402
from rfcv.domains.rfc_protocol.adapter_view import vocabulary_terms  # noqa: E402
from rfcv.domains.rfc_protocol.runtime import ProtocolRuntime  # noqa: E402
from rfcv.domains.rfc_protocol.sandbox.driver import TestDriver  # noqa: E402
from rfcv.domains.rfc_protocol.schema_gate import SchemaGate  # noqa: E402
from rfcv.eval.demo_providers import NoExec  # noqa: E402
from rfcv.eval.faults import references  # noqa: E402
from rfcv.eval.hard_world import HARD_CASES, WORLDS, HardBackend, HardCase, hard_index, sim_impl  # noqa: E402
from rfcv.eval.sim import SimLauncher  # noqa: E402
from rfcv.evidence.artifacts import ArtifactStore  # noqa: E402
from rfcv.evidence.store import EvidenceStore  # noqa: E402
from rfcv.gates.code_gate import build_code_tools  # noqa: E402
from rfcv.gates.explore_policy import CodeScope  # noqa: E402
from rfcv.gates.tool_gateway import ToolGateway  # noqa: E402
from rfcv.plugins import current_registry, use_registry  # noqa: E402
from rfcv.runtime.pydantic_ai import PydanticAIRoleRunner  # noqa: E402


def load_dotenv() -> None:
    """Nạp .env ở gốc repo cho biến chưa đặt. Không in giá trị."""
    env = ROOT / ".env"
    if not env.is_file():
        return
    for raw in env.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            if value:
                os.environ.setdefault(key.strip(), value)


async def main(case: HardCase, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    reg = current_registry()
    manifest = load_manifest(ROOT / "adapters" / "tls13")
    impl, refs, index = sim_impl(case), references(), hard_index(case)

    store = EvidenceStore(outdir / "evidence.db")
    trace = TraceLog(outdir / "trace.db")
    artifacts = ArtifactStore(outdir / "artifacts")
    policy = PolicyStore.load(None, reg, "rfc_protocol")
    llm = LLMGateway.load(ROOT / "config" / "models.yaml", env=dict(os.environ))
    llm.validate()
    skills = default_registry(ROOT / "skills", manifest.adapter)

    rt = SimpleNamespace(
        run_id="run-hard",
        manifest=manifest,
        trace=trace,
        store=store,
        artifacts=artifacts,
        seed=7,
        providers=SimpleNamespace(code_index=index),
    )
    runtime = ProtocolRuntime()
    gateway = ToolGateway(policy, trace, reg.tools)
    with tempfile.TemporaryDirectory() as tmp:
        for spec in build_code_tools(index, NoExec(), CodeScope(Path(tmp))):
            gateway.register(spec)
        for spec in runtime.tools(rt):
            gateway.register(spec)
        inv = runtime.investigations(rt, ROOT / "adapters" / "tls13" / "examples")[0]
        driver = TestDriver(
            HardBackend([impl, *refs], WORLDS[case]),
            SimLauncher(),
            store,
            artifacts,
            trace,
            sut_impl=impl.name,
            references=[r.name for r in refs],
        )
        runtime.attach_driver(driver)
        handlers = {
            "LOCATE": LocationHandler(rt, SchemaGate(index, vocabulary_terms(manifest))),
            "SELECT_TESTS": ScenarioHandler(rt, driver),
            "CRITIQUE": NoopHandler(),
        }
        handlers["TRACE_PATHS"] = handlers["RECHECK"] = handlers["LOCATE"]
        runner = PydanticAIRoleRunner(policy, gateway, llm, trace, skills=skills)
        loop = ExecutionLoop(
            run_id="run-hard",
            runner=runner,
            policy=policy,
            store=store,
            trace=trace,
            handlers=handlers,
            budget=RequirementBudget(rounds=8, tool_calls=120, tokens=1_500_000, seconds=900),
        )
        with use_registry(reg):
            verdict = await loop.investigate(inv)
    world = WORLDS[case]
    print(f"\n##### KẾT QUẢ ({case}) #####")
    print("nhãn:", verdict.label.value, f"(kỳ vọng {world.expected_label})", "| quy tắc:", verdict.rule)
    print(f"trace: {outdir}  (chấm: python scripts/measure_reaction.py {outdir})")
    store.close()


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in HARD_CASES:
        sys.exit(__doc__)
    load_dotenv()
    chosen: HardCase = sys.argv[1]  # type: ignore[assignment]
    asyncio.run(main(chosen, Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "runs" / f"e2e-{chosen}"))
